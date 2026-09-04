"""Executable entity mutation contract and ordering regressions."""

from datetime import datetime, timezone

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
from lagniappe.core.entities.notification import Notification
from lagniappe.core.entities.deferred_job import DeferredJob
from lagniappe.core.entities.user import User
from lagniappe.core.mutations import (
    execute_mutation,
    plan_document_checkpoint,
    plan_document_parent_touch,
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


# @matrix mutations task-scheduling : durable-first post-commit
# @source lagniappe/core/definitions/mutations.py::MutationIntent.dispatch_scheduled_uncomplete
def test_scheduled_uncomplete_dispatch_is_planned_after_task_write():
    task = TestEntities.get(
        "TASK",
        {
            "name": "Durable scheduled dispatch",
            "hash": "mutation-uncomplete",
            "page": {"name": "Task page", "hash": "mutation-uncomplete-page"},
        },
    )
    task.db["scheduled_uncomplete_token"] = "token"
    task.db["scheduled_uncomplete_at"] = datetime(2026, 8, 25, tzinfo=timezone.utc)
    task.add_mutation_intents(
        MutationIntent.dispatch_scheduled_uncomplete(
            task,
            reason="scheduled-task-uncompletion",
        )
    )

    plan = plan_mutation(MutationOperation.SAVE, task, registry=Entities)

    task_write = next(
        index
        for index, effect in enumerate(plan.effects)
        if effect.effect is MutationEffectType.UPSERT and effect.entity is task
    )
    dispatch = next(
        index
        for index, effect in enumerate(plan.effects)
        if effect.effect is MutationEffectType.SCHEDULED_UNCOMPLETE_DISPATCH
    )
    assert task_write < dispatch


# @matrix mutations : durable-first
# @matrix public-pages public-directory sitemap : invalidation
def test_public_discovery_invalidation_runs_after_durable_write(monkeypatch):
    page = TestEntities.get(
        "PAGE",
        {"name": "Discoverable page", "hash": "discoverable-page"},
    )
    page.is_public = True
    page._db = SaveDB(page.db)
    events = []

    monkeypatch.setattr(
        mutation_executor.database_utility,
        "save_mutations",
        lambda _writes: events.append("datastore"),
    )
    monkeypatch.setattr(
        mutation_executor.cache,
        "update",
        lambda *_entities: events.append("entity-cache"),
    )
    monkeypatch.setattr(
        mutation_executor.cache,
        "update_owner_projection",
        lambda *_entities: None,
    )
    monkeypatch.setattr(
        mutation_executor.cache,
        "invalidate_public_discovery",
        lambda: events.append("public-discovery"),
    )

    outcome = execute_mutation(
        plan_mutation(MutationOperation.SAVE, page, registry=Entities)
    )

    assert events == ["datastore", "entity-cache", "public-discovery"]
    assert (
        MutationEffectType.PUBLIC_DISCOVERY_INVALIDATE
        in outcome.completed_effects
    )
    assert outcome.complete is True


# @matrix categories public-directory : invalidation save
def test_category_save_plans_public_discovery_invalidation():
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Published category", "hash": "published-category"},
    )

    plan = plan_mutation(MutationOperation.SAVE, category, registry=Entities)

    discovery = [
        effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.PUBLIC_DISCOVERY_INVALIDATE
    ]
    assert len(discovery) == 1
    assert discovery[0].reasons == ("category-save",)


# @matrix mutations : completeness contract lookup planner-registry serialization validation
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


# @matrix mutations : durable-first plan save serialization typed-intent-preservation
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
        mutation_executor.database_utility,
        "save_mutations",
        lambda _writes: (_ for _ in ()).throw(RuntimeError("datastore down")),
    )
    with pytest.raises(RuntimeError, match="datastore down"):
        execute_mutation(plan)
    assert page.mutation_intents == [intent]


# @matrix mutations : cache-isolation direct-save exclusions intent-isolation lifecycle-isolation plan root-save serialization
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

    monkeypatch.setattr(mutation_executor.database_utility, "save_mutations", save_mutations)
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


# @matrix mutations : exclusions modified property-mask root-save touch
def test_touch_uses_masked_root_save_and_only_updates_modified(monkeypatch):
    category = TestEntities.get(
        "CATEGORY", {"name": "Touched category", "hash": "touched-category"}
    )
    category._db = SaveDB(category.db)
    original = category.modified
    saved = []

    def save_mutations(writes):
        saved.extend(writes)

    monkeypatch.setattr(mutation_executor.database_utility, "save_mutations", save_mutations)

    outcome = Entities.touch(category)

    assert category.modified is not None
    assert category.modified != original
    assert category.db.exclude_from_indexes == category.exclude_from_index
    assert saved == [(category, ("modified",))]
    assert outcome.complete is True


# @matrix mutations sync : checkpoint document history list-owner parent-fingerprint property-mask
def test_document_checkpoint_masks_parent_state_and_optionally_advances_lists(
    monkeypatch,
):
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Document page",
            "hash": "document-page",
            "categories": [
                {"name": "Document category", "hash": "document-category"}
            ],
        },
    )
    page._db = SaveDB(page.db)
    history = TestEntities.get(
        "CATEGORY",
        {"name": "Document history intent", "hash": "document-history-intent"},
    )
    history._db = SaveDB(history.db)
    page.add_mutation_intents(
        MutationIntent.standard(history, reason="document-history")
    )
    saved = []
    monkeypatch.setattr(
        mutation_executor.database_utility,
        "save_mutations",
        lambda writes: saved.extend(writes),
    )
    monkeypatch.setattr(mutation_executor.cache, "update", lambda *_entities: None)

    original_modified = page.modified
    outcome = Entities.save_document_checkpoint(page)

    assert saved == [
        (page, ("assets", "document_history")),
        (history, None),
    ]
    assert page.modified == original_modified
    assert page.mutation_intents == []
    assert outcome.complete is True

    saved.clear()
    plan = plan_document_checkpoint(
        page,
        advance_parent=True,
        registry=Entities,
    )
    writes = {effect.entity.key: effect for effect in _writes(plan)}

    assert writes[page.key].property_mask == (
        "assets",
        "document_history",
        "modified",
    )
    assert writes[page.key].property_updates == ("modified",)
    assert writes["document-category"].property_mask == ("modified",)


# @matrix mutations sync : document list-owner parent-fingerprint property-mask
def test_document_parent_touch_only_advances_parent_and_list_fingerprints(
    monkeypatch,
):
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Touched document page",
            "hash": "touched-document-page",
            "categories": [
                {
                    "name": "Touched document category",
                    "hash": "touched-document-category",
                }
            ],
        },
    )
    page._db = SaveDB(page.db)
    saved = []
    monkeypatch.setattr(
        mutation_executor.database_utility,
        "save_mutations",
        lambda writes: saved.extend(writes),
    )
    monkeypatch.setattr(mutation_executor.cache, "update", lambda *_entities: None)

    plan = plan_document_parent_touch(page, registry=Entities)
    writes = {effect.entity.key: effect for effect in _writes(plan)}
    outcome = Entities.advance_document_parent(page)

    assert writes[page.key].property_mask == ("modified",)
    assert "assets" not in writes[page.key].property_mask
    assert writes["touched-document-category"].property_mask == ("modified",)
    assert {
        (entity.key, property_mask)
        for entity, property_mask in saved
    } == {
        ("touched-document-page", ("modified",)),
        ("touched-document-category", ("modified",)),
    }
    assert outcome.complete is True


