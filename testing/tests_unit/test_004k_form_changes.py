"""Durable form-change ownership, partial reads, and narrow submission writes."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

from google.cloud import datastore
import pytest

from lagniappe.core.definitions import (
    Action,
    Fetch,
    MutationEffect,
    MutationEffectType,
    MutationPhase,
)
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import MutationConflict, ValidationError
from lagniappe.core.mutations import executor
from lagniappe.core.tools import (
    form_changes as changes,
    form_conversions as conversions,
)
from lagniappe.core.tools.database import get as database_get, utility
from lagniappe.core.tools.deferred_jobs.adapters.form_change import FormChangeAdapter
from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext

pytestmark = pytest.mark.unit


def record(kind, name, **data):
    row = datastore.Entity(
        key=datastore.Key(
            "models" if kind == "form" else "instances", name, project="test-project"
        )
    )
    row.update(
        type=kind,
        hash=name,
        name=name,
        created=datetime(2026, 9, 11, tzinfo=timezone.utc),
        **data,
    )
    return getattr(Entities, kind.upper())(row)


@pytest.fixture
def migration(monkeypatch):
    old = [{"id": "answer", "type": "input", "input": "text", "title": "Answer"}]
    new = [{"id": "answer", "type": "input", "input": "number", "title": "Answer"}]
    form = record(
        "form", "source", form_type="task", schema=json.dumps(old), version="old"
    )
    actor = SimpleNamespace(urlsafe_key="actor", timezone="UTC", is_authenticated=False)
    change = {
        "id": "change1",
        "job": "job1",
        "digest": "digest",
        "source_generation": 0,
        "zone": "UTC",
        "phase": "checking",
        "applied": False,
        "baseline": "source",
        "image_urls": {},
        "operations": conversions.classify_changes(old, new),
        "target": {
            "name": "Converted",
            "schema": new,
            "assets": {},
            "generation": 1,
            "version": "new",
            "html_fields": {},
        },
    }
    form.db[changes.PENDING] = json.dumps(change)
    job = SimpleNamespace(
        urlsafe_key="job1",
        key=datastore.Key("job", "job1", project="test-project"),
        lease_token="lease",
        status="running",
    )
    job_row = datastore.Entity(key=job.key)
    job_row.update(status="running", lease_token="lease")
    rows = {form.key: deepcopy(form.db), job.key: job_row}
    writes = []

    def fetch_one(identifier, *, request):
        if hasattr(identifier, "db"):
            return identifier
        if isinstance(identifier, datastore.Entity):
            raw = identifier
        else:
            raw = rows.get(identifier)
        if raw is None:
            return None
        return getattr(Entities, raw["type"].upper())(deepcopy(raw))

    def commit(items, *, guards=None, deletes=()):
        items = list(items)
        for key, expected in guards or []:
            raw = rows.get(key)
            assert raw is not None
            if isinstance(expected, utility.ExactEntityState):
                mismatch = dict(raw) != expected
            else:
                mismatch = any(raw.get(key) != value for key, value in expected.items())
            if mismatch:
                raise MutationConflict("changed")
        for entity, mask in items:
            if mask is None:
                rows[entity.key] = deepcopy(entity.db)
            else:
                for name in mask:
                    if name in entity.db:
                        rows[entity.key][name] = deepcopy(entity.db[name])
                    else:
                        rows[entity.key].pop(name, None)
            writes.append((entity.key, mask))
        for entity in deletes:
            rows.pop(entity.key, None)

    monkeypatch.setattr(Entities, "fetch_one", fetch_one)
    monkeypatch.setattr(
        Entities,
        "fetch",
        lambda *keys, request: [
            value for key in keys if (value := fetch_one(key, request=request))
        ],
    )
    monkeypatch.setattr(database_get, "entity", lambda key: deepcopy(rows.get(key)))
    monkeypatch.setattr(utility, "save_mutations", commit)
    monkeypatch.setattr(
        utility,
        "create_named_key",
        lambda kind, identity: datastore.Key(kind, identity, project="test-project"),
    )
    monkeypatch.setattr(executor, "execute_post_commit", lambda plan: ([], []))
    for kind in (Entities.FORM, Entities.PAGE, Entities.TASK):
        monkeypatch.setattr(kind, "allowed", lambda self, action, user=None: True)
    context = DeferredJobContext(
        job, actor, None, {"form": form}, {"change_id": "change1"}, {}
    )
    return SimpleNamespace(
        form=form,
        change=change,
        rows=rows,
        context=context,
        writes=writes,
        commit=commit,
        actor=actor,
    )


# @matrix form-migration : partial-read generation
def test_pending_definition_resolves_each_generation(migration):
    form = migration.form
    target = record("page", "page", form=form.key)
    assert changes.effective_definition(target, form).schema[0]["input"] == "text"
    target.db["generation"] = 1
    resolved = changes.effective_definition(target, form)
    assert resolved.schema[0]["input"] == "number"
    assert resolved.generation == 1
    assert form.generation == 0
    assert changes.PENDING in form.db


# @source lagniappe/core/properties/category.py::CategoryTable
# @source lagniappe/core/properties/filter.py::FilterTable
# @matrix form-migration : pending-projection removed-field typed-filter
@pytest.mark.parametrize("remove", [False, True])
def test_pending_and_removed_fields_are_withheld_from_tables_and_filters(migration, monkeypatch, remove):
    from lagniappe.core.properties.category import CategoryTable
    from lagniappe.core.properties.filter import FilterTable
    from lagniappe.core.tools.filters.contract import field_catalog, resolve_filter_field, FilterContractError
    from testing.utility.test_entities import TestEntities

    monkeypatch.setattr(Entities.CATEGORY, "allowed", lambda self, action, user=None: True)
    if remove:
        migration.change["target"]["schema"] = []
        migration.form.db[changes.PENDING] = json.dumps(migration.change)

    def projections(form):
        category = TestEntities.get("CATEGORY", {"name": "Projection parent", "hash": "projection-parent"})
        category.form = form
        table = CategoryTable(entity=category)
        filtered = FilterTable(entity=SimpleNamespace(entity_kind="filter", parent=category, related=[form]))
        return category, table, filtered

    category, table, filtered = projections(migration.form)
    assert "answer" not in table.fields
    assert "answer" not in filtered.fields
    catalog = field_catalog(category, migration.actor)
    assert (migration.form.hash, "answer") not in catalog
    assert any(entry.allowed_values for entry in catalog.values())  # Form restriction stays available.
    with pytest.raises(FilterContractError, match="unavailable"):
        resolve_filter_field(category, migration.form.hash, "answer", migration.actor)

    published = changes.target_definition(migration.form)
    category, table, filtered = projections(published)
    if remove:
        assert "answer" not in table.fields
        assert "answer" not in filtered.fields
        with pytest.raises(FilterContractError, match="unavailable"):
            resolve_filter_field(category, published.hash, "answer", migration.actor)
    else:
        assert table.fields["answer"].schema["input"] == "number"
        assert filtered.fields["answer"].schema["input"] == "number"
        assert resolve_filter_field(category, published.hash, "answer", migration.actor).field.schema["input"] == "number"


# @matrix form-migration : save no-submission-read durable-intent
def test_start_stages_intent_without_enumerating_submissions(migration, monkeypatch):
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    form = migration.form
    form.db.pop(changes.PENDING)
    migration.rows[form.key] = deepcopy(form.db)
    draft = {
        "name": "Converted",
        "schema": migration.change["target"]["schema"],
        "html_fields": {},
        "migration": {"version": 1, "clear_invalid": True},
    }
    monkeypatch.setattr(
        changes,
        "target_batch",
        lambda *args: pytest.fail("Save enumerated submissions"),
    )
    monkeypatch.setattr(changes, "change_response", lambda form: {"accepted": True})

    def start(spec):
        writes, guards = FormChangeAdapter().start_writes(spec, migration.context.job)
        migration.commit(writes, guards=guards)

    monkeypatch.setattr(DeferredJobs, "start", start)
    assert changes.start_change(form, draft, "save1", migration.actor) == {
        "accepted": True
    }
    pending = json.loads(migration.rows[form.key][changes.PENDING])
    assert pending["target"]["generation"] == 1
    assert pending["source_generation"] == 0
    assert json.loads(migration.rows[form.key]["schema"])[0]["input"] == "text"


# @matrix form-migration : completed-task legacy-generation notice masked-write
@pytest.mark.parametrize(
    "envelope",
    [
        None,
        {
            "submission": {"answer": "original"},
            "form_key": "original-form",
            "generation": 0,
        },
    ],
)
def test_prepare_target_preserves_completion_and_original_answers(migration, envelope):
    task = record(
        "task",
        "task",
        form=migration.form.key,
        submission=json.dumps({"answer": "7", "unrelated": False}),
        completed=True,
    )
    if envelope:
        task.db["completed_submission"] = json.dumps(envelope)
    before = deepcopy(task.db)
    converted = changes.prepare_target(task, migration.change)
    assert converted.completed
    assert converted.generation == 1
    assert json.loads(converted.db["submission"]) == {"answer": 7, "unrelated": False}
    original = json.loads(converted.db["completed_submission"])
    assert (
        original == envelope
        if envelope
        else original["submission"] == {"answer": "7", "unrelated": False}
    )
    assert json.loads(converted.db[changes.NOTICE])["answer"]["value"] == "7"
    assert task.db == before


# @matrix form-migration : duplicate-delivery guarded-write effects-retry
def test_apply_is_guarded_idempotent_and_retries_effects(migration, monkeypatch):
    page = record(
        "page",
        "page",
        form=migration.form.key,
        submission=json.dumps({"answer": "2"}),
        description="Preserve",
        categories=[],
    )
    migration.rows[page.key] = deepcopy(page.db)
    monkeypatch.setattr(
        executor, "execute_post_commit", lambda plan: ([], ["cache unavailable"])
    )
    with pytest.raises(RuntimeError, match="display refresh"):
        changes.apply_target(migration.context, page.db)
    assert json.loads(migration.rows[page.key]["submission"]) == {"answer": 2}
    notice = migration.rows[page.key][changes.NOTICE]
    monkeypatch.setattr(executor, "execute_post_commit", lambda plan: ([], []))
    changes.apply_target(migration.context, migration.rows[page.key])
    assert migration.rows[page.key][changes.NOTICE] == notice
    assert migration.rows[page.key]["description"] == "Preserve"
    assert sum(1 for key, mask in migration.writes if key == page.key) == 1
    migration.rows[migration.context.job.key]["lease_token"] = "replacement"
    with pytest.raises(MutationConflict):
        changes.apply_target(migration.context, page.db)


# @matrix form-migration : writer-fence stale-generation completion-race
def test_mutation_guard_blocks_locked_and_stale_answer_writes(migration):
    page = record(
        "page", "page", form=migration.form.key, submission=json.dumps({"answer": "2"})
    )
    migration.rows[page.key] = deepcopy(page.db)
    effect = MutationEffect(
        MutationEffectType.UPSERT, MutationPhase.DURABLE, entity=page
    )
    with pytest.raises(ValidationError, match="being updated"):
        changes.mutation_guards([effect], [])
    migration.rows[migration.form.key].pop(changes.PENDING)
    migration.rows[migration.form.key]["generation"] = 1
    with pytest.raises(MutationConflict, match="fields changed"):
        changes.mutation_guards([effect], [])
    touch = MutationEffect(
        MutationEffectType.UPSERT,
        MutationPhase.DURABLE,
        entity=page,
        property_mask=("modified",),
    )
    assert changes.mutation_guards([touch], []) == []


# @matrix form-migration : writer-fence stale-generation creation reassignment
def test_new_attachments_adopt_current_generation_without_accepting_stale_answers(
    migration,
):
    migration.rows[migration.form.key].pop(changes.PENDING)
    migration.rows[migration.form.key]["generation"] = 1
    current = Entities.fetch_one(migration.form.key, request=Fetch.root())
    page = record("page", "new", form=current.key)
    page.form = current
    effect = MutationEffect(
        MutationEffectType.UPSERT, MutationPhase.DURABLE, entity=page
    )
    guards = changes.mutation_guards([effect], [])
    assert page.generation == 1
    assert (current.key, {changes.PENDING: None, "generation": 1}) in guards

    # Moving an existing row to this Form adopts its generation too.
    migration.rows[page.key] = record("page", "new", generation=0).db
    page.db["generation"] = 0
    changes.mutation_guards([effect], [])
    assert page.generation == 1

    page.form = migration.form  # an editor that loaded the old representation
    page.db["submission"] = json.dumps({"answer": "old text"})
    with pytest.raises(MutationConflict, match="before these answers were prepared"):
        changes.mutation_guards([effect], [])


# @matrix form-migration : writer-fence pending-delete masked-write attachment
@pytest.mark.parametrize("operation", [
    "delete-form", "patch-page", "patch-task", "create-page", "create-task",
    "reassign-page", "reassign-task",
])
def test_pending_change_fences_conflicting_writes(migration, operation):
    if operation == "delete-form":
        effect = MutationEffect(
            MutationEffectType.DELETE, MutationPhase.DURABLE, entity=migration.form,
        )
        writes, deletes = [], [effect]
    else:
        action, kind = operation.split("-")
        entity = record(kind, "target", form=migration.form.key)
        if action != "create":
            persisted = deepcopy(entity.db)
            if action == "reassign":
                persisted.pop("form")
            migration.rows[entity.key] = persisted
        effect = MutationEffect(
            MutationEffectType.UPSERT, MutationPhase.DURABLE, entity=entity,
            property_mask=("submission",) if action == "patch" else None,
        )
        writes, deletes = [effect], []
    before = deepcopy(migration.rows)
    with pytest.raises(ValidationError, match="being updated"):
        changes.mutation_guards(writes, deletes)
    assert migration.rows == before
    assert migration.writes == []


# @matrix form-migration : preflight batch-job publication
def test_adapter_checks_all_values_before_applying(migration, monkeypatch):
    first = record(
        "page",
        "first",
        form=migration.form.key,
        submission=json.dumps({"answer": "bad"}),
    )
    second = record("page", "second", form=migration.form.key, generation=9)

    class Batch(list):
        next_cursor = None

    monkeypatch.setattr(
        changes, "target_batch", lambda form, cursor: Batch([first.db, second.db])
    )
    with pytest.raises(ValidationError, match="unexpected form generation"):
        FormChangeAdapter().prepare(migration.context)
    assert migration.writes == []
    second.db["generation"] = 0
    FormChangeAdapter().prepare(migration.context)
    assert migration.context.checkpoint["validated"] is True
    assert migration.context.checkpoint["checked"] == 2
    assert migration.writes == []


# @matrix form-migration : form-authority restricted-submissions
@pytest.mark.parametrize("kind", ["page", "task"])
def test_form_authority_migrates_restricted_submissions(migration, monkeypatch, kind):
    target = record(
        kind, "restricted", form=migration.form.key,
        submission=json.dumps({"answer": "007"}), restricted_to=["admin"],
    )
    monkeypatch.setattr(type(target), "allowed", lambda self, action, user=None: False)
    assert migration.form.allowed(Action.EDIT, user=migration.actor)
    assert not target.allowed(Action.VIEW, user=migration.actor)
    assert not target.allowed(Action.EDIT, user=migration.actor)

    class Batch(list):
        next_cursor = None

    monkeypatch.setattr(changes, "target_batch", lambda form, cursor: Batch([target.db]))
    FormChangeAdapter().prepare(migration.context)
    assert migration.context.checkpoint["validated"] is True
    converted = changes.prepare_target(changes.load_target(target.db), migration.change)
    assert json.loads(converted.db["submission"]) == {"answer": 7}
    assert json.loads(converted.db[changes.NOTICE])["answer"]["value"] == "007"
    assert converted.db["restricted_to"] == ["admin"]
    assert not converted.allowed(Action.VIEW, user=migration.actor)


# @matrix form-migration : informational-notice changed-cells
def test_notice_shows_only_changed_fields_and_cells(migration):
    schema = {
        "id": "table",
        "type": "table",
        "title": "Items",
        "columns": [{"id": "x", "type": "input", "input": "text", "title": "Quantity"}],
    }
    page = record(
        "page",
        "page",
        submission=json.dumps({"table": {"rows": [{"x": 2}, {"x": "same"}, {}]}}),
        pre_migration=json.dumps(
            {
                "table": {
                    "schema": schema,
                    "value": {"rows": [{"x": "2"}, {"x": "same"}, {"x": "bad"}]},
                    "reason": "converted",
                }
            }
        ),
    )
    form = record("form", "table-form", form_type="page", schema=json.dumps([schema]))
    page.form = form
    result = changes.notice_projection(page)
    assert len(result) == 2
    assert result[0]["label"] == "Items · Row 1 · Quantity"
    assert result[0]["reason"] == "converted"
    assert result[1]["label"] == "Items · Row 3 · Quantity"
    assert result[1]["reason"] == "invalid"
    assert changes.NOTICE in page.db


# @matrix form-migration : retry cancellation ownership
def test_recovery_retains_partial_changes_and_cancels_only_before_apply(
    migration, monkeypatch
):
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
    from lagniappe.core.tools.database import deferred_jobs

    change = migration.change
    change["applied"] = True
    migration.rows[migration.form.key][changes.PENDING] = json.dumps(change)
    with pytest.raises(ValidationError, match="Retry"):
        changes.recover_change(migration.form, migration.actor, "cancel")
    change["applied"] = False
    migration.rows[migration.form.key][changes.PENDING] = json.dumps(change)
    monkeypatch.setattr(deferred_jobs, "release_deferred_job_lock", lambda *args: True)
    monkeypatch.setattr(DeferredJobs, "cancel", lambda *args: True)
    monkeypatch.setattr(
        changes,
        "change_response",
        lambda form: {"pending": bool(form.db.get(changes.PENDING))},
    )
    assert changes.recover_change(migration.form, migration.actor, "cancel") == {
        "pending": False
    }
    assert changes.PENDING not in migration.rows[migration.form.key]
