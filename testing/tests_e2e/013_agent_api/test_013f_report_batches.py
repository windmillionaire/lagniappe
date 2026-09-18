"""General report batches through real entity, Storage, and Datastore boundaries."""
from uuid import uuid4

import pytest
from flask_login import login_user

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai.reporting.entity_updates import prepare_entity_updates
from lagniappe.core.tools.ai.reporting.execution.runner import run_report
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.document_crdt import append_fragment
from lagniappe.web import app
from testing.definitions import Users

pytestmark = pytest.mark.e2e


# @source lagniappe/core/tools/ai/reporting/execution/batch.py::WorkingEntities
# @source lagniappe/core/properties/project.py::ModelTasks
# @source lagniappe/core/tools/entity_patches.py::prepare_patch
# @matrix ai-report : batching identity dependencies
# @matrix project : db-load model-tasks ordering relation-attach
# @matrix entity-patch : preservation preparation
def test_saved_project_and_page_forms_survive_linked_batch_updates(get_user):
    actor = get_user(Users.OWNER).entity
    suffix = uuid4().hex[:8]
    with app.test_request_context('/'):
        login_user(actor)
        forms = [Entities.FORM.create({"name": f"Saved Form {suffix}-{i}", "form-type": "page"}) for i in range(2)]
        for form in forms:
            form.schema = [{"id": "notes", "type": "textarea", "title": "Notes"}]
        category = Entities.CATEGORY.create({"name": f"Saved Category {suffix}"})
        category.properties.forms.value = forms
        pages = [Entities.PAGE.create({"name": f"Saved Page {suffix}-{i}", "model": category, "form": forms[0]}) for i in range(2)]
        project = Entities.PROJECT.create({"name": f"Saved Project {suffix}"})
        model = Entities.MODEL_TASK.create(project, {"name": "Existing"})
        task = Entities.TASK.create({"name": "Existing Task", "page": pages[0], "project": project, "model": model})
        Entities.save(*forms, category, *pages, project, model, task)
        actions = [
            {"id": "model", "type": "create_model_task", "data": {"name": "Added", "project": project.urlsafe_key}},
            {"id": "order", "type": "update_project", "data": {"entity": project.urlsafe_key, "changes": {
                "name": "Reviewed Project", "description": "Reviewed description", "model_tasks": [model.urlsafe_key, "$model"],
            }}},
            {"id": "task", "type": "update_task", "data": {"entity": task.urlsafe_key, "changes": {"description": "Reviewed Task"}}},
            {"id": "page", "type": "update_page", "data": {"entity": pages[1].urlsafe_key, "changes": {
                "form": forms[1].urlsafe_key, "submission": {"notes": "Moved answers"},
            }}},
        ]
        report = Entities.REPORT.create({"name": f"Saved batch {suffix}", "parent": actor, "user": actor, "status": "ready", "proposal": {"summary": "Saved linked changes", "actions": actions}})
        prepare_entity_updates(report.proposal, actor)
        Entities.save(report)
        result = run_report(report, actor)
        assert result["status"] == "complete", report.error
        assert all(record["status"] == "complete" for record in result["actions"]), result["actions"]
        saved = Entities.fetch_one(project.key, request=Fetch.direct())
        assert saved.name == "Reviewed Project"
        assert saved.description == "Reviewed description"
        assert [item.name for item in sorted(saved.model_tasks, key=lambda item: item.order)] == ["Existing", "Added"]
        saved_category = Entities.fetch_one(category.key, request=Fetch.direct())
        assert {form.key for form in saved_category.forms} == {form.key for form in forms}
        saved_page = Entities.fetch_one(pages[1].key, request=Fetch.direct())
        assert saved_page.form.key == forms[1].key
        assert saved_page.submission == {"notes": "Moved answers"}


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @source lagniappe/core/tools/ai/reporting/execution/batch.py::ExecutionBatch
# @source lagniappe/core/tools/ai/reporting/execution/actions/documents.py::_append_page_document
# @matrix ai-report : batching atomicity documents dependencies recovery
# @matrix ai-report : document append persistence
def test_related_creations_and_document_appends_commit_together(get_user, monkeypatch):
    user = get_user(Users.OWNER)
    actor = user.entity
    suffix = uuid4().hex[:8]
    with app.test_request_context('/'):
        login_user(actor)
        category = Entities.CATEGORY.get_uncategorized_pages()
        existing = Entities.PAGE.create({"name": f"Existing batch page {suffix}", "model": category})
        existing.description = "Keep this description"
        baseline, _ = append_fragment(None, '<p>Original document</p>', 'initial')
        existing.properties.document.save(html='<p>Original document</p>', ydoc=baseline)
        Entities.save(existing, category)
        actions = [
            {"id": "project", "type": "create_project", "data": {"name": f"Batch project {suffix}"}},
            {"id": "model", "type": "create_model_task", "data": {"name": "Review", "project_action": "project"}},
            {"id": "form", "type": "create_form", "data": {"name": f"Batch Form {suffix}", "form_type": "task", "schema": [{"id": "notes", "type": "textarea", "title": "Notes"}]}},
            {"id": "default", "type": "update_model_task", "data": {"entity": "$model", "changes": {"form": "$form"}}},
            {"id": "existing_doc", "type": "append_page_document", "data": {"page": existing.urlsafe_key, "document": '<p>Additional document content</p>'}},
            {"id": "existing_doc_again", "type": "append_page_document", "data": {"page": existing.urlsafe_key, "document": '<p>Second addition</p>'}},
        ]
        for i in range(3):
            actions.extend([
                {"id": f"page{i}", "type": "create_page", "data": {"name": f"Batch page {suffix}-{i}", "category": category.urlsafe_key}},
                {"id": f"task{i}", "type": "create_task", "data": {"name": f"Batch task {suffix}-{i}", "page_action": f"page{i}", "project_action": "project", "model_action": "model", "submission": {"notes": "Migrated notes"}}},
                {"id": f"doc{i}", "type": "append_page_document", "data": {"page": f"$page{i}", "document": f'<p>Document {i}</p>'}},
            ])
        report = Entities.REPORT.create({"name": f"Batch report {suffix}", "parent": actor, "user": actor, "status": "ready", "proposal": {"summary": "Related changes", "actions": actions}})
        prepare_entity_updates(report.proposal, actor)
        Entities.save(report)
        writes_seen = []
        save = database_utility.save_mutations
        def observe(writes, **kwargs):
            writes = list(writes)
            if any(item.entity_kind != 'report' and mask is None for item, mask in writes):
                writes_seen.append(writes)
                assert any(item.key == report.key for item, _mask in writes)
                assert kwargs.get('guards')
            return save(writes, **kwargs)
        monkeypatch.setattr(database_utility, 'save_mutations', observe)
        result = run_report(report, actor)
        assert result['status'] == 'complete', report.error
        assert len(writes_seen) == 1
        writes = writes_seen[0]
        assert len({item.key for item, _mask in writes}) == len(writes)
        category_write = next(mask for item, mask in writes if item.key == category.key)
        assert set(category_write) == {'modified'}
        existing_write = next(mask for item, mask in writes if item.key == existing.key)
        assert set(existing_write) == {'assets', 'document_history', 'modified'}
        ids = {record['id']: record['entity']['id'] for record in result['actions']}
        for i in range(3):
            task = Entities.fetch_one(ids[f'task{i}'], request=Fetch.direct())
            assert task.properties.model.key == Entities.fetch_one(ids['model'], request=Fetch.root()).key
            assert task.form.urlsafe_key == ids['form']
            assert task.submission == {'notes': 'Migrated notes'}
            page = Entities.fetch_one(ids[f'page{i}'], request=Fetch.direct())
            assert f'Document {i}' in page.properties.document.html
        updated = Entities.fetch_one(existing.key, request=Fetch.direct())
        assert updated.description == 'Keep this description'
        assert 'Original document' in updated.properties.document.html
        assert 'Additional document content' in updated.properties.document.html
        assert 'Second addition' in updated.properties.document.html
        versions = database_get.document_history(updated)
        assert len(versions) == 1
        version = Entities.DOCUMENT_HISTORY(versions[0])
        assert version.name.startswith('Before report append')
        assert version.get_asset('document').html() == '<p>Original document</p>'
        saved = Entities.fetch_one(report.key, request=Fetch.direct())
        assert saved.result['status'] == 'complete'
        assert saved.db['execution_documents'] == []
        assert run_report(saved, actor)['status'] == 'complete'
        assert len(writes_seen) == 1
