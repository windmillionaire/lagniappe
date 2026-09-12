"""Draft validation and guarded publication of versioned Form definitions."""

from copy import deepcopy
import hashlib
import json
import re
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
from lagniappe.core.properties.form import requires_submission_conversion

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


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_compatible_schema_preserves_representation_and_identity
# @matrix form-schema : identity migration-required save-guard
def validate_compatible_schema(previous, proposed, form_type=None):
    """Require the guarded form-change workflow for representation changes."""
    kind = form_type or "task"
    old = canonicalize_schema(previous or [], form_type=kind)
    new = validate_draft_schema(proposed, kind)
    removed_fields = {field["id"] for field in old if field["type"] not in {"html", "status"}} - {field["id"] for field in new}
    if removed_fields or requires_submission_conversion(old, new):
        raise exceptions.ValidationError(
            "Removing or changing a saved field, option or column requires a form migration, "
            "using Modify in the form builder and then Save."
        )
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
# @covered-by lagniappe/core/tools/form_drafts.py::resolve_form_generation
# @reason historical definitions are queried only for an explicitly requested generation
def _stored_generation(form_key, generation):
    rows = Query(KINDS.history).ancestor(form_key).filter(
        Filter().eq("type", "form_history").eq("generation", generation)
    ).fetch_all()
    if not rows:
        return None
    return Entities.fetch_one(rows[0], request=Fetch.root())


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_generation_resolution_ignores_legacy_versions
# @tests tests_unit/test_004f_form_drafts.py::test_generation_resolution_loads_only_the_requested_archive
# @matrix form-schema : history generation
def resolve_form_generation(form_or_key, generation):
    """Use the current Form when possible; otherwise load its archived generation."""
    form = form_or_key if hasattr(form_or_key, "schema") else None
    key = form.key if form is not None else form_or_key
    if not key:
        return None
    if form is None:
        form = Entities.fetch_one(key, request=Fetch.root())
    if form is not None and form.generation == generation:
        return form
    return _stored_generation(key, generation)


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_generation_resolution_batches_current_forms
# @matrix form-schema : history generation batch-read
def resolve_form_generations(pairs):
    """Load each current Form once, then resolve the distinct older generations."""
    requested = set(pairs)
    keys = {key for key, _generation in requested if key}
    current = {
        form.key: form
        for form in Entities.fetch(*keys, request=Fetch.root())
    }
    return {
        (key, generation): (
            current[key] if key in current and current[key].generation == generation
            else _stored_generation(key, generation)
        )
        for key, generation in requested if key
    }


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_archived_generation_preserves_schema_html_and_images
# @matrix form-schema html-field : history generation immutable-assets
def archive_form_generation(source, *, attempt_owner=None):
    """Preserve a superseded Form and its private content before replacing it."""
    history = Entities.FORM_HISTORY.create(source, source.generation)
    owner = attempt_owner if attempt_owner is not None else history
    html_ids = _html_ids(source)
    source_urls = {}
    try:
        for name, definition in source.assets.items():
            is_image = any(name.startswith(f"image_{field_id}_") for field_id in html_ids)
            if name not in html_ids and not is_image:
                continue
            asset = source.get_asset(name)
            destination = f"{history.hash}_{name}_{uuid4().hex}.{asset.extension}"
            blob = storage_assets.copy_file(
                asset.path, asset.visibility.value, destination, "private",
                **({"source_generation": asset.generation} if asset.generation else {}),
            )
            if not blob:
                raise exceptions.ValidationError("Could not preserve the Form's previous content.")
            copied = dict(definition)
            copied["path"] = destination
            copied.pop("visibility", None)
            if getattr(blob, "generation", None) is not None:
                copied["generation"] = str(blob.generation)
            history.assets[name] = copied
            record_attempt_asset(owner, copied)
            if definition.get("type") == "image":
                source_urls[name] = asset.url
    except Exception:
        cleanup_rejected_attempt(owner)
        raise
    history.db["assets"] = json.dumps(history.assets)
    history.db["source_asset_urls"] = source_urls
    history.db["form_content_version"] = CONTENT_VERSION
    return history


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_publication_reads_saved_form_only_at_save
# @tests tests_unit/test_004f_form_drafts.py::test_compatible_saves_update_version_without_archiving_generation
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_form_creation_and_content_edits_do_not_queue_reconciliation
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_change_detection_and_forced_retry
# @matrix forms mutations : guarded-save generation publication
# @matrix html-field : isolated-assets cleanup
# @matrix permissions cache : change-detection retry new-form content-only no-queue
# @pair mutations:rejected-save
def prepare_form_publication(form, builder):
    """Compare with the saved Form and publish staged content at the save boundary."""
    source = builder.entities.fetch_one(form.key, request=Fetch.root())
    prior_guard = getattr(form, "_form_save_guard", None)
    if prior_guard is not None:
        expected = prior_guard[1]
        actual = dict(source.db) if source is not None else None
        if actual != expected:
            raise exceptions.MutationConflict("This Form changed while preparing the Save; retry.")
    if source is not None:
        if source.modified != form.modified:
            raise exceptions.MutationConflict("This Form changed before saving; reload and retry.")
        if source.form_type != form.form_type:
            raise exceptions.ValidationError("A saved Form's type cannot be changed.")
        from .form_changes import PENDING, json_value
        change = json_value(source.db, PENDING)
        if change and getattr(form, "_form_change_publication", None) == change["id"]:
            if form.schema != change["target"]["schema"] or not change["applied"]:
                raise exceptions.ValidationError("The pending Form change does not match its publication.")
        else:
            if change:
                raise exceptions.ValidationError("This Form is being updated. Wait for the update to finish.")
            validate_compatible_schema(source.schema, form.schema, form.form_type)
        form._form_save_guard = (form.key, ExactEntityState(dict(source.db)))
    else:
        if form.created:
            raise exceptions.MutationConflict("This Form was deleted before saving.")
        validate_draft_schema(form.schema, form.form_type)
        form._form_save_guard = (form.key, None)

    # Only existing submissions need their inherited permissions reconciled.
    # Compare the saved source, not a cache row that may be missing or stale.
    form._reconcile_restrictions = source is not None and (
        source.restricted_to != form.restricted_to
        or getattr(form, "_reconcile_restrictions", False)
    )
    if form._reconcile_restrictions:
        form._permission_sources_changed = True

    previous_generation = source.generation if source else 0
    changed_generation = bool(source) and requires_submission_conversion(source.schema, form.schema)
    form.generation = previous_generation + 1 if changed_generation else previous_generation
    if not getattr(form, "_form_change_publication", None):
        stage_form_content(form)

    # Ordinary Step 1 saves are compatible. The existing migration guard stays
    # in place until the later transfer workflow can convert affected values.
    if changed_generation:
        history = archive_form_generation(source, attempt_owner=form)
        builder.plan_standard(history, reason="form-generation-history")
    if source is not None:
        for name, definition in source.assets.items():
            if definition.get("path") != (form.assets.get(name) or {}).get("path"):
                asset = source.get_asset(name)
                builder.delete_blob(asset.path, asset.visibility.value, reason="replaced-form-content")
    previous_version = form.version
    form.properties.version.update()
    if form.version != previous_version:
        form._permission_sources_changed = True


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::prepare_form_publication
# @covered-by lagniappe/core/tools/form_changes.py::start_change
# @reason explicit Save stages isolated content for immediate or deferred publication
def stage_form_content(form):
    for field_id, content in getattr(form, "_pending_html", {}).items():
        if field_id not in _html_ids(form):
            raise exceptions.ValidationError("Static content must belong to a draft HTML field.")
        content = sanitize_form_content_html(content, form, field_id)
        if content:
            previous_path = (form.assets.get(field_id) or {}).get("path")
            asset = form.save_asset(content, field_id, "html", isolated=True)
            if asset and asset.path != previous_path:
                record_attempt_asset(form, asset.definition)
        else:
            form.assets.pop(field_id, None)
            form.db["assets"] = json.dumps(form.assets)


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
    from .form_changes import PENDING, start_change, change_response, json_value
    pending = json_value(current.db, PENDING)
    if pending:
        if pending["id"] == save_id and pending["digest"] == payload_digest:
            return change_response(current)
        raise FormDraftConflict("A form change is already saved. Wait for it to finish before saving another draft.")
    schema = validate_draft_schema(draft.get("schema"), current.form_type)
    if requires_submission_conversion(current.schema, schema):
        return start_change(current, draft, save_id, actor, images=images)
    html = draft.get("html_fields")
    images = images or {}
    _validate_content(schema, html, images)

    current._form_save_guard = (current.key, ExactEntityState(dict(current.db)))
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
            # Re-read permissions and metadata; the browser baseline still
            # prevents overwriting another editor's accepted draft.
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
