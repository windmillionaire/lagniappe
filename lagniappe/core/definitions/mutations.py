"""Machine-readable contracts and executable plans for entity mutations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MutationOperation(Enum):
    """Top-level mutation requested by a caller."""

    SAVE = "save"
    DELETE = "delete"


class MutationPhase(Enum):
    """Ordering boundary for a mutation effect."""

    DURABLE = "durable"
    POST_COMMIT = "post-commit"


class MutationEffectType(Enum):
    """Effect kinds understood by the entity mutation executor."""

    UPSERT = "upsert"
    UNLINK = "unlink"
    DELETE = "delete"
    CACHE_REFRESH = "cache-refresh"
    CACHE_DELETE = "cache-delete"
    CACHE_STATE_DELETE = "cache-state-delete"
    CACHE_SEARCH_DELETE = "cache-search-delete"
    NOTIFICATION_UPSERT = "notification-upsert"
    NOTIFICATION_DELETE = "notification-delete"
    OPERATION_UPSERT = "operation-upsert"
    OPERATION_DELETE = "operation-delete"
    BLOB_DELETE = "blob-delete"
    SCHEDULED_UNCOMPLETE_DISPATCH = "scheduled-uncomplete-dispatch"
    PUBLIC_DISCOVERY_INVALIDATE = "public-discovery-invalidate"


class MutationIntentType(Enum):
    """Pending work registered by an entity before its mutation is planned."""

    STANDARD = "standard"
    PATCH = "patch"
    TOUCH = "touch"
    CACHE_STATE_DELETE = "cache-state-delete"
    CACHE_SEARCH_DELETE = "cache-search-delete"
    SCHEDULED_UNCOMPLETE_DISPATCH = "scheduled-uncomplete-dispatch"
    PUBLIC_DISCOVERY_INVALIDATE = "public-discovery-invalidate"


class RelationAuthority(Enum):
    """Where a relationship's durable membership is owned."""

    SOURCE = "source"
    MIRRORED = "mirrored"
    ANCESTOR = "ancestor"
    QUERY = "query-derived"


class DeletePolicy(Enum):
    """What happens to one side when the other side is deleted."""

    PRESERVE = "preserve"
    UNLINK = "unlink"
    CASCADE = "cascade"
    DELETE_IF_ORPHANED = "delete-if-orphaned"


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @matrix mutations : contract serialization
@dataclass(frozen=True)
class RelationMutationContract:
    """Declared storage and lifecycle behavior for one entity relation."""

    name: str
    targets: tuple[str, ...]
    cardinality: str
    authority: RelationAuthority
    gateway: str
    persisted: bool = True
    on_source_delete: DeletePolicy = DeletePolicy.PRESERVE
    on_target_delete: DeletePolicy = DeletePolicy.PRESERVE
    add_effects: tuple[MutationEffectType, ...] = (MutationEffectType.UPSERT,)
    replace_effects: tuple[MutationEffectType, ...] = (MutationEffectType.UPSERT,)
    remove_effects: tuple[MutationEffectType, ...] = (MutationEffectType.UPSERT,)

    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::RelationMutationContract
    # @reason relation serialization is exercised through the public contract
    def to_dict(self):
        return {
            "name": self.name,
            "targets": list(self.targets),
            "cardinality": self.cardinality,
            "authority": self.authority.value,
            "gateway": self.gateway,
            "persisted": self.persisted,
            "on_source_delete": self.on_source_delete.value,
            "on_target_delete": self.on_target_delete.value,
            "add_effects": [effect.value for effect in self.add_effects],
            "replace_effects": [effect.value for effect in self.replace_effects],
            "remove_effects": [effect.value for effect in self.remove_effects],
        }


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @matrix mutations : completeness contract
@dataclass(frozen=True)
class EntityMutationContract:
    """Mutation inventory for one persisted entity kind."""

    kind: str
    relations: tuple[RelationMutationContract, ...] = ()
    delete_effects: tuple[MutationEffectType, ...] = (
        MutationEffectType.DELETE,
        MutationEffectType.CACHE_DELETE,
        MutationEffectType.BLOB_DELETE,
    )

    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::EntityMutationContract
    # @reason entity serialization is exercised through the public contract
    def to_dict(self):
        return {
            "kind": self.kind,
            "delete_effects": [effect.value for effect in self.delete_effects],
            "relations": [relation.to_dict() for relation in self.relations],
        }


