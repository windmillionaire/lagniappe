from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..entities.category import Category

from .base_property import build_field
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
from ..mixins import ColumnMixin, FilterMixin


# @testable true
# @tests tests_unit/test_007a_category_index.py::test_category_index
# @matrix category-index : columns table
# @matrix form-migration : pending-projection removed-field typed-filter
class CategoryTable(Columns["Category"]):
    _id = "table"
    _kind = "page"

    def __init__(self, *args: object, entity: Category | None = None, **kwargs: object) -> None:
        self.column_fields = [Image, Name, AttachedForm, Description, Modified]
        self.default_selected = (Name, Modified)
        super().__init__(*args, entity=entity, **kwargs)

    @property
    def fields(self) -> dict[str, ColumnMixin]:
        if cached := getattr(self, "_fields", None):
            return cached

        fields = {}
        for f in self.column_fields:
            field = build_field(f, self.entity)
            fields[field.id] = field

        if self.entity.form and not self.entity.form.db.get("pending_form_change"):
            fields.update(
                {
                    f.id: f
                    for f in self.entity.form.fields.values()
                    if isinstance(f, ColumnMixin)
                }
            )

        name_field = cast(Name, fields["name"])
        name_field.selected = True
        name_field.parent = False
        name_field.link = True
        fields["modified"].selected = True

        self._fields = fields

        return self._fields


# @testable true
# @tests tests_unit/test_007_category_properties.py::test_category_filters
# @matrix category filters page : conditions entity-fields filter-value
class CategoryFilters(Filters["Category"]):
    def __init__(self, *args: object, entity: Category | None = None, **kwargs: object) -> None:
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
    def entity_fields(self) -> dict[str, FilterMixin]:
        if self._entity_fields is not None:
            return self._entity_fields

        self._entity_fields = {}
        if self.entity.form:
            field = RelatedForm(entity=self.entity)
            field.value = self.entity.form
            self._entity_fields[self.entity.form.hash] = field

        related_forms = [
            f for f in self.entity.forms if f.hash not in self._entity_fields
        ]
        for form in related_forms:
            field = RelatedForm(entity=self.entity)
            field.value = form
            self._entity_fields[form.hash] = field

        return self._entity_fields
