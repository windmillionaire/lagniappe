"""Task-form to-do list field behavior and lifecycle rules."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.form_todo import TodoList
from lagniappe.core.properties.schema import SchemaValidationError, canonicalize_schema
from testing.utility.test_entities import TestEntities


def _todo_field():
    return TodoList(
        {"id": "todo-work", "title": "Work", "type": "todo"},
        entity=SimpleNamespace(entity_kind="task"),
    )


# @features form-todo
# @dimensions submission db-value form-value ai-value search-value column
@pytest.mark.unit
def test_todo_list_submission_projections():
    field = _todo_field()
    field.validate_submission(
        json.dumps(
            {
                "items": [
                    {"text": "  First step  ", "checked": True},
                    {"text": "Second step", "checked": False},
                ]
            }
        )
    )

    expected = {
        "items": [
            {"text": "First step", "checked": True},
            {"text": "Second step", "checked": False},
        ]
    }
    assert field.value == expected
    assert field.form_value == expected
    assert field.db_value == expected
    assert field.ai_value == expected["items"]
    assert field.search_key == ["Work", "Work"]
    assert field.search_value == ["First step", "Second step"]
    assert field.column_value == "1 of 2 complete"
    assert field.sort_value is True

    external = field.value
    external["items"][0]["text"] = "Changed outside"
    assert field.value == expected


# @features form-todo
# @dimensions validation import ai-value normalization
@pytest.mark.unit
def test_todo_list_validation_and_import():
    field = _todo_field()

    field.validate_ai(["One", "Two"])
    assert field.value == {
        "items": [
            {"text": "One", "checked": False},
            {"text": "Two", "checked": False},
        ]
    }

    field.validate_import("Imported item")
    assert field.value == {
        "items": [{"text": "Imported item", "checked": False}]
    }

    field.validate_submission({"items": [{"text": "  ", "checked": False}]})
    assert field.value is None
    assert field.form_value is None
    assert field.column_value is None
    assert field.sort_value is False

    with pytest.raises(ValidationError, match="checked value must be a boolean"):
        field.validate_submission({"items": [{"text": "Bad", "checked": "yes"}]})
    with pytest.raises(ValidationError, match="valid JSON"):
        field.validate_submission("not-json")


# @pairs form-schema:form-type form-todo:task-only
@pytest.mark.unit
def test_todo_schema_is_task_only():
    schema = [{"id": "todo-work", "title": "Work", "type": "todo"}]

    assert canonicalize_schema(schema, form_type="task") == schema
    with pytest.raises(SchemaValidationError, match="only on task forms"):
        canonicalize_schema(schema, form_type="page")
    assert canonicalize_schema(
        schema,
        form_type="page",
        discard_invalid=True,
    ) == []


def _todo_task(hash_suffix):
    task = TestEntities.get(
        "TASK",
        {
            "name": "Checklist task",
            "hash": f"todo_task_{hash_suffix}",
            "page": {"name": "Parent", "hash": f"todo_parent_{hash_suffix}"},
            "form": {"name": "Checklist", "hash": f"todo_form_{hash_suffix}"},
        },
    )
    task.form.schema = [
        {
            "id": "repeat-note",
            "title": "Repeat note",
            "type": "input",
            "input": "text",
        },
        {"id": "todo-work", "title": "Work", "type": "todo"},
    ]
    return task


# @pairs submission:repeating-default form-todo:repeating-default
@pytest.mark.unit
def test_todo_list_cannot_be_saved_as_repeating_default():
    task = _todo_task("default")
    submission = task.properties.submission
    submission.value = {
        "todo-work": {"items": [{"text": "Old work", "checked": True}]}
    }

    with pytest.raises(ValidationError, match="cannot repeat automatically"):
        task.save_default_field("todo-work", submission)
    assert task.default_submission == {}


# @pairs task-completion:history task-completion:repeating-default
# @pair form-todo:field-reset
@pytest.mark.unit
def test_uncomplete_archives_then_clears_todo_items():
    task = _todo_task("uncomplete")
    current = {
        "repeat-note": "Keep this",
        "todo-work": {
            "items": [
                {"text": "Finished step", "checked": True},
                {"text": "Open step", "checked": False},
            ]
        },
    }
    task.properties.submission.value = current
    task.db["default_submission"] = json.dumps(current)
    task.completed = True
    archived = []

    def capture_history(**_kwargs):
        archived.append(deepcopy(task.submission))

    with patch.object(task, "create_history_entry", side_effect=capture_history):
        task.uncomplete()

    assert archived == [current]
    assert task.submission == {"repeat-note": "Keep this"}
    assert "todo-work" not in task.default_submission
