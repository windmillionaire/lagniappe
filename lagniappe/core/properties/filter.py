"""Filter-related properties for stored filter configurations."""

from ..mixins import RelatedEntityListMixin, RelatedEntityMixin
from .base_columns import Columns
from .base_db import DBProperty
from ..entities import Entities
from .category import CategoryTable
from .index import TaskTable


class ConditionEntities(RelatedEntityListMixin, DBProperty):
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
# @features filter
# @dimensions parent parent-hash
class FilterParent(RelatedEntityMixin, DBProperty):
    """The category or project that a saved filter applies to.

    Get:
        value (Entity): The Category or Project being filtered.
    """

    # Property Attributes
    _id = "parent"
    _label = "Parent"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        RelatedEntityMixin.value.fset(self, value)
        if value:
            self.entity.db["parent_hash"] = value.hash
        else:
            self.entity.db.pop("parent_hash", None)


class Creator(RelatedEntityMixin, DBProperty):
    """The user who created a saved filter.

    Get:
        value (Entity): The User entity who created this filter.
    """

    # Property Attributes
    _id = "creator"
    _label = "Creator"


# @testable true
# @tests tests_unit/test_011_filters.py::test_filter_table_derives_parent_fields_and_related_forms
# @features filter
# @dimensions table category project related-forms
class FilterTable(Columns):
    _id = "table"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        parent = self.entity.parent

        if isinstance(parent, Entities.CATEGORY):
            self.kind = "page"
            category_table = CategoryTable(entity=parent)
            self._fields = category_table.fields
            self._fields["name"].parent = False
        elif isinstance(parent, Entities.PROJECT):
            self.kind = "task"
            task_table = TaskTable(entity=parent)
            self._fields = task_table.fields
            self._fields["name"].parent = True

        self._fields["name"].selected = True

        for e in [e for e in self.entity.related if isinstance(e, Entities.FORM)]:
            self.update_fields(e.fields)
