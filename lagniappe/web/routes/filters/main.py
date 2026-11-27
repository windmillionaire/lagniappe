from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from types import SimpleNamespace
from flask import request, url_for
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Comparator, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.mixins.date import DateMixin
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.filters import (
    FilterCache,
    FilterContractError,
    compile_filter_contract,
    parse_filter_request,
    resolve_allowed_value,
    resolve_filter_field,
)
from lagniappe.core.tools.tasks.ordering import sort_tasks
from lagniappe.core.tools.polling.projections import filter_result_revision
from lagniappe.web import responses
from lagniappe.web.auth import load_route_entity, permission

from . import filters


def _contract_from_request():
    return parse_filter_request(
        request.values.get("contract"),
        request.values.getlist("definition"),
    )


def _compiled_from_request(entity):
    return compile_filter_contract(entity, _contract_from_request(), current_user)


def _contract_error_response(error):
    if getattr(error, "status", 422) == 400:
        return responses.bad_request(str(error))
    return responses.error(str(error))


def _definition_field(definition):
    return definition.field


def _definition_is_entity_valued(definition):
    return definition.is_entity_valued


def _filter_results_response(entity, compiled):
    new_filter = Entities.FILTER.create(entity, compiled, temporary=True)
    if new_filter.parent is None:
        return responses.not_found("Filter parent not found")
    cache = FilterCache(new_filter.parent)
    cache.update(queue=False)
    results = cache.query(compiled)

    if request.values.get("mode") == "rows":
        if isinstance(entity, Entities.CATEGORY):
            category_index = entity.index()
            table_parent = SimpleNamespace(
                table=category_index.table,
                is_filter=True,
                route=category_index.route,
                append=None,
            )
            pages = [item for item in results if isinstance(item, Entities.PAGE)]
            return responses.rows(pages, table_parent)
        if isinstance(entity, Entities.PROJECT):
            project_index = entity.index()
            tasks = sort_tasks(
                [item for item in results if isinstance(item, Entities.TASK)]
            )
            table_parent = SimpleNamespace(
                table=project_index.table,
                is_filter=True,
                route=url_for("projects.tasks", key=entity.urlsafe_key),
                append=None,
            )
            return responses.rows(tasks, table_parent)

    new_filter.table.embedded = True

    return responses.table(results, new_filter)


def _string_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


def _status_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


def _date_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


def _entity_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


def _compound_filter_results_response(entity, definitions):
    return _filter_results_response(entity, definitions)


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


@filters.route("<key>/test", methods=["GET"])
@permission(requested=Action.VIEW, fingerprint=filter_result_revision)
def test(key: str, **kwargs: Unpack[EntityContext[Entity]]) -> ResponseReturnValue:
    entity = kwargs["entity"]
    try:
        compiled = _compiled_from_request(entity)
    except FilterContractError as error:
        return _contract_error_response(error)

    response_owner = _filter_results_owner(compiled.definitions)
    return response_owner(entity, compiled)


@filters.route("<key>/save", methods=["POST"])
@permission(requested=Action.EDIT)
def save(key: str, **kwargs: Unpack[EntityContext[models.Category | models.Project]]) -> ResponseReturnValue:
    entity = kwargs["entity"]
    try:
        compiled = _compiled_from_request(entity)
    except FilterContractError as error:
        return _contract_error_response(error)

    new_filter = Entities.FILTER.create(entity, compiled)
    Entities.save(new_filter, entity)

    if request.values.get("format") == "bar":
        return responses.saved_filter_bar_item(new_filter)
    return responses.new_filter(new_filter)


@filters.route("<key>/get", methods=["GET"])
@permission(requested=Action.VIEW)
def get(
    key: str, **kwargs: Unpack[EntityContext[models.Project | models.Category]]
) -> ResponseReturnValue:
    entity = load_route_entity(kwargs["entity"], request=Fetch.direct())
    filters = []
    can_edit = entity.allowed(Action.EDIT, user=current_user)
    for entity_filter in Entities.fetch(
        *database_get.filters(entity), request=Fetch.direct()
    ):
        if not isinstance(entity_filter, Entities.FILTER):
            continue
        try:
            entity_filter.compile(current_user)
            entity_filter.unavailable = False
            filters.append(entity_filter)
        except exceptions.ValidationError:
            if can_edit:
                entity_filter.unavailable = True
                filters.append(entity_filter)

    if request.values.get("format") == "bar":
        return responses.saved_filters_bar(filters)
    return responses.saved_filters(entity, filters)


