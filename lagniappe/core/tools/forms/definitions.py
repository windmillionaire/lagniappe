"""Current, pending, and historical Form definitions and original completions."""

from copy import deepcopy
from dataclasses import dataclass
import json

from ...definitions import Fetch
from ...exceptions import ValidationError
from ..database.core import KINDS
from ..database.filter import Filter, Query
from ..database import get as database_get
from ..files.html import sanitize_form_content_html
from .contracts import PENDING, json_value


_ORIGINAL_UNAVAILABLE = (
    "The original form definition is unavailable. Saved answers are preserved."
)
_COMPLETION_FIELDS = (
    "completed_submission", "submission", "generation",
    "form", "assets", "completed", "completed_on", "completed_by",
)
_COMPLETION_STATUS_FIELDS = (
    "completed_submission", "completed", "completed_on", "completed_by",
)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_definition_uses_recorded_version_and_reports_missing_schema
# @matrix submission task-completion : schema-version missing-schema
@dataclass(frozen=True)
class SubmissionDefinition:
    source: object = None
    generation: int = 0
    immutable: bool = False
    error: str = None

    @property
    def schema(self):
        return self.source.schema if self.source is not None else []

    @property
    def content_available(self):
        return self.source is not None and getattr(self.source, "content_available", True)


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::original_completion
# @covered-by lagniappe/core/entities/history.py::TaskHistory.create
# @reason only original-completion reads and archives parse the saved envelope
def completed_envelope(entity):
    if getattr(entity, "entity_kind", None) != "task":
        return None
    raw = entity.db.get("completed_submission")
    if raw is None:
        return None
    try:
        value = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
    except (ValueError, TypeError) as error:
        raise ValidationError("The saved completion is invalid and needs review.") from error
    if not isinstance(value, dict) or not isinstance(value.get("submission"), dict):
        raise ValidationError("The saved completion is invalid and needs review.")
    return value


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::require_mutable_submission
# @reason ordinary edit paths require reopening even though current values are separate from original answers
def immutable_submission(entity):
    return entity.entity_kind == "task_history" or (
        entity.entity_kind == "task" and (
            bool(entity.db.get("completed_submission")) or entity.completed
        )
    )


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::definition_for
# @covered-by lagniappe/core/tools/forms/definitions.py::history_groups
# @reason only explicit generations qualify historical definitions; old schema versions are cache metadata
def definition_identity(entity):
    return entity.properties.form.key, getattr(entity, "generation", 0) or 0


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::definition_for
# @covered-by lagniappe/core/tools/forms/definitions.py::original_completion
# @reason already-loaded matching Forms avoid historical storage reads
def _current_definition(entity, identity):
    prop = entity.properties.form
    if hasattr(prop, "is_set") and not prop.is_set:
        return None
    form = entity.form
    if (
        form is not None
        and form.key == identity[0]
        and (getattr(form, "generation", 0) or 0) == identity[1]
    ):
        return SubmissionDefinition(form, identity[1], True)
    return None


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::definition_for
# @covered-by lagniappe/core/tools/forms/definitions.py::original_completion
# @reason only mismatched historical generations need cached resolution
def _historical_definition(entity, identity):
    current = _current_definition(entity, identity)
    if current is not None:
        return current
    cached = getattr(entity, "_submission_definition", None)
    if cached is not None and cached[0] == identity:
        return cached[1]

    source = resolve_form_generation(*identity) if identity[0] else None
    result = SubmissionDefinition(
        source, identity[1], True, None if source is not None else _ORIGINAL_UNAVAILABLE,
    )
    entity._submission_definition = (identity, result)
    return result


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_definition_uses_recorded_version_and_reports_missing_schema
# @tests tests_unit/test_004i_form_definitions.py::test_active_definition_uses_latest_metadata
# @tests tests_unit/test_004i_form_definitions.py::test_completed_envelope_uses_matching_current_definition_without_history_read
# @tests tests_unit/test_004i_form_definitions.py::test_completed_task_resolves_saved_generation_after_form_deletion
# @tests tests_unit/test_004i_form_definitions.py::test_active_submission_does_not_restore_deleted_form
# @tests tests_unit/test_004i_form_definitions.py::test_completed_task_without_an_attached_form_stays_empty
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_deleted_migrated_form_retains_completed_submissions_and_history
# @matrix submission task-completion : schema-version missing-schema live-metadata
# @matrix task-completion : deleted-form generation raw-values active-form empty-submission
# @pairs task-completion:current-definition task-completion:no-extra-read
def definition_for(entity, *, archived=False):
    """Use live fields unless history or an archived completion is explicitly requested."""
    if entity.entity_kind == "task_history" or (
        archived and entity.entity_kind == "task" and entity.completed and entity.form is None
    ):
        identity = definition_identity(entity)
        if identity[0] is None and not entity.properties.submission.value:
            return SubmissionDefinition(generation=identity[1], immutable=True)
        return _historical_definition(entity, identity)
    form = entity.form
    form = effective_definition(entity, form)
    return SubmissionDefinition(form, getattr(form, "generation", 0) or 0)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_envelope_uses_matching_current_definition_without_history_read