# @testable false
# @covered-by lagniappe/core/definitions/mutations.py::MutationEffect
# @reason compact entity identifiers are exercised through plan serialization
def _entity_key(entity):
    try:
        return entity.urlsafe_key
    except (AttributeError, RuntimeError, ValueError):
        key = getattr(entity, "key", None)
        return str(key) if key is not None else None


# @testable false
# @covered-by lagniappe/core/definitions/mutations.py::MutationEffect
# @reason compact entity kinds are exercised through plan serialization
def _entity_kind(entity):
    return getattr(entity, "entity_kind", None) or getattr(entity, "kind", None)


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_plan_is_serializable_and_preserves_intents_until_commit
# @matrix mutations : plan serialization
@dataclass(frozen=True)
class MutationEffect:
    """Serializable description of one planned mutation effect."""

    effect: MutationEffectType
    phase: MutationPhase
    entity: Any = field(default=None, repr=False, compare=False)
    relation: str | None = None
    targets: tuple[Any, ...] = field(default=(), repr=False, compare=False)
    property_mask: tuple[str, ...] | None = None
    property_updates: tuple[str, ...] = ()
    serialize_processes: bool = False
    reasons: tuple[str, ...] = ()
    depends_on: tuple[Any, ...] = field(default=(), repr=False, compare=False)
    path: str | None = None
    visibility: str | None = None
    cache_key: str | None = None
    cache_kind: str | None = None

    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationEffect
    # @reason effect serialization is exercised through plan serialization
    def to_dict(self):
        data = {
            "effect": self.effect.value,
            "phase": self.phase.value,
        }
        if self.entity is not None:
            data["entity"] = {
                "kind": _entity_kind(self.entity),
                "id": _entity_key(self.entity),
            }
        if self.relation:
            data["relation"] = self.relation
        if self.targets:
            data["targets"] = [
                {"kind": _entity_kind(target), "id": _entity_key(target)}
                for target in self.targets
            ]
        if self.property_mask is not None:
            data["property_mask"] = list(self.property_mask)
        if self.property_updates:
            data["property_updates"] = list(self.property_updates)
        if self.serialize_processes:
            data["serialize_processes"] = True
        if self.reasons:
            data["reasons"] = list(self.reasons)
        if self.depends_on:
            data["depends_on"] = [
                {"kind": _entity_kind(target), "id": _entity_key(target)}
                for target in self.depends_on
            ]
        if self.path:
            data["path"] = self.path
        if self.visibility:
            data["visibility"] = self.visibility
        if self.cache_key:
            data["cache_key"] = self.cache_key
        if self.cache_kind:
            data["cache_kind"] = self.cache_kind
        return data


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_add_mutation_intents_requires_typed_intents_and_dedupes
# @tests tests_unit/test_022_mutation_contracts.py::test_save_plan_is_serializable_and_preserves_intents_until_commit
# @matrix entity : dedupe typed-intent validation
# @pair mutations:save
@dataclass(frozen=True)
class MutationIntent:
    """Typed related or post-commit work awaiting a root mutation."""

    intent: MutationIntentType
    entity: Any = field(default=None, repr=False, compare=False)
    property_mask: tuple[str, ...] = ()
    property_updates: tuple[str, ...] = ()
    refresh_cache: bool = True
    reason: str = ""
    cache_key: str | None = None
    cache_kind: str | None = None

    @classmethod
    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationIntent
    # @reason intent factories are exercised through typed intent planning
    def standard(cls, entity, *, reason):
        return cls(MutationIntentType.STANDARD, entity=entity, reason=reason)

    @classmethod
    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationIntent
    # @reason intent factories are exercised through typed intent planning
    def patch(
        cls,
        entity,
        *properties,
        property_updates=("modified",),
        refresh_cache=True,
        reason,
    ):
        mask = tuple(dict.fromkeys((*properties, *property_updates)))
        if not mask:
            raise ValueError("Patch mutation intents require at least one property")
        return cls(
            MutationIntentType.PATCH,
            entity=entity,
            property_mask=mask,
            property_updates=tuple(property_updates),
            refresh_cache=refresh_cache,
            reason=reason,
        )

    @classmethod
    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationIntent
    # @reason intent factories are exercised through typed intent planning
    def touch(cls, entity, *, refresh_cache=True, reason):
        return cls(
            MutationIntentType.TOUCH,
            entity=entity,
            property_mask=("modified",),
            property_updates=("modified",),
            refresh_cache=refresh_cache,
            reason=reason,
        )

    @classmethod
    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationIntent
    # @reason intent factories are exercised through typed intent planning
    def clear_cache_state(cls, cache_key, *, reason):
        return cls(
            MutationIntentType.CACHE_STATE_DELETE,
            refresh_cache=False,
            reason=reason,
            cache_key=cache_key,
        )

    @classmethod
    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationIntent
    # @reason intent factories are exercised through typed intent planning
    def delete_from_search(cls, kind, entity, *, reason):
        return cls(
            MutationIntentType.CACHE_SEARCH_DELETE,
            entity=entity,
            refresh_cache=False,
            reason=reason,
            cache_kind=kind,
        )

    @classmethod
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_scheduled_uncomplete_dispatch_is_planned_after_task_write
    # @matrix mutations task-scheduling : durable-first post-commit
    def dispatch_scheduled_uncomplete(cls, entity, *, reason):
        """Dispatch one tokenized uncompletion only after ``entity`` commits."""
        return cls(
            MutationIntentType.SCHEDULED_UNCOMPLETE_DISPATCH,
            entity=entity,
            reason=reason,
        )

    @classmethod
    # @testable false
    # @covered-by lagniappe/core/mutations/base.py::MutationPlanBuilder.consume_intents
    # @reason factory is exercised through page visibility mutation planning
    def invalidate_public_discovery(cls, *, reason):
        return cls(
            MutationIntentType.PUBLIC_DISCOVERY_INVALIDATE,
            refresh_cache=False,
            reason=reason,
        )


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_plan_is_serializable_and_preserves_intents_until_commit
# @tests tests_unit/test_022_mutation_contracts.py::test_save_root_persists_full_exclusions_without_lifecycle_intents_or_cache
# @matrix mutations : plan serialization
@dataclass
class MutationPlan:
    """Executable entity mutation and its ordered public effect inventory."""

    operation: MutationOperation
    effects: list[MutationEffect]
    consumed_intents: tuple[Any, ...] = field(default=(), repr=False)

    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationPlan
    # @reason plan serialization is exercised through the public plan contract
    def to_dict(self):
        return {
            "operation": self.operation.value,
            "effects": [effect.to_dict() for effect in self.effects],
        }


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_executes_datastore_before_cache_and_reports_cache_failure
# @matrix mutations : cache-failure post-commit-outcome
@dataclass
class MutationOutcome:
    """Progress boundary returned after executing a mutation plan."""

    operation: MutationOperation
    durable_committed: bool = False
    post_commit_complete: bool = False
    completed_effects: list[MutationEffectType] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationOutcome
    # @reason completion is asserted through the public outcome contract
    @property
    def complete(self):
        return self.durable_committed and self.post_commit_complete and not self.errors

    # @testable false
    # @covered-by lagniappe/core/definitions/mutations.py::MutationOutcome
    # @reason outcome serialization is exercised through the public contract
    def to_dict(self):
        return {
            "operation": self.operation.value,
            "durable_committed": self.durable_committed,
            "post_commit_complete": self.post_commit_complete,
            "completed_effects": [effect.value for effect in self.completed_effects],
            "errors": list(self.errors),
            "complete": self.complete,
        }
