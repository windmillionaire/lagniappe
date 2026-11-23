from typing import TypedDict


import json
from copy import deepcopy

from ..definitions import Ordering
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, SearchMixin
from .base_schema import SchemaProperty


class TodoItem(TypedDict):
    text: str
    checked: bool


class TodoValue(TypedDict):
    items: list[TodoItem]


# @testable true
# @tests tests_unit/test_003g_todo_lists.py::test_todo_list_validation_and_import
# @matrix form-todo : normalization validation
def _todo_items(value: object, *, allow_scalar: bool = False) -> list[TodoItem]:
    """Return canonical ordered todo items from a supported value shape."""

    if value in (None, ""):
        return []

    if isinstance(value, str) and not allow_scalar:
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValidationError("Todo list submission must be valid JSON.") from error

    if isinstance(value, dict):
        value = value.get("items", [])
    elif allow_scalar and not isinstance(value, list):
        value = [value]

    if not isinstance(value, list):
        raise ValidationError("Todo list submission must contain an items list.")

    items: list[TodoItem] = []
    for item in value:
        if allow_scalar and not isinstance(item, dict):
            item = {"text": item, "checked": False}
        if not isinstance(item, dict):
            raise ValidationError("Each todo item must be an object.")

        text = item.get("text")
        checked = item.get("checked", False)
        if not isinstance(text, str):
            raise ValidationError("Each todo item must contain text.")
        if not isinstance(checked, bool):
            raise ValidationError("Each todo checked value must be a boolean.")

        text = text.strip()
        if text:
            items.append({"text": text, "checked": checked})

    return items


# @testable true
# @tests tests_unit/test_003g_todo_lists.py::test_todo_list_submission_projections
# @tests tests_unit/test_003g_todo_lists.py::test_todo_list_validation_and_import
# @matrix form-todo : ai-value column db-value form-value import search-value submission validation
class TodoList(SearchMixin, AIMixin, ColumnMixin, SchemaProperty[TodoValue]):
    """Ordered single-line checklist stored as text/checked item objects."""

    _icon = "checklist"
    _ordering = Ordering.EXISTS

    @property
    def value(self) -> TodoValue | None:
        return deepcopy(super().value) if self.is_set else None

    @value.setter
    def value(self, value: object) -> None:
        items = _todo_items(value)
        if items:
            self._value = {"items": items}
        else:
            self.unset()

    def validate_submission(self, value: object) -> None:
        self.value = value

    def validate_ai(self, value: object) -> None:
        if value in (None, ""):
            self.unset()
            return
        items = _todo_items(value, allow_scalar=True)
        if items:
            self._value = {"items": items}
        else:
            self.unset()

    # @testable true
    # @tests tests_unit/test_003g_todo_lists.py::test_todo_list_validation_and_import
    # @tests tests_unit/test_006b_ingress_entity.py::test_importer_rejects_entire_malformed_todo_row
    # @matrix form-todo : import validation
    def validate_import(self, value: object) -> None:
        """Raise on malformed input so the importer rejects the whole row."""
        items = _todo_items(value, allow_scalar=True)
        if items:
            self._value = {"items": items}
        else:
            self.unset()

    @property
    def items(self) -> list[TodoItem]:  # pyright: ignore[reportIncompatibleMethodOverride] -- checklist items are a public read-only projection.
        return self.value.get("items", []) if self.value else []

    @property
    def form_value(self) -> TodoValue | None:
        return self.value

    @property
    def db_value(self) -> TodoValue | None:
        return self.value

    @db_value.setter
    def db_value(self, value: object) -> None:
        self.value = value

    @property
    def ai_value(self) -> TodoValue | None:
        return deepcopy(self.value) or None

    @property
    def search_key(self) -> list[str | None]:
        return [self.label for _item in self.items]

    @property
    def search_value(self) -> list[str]:
        return [item["text"] for item in self.items]

    @property
    def column_value(self) -> str | None:
        total = len(self.items)
        if not total:
            return None
        checked = sum(1 for item in self.items if item["checked"])
        return f"{checked} of {total} complete"

    @property
    def sort_value(self) -> bool:
        return bool(self.items)
