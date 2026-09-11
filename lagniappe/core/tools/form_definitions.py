"""Version-qualified definitions for immutable completion submissions."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from google.cloud import datastore

from ..exceptions import ValidationError
from .database import get as database_get
from .database.core import KINDS
from .database.utility import ExactEntityState
from .files.html import sanitize_form_content_html


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::definition_version
# @covered-by lagniappe/core/tools/form_drafts.py::resolve_form_version
# @reason canonical identity encoding is shared by content versions and snapshot keys
def _definition_digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    ).encode()).hexdigest()


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_content_version_changes_only_with_definition_content
# @matrix form-schema html-field : content-version fingerprint
def definition_version(form):
    """Identify schema and exact static content, independently from display name."""
    html_ids = {field["id"] for field in form.schema if field.get("type") == "html"}
    assets = {
        name: {key: definition.get(key) for key in ("type", "fingerprint")}
        for name, definition in form.assets.items()
        if name in html_ids or any(name.startswith(f"image_{field_id}_") for field_id in html_ids)
    }
    if any(not isinstance(asset["fingerprint"], str) or not asset["fingerprint"] for asset in assets.values()):
        raise ValidationError("Form content has no verifiable fingerprint and requires repair before publication.")
    return "fc1-" + _definition_digest({"schema": form.schema, "form_type": form.form_type, "assets": assets})


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::resolve_form_version
# @covered-by lagniappe/core/tools/form_drafts.py::ensure_form_snapshot
# @reason deterministic version lookup is owned by the public snapshot APIs
def _snapshot_key(form_key, version):
    return datastore.Key(KINDS.history.value, "definition-" + _definition_digest(version), parent=form_key)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_definition_uses_recorded_version_and_reports_missing_schema
# @matrix submission task-completion : schema-version missing-schema
@dataclass(frozen=True)
class SubmissionDefinition:
    source: object = None
    version: str = None
    immutable: bool = False
    error: str = None

    @property
    def schema(self):
        return self.source.schema if self.source is not None else []

    @property
    def content_available(self):
        return bool(self.source is not None and (
            not self.immutable or getattr(self.source, "content_available", False)
        ))


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::definition_for
# @covered-by lagniappe/core/entities/history.py::TaskHistory.create
# @reason JSON envelopes are parsed once per stored immutable string
def completed_envelope(entity, *, refresh=False):
    raw = getattr(entity, "db", {}).get("completed_submission") if getattr(entity, "entity_kind", None) == "task" else None
    if raw is None:
        return None
    cached = getattr(entity, "_completed_envelope", None)
    if not refresh and cached is not None and cached[0] is raw:
        return cached[1]
    try:
        value = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
    except (ValueError, TypeError) as error:
        raise ValidationError("The saved completion is invalid and needs review.") from error
    if not isinstance(value, dict) or not isinstance(value.get("submission"), dict):
        raise ValidationError("The saved completion is invalid and needs review.")
    entity._completed_envelope = (raw, value)
    return value


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::definition_for
# @reason shared completion classification for reads and mutation guards
def immutable_submission(entity):
    return entity.entity_kind == "task_history" or (
        entity.entity_kind == "task" and (
            bool(getattr(entity, "db", {}).get("completed_submission")) or entity.completed
        )
    )


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::definition_for
# @reason the envelope owns the original Form identity even if flat fields change
def definition_identity(entity):
    envelope = completed_envelope(entity)
    key = entity.properties.form.key
    if envelope is None:
        return key, entity.schema_version
    encoded = envelope.get("form_key")
    if encoded != database_get.urlsafe_key(key):
        key = database_get.datastore_key(encoded) if encoded else None
    return key, envelope.get("schema_version")


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::definition_for
# @reason exact current content versions avoid historical storage reads
def _current_definition(entity, identity):
    prop = entity.properties.form
    # Collection readers already batch-load this relation. Do not create a new
    # lazy relationship read just to attempt the fast path.
    if hasattr(prop, "is_set") and not prop.is_set:
        return None
    form = entity.form
    if form is not None and form.key == identity[0] and form.version == identity[1] and getattr(form, "content_available", False):
        return SubmissionDefinition(form, identity[1], True)
    return None


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::definition_for
# @reason a cached live Form must stop serving a completion after publication
def _cached_definition(entity, identity):
    cached = getattr(entity, "_submission_definition", None)
    if not cached or cached[0] != identity:
        return None
    source = cached[1].source
    if getattr(source, "entity_kind", None) == "form" and (
        source.version != identity[1] or not source.content_available
    ):
        return None
    return cached[1]


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_definition_uses_recorded_version_and_reports_missing_schema
# @tests tests_unit/test_004i_form_definitions.py::test_active_definition_uses_latest_metadata
# @tests tests_unit/test_004i_form_definitions.py::test_completed_envelope_uses_matching_current_definition_without_history_read
# @matrix submission task-completion : schema-version missing-schema live-metadata
# @pairs task-completion:current-definition task-completion:no-extra-read
def definition_for(entity):
    """Use matching current content, resolving history only after a change."""
    if not immutable_submission(entity):
        form = entity.form
        return SubmissionDefinition(form, getattr(form, "version", None))
    identity = definition_identity(entity)
    form_key, version = identity
    if not form_key:
        envelope = completed_envelope(entity)
        raw = envelope["submission"] if envelope else getattr(entity, "db", {}).get("submission")
        raw = json.loads(raw) if isinstance(raw, str) else raw
        return SubmissionDefinition(immutable=True, error=(
            "The original form definition is unavailable. Saved answers are preserved."
            if raw else None
        ))
    result = _current_definition(entity, identity) or _cached_definition(entity, identity)
    if result is not None:
        return result
    # The storage service imports entities; defer it across that module cycle.
    from .form_drafts import resolve_form_version

    source = resolve_form_version(form_key, version) if version else None
    result = SubmissionDefinition(
        source, version, True,
        None if source is not None else
        "The original form definition is unavailable. Saved answers are preserved.",
    )
    entity._submission_definition = (identity, result)
    return result


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_mutations_are_rejected_before_changing_values
# @matrix task-completion : immutable-submission
def require_mutable_submission(entity):
    if immutable_submission(entity) and not (
        entity.entity_kind == "task_history" and not entity.created
    ):
        raise ValidationError("Completed answers cannot be changed. Reopen the task first.")


_COMPLETION_FIELDS = (
    "completed_submission", "submission", "default_submission", "schema_version",
    "form", "assets", "completed", "completed_on", "completed_by",
)


# @testable true
# @matrix task-completion mutations : hydration no-extra-read
def capture_completion_identity(entity, raw):
    # Current storage uses JSON strings and scalar values. Only rare legacy
    # mutable encodings need copying; ordinary Task hydration never clones a row.
    identity = {
        name: deepcopy(value) if isinstance(value, (dict, list)) else value
        for name in _COMPLETION_FIELDS
        if (value := raw.get(name)) is not None
    } if raw else None
    object.__setattr__(entity, "_completion_identity", identity)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completion_write_rejects_raw_changes_and_stages_original_guards
# @matrix task-completion mutations : immutable-submission concurrency
def validate_completion_write(entity):
    raw = entity.db
    before = getattr(entity, "_completion_identity", None)
    was_completed = bool(before) and (entity.entity_kind == "task_history" or before.get("completed") or before.get("completed_submission"))
    reopening = entity.entity_kind == "task" and getattr(entity, "_completion_reopening", False)
    if was_completed and not reopening and any(before.get(name) != raw.get(name) for name in _COMPLETION_FIELDS):
        raise ValidationError("Completed answers and their original form cannot be changed.")
    sealed = getattr(entity, "_completion_sealing", None)
    if sealed is not None and not reopening and raw.get("completed_submission") != sealed:
        raise ValidationError("Completed answers and their original form cannot be changed.")
    if before is not None and not was_completed and not reopening and entity.entity_kind == "task" and (raw.get("completed_submission") or raw.get("completed")) and sealed is None:
        raise ValidationError("Complete the task before saving completed answers.")
    # Guard only the completion fields a whole save could overwrite. Missing
    # fields are explicit so a concurrent completion cannot slip past the CAS.
    if before is not None:
        expected = {name: before.get(name) for name in _COMPLETION_FIELDS}
        guards = list(getattr(entity, "_completion_write_guards", ()))
        guards = [(key, state) for key, state in guards if key != entity.key]
        entity._completion_write_guards = [(entity.key, expected), *guards]


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completion_write_rejects_raw_changes_and_stages_original_guards
# @matrix task-completion mutations : immutable-submission concurrency
def stage_completion_guards(task):
    before = getattr(task, "_completion_identity", None)
    expected = {name: before.get(name) for name in _COMPLETION_FIELDS} if before is not None else None
    guards = [(task.key, expected)]
    if task.form:
        source = task.form.saved_form_state()
        guards.append((task.form.key, ExactEntityState(source) if source is not None else None))
    task._completion_write_guards = guards


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completion_rejects_unrepresented_values_without_rewriting_answers
# @matrix task-completion submission : schema-version incompatible-value preservation
def validate_completion_values(task):
    """Do not stamp a current version onto answers it cannot losslessly read."""
    from ..properties.schema import SchemaFields
    from .form_drafts import resolve_form_version

    values = task.properties.submission.value
    current = task.form
    if not current:
        if values:
            raise ValidationError("Saved answers have no form definition and need review.")
        return
    if values and task.schema_version and task.schema_version != current.version:
        original = resolve_form_version(current, task.schema_version)
        if original is None:
            raise ValidationError("The saved answer definition is unavailable; review is required before completion.")
        compatible_values(original.schema, current.schema, values)
    schema = {field["id"]: field for field in current.schema}
    for field_id, value in values.items():
        definition = schema.get(field_id)
        if definition is None:
            raise ValidationError("Saved answers include an unavailable field and need review before completion.")
        field = SchemaFields.create_field(definition, task)
        if field is None:
            raise ValidationError("A saved field type is unavailable and needs review before completion.")
        field.db_value = deepcopy(value)
        if json.dumps(field.db_value, sort_keys=True) != json.dumps(value, sort_keys=True):
            raise ValidationError("Saved answers require conversion before this task can be completed.")


# @testable false
# @covered-by lagniappe/core/entities/task.py::Task.complete
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason interactive and imported completion boundaries share snapshot pinning and guards
def stage_completion_definition(task):
    values = task.properties.submission.value
    form = task.form
    version = None
    if form:
        snapshot = form.snapshot_for_completion()
        version = snapshot.version
        task.db["schema_version"] = version
        task._submission_definition = (
            (task.properties.form.key, version),
            SubmissionDefinition(snapshot, version, True),
        )
    stage_completion_guards(task)
    envelope = json.dumps({
        "submission": values,
        "schema_version": version,
        "form_key": database_get.urlsafe_key(task.properties.form.key),
    })
    task.db["completed_submission"] = envelope
    task._completion_sealing = envelope
    task.properties.submission._fields = None


# @testable false
# @covered-by lagniappe/core/tools/form_definitions.py::compatible_values
# @reason representation comparison is exercised by history/default transfer tests
def _representation(field):
    return (
        field.get("type"),
        field.get("input", "text") if field.get("type") == "input" else None,
        bool(field.get("multiple")) if field.get("type") in {"select", "link"} else None,
        field.get("location") if field.get("type") == "link" else None,
    )


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_transfer_preserves_identity_and_rejects_incompatible_values
# @matrix task-completion submission : history-fill repeating-default identity incompatible-value
def compatible_values(source_schema, target_schema, values):
    """Copy exact values only when their source and destination mean the same thing."""
    source = {field["id"]: field for field in source_schema}
    target = {field["id"]: field for field in target_schema}
    for field_id, value in values.items():
        old, new = source.get(field_id), target.get(field_id)
        if old is None or new is None or _representation(old) != _representation(new):
            raise ValidationError(
                "Saved answers use a different form definition and need review before reuse."
            )
        old_options = {json.dumps(option.get("value"), sort_keys=True) for option in old.get("options", [])}
        new_options = {json.dumps(option.get("value"), sort_keys=True) for option in new.get("options", [])}
        if not old_options.issubset(new_options):
            raise ValidationError("Saved choices need review before reuse with this form.")
        if old.get("type") == "table" and value is not None:
            rows = value.get("rows", []) if isinstance(value, dict) else value
            if not isinstance(rows, list):
                raise ValidationError("Saved table answers need review before reuse.")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValidationError("Saved table answers need review before reuse.")
                compatible_values(old.get("columns", []), new.get("columns", []), row)
    return deepcopy(values)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_transfer_preserves_identity_and_rejects_incompatible_values
# @matrix task-completion submission : history-fill repeating-default identity incompatible-value
def history_values_for(task, history, field_id=None):
    if task.completed:
        raise ValidationError("Reopen the task before filling saved answers.")
    if task.properties.form.key != history.properties.form.key:
        raise ValidationError("This completion belongs to a different form.")
    definition = definition_for(history)
    if definition.error:
        raise ValidationError(definition.error)
    values = history.properties.submission.value
    if field_id is not None:
        if field_id not in values:
            raise ValidationError("This completion has no saved answer for that field.")
        values = {field_id: values[field_id]}
    return compatible_values(definition.schema, task.submission_schema, values)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_groups_preserve_chronology_and_original_columns
# @matrix tasks task-completion : history schema-version ordering
def history_groups(histories):
    """Keep newest-first order, grouping only consecutive equal definitions."""
    preload_definitions(histories)
    groups = []
    definitions = {}
    for history in histories:
        identity = definition_identity(history)
        if identity not in definitions:
            definitions[identity] = definition_for(history)
        history._submission_definition = (identity, definitions[identity])
        if not groups or groups[-1]["identity"] != identity:
            groups.append({"identity": identity, "records": [], "definition": definitions[identity]})
        groups[-1]["records"].append(history)
    return groups


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_groups_preserve_chronology_and_original_columns
# @matrix tasks task-completion : history schema-version ordering
def preload_definitions(records):
    """Batch the unique immutable definitions needed by one record collection."""
    from .form_drafts import resolve_form_versions

    pending = {}
    for record in records:
        if not immutable_submission(record):
            continue
        identity = definition_identity(record)
        if not all(identity):
            continue
        current = _current_definition(record, identity)
        if current is not None:
            record._submission_definition = (identity, current)
            continue
        if _cached_definition(record, identity) is not None:
            continue
        pending.setdefault(identity, []).append(record)
    resolved = resolve_form_versions(pending) if pending else {}
    for identity, users in pending.items():
        source = resolved.get(identity)
        result = SubmissionDefinition(
            source, identity[1], True,
            None if source is not None else
            "The original form definition is unavailable. Saved answers are preserved.",
        )
        for record in users:
            record._submission_definition = (identity, result)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_html_uses_authorized_record_asset_urls
# @matrix task-completion html-field : schema-version owned-image missing-content
def rendered_html_fields(entity):
    """Render exact content with image URLs authorized through its submission."""
    definition = definition_for(entity)
    result = {}
    for field in definition.schema:
        if field.get("type") != "html":
            continue
        field_id = field["id"]
        if not definition.content_available:
            result[field_id] = "<p>Original static content is unavailable. Saved answers are preserved.</p>"
            continue
        source = definition.source
        html = sanitize_form_content_html(source.get_html_field(field_id) or "", source, field_id)
        if definition.immutable:
            for name, asset_definition in source.assets.items():
                if name.startswith(f"image_{field_id}_") and asset_definition.get("type") == "image":
                    asset = source.get_asset(name)
                    if asset and asset.url:
                        extension = getattr(asset, "extension", None)
                        identifier = f"{name}.{extension}" if extension else name
                        html = html.replace(
                            asset.url,
                            f"/assets/{entity.urlsafe_key}/form-version/{definition.version}/{identifier}",
                        )
        result[field_id] = html
    return result