# @tests tests_unit/test_004i_form_definitions.py::test_completed_definition_uses_recorded_version_and_reports_missing_schema
# @matrix submission task-completion : schema-version missing-schema raw-values
# @pairs task-completion:current-definition task-completion:no-extra-read
def original_completion(task):
    """Read original answers explicitly, including generation-zero legacy completions."""
    envelope = completed_envelope(task)
    form_key = task.properties.form.key
    if envelope is None:
        values = deepcopy(task.properties.submission.value)
        generation = getattr(task, "generation", 0) or 0
    else:
        values = envelope["submission"]
        generation = envelope.get("generation", 0) or 0
        encoded_key = envelope.get("form_key")
        if encoded_key != database_get.urlsafe_key(form_key):
            form_key = database_get.datastore_key(encoded_key) if encoded_key else None
    definition = (
        _historical_definition(task, (form_key, generation))
        if form_key is not None or values
        else SubmissionDefinition(generation=generation, immutable=True)
    )
    return {
        "definition": definition,
        "submission": values,
        "generation": generation,
        "form_key": form_key,
    }


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completed_mutations_are_rejected_before_changing_values
# @matrix task-completion : immutable-submission
def require_mutable_submission(entity):
    if immutable_submission(entity) and not (
        entity.entity_kind == "task_history" and not entity.created
    ):
        raise ValidationError("Completed answers cannot be changed. Reopen the task first.")


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::validate_completion_write
# @reason completion CAS captures only fields owned by the operation, including absent values
def _completion_projection(raw):
    if raw is None:
        return None
    return {name: deepcopy(raw.get(name)) for name in _COMPLETION_FIELDS}


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completion_write_rejects_raw_changes_and_stages_original_guards
# @tests tests_unit/test_004i_form_definitions.py::test_envelope_write_guard_rejects_raw_mutation_and_stale_active_overwrite
# @matrix task-completion mutations : immutable-submission concurrency
def validate_completion_write(entity, persisted):
    """Validate original answers at a write boundary with a fresh persisted row."""
    raw = entity.db
    transition = getattr(entity, "_completion_transition", None)
    action = transition.get("action") if transition else None
    guards = list(getattr(entity, "_completion_write_guards", ()))
    current = _completion_projection(persisted)
    previous = next((expected for key, expected in guards if key == entity.key), current)
    if previous != current:
        raise ValidationError("The task changed during completion. Reload and try again.")

    if entity.entity_kind == "task_history":
        if persisted is not None and any(
            persisted.get(name) != raw.get(name) for name in _COMPLETION_FIELDS
        ):
            raise ValidationError("Original completed answers cannot be changed.")
    elif action == "complete":
        if not raw.get("completed") or raw.get("completed_submission") != transition["envelope"]:
            raise ValidationError("Completed answers and their original form cannot be changed.")
    elif action == "reopen":
        if raw.get("completed") or raw.get("completed_submission") is not None:
            raise ValidationError("Reopening must archive and clear the original completion.")
    elif persisted is not None and (persisted.get("completed") or persisted.get("completed_submission")):
        if any(persisted.get(name) != raw.get(name) for name in _COMPLETION_STATUS_FIELDS):
            raise ValidationError("Completed answers and their original form cannot be changed.")
    elif raw.get("completed") or raw.get("completed_submission"):
        raise ValidationError("Complete the task before saving completed answers.")

    entity._completion_write_guards = [
        (entity.key, current),
        *((key, expected) for key, expected in guards if key != entity.key),
    ]


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completion_write_rejects_raw_changes_and_stages_original_guards
# @matrix task-completion mutations : immutable-submission concurrency
def stage_completion_guards(task, *, transition=None):
    """Capture concurrency expectations only when completing or reopening a task."""
    guards = list(getattr(task, "_completion_write_guards", ()))
    prior_transition = getattr(task, "_completion_transition", None)
    if (
        prior_transition
        and prior_transition["action"] == "complete"
        and task.db.get("completed_submission") != prior_transition["envelope"]
    ):
        raise ValidationError("Completed answers and their original form cannot be changed.")
    task_guard = next((expected for key, expected in guards if key == task.key), None)
    if not any(key == task.key for key, _ in guards):
        persisted = database_get.entity(task.key)
        task_guard = _completion_projection(persisted)
        guards.append((task.key, task_guard))
    if (
        prior_transition is None
        and task_guard is not None
        and (task_guard.get("completed") or task_guard.get("completed_submission"))
        and (
            transition != "reopen"
            or any(task_guard.get(name) != task.db.get(name) for name in _COMPLETION_STATUS_FIELDS)
        )
    ):
        raise ValidationError("Completed answers and their original form cannot be changed.")
    form = task.form
    if form is not None and not any(key == form.key for key, _ in guards):
        persisted_form = database_get.entity(form.key)
        if persisted_form is not None and (persisted_form.get("generation", 0) or 0) != form.generation:
            raise ValidationError("The form changed before completion. Reload and try again.")
        expected = (
            {name: deepcopy(persisted_form.get(name)) for name in ("generation", "schema", "assets")}
            if persisted_form is not None else None
        )
        guards.append((form.key, expected))
    task._completion_write_guards = guards


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_completion_rejects_unrepresented_values_without_rewriting_answers
# @matrix task-completion submission : schema-version incompatible-value preservation
def validate_completion_values(task):
    """Do not capture answers that the current schema cannot losslessly read."""
    from ...properties.schema import SchemaFields

    values = task.properties.submission.value
    current = task.form
    if not current:
        if values:
            raise ValidationError("Saved answers have no form definition and need review.")
        return
    if values and task.generation != current.generation:
        raise ValidationError("Saved answers need transfer to the current form before completion.")
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
# @reason manual and imported completion capture original values through the same boundary
def capture_completed_submission(task):
    stage_completion_guards(task, transition="complete")
    form = task.form
    generation = getattr(form, "generation", 0) or 0
    values = task.properties.submission.value
    envelope = json.dumps({
        "submission": values,
        "generation": generation,
        "form_key": database_get.urlsafe_key(task.properties.form.key),
    })
    task.db["completed_submission"] = envelope
    task.db["generation"] = generation
    if values:
        task.db["submission"] = json.dumps(values)
    else:
        task.db.pop("submission", None)
    if form is not None:
        task.db["schema_version"] = form.version
    task._completion_transition = {"action": "complete", "envelope": envelope}


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::compatible_values
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
# @matrix task-completion submission : history-fill identity incompatible-value
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
# @tests tests_unit/test_004i_form_definitions.py::test_history_fill_converts_one_field_without_changing_history
# @matrix task-completion submission : history-fill identity incompatible-value
def history_values_for(task, history, field_id=None, *, zone="UTC"):
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
    source = {field["id"]: field for field in definition.schema}
    target = {field["id"]: field for field in task.submission_schema}
    return {
        key: _history_value(source.get(key), target.get(key), value, zone)
        for key, value in values.items()
    }


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::history_values_for
# @reason history reuse applies existing deterministic rules without clearing invalid answers
def _history_value(source, target, value, zone):
    from .conversions import MISSING, conversion_rule, convert_value

    label = (target or source or {}).get("title", "this field")
    error = f'The saved value for "{label}" cannot be converted to the current field type.'
    if not source or not target or conversion_rule(source, target) in {None, "ai", "delete"}:
        raise ValidationError(error)
    if source["type"] == target["type"] == "table":
        rows = value.get("rows", []) if isinstance(value, dict) else value
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValidationError(error)
        old_columns = {column["id"]: column for column in source.get("columns", [])}
        new_columns = {column["id"]: column for column in target.get("columns", [])}
        return {"rows": [
            {key: _history_value(old_columns.get(key), new_columns[key], item, zone)
             for key, item in row.items() if key in new_columns}
            for row in rows
        ]}
    converted, reason = convert_value(value, source, target, zone=zone)
    if converted is MISSING or reason == "invalid":
        raise ValidationError(error)
    return converted


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_groups_share_generation_tables_and_preserve_row_order
# @matrix tasks task-completion : history schema-version ordering
def history_groups(histories):
    """Build one table per Form generation, keeping newest-first groups and rows."""
    preload_definitions(histories)
    groups = {}
    for history in histories:
        identity = definition_identity(history)
        if identity not in groups:
            groups[identity] = {
                "identity": identity, "records": [], "definition": definition_for(history),
            }
        groups[identity]["records"].append(history)
    return list(groups.values())


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_groups_share_generation_tables_and_preserve_row_order
# @matrix tasks task-completion : history schema-version ordering
def preload_definitions(records):
    """Batch mismatched generations only when a history collection is requested."""

    pending = {}
    for record in records:
        if record.entity_kind != "task_history":
            continue
        identity = definition_identity(record)
        if identity[0] is None:
            continue
        current = _current_definition(record, identity)
        if current is not None:
            continue
        cached = getattr(record, "_submission_definition", None)
        if cached is not None and cached[0] == identity:
            continue
        pending.setdefault(identity, []).append(record)
    resolved = resolve_form_generations(pending) if pending else {}
    for identity, users in pending.items():
        source = resolved.get(identity)
        result = SubmissionDefinition(
            source, identity[1], True,
            None if source is not None else
            _ORIGINAL_UNAVAILABLE,
        )
        for record in users:
            record._submission_definition = (identity, result)


