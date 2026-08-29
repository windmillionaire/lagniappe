"""Focused contracts for AI-driven shared-cache workspace filters."""

from datetime import datetime, time, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Comparator,
    FieldType,
    FilterOptions,
)
from lagniappe.core.tools.ai import ask
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai.function_definitions import workspace_filter
from lagniappe.core.tools.filters import ai_query
from lagniappe.core.tools.filters import contract
from testing.utility.test_entities import TestEntities


class _Field:
    def __init__(
        self,
        key,
        field_type,
        options,
        *,
        label=None,
        entity_valued=False,
        choices=None,
        value=None,
    ):
        self.filter_key = key
        self.filter_label = label or key.replace("_", " ").title()
        self.field_type = field_type
        self.field_options = options
        self.is_entity_valued = entity_valued
        self.choices = choices
        self.value = value


class _Entity:
    def __init__(
        self,
        kind,
        hash_value,
        name,
        *,
        allowed=True,
        filters=None,
        active=True,
        modified=None,
        due_date=None,
    ):
        self.kind = kind
        self.hash = hash_value
        self.name = name
        self.reserved = False
        self.filters = filters or SimpleNamespace(fields={}, entity_fields={})
        self.active = active
        self.modified = modified
        self.due_date = due_date
        self._allowed = allowed
        self.to_ai_users = []

    def allowed(self, _action, user=None):
        return self._allowed

    def to_ai(self, user):
        self.to_ai_users.append(user)
        return {
            "kind": self.kind,
            "hash": f"hash:{self.hash}",
            "name": self.name,
        }


def _workspace_filter_fixture():
    completed = _Field(
        "completed",
        FieldType.BOOLEAN,
        FilterOptions.COMPLETED.value,
        label="Completed",
    )
    due_date = _Field(
        "due_date",
        FieldType.TIMESTAMP,
        FilterOptions.DATE.value,
        label="Due Date",
    )
    name = _Field(
        "name",
        FieldType.STRING,
        FilterOptions.STRING.value,
        label="Task Name",
    )
    total = _Field(
        "input-total",
        FieldType.NUMBER,
        FilterOptions.NUMBER.value,
        label="Total",
    )
    status = _Field(
        "select-status",
        FieldType.STRING,
        FilterOptions.LIST.value,
        label="Status",
        choices={"open": "Open", "paid": "Paid"},
    )
    form = _Entity(
        "form",
        "invoice-form",
        "Invoice",
        filters=SimpleNamespace(
            fields={"input-total": total, "select-status": status},
            entity_fields={},
        ),
    )
    hidden_form = _Entity("form", "hidden-form", "Hidden", allowed=False)
    model = _Entity("model", "invoice-model", "Review Invoice")
    model_field = _Field(
        "model",
        FieldType.STRING,
        FilterOptions.STRING.value,
        entity_valued=True,
        value=model,
    )
    form_field = _Field(
        "form",
        FieldType.STRING,
        FilterOptions.STRING.value,
        entity_valued=True,
        value=form,
    )
    hidden_form_field = _Field(
        "form",
        FieldType.STRING,
        FilterOptions.STRING.value,
        entity_valued=True,
        value=hidden_form,
    )
    project = _Entity(
        "project",
        "project-one",
        "Accounts Payable",
        filters=SimpleNamespace(
            fields={
                "completed": completed,
                "due_date": due_date,
                "name": name,
            },
            entity_fields={
                "invoice-model": model_field,
                "invoice-form": form_field,
                "hidden-form": hidden_form_field,
            },
        ),
    )
    return project, model, form, hidden_form


# @matrix ai-filter : permissions schema
@pytest.mark.unit
def test_describe_filter_fields_exposes_parent_relations_and_form_fields():
    user = object()
    project, model, form, hidden_form = _workspace_filter_fixture()

    schema = ai_query.describe_filter_fields(project, user)

    assert schema["parent"] == {
        "kind": "project",
        "hash": "hash:project-one",
        "name": "Accounts Payable",
    }
    assert schema["result_kind"] == "task"
    fields = {
        (field["source"]["hash"], field["field"]): field
        for field in schema["fields"]
    }
    assert fields[("hash:project-one", "completed")]["comparators"] == [
        "is_false",
        "is_true",
    ]
    assert fields[("hash:project-one", "model")]["comparators"] == ["eq", "in"]
    assert fields[("hash:project-one", "model")]["allowed_values"] == [
        {"kind": "model", "hash": "hash:invoice-model", "name": "Review Invoice"}
    ]
    assert fields[("hash:project-one", "form")]["allowed_values"] == [
        {"kind": "form", "hash": "hash:invoice-form", "name": "Invoice"}
    ]
    assert fields[("hash:invoice-form", "input-total")]["type"] == "number"
    assert fields[("hash:invoice-form", "select-status")]["choices"] == [
        {"value": "open", "label": "Open"},
        {"value": "paid", "label": "Paid"},
    ]
    assert all(
        field["source"]["hash"] != f"hash:{hidden_form.hash}"
        for field in schema["fields"]
    )