@filters.route("/<key>", methods=["GET"])
@permission(requested=Action.VIEW, fingerprint=filter_result_revision)
def run(
    key: str, **kwargs: Unpack[EntityContext[models.Filter]]
) -> ResponseReturnValue:
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

    if filter.parent is None:
        return responses.not_found("Filter parent not found")
    cache = FilterCache(filter.parent)

    cache.update(queue=False)
    results = cache.query(compiled)

    if isinstance(filter.parent, Entities.PROJECT):
        tasks = sort_tasks([item for item in results if isinstance(item, Entities.TASK)])
        return responses.filtered_task_index(tasks, filter)
    return responses.filtered_page_index([item for item in results if isinstance(item, Entities.PAGE)], filter)


def _condition_options_response(updates, condition):
    return responses.filter_condition(updates, condition, options=True)


def _string_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


def _status_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


def _date_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


def _entity_condition_options_response(updates, condition):
    return _condition_options_response(updates, condition)


def _dynamic_entity_condition_response(updates, condition, related_entity):
    if isinstance(related_entity, Entities.FORM):
        updates["form"] = related_entity.urlsafe_key
        updates["conditions"] = related_entity.properties.filters.conditions

    return responses.filter_condition(updates, condition, filter=True)


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


@filters.route("/<key>/condition", methods=["GET"])
@permission(requested=Action.VIEW)
def condition(
    key: str, **kwargs: Unpack[EntityContext[models.Project | models.Category]]
) -> ResponseReturnValue:
    entity = load_route_entity(
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
            selected = condition.field
            if selected is None:
                raise FilterContractError("Filter field is unavailable.")
            updates["kind"] = selected.filter_kind
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

    if condition.field is None:
        return _contract_error_response(FilterContractError("Filter field is unavailable."))
    updates["kind"] = condition.field.filter_kind
    response_owner = _condition_options_owner(condition)
    return response_owner(updates, condition)


def _options_values(condition, field, comparator):
    if comparator == "BETWEEN":
        values = [
            request.values.get(f"{field}_value_from"),
            request.values.get(f"{field}_value_to"),
        ]
    else:
        values = [v for v in request.values.getlist(f"{field}_value") if v]

    return values


def _filter_options_response(updates, condition, values, comparator):
    field_label = (
        getattr(condition.field, "filter_label", None)
        or getattr(condition.field, "label", None)
        or updates["field"]
    )
    if comparator == "BETWEEN" and (len(values) < 2 or any(not v for v in values)):
        return responses.error(f"{field_label} must have both a from and to value.")
    elif not values:
        return responses.error(f"Enter a value for {field_label}.")

    try:
        if isinstance(condition.field, DateMixin):
            # Compile raw ISO date strings so contract.py expands whole-day
            # bounds in the acting user's timezone (e.g. EQUALS -> full local
            # day BETWEEN, LESS_EQUAL -> end of local day).
            try:
                comparator_value = Comparator[comparator or "EQUALS"].value
            except KeyError as error:
                raise FilterContractError(f"Unknown comparator: {comparator}") from error
            compiled = compile_filter_contract(
                condition._contract_parent,
                {
                    "version": 1,
                    "conditions": [
                        {
                            "source_id": condition.entity.hash,
                            "field": updates["field"],
                            "comparator": comparator_value,
                            "values": values,
                        }
                    ],
                },
                current_user,
            )
            entity_map = {entity.hash: entity for entity in compiled.related}
            condition = Entities.CONDITION.create(compiled.definitions[-1], entity_map)
            if not condition:
                raise FilterContractError("Filter condition is unavailable.")
        else:
            condition.set_value(values, default_comparator=comparator)
            condition = _validated_display_condition(condition._contract_parent, condition)
    except FilterContractError as error:
        return _contract_error_response(error)
    except Exception as e:
        return responses.error(f"Invalid value for {field_label}: {e}")

    return responses.filter_condition(updates, condition, filter=True)


def _string_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


def _status_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


def _date_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


def _entity_filter_options_response(updates, condition, values, comparator):
    return _filter_options_response(updates, condition, values, comparator)


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


@filters.route("/<key>/options", methods=["GET"])
@permission(requested=Action.VIEW)
def options(
    key: str, **kwargs: Unpack[EntityContext[models.Project | models.Category]]
) -> ResponseReturnValue:
    entity = load_route_entity(
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


@filters.route("/<key>/delete", methods=["DELETE"])
@permission(requested=Action.EDIT)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.Filter]]
) -> ResponseReturnValue:
    filter = load_route_entity(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    parent = filter.parent

    Entities.delete(filter)
    if parent is not None:
        Entities.save(parent)

    if request.values.get("format") == "bar":
        return responses.saved_filter_bar_deleted(parent)
    return responses.ok()
