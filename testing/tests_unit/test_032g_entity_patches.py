"""Cohesive patches validate selected changes and preserve omitted fields."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from google.cloud.datastore import Key, Entity as DatastoreEntity
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import MutationConflict, ValidationError
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.entity_patches import prepare_patch
from lagniappe.core.tools.ai.reporting.entity_updates import (
    execute_update_action, prepare_update_action, review_update_action,
)
from testing.utility.ai_report_fakes import _test_user, _permissioned_user

pytestmark = pytest.mark.unit


def entity(kind, name):
    row = DatastoreEntity(key=Key("activity", name, project="test-project"))
    row["name"] = name
    row["hash"] = name
    result = getattr(Entities, kind)(row)
    result.kind = result.entity_kind
    result.name = name
    return result


def case():
    actor = _test_user("patch-owner")
    page = entity("PAGE", "page")
    form = entity("FORM", "old-form")
    form.form_type = "task"
    form.schema = [{"id": "answer", "type": "input", "input": "text", "title": "Answer"}, {"id": "kept", "type": "input", "input": "text", "title": "Keep"}]
    task = entity("TASK", "task")
    task.page = page
    task.form = form
    task.description = "Long original description"
    task.submission = {"answer": "old answer", "kept": "preserve me"}
    task.due_date = datetime(2026, 10, 1, tzinfo=timezone.utc)
    task.db["history"] = True
    task.db["scheduled_uncomplete_token"] = "keep-token"
    return actor, task, form, page


# @matrix entity-patch : preservation validation preparation permissions
def test_task_patch_preserves_omitted_values_and_source():
    actor, task, form, page = case()
    original = deepcopy(task.db)
    prepared = prepare_patch(task, {"description": "Short", "submission": {"answer": "new answer"}}, actor)
    assert task.db == original
    assert prepared.entity.key == task.key
    assert prepared.entity.description == "Short"
    assert prepared.entity.submission == {"answer": "new answer", "kept": "preserve me"}
    assert prepared.entity.form.key == form.key
    assert prepared.entity.page.key == page.key
    assert prepared.entity.due_date == task.due_date
    assert prepared.entity.db["history"] is True
    assert prepared.entity.db["scheduled_uncomplete_token"] == "keep-token"
    assert prepared.guards == ()
    assert prepared.before["description"] == "Long original description"
    assert prepared.after["description"] == "Short"


# @matrix entity-patch : preservation validation preparation permissions
def test_reassignment_requires_complete_values_and_reviews_removals():
    actor, task, form, page = case()
    target = entity("FORM", "target-form")
    target.form_type = "task"
    target.schema = [{"id": "summary", "type": "input", "input": "text", "title": "Summary"}]
    for patch in ({"form": target}, {"form": target, "submission": {}}):
        with pytest.raises(ValidationError, match="complete|every"):
            prepare_patch(task, patch, actor)
    prepared = prepare_patch(task, {"form": target, "submission": {"summary": "Migrated"}, "description": "Short"}, actor)
    assert prepared.removed_values == {"answer": "old answer", "kept": "preserve me"}
    assert prepared.entity.submission == {"summary": "Migrated"}
    assert prepared.entity.form.key == target.key
    assert task.form.key == form.key
    assert task.description == "Long original description"
    assert {item.key for item in prepared.forms} == {form.key, target.key}


# @matrix entity-patch : preservation validation preparation permissions
# @source lagniappe/core/properties/schema.py::SchemaFields.prepare_ai_field
# @matrix ai-report submission : validation failure-isolation
def test_patch_rejects_completed_locked_invalid_and_unauthorized_targets():
    actor, task, form, page = case()
    original = deepcopy(task.db)
    with pytest.raises(ValidationError, match="unknown"):
        prepare_patch(task, {"description": "Short", "submission": {"missing": "value"}}, actor)
    assert task.db == original
    task.completed = True
    with pytest.raises(ValidationError, match="Completed"):
        prepare_patch(task, {"name": "Changed"}, actor)
    task.completed = False
    form.db["pending_form_change"] = "pending"
    with pytest.raises(ValidationError, match="Wait"):
        prepare_patch(task, {"name": "Changed"}, actor)
    form.db.pop("pending_form_change")
    with pytest.raises(ValidationError, match="permission"):
        prepare_patch(task, {"name": "Changed"}, None)
    with pytest.raises(ValidationError, match="cannot be cleared"):
        prepare_patch(task, {"name": None}, actor)


# @matrix entity-patch : preservation validation preparation permissions
def test_model_and_project_patches_preserve_defaults_and_validate_order():
    actor, task, form, page = case()
    project = entity("PROJECT", "project")
    first, second = entity("MODEL_TASK", "first"), entity("MODEL_TASK", "second")
    for index, model in enumerate((first, second), 1):
        model.project, model.form, model.order = project, form, index
    project.properties.model_tasks._value = [first, second]
    changed = prepare_patch(first, {"name": "Renamed"}, actor)
    assert changed.entity.form.key == form.key
    assert first.name == "first"
    ordered = prepare_patch(project, {"model_tasks": [second, first]}, actor)
    assert [(model.name, model.order) for model in ordered.writes[1:]] == [("second", 1), ("first", 2)]
    assert (first.order, second.order) == (1, 2)
    assert [item["name"] for item in ordered.before["model_tasks"]] == ["first", "second"]
    assert [item["name"] for item in ordered.after["model_tasks"]] == ["second", "first"]
    with pytest.raises(ValidationError, match="exactly once"):
        prepare_patch(project, {"model_tasks": [first, first]}, actor)


# @matrix entity-patch : preservation validation preparation permissions
def test_page_patch_preserves_omitted_membership():
    actor, task, form, page = case()
    category = entity("CATEGORY", "category")
    page.model = category
    original = deepcopy(page.db)
    prepared = prepare_patch(page, {"description": "New description"}, actor)
    assert prepared.entity.model.key == category.key
    assert page.db == original


# @matrix entity-patch : preservation validation preparation permissions
def test_patch_checks_completion_and_migrations_without_owner_guards(monkeypatch):
    actor, task, form, page = case()
    prepared = prepare_patch(task, {"description": "Short", "submission": {"answer": "Migrated"}}, actor)
    assert prepared.guards == ()
    page.db["modified"] = datetime.now(timezone.utc)
    assert prepare_patch(task, {"description": "Short"}, actor).entity.description == "Short"
    task.completed = True
    with pytest.raises(ValidationError, match="Completed"):
        prepare_patch(task, {"description": "Short"}, actor)
    task.completed = False
    form.db["pending_form_change"] = "concurrent-migration"
    with pytest.raises(ValidationError, match="Wait"):
        prepare_patch(task, {"description": "Short"}, actor)
    assert task.description == "Long original description"


# @matrix entity-patch : preservation validation preparation permissions
def test_patch_validates_classification_assignee_and_explicit_clears():
    actor, task, form, page = case()
    project, other = entity("PROJECT", "project"), entity("PROJECT", "other")
    model = entity("MODEL_TASK", "model")
    model.project = project
    task.model, task.project = model, project
    with pytest.raises(ValidationError, match="model task"):
        prepare_patch(task, {"project": other}, actor)
    moved = prepare_patch(task, {"project": other, "model": None}, actor)
    assert moved.entity.project.key == other.key
    assert moved.entity.model is None
    with pytest.raises(ValidationError, match="linked to a user"):
        prepare_patch(task, {"assigned_to": page}, actor)
    cleared = prepare_patch(task, {"form": None, "submission": {}, "description": None, "due_date": None}, actor)
    assert cleared.entity.form is None
    assert not cleared.entity.submission
    assert cleared.entity.description is None
    assert cleared.entity.due_date is None
    assert task.form.key == form.key


# @matrix entity-patch : preservation validation preparation permissions
def test_page_form_registration_is_detached_and_pending_checklist_stays_unchecked():
    actor, task, form, page = case()
    category = entity("CATEGORY", "category")
    page.model = category
    target = entity("FORM", "page-form")
    target.form_type = "page"
    target.schema = [{"id": "pending", "type": "checkbox", "title": "Pending"}]
    prepared = prepare_patch(page, {"form": target, "submission": {"pending": False}}, actor)
    assert prepared.entity.submission == {"pending": False}
    assert not category.forms
    assert not page.form
    assert any(intent.reason == "page-category-form-registration" for intent in prepared.entity.mutation_intents)


# @matrix entity-patch : preservation preparation
def test_page_form_registration_preserves_unloaded_category_forms(monkeypatch):
    actor, _task, _form, page = case()
    category = entity("CATEGORY", "shallow-category")
    original = entity("FORM", "original-page-form")
    target = entity("FORM", "added-page-form")
    for form in (original, target):
        form.form_type = "page"
        form.schema = [{"id": "notes", "type": "textarea", "title": "Notes"}]
    category.db["forms"] = [original.key]
    category.properties.forms.attach({})
    page.model = category
    reads = []

    def fetch(*keys, request):
        reads.extend(keys)
        return [original]

    monkeypatch.setattr(Entities, "fetch", fetch)
    prepared = prepare_patch(page, {"form": target, "submission": {"notes": "Keep"}}, actor)
    registration = next(intent for intent in prepared.entity.mutation_intents if intent.reason == "page-category-form-registration")
    assert set(registration.entity.properties.forms.keys) == {original.key, target.key}
    assert category.properties.forms.keys == [original.key]
    assert reads == [original.key]


# @matrix entity-patch : preservation validation preparation permissions
def test_patch_schedule_and_form_type_and_permission_validation():
    actor, task, form, page = case()
    with pytest.raises(ValidationError, match="permission"):
        prepare_patch(task, {"name": "Changed"}, _permissioned_user("reader", {}))
    wrong_form = entity("FORM", "page-only")
    wrong_form.form_type = "page"
    with pytest.raises(ValidationError, match="task Form"):
        prepare_patch(task, {"form": wrong_form, "submission": {}}, actor)
    changed = prepare_patch(task, {"schedule": {"kind": "recurring", "interval": 2, "unit": "week"}}, actor)
    assert changed.entity.properties.recurring.interval == 2
    assert changed.after["schedule"]["recurring"]["interval"] == 2
    assert task.db["scheduled_uncomplete_token"] == "keep-token"
    cleared = prepare_patch(task, {"schedule": None}, actor)
    assert not cleared.entity.properties.schedule.value
    assert task.db["scheduled_uncomplete_token"] == "keep-token"


# @matrix entity-patch : integration review dependencies stale-state
def test_update_review_and_execution_share_exact_references(monkeypatch):
    actor, task, form, page = case()
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: task if reference is task or reference == task.urlsafe_key else None)
    target = entity("FORM", "target")
    target.form_type = "task"
    target.schema = [{"id": "summary", "type": "input", "input": "text", "title": "Summary"}]
    action = {"type": "update_task", "data": {"entity": task.urlsafe_key, "changes": {
        "form": "$new-form", "submission": {"summary": "Migrated"}, "description": "Short", "due_date": "2026-11-01",
    }}, "_entity_update": {"forged": True}}
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: reference if hasattr(reference, "entity_kind") else {task.urlsafe_key: task, target.urlsafe_key: target}.get(reference))
    outputs = {"new-form": target}
    review_update_action(action, actor, outputs)
    assert "forged" not in action["_entity_update"]
    assert action["_entity_update"]["removed_values"]["answer"] == "old answer"
    updated, writes, metadata = execute_update_action(action, None, actor, outputs)
    assert updated.submission == {"summary": "Migrated"}
    assert updated.description == "Short"
    assert writes == [updated]
    assert metadata["previous"]["description"] == "Long original description"
    assert task.description == "Long original description"


# @matrix entity-patch : integration review dependencies stale-state
def test_update_execution_overwrites_selected_values_but_rejects_unreviewed_proposal(monkeypatch):
    actor, task, form, page = case()
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: task)
    action = {"type": "update_task", "data": {"entity": task.urlsafe_key, "changes": {"description": "Short"}}}
    with pytest.raises(ValidationError, match="fresh review"):
        execute_update_action(action, None, actor, {})
    review_update_action(action, actor)
    task.description = "Human edit"
    updated, _, _ = execute_update_action(action, None, actor, {})
    assert updated.description == "Short"
    assert task.description == "Human edit"
    review_update_action(action, actor)
    action["data"]["changes"]["description"] = "Unreviewed replacement"
    with pytest.raises(ValidationError, match="fresh review"):
        execute_update_action(action, None, actor, {})


# @matrix entity-patch : integration review dependencies stale-state
def test_update_missing_dependencies_never_fall_back_to_entity_lookup(monkeypatch):
    actor, task, form, page = case()
    reads = []
    def fetch(reference, **kwargs):
        reads.append(reference)
        return task
    monkeypatch.setattr(Entities, "fetch_one", fetch)
    action = {"type": "update_task", "data": {"entity": "$created-task", "changes": {"description": "Short"}}}
    with pytest.raises(ValidationError, match="no successful output"):
        prepare_update_action(action, actor)
    assert reads == []
    review_update_action(action, actor, {"created-task": task})
    with pytest.raises(ValidationError, match="no successful output"):
        execute_update_action(action, None, actor, {})
    assert reads == []


# @matrix entity-patch : integration review dependencies stale-state
def test_proposal_prepares_new_forms_and_model_order(monkeypatch):
    from lagniappe.core.tools.ai.reporting.entity_updates import prepare_entity_updates
    actor, task, old_form, page = case()
    project = entity("PROJECT", "project")
    first = entity("MODEL_TASK", "first")
    first.project, first.order = project, 1
    project.properties.model_tasks._value = [first]
    entities = {item.urlsafe_key: item for item in (task, project, first)}
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: reference if hasattr(reference, "entity_kind") else entities.get(reference))
    proposal = {"actions": [
        {"id": "form", "type": "create_form", "data": {"name": "New Form", "form_type": "task", "schema": [{"id": "summary", "type": "input", "input": "text", "title": "Summary"}]}},
        {"id": "model", "type": "create_model_task", "data": {"name": "Second", "project": project.urlsafe_key, "form_action": "form"}},
        {"id": "order", "type": "update_project", "data": {"entity": project.urlsafe_key, "changes": {"model_tasks": ["$model", first.urlsafe_key]}}},
        {"id": "migrate", "type": "update_task", "data": {"entity": task.urlsafe_key, "changes": {"form": "$form", "model": "$model", "submission": {"summary": "Migrated"}, "description": "Short"}}},
    ]}
    prepare_entity_updates(proposal, actor)
    assert proposal["actions"][2]["depends_on"] == ["model"]
    assert proposal["actions"][2]["_entity_update"]["after"]["model_tasks"] == ["$model", first.urlsafe_key]
    assert proposal["actions"][3]["_entity_update"]["after"]["form"] == "$form"
    assert task.description == "Long original description"
    assert project.model_tasks == [first]


# @matrix entity-patch : integration review dependencies
def test_proposal_orders_models_on_a_new_project():
    from lagniappe.core.tools.ai.reporting.entity_updates import prepare_entity_updates
    proposal = {"actions": [
        {"id": "project", "type": "create_project", "data": {"name": "New Project"}},
        {"id": "first", "type": "create_model_task", "data": {"name": "First", "project_action": "project"}},
        {"id": "second", "type": "create_model_task", "data": {"name": "Second", "project_action": "project"}},
        {"id": "order", "type": "update_project", "data": {"entity": "$project", "changes": {"model_tasks": ["$second", "$first"]}}},
    ]}
    prepare_entity_updates(proposal, _test_user("new-project-owner"))
    assert proposal["actions"][-1]["depends_on"] == ["first", "second"]
    assert proposal["actions"][-1]["_entity_update"]["after"]["model_tasks"] == ["$second", "$first"]


# @matrix ai-report : correction ownership supersession
def test_correction_snapshot_and_approval_reject_changed_source(monkeypatch):
    from lagniappe.core.tools.ai.reporting.corrections import link_correction, approve_correction
    from lagniappe.core.entities.ai_report import REPORT_FORMAT_VERSION
    actor = _test_user("correction-owner")
    source, correction = entity("REPORT", "source"), entity("REPORT", "correction")
    for report in (source, correction):
        report.format_version = REPORT_FORMAT_VERSION
        report.user = actor
        report.parent = actor
        report.input_files = []
        report.pending = False
    source.status = "failed"
    source.proposal = {"summary": "Original", "actions": []}
    source.result = {"status": "failed", "actions": [{"id": "created", "status": "complete"}]}
    link_correction(correction, source, actor)
    assert not source.db.get("superseded_by")
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: source)
    saved = []
    monkeypatch.setattr(Entities, "save", lambda *items: saved.extend(items))
    source.result = {"status": "complete", "actions": []}
    with pytest.raises(ValidationError, match="original execution changed"):
        approve_correction(correction, actor)
    assert not saved
    source.result = deepcopy(correction.db["correction"]["result"])
    approve_correction(correction, actor)
    assert source.db["superseded_by"] == correction.urlsafe_key
    assert saved == [source, correction]
    assert source._form_additional_guards[0][0] == source.key


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @source lagniappe/core/tools/ai/reporting/entity_updates.py::prepare_entity_updates
# @matrix entity-patch : integration review dependencies stale-state
# @matrix ai-report : execute idempotency skip-action validation
@pytest.mark.parametrize("skip_form", [False, True])
def test_form_creation_and_task_update_batch_preserves_dependencies_and_retry(monkeypatch, skip_form):
    from lagniappe.core.tools.ai.reporting.entity_updates import prepare_entity_updates
    from lagniappe.core.tools.ai.reporting.execution.runner import run_report
    from lagniappe.core.tools.database import utility as database_utility
    from lagniappe.core.entities.ai_report import REPORT_FORMAT_VERSION
    actor, task, old_form, page = case()
    report = entity("REPORT", "migration-report")
    report.format_version, report.user, report.parent = REPORT_FORMAT_VERSION, actor, actor
    report.status, report.pending, report.input_files = "ready", False, []
    store = {item.urlsafe_key: item for item in (task, old_form, page, report)}
    def fetch(reference, **kwargs):
        return reference if hasattr(reference, "entity_kind") else store.get(reference)
    monkeypatch.setattr(Entities, "fetch_one", fetch)
    writes = []
    def save(*items):
        writes.append(items)
        for item in items:
            store[item.urlsafe_key] = item
    monkeypatch.setattr(Entities, "save", save)
    from lagniappe.core.tools.database import get as database_get
    monkeypatch.setattr(database_get, "entity", lambda key, **kwargs: next((item.db for item in store.values() if item.key == key), None))
    keys = iter(range(100, 200))
    monkeypatch.setattr(database_utility, "create_key", lambda kind, parent=None: Key("activity", str(next(keys)), project="test-project"))
    report.proposal = {"summary": "Migrate", "confidence": 1, "actions": [
        {"id": "form", "type": "create_form", "data": {"name": "New", "form_type": "task", "schema": [{"id": "summary", "type": "input", "input": "text", "title": "Summary"}]}},
        {"id": "migrate", "type": "update_task", "depends_on": ["form"], "data": {"entity": task.urlsafe_key, "changes": {"form": "$form", "submission": {"summary": "Migrated"}, "description": "Short"}}},
    ]}
    prepare_entity_updates(report.proposal, actor)
    report.proposal["actions"][0]["skip"] = skip_form
    result = run_report(report, actor)
    assert result["status"] == "complete", [record.get("error") for record in result["actions"]]
    current = store[task.urlsafe_key]
    if skip_form:
        assert result["actions"][1]["status"] == "skipped"
        assert current.description == "Long original description"
    else:
        assert result["actions"][1]["status"] == "complete", result["actions"][1].get("error")
        assert current.submission == {"summary": "Migrated"}
        assert current.description == "Short"
        assert current.db["history"] is True
        assert current.due_date == task.due_date
        batches = [batch for batch in writes if any(item.entity_kind == "task" for item in batch)]
        assert len(batches) == 1
        assert any(item.entity_kind == "form" for item in batches[0])
        count = sum(any(item.entity_kind == "form" for item in batch) for batch in writes)
        assert run_report(report, actor)["status"] == "complete"
        assert sum(any(item.entity_kind == "form" for item in batch) for batch in writes) == count


# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report : validation unavailable
@pytest.mark.parametrize("version", [None, 1])
def test_obsolete_report_execution_stops_before_workspace_writes(monkeypatch, version):
    from lagniappe.core.tools.ai.reporting.execution.runner import run_report
    actor = _test_user("obsolete-owner")
    report = entity("REPORT", "obsolete")
    report.format_version = version
    report.proposal = {"summary": "Old", "actions": [{"type": "create_page", "data": {"name": "Must not create"}}]}
    def unexpected(*args, **kwargs):
        pytest.fail("Obsolete report reached a write")
    monkeypatch.setattr(Entities, "save", unexpected)
    with pytest.raises(ValidationError, match="no longer available"):
        run_report(report, actor)


# @source lagniappe/core/tools/ai/reporting/entity_updates.py::prepare_entity_updates
# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix entity-patch : integration review dependencies stale-state
# @matrix ai-report : execute idempotency preservation
@pytest.mark.parametrize("new_models", [False, True])
def test_promotion_eight_task_migration_preserves_identity_and_orders_models(monkeypatch, new_models):
    from lagniappe.core.tools.ai.reporting.entity_updates import prepare_entity_updates
    from lagniappe.core.tools.ai.reporting.execution.runner import run_report
    from lagniappe.core.tools.database import get as database_get
    from lagniappe.core.entities.ai_report import REPORT_FORMAT_VERSION
    from lagniappe.core.properties import common_entity
    monkeypatch.setattr(common_entity.cache, "check_hash", lambda *_args, **_kwargs: False)
    actor, first_task, old_form, page = case()
    project = entity("PROJECT", "promotion")
    labels = ["Readiness", "Discovery", "Outreach", "Results"]
    models = [entity("MODEL_TASK", label.lower()) for label in labels]
    for i, model in enumerate(models):
        model.project, model.order = project, 4 - i
    project.properties.model_tasks._value = [] if new_models else list(reversed(models))
    tasks = [first_task]
    for i in range(1, 8):
        task = entity("TASK", f"promotion-task-{i}")
        task.page, task.form, task.description = page, old_form, "Long source detail"
        task.submission = {"answer": f"Evidence {i}", "kept": "Notes"}
        task.due_date = first_task.due_date
        task.db["history"] = True
        tasks.append(task)
    for task in tasks:
        task.db["assets"] = '{"attachment": {"path": "keep-original"}}'
    baseline = {task.urlsafe_key: deepcopy(dict(task.db)) for task in tasks}
    report = entity("REPORT", "promotion-report")
    report.format_version, report.user, report.parent = REPORT_FORMAT_VERSION, actor, actor
    report.status, report.pending, report.input_files = "ready", False, []
    store = {item.urlsafe_key: item for item in [*tasks, old_form, page, project, report, *([] if new_models else models)]}
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: reference if hasattr(reference, "entity_kind") else store.get(reference))
    monkeypatch.setattr(database_get, "entity", lambda key, **kwargs: next((item.db for item in store.values() if item.key == key), None))
    keys = iter(range(300, 400))
    monkeypatch.setattr(database_utility, "create_key", lambda kind, parent=None: Key("activity", str(next(keys)), project="test-project"))
    saved_commit = None
    def save(*items):
        nonlocal saved_commit
        # Enforce the database preconditions before accepting any batch writes.
        for item in items:
            for key, expected in getattr(item, "_form_additional_guards", []):
                current = next((saved.db for saved in store.values() if saved.key == key), None)
                actual = {"execution_commit": saved_commit} if key == report.key else current
                if actual is None or any(actual.get(name) != value for name, value in expected.items()):
                    raise MutationConflict("Saved state changed while saving; reload and retry.")
        for item in items:
            item._form_additional_guards = []
            store[item.urlsafe_key] = item
            item.db.setdefault("hash", "saved-" + item.key.name)
        saved_commit = report.db.get("execution_commit")
        # Model lists are datastore relationships in production; refresh the fake cache.
        current_project = store[project.urlsafe_key]
        current_project.properties.model_tasks._value = sorted([item for item in store.values() if item.entity_kind == "model" and item.project.key == project.key], key=lambda item: item.order)
    monkeypatch.setattr(Entities, "save", save)
    actions = []
    model_refs = []
    for i, label in enumerate(labels):
        actions.append({"id": f"form{i}", "type": "create_form", "data": {"name": label + " Form", "form_type": "task", "schema": [{"id": "notes", "type": "textarea", "title": "Notes"}, {"id": "steps", "type": "todo", "title": "Pending steps"}]}})
        if new_models:
            actions.append({"id": f"model{i}", "type": "create_model_task", "data": {"name": label, "project": project.urlsafe_key, "form_action": f"form{i}"}})
            model_refs.append(f"$model{i}")
        else:
            actions.append({"id": f"model{i}", "type": "update_model_task", "data": {"entity": models[i].urlsafe_key, "changes": {"name": label, "form": f"$form{i}"}}})
            model_refs.append(models[i].urlsafe_key)
    actions.append({"id": "order", "type": "update_project", "data": {"entity": project.urlsafe_key, "changes": {"name": "Promotion workflow", "description": "Reusable promotion process", "model_tasks": model_refs}}})
    for index, (task, stage) in enumerate(zip(tasks, [0, 1, 1, 2, 2, 2, 3, 3])):
        actions.append({"id": f"task{index}", "type": "update_task", "data": {"entity": task.urlsafe_key, "changes": {"model": model_refs[stage], "form": f"$form{stage}", "submission": {"notes": task.description, "steps": {"items": [{"text": "Follow up", "checked": False}]}}, "description": labels[stage]}}})
    report.proposal = {"summary": "Generalize Promotion", "confidence": 1, "actions": actions}
    prepare_entity_updates(report.proposal, actor)
    result = run_report(report, actor)
    assert report.status == "complete", report.error
    assert all(record["status"] == "complete" for record in result["actions"]), [(record["id"], record.get("error")) for record in result["actions"] if record["status"] != "complete"]
    assert store[project.urlsafe_key].name == "Promotion workflow"
    assert [model.name for model in store[project.urlsafe_key].model_tasks] == labels
    assert sum(item.entity_kind == "form" for item in store.values()) == 5
    for task in tasks:
        current = store[task.urlsafe_key]
        assert current.key == task.key
        assert current.due_date == task.due_date
        assert current.db["history"] is True
        assert current.db["assets"] == baseline[task.urlsafe_key]["assets"]
        assert current.submission["steps"]["items"][0]["checked"] is False
        assert current.description in labels
        assert current.form.key == current.model.form.key


# @source lagniappe/core/tools/ai/reporting/execution/actions/entities.py::_move_task
# @pair ai-report:moves
def test_completed_task_movement_remains_a_distinct_supported_operation(monkeypatch):
    from lagniappe.core.tools.ai.reporting.execution.actions.entities import _move_task
    actor, task, form, page = case()
    task.completed = True
    target = entity("PAGE", "destination")
    store = {item.urlsafe_key: item for item in [task, page, target]}
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: reference if hasattr(reference, "entity_kind") else store.get(reference))
    result, writes, receipt = _move_task({"data": {"task": task.urlsafe_key, "to_page": target.urlsafe_key}}, None, actor, {})
    assert result.key == task.key
    assert result.page.key == target.key
    assert result.completed is True
    assert receipt["previous"]["page"]["id"] == page.urlsafe_key


# @source lagniappe/core/tools/ai/function_definitions/get_entity.py::execute_get_entity
# @matrix ai : edit-view exact-answers shared-schema
# @matrix entity-patch : preservation validation preparation permissions
def test_edit_view_preserves_complete_descriptions_and_deduplicates_schema(monkeypatch):
    from lagniappe.core.tools.ai.function_definitions.get_entity import execute_get_entity, edit_entity
    actor, task, form, page = case()
    import importlib
    for module in ("form", "page", "task"):
        monkeypatch.setattr(importlib.import_module("lagniappe.core.entities." + module), "url_for", lambda endpoint, **kwargs: "/entity/" + kwargs["key"])
    task.description = "Complete detailed description. " * 200
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: reference if hasattr(reference, "entity_kind") else task)
    result = execute_get_entity({"id": task.urlsafe_key, "view": "edit"}, actor)
    assert result["description"] == task.description
    assert result["answers"] == {"answer": "old answer", "kept": "preserve me"}
    assert "form" in result["editable_fields"]
    schemas = {}
    for _ in range(2):
        row = edit_entity(task, actor, schemas)
        assert "schema" not in row["form"]
        assert "Form" not in row
    assert list(schemas.values()) == [form.schema]
    task.completed = True
    assert edit_entity(task, actor)["editable_fields"] == []


# @source lagniappe/core/tools/ai/reporting/corrections.py::link_correction
# @source lagniappe/core/tools/ai/reporting/corrections.py::approve_correction
# @source lagniappe/core/tools/ai/report_history.py::delete_report_record
# @matrix ai-report : correction ownership supersession delete file-cleanup guarded-delete
@pytest.mark.parametrize("source_origin,correction_origin", [("api", "web"), ("web", "api")])
def test_corrections_share_evidence_across_origins_and_fence_source_retries(monkeypatch, source_origin, correction_origin):
    from lagniappe.core.tools.ai.reporting.corrections import link_correction, save_correction, approve_correction
    from lagniappe.core.tools.ai.report_history import _other_report_references
    from lagniappe.core.entities.ai_report import REPORT_FORMAT_VERSION
    actor = _test_user("owner")
    source, correction = entity("REPORT", "evidence-source"), entity("REPORT", "evidence-correction")
    file = entity("FILE", "evidence")
    for report in [source, correction]:
        report.format_version, report.user, report.parent = REPORT_FORMAT_VERSION, actor, actor
        report.pending, report.status = False, "complete"
    source.input_files, source.origin, correction.origin = [file], source_origin, correction_origin
    source.proposal = {"summary": "Source execution", "actions": []}
    source.result = {"status": "failed", "actions": [{"status": "complete", "type": "create_task"}]}
    saved = []
    monkeypatch.setattr(Entities, "save", lambda *items: saved.append(items))
    store = {item.urlsafe_key: item for item in [source, correction]}
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: store.get(reference))
    with pytest.raises(ValidationError, match="you created"):
        link_correction(correction, source, _test_user("another-user"))
    link_correction(correction, source, actor)
    save_correction(correction, source)
    assert not source.db.get("superseded_by")
    assert correction.urlsafe_key in source.db["correction_children"]
    assert set(file.db["report_refs"]) == set(store)
    assert {key for key, _ in correction._form_additional_guards} == {source.key, file.key}
    assert _other_report_references(file, source)
    approve_correction(correction, actor)
    assert source.db["superseded_by"] == correction.urlsafe_key
    approve_correction(correction, actor)  # Approval delivery is idempotent.
    assert len(saved) == 2
    store.pop(source.urlsafe_key)
    assert not _other_report_references(file, correction)


# @source lagniappe/core/tools/ai/reporting/execution/actions/recovery.py::_inspect_action_applied
# @matrix ai-report : completed-prefix completed-task permissions recovery
def test_update_recovery_accepts_later_completion_but_rejects_unrelated_drift(monkeypatch):
    from lagniappe.core.tools.ai.reporting.execution.actions.recovery import _inspect_action_applied, ACTION_APPLIED, ACTION_DRIFTED
    from lagniappe.core.tools.ai.reporting.execution.actions.completed_tasks import _task_state_fingerprint
    from lagniappe.core.tools.ai.reporting.execution.actions.task_completion import _completion_state
    from lagniappe.core.tools.entity_patches import _projection
    actor, task, form, page = case()
    before = _projection(task)
    task.due_date = datetime(2026, 11, 1, tzinfo=timezone.utc)
    task.completed = True
    records = [
        {"id": "edit", "type": "update_task", "status": "complete", "entity": {"id": task.urlsafe_key}, "expected": {"entity": task.urlsafe_key, "entity_update_after": before}},
        {"id": "done", "type": "complete_task", "status": "complete", "entity": {"id": task.urlsafe_key}, "expected": {"entity": task.urlsafe_key, "completion_state": _completion_state(task), "task_state_fingerprint": _task_state_fingerprint(task)}},
    ]
    report = SimpleNamespace(result={"actions": records})
    monkeypatch.setattr(Entities, "fetch_one", lambda reference, **kwargs: task)
    assert _inspect_action_applied({"type": "update_task"}, report, actor, records[0]) == ACTION_APPLIED
    task.description = "Unrelated later edit"
    assert _inspect_action_applied({"type": "update_task"}, report, actor, records[0]) == ACTION_DRIFTED


# @source lagniappe/core/tools/ai/reporting/corrections.py::link_correction
# @pair ai-report:correction
def test_correction_snapshot_excludes_nested_long_values_from_datastore_indexes():
    from google.cloud.datastore.helpers import entity_to_protobuf, entity_from_protobuf
    from lagniappe.core.tools.ai.reporting.corrections import link_correction
    from lagniappe.core.entities.ai_report import REPORT_FORMAT_VERSION
    actor = _test_user("snapshot-owner")
    source, correction = entity("REPORT", "snapshot-source"), entity("REPORT", "snapshot-correction")
    source.format_version, source.user, source.parent = REPORT_FORMAT_VERSION, actor, actor
    source.status, source.pending = "complete", False
    long_text = "Long answer and migrated task detail. " * 100
    source.proposal = {"summary": "Source", "answer_html": long_text, "actions": [
        {"type": "update_task", "data": {"changes": {"description": long_text}}}
    ]}
    source.result = {"status": "complete", "actions": [{"status": "skipped", "note": long_text}]}
    source.input_files = []
    link_correction(correction, source, actor)
    correction.db.exclude_from_indexes = correction.exclude_from_index
    encoded = entity_to_protobuf(correction.db)
    snapshot = encoded.properties["correction"]
    assert snapshot.exclude_from_indexes
    proposal = snapshot.entity_value.properties["proposal"].entity_value
    answer = proposal.properties["answer_html"]
    assert len(answer.string_value.encode()) > 1500
    assert answer.exclude_from_indexes
    action = proposal.properties["actions"].array_value.values[0].entity_value
    description = action.properties["data"].entity_value.properties["changes"].entity_value.properties["description"]
    assert description.exclude_from_indexes
    result = snapshot.entity_value.properties["result"].entity_value
    note = result.properties["actions"].array_value.values[0].entity_value.properties["note"]
    assert note.exclude_from_indexes
    restored = entity_from_protobuf(encoded)
    assert restored["correction"]["proposal"] == source.proposal
    assert restored["correction"]["result"] == source.result
