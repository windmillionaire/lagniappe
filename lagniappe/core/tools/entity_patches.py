"""Prepare cohesive entity edits without clearing omitted fields or writing data."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timezone as utc_timezone

from lagniappe.core.definitions import Action, MutationIntent
from lagniappe.core.entities import Entities
from lagniappe.core.entities.category import UNCATEGORIZED_PAGES_NAME
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.form_special import HTML
from lagniappe.core.properties.schema import SchemaFields
from lagniappe.core.tools import dates
from lagniappe.core.tools.database.utility import ExactEntityState


PATCH_FIELDS = {
    "task": frozenset({"name", "description", "page", "project", "model", "form", "submission", "assigned_to", "due_date", "schedule"}),
    "model": frozenset({"name", "form"}),
    "project": frozenset({"name", "description", "model_tasks"}),
    "page": frozenset({"name", "description", "categories", "form", "submission"}),
}


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_task_patch_preserves_omitted_values_and_source
# @tests tests_unit/test_032g_entity_patches.py::test_reassignment_requires_complete_values_and_reviews_removals
# @tests tests_unit/test_032g_entity_patches.py::test_patch_rejects_completed_locked_invalid_and_unauthorized_targets
# @tests tests_unit/test_032g_entity_patches.py::test_model_and_project_patches_preserve_defaults_and_validate_order
# @tests tests_unit/test_032g_entity_patches.py::test_page_patch_preserves_omitted_membership
# @tests tests_unit/test_032g_entity_patches.py::test_patch_guards_reject_concurrent_completion_and_form_changes
# @tests tests_unit/test_032g_entity_patches.py::test_patch_validates_classification_assignee_and_explicit_clears
# @tests tests_unit/test_032g_entity_patches.py::test_page_form_registration_is_detached_and_pending_checklist_stays_unchecked
# @tests tests_unit/test_032g_entity_patches.py::test_patch_schedule_and_form_type_and_permission_validation
# @matrix entity-patch : preservation validation preparation permissions
def prepare_patch(entity, changes, actor):
    """Return detached writes and source guards for one reviewed edit.

    Relationship values are resolved entities, never names. Callers resolve exact
    saved references or earlier-action outputs before entering this boundary.
    The returned writes are for the ordinary mutation executor, including its
    Form-migration guards, relation effects and notifications.
    """
    from lagniappe.core.tools.ai.reporting.schedules import apply_task_schedule, validate_task_due_date

    kind = entity.entity_kind
    if kind not in PATCH_FIELDS or not isinstance(changes, dict) or not changes:
        raise ValidationError("Provide a nonempty patch for a supported entity.")
    unknown = set(changes) - PATCH_FIELDS[kind]
    if unknown:
        raise ValidationError(f"Unsupported patch fields: {', '.join(sorted(unknown))}.")
    _require(entity, actor, Action.EDIT)
    if kind == "task" and entity.completed:
        raise ValidationError("Completed tasks cannot be restructured. Reopen the task first.")
    sources = {entity.key: entity}
    related_sources = []
    if kind == "task":
        related_sources = [entity.page, entity.project, entity.model]
    elif kind == "model":
        related_sources = [entity.project]
    elif kind == "page":
        related_sources = list(entity.categories)
    for related in related_sources:
        if getattr(related, "key", None):
            sources[related.key] = related
    candidate = _copy_entity(entity)
    writes = [candidate]
    before = _projection(entity)
    removed = {}

    if "form" in PATCH_FIELDS[kind]:
        old_form = entity.form
        if old_form:
            _unlocked(old_form)
            sources[old_form.key] = old_form
        if "form" in changes:
            form = changes["form"]
            if form is not None:
                _reference(form, "form", actor)
                _unlocked(form)
                expected_type = "page" if kind == "page" else "task"
                if form.form_type != expected_type:
                    raise ValidationError(f"This edit requires a {expected_type} Form.")
                sources[form.key] = form
            changed_form = getattr(old_form, "key", None) != getattr(form, "key", None)
            candidate.form = form
            if changed_form and kind in {"task", "page"}:
                if "submission" not in changes:
                    raise ValidationError("Form reassignment requires a complete target submission.")
                removed = deepcopy(entity.submission or {})
                candidate.properties.submission.value = {}
                candidate._submission_definition = None
                candidate.properties.submission._fields = None
        else:
            changed_form = False
        if "submission" in changes:
            _patch_answers(candidate, changes["submission"], actor, complete=changed_form)

    if kind == "task":
        for field, expected in (("page", "page"), ("project", "project"), ("model", "model")):
            if field not in changes:
                continue
            value = changes[field]
            if value is not None:
                _reference(value, expected, actor, edit=field == "page")
                sources[value.key] = value
            elif field == "page":
                raise ValidationError("A task must belong to a Page.")
            setattr(candidate, field, value)
        if "model" in changes and candidate.model is not None:
            if "project" in changes and getattr(candidate.project, "key", None) != candidate.model.project.key:
                raise ValidationError("The model task does not belong to the selected Project.")
            candidate.project = candidate.model.project
        if candidate.model and getattr(candidate.project, "key", None) != candidate.model.project.key:
            raise ValidationError("Clear or change the model task when changing its Project.")
        if "due_date" in changes:
            value = validate_task_due_date(changes["due_date"])
            timezone = dates.user_timezone(actor)
            candidate.due_date = datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone) if value else None
        if "schedule" in changes:
            candidate.properties.schedule.clear()
            if changes["schedule"] is not None:
                apply_task_schedule(candidate, changes["schedule"])
                candidate.properties.schedule.unset()
        assignee = changes.get("assigned_to", entity.assigned_to)
        if assignee is not None and ("assigned_to" in changes or {"form", "page"} & changes.keys()):
            _reference(assignee, "page", actor)
            sources[assignee.key] = assignee
        if "assigned_to" in changes or {"form", "page"} & changes.keys():
            candidate.validate_assignment(assignee, actor=actor)
        if "assigned_to" in changes and getattr(assignee, "key", None) != getattr(entity.assigned_to, "key", None):
            candidate.assigned_to = assignee
            candidate.assigned_by = actor.page
            candidate.db["assignment_revision"] = int(entity.db.get("assignment_revision") or 0) + 1
            candidate._add_assignment_notice(actor, assignee)

    if kind == "project" and "model_tasks" in changes:
        ordered = changes["model_tasks"]
        if not isinstance(ordered, list):
            raise ValidationError("Model ordering must be a list.")
        for model in ordered:
            _reference(model, "model", actor, edit=True)
            if model.project.key != entity.key:
                raise ValidationError("Model ordering contains another Project's model task.")
        keys = [model.key for model in ordered]
        if len(keys) != len(set(keys)) or set(keys) != {model.key for model in entity.model_tasks}:
            raise ValidationError("Model ordering must include every model task exactly once.")
        for order, model in enumerate(ordered, 1):
            sources[model.key] = model
            updated = _copy_entity(model)
            updated.order = order
            writes.append(updated)
        candidate.properties.model_tasks._value = writes[1:]

    if kind == "page" and "categories" in changes:
        categories = changes["categories"]
        if not isinstance(categories, list) or not categories:
            raise ValidationError("Page membership requires at least one Category.")
        for category in categories:
            _reference(category, "category", actor, edit=True)
            sources[category.key] = category
        if len({category.key for category in categories}) != len(categories):
            raise ValidationError("Page categories cannot repeat.")
        candidate.model, candidate.categories = categories[0], categories[1:]
        for owner in entity.page_list_owners:
            candidate.add_mutation_intents(MutationIntent.touch(owner, reason="page-patch-previous-owner"))

    if kind == "page" and candidate.form and {"categories", "form"} & changes.keys():
        for category in candidate.categories:
            if category.name == UNCATEGORIZED_PAGES_NAME:
                continue
            sources[category.key] = category
            updated = _copy_entity(category)
            if updated.properties.forms.add(candidate.form):
                candidate.add_mutation_intents(
                    MutationIntent.patch(updated, "forms", reason="page-category-form-registration"),
                    MutationIntent.touch(candidate.form, reason="page-category-form-registration"),
                )

    for field in ("name", "description"):
        if field not in changes:
            continue
        value = changes[field]
        if field == "name" and (not isinstance(value, str) or not value.strip()):
            raise ValidationError("Name cannot be cleared.")
        if value is not None and not isinstance(value, str):
            raise ValidationError(f"{field} must be text or null.")
        setattr(candidate, field, value)
    _require(candidate, actor, Action.EDIT)
    guards = [(source.key, ExactEntityState(deepcopy(dict(source.db)))) for source in sources.values()]
    candidate._form_additional_guards = guards
    return PreparedPatch(candidate, tuple(writes), tuple(guards), before, _projection(candidate), removed, tuple(source for source in sources.values() if source.entity_kind == "form"))


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason typed preparation result carries review values and transaction inputs
@dataclass(frozen=True)
class PreparedPatch:
    entity: object
    writes: tuple
    guards: tuple
    before: dict
    after: dict
    removed_values: dict
    forms: tuple


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason detached copies preserve storage and already-loaded relations
def _copy_entity(entity):
    cls = {"task": Entities.TASK, "page": Entities.PAGE, "project": Entities.PROJECT, "model": Entities.MODEL_TASK, "category": Entities.CATEGORY}[entity.entity_kind]
    result = cls(entity.key)
    result._db = deepcopy(entity.db)
    result.attach(entity.related_entities)
    return result


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason exact entity types and permissions are validated before edits
def _reference(entity, kind, actor, *, edit=False):
    if getattr(entity, "entity_kind", None) != kind or not getattr(entity, "key", None):
        raise ValidationError(f"Expected an exact {kind} reference.")
    _require(entity, actor, Action.EDIT if edit else Action.VIEW)


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason shared authorization guard applies to source and proposed state
def _require(entity, actor, action):
    if actor is None or not entity.allowed(action, user=actor):
        raise ValidationError("You do not have permission to make this edit.")


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason migration locks are checked on both old and new Forms
def _unlocked(form):
    if form.db.get("pending_form_change"):
        raise ValidationError("Wait for the Form update to finish before editing its tasks or answers.")


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason selected fields are validated on detached candidates before assignment
def _patch_answers(entity, values, actor, *, complete):
    if not isinstance(values, dict):
        raise ValidationError("Submission must be an object.")
    if entity.form is None:
        if values:
            raise ValidationError("Answers require a Form.")
        return
    submission = entity.properties.submission
    fields = {key: field for key, field in submission.fields.items() if not isinstance(field, HTML)}
    if set(values) - set(fields):
        raise ValidationError("Submission contains unknown fields.")
    if complete and set(values) != set(fields):
        raise ValidationError("Form reassignment requires every target answer field, including empty values.")
    prepared = {key: SchemaFields.prepare_ai_field(fields[key], value, entity, user=actor) for key, value in values.items()}
    for key, value in prepared.items():
        submission.fields[key] = value
    entity.save_submission()


# @testable false
# @covered-by lagniappe/core/tools/entity_patches.py::prepare_patch
# @reason review uses exact answer IDs and complete editable values
def _projection(entity):
    result = {}
    for field in PATCH_FIELDS[entity.entity_kind]:
        if field == "model_tasks":
            result[field] = [{"id": model.urlsafe_key, "name": model.name} for model in entity.model_tasks]
            continue
        value = getattr(entity, field, None)
        if field == "schedule":
            value = entity.properties.schedule.value
        if hasattr(value, "urlsafe_key"):
            value = {"id": value.urlsafe_key, "name": value.name}
        elif field == "categories":
            value = [{"id": item.urlsafe_key, "name": item.name} for item in value or []]
        elif isinstance(value, datetime):
            value = value.astimezone(utc_timezone.utc).isoformat() if value.tzinfo else value.isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        result[field] = deepcopy(value)
    return result
