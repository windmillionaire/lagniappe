from collections.abc import Iterable
from typing import TYPE_CHECKING, Self, cast

import json
import hashlib

from flask import url_for
from flask_login import current_user

from ..definitions import Action, Fetch, FilterDefinition
from ..entities import Entities
from ..properties import filter
from ..tools.auth.context import current_context_user
from .condition import Condition
from .entity import Entity, EntityProperties


if TYPE_CHECKING:
    from ..mixins.field_host import FieldUser
    from ..tools.database.get import Identifier
    from ..tools.filters.contract import CompiledFilter
    from . import property_types
    from .user import User
    from .category import Category
    from .project import Project


# @testable false
# @covered-by lagniappe/core/entities/filter.py::Filter.conditions
class Filter(Entity):
    if TYPE_CHECKING:
        parent: Category | Project | None
        creator: User | None
        related: list[Entity]

        @property
        def table(self) -> filter.FilterTable: ...

        @property
        def properties(self) -> property_types.FilterProperties: ...

    entity_kind = "filter"

    def __init__(
        self, *args: Identifier, temporary: bool | None = None,
        testing: bool | None = None, parent: Identifier = None, **kwargs: object,
    ) -> None:
        super().__init__(*args, temporary=temporary, testing=testing, parent=parent, **kwargs)
        self._conditions: list[Condition] | None = None
        self._definitions: list[FilterDefinition] | None = None
        self._compiled_filters: dict[str | int, CompiledFilter] = {}
        self._compiled_related: list[Entity] | None = None

    @property
    def is_filter(self) -> bool:
        return True

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_fingerprint_uses_loaded_parent_fingerprint
    # @matrix filter : fingerprint parent
    @property
    def fingerprint(self) -> str:
        fingerprint = super().fingerprint
        parent = self.parent
        parent_fingerprint = parent.fingerprint if parent else fingerprint
        return hashlib.md5(
            f"{fingerprint}:{parent_fingerprint}".encode()
        ).hexdigest()

    @property
    def _filter_parent(self) -> Category | Project:
        if self.parent is None:
            raise AttributeError("Filter requires a parent")
        return self.parent

    @property
    def required(self) -> list[str]:
        if self.creator is None:
            raise AttributeError("Filter requires a creator")
        return [self.hash, self._filter_parent.hash, self.creator.hash]

    @property
    def url(self) -> str:
        return url_for("filters.view", key=self.urlsafe_key)

    @property
    def parent_filters_url(self) -> str:
        if isinstance(self.parent, Entities.PROJECT):
            return url_for("projects.view", key=self.parent.urlsafe_key, tab="filters")
        if isinstance(self.parent, Entities.CATEGORY):
            return url_for(
                "categories.index", key=self.parent.urlsafe_key, tool="filters"
            )
        return self._filter_parent.url

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"definitions"})

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "related": filter.ConditionEntities,
                "parent": filter.FilterParent,
                "creator": filter.Creator,
                "table": filter.FilterTable,
            }
        )
        return properties

    def allowed(self, action: Action, user: FieldUser = None) -> bool:
        user = current_context_user(user)
        action = Action.EDIT if action.implies(Action.EDIT) else action

        return self._filter_parent.allowed(action, user=user)

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_related_entities_allowed_checks_referenced_entities
    # @tests tests_unit/test_011_filters.py::test_filter_related_entities_allowed_keeps_model_and_form_access_separate
    # @matrix filter permissions : model-task related-entities restricted-access saved-filters
    def related_entities_allowed(self, user: FieldUser = None) -> bool:
        user = current_context_user(user)
        related = Entities.fetch(*self.related, request=Fetch.direct())
        return all(e.allowed(Action.VIEW, user=user) for e in related)

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_string
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_boolean
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_entity_valued
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_multiple_types
    # @matrix filter : boolean conditions entity-valued mixed-types string
    @property
    def conditions(self) -> list[Condition]:
        if cached := getattr(self, "_conditions", None):
            return cached

        if self._definitions is None:
            self.compile()
        related = self._compiled_related or self.related
        entity_map = {e.hash: e for e in related}
        conditions = [Condition.create(d, entity_map) for d in self.definitions]
        self._conditions = [c for c in conditions if c]

        return self._conditions

    @property
    def definitions(self) -> list[FilterDefinition]:
        if self._definitions is not None:
            return self._definitions

        self.compile()
        return cast("list[FilterDefinition]", self._definitions)

    @definitions.setter
    def definitions(self, definitions: CompiledFilter | Iterable[FilterDefinition]) -> None:
        from ..tools.filters.contract import CompiledFilter

        self._compiled_filters = {}
        self._conditions = None
        if isinstance(definitions, CompiledFilter):
            self._definitions = list(definitions.definitions)
            self._compiled_related = list(definitions.related)
            self.db["definitions"] = json.dumps(definitions.contract)
            return

        # Retain the legacy setter for fixtures and trusted compatibility
        # callers. Production creation compiles before reaching this boundary.
        self._definitions = list(definitions)
        self.db["definitions"] = json.dumps(
            [definition.description for definition in definitions]
        )

    # @testable true
    # @tests tests_unit/test_011c_filter_contract.py::test_saved_filter_compiles_legacy_data_per_viewer
    # @matrix filters permissions : authorization legacy saved-filter validation
    def compile(self, user: FieldUser = None) -> CompiledFilter:
        """Validate saved data for the current viewer before it can be queried."""
        from ..tools.filters.contract import compile_saved_filter

        user = current_context_user(user)
        user_key = getattr(user, "urlsafe_key", None) or id(user)
        compiled = self._compiled_filters.get(user_key)
        if compiled is None:
            compiled = compile_saved_filter(
                self._filter_parent,
                self.db.get("definitions", "[]"),
                user,
            )
            self._compiled_filters[user_key] = compiled

        # The entity can be compiled for more than one viewer in a long-lived
        # context. Keep the display projections aligned with the requested
        # viewer even when their compiled contract came from this local cache.
        self._conditions = None
        self._definitions = list(compiled.definitions)
        self._compiled_related = list(compiled.related)
        return compiled

    @classmethod
    def create(
        cls, entity: Category | Project, definitions: CompiledFilter | Iterable[object],
        temporary: bool = False,
    ) -> Self:
        from ..tools.filters.contract import (
            CompiledFilter,
            compile_filter_contract,
            parse_filter_request,
        )

        filter = cls(temporary=temporary, parent=entity.key)
        filter.kind = filter.entity_kind
        # The relation setter accepts the active Flask user through its forwarding proxy.
        filter.creator = cast("User", current_user)
        filter.parent = entity

        if not isinstance(definitions, CompiledFilter):
            legacy_values = [
                json.dumps(
                    definition.description
                    if isinstance(definition, FilterDefinition)
                    else definition
                )
                for definition in definitions
            ]
            contract = parse_filter_request(None, legacy_values)
            definitions = compile_filter_contract(
                entity,
                contract,
                current_context_user(),
            )
        filter.definitions = definitions
        filter.related = list(definitions.related)

        return filter
