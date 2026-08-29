from .base_columns import Columns
from .base_filters import Filters
from .common_entity import (
    Description,
    Modified,
    Name,
    IsPublic,
)
from .common_related import AttachedForm, Categories, RelatedForm
from .common_assets import Document
from .page_assets import Image
from ..mixins import ColumnMixin


# @testable true
# @tests tests_unit/test_007a_category_index.py::test_category_index
# @matrix category-index : columns table
class CategoryTable(Columns):
    _id = "table"
    _kind = "page"

    def __init__(self, *args, entity=None, **kwargs):
        self.column_fields = [Image, Name, AttachedForm, Description, Modified]
        self.default_selected = (Name, Modified)
        super().__init__(*args, entity=entity, **kwargs)

    @property
    def fields(self):
        if getattr(self, "_fields", None):
            return self._fields

        fields = {}
        for f in self.column_fields:
            field = f(entity=self.entity)
            fields[field.id] = field

        if self.entity.form:
            fields.update(
                {
                    f.id: f
                    for f in self.entity.form.fields.values()
                    if isinstance(f, ColumnMixin)
                }
            )

        fields["name"].selected = True
        fields["name"].parent = False
        fields["name"].link = True
        fields["modified"].selected = True

        self._fields = fields

        return self._fields


# @testable true
# @tests tests_unit/test_007_category_properties.py::test_category_filters
# @matrix category filters page : conditions entity-fields filter-value
class CategoryFilters(Filters):
    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, entity=entity, **kwargs)
        self.filter_kind = "page"
        self.filter_fields = [
            Name,
            Description,
            Categories,
            Document,
            Image,
            IsPublic,
            Modified,
        ]
        self._entity_fields = None

    @property
    def entity_fields(self):
        if self._entity_fields is not None:
            return self._entity_fields

        self._entity_fields = {}
        if self.entity.form:
            self._entity_fields[self.entity.form.hash] = RelatedForm(entity=self.entity)
            self._entity_fields[self.entity.form.hash].value = self.entity.form

        related_forms = [
            f for f in self.entity.forms if f.hash not in self._entity_fields.keys()
        ]
        for form in related_forms:
            self._entity_fields[form.hash] = RelatedForm(entity=self.entity)
            self._entity_fields[form.hash].value = form

        return self._entity_fields
