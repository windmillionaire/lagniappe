"""Small shared validation and entity-value helpers for report actions."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities

TASK_FORM_TYPE_ERROR = "Create task actions require a task form."
PAGE_FORM_TYPE_ERROR = "Add form to page actions require a page form."
SUBMISSION_UPDATE_ROWS_ERROR = "Submission update action requires at least one update."


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason permission failures are covered through runner action handlers
def _require_allowed(allowed, message):
    if not allowed:
        raise exceptions.ValidationError(message)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason action data extraction is exercised by each handler
def _data(action):
    data = action.get("data") or {}
    if not isinstance(data, dict):
        raise exceptions.ValidationError("Action data must be an object.")
    return data


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @reason reference alias lookup is covered through endpoint resolution tests
def _first_data_reference(data, *roots):
    for root in roots:
        for key in (root, f"{root}_id", f"{root}_ref", f"{root}_action"):
            value = data.get(key)
            if value:
                return value
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_action_page
# @reason lookup normalization is covered through task creation and attachment tests
def _normalized_lookup_name(value):
    return " ".join(str(value or "").strip().casefold().split())


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason save-list deduplication supports report-run action results
def _unique_entities(entities):
    unique = []
    seen = set()
    for entity in entities:
        if entity is None:
            continue
        key = getattr(entity, "key", None) or id(entity)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entity)
    return unique


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason page form inheritance is verified through report-run page creation tests
def _category_form(category):
    if category is None:
        return None

    form_property = getattr(getattr(category, "properties", None), "form", None)
    if form_property is not None and getattr(form_property, "is_set", False):
        form = form_property.value
        if form is not None:
            return form

    form = getattr(category, "form", None)
    if form is not None:
        return form

    form_key = _stored_relation_key(category, "form")
    if not form_key:
        return None

    form = Entities.fetch_one(form_key, request=Fetch.direct())
    return form if isinstance(form, Entities.FORM) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/results.py::_task_structure_result
# @reason relation access failures are represented by omitted diagnostics
def _safe_entity_relation(entity, name):
    try:
        return getattr(entity, name, None)
    except Exception:
        return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/tasks.py::_create_task
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/entities.py::_add_form_to_page
# @reason mismatched form type behavior is covered through public report runner tests
def _require_form_type(form, expected_type, message):
    if form is None:
        return
    form_type = getattr(form, "form_type", None)
    if form_type and form_type != expected_type:
        raise exceptions.ValidationError(message)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/results.py::_entity_result
# @reason telemetry-only relation key projection is covered by result serialization
def _stored_relation_key(entity, name):
    relation = getattr(getattr(entity, "properties", None), name, None)
    if relation is not None:
        try:
            key = relation.key
        except Exception:
            key = None
        if key:
            return key

    db = getattr(entity, "db", None)
    if isinstance(db, dict):
        return db.get(name)
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_report_file
# @reason helper behavior is covered through public report runner file matching tests
def _unique_values(values):
    unique = []
    seen = set()
    for value in values:
        key = value if isinstance(value, (str, int, float, tuple)) else id(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique
