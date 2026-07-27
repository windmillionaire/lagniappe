"""Executable entity mutation contract and ordering regressions."""

import pytest

from lagniappe.core.definitions import (
    MutationEffectType,
    MutationIntent,
    MutationOperation,
)
from lagniappe.core.definitions.mutation_contracts import (
    ENTITY_MUTATION_CONTRACTS,
)
from lagniappe.core.entities import Entities
from lagniappe.core.mutations import (
    execute_mutation,
    plan_mutation,
    plan_root,
    registered_kinds,
)
from lagniappe.core.mutations import executor as mutation_executor
from lagniappe.core.mutations.delete import Survivor, _merge_survivors
from testing.utility import mutation_contracts
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


class SaveDB(dict):
    pass


def _writes(plan):
    return [
        effect
        for effect in plan.effects
        if effect.effect in {MutationEffectType.UPSERT, MutationEffectType.UNLINK}
    ]


# @features mutations
# @dimensions contract completeness serialization lookup validation planner-registry
# @source lagniappe/core/mutations/__init__.py::registered_kinds
# @source lagniappe/core/mutations/registry.py::planner_for
def test_mutation_contract_registry_covers_persisted_entities_and_relations(capsys):
    assert mutation_contracts._registry_errors() == []
    assert registered_kinds() == frozenset(ENTITY_MUTATION_CONTRACTS)
    assert {"user", "page", "task", "file", "report"}.issubset(
        ENTITY_MUTATION_CONTRACTS
    )
    assert mutation_contracts.main(["--kind", "file", "--check"]) == 0
    output = capsys.readouterr().out
    assert "pages -> page" in output
    assert "tasks -> task, task_history" in output


# @features mutations
# @dimensions save plan serialization durable-first typed-intent-preservation
# @source lagniappe/core/definitions/mutations.py::MutationEffect
# @source lagniappe/core/definitions/mutations.py::MutationPlan
# @source lagniappe/core/mutations/executor.py::execute_mutation
def test_save_plan_is_serializable_and_preserves_intents_until_commit(monkeypatch):
    page = TestEntities.get("PAGE", {"name": "Plan Page", "hash": "plan-page"})
    category = TestEntities.get(
        "CATEGORY", {"name": "Plan Category", "hash": "plan-category"}
    )
    intent = MutationIntent.touch(category, reason="plan-dependent-owner")
    page.add_mutation_intents(intent)
    page._db = SaveDB(page.db)
    category._db = SaveDB(category.db)
    plan = plan_mutation(MutationOperation.SAVE, page, registry=Entities)

    assert plan.operation is MutationOperation.SAVE
    writes = _writes(plan)
    assert [effect.entity for effect in writes] == [page, category]
    assert writes[0].property_mask is None
    assert writes[1].property_mask == ("modified",)
    assert [effect.effect for effect in writes] == [
        MutationEffectType.UPSERT,
        MutationEffectType.UPSERT,
    ]
    serialized = plan.to_dict()
    assert serialized["operation"] == "save"
    assert serialized["effects"][0]["reasons"] == ["explicit-root"]

    monkeypatch.setattr(
        mutation_executor.database,
        "save_mutations",
        lambda _writes: (_ for _ in ()).throw(RuntimeError("datastore down")),
    )
    with pytest.raises(RuntimeError, match="datastore down"):
        execute_mutation(plan)
    assert page.mutation_intents == [intent]


# @pair mutations:root-save
# @pair mutations:exclusions
# @pair mutations:direct-save
# @pair mutations:lifecycle-isolation
# @pair mutations:intent-isolation
# @pair mutations:cache-isolation
# @pair mutations:plan
# @pair mutations:serialization
# @source lagniappe/core/entities/__init__.py::EntityRegistry.save_root
# @source lagniappe/core/mutations/__init__.py::plan_root
def test_save_root_persists_full_exclusions_without_lifecycle_intents_or_cache(
    monkeypatch,
):
    task = TestEntities.get(
        "TASK",
        {
            "name": "Root-only task",
            "hash": "root-only-task",
            "page": {"name": "Root parent", "hash": "root-only-parent"},
        },
    )
    relation = TestEntities.get(
        "CATEGORY", {"name": "Pending relation", "hash": "pending-relation"}
    )
    intent = MutationIntent.touch(relation, reason="pending-intent")
    task.add_mutation_intents(intent)
    task._db = SaveDB(task.db)
    task.db["modified"] = "unchanged"
    plan = plan_root(task)

    events = []

    def save_mutations(writes):
        events.append(("database", list(writes)))

    monkeypatch.setattr(mutation_executor.database, "save_mutations", save_mutations)
    monkeypatch.setattr(
        mutation_executor.cache,
        "update",
        lambda *entities: events.append(("cache", entities)),
    )

    outcome = Entities.save_root(task)

    writes = _writes(plan)
    assert len(writes) == 1
    assert writes[0].entity is task
    assert writes[0].property_updates == ()
    assert plan.to_dict()["effects"][0]["reasons"] == ["root-only-save"]
    assert task.db.exclude_from_indexes == task.exclude_from_index
    assert "default_submission" in task.db.exclude_from_indexes
    assert task.db["modified"] == "unchanged"
    assert task.mutation_intents == [intent]
    assert events == [("database", [(task, None)])]
    assert outcome.complete is True


