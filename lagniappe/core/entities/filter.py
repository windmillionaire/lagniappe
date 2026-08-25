import json
import hashlib

from flask import url_for
from flask_login import current_user

from ..definitions import Action, Fetch, FilterDefinition
from ..entities import Entities
from ..properties import filter
from ..tools.auth.context import current_context_user
from .condition import Condition
from .entity import Entity


# @testable false
# @covered-by lagniappe/core/entities/filter.py::Filter.conditions
class Filter(Entity):
    entity_kind = "filter"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conditions = None
        self._definitions = None
        self._compiled_filters = {}
        self._compiled_related = None

    @property
    def is_filter(self):
        return True

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_fingerprint_uses_loaded_parent_fingerprint
    # @features filter
    # @dimensions fingerprint parent
    @property
    def fingerprint(self):
        fingerprint = super().fingerprint
        parent = self.parent
        parent_fingerprint = parent.fingerprint if parent else fingerprint
        return hashlib.md5(
            f"{fingerprint}:{parent_fingerprint}".encode("utf-8")
        ).hexdigest()

    @property
    def required(self):
        return [self.hash, self.parent.hash, self.creator.hash]

    @property
    def url(self):
        return url_for("filters.view", key=self.urlsafe_key)

    @property
    def parent_filters_url(self):
        if isinstance(self.parent, Entities.PROJECT):
            return url_for("projects.view", key=self.parent.urlsafe_key, tab="filters")
        if isinstance(self.parent, Entities.CATEGORY):
            return url_for(
                "categories.index", key=self.parent.urlsafe_key, tool="filters"
            )
        return self.parent.url

    @property
    def exclude_from_index(self):
        return frozenset({"definitions"})

    def _get_properties(self):
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

    def allowed(self, action, user=None):
        user = current_context_user(user)
        action = Action.EDIT if action.implies(Action.EDIT) else action

        return self.parent.allowed(action, user=user)

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_related_entities_allowed_checks_referenced_entities
    # @tests tests_unit/test_011_filters.py::test_filter_related_entities_allowed_checks_model_task_form_restrictions
    # @features filter permissions
    # @dimensions saved-filters related-entities model-task restricted-access
    def related_entities_allowed(self, user=None):
        user = current_context_user(user)
        related = Entities.fetch(*self.related, request=Fetch.direct())
        return all(e.allowed(Action.VIEW, user=user) for e in related)

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_string
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_boolean
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_entity_valued
    # @tests tests_unit/test_011_filters.py::test_filter_conditions_multiple_types
    # @features filter
    # @dimensions conditions, string, boolean, entity-valued, mixed-types
    @property
    def conditions(self):
        if getattr(self, "_conditions", None):
            return self._conditions

        if self._definitions is None:
            self.compile()
        related = self._compiled_related or self.related
        entity_map = {e.hash: e for e in related}
        conditions = [Condition.create(d, entity_map) for d in self.definitions]
        self._conditions = [c for c in conditions if c]

        return self._conditions

    @property
    def definitions(self):
        if self._definitions is not None:
            return self._definitions

        self.compile()
        return self._definitions

    @definitions.setter
    def definitions(self, definitions):
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
    # @features filters permissions
    # @dimensions saved-filter validation authorization legacy
    def compile(self, user=None):
        """Validate saved data for the current viewer before it can be queried."""
        from ..tools.filters.contract import compile_saved_filter

        user = current_context_user(user)
        user_key = getattr(user, "urlsafe_key", None) or id(user)
        compiled = self._compiled_filters.get(user_key)
        if compiled is None:
            compiled = compile_saved_filter(
                self.parent,
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
    def create(cls, entity, definitions, temporary=False):
        from ..tools.filters.contract import (
            CompiledFilter,
            compile_filter_contract,
            parse_filter_request,
        )

        filter = cls(temporary=temporary, parent=entity.key)
        filter.kind = filter.entity_kind
        filter.creator = current_user
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
