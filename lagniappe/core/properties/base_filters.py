from ..definitions import Action
from ..tools.auth.context import current_context_user
from .base_property import Property


# @testable infrastructure
# @covered-by lagniappe/core/properties/category.py::CategoryFilters
# @covered-by lagniappe/core/properties/project.py::ProjectFilters
# @covered-by lagniappe/core/properties/form.py::FormFilters.conditions
class Filters(Property):
    """Filter configuration for an entity's list view.

    Builds filter fields from ``filter_fields`` and optionally adds
    entity-specific fields (e.g. form fields) via ``entity_fields``.
    Generates condition metadata for the frontend filter UI.

    Get:
        fields (dict): {filter_key: FilterMixin field instance}.
        conditions (list[dict]): Filter condition metadata for the UI.
        entity_fields (dict): Additional entity-scoped filter fields.
    """

    _id = "filters"

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, entity=entity, **kwargs)
        self._entity_fields = None
        self._fields = None
        self._conditions = None
        self._conditions_user_key = None

    @property
    def value(self):
        return self

    @property
    def fields(self):
        if self._fields is not None:
            return self._fields

        self._fields = {}
        for f in self.filter_fields:
            field = f(entity=self.entity) if isinstance(f, type) else f
            field.filter_kind = self.filter_kind
            self._fields[field.filter_key] = field

        return self._fields

    @property
    def conditions(self):
        user = current_context_user()
        user_key = getattr(user, "key", None) or id(user)
        if self._conditions is not None and self._conditions_user_key == user_key:
            return self._conditions

        self._conditions = [
            {
                "field": f.filter_key,
                "label": f.filter_label,
                "kind": f.filter_kind,
                "icon": f.icon,
            }
            for f in self.fields.values()
        ]

        visible_entity_fields = self.visible_entity_fields
        if not visible_entity_fields:
            self._conditions_user_key = user_key
            return self._conditions

        for entity_field in visible_entity_fields.values():
            self._conditions.append(
                {
                    "field": entity_field.filter_key,
                    "label": entity_field.filter_label,
                    "kind": entity_field.filter_kind,
                    "icon": entity_field.icon,
                    "hash": entity_field.value.hash,
                    "key": entity_field.value.urlsafe_key,
                }
            )

        self._conditions_user_key = user_key
        return self._conditions

    @property
    def preload(self):
        return self.conditions

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_filter_conditions_include_only_viewable_entity_fields
    # @tests tests_unit/test_007_category_properties.py::test_category_filter_conditions_include_only_viewable_forms
    # @matrix category filters permissions project : conditions entity-fields view-access
    @property
    def visible_entity_fields(self):
        user = current_context_user()
        return {
            key: field
            for key, field in self.entity_fields.items()
            if field.value and field.value.allowed(Action.VIEW, user=user)
        }

    def reset(self):
        self._conditions = None
        self._conditions_user_key = None
        self._fields = None
        self._entity_fields = None