# @matrix notifications : cache-failure-isolation cache-isolation mutation personal-activity
def test_notification_save_updates_projection_without_touching_user(monkeypatch):
    modified = datetime(2026, 7, 30, tzinfo=timezone.utc)
    user = User(testing=True)
    user._key = "notification-user"
    user._db = SaveDB(
        {
            "type": "user",
            "name": "Notification User",
            "email": "notification@example.test",
            "hash": "notification-user-hash",
            "modified": modified,
        }
    )
    notification = Notification(testing=True)
    notification._key = "notification"
    notification.kind = "notification"
    notification.db["hash"] = "notification-hash"
    notification.parent = user
    notification.body = "Ready"
    saved = []

    monkeypatch.setattr(
        mutation_executor.database_utility,
        "save_mutations",
        lambda writes: saved.extend(writes),
    )
    cache_updates = []
    monkeypatch.setattr(
        mutation_executor.cache,
        "update",
        lambda *entities: cache_updates.extend(entities),
    )
    projection_updates = []
    aggregate_updates = []
    monkeypatch.setattr(
        mutation_executor.notification_service,
        "apply_ordinary_mutations",
        lambda **changes: aggregate_updates.append(changes) or {},
    )
    monkeypatch.setattr(
        mutation_executor.cache,
        "update_notification_projection",
        lambda **changes: projection_updates.append(changes),
    )

    outcome = Entities.save(notification)

    assert user.modified == modified
    assert saved == [(notification, None)]
    assert user not in cache_updates
    assert notification._notification_count_delta == 1
    assert aggregate_updates == [{"upserts": [notification], "deletes": []}]
    assert projection_updates == [{"upserts": [notification], "deletes": []}]
    assert outcome.complete is True

    failed_notification = Notification(testing=True)
    failed_notification._key = "failed-notification"
    failed_notification.kind = "notification"
    failed_notification.db["hash"] = "failed-notification-hash"
    failed_notification.parent = user
    failed_notification.body = "Durable despite Redis"
    monkeypatch.setattr(
        mutation_executor.cache,
        "update_notification_projection",
        lambda **_changes: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )

    failed_outcome = Entities.save(failed_notification)

    assert saved[-1] == (failed_notification, None)
    assert failed_outcome.durable_committed is True
    assert failed_outcome.post_commit_complete is False
    assert failed_outcome.errors == ["redis unavailable"]


# @matrix deferred-jobs : cache-isolation mutation redis-projection
def test_job_save_updates_operation_projection_without_touching_relations(monkeypatch):
    modified = datetime(2026, 8, 5, tzinfo=timezone.utc)
    user = User(testing=True)
    user._key = "operation-user"
    user._db = SaveDB(
        {
            "type": "user",
            "name": "Operation User",
            "email": "operation@example.test",
            "hash": "operation-user-hash",
            "modified": modified,
        }
    )
    notification = Notification(testing=True)
    notification._key = "operation-notification"
    notification.kind = "notification"
    notification.db["hash"] = "operation-notification-hash"
    notification.parent = user
    notification.body = "Working"
    notification_modified = notification.modified

    job = DeferredJob(testing=True)
    job._key = "operation-job"
    job.kind = "job"
    job.db["hash"] = "operation-job-hash"
    job.actor = user
    job.notification = notification
    job.status = "running"
    job.status_revision = 3

    saved = []
    monkeypatch.setattr(
        mutation_executor.database_utility,
        "save_mutations",
        lambda writes: saved.extend(writes),
    )
    monkeypatch.setattr(mutation_executor.cache, "update", lambda *_entities: None)
    projected = []
    monkeypatch.setattr(
        mutation_executor.cache,
        "update_operation_projection",
        lambda *jobs: projected.extend(jobs),
    )

    outcome = Entities.save(job)

    assert saved == [(job, None)]
    assert user.modified == modified
    assert notification.modified == notification_modified
    assert projected == [job]
    assert outcome.complete is True