# @matrix ai-filter : integration schema
@pytest.mark.unit
def test_describe_filter_fields_uses_real_project_and_form_filter_surfaces():
    user = object()
    project = ai_query.Entities.PROJECT(temporary=True)
    project.name = "Real Project"
    project.properties.hash._value = "real-project"
    project.kind = "project"
    form = TestEntities.get(
        "FORM",
        {"name": "Real Form", "hash": "real-form"},
    )
    form.form_type = "task"
    form.schema = [
        {
            "id": "input-amount",
            "type": "input",
            "input": "number",
            "title": "Amount",
        }
    ]
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Real Model", "hash": "real-model"},
        project=project,
    )
    model.form = form
    project.properties.model_tasks._value = [model]
    for entity in (project, model, form):
        entity.allowed = lambda _action, user=None: True

    schema = ai_query.describe_filter_fields(project, user)
    fields = {
        (field["source"]["hash"], field["field"]): field
        for field in schema["fields"]
    }

    assert ("hash:real-project", "completed") in fields
    assert fields[("hash:real-project", "categories")]["comparators"] == [
        "contains",
        "contains_any",
    ]
    assert ("hash:real-project", "model") in fields
    assert fields[("hash:real-project", "model")]["allowed_values"][0]["hash"] == (
        "hash:real-model"
    )
    assert fields[("hash:real-project", "form")]["allowed_values"][0]["hash"] == (
        "hash:real-form"
    )
    assert fields[("hash:real-form", "input-amount")]["type"] == "number"


# @matrix ai-filter : compilation validation
@pytest.mark.unit
def test_compile_filter_definitions_normalizes_dates_numbers_and_booleans(monkeypatch):
    user = object()
    project, _model, form, _hidden_form = _workspace_filter_fixture()
    monkeypatch.setattr(
        contract.dates,
        "user_timezone",
        lambda _user=None: timezone.utc,
    )

    definitions = ai_query.compile_filter_definitions(
        project,
        [
            {"field": "completed", "comparator": "is_false", "values": []},
            {
                "field": "due_date",
                "comparator": "lte",
                "values": ["2026-07-31"],
            },
            {
                "source_id": f"hash:{form.hash}",
                "field": "input-total",
                "comparator": "gt",
                "values": ["100.25"],
            },
            {
                "source_id": form.hash,
                "field": "select-status",
                "comparator": "in",
                "values": ["Paid"],
            },
        ],
        user,
    )

    assert [definition.field for definition in definitions] == [
        "completed",
        "due_date",
        "form",
        "input-total",
        "select-status",
    ]
    assert definitions[0].comparator == Comparator.IS_FALSE
    assert definitions[0].value is None
    expected_end = datetime.combine(
        datetime(2026, 7, 31).date(),
        time.max,
        tzinfo=timezone.utc,
    ).timestamp()
    assert definitions[1].comparator == Comparator.LESS_EQUAL
    assert definitions[1].value == expected_end
    assert definitions[2].value == form.hash
    assert definitions[2].is_entity_valued is True
    assert definitions[3].field_type == FieldType.NUMBER
    assert definitions[3].value == 100.25
    assert definitions[4].value == ["paid"]


# @matrix ai-filter : compilation permissions validation
@pytest.mark.unit
def test_compile_filter_definitions_rejects_unknown_fields_comparators_and_values(
    monkeypatch,
):
    user = object()
    project, model, form, _hidden_form = _workspace_filter_fixture()

    with pytest.raises(exceptions.ValidationError, match="unavailable field"):
        ai_query.compile_filter_definitions(
            project,
            [{"field": "imaginary", "comparator": "eq", "values": ["x"]}],
            user,
        )

    with pytest.raises(
        exceptions.ValidationError,
        match=rf"input-total.*hash:{form.hash}",
    ):
        ai_query.compile_filter_definitions(
            project,
            [
                {
                    "source_id": "wrong-source",
                    "field": "input-total",
                    "comparator": "gt",
                    "values": ["100"],
                }
            ],
            user,
        )

    with pytest.raises(exceptions.ValidationError, match="not valid for name"):
        ai_query.compile_filter_definitions(
            project,
            [{"field": "name", "comparator": "not_in", "values": ["x"]}],
            user,
        )

    unrelated = _Entity("model", "other-model", "Other")
    monkeypatch.setattr(
        ai_query.Entities,
        "fetch_one",
        lambda value, request: unrelated if value == unrelated.hash else model,
    )
    with pytest.raises(exceptions.ValidationError, match="not valid for model"):
        ai_query.compile_filter_definitions(
            project,
            [
                {
                    "field": "model",
                    "comparator": "eq",
                    "values": [unrelated.hash],
                }
            ],
            user,
        )


