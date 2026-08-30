import json
import hashlib
from datetime import datetime, timezone

from google.cloud import datastore

from .. import mixins
from ..definitions import Action, MutationIntent
from ..entities import Entities
from ..exceptions import PropertyError
from ..properties import common_entity
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from ..tools.auth.context import current_context_user


# @testable infrastructure
class EntityProperties:
    """Lazy-instantiating property container for an entity.

    Maps property names to Property classes via an internal registry.
    Instances are created on first access and cached. Supports dict-like
    access, attribute access, and ``implementing(*mixins)`` to iterate properties
    with specific mixins.

    If a property fails to instantiate, the error is wrapped in
    PropertyError (entity context) and the original exception is chained.
    """

    def __init__(self, entity, registry):
        self._entity = entity
        self._registry = dict(registry)
        self._instances = {}

    def _get(self, name):
        if name in self._instances:
            return self._instances[name]

        if name in self._registry:
            base_class = self._registry[name]
            try:
                property_instance = base_class(entity=self._entity)
            except PropertyError:
                raise
            except Exception as e:
                label = getattr(
                    self._entity, "entity_kind", type(self._entity).__name__
                )
                raise PropertyError(
                    f"Property {name!r} failed to instantiate on {label}: {e}",
                    entity=self._entity,
                ) from e
            self._instances[name] = property_instance
            return property_instance

        return None

    def __getattr__(self, name):
        prop = self._get(name)
        if prop is not None:
            return prop
        raise AttributeError(f"Property {name} not found")

    def __getitem__(self, name):
        prop = self._get(name)
        if prop is not None:
            return prop
        raise KeyError(f"Property {name} not found")

    def __contains__(self, name):
        return name in self._registry

    def get(self, name, default=None):
        prop = self._get(name)
        return prop if prop is not None else default

    def update(self, mapping):
        self._registry.update(mapping)

    def implementing(self, *mixins):
        for name, cls in self._registry.items():
            if issubclass(cls, mixins):
                yield self._get(name)


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_requires_subclass_entity_kind
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_preserves_key_from_empty_datastore_entity
# @matrix entity : empty-datastore-entity initialization key-preservation validation
class Entity:
    """Base class for all persistent entities.

    Subclasses set ``entity_kind`` and override ``_get_properties()`` to
    register their Property classes. Properties are accessed via attribute
    or dict syntax on ``self.properties``, and ``__getattr__``/``__setattr__``
    delegate to property values for convenience (e.g. ``entity.name``).

    Provides DB persistence (``save``/``delete``), cache output (``to_cache``),
    AI context (``to_ai``), filter indexing (``to_filter_index``), detail
    serialization (``details``), and permission checking (``allowed``).
    """

    _properties = None
    _related_keys = None
    _relations = None
    _mutation_intents = None
    _processes = None
    _to_cache = None
    _details = None
    _readonly = None
    _key = None
    _db = None
    _state = None
    retired_fields = frozenset()

    def __init__(self, *args, **kwargs):
        if not getattr(type(self), "entity_kind", None):
            raise NotImplementedError(f"{type(self).__name__} requires entity_kind")
        identifier = args[0] if args and args[0] is not None else None
        self._db = identifier if isinstance(identifier, datastore.Entity) else {}

        if identifier is not None:
            self._key = database_get.datastore_key(identifier)
        elif not kwargs.get("temporary") and not kwargs.get("testing"):
            self._key = database_utility.create_key(self.entity_kind, kwargs.get("parent"))

        self._temporary = kwargs.get("temporary")
        self._testing = kwargs.get("testing")

    @property
    def exclude_from_index(self):
        return frozenset()

    def _get_properties(self):
        properties = {
            "name": common_entity.Name,
            "created": common_entity.Created,
            "modified": common_entity.Modified,
            "kind": common_entity.Kind,
            "requires": common_entity.Requires,
            "hash": common_entity.Hash,
            "active": common_entity.Active,
        }
        return EntityProperties(self, properties)

    @property
    def sync_ids(self):
        return {}

    @property
    def temporary(self):
        return self._temporary

    @property
    def fingerprint(self):
        modified = self.modified or datetime.now(timezone.utc)
        return hashlib.md5(modified.isoformat().encode("utf-8")).hexdigest()

    @property
    def properties(self):
        if self._properties is not None:
            return self._properties

        super().__setattr__("_properties", self._get_properties())

        return self._properties

    def __getattr__(self, name):
        prop = self.properties.get(name)
        if prop is None:
            raise AttributeError(f"Property {name} not found")
        return prop.value

    def __setattr__(self, name, value):
        prop = self.properties.get(name)
        if prop is None:
            super().__setattr__(name, value)
            return
        prop.value = value

    @property
    def readonly(self):
        if self._readonly is None:
            self._readonly = not self.allowed(Action.EDIT)
        return self._readonly

    def column(self, field_id):
        """Get a property or submission field by ID for table column display."""
        if field_id in self.properties:
            return self.properties[field_id]

        if isinstance(self, mixins.SubmitterMixin):
            return self.properties.submission.column(field_id)

        raise PropertyError(
            f"Column {field_id!r} not found on {self.entity_kind}",
            entity=self,
        )

    @property
    def relations(self):
        if self._relations is not None:
            return self._relations

        self._relations = list(
            self.properties.implementing(
                mixins.RelatedEntityMixin, mixins.RelatedEntityListMixin
            )
        )
        return self._relations

    @property
    def related_keys(self):
        if self._related_keys is not None:
            return self._related_keys

        self._related_keys = {k for r in self.relations for k in r.keys if k}
        return self._related_keys

    @property
    def related_entities(self):
        loaded = {}
        for relation in self.relations:
            loaded.update(relation.attached_entities)
        return loaded

    def attach(self, key_map, *, resolved_keys=None):
        known_keys = set(key_map)
        if resolved_keys is not None:
            known_keys.update(resolved_keys)

        for relation in self.relations:
            keys = [key for key in relation.keys if key]
            if resolved_keys is None or all(key in known_keys for key in keys):
                relation.attach(key_map)

    @property
    def details(self):
        if self._details is not None:
            return self._details

        details = {}
        for p in self.properties.implementing(mixins.DetailsMixin):
            value = p.details_value
            if value and p.details_key:
                details[p.details_key] = value
        details["id"] = (
            self.page.urlsafe_key
            if getattr(self, "entity_kind", None) == "user"
            else self.urlsafe_key
        )

        self._details = details
        return self._details

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_reference_details_does_not_derive_requirements_from_unloaded_relations
    # @pairs entities:reference-details relations:direct
    @property
    def reference_details(self):
        """Return a non-recursive display projection for an entity reference."""
        relation_ids = {id(relation) for relation in self.relations}
        details = {}
        for prop in self.properties.implementing(mixins.DetailsMixin):
            if id(prop) in relation_ids or prop.id == "requires":
                continue
            value = prop.details_value
            if value and prop.details_key:
                details[prop.details_key] = value

        if getattr(self, "entity_kind", None) == "user":
            page = self.properties.get("page")
            details["id"] = database_get.urlsafe_key(page.key) if page else None
        else:
            details["id"] = self.urlsafe_key
        return details

    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_default_entity_fields_are_not_duplicated_in_submission_search_cache
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_to_cache_stores_detail_parent_pointers
    # @matrix cache : cache-deduplication default-fields details-key parent-key
    @property
    def to_cache(self):
        if self.reserved or not self.hash:
            self._to_cache = {}
            return self._to_cache
        elif self._to_cache is not None:
            return self._to_cache

        cache = {
            p.cache_key: p.cache_value
            for p in self.properties.implementing(mixins.CacheMixin)
            if isinstance(p.cache_value, str)
        }

        details = self.details
        cache["id"] = details["id"]
        cache["details_key"] = self.hash
        parent = details.get("parent")
        if isinstance(parent, dict) and parent.get("hash"):
            cache["parent_key"] = parent["hash"]

        if self.properties.get("submission"):
            cache.update(self.properties.submission.search_value)

        self._to_cache = cache
        return cache

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_context_exports_authentication_and_filter_index_neutrality
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_to_ai_merges_submission_fields_without_nested_duplicate
    # @tests tests_unit/test_006_file_properties.py::test_file_to_ai_exports_metadata_and_uri_to_ai
    # @matrix ai entity submission : single-merge submission-fields
    # @matrix ai file : metadata permissions
    # @pair permissions:authenticated-user
    def to_ai(self, user=None):
        user = current_context_user(user)
        if not user or not getattr(user, "is_authenticated", False):
            raise PermissionError("user must be authenticated")

        values = {}
        for p in self.properties.implementing(mixins.AIMixin):
            p.user = user
            values[p.ai_key] = p.ai_value

        if self.properties.get("submission"):
            self.properties.submission.user = user
            submission = self.properties.submission.ai_value
            if submission:
                values.update(submission)

        values["permissions"] = {
            "can_view": self.allowed(Action.VIEW, user=user),
            "can_edit": self.allowed(Action.EDIT, user=user),
            "can_create": self.allowed(Action.CREATE, user=user),
        }
        if hasattr(self, "url"):
            values["url"] = self._ai_url()

        return {k: v for k, v in values.items() if v is not None}

    def _ai_url(self):
        url = self.url
        entity_hash = getattr(self, "hash", None)
        if not url or not entity_hash:
            return url

        try:
            urlsafe_key = self.urlsafe_key
        except RuntimeError:
            return url

        return url.replace(urlsafe_key, f"hash:{entity_hash}", 1)

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_context_exports_authentication_and_filter_index_neutrality
    # @tests tests_unit/test_013_task_properties.py::test_task_filter_index_includes_restricted_related_values
    # @tests tests_unit/test_004e_submission_behavior.py::test_unset_submission_fields_do_not_erase_entity_filter_metadata
    # @matrix filter-index permissions task : column-view entity-metadata permission-neutral related-values unset-values
    # @pairs filter-index:related-values permissions:filter-index-neutral
    def to_filter_index(self, user=None):
        values = {"id": self.urlsafe_key}

        for p in self.properties.implementing(mixins.FilterMixin):
            values[p.filter_key] = p.filter_value

        if self.properties.get("submission"):
            values.update(
                {
                    key: value
                    for key, value in self.properties.submission.filter_value.items()
                    if value is not None
                }
            )

        return {k: v for k, v in values.items() if v is not None}

    @property
    def reserved(self):
        return self.db.get("reserved", False)

    # @testable true
    # @tests tests_unit/test_009f_page_view_access.py::test_page_restricted_access_group_match
    # @matrix page permissions user-groups : group-match restricted-access
    def restricted_access(self, user):
        if not user or not user.is_authenticated:
            return True
        elif getattr(user, "is_admin", getattr(user, "is_owner", False)):
            return False

        if getattr(self, "restricted_to", False):
            belongs_to = user.properties.restrictions.belongs_to
            view_access = set(self.restricted_to) & set(belongs_to)
            if not view_access:
                return True

        return False

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_testing_entity_allowed_uses_real_permissions
    # @matrix permissions testing : entity-allowed no-testing-shortcut
    def allowed(self, action, user=None):
        user = current_context_user(user)

        if self.restricted_access(user):
            return False

        return bool(user and user.has_permission(self, action))

    @property
    def key(self):
        if self._db and not self._key:
            self._key = self._db.key

        return self._key

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_key_access_without_key_raises_runtime_error
    # @pair entity:key-validation
    @property
    def urlsafe_key(self):
        if not self.key:
            raise RuntimeError("no key assigned")

        if getattr(self, "_urlsafe_key", None):
            return self._urlsafe_key

        self._urlsafe_key = database_get.urlsafe_key(self.key)
        return self._urlsafe_key

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_key_access_without_key_raises_runtime_error
    # @pair entity:key-validation
    @property
    def db(self):
        if self._db or self._temporary or self._testing:
            return self._db

        if not self.key:
            raise RuntimeError("no key assigned")

        self._db = database_get.entity(self.key)

        if not self._db:
            self._db = database_utility.create_entity(self.key)

        return self._db

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_add_mutation_intents_requires_typed_intents_and_dedupes
    # @matrix entity : dedupe key-validation typed-intent validation
    def add_mutation_intents(self, *intents):
        if self._mutation_intents is None:
            self._mutation_intents = []

        existing = {
            (
                intent.intent,
                getattr(intent.entity, "key", None),
                intent.property_mask,
                intent.property_updates,
                intent.cache_key,
                intent.cache_kind,
                intent.reason,
            )
            for intent in self._mutation_intents
        }
        for intent in intents:
            if not isinstance(intent, MutationIntent):
                raise TypeError("Entity mutation intents must be MutationIntent values")
            if (
                intent.entity is not None
                and getattr(intent.entity, "key", None) is None
            ):
                raise ValueError("Mutation intent entities must have a key")
            signature = (
                intent.intent,
                getattr(intent.entity, "key", None),
                intent.property_mask,
                intent.property_updates,
                intent.cache_key,
                intent.cache_kind,
                intent.reason,
            )
            if signature not in existing:
                self._mutation_intents.append(intent)
                existing.add(signature)

    @property
    def mutation_intents(self):
        if self._mutation_intents is None:
            self._mutation_intents = []
        return self._mutation_intents

    def get_process(self, process_id):
        if process_id in self.processes:
            return self.processes[process_id]
        elif process_id in self.db:
            self.processes[process_id] = json.loads(self.db.get(process_id, "{}"))
            return self.processes[process_id]
        else:
            return self.processes.setdefault(process_id, {})

    @property
    def processes(self):
        if self._processes is None:
            self._processes = {}
        return self._processes

    def save(self, *args):
        if self._testing:
            return

        Entities.save(self, *args)
