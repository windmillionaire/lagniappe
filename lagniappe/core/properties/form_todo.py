import json
from copy import deepcopy

from ..definitions import Ordering
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, SearchMixin
from .base_schema import SchemaProperty


# @testable true
# @tests tests_unit/test_003g_todo_lists.py::test_todo_list_validation_and_import
# @features form-todo
# @dimensions normalization validation
def _todo_items(value, *, allow_scalar=False):
    """Return canonical ordered to-do items from a supported value shape."""

    if value in (None, ""):
        return []

    if isinstance(value, str) and not allow_scalar:
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValidationError("To-do list submission must be valid JSON.") from error

    if isinstance(value, dict):
        value = value.get("items", [])
    elif allow_scalar and not isinstance(value, list):
        value = [value]

    if not isinstance(value, list):
        raise ValidationError("To-do list submission must contain an items list.")

    items = []
    for item in value:
        if allow_scalar and not isinstance(item, dict):
            item = {"text": item, "checked": False}
        if not isinstance(item, dict):
            raise ValidationError("Each to-do item must be an object.")

        text = item.get("text")
        checked = item.get("checked", False)
        if not isinstance(text, str):
            raise ValidationError("Each to-do item must contain text.")
        if not isinstance(checked, bool):
            raise ValidationError("Each to-do checked value must be a boolean.")

        text = text.strip()
        if text:
            items.append({"text": text, "checked": checked})

    return items


# @testable true
# @tests tests_unit/test_003g_todo_lists.py::test_todo_list_submission_projections
# @tests tests_unit/test_003g_todo_lists.py::test_todo_list_validation_and_import
# @features form-todo
# @dimensions submission db-value form-value ai-value search-value column import validation
class TodoList(SearchMixin, AIMixin, ColumnMixin, SchemaProperty):
    """Ordered single-line checklist stored as text/checked item objects."""

    _icon = "checklist"
    _ordering = Ordering.EXISTS
    repeating_default = False
    restore_on_uncomplete = False

    @property
    def value(self):
        return deepcopy(super().value) if self.is_set else None

    @value.setter
    def value(self, value):
        items = _todo_items(value)
        if items:
            SchemaProperty.value.fset(self, {"items": items})
        else:
            self.unset()

    def validate_submission(self, value):
        self.value = value

    def validate_ai(self, value):
        if value in (None, ""):
            self.unset()
            return
        items = _todo_items(value, allow_scalar=True)
        if items:
            SchemaProperty.value.fset(self, {"items": items})
        else:
            self.unset()

    def validate_import(self, value):
        try:
            items = _todo_items(value, allow_scalar=True)
            if items:
                SchemaProperty.value.fset(self, {"items": items})
            else:
                self.unset()
        except ValidationError as error:
            self.unset()
            self.errors.append(str(error))

    @property
    def items(self):
        return self.value.get("items", []) if self.value else []

    @property
    def form_value(self):
        return self.value

    @property
    def db_value(self):
        return self.value

    @db_value.setter
    def db_value(self, value):
        self.value = value

    @property
    def ai_value(self):
        return deepcopy(self.items) or None

    @property
    def search_key(self):
        return [self.label for _item in self.items]

    @property
    def search_value(self):
        return [item["text"] for item in self.items]

    @property
    def column_value(self):
        total = len(self.items)
        if not total:
            return None
        checked = sum(1 for item in self.items if item["checked"])
        return f"{checked} of {total} complete"

    @property
    def sort_value(self):
        return bool(self.items)