# @features mutations
# @dimensions touch root-save modified exclusions property-mask
# @source lagniappe/core/entities/__init__.py::EntityRegistry.touch
# @source lagniappe/core/mutations/__init__.py::plan_root
def test_touch_uses_masked_root_save_and_only_updates_modified(monkeypatch):
    category = TestEntities.get(
        "CATEGORY", {"name": "Touched category", "hash": "touched-category"}
    )
    category._db = SaveDB(category.db)
    original = category.modified
    saved = []

    def save_mutations(writes):
        saved.extend(writes)

    monkeypatch.setattr(mutation_executor.database, "save_mutations", save_mutations)

    outcome = Entities.touch(category)

    assert category.modified is not None
    assert category.modified != original
    assert category.db.exclude_from_indexes == category.exclude_from_index
    assert saved == [(category, ("modified",))]
    assert outcome.complete is True


# @features mutations
# @dimensions save mutation-plan durable-first post-commit-outcome cache-failure
# @source lagniappe/core/mutations/executor.py::execute_mutation
def test_save_executes_datastore_before_cache_and_reports_cache_failure(monkeypatch):
    entity = TestEntities.get(
        "CATEGORY", {"name": "Ordered Save", "hash": "ordered-save"}
    )
    entity._db = SaveDB(entity.db)
    events = []

    def save_mutations(writes):
        assert list(writes) == [(entity, None)]
        events.append("datastore")

    monkeypatch.setattr(mutation_executor.database, "save_mutations", save_mutations)

    def fail_cache(*entities):
        events.append("cache")
        raise RuntimeError("redis down")

    monkeypatch.setattr(mutation_executor.cache, "update", fail_cache)

    outcome = Entities.save(entity)

    assert events == ["datastore", "cache"]
    assert outcome.durable_committed is True
    assert outcome.post_commit_complete is False
    assert outcome.errors == ["redis down"]


# @features mutations
# @dimensions save multiple-explicit-roots standard-lifecycle property-mask
# @source lagniappe/core/mutations/__init__.py::plan_mutation
def test_each_explicit_save_argument_is_a_standard_root():
    page = TestEntities.get("PAGE", {"name": "Root page", "hash": "root-page"})
    category = TestEntities.get(
        "CATEGORY", {"name": "Root category", "hash": "root-category"}
    )

    plan = plan_mutation(
        MutationOperation.SAVE,
        page,
        category,
        registry=Entities,
    )

    writes = {effect.entity.key: effect for effect in _writes(plan)}
    assert writes[page.key].property_mask is None
    assert writes[category.key].property_mask is None
    assert writes[page.key].serialize_processes is True
    assert writes[category.key].serialize_processes is True


# @features mutations user
# @dimensions save canonical-page intent-isolation
# @source lagniappe/core/mutations/save.py::UserMutation.plan_save
def test_existing_user_save_does_not_implicitly_mutate_canonical_page():
    user = TestEntities.get(
        "USER",
        {
            "name": "Existing user",
            "hash": "existing-user",
            "email": "existing@example.test",
            "page": {"name": "Existing user page", "hash": "existing-user-page"},
        },
    )

    plan = plan_mutation(MutationOperation.SAVE, user, registry=Entities)

    assert [effect.entity for effect in _writes(plan)] == [user]


# @features mutations
# @dimensions delete plan overlapping-roots mergeable-unlinks property-mask
# @source lagniappe/core/mutations/delete.py::_merge_survivors
def test_delete_survivor_merge_combines_relation_removals():
    page_a = TestEntities.get("PAGE", {"name": "A", "hash": "merge-page-a"})
    page_b = TestEntities.get("PAGE", {"name": "B", "hash": "merge-page-b"})
    file_a = TestEntities.get("FILE", {"name": "Shared", "hash": "shared-file"})
    file_b = TestEntities.get("FILE", {"name": "Shared", "hash": "shared-file"})
    file_b._key = file_a.key
    file_a.db["pages"] = [page_b.key]
    file_b.db["pages"] = [page_a.key]

    merged = _merge_survivors(
        [
            Survivor(file_a, {"pages"}, {"modified"}, {"unlink-a"}),
            Survivor(file_b, {"pages"}, {"modified"}, {"unlink-b"}),
        ]
    )

    assert len(merged) == 1
    assert merged[0].entity is file_a
    assert merged[0].properties == {"pages"}
    assert file_a.db.get("pages") is None
