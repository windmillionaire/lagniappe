"""Draft validation and guarded publication of versioned Form definitions."""

from copy import deepcopy
import hashlib
import json
import re
from types import SimpleNamespace
from uuid import uuid4

from google.cloud import datastore
from bs4 import BeautifulSoup
from config.form_schema import normalize_form_schema as canonicalize_schema

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, MutationOperation
from lagniappe.core.definitions.file_consumers import FileConsumer, enforce_file_consumer
from lagniappe.core.definitions.identifiers import short_hash
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.database.assets import cleanup_rejected_attempt, record_attempt_asset
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.database.filter import Filter, Query
from lagniappe.core.tools.database.utility import ExactEntityState
from lagniappe.core.tools.files.html import sanitize_form_content_html
from lagniappe.core.tools.form_definitions import definition_version, _snapshot_key

CONTENT_VERSION = 1
IMAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


# @testable infrastructure
class FormDraftConflict(exceptions.ValidationError):
    """The saved Form no longer matches this draft's baseline."""


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::builder_draft
# @covered-by lagniappe/core/tools/form_drafts.py::save_form_draft
# @reason canonical digest helper owned by draft revision and receipt contracts
def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode()).hexdigest()


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_draft_schema_rejects_collisions_and_broken_conditions
# @tests tests_unit/test_004f_form_drafts.py::test_compatible_schema_preserves_representation_and_identity
# @matrix form-schema : validation identity conditions
def validate_draft_schema(schema, form_type):
    """Validate a complete draft without dropping malformed definitions."""
    if form_type not in {"page", "task"}:
        raise exceptions.ValidationError("Unknown form type.")
    canonical = canonicalize_schema(schema, form_type=form_type)
    fields = {field["id"]: field for field in canonical}
    for singleton in ("status", "signature", "bookmark"):
        if sum(field["type"] == singleton for field in canonical) > 1:
            raise exceptions.ValidationError("This field type may occur only once per Form.")
    for field in canonical:
        if form_type == "page" and field["type"] in {"html", "status", "signature", "todo"}:
            raise exceptions.ValidationError("This field type is available only on task forms.")
        if field["id"] in {"name", "description"}:
            expected = "input" if field["id"] == "name" else "textarea"
            if form_type != "page" or field["type"] != expected or (
                expected == "input" and field.get("input", "text") != "text"
            ):
                raise exceptions.ValidationError("Reserved Page field identity cannot be changed.")
        values = [option["value"] for option in field.get("options", [])]
        if len(values) != len(set(values)):
            raise exceptions.ValidationError("Option values must be unique within their field.")
        for condition in [*(field.get("visibility") or []), *(field.get("status") or [])]:
            target = fields.get(condition.get("id"))
            if target is None or target["id"] == field["id"]:
                raise exceptions.ValidationError("A condition references an unavailable field.")
            if target["type"] not in {"checkbox", "radio", "select"}:
                raise exceptions.ValidationError("Conditions require a checkbox or selection field.")
            if target["type"] == "checkbox" and not isinstance(
                condition.get("value", condition.get("checked", True)), bool
            ):
                raise exceptions.ValidationError("Checkbox conditions require a Boolean value.")
            if target["type"] in {"radio", "select"}:
                allowed = {option["value"] for option in target.get("options", [])}
                selected = condition.get("value", condition.get("checked"))
                selected = selected if isinstance(selected, list) else [selected]
                if any(value not in allowed for value in selected):
                    raise exceptions.ValidationError("A condition references an unavailable option.")
    return canonical


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::validate_compatible_schema
# @reason field representation comparison is owned by the compatibility guard
def _representation(field):
    return (
        field["type"],
        field.get("input", "text") if field["type"] == "input" else None,
        bool(field.get("multiple")) if field["type"] == "select" else None,
        field.get("location", "out") if field["type"] == "link" else None,
    )


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_compatible_schema_preserves_representation_and_identity
# @matrix form-schema : identity migration-required save-guard
def validate_compatible_schema(previous, proposed, form_type=None):
    """Block durable identity/removal/type changes until migration support ships."""
    kind = form_type or "task"
    old = canonicalize_schema(previous or [], form_type=kind)
    new = validate_draft_schema(proposed, kind)
    destinations = {field["id"]: field for field in new}
    for source in old:
        target = destinations.get(source["id"])
        if target is None or _representation(source) != _representation(target):
            raise exceptions.ValidationError(
                "Removing or replacing a saved field requires a form migration, which is not available yet."
            )
        if source["type"] in {"radio", "select"}:
            values = {option["value"] for option in target["options"]}
            if any(option["value"] not in values for option in source["options"]):
                raise exceptions.ValidationError("Removing or replacing saved options requires a form migration.")
        if source["type"] == "table":
            columns = {column["id"]: column for column in target["columns"]}
            for column in source["columns"]:
                destination = columns.get(column["id"])
                if destination is None or _representation(column) != _representation(destination):
                    raise exceptions.ValidationError("Removing or replacing saved columns requires a form migration.")
    return new


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::builder_draft
# @reason HTML field enumeration is part of the complete builder projection
def _html_ids(form):
    return {field["id"] for field in form.schema if field.get("type") == "html"}


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_builder_draft_and_staged_html_are_read_only
# @matrix forms html-field : draft baseline no-write
def builder_draft(form):
    """Return one complete read-only builder baseline, including static content."""
    html = {
        field_id: str(sanitize_form_content_html(form.get_html_field(field_id) or "", form, field_id))
        for field_id in sorted(_html_ids(form))
    }
    return {
        "name": form.name or "", "schema": deepcopy(form.schema),
        "form_type": form.form_type, "html_fields": html,
        "baseline": _digest({
            "name": form.name, "schema": form.schema, "form_type": form.form_type,
            "assets": form.assets, "version": form.version,
        }),
    }


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::resolve_form_version
# @covered-by lagniappe/core/tools/form_drafts.py::ensure_form_snapshot
# @reason persisted snapshot identity validation belongs to exact-version resolution
def _checked_snapshot(snapshot, form_key, version):
    if snapshot is None:
        return None
    if (getattr(snapshot, "entity_kind", None) != "form_history"
            or snapshot.source_form_key != form_key or snapshot.version != version
            or (str(version).startswith("fc1-") and (
                not snapshot.content_available or definition_version(snapshot) != version
            ))):
        raise exceptions.ValidationError("The saved Form definition is inconsistent and requires repair.")
    return snapshot


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_resolver_prefers_snapshot_and_does_not_invent_legacy_content
# @matrix form-schema html-field : history legacy missing-version
def resolve_form_version(form_or_key, version):
    """Resolve an exact immutable definition; never substitute newer content."""
    form = form_or_key if hasattr(form_or_key, "schema") else None
    key = form.key if form is not None else form_or_key
    if not key or not version:
        return None
    stored = _checked_snapshot(Entities.fetch_one(_snapshot_key(key, version), request=Fetch.root()), key, version)
    if stored is not None:
        return stored
    rows = Query(KINDS.history).ancestor(key).filter(
        Filter().eq("type", "form_history").eq("schema_version", version)
    ).fetch_all()
    if rows:
        histories = [_checked_snapshot(Entities.fetch_one(row, request=Fetch.root()), key, version) for row in rows]
        if any(item is None for item in histories) or len({_digest({"schema": item.schema, "type": item.form_type}) for item in histories}) != 1:
            raise exceptions.ValidationError("The saved Form version has conflicting definitions and requires repair.")
        return histories[0]
    if form is None:
        form = Entities.fetch_one(key, request=Fetch.root())
    if form is not None and form.version == version:
        # Old versions did not identify HTML. Their current bytes are not proof
        # of what a historical completion saw.
        return Entities.FORM_HISTORY.snapshot(
            form, version, content_available=False, copy_content=False,
        )
    return None


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_definition_versions_batch_shared_history_reads
# @matrix form-schema : history batch-read
def resolve_form_versions(pairs):
    """Batch immutable snapshot reads for a collection of completed records."""
    requested = {}
    for form, version in pairs:
        key = form.key if hasattr(form, "schema") else form
        if key and version:
            requested[(key, version)] = form
    snapshot_keys = {_snapshot_key(key, version): (key, version) for key, version in requested}
    snapshots = Entities.fetch(*snapshot_keys, request=Fetch.root()) if snapshot_keys else []
    resolved = {snapshot_keys[item.key]: _checked_snapshot(item, *snapshot_keys[item.key])
                for item in snapshots if item.key in snapshot_keys}
    for pair, form in requested.items():
        if pair not in resolved:
            resolved[pair] = resolve_form_version(form, pair[1])
    return resolved


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::prepare_form_publication
# @reason raw saved baseline reconstruction is owned by guarded publication
def _source_form(form):
    source = form.saved_form_state()
    if not source:
        return None
    row = datastore.Entity(key=form.key)
    row.update(source)
    return Entities.FORM(row)


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_publication_stages_immutable_history_and_guards_original_row
# @matrix forms html-field mutations : content-version history guarded-save
def prepare_form_publication(form, builder):
    """Prepare every Form writer through the same compatibility/history contract."""
    source = _source_form(form)
    if source is not None:
        if source.form_type != form.form_type:
            raise exceptions.ValidationError("A saved Form's type cannot be changed.")
        validate_compatible_schema(source.schema, form.schema, form.form_type)
        form._form_save_guard = (form.key, ExactEntityState(dict(source.db)))
    else:
        validate_draft_schema(form.schema, form.form_type)

    pending = dict(getattr(form, "_pending_html", {}) or {})
    for field_id, content in pending.items():
        if field_id not in _html_ids(form):
            raise exceptions.ValidationError("Static content must belong to a draft HTML field.")
        content = sanitize_form_content_html(content, form, field_id)
        if content:
            previous_path = (form.assets.get(field_id) or {}).get("path")
            asset = form.save_asset(content, field_id, "html", isolated=True)
            if asset and asset.path != previous_path:
                record_attempt_asset(form, asset.definition)
        else:
            # Clearing a draft removes its live reference only. Never invoke
            # HTMLAsset.delete(), which also deletes embedded images.
            form.assets.pop(field_id, None)
            form.db["assets"] = json.dumps(form.assets)

    version = definition_version(form)
    old_version = source.version if source is not None else form.version
    prepared_versions = set()
    if source is not None and old_version:
        snapshot = _checked_snapshot(Entities.fetch_one(_snapshot_key(form.key, old_version), request=Fetch.root()), form.key, old_version)
        if snapshot is None:
            snapshot = Entities.FORM_HISTORY.snapshot(
                source, old_version,
                content_available=source.db.get("form_content_version") == CONTENT_VERSION,
                on_asset=lambda definition: record_attempt_asset(form, definition),
            )
            builder.plan_standard(snapshot, reason="form-definition-history")
            prepared_versions.add(old_version)
    if source is None or version != old_version or pending:
        snapshot = _checked_snapshot(Entities.fetch_one(_snapshot_key(form.key, version), request=Fetch.root()), form.key, version)
        if snapshot is None and version not in prepared_versions:
            snapshot = Entities.FORM_HISTORY.snapshot(form, version, content_available=True,
                on_asset=lambda definition: record_attempt_asset(form, definition))
            builder.plan_standard(snapshot, reason="form-definition-snapshot")
    form.version = version
    form.db["form_content_version"] = CONTENT_VERSION
    if old_version != version:
        form._permission_sources_changed = True


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_completion_snapshot_is_exact_and_does_not_relabel_legacy_version
# @matrix task-completion form-schema : immutable-snapshot content-version
def ensure_form_snapshot(form):
    """Capture the definition seen by a new completion without changing its Form."""
    # The mutation registry itself imports Form publication preparation.
    from lagniappe.core.mutations import execute_mutation, plan_root

    source = _source_form(form)
    if source is None or getattr(form, "_pending_html", None) or source.schema != form.schema or source.assets != form.assets:
        raise exceptions.ValidationError("Save the Form draft before completing a task with it.")
    version = definition_version(form)
    existing = _checked_snapshot(Entities.fetch_one(_snapshot_key(form.key, version), request=Fetch.root()), form.key, version)
    if existing is not None:
        return existing
    expected = ExactEntityState(deepcopy(dict(form.db)))
    attempt = SimpleNamespace()
    commit_started = False
    try:
        snapshot = Entities.FORM_HISTORY.snapshot(form, version, content_available=True,
            on_asset=lambda definition: record_attempt_asset(attempt, definition))
        plan = plan_root(snapshot)
        commit_started = True
        execute_mutation(plan, guards=[(form.key, expected)])
    except exceptions.MutationConflict:
        cleanup_rejected_attempt(attempt)
        # Another completion can capture the same immutable definition first.
        existing = _checked_snapshot(Entities.fetch_one(_snapshot_key(form.key, version), request=Fetch.root()), form.key, version)
        if existing is not None:
            return existing
        raise
    except Exception:
        if not commit_started:
            cleanup_rejected_attempt(attempt)
        raise
    return snapshot


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::save_form_draft
# @reason save response projection is shared by accepted requests and their receipts
def _saved_response(form, image_urls, *, post_commit_complete=True):
    accepted = builder_draft(form)
    baseline = accepted.pop("baseline")
    return {"draft": accepted, "baseline": baseline, "image_urls": image_urls,
            "post_commit_complete": post_commit_complete}


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::save_form_draft
# @covered-by lagniappe/core/tools/form_drafts.py::copy_form_draft
# @reason exact draft image references are part of draft validation
def _validate_content(schema, html, images):
    html_ids = {field["id"] for field in schema if field["type"] == "html"}
    if not isinstance(html, dict) or set(html) != html_ids or any(not isinstance(value, str) for value in html.values()):
        raise exceptions.ValidationError("The draft must include content for every HTML field.")
    references = set()
    for field_id, content in html.items():
        for image in BeautifulSoup(content, "html.parser").find_all("img"):
            source = image.get("src", "")
            if source.startswith("draft-image:"):
                image_id = source.removeprefix("draft-image:")
                if not IMAGE_ID.fullmatch(image_id) or image_id not in images or images[image_id].get("field_id") != field_id:
                    raise exceptions.ValidationError("A draft image is missing or belongs to another field.")
                references.add(image_id)
    for image_id, image in images.items():
        if not IMAGE_ID.fullmatch(str(image_id)) or image.get("field_id") not in html_ids or image_id not in references:
            raise exceptions.ValidationError("A draft image has invalid ownership or is not referenced by its field.")


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::save_form_draft
# @covered-by lagniappe/core/tools/form_drafts.py::copy_form_draft
# @reason exact image URL replacement is owned by publication
def _rewrite_images(content, replacements):
    soup = BeautifulSoup(content, "html.parser")
    for image in soup.find_all("img"):
        source = image.get("src")
        if source in replacements:
            image["src"] = replacements[source]
    return str(soup)


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::save_form_draft
# @covered-by lagniappe/core/tools/form_drafts.py::copy_form_draft
# @reason private attempt assets are prepared only after full draft validation
def _stage_content(form, html, images):
    image_urls = {}
    for image_id, image in images.items():
        source = image["file"]() if callable(image["file"]) else image["file"]
        enforce_file_consumer(source, FileConsumer.IMAGE_FINGERPRINT)
        asset_name = f"image_{image['field_id']}_{image_id}_{uuid4().hex}"
        asset = form.save_asset(source, asset_name, "image")
        if asset is None:
            raise exceptions.ValidationError("A draft image could not be stored.")
        record_attempt_asset(form, asset.definition)
        image_urls[f"draft-image:{image_id}"] = asset.url
    for field_id, content in html.items():
        form.set_html_field(field_id, _rewrite_images(content, image_urls))
    return image_urls


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::copy_form_draft
# @reason copying source images is part of independent draft publication
def _stage_copy_content(copied, source, html, images):
    replacements = {}
    for asset_name, definition in source.assets.items():
        if definition.get("type") != "image" or not any(asset_name.startswith(f"image_{field_id}_") for field_id in html):
            continue
        asset = source.get_asset(asset_name)
        destination = f"{copied.hash}_{uuid4().hex}_{asset_name}.{asset.extension}"
        blob = storage_assets.copy_file(asset.path, asset.visibility.value, destination, "private",
            **({"source_generation": asset.generation} if asset.generation else {}))
        if not blob:
            raise exceptions.ValidationError("The Form's images could not be copied.")
        stored = deepcopy(definition)
        stored["path"] = destination
        stored.pop("visibility", None)
        if getattr(blob, "generation", None) is not None:
            stored["generation"] = str(blob.generation)
        copied.assets[asset_name] = stored
        record_attempt_asset(copied, stored)
        replacements[asset.url] = copied.get_asset(asset_name).url
    copied.db["assets"] = json.dumps(copied.assets)
    html = {field_id: _rewrite_images(content, replacements) for field_id, content in html.items()}
    return _stage_content(copied, html, images)


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_save_draft_checks_receipt_baseline_and_validation_before_uploads
# @tests tests_unit/test_004f_form_drafts.py::test_save_draft_publishes_images_once_and_retains_failed_attempt_originals
# @tests tests_unit/test_004f_form_drafts.py::test_rejected_save_cleans_only_attempt_blobs_and_ambiguous_commit_retains_them
# @matrix forms : draft save-receipt conflict publication
# @matrix html-field : upload publication
# @matrix mutations : conflict rejected-save ambiguous-commit
def save_form_draft(form, draft, baseline, save_id, actor, *, images=None, _retry=True):
    """Publish one accepted draft; retries are recognized before consuming uploads."""
    # Keep the persistence entry point out of mutation-registry initialization.
    from lagniappe.core.mutations import execute_mutation, plan_mutation

    if not isinstance(save_id, str) or not IMAGE_ID.fullmatch(save_id):
        raise exceptions.ValidationError("A valid Save request identity is required.")
    if not isinstance(draft, dict):
        raise exceptions.ValidationError("A complete Form draft is required.")
    payload_digest = _digest(draft)
    current = Entities.fetch_one(form.key, request=Fetch.direct())
    if current is None or not current.allowed(Action.EDIT, user=actor):
        raise exceptions.ValidationError("This Form is unavailable or no longer editable.")
    receipt = current.db.get("form_draft_receipt") or {}
    if isinstance(receipt, str):
        receipt = json.loads(receipt)
    if receipt.get("id") == save_id:
        if receipt.get("digest") != payload_digest:
            raise FormDraftConflict("This Save identity was already used for another draft.")
        if receipt.get("baseline") != builder_draft(current)["baseline"]:
            raise FormDraftConflict("The Form changed after this Save. Reload before reconciling your draft.")
        return _saved_response(current, receipt.get("image_urls") or {})
    if not isinstance(baseline, str) or builder_draft(current)["baseline"] != baseline:
        raise FormDraftConflict("This Form changed in another session. Your draft is preserved; reload to reconcile it.")
    if draft.get("form_type", current.form_type) != current.form_type:
        raise exceptions.ValidationError("A saved Form's type cannot be changed.")
    name = draft.get("name")
    if not isinstance(name, str) or not name.strip():
        raise exceptions.ValidationError("Please enter a Form name.")
    schema = validate_compatible_schema(current.schema, draft.get("schema"), current.form_type)
    html = draft.get("html_fields")
    images = images or {}
    _validate_content(schema, html, images)

    current.name = name.strip()
    current.set_schema(schema)
    commit_started = False
    try:
        image_urls = _stage_content(current, html, images)
        plan = plan_mutation(MutationOperation.SAVE, current, registry=Entities)
        current.db["form_draft_receipt"] = json.dumps({
            "id": save_id, "digest": payload_digest, "version": current.version,
            "baseline": builder_draft(current)["baseline"],
            "image_urls": image_urls,
        })
        commit_started = True
        outcome = execute_mutation(plan)
    except exceptions.MutationConflict:
        cleanup_rejected_attempt(current)
        if _retry:
            # Re-read permissions and unrelated metadata, or reuse an immutable
            # snapshot won by a concurrent completion. The baseline check in
            # the retried request still prevents overwriting newer draft work.
            return save_form_draft(form, draft, baseline, save_id, actor, images=images, _retry=False)
        raise FormDraftConflict("The Form changed while saving. Your draft is preserved; reload to reconcile it.")
    except Exception:
        if not commit_started:
            cleanup_rejected_attempt(current)
        raise
    return _saved_response(current, image_urls, post_commit_complete=outcome.post_commit_complete)


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_copy_draft_owns_content_and_is_idempotent_without_saving_source
# @matrix forms html-field : copy draft immutable-assets save-receipt
def copy_form_draft(source, draft, baseline, save_id, actor, *, images=None):
    """Copy the complete draft into an independent Form without saving its source."""
    # Keep the persistence entry point out of mutation-registry initialization.
    from lagniappe.core.mutations import execute_mutation, plan_mutation

    if not isinstance(save_id, str) or not IMAGE_ID.fullmatch(save_id) or not isinstance(draft, dict):
        raise exceptions.ValidationError("A complete draft and valid Copy request identity are required.")
    source = Entities.fetch_one(source.key, request=Fetch.direct())
    if source is None or not source.allowed(Action.VIEW, user=actor):
        raise exceptions.ValidationError("The source Form is unavailable.")
    identity = _digest({"source": source.urlsafe_key, "actor": str(getattr(actor, "key", None)), "id": save_id})
    key = datastore.Key(KINDS.models.value, "form-copy-" + identity,
                        project=source.key.project, namespace=source.key.namespace)
    digest = _digest(draft)
    existing = Entities.fetch_one(key, request=Fetch.direct())
    if existing is not None:
        receipt = json.loads(existing.db.get("form_draft_receipt") or "{}")
        if receipt.get("id") != save_id or receipt.get("digest") != digest or receipt.get("baseline") != builder_draft(existing)["baseline"]:
            raise FormDraftConflict("This copied Form changed after the original Copy request.")
        return {**_saved_response(existing, receipt.get("image_urls") or {}), "form_key": existing.urlsafe_key}
    if baseline != builder_draft(source)["baseline"]:
        raise FormDraftConflict("The source Form changed. Your draft is preserved; reload to reconcile it.")
    schema = validate_draft_schema(draft.get("schema"), source.form_type)
    name = draft.get("name")
    if not isinstance(name, str) or not name.strip():
        raise exceptions.ValidationError("Please enter a Form name.")
    if draft.get("form_type", source.form_type) != source.form_type:
        raise exceptions.ValidationError("A copy must keep its source Form type.")
    html = deepcopy(draft.get("html_fields"))
    images = images or {}
    _validate_content(schema, html, images)

    row = datastore.Entity(key=key)
    row.update({"type": "form", "form_type": source.form_type,
                "hash": short_hash(key.to_legacy_urlsafe().decode()), "name": "Copy of " + name.strip()})
    copied = Entities.FORM(row)
    copied._form_source_state = None
    copied._form_save_guard = (key, None)
    copied._form_additional_guards = [(source.key, ExactEntityState(deepcopy(dict(source.db))))]
    copied.set_schema(schema)
    commit_started = False
    try:
        image_urls = _stage_copy_content(copied, source, html, images)
        plan = plan_mutation(MutationOperation.SAVE, copied, registry=Entities)
        copied.db["form_draft_receipt"] = json.dumps({
            "id": save_id, "digest": digest, "version": copied.version,
            "baseline": builder_draft(copied)["baseline"], "image_urls": image_urls,
        })
        commit_started = True
        outcome = execute_mutation(plan)
    except exceptions.MutationConflict:
        cleanup_rejected_attempt(copied)
        existing = Entities.fetch_one(key, request=Fetch.direct())
        if existing is not None:
            return copy_form_draft(source, draft, baseline, save_id, actor, images=images)
        raise FormDraftConflict("The source Form changed while copying. Your draft is preserved.")
    except Exception:
        if not commit_started:
            cleanup_rejected_attempt(copied)
        raise
    return {**_saved_response(copied, image_urls, post_commit_complete=outcome.post_commit_complete),
            "form_key": copied.urlsafe_key}
