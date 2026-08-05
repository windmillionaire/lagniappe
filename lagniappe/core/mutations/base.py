"""Mutation plan construction primitives shared by every entity kind."""

from collections import OrderedDict

from ..definitions import (
    MutationEffect,
    MutationEffectType,
    MutationIntentType,
    MutationOperation,
    MutationPhase,
    MutationPlan,
)


STANDARD_PROPERTY_UPDATES = (
    "active",
    "hash",
    "requires",
    "modified",
    "created",
    "version",
)


# @testable infrastructure
def _entity_key(entity):
    return getattr(entity, "key", None)


# @testable infrastructure
def _unique(values):
    return tuple(dict.fromkeys(value for value in values if value is not None))


# @testable infrastructure
class MutationPlanBuilder:
    """Merge kind-planner output into one authoritative effect inventory."""

    # @testable infrastructure
    def __init__(self, operation, entities, *, registry=None):
        self.operation = operation
        self.roots = tuple(entities)
        self.entities = registry
        self._effects = OrderedDict()
        self._standard_planned = set()
        self._standard_planning = set()
        self._consumed = OrderedDict()

    # @testable infrastructure
    def _effect_key(self, effect, entity=None, cache_key=None, cache_kind=None):
        if entity is not None:
            return effect, _entity_key(entity)
        if effect is MutationEffectType.CACHE_STATE_DELETE:
            return effect, cache_key
        if effect is MutationEffectType.CACHE_SEARCH_DELETE:
            return effect, cache_kind, _entity_key(entity)
        return effect, cache_kind, cache_key

    # @testable infrastructure
    def _merge_write(self, existing, incoming):
        if existing.property_mask is None or incoming.property_mask is None:
            property_mask = None
        else:
            property_mask = _unique((*existing.property_mask, *incoming.property_mask))
        return MutationEffect(
            existing.effect,
            existing.phase,
            entity=existing.entity,
            property_mask=property_mask,
            property_updates=_unique(
                (*existing.property_updates, *incoming.property_updates)
            ),
            serialize_processes=(
                existing.serialize_processes or incoming.serialize_processes
            ),
            reasons=_unique((*existing.reasons, *incoming.reasons)),
            depends_on=_unique((*existing.depends_on, *incoming.depends_on)),
        )

    # @testable infrastructure
    def add_write(
        self,
        entity,
        *,
        effect=MutationEffectType.UPSERT,
        property_mask=None,
        property_updates=(),
        serialize_processes=False,
        reason,
        depends_on=(),
    ):
        if not getattr(entity, "key", None):
            return
        key = self._effect_key(effect, entity=entity)
        incoming = MutationEffect(
            effect,
            MutationPhase.DURABLE,
            entity=entity,
            property_mask=(
                None if property_mask is None else tuple(dict.fromkeys(property_mask))
            ),
            property_updates=tuple(dict.fromkeys(property_updates)),
            serialize_processes=serialize_processes,
            reasons=(reason,),
            depends_on=tuple(depends_on),
        )
        existing = self._effects.get(key)
        self._effects[key] = (
            self._merge_write(existing, incoming) if existing else incoming
        )

    # @testable infrastructure
    def standard_root(self, entity, *, reason, depends_on=()):
        self.add_write(
            entity,
            property_updates=STANDARD_PROPERTY_UPDATES,
            serialize_processes=True,
            reason=reason,
            depends_on=depends_on,
        )
        self.cache_refresh(entity, reason=reason)

    # @testable infrastructure
    def root(self, entity, *, property_mask=None, property_updates=(), reason):
        mask = None if property_mask is None else tuple(property_mask)
        self.add_write(
            entity,
            property_mask=mask,
            property_updates=property_updates,
            reason=reason,
        )

    # @testable infrastructure
    def patch(
        self,
        entity,
        *properties,
        property_updates=("modified",),
        refresh_cache=True,
        reason,
        depends_on=(),
        effect=MutationEffectType.UPSERT,
    ):
        mask = _unique((*properties, *property_updates))
        if not mask:
            raise ValueError("Masked mutation writes require at least one property")
        self.add_write(
            entity,
            effect=effect,
            property_mask=mask,
            property_updates=property_updates,
            reason=reason,
            depends_on=depends_on,
        )
        if refresh_cache:
            self.cache_refresh(entity, reason=reason)

    # @testable infrastructure
    def touch(self, entity, *, refresh_cache=True, reason, depends_on=()):
        self.patch(
            entity,
            property_updates=("modified",),
            refresh_cache=refresh_cache,
            reason=reason,
            depends_on=depends_on,
        )

    # @testable infrastructure
    def delete(self, entity, *, reason):
        if not getattr(entity, "key", None):
            return
        key = self._effect_key(MutationEffectType.DELETE, entity=entity)
        self._effects[key] = MutationEffect(
            MutationEffectType.DELETE,
            MutationPhase.DURABLE,
            entity=entity,
            reasons=(reason,),
        )
        self.cache_delete(entity, reason=reason)

    # @testable infrastructure
    def _add_entity_cache_effect(self, effect, entity, reason):
        if not getattr(entity, "key", None):
            return
        key = self._effect_key(effect, entity=entity)
        existing = self._effects.get(key)
        reasons = _unique((*(existing.reasons if existing else ()), reason))
        self._effects[key] = MutationEffect(
            effect,
            MutationPhase.POST_COMMIT,
            entity=entity,
            reasons=reasons,
        )

    # @testable infrastructure
    def cache_refresh(self, entity, *, reason):
        self._add_entity_cache_effect(MutationEffectType.CACHE_REFRESH, entity, reason)

    # @testable infrastructure
    def cache_delete(self, entity, *, reason):
        self._add_entity_cache_effect(MutationEffectType.CACHE_DELETE, entity, reason)

    # @testable infrastructure
    def notification_upsert(self, entity, *, reason):
        self._add_entity_cache_effect(
            MutationEffectType.NOTIFICATION_UPSERT,
            entity,
            reason,
        )

    # @testable infrastructure
    def notification_delete(self, entity, *, reason):
        self._add_entity_cache_effect(
            MutationEffectType.NOTIFICATION_DELETE,
            entity,
            reason,
        )

    # @testable infrastructure
    def clear_cache_state(self, cache_key, *, reason):
        if not cache_key:
            return
        key = self._effect_key(
            MutationEffectType.CACHE_STATE_DELETE, cache_key=cache_key
        )
        existing = self._effects.get(key)
        reasons = _unique((*(existing.reasons if existing else ()), reason))
        self._effects[key] = MutationEffect(
            MutationEffectType.CACHE_STATE_DELETE,
            MutationPhase.POST_COMMIT,
            cache_key=cache_key,
            reasons=reasons,
        )

    # @testable infrastructure
    def delete_from_search(self, kind, entity, *, reason):
        if not kind or not getattr(entity, "key", None):
            return
        key = (
            MutationEffectType.CACHE_SEARCH_DELETE,
            kind,
            _entity_key(entity),
        )
        existing = self._effects.get(key)
        reasons = _unique((*(existing.reasons if existing else ()), reason))
        self._effects[key] = MutationEffect(
            MutationEffectType.CACHE_SEARCH_DELETE,
            MutationPhase.POST_COMMIT,
            entity=entity,
            cache_kind=kind,
            reasons=reasons,
        )

    # @testable infrastructure
    def delete_blob(self, path, visibility, *, reason):
        if not path:
            return
        key = MutationEffectType.BLOB_DELETE, visibility, path
        existing = self._effects.get(key)
        reasons = _unique((*(existing.reasons if existing else ()), reason))
        self._effects[key] = MutationEffect(
            MutationEffectType.BLOB_DELETE,
            MutationPhase.POST_COMMIT,
            path=path,
            visibility=visibility,
            reasons=reasons,
        )

    # @testable infrastructure
    def plan_standard(self, entity, *, reason="explicit-root", depends_on=()):
        key = _entity_key(entity)
        if key is None:
            return
        if key in self._standard_planning:
            self.standard_root(entity, reason=reason, depends_on=depends_on)
            return
        if key in self._standard_planned:
            self.standard_root(entity, reason=reason, depends_on=depends_on)
            return

        self._standard_planning.add(key)
        from .registry import planner_for

        planner_for(entity).plan_save(
            entity,
            self,
            reason=reason,
            depends_on=depends_on,
        )
        self._standard_planning.remove(key)
        self._standard_planned.add(key)

    # @testable infrastructure
    def consume_intents(self, owner):
        intents = tuple(getattr(owner, "mutation_intents", ()))
        if not intents:
            return
        owner_key = _entity_key(owner)
        if owner_key in self._consumed:
            return
        self._consumed[owner_key] = (owner, intents)

        for intent in intents:
            if intent.intent is MutationIntentType.STANDARD:
                self.plan_standard(intent.entity, reason=intent.reason)
            elif intent.intent in {MutationIntentType.PATCH, MutationIntentType.TOUCH}:
                self.patch(
                    intent.entity,
                    *intent.property_mask,
                    property_updates=intent.property_updates,
                    refresh_cache=intent.refresh_cache,
                    reason=intent.reason,
                    depends_on=(owner,),
                )
            elif intent.intent is MutationIntentType.CACHE_STATE_DELETE:
                self.clear_cache_state(intent.cache_key, reason=intent.reason)
            elif intent.intent is MutationIntentType.CACHE_SEARCH_DELETE:
                self.delete_from_search(
                    intent.cache_kind,
                    intent.entity,
                    reason=intent.reason,
                )
            else:
                raise ValueError(f"Unsupported mutation intent: {intent.intent}")

    # @testable infrastructure
    def _ordered_writes(self, effects):
        writes = [
            effect
            for effect in effects
            if effect.effect in {MutationEffectType.UPSERT, MutationEffectType.UNLINK}
        ]
        by_key = {_entity_key(effect.entity): effect for effect in writes}
        remaining = list(writes)
        ordered = []
        while remaining:
            ready = [
                effect
                for effect in remaining
                if all(
                    _entity_key(dependency) not in by_key
                    or by_key[_entity_key(dependency)] in ordered
                    for dependency in effect.depends_on
                )
            ]
            if not ready:
                keys = [_entity_key(effect.entity) for effect in remaining]
                raise ValueError(f"Cyclic mutation write dependencies: {keys}")
            for effect in ready:
                remaining.remove(effect)
                ordered.append(effect)
        return ordered

    # @testable infrastructure
    def build(self):
        effects = list(self._effects.values())
        delete_keys = {
            _entity_key(effect.entity)
            for effect in effects
            if effect.effect is MutationEffectType.DELETE
        }
        effects = [
            effect
            for effect in effects
            if not (
                _entity_key(effect.entity) in delete_keys
                and effect.effect
                in {
                    MutationEffectType.UPSERT,
                    MutationEffectType.UNLINK,
                    MutationEffectType.CACHE_REFRESH,
                    MutationEffectType.CACHE_SEARCH_DELETE,
                    MutationEffectType.NOTIFICATION_UPSERT,
                }
            )
        ]
        writes = self._ordered_writes(effects)
        deletes = [
            effect for effect in effects if effect.effect is MutationEffectType.DELETE
        ]
        post_commit = [
            effect for effect in effects if effect.phase is MutationPhase.POST_COMMIT
        ]
        return MutationPlan(
            self.operation,
            [*writes, *deletes, *post_commit],
            consumed_intents=tuple(self._consumed.values()),
        )


# @testable infrastructure
class RootMutation:
    """Minimal root-scoped persistence without lifecycle or cache work."""

    @classmethod
    # @testable infrastructure
    def plan(cls, *entities, property_mask=None, property_updates=()):
        builder = MutationPlanBuilder(MutationOperation.SAVE, entities)
        for entity in entities:
            builder.root(
                entity,
                property_mask=property_mask,
                property_updates=property_updates,
                reason="root-only-save",
            )
        return builder.build()


# @testable infrastructure
class StandardMutation:
    """Normal full-document root mutation shared by simple entity kinds."""

    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        builder.standard_root(entity, reason=reason, depends_on=depends_on)
        builder.consume_intents(entity)
