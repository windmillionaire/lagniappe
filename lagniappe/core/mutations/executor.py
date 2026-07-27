"""Execute authoritative mutation effects in durable-first order."""

import json

from ..definitions import (
    MutationEffectType,
    MutationOutcome,
    MutationPhase,
    MutationPlan,
)
from ..exceptions import capture
from ..tools import cache, database


WRITE_EFFECTS = {MutationEffectType.UPSERT, MutationEffectType.UNLINK}


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_save_entities_updates_hash_before_requires
# @tests tests_unit/test_002_entity_general_properties.py::test_save_entities_updates_and_persists_user_before_owned_page
# @pair entities:save-order
# @pair requires:hash-before-requires
# @pair users:user-before-page
# @pair requires:persisted-requires
def _prepare_write(effect):
    entity = effect.entity
    for name in effect.property_updates:
        if name in entity.properties:
            entity.properties[name].update()

    if effect.serialize_processes:
        processes = {key: value for key, value in entity.processes.items() if value}
        for key, updates in processes.items():
            entity.db[key] = json.dumps(updates)

    try:
        entity.db.exclude_from_indexes = entity.exclude_from_index
    except AttributeError:
        pass


# @testable infrastructure
def consume_mutation_intents(plan):
    for owner, captured in plan.consumed_intents:
        current = list(getattr(owner, "mutation_intents", ()))
        captured_ids = {id(intent) for intent in captured}
        owner._mutation_intents = [
            intent for intent in current if id(intent) not in captured_ids
        ]


# @testable infrastructure
def _completed(outcome, effect_type):
    if effect_type not in outcome.completed_effects:
        outcome.completed_effects.append(effect_type)


# @testable infrastructure
def prepare_durable_writes(plan):
    writes = [
        effect
        for effect in plan.effects
        if effect.phase is MutationPhase.DURABLE and effect.effect in WRITE_EFFECTS
    ]
    for effect in writes:
        _prepare_write(effect)
    return writes


# @testable infrastructure
def execute_post_commit(plan):
    """Execute declared post-commit effects and return types plus errors."""
    completed = []
    errors = []

    # @testable infrastructure
    def complete(effect_type):
        if effect_type not in completed:
            completed.append(effect_type)

    post_commit = [
        effect for effect in plan.effects if effect.phase is MutationPhase.POST_COMMIT
    ]
    refresh = [
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_REFRESH
    ]
    if refresh:
        cache.update(*refresh)
        complete(MutationEffectType.CACHE_REFRESH)

    deleted = [
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_DELETE
    ]
    if deleted:
        cache.delete(deleted)
        complete(MutationEffectType.CACHE_DELETE)

    for effect in post_commit:
        if effect.effect is MutationEffectType.CACHE_STATE_DELETE:
            cache.clear_state(effect.cache_key)
            complete(MutationEffectType.CACHE_STATE_DELETE)
        elif effect.effect is MutationEffectType.CACHE_SEARCH_DELETE:
            cache.delete_entity_from_search(effect.cache_kind, effect.entity)
            complete(MutationEffectType.CACHE_SEARCH_DELETE)

    blob_effects = [
        effect
        for effect in post_commit
        if effect.effect is MutationEffectType.BLOB_DELETE
    ]
    if blob_effects:
        errors.extend(
            database.delete_blobs(
                [effect.path for effect in blob_effects if effect.visibility == "private"],
                [effect.path for effect in blob_effects if effect.visibility == "public"],
            )
            or []
        )
        complete(MutationEffectType.BLOB_DELETE)
    return completed, errors


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_executes_datastore_before_cache_and_reports_cache_failure
# @tests tests_unit/test_022_mutation_contracts.py::test_save_plan_is_serializable_and_preserves_intents_until_commit
# @features mutations
# @dimensions save mutation-plan durable-first typed-intent-preservation post-commit-outcome cache-failure
def execute_mutation(plan):
    """Execute durable effects before rebuildable cache and blob effects."""
    if not isinstance(plan, MutationPlan):
        raise TypeError("execute_mutation requires a MutationPlan")

    outcome = MutationOutcome(plan.operation)
    durable = [effect for effect in plan.effects if effect.phase is MutationPhase.DURABLE]
    writes = prepare_durable_writes(plan)
    deletes = [
        effect for effect in durable if effect.effect is MutationEffectType.DELETE
    ]

    if writes:
        database.save_mutations(
            (effect.entity, effect.property_mask) for effect in writes
        )
        for effect in writes:
            _completed(outcome, effect.effect)

    if deletes:
        database.delete_entities(effect.entity for effect in deletes)
        _completed(outcome, MutationEffectType.DELETE)

    consume_mutation_intents(plan)
    outcome.durable_committed = True

    try:
        completed, errors = execute_post_commit(plan)
        for effect_type in completed:
            _completed(outcome, effect_type)
        outcome.errors.extend(errors)
    except Exception as error:
        capture(
            error,
            context={
                "mutation": {
                    "operation": plan.operation.value,
                    "durable_committed": outcome.durable_committed,
                }
            },
        )
        outcome.errors.append(str(error))

    outcome.post_commit_complete = not outcome.errors
    return outcome
