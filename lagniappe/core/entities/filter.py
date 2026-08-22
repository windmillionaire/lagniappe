import json
import hashlib

from flask import url_for
from flask_login import current_user

from ..definitions import Action, Fetch, FilterDefinition
from ..entities import Entities
from ..properties import filter
from ..tools import cache
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

        entity_map = {e.hash: e for e in self.related}
        conditions = [Condition.create(d, entity_map) for d in self.definitions]
        self._conditions = [c for c in conditions if c]

        return self._conditions

    @property
    def definitions(self):
        if getattr(self, "_definitions", None):
            return self._definitions

        stored_definitions = json.loads(self.db.get("definitions", "[]"))
        self._definitions = [FilterDefinition.load(d) for d in stored_definitions]
        return self._definitions

    @definitions.setter
    def definitions(self, definitions):
        self._definitions = definitions
        self.db["definitions"] = json.dumps([d.description for d in definitions])

    @classmethod
    def create(cls, entity, definitions, temporary=False):
        filter = cls(temporary=temporary, parent=entity.key)
        filter.kind = filter.entity_kind
        filter.creator = current_user
        filter.parent = entity

        definitions = [FilterDefinition.load(d) for d in definitions]
        filter.definitions = definitions

        conditions = [Condition(definition=d) for d in definitions]

        hashes = {h for c in conditions for h in c.hashes}
        entity_keys = [d["id"] for d in cache.get_details_by_hash(hashes).values()]
        filter.related = Entities.fetch(*entity_keys, request=Fetch.direct())

        return filter
