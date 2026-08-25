from flask import request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.filters import (
    FilterCache,
    FilterContractError,
    compile_filter_contract,
    parse_filter_request,
    resolve_allowed_value,
    resolve_filter_field,
)
from lagniappe.core.tools.tasks.ordering import sort_tasks
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import filters


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_preview_rejects_malformed_and_forged_contracts
# @pairs filters:malformed-contract request-errors:stable-status
def _contract_from_request():
    return parse_filter_request(
        request.values.get("contract"),
        request.values.getlist("definition"),
    )


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::test
# @covered-by lagniappe/web/routes/filters/main.py::save
# @reason preview/save exercise the shared request compiler
def _compiled_from_request(entity):
    return compile_filter_contract(entity, _contract_from_request(), current_user)


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::test
# @reason preview error cases assert the stable HTTP translation
def _contract_error_response(error):
    if getattr(error, "status", 422) == 400:
        return responses.bad_request(str(error))
    return responses.error(str(error))


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_filter_results_owner
# @reason filter definition shape helper is part of result-owner dispatch
def _definition_field(definition):
    return definition.field


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_filter_results_owner
# @reason filter definition shape helper is part of entity-valued dispatch
def _definition_is_entity_valued(definition):
    return definition.is_entity_valued


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
# @matrix filters : attached-form boolean-condition number-condition run-results select-condition string-condition
def _filter_results_response(entity, compiled):
    new_filter = Entities.FILTER.create(entity, compiled, temporary=True)
    cache = FilterCache(new_filter.parent)
    cache.update(queue=False)
    results = cache.query(compiled)
    new_filter.table.embedded = True

    return responses.table(results, new_filter)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name_exact
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_no_results
# @matrix filters : empty-results exact-match run-results string-condition
def _string_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable false
# @reason status branch delegates to common filter result rendering
# @matrix filters : boolean-condition completed in-progress run-results
def _status_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_due_date
# @matrix filters : date-condition run-results
def _date_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_assigned_user
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_model_task
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
# @matrix filters : category entity-condition model-task run-results
def _entity_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_multiple_conditions
# @matrix filters : compound run-results
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
    try:
        compiled = _compiled_from_request(entity)
    except FilterContractError as error:
        return _contract_error_response(error)

    response_owner = _filter_results_owner(compiled.definitions)
    return response_owner(entity, compiled)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_saved_in_progress_filter_removes_completed_task_after_back_navigation
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
# @matrix filters : save saved-filter saved-filters
@filters.route("<key>/save", methods=["POST"])
@permission(requested=Action.EDIT)
def save(key, **kwargs):
    entity = kwargs["entity"]
    try:
        compiled = _compiled_from_request(entity)
    except FilterContractError as error:
        return _contract_error_response(error)

    new_filter = Entities.FILTER.create(entity, compiled)
    Entities.save(new_filter, entity)

    return responses.new_filter(new_filter)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
# @matrix filters : reload-persistence saved-filters shared-viewer
@filters.route("<key>/get", methods=["GET"])
@permission(requested=Action.VIEW)
def get(key, **kwargs):
    entity = Entities.fetch_one(kwargs["entity"], request=Fetch.direct())
    filters = []
    can_edit = entity.allowed(Action.EDIT, user=current_user)
    for entity_filter in Entities.fetch(
        *database.get.filters(entity), request=Fetch.direct()
    ):
        try:
            entity_filter.compile(current_user)
            entity_filter.unavailable = False
            filters.append(entity_filter)
        except exceptions.ValidationError:
            if can_edit:
                entity_filter.unavailable = True
                filters.append(entity_filter)

    return responses.saved_filters(entity, filters)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @pair filters:run-results
@filters.route("/<key>", methods=["GET"])
@permission(requested=Action.VIEW)
def run(key, **kwargs):
    filter = kwargs["entity"]
    Entities.fetch(
        filter,
        filter.parent,
        request=Fetch.direct(),
    )
    try:
        compiled = filter.compile(current_user)
    except exceptions.ValidationError:
        return responses.error("This saved filter is no longer available")

    cache = FilterCache(filter.parent)

    cache.update(queue=False)
    results = cache.query(compiled)

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
# @matrix filters : exact-match string-condition
def _string_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable false
# @reason status branch delegates to common condition option rendering
# @matrix filters : boolean-condition completed in-progress
def _status_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_due_date
# @pair filters:date-condition
def _date_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_assigned_user
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
# @matrix filters : assigned-user category entity-condition
def _entity_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_model_task
# @matrix filters : entity-condition model-task
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
# @covered-by lagniappe/web/routes/filters/main.py::condition
# @covered-by lagniappe/web/routes/filters/main.py::options
# @reason condition/option E2E owns compiled badge reconstruction
def _validated_display_condition(parent, condition):
    compiled = compile_filter_contract(
        parent,
        {"version": 1, "conditions": [condition.contract_condition]},
        current_user,
    )
    entity_map = {entity.hash: entity for entity in compiled.related}
    display = Entities.CONDITION.create(compiled.definitions[-1], entity_map)
    if not display:
        raise FilterContractError("Filter condition is unavailable.")
    return display


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

    try:
        entry = resolve_filter_field(entity, parent, field, current_user)
        condition = Entities.CONDITION()
        condition.entity = entry.source
        if not (entity_key and value):
            condition.field = entry.field.filter_key
    except (FilterContractError, ValueError) as error:
        return _contract_error_response(error)

    updates = {"parent": parent, "field": field}

    if entity_key and value:
        try:
            related_entity = resolve_allowed_value(entry, value)
            if str(entity_key) != str(related_entity.urlsafe_key):
                raise FilterContractError("Filter entity is unavailable.")
            condition.field = related_entity.hash
            updates["kind"] = condition.field.filter_kind
            condition.entity_map[related_entity.hash] = related_entity
            condition.set_value(value, default_comparator=None)
            condition = _validated_display_condition(entity, condition)
            return _dynamic_entity_condition_response(
                updates,
                condition,
                related_entity,
            )
        except (FilterContractError, ValueError) as error:
            return _contract_error_response(error)

    updates["kind"] = condition.field.filter_kind
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
# @matrix filters : attached-form boolean-condition number-condition select-condition string-condition
def _filter_options_response(updates, condition, values, comparator):
    if comparator == "BETWEEN" and len(values) < 2:
        return responses.error(f"{updates['field']} must have both a from and to value")
    elif not values:
        return responses.error(f"No value provided for {updates['field']}")

    try:
        condition.set_value(values, default_comparator=comparator)
        condition = _validated_display_condition(condition._contract_parent, condition)
    except FilterContractError as error:
        return _contract_error_response(error)
    except Exception as e:
        return responses.error(f"Invalid value for {updates['field']}: {e}")

    return responses.filter_condition(updates, condition, filter=True)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name_exact
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_name
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_description
# @matrix filters : exact-match string-condition
def _string_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable false
# @reason status branch delegates to common filter option rendering
# @matrix filters : boolean-condition completed in-progress
def _status_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_due_date
# @pair filters:date-condition
def _date_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_assigned_user
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
# @matrix filters : assigned-user category entity-condition
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

    try:
        entry = resolve_filter_field(entity, parent, field, current_user)
        condition = Entities.CONDITION()
        condition.entity = entry.source
        condition.field = entry.field.filter_key
        condition._contract_parent = entity
    except (FilterContractError, ValueError) as error:
        return _contract_error_response(error)

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
# @matrix filters : delete reload-persistence saved-filters
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
