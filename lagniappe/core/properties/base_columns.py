from ..mixins import ColumnMixin
from .base_property import Property


# @testable infrastructure
# @covered-by lagniappe/core/properties/index.py::TaskTable
# @covered-by lagniappe/core/properties/index.py::FormTable
# @covered-by lagniappe/core/properties/index.py::UserTable
# @covered-by lagniappe/core/properties/category.py::CategoryTable
class Columns(Property):
    """Table column configuration for an entity's list view.

    Builds a dict of ColumnMixin fields from ``column_fields`` and
    generates column metadata (title, icon, ordering, etc.) for the
    frontend table renderer.

    Get:
        fields (dict): {field_id: ColumnMixin field instance}.
        columns (list[dict]): Column metadata dicts for the UI.
        selected (list[str]): IDs of columns currently selected for display.
    """

    _id = "table"
    _embedded = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fields = None
        self._columns = None

    @property
    def value(self):
        return self

    @property
    def embedded(self):
        return self._embedded

    @embedded.setter
    def embedded(self, value):
        self._embedded = value

    @property
    def fields(self):
        if getattr(self, "_fields", None):
            return self._fields

        fields = {}
        for f in self.column_fields:
            field = f(entity=self.entity)
            fields[field.id] = field

        if not all(isinstance(f, ColumnMixin) for f in fields.values()):
            raise TypeError("All fields must inherit from ColumnMixin")

        self._fields = fields
        return fields

    def update_fields(self, fields):
        new_fields = {
            f_id: f
            for f_id, f in fields.items()
            if f_id not in self.fields and isinstance(f, ColumnMixin)
        }
        for field in new_fields.values():
            field.selected = False
        self.fields.update(new_fields)
        self._columns = None

    @property
    def selected(self):
        return [f.id for f in self.fields.values() if f.selected]

    @property
    def columns(self):
        if getattr(self, "_columns", None):
            return self._columns

        self._columns = [
            {
                "field": f.id,
                "title": f.label,
                "icon": f.icon,
                "ordering": f.ordering.value if getattr(f, "ordering", None) else None,
                "selected": getattr(f, "selected", False),
                "link": getattr(f, "link", True),
                "parent": getattr(f, "parent", True),
                "schema": f.schema if f.editable else None,
            }
            for f in self.fields.values()
        ]
        return self._columns

    @property
    def preload(self):
        return {"columns": self.columns, "selected": self.selected}