# @matrix ai-filter : cache-query output permissions
@pytest.mark.unit
def test_query_workspace_filter_uses_shared_cache_and_permission_filters_results(
    monkeypatch,
):
    user = object()
    project, _model, _form, _hidden_form = _workspace_filter_fixture()
    visible = _Entity(
        "task",
        "visible-task",
        "Visible",
        modified=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    older = _Entity(
        "task",
        "older-task",
        "Older",
        modified=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    hidden = _Entity(
        "task",
        "hidden-task",
        "Hidden",
        allowed=False,
        modified=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    inactive = _Entity(
        "task",
        "inactive-task",
        "Inactive",
        active=False,
        modified=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
    calls = {}

    class FakeFilterCache:
        def __init__(self, parent, user=None):
            calls["init"] = (parent, user)
            self.cache_key = f"filter:{parent.hash}:all"

        def update(self, queue=True):
            calls["update"] = queue

        def query(self, entity_filter):
            calls["definitions"] = entity_filter.definitions
            return [hidden, older, inactive, visible]

    monkeypatch.setattr(ai_query, "FilterCache", FakeFilterCache)

    result = ai_query.query_workspace_filter(
        project,
        [{"field": "name", "comparator": "substring", "values": ["task"]}],
        user,
        limit=1,
    )

    assert calls["init"] == (project, user)
    assert calls["update"] is False
    assert calls["definitions"][0].field == "name"
    assert result["matched"] == 2
    assert result["returned"] == 1
    assert result["truncated"] is True
    assert result["results"] == [
        {"kind": "task", "hash": "hash:visible-task", "name": "Visible"}
    ]
    assert visible.to_ai_users == [user]
    assert hidden.to_ai_users == []
    assert inactive.to_ai_users == []


# @matrix ai-filter : permissions tool-handler validation
@pytest.mark.unit
def test_filter_tool_handlers_load_viewable_parents_and_return_validation_errors(
    monkeypatch,
):
    user = object()
    project, _model, _form, _hidden_form = _workspace_filter_fixture()
    monkeypatch.setattr(
        workspace_filter.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: project,
    )
    monkeypatch.setattr(
        workspace_filter,
        "describe_filter_fields",
        lambda parent, current_user: {"parent": parent.hash, "user": current_user},
    )
    monkeypatch.setattr(
        workspace_filter,
        "query_workspace_filter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            exceptions.ValidationError("bad condition")
        ),
    )

    schema_result = workspace_filter.execute_get_filter_schema(
        {"parent_id": project.hash},
        user,
    )
    assert schema_result == {
        "parent": project.hash,
        "user": user,
    }
    assert workspace_filter.execute_query_workspace_filter(
        {"parent_id": project.hash, "conditions": []},
        user,
    ) == {"error": "bad condition"}
    assert workspace_filter.execute_get_filter_schema({}, user) == {
        "error": "parent_id is required"
    }

    project._allowed = False
    denied_result = workspace_filter.execute_get_filter_schema(
        {"parent_id": project.hash},
        user,
    )
    assert denied_result == {
        "error": "Access denied"
    }


@pytest.mark.unit
def test_filter_tools_are_registered_for_ask():
    assert (
        ai_functions.DECLARATIONS["get_filter_schema"]
        is workspace_filter.GET_FILTER_SCHEMA
    )
    assert (
        ai_functions.DECLARATIONS["query_workspace_filter"]
        is workspace_filter.QUERY_WORKSPACE_FILTER
    )
    assert (
        ai_functions.HANDLERS["get_filter_schema"]
        is workspace_filter.execute_get_filter_schema
    )
    assert (
        ai_functions.HANDLERS["query_workspace_filter"]
        is workspace_filter.execute_query_workspace_filter
    )
    assert "get_filter_schema" in ask.ASK_READ_ONLY_CONTEXT_TOOLS
    assert "query_workspace_filter" in ask.ASK_READ_ONLY_CONTEXT_TOOLS