# @testable true
# @tests tests_unit/test_004i_form_definitions.py::test_history_html_uses_authorized_record_asset_urls
# @tests tests_unit/test_004i_form_definitions.py::test_html_field_selection_reads_only_requested_content
# @matrix task-completion html-field : schema-version owned-image missing-content
# @matrix html-field : authoritative-content
def rendered_html_fields(entity, *, original=False, definition=None, only_field_id=None):
    """Render the selected definition, optionally without reading unrelated fields."""
    if definition is None:
        definition = original_completion(entity)["definition"] if original else definition_for(entity)
    result = {}
    for field in definition.schema:
        if field.get("type") != "html":
            continue
        field_id = field["id"]
        if only_field_id is not None and field_id != only_field_id:
            continue
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
                            f"/assets/{entity.urlsafe_key}/form-generation/{definition.generation}/{identifier}",
                        )
        result[field_id] = html
    return result


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_pending_definition_resolves_each_generation
# @matrix form-migration : partial-read generation
def target_definition(form, change=None):
    from ...entities import Entities

    change = change or json_value(form.db, PENDING)
    if not change:
        return form
    target = change["target"]
    row = deepcopy(form.db)
    row.pop(PENDING, None)
    for name in ("schema", "assets"):
        row[name] = json.dumps(target[name])
    for name in ("name", "generation", "version"):
        row[name] = target[name]
    result = Entities.FORM(row)
    result._pending_html = deepcopy(target["html_fields"])
    return result


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_pending_definition_resolves_each_generation
# @matrix form-migration : partial-read generation
def effective_definition(entity, form):
    if not form:
        return form
    change = json_value(getattr(form, "db", {}), PENDING)
    if change and entity.generation == change["target"]["generation"]:
        return target_definition(form, change)
    return form


# @testable false
# @covered-by lagniappe/core/tools/forms/definitions.py::resolve_form_generation
# @reason historical definitions are queried only for an explicitly requested generation
def _stored_generation(form_key, generation):
    from ...entities import Entities

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
    from ...entities import Entities

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
    from ...entities import Entities

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