# @pairs deferred-jobs:redis-projection mutations:delete
def test_job_delete_removes_operation_projection_after_commit(monkeypatch):
    job = DeferredJob(testing=True)
    job._key = "deleted-operation-job"
    job.kind = "job"
    job.db["hash"] = "deleted-operation-job-hash"
    job.status = "succeeded"
    job.status_revision = 5
    deleted = []
    projected = []
    monkeypatch.setattr(
        mutation_executor.database_utility,
        "delete_entities",
        lambda entities: deleted.extend(entities),
    )
    monkeypatch.setattr(mutation_executor.cache, "delete", lambda _entities: None)
    monkeypatch.setattr(
        mutation_executor.cache,
        "delete_operation_projection",
        lambda *jobs: projected.extend(jobs),
    )

    outcome = Entities.delete(job)

    assert deleted == [job]
    assert projected == [job]
    assert outcome.complete is True


# @matrix mutations : cache-failure durable-first mutation-plan post-commit-outcome save
def test_save_executes_datastore_before_cache_and_reports_cache_failure(monkeypatch):
    entity = TestEntities.get(
        "CATEGORY", {"name": "Ordered Save", "hash": "ordered-save"}
    )
    entity._db = SaveDB(entity.db)
    events = []

    def save_mutations(writes):
        assert list(writes) == [(entity, None)]
        events.append("datastore")

    monkeypatch.setattr(mutation_executor.database_utility, "save_mutations", save_mutations)

    def fail_cache(*entities):
        events.append("cache")
        raise RuntimeError("redis down")

    monkeypatch.setattr(mutation_executor.cache, "update", fail_cache)

    outcome = Entities.save(entity)

    assert events == ["datastore", "cache"]
    assert outcome.durable_committed is True
    assert outcome.post_commit_complete is False
    assert outcome.errors == ["redis down"]


# @matrix mutations : multiple-explicit-roots property-mask save standard-lifecycle
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


# @matrix mutations user : canonical-page intent-isolation save
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


# @matrix mutations : delete mergeable-unlinks overlapping-roots plan property-mask
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


# @pairs file:delete file:reverse-link mutations:delete mutations:unlink
# @pairs tasks:delete tasks:list-owner-fingerprint tasks:reverse-link
# @pairs tasks:task-history tasks:unlink
def test_file_delete_unlinks_task_references_and_list_owners(monkeypatch):
    page = TestEntities.get(
        "PAGE",
        {"name": "Attachment page", "hash": "attachment-page"},
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Attachment task",
            "hash": "attachment-task",
            "page": {"name": page.name, "hash": page.hash},
        },
    )
    task.properties.page._value = page
    retained = TestEntities.get(
        "FILE",
        {"name": "Retained attachment", "hash": "retained-attachment"},
    )
    deleted = TestEntities.get(
        "FILE",
        {"name": "Deleted attachment", "hash": "deleted-attachment"},
    )
    task.files = [retained, deleted]

    history = Entities.TASK_HISTORY(testing=True)
    history._key = "attachment-history"
    history.kind = "task_history"
    history.created = datetime.now(timezone.utc)
    history.task = task
    history.page = page
    history.linked_pages = []
    history.files = [deleted]

    linked = {task.key: task, history.key: history}

    def fetch_linked_tasks(*identifiers, request):
        assert request.depth.name == "NESTED"
        return [linked[key] for key in identifiers]

    monkeypatch.setattr(Entities, "fetch", fetch_linked_tasks)

    plan = plan_mutation(MutationOperation.DELETE, deleted, registry=Entities)
    writes = {effect.entity.key: effect for effect in _writes(plan)}
    deleted_entities = [
        effect.entity
        for effect in plan.effects
        if effect.effect is MutationEffectType.DELETE
    ]

    assert deleted_entities == [deleted]
    assert task.files == [retained]
    assert history.files == []
    assert deleted.properties.tasks.keys == []
    assert retained.properties.tasks.keys == [task.key]
    assert writes[task.key].property_mask == ("files", "modified")
    assert writes[history.key].property_mask == ("files",)
    assert writes[page.key].property_mask == ("modified",)
