"""Filter-related properties for stored filter configurations."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..entities.category import Category
    from ..entities.entity import Entity  # noqa: F401 -- forward reference in field bases.
    from ..entities.filter import Filter
    from ..entities.project import Project
    from ..entities.user import User  # noqa: F401 -- forward reference in field bases.

from .common_entity import Name
from ..mixins import RelatedEntityListMixin, RelatedEntityMixin
from .base_columns import Columns
from .base_db import DBProperty
from ..entities import Entities
from .category import CategoryTable
from .index import TaskTable


class ConditionEntities(RelatedEntityListMixin, DBProperty["list[Entity]", "Filter"]):
    """Entities referenced by a filter's conditions.

    Filter conditions reference entities (categories, projects, forms)
    by hash. This property loads them so conditions can display labels
    and validate against live data.

    Get:
        value (list): Referenced Entity objects.
    """

    # Property Attributes
    _id = "related"


# @testable true
# @tests tests_unit/test_011_filters.py::test_filter_parent_sets_parent_hash
# @matrix filter : parent parent-hash
class FilterParent(RelatedEntityMixin["Category | Project"], DBProperty["Category | Project", "Filter"]):
    """The category or project that a saved filter applies to.

    Get:
        value (Entity): The Category or Project being filtered.
    """

    # Property Attributes
    _id = "parent"
    _label = "Parent"

    @property
    def value(self) -> Category | Project | None:
        return super().value

    @value.setter
    def value(self, value: Category | Project | None) -> None:
        self._write_related(value)
        if value:
            self.entity.db["parent_hash"] = value.hash
        else:
            self.entity.db.pop("parent_hash", None)


class Creator(RelatedEntityMixin["User"], DBProperty["User", "Filter"]):
    """The user who created a saved filter.

    Get:
        value (Entity): The User entity who created this filter.
    """

    # Property Attributes
    _id = "creator"
    _label = "Creator"


# @testable true
# @tests tests_unit/test_011_filters.py::test_filter_table_derives_parent_fields_and_related_forms
# @matrix filter : category project related-forms table
# @matrix form-migration : pending-projection removed-field typed-filter
class FilterTable(Columns["Filter"]):
    _id = "table"

    def __init__(self, *args: object, entity: Filter | None = None, **kwargs: object) -> None:
        super().__init__(*args, entity=entity, **kwargs)

        parent = self.entity.parent

        if isinstance(parent, Entities.CATEGORY):
            self.kind = "page"
            category_table = CategoryTable(entity=parent)
            self._fields = category_table.fields
            cast(Name, self._fields["name"]).parent = False
        elif isinstance(parent, Entities.PROJECT):
            self.kind = "task"
            task_table = TaskTable(entity=parent)
            self._fields = task_table.fields
            cast(Name, self._fields["name"]).parent = True

        if self._fields is None:
            raise TypeError("Filter table requires a category or project parent")
        self._fields["name"].selected = True

        for e in [e for e in self.entity.related if isinstance(e, Entities.FORM)]:
            if not e.db.get("pending_form_change"):
                self.update_fields(e.fields)
