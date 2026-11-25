from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast

from ..mixins.filter import FilterMixin

if TYPE_CHECKING:
    from ..entities.entity import Entity

from ..definitions import Action
from ..tools.auth.context import current_context_user
from .base_property import Property, build_field


class Filters[Owner: Entity = "Entity"](Property["Filters", Owner, "Filters | None"]):
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
    filter_fields: list[type[FilterMixin] | FilterMixin]
    filter_kind: str
    _fields: dict[str, FilterMixin] | None
    _conditions: list[dict[str, object]] | None
    _entity_fields: dict[str, FilterMixin] | None

    if TYPE_CHECKING:
        @property
        def entity_fields(self) -> Mapping[str, FilterMixin]: ...


    def __init__(self, *args: object, entity: Owner | None = None, **kwargs: object) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._entity_fields = None
        self._fields = None
        self._conditions = None
        self._conditions_user_key = None

    @property
    def value(self) -> Self:  # pyright: ignore[reportIncompatibleMethodOverride] -- The filter configuration is a read-only computed field.
        return self

    @property
    def fields(self) -> dict[str, FilterMixin]:
        if self._fields is not None:
            return self._fields

        self._fields = {}
        for f in self.filter_fields:
            field = build_field(f, self.entity) if isinstance(f, type) else f
            field.filter_kind = self.filter_kind
            self._fields[field.filter_key] = field

        return self._fields

    @property
    def conditions(self) -> list[dict[str, object]]:
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
            entity = cast("Entity", entity_field.value)
            self._conditions.append(
                {
                    "field": entity_field.filter_key,
                    "label": entity_field.filter_label,
                    "kind": entity_field.filter_kind,
                    "icon": entity_field.icon,
                    "hash": entity.hash,
                    "key": entity.urlsafe_key,
                }
            )

        self._conditions_user_key = user_key
        return self._conditions

    @property
    def preload(self) -> list[dict[str, object]]:
        return self.conditions

    @property
    def visible_entity_fields(self) -> dict[str, FilterMixin]:
        user = current_context_user()
        return {
            key: field
            for key, field in self.entity_fields.items()
            if (entity := cast("Entity | None", field.value)) and entity.allowed(Action.VIEW, user=user)
        }

    def reset(self) -> None:
        self._conditions = None
        self._conditions_user_key = None
        self._fields = None
        self._entity_fields = None
