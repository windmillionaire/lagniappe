"""Report batches share working entities and atomically publish their receipts."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest
from google.cloud.datastore import Entity as StoredEntity, Key

from lagniappe.core.definitions import MutationOperation, MutationEffectType
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import MutationConflict
from lagniappe.core.tools.ai.reporting.entity_updates import prepare_entity_updates
from lagniappe.core.tools.ai.reporting.execution import batch as batches, runner
from lagniappe.core.tools.ai.reporting.execution.actions.base import ReportActionAdapter
from lagniappe.core.tools.cache import documents
from lagniappe.core.tools.document_crdt import append_fragment
from lagniappe.core.properties.common_assets import Document
from lagniappe.core.mutations import plan_mutation
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


def clone(item):
    result = type(item)(dict(item.test_spec)) if getattr(item, "_testing", False) else type(item)(item.key)
    result._key = item.key
    result._db = deepcopy(item.db)
    if hasattr(item, "test_spec"):
        result.test_spec = dict(item.test_spec)
    for relation in item.relations:
        if relation.attached_entities:
            result.properties[relation.id].attach(item.related_entities)
    if item.entity_kind == "report":
        result.result = deepcopy(item.result)
        result.proposal = deepcopy(item.proposal)
        result.status, result.pending = item.status, item.pending
    if item.entity_kind in {"page", "project"}:
        result.properties.document._html = item.properties.document._html
        result.properties.document._ydoc = item.properties.document._ydoc
    return result


def setup_case(monkeypatch, actions, initial=()):
    _patch_fake_keys(monkeypatch)
    actor = _test_user("batch-owner")
    report = TestEntities.get("REPORT", {
        "name": "Batch report", "hash": "batch-report", "parent": actor,
        "user": actor, "status": "ready", "pending": False,
        "proposal": {"summary": "Batch changes", "confidence": 1, "actions": actions},
    })
    state = SimpleNamespace(report=report, actor=actor, rows={}, commits=[], events=[], reads=[], fail=None)
    for item in (*initial, report):
        state.rows[item.urlsafe_key] = clone(item)

    def fetch(identifier, **kwargs):
        if hasattr(identifier, "db"):
            return identifier
        state.reads.append(identifier)
        key = getattr(identifier, "name", identifier)
        return clone(state.rows[key]) if key in state.rows else None

    def save(*entities):
        edits = [item for item in entities if item.entity_kind != "report"]
        if edits and state.fail == "before":
            state.fail = None
            raise MutationConflict("Rejected test batch")
        staged = list(entities)
        for intent in state.report.mutation_intents:
            if intent.entity is not None and intent.entity not in staged:
                staged.append(intent.entity)
        # Copy the complete write set before accepting any of it.
        rows = {item.urlsafe_key: clone(item) for item in staged}
        state.rows.update(rows)
        state.commits.append(tuple(staged))
        state.events.append("commit" if edits or state.report.mutation_intents else "report")
        if edits and state.fail in {"after", "replaced"}:
            if state.fail == "replaced":
                state.rows[state.report.urlsafe_key].db["execution_commit"] = "another-commit"
            state.fail = None
            raise TimeoutError("Lost commit response")

    monkeypatch.setattr(Entities, "fetch_one", fetch)
    monkeypatch.setattr(Entities, "save", save)
    return state


def create(kind, name, **data):
    return {"id": name, "type": "create_" + kind, "data": {"name": name, **data}}


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report : batching identity dependencies atomicity recovery
def test_dependent_creations_share_one_commit(monkeypatch):
    actions = [create("project", "project"), create("model_task", "model", project_action="project"),
               create("form", "form", form_type="task", schema=[{"id": "notes", "type": "textarea", "title": "Notes"}]),
               {"id": "assign_form", "type": "update_model_task", "data": {"entity": "$model", "changes": {"form": "$form"}}},
               {"id": "describe", "type": "update_project", "data": {"entity": "$project", "changes": {"description": "Shared project"}}},
               create("model_task", "second_model", project_action="project"),
               create("category", "category")]
    for i in range(3):
        actions.extend([create("page", f"page{i}", category_action="category"),
                        create("task", f"task{i}", page_action=f"page{i}", project_action="project", model_action="model", submission={"notes": "Keep"})])
    state = setup_case(monkeypatch, actions)
    prepare_entity_updates(state.report.proposal, state.actor)
    result = runner.run_report(state.report, state.actor)
    assert result["status"] == "complete", state.report.error
    commits = [items for items in state.commits if len(items) > 1]
    assert len(commits) == 1
    items = commits[0]
    assert len({item.key for item in items}) == len(items)
    form = next(item for item in items if item.entity_kind == "form")
    model = next(item for item in items if item.entity_kind == "model" and item.name == "model")
    assert sorted(item.order for item in items if item.entity_kind == "model") == [1, 2]
    assert model.form.key == form.key
    tasks = [item for item in items if item.entity_kind == "task"]
    assert len(tasks) == 3
    assert all(task.model is model and task.form is form for task in tasks)
    assert all(task.submission == {"notes": "Keep"} for task in tasks)
    assert state.rows[state.report.urlsafe_key].result["status"] == "complete"
    assert runner.run_report(state.report, state.actor) == result
    assert len([items for items in state.commits if len(items) > 1]) == 1


# @matrix ai-report : batching identity dependencies
def test_updates_reuse_loaded_entities_and_merge_final_state(monkeypatch):
    project = TestEntities.get("PROJECT", {"name": "Original", "hash": "original-project", "description": "Keep"})
    project.description = "Keep"
    state = setup_case(monkeypatch, [], (project,))
    workspace = batches.WorkingEntities()
    first = workspace.resolve(project.urlsafe_key)
    assert workspace.resolve(project.urlsafe_key) is first
    assert len(state.reads) == 1
    revised = clone(first)
    revised.name = "Revised"
    workspace.remember(revised)
    assert workspace.resolve(project.urlsafe_key) is revised
    assert revised.description == "Keep"
    assert len(state.reads) == 1
    state.rows["short-reference"] = clone(project)
    assert workspace.resolve("short-reference") is revised
    assert workspace.resolve("short-reference").name == "Revised"
    assert len(state.reads) == 2
    from lagniappe.core.tools.ai.reporting.entity_updates import _comparison
    assert _comparison({"id": project.urlsafe_key, "name": ""}, workspace) == project.urlsafe_key


# @source lagniappe/core/tools/ai/reporting/execution/batch.py::ExecutionBatch
# @source lagniappe/core/tools/ai/reporting/execution/batch.py::WorkingEntities
# @matrix ai-report : batching identity dependencies atomicity
def test_shared_category_form_patches_merge_without_full_owner_save(monkeypatch):
    def make(kind, name):
        row = StoredEntity(key=Key("models", name, project="test-project"))
        row.update(type=kind, name=name, hash=name)
        return getattr(Entities, kind.upper())(row)
    category = make("category", "shared-category")
    pages, forms, actions = [], [], []
    for i in range(2):
        page, form = make("page", f"page{i}"), make("form", f"form{i}")
        page.model = category
        form.form_type = "page"
        form.schema = [{"id": "notes", "type": "textarea", "title": "Notes"}]
        pages.append(page)
        forms.append(form)
        actions.append({"id": f"update{i}", "type": "update_page", "data": {
            "entity": page.urlsafe_key, "changes": {"form": form.urlsafe_key, "submission": {"notes": f"Notes {i}"}},
        }})
    state = setup_case(monkeypatch, actions, (category, *pages, *forms))
    prepare_entity_updates(state.report.proposal, state.actor)
    assert runner.run_report(state.report, state.actor)["status"] == "complete", state.report.error
    saved_pages = [item for item in state.commits[-1] if item.entity_kind == "page"]
    assert len(saved_pages) == 2
    assert saved_pages[0].model is saved_pages[1].model
    plan = plan_mutation(MutationOperation.SAVE, *saved_pages, registry=Entities)
    write = next(effect for effect in plan.effects if effect.effect is MutationEffectType.UPSERT and effect.entity.key == category.key)
    assert set(write.property_mask) == {"forms", "modified"}
    assert set(write.entity.properties.forms.keys) == {form.key for form in forms}


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report : batching atomicity recovery
@pytest.mark.parametrize("failure", ["before", "after", "replaced"])
def test_batch_failure_and_ambiguous_commit_do_not_duplicate_creations(monkeypatch, failure):
    state = setup_case(monkeypatch, [create("project", "first"), create("project", "second")])
    state.fail = failure
    if failure == "replaced":
        from lagniappe.core.tools.deferred_jobs.errors import DeferredJobInfrastructureError
        with pytest.raises(DeferredJobInfrastructureError, match="Another batch"):
            runner.run_report(state.report, state.actor)
        saved = state.rows[state.report.urlsafe_key]
        assert saved.result["status"] == "complete"
        assert saved.db["execution_commit"] == "another-commit"
        state.report = clone(saved)
    result = runner.run_report(state.report, state.actor)
    if failure == "before":
        assert result["status"] == "failed"
        assert not any(item.entity_kind == "project" for item in state.rows.values())
        assert result["actions"][1]["status"] == "pending"
        result = runner.run_report(state.report, state.actor)
    assert result["status"] == "complete", state.report.error
    assert sorted(item.name for item in state.rows.values() if item.entity_kind == "project") == ["first", "second"]
    assert len([items for items in state.commits if len(items) > 1]) == 1


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report : batching atomicity documents recovery
def test_documents_upload_before_combined_commit_and_publish_after(monkeypatch):
    actions = [create("category", "category")]
    for i in range(10):
        actions.extend([create("page", f"page{i}", category_action="category"),
                        {"id": f"doc{i}", "type": "append_page_document", "data": {"page": f"$page{i}", "document": f"<p>Document {i}</p>"}}])
    state = setup_case(monkeypatch, actions)

    def upload(document, *, html, ydoc):
        state.events.append("upload")
        document._html, document._ydoc = html, ydoc
        document.entity.assets["document"] = {"type": "html", "path": f"document-{len(state.events)}", "fingerprint": hashlib.md5(html.encode()).hexdigest()}
        document.entity.db["assets"] = json.dumps(document.entity.assets)

    monkeypatch.setattr(Document, "save", upload)
    monkeypatch.setattr(documents, "publish_document_checkpoint", lambda *_args, **_kwargs: state.events.append("publish"))
    result = runner.run_report(state.report, state.actor)
    assert result["status"] == "complete", state.report.error
    assert state.events == ["report", *(["upload"] * 10), "commit", *(["publish"] * 10), "report"]
    pages = [item for item in state.rows.values() if item.entity_kind == "page"]
    assert len(pages) == 10
    assert all(page.assets.get("document") for page in pages)
    assert len([items for items in state.commits if len(items) > 1]) == 1


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report : batching atomicity recovery
def test_batch_boundaries_resume_without_replaying_completed_work(monkeypatch):
    state = setup_case(monkeypatch, [create("project", "first"), create("project", "second"), create("project", "third")])
    monkeypatch.setattr(batches, "MAX_BATCH_ACTIONS", 2)
    original = ReportActionAdapter.apply
    def fail_third(adapter, action, *args, **kwargs):
        if action["id"] == "third":
            raise RuntimeError("Interrupted preparation")
        return original(adapter, action, *args, **kwargs)
    monkeypatch.setattr(ReportActionAdapter, "apply", fail_third)
    result = runner.run_report(state.report, state.actor)
    assert [record["status"] for record in result["actions"]] == ["complete", "complete", "failed"]
    first_ids = {key for key, item in state.rows.items() if item.entity_kind == "project"}
    monkeypatch.setattr(ReportActionAdapter, "apply", original)
    # Simulate another process loading the saved report before Retry.
    report = clone(state.rows[state.report.urlsafe_key])
    state.report = report
    assert runner.run_report(report, state.actor)["status"] == "complete"
    assert first_ids <= {key for key, item in state.rows.items() if item.entity_kind == "project"}
    assert len([item for item in state.rows.values() if item.entity_kind == "project"]) == 3


# @source lagniappe/core/tools/ai/reporting/execution/batch.py::ExecutionBatch
# @matrix ai-report : batching atomicity recovery
def test_lost_intermediate_commit_resumes_from_saved_receipt(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.errors import DeferredJobInfrastructureError
    state = setup_case(monkeypatch, [create("project", "first"), create("project", "second"), create("project", "third")])
    monkeypatch.setattr(batches, "MAX_BATCH_ACTIONS", 2)
    state.fail = "after"
    with pytest.raises(DeferredJobInfrastructureError, match="batch was saved"):
        runner.run_report(state.report, state.actor)
    saved = state.rows[state.report.urlsafe_key]
    assert [record["status"] for record in saved.result["actions"]] == ["complete", "complete", "pending"]
    state.report = clone(saved)
    assert runner.run_report(state.report, state.actor)["status"] == "complete"
    assert sorted(item.name for item in state.rows.values() if item.entity_kind == "project") == ["first", "second", "third"]


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report : batching documents recovery
def test_document_publication_retries_without_reapplying_changes(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.errors import DeferredJobInfrastructureError
    actions = [create("category", "category"), create("page", "page", category_action="category", document="<p>Keep</p>")]
    state = setup_case(monkeypatch, actions)
    def upload(document, *, html, ydoc):
        document._html, document._ydoc = html, ydoc
        document.entity.assets["document"] = {"type": "html", "path": "uploaded", "fingerprint": hashlib.md5(html.encode()).hexdigest()}
        document.entity.db["assets"] = json.dumps(document.entity.assets)
    monkeypatch.setattr(Document, "save", upload)
    monkeypatch.setattr(documents, "publish_document_checkpoint", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Redis unavailable")))
    with pytest.raises(DeferredJobInfrastructureError, match="publication"):
        runner.run_report(state.report, state.actor)
    saved = state.rows[state.report.urlsafe_key]
    assert saved.result["status"] == "complete"
    assert len(saved.db["execution_documents"]) == 1
    assert len([items for items in state.commits if len(items) > 1]) == 1
    monkeypatch.setattr(documents, "publish_document_checkpoint", lambda *_args, **_kwargs: None)
    state.report = clone(saved)
    assert runner.run_report(state.report, state.actor)["status"] == "complete"
    assert state.rows[state.report.urlsafe_key].db["execution_documents"] == []
    assert len([items for items in state.commits if len(items) > 1]) == 1


# @source lagniappe/core/tools/ai/reporting/execution/batch.py::ExecutionBatch
# @matrix ai-report : batching atomicity documents recovery
def test_concurrent_document_edit_rejects_uncommitted_batch(monkeypatch):
    baseline, _ = append_fragment(None, "<p>Original</p>", "baseline")
    pages = [TestEntities.get("PAGE", {"name": f"Existing {i}", "hash": f"existing-document-{i}"}) for i in range(2)]
    actions = [create("project", "project")]
    for i, page in enumerate(pages):
        page.properties.document._html = "<p>Original</p>"
        page.properties.document._ydoc = baseline
        actions.append({"id": f"append{i}", "type": "append_page_document",
                        "data": {"page": page.urlsafe_key, "document": "<p>Additional</p>"}})
    state = setup_case(monkeypatch, actions, pages)
    def upload(document, *, html, ydoc):
        document._html, document._ydoc = html, ydoc
        state.events.append("upload")
    def current(_id, *, seed, reconcile):
        assert reconcile is False
        changed = state.events.count("upload") == 2 and _id == pages[1].properties.document.sync_id
        return {**seed, "updates": [{"update": "concurrent"}] if changed else []}
    monkeypatch.setattr(Document, "save", upload)
    monkeypatch.setattr(documents, "current_document_state", current)
    monkeypatch.setattr(documents, "publish_document_checkpoint", lambda *_args, **_kwargs: pytest.fail("Rejected document must not publish"))
    result = runner.run_report(state.report, state.actor)
    assert result["status"] == "failed"
    assert "Document changed" in state.report.error
    assert not any(item.entity_kind == "project" for item in state.rows.values())
    assert all(state.rows[page.urlsafe_key].properties.document.ydoc == baseline for page in pages)
    assert state.rows[state.report.urlsafe_key].db["execution_documents"] == []
    assert state.report.mutation_intents == []
