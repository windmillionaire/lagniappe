import json

from flask import request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.filters import FilterCache
from lagniappe.core.tools.tasks.ordering import sort_tasks
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import filters


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::test
# @covered-by lagniappe/web/routes/filters/main.py::save
# @reason request parsing helper owned by filter preview/save endpoints
def _definitions_from_request():
    return [json.loads(d) for d in request.values.getlist("definition")]


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_filter_results_owner
# @reason filter definition shape helper is part of result-owner dispatch
def _definition_field(definition):
    return definition[1] if len(definition) > 1 else None


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_filter_results_owner
# @reason filter definition shape helper is part of entity-valued dispatch
def _definition_is_entity_valued(definition):
    return bool(definition[5]) if len(definition) > 5 else False


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_text_condition
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_number_condition
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_checkbox_condition
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_select_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_name
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_description
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_public_page
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_document_asset
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_text_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_number_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_checkbox_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_select_condition
# @features filters
# @dimensions string-condition boolean-condition number-condition select-condition attached-form run-results
def _filter_results_response(entity, definitions):
    new_filter = Entities.FILTER.create(entity, definitions, temporary=True)
    cache = FilterCache(new_filter.parent)
    cache.update(queue=False)
    results = cache.query(new_filter)
    new_filter.table.embedded = True

    return responses.table(results, new_filter)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name_exact
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_no_results
# @features filters
# @dimensions string-condition exact-match empty-results run-results
def _string_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable false
# @reason status branch delegates to common filter result rendering
# @features filters
# @dimensions boolean-condition completed in-progress run-results
def _status_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_due_date
# @features filters
# @dimensions date-condition run-results
def _date_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_assigned_user
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_model_task
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
# @features filters
# @dimensions entity-condition category model-task run-results
def _entity_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_multiple_conditions
# @features filters
# @dimensions compound run-results
def _compound_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_compound_filter_results_response
# @reason dispatch helper routes definitions to the focused filter result owners
def _filter_results_owner(definitions):
    if len(definitions) > 1:
        return _compound_filter_results_response

    field = _definition_field(definitions[0])
    if field == "name":
        return _string_filter_results_response
    if field == "completed":
        return _status_filter_results_response
    if field == "due_date":
        return _date_filter_results_response
    if field in {"categories", "assigned_to"} or _definition_is_entity_valued(
        definitions[0]
    ):
        return _entity_filter_results_response
    return _filter_results_response


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_filter_results_response
# @covered-by lagniappe/web/routes/filters/main.py::_compound_filter_results_response
# @reason endpoint coordinates request parsing while focused helpers own filter result behaviors
@filters.route("<key>/test", methods=["GET"])
@permission(requested=Action.VIEW)
def test(key, **kwargs):
    entity = kwargs["entity"]

    definitions = _definitions_from_request()
    if not definitions:
        return responses.error("Please add at least one filter condition")

    response_owner = _filter_results_owner(definitions)
    return response_owner(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_saved_in_progress_filter_removes_completed_task_after_back_navigation
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
# @features filters
# @dimensions save saved-filter reload-persistence
# @pair filters:saved-filter
@filters.route("<key>/save", methods=["POST"])
@permission(requested=Action.EDIT)
def save(key, **kwargs):
    entity = kwargs["entity"]

    definitions = [json.loads(d) for d in request.values.getlist("definition")]
    if not definitions:
        return responses.error("Please add at least one filter condition")

    new_filter = Entities.FILTER.create(entity, definitions)
    Entities.save(new_filter, entity)

    return responses.new_filter(new_filter)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
# @features filters
# @dimensions saved-filters reload-persistence shared-viewer
@filters.route("<key>/get", methods=["GET"])
@permission(requested=Action.VIEW)
def get(key, **kwargs):
    entity = kwargs["entity"]

    filters = [
        entity_filter
        for entity_filter in Entities.fetch(
            *database.get.filters(entity), request=Fetch.direct()
        )
        if entity_filter.related_entities_allowed(current_user)
    ]

    return responses.saved_filters(entity, filters)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @features filters
# @dimensions run-results
@filters.route("/<key>", methods=["GET"])
@permission(requested=Action.VIEW)
def run(key, **kwargs):
    filter = kwargs["entity"]
    Entities.fetch(
        filter,
        filter.parent,
        request=Fetch.direct(),
    )
    cache = FilterCache(filter.parent)

    cache.update(queue=False)
    results = cache.query(filter)

    if filter.parent.kind == "project":
        tasks = sort_tasks(results)
        return responses.filtered_task_index(tasks, filter)
    elif filter.parent.kind == "category":
        return responses.filtered_page_index(results, filter)


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_dynamic_entity_condition_response
# @reason common response builder is exercised through condition-kind owners
def _condition_options_response(updates, condition):
    return responses.filter_condition(updates, condition, options=True)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name_exact
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_name
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_description
# @features filters
# @dimensions string-condition exact-match
def _string_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable false
# @reason status branch delegates to common condition option rendering
# @features filters
# @dimensions boolean-condition completed in-progress
def _status_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_due_date
# @features filters
# @dimensions date-condition
def _date_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_assigned_user
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
# @features filters
# @dimensions entity-condition category assigned-user
def _entity_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_model_task
# @features filters
# @dimensions entity-condition model-task
def _dynamic_entity_condition_response(updates, condition, related_entity):
    if isinstance(related_entity, Entities.FORM):
        updates["form"] = related_entity.urlsafe_key
        updates["conditions"] = related_entity.filters.conditions

    return responses.filter_condition(updates, condition, filter=True)


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_dynamic_entity_condition_response
# @reason dispatch helper routes a condition to the focused condition-kind owners
def _condition_options_owner(condition):
    field = condition.field.filter_key
    if field == "name":
        return _string_condition_options_response
    if field == "completed":
        return _status_condition_options_response
    if field == "due_date":
        return _date_condition_options_response
    if field in {"categories", "assigned_to"} or condition.field.is_entity_valued:
        return _entity_condition_options_response
    return _condition_options_response


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_condition_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_dynamic_entity_condition_response
# @reason endpoint coordinates condition requests while focused helpers own condition-kind behavior
@filters.route("/<key>/condition", methods=["GET"])
@permission(requested=Action.VIEW)
def condition(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    field = request.values.get("field")
    parent = request.values.get("parent")
    value = request.values.get(f"{field}_value")
    entity_key = request.values.get(f"{field}_key")

    condition = Entities.CONDITION()
    condition.entity = (
        entity if parent == key else Entities.fetch_one(parent, request=Fetch.direct())
    )
    condition.field = value if value else field

    updates = {"parent": parent, "kind": condition.field.filter_kind, "field": field}

    if entity_key and value:
        related_entity = Entities.fetch_one(entity_key, request=Fetch.direct())
        condition.entity_map[related_entity.hash] = related_entity
        condition.set_value(value, default_comparator=None)

        return _dynamic_entity_condition_response(updates, condition, related_entity)

    response_owner = _condition_options_owner(condition)
    return response_owner(updates, condition)


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_filter_options_response
# @reason request value parsing helper is exercised through filter option owners
def _options_values(condition, field, comparator):
    if comparator == "BETWEEN":
        values = [
            request.values.get(f"{field}_value_from"),
            request.values.get(f"{field}_value_to"),
        ]
    else:
        values = [v for v in request.values.getlist(f"{field}_value") if v]

    if condition.field.is_entity_valued:
        related = Entities.fetch(*values, request=Fetch.root())
        condition.entity_map.update({e.hash: e for e in related})
        values = [e.hash for e in related]

    return values


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_text_condition
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_number_condition
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_checkbox_condition
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_select_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_public_page
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_document_asset
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_text_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_number_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_checkbox_condition
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_select_condition
# @features filters
# @dimensions string-condition boolean-condition number-condition select-condition attached-form
def _filter_options_response(updates, condition, values, comparator):
    if comparator == "BETWEEN" and len(values) < 2:
        return responses.error(f"{updates['field']} must have both a from and to value")
    elif not values:
        return responses.error(f"No value provided for {updates['field']}")

    try:
        condition.set_value(values, default_comparator=comparator)
    except Exception as e:
        return responses.error(f"Invalid value for {updates['field']}: {e}")

    return responses.filter_condition(updates, condition, filter=True)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name_exact
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_name
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_description
# @features filters
# @dimensions string-condition exact-match
def _string_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable false
# @reason status branch delegates to common filter option rendering
# @features filters
# @dimensions boolean-condition completed in-progress
def _status_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_due_date
# @features filters
# @dimensions date-condition
def _date_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_assigned_user
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
# @features filters
# @dimensions entity-condition category assigned-user
def _entity_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_filter_options_response
# @reason dispatch helper routes a condition to the focused option-kind owners
def _filter_options_owner(condition):
    field = condition.field.filter_key
    if field == "name":
        return _string_filter_options_response
    if field == "completed":
        return _status_filter_options_response
    if field == "due_date":
        return _date_filter_options_response
    if field in {"categories", "assigned_to"} or condition.field.is_entity_valued:
        return _entity_filter_options_response
    return _filter_options_response


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_string_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_status_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_date_filter_options_response
# @covered-by lagniappe/web/routes/filters/main.py::_entity_filter_options_response
# @reason endpoint coordinates option requests while focused helpers own option-kind behavior
@filters.route("/<key>/options", methods=["GET"])
@permission(requested=Action.VIEW)
def options(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    field = request.values.get("field")
    parent = request.values.get("parent")

    condition = Entities.CONDITION()
    condition.entity = (
        Entities.fetch_one(parent, request=Fetch.direct()) if parent != key else entity
    )
    condition.field = field

    comparator = request.values.get(f"{field}_comparator")
    updates = {
        "parent": parent,
        "field": field,
    }

    values = _options_values(condition, field, comparator)
    response_owner = _filter_options_owner(condition)
    return response_owner(updates, condition, values, comparator)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
# @features filters
# @dimensions delete saved-filters reload-persistence
@filters.route("/<key>/delete", methods=["DELETE"])
@permission(requested=Action.EDIT)
def delete(key, **kwargs):
    filter = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    parent = filter.parent

    Entities.delete(filter)
    Entities.save(parent)

    return responses.ok()
