"""``Task.complete`` / ``Task.uncomplete`` and interaction with schedule queue."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from lagniappe.core.definitions.asset import AssetVisibility
from lagniappe.core.definitions import MutationEffectType, MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.entities.history import DocumentHistory, TaskHistory
from lagniappe.core.entities.task import Task
from lagniappe.core.exceptions import TaskCompletionError, ValidationError
from lagniappe.core.mutations import plan_mutation
from lagniappe.core.tools.tasks import scheduling as dates
from lagniappe.core.tools.tasks.combine import select_main_task
from testing.utility.test_entities import TestEntities

# DateMixin resolves timezone via ``mixins.date.dates`` (not only ``tools.dates``).
_USER_TZ = "lagniappe.core.mixins.date.dates.user_timezone"


# @matrix task-completion : assignee complete completed-by no-schedule
@pytest.mark.unit
def test_task_complete_without_schedule(get_test_entities):
    """No schedule: completion status/date, assignee retained, due date cleared."""
    task = get_test_entities()[0]
    completer = TestEntities.get(
        "USER",
        {
            "name": "Completer",
            "hash": "cmp001",
            "page": {"name": "Completer Page", "hash": "cpg001"},
        },
    )

    task.due_date = datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert task.properties.assigned_to.exists

    with patch(_USER_TZ, return_value=ZoneInfo("UTC")):
        with patch("lagniappe.core.entities.task.current_user", completer):
            task.complete()

    assert task.completed is True
    assert task.completed_on is not None
    assert task.properties.completed_by.value is completer.page
    assert task.properties.assigned_to.exists
    assert task.assigned_to.name == "Assignee Page"
    assert task.active is True
    assert task.due_date is None


# @matrix submission task-completion : required-fields validation
@pytest.mark.unit
def test_task_complete_raises_when_required_submission_missing(get_test_entities):
    """``TaskCompletionError`` when form exists and required fields are incomplete."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "Form task",
            "hash": "tclf01",
            "page": {"name": "Parent Page", "hash": "pgf01"},
            "form": {"name": "F", "hash": "frm01", "schema": "text_input_only"},
        },
    )
    completer = TestEntities.get(
        "USER",
        {
            "name": "Completer",
            "hash": "cmp002",
            "page": {"name": "Completer Page", "hash": "cpg002"},
        },
    )
    missing = MagicMock()
    missing.label = "Required Field"

    with patch(_USER_TZ, return_value=ZoneInfo("UTC")):
        with patch.object(Task, "_check_required", return_value=[missing]):
            with patch("lagniappe.core.entities.task.current_user", completer):
                with pytest.raises(TaskCompletionError, match="Required Field"):
                    task.complete()


# @matrix signature task-completion : asset-cleanup history uncomplete
@pytest.mark.unit
def test_task_uncomplete_after_complete(get_test_entities):
    """``uncomplete`` clears completion state and reactivates; history entry is created when was completed."""
    task = get_test_entities()[0]
    file_entity = TestEntities.get("FILE", {"name": "Attachment", "hash": "filc01"})
    completer = TestEntities.get(
        "USER",
        {
            "name": "Completer",
            "hash": "cmp003",
            "page": {"name": "Completer Page", "hash": "cpg003"},
        },
    )
    task.files = [file_entity]
    task.test_spec["assets"] = {
        "task-signature-field": {"type": "image", "path": "signature.png"}
    }

    with patch(_USER_TZ, return_value=ZoneInfo("UTC")):
        with patch("lagniappe.core.entities.task.current_user", completer):
            task.complete()

    assert task.completed is True
    assert task.completed_on is not None
    assert not task.db.get("history")

    history = MagicMock()
    history.files = []
    with (
        patch(
            "lagniappe.core.entities.task.Entities.TASK_HISTORY.create",
            return_value=history,
        ),
        patch.object(task, "delete_asset") as delete_asset,
    ):
        task.uncomplete()

    assert task.completed is False
    assert task.completed_on is None
    assert task.properties.completed_by.value is None
    assert task.active is True
    assert task.db.get("submission") is None
    assert task.submission == {}
    assert task.files == []
    assert task.db.get("files", []) == []
    assert file_entity.tasks == []
    assert file_entity.db.get("tasks", []) == []
    delete_asset.assert_called_once_with("task-signature-field")
    assert task.db.get("history") is True


# @matrix task-completion : assignment repeating-default uncomplete
@pytest.mark.unit
def test_task_uncomplete_restores_default_submission_and_assignment(get_schema):
    assignee = TestEntities.get(
        "PAGE", {"name": "Persistent assignee", "hash": "persistent_assignee"}
    )
    assigner = TestEntities.get(
        "PAGE", {"name": "Persistent assigner", "hash": "persistent_assigner"}
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Repeating submission task",
            "hash": "repeating_submission_task",
            "page": {"name": "Parent", "hash": "repeating_submission_parent"},
            "form": {"name": "Inputs", "hash": "repeating_submission_form"},
        },
    )
    task.form.schema = get_schema("basic_inputs")
    task.properties.assigned_to._value = assignee
    task.db["assigned_to"] = assignee.key
    task.properties.assigned_by._value = assigner
    task.db["assigned_by"] = assigner.key
    task.db["default_submission"] = json.dumps({"input-textab12": "Repeat this value"})
    task.properties.submission.value = {
        "input-textab12": "Completed value",
        "input-numgh78": 12,
    }
    assert task.properties.submission.form_value["input-textab12"] == "Completed value"

    task.uncomplete()

    assert task.submission == {"input-textab12": "Repeat this value"}
    assert task.properties.submission.form_value == {
        "input-textab12": "Repeat this value"
    }
    assert task.assigned_to is assignee
    assert task.assigned_by is assigner
    assert task.db["assigned_to"] == assignee.key
    assert task.db["assigned_by"] == assigner.key


# @matrix task-completion : description history legacy name
@pytest.mark.unit
def test_legacy_task_history_snapshot_text_defaults_to_none():
    """Legacy history rows without snapshot text remain readable."""
    history = TaskHistory(testing=True)

    assert history.name is None
    assert history.description is None


# @pair task-completion:immutable-fingerprint
@pytest.mark.unit
def test_task_history_fingerprint_ignores_later_form_versions():
    """An immutable history row keeps its creation-based entity fingerprint."""
    form = TestEntities.get(
        "FORM",
        {"name": "History fingerprint form", "hash": "historyfingerprintform"},
    )
    form.version = 1
    history = TaskHistory(testing=True)
    history.created = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    history.form = form

    original = history.fingerprint
    form.version = 2

    assert history.modified == history.created
    assert history.fingerprint == original


# @matrix tasks : attached-page history parent-details
@pytest.mark.unit
def test_task_history_attached_page_details_key_uses_parent():
    """Task history page details use the same parent payload key as live tasks."""
    page = TestEntities.get("PAGE", {"name": "History Parent", "hash": "thp001"})
    history = TaskHistory(testing=True)
    history._key = "histpg"
    history.page = page

    assert history.properties.page.details_key == "parent"
    assert history.details["parent"] == page.reference_details
    assert "page" not in history.details
    assert history.properties.page.column_value == page.reference_details


# @matrix task-completion : asset-copy description history linked-pages name schema-version snapshot submission
# @pair signature:asset-copy
@pytest.mark.unit
def test_task_history_create_snapshots_completed_task_state():
    """``TaskHistory.create`` snapshots the task state being archived."""
    parent = TestEntities.get("PAGE", {"name": "Parent Page", "hash": "pgth01"})
    linked_page = TestEntities.get("PAGE", {"name": "Linked Page", "hash": "pgth02"})
    file_entity = TestEntities.get(
        "FILE",
        {"name": "Attachment", "hash": "filth1"},
    )
    completed_by = TestEntities.get(
        "USER",
        {
            "name": "Completer",
            "hash": "usrth1",
            "page": {"name": "Completer Page", "hash": "pgusr1"},
        },
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Completed form task",
            "hash": "tskth1",
            "page": {"name": "Parent Page", "hash": "pgth01"},
            "form": {"name": "Task Form", "hash": "frmth1"},
        },
        page=parent,
    )
    completed_on = datetime(2025, 8, 5, 14, 30, tzinfo=timezone.utc)
    submission = {"notes": "done", "score": 5}
    signature_asset = SimpleNamespace(
        type="image",
        content_type="image/png",
        visibility=AssetVisibility.private,
        get=lambda: b"signature-bytes",
    )

    task.form.version = "schema-v1"
    task.completed = True
    task.completed_on = completed_on
    task.completed_by = completed_by
    task.submission = submission
    task.page = parent
    task.description = "Finished carefully"
    task.properties.linked_pages._value = [linked_page]
    task.db["linked_pages"] = [linked_page.key]
    task.files = [file_entity]
    task.test_spec["assets"] = {"task-signature-field": signature_asset}

    history_key = "histth1"
    with (
        patch(
            "lagniappe.core.entities.entity.database_utility.create_key",
            return_value=history_key,
        ),
        patch.object(TaskHistory, "copy_asset") as copy_asset,
    ):
        history = TaskHistory.create(task)

    assert history.kind == "task_history"
    assert history.properties.task.value is task
    assert history.completed_on == completed_on
    assert history.completed_by is completed_by.page
    assert history.required == task.required
    assert history.requires == task.required
    assert history.submission == submission
    assert history.page is parent
    assert history.name == "Completed form task"
    assert history.description == "Finished carefully"
    assert history.linked_pages == [linked_page]
    assert history.files == [file_entity]
    assert file_entity.tasks == [history, task]
    assert history.form is task.form
    assert history.version == "schema-v1"
    assert history.db["completed_by"] == completed_by.page.key
    assert history.db["page"] == parent.key
    assert history.db["name"] == "Completed form task"
    assert history.db["linked_pages"] == [linked_page.key]
    assert history.db["files"] == [file_entity.key]
    assert history.db["schema_version"] == "schema-v1"
    assert history.db["completed_on"] == completed_on
    assert "hash" not in history.db
    assert "completed" not in history.db

    copy_asset.assert_called_once_with(signature_asset)


# @matrix task-combine : completed-on deterministic-tie modified winner
@pytest.mark.unit
def test_task_combine_selects_completed_then_modified_main():
    page = TestEntities.get("PAGE", {"name": "Combine Page", "hash": "pgcmb1"})
    active = TestEntities.get("TASK", {"name": "Active", "hash": "tskcmb1"}, page=page)
    older = TestEntities.get(
        "TASK", {"name": "Older completion", "hash": "tskcmb2"}, page=page
    )
    newer = TestEntities.get(
        "TASK", {"name": "Newer completion", "hash": "tskcmb3"}, page=page
    )
    active.modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    older.modified = datetime(2025, 6, 1, tzinfo=timezone.utc)
    older.completed_on = datetime(2025, 5, 1, tzinfo=timezone.utc)
    newer.modified = datetime(2024, 6, 1, tzinfo=timezone.utc)
    newer.completed_on = datetime(2025, 7, 1, tzinfo=timezone.utc)

    assert select_main_task((active, older, newer)) is newer

    older.completed_on = None
    newer.completed_on = None
    assert select_main_task((active, older, newer)) is active

    active.modified = older.modified = newer.modified
    expected = max((active, older, newer), key=lambda task: task.urlsafe_key)
    assert select_main_task((active, older, newer)) is expected


# @matrix task-combine : asset-copy attachments existing-history metadata schema-version source-snapshot
# @pair signature:asset-copy
@pytest.mark.unit
def test_task_history_create_clones_another_task_and_existing_history():
    main_page = TestEntities.get("PAGE", {"name": "Main Page", "hash": "pgcmb2"})
    linked_page = TestEntities.get("PAGE", {"name": "Linked Page", "hash": "pgcmb3"})
    form = TestEntities.get("FORM", {"name": "Combine Form", "hash": "frmcmb1"})
    form.version = "source-schema-v2"
    file_entity = TestEntities.get(
        "FILE", {"name": "Source attachment", "hash": "filcmb1"}
    )
    main = TestEntities.get(
        "TASK", {"name": "Main task", "hash": "tskcmb4"}, page=main_page
    )
    source = TestEntities.get(
        "TASK", {"name": "Source task", "hash": "tskcmb5"}, page=main_page
    )
    completed_on = datetime(2025, 8, 1, tzinfo=timezone.utc)
    source.description = "Source description"
    source.form = form
    source.completed_on = completed_on
    source.submission = {"notes": "source submission"}
    source.properties.linked_pages._value = [linked_page]
    source.db["linked_pages"] = [linked_page.key]
    source.files = [file_entity]
    source.test_spec["assets"] = {
        "source-signature": SimpleNamespace(name="source-signature")
    }

    with (
        patch(
            "lagniappe.core.entities.entity.database_utility.create_key",
            side_effect=("source-history", "current-clone", "history-clone"),
        ),
        patch.object(TaskHistory, "copy_asset") as copy_asset,
    ):
        source_history = TaskHistory.create(source)
        source_history.created = datetime(2024, 8, 1, tzinfo=timezone.utc)
        source_history.version = "source-schema-v1"
        source_history._assets = {
            "source-signature": SimpleNamespace(name="source-signature")
        }
        source_history.get_asset = lambda name: source_history._assets[name]
        current_clone = TaskHistory.create(main, source=source)
        history_clone = TaskHistory.create(main, source=source_history)

    assert current_clone.task is main
    assert current_clone.page is main_page
    assert current_clone.name == "Source task"
    assert current_clone.description == "Source description"
    assert current_clone.completed_on == completed_on
    assert current_clone.created == completed_on
    assert current_clone.form is form
    assert current_clone.version == "source-schema-v2"
    assert current_clone.submission == {"notes": "source submission"}
    assert current_clone.files == [file_entity]
    assert current_clone.linked_pages == [linked_page]

    assert history_clone.task is main
    assert history_clone.created == source_history.created
    assert history_clone.version == "source-schema-v1"
    assert history_clone.submission == source_history.submission
    assert copy_asset.call_count == 3


# @matrix asset-storage : copy metadata visibility
@pytest.mark.unit
def test_asset_mixin_copy_asset_copies_storage_and_updates_definition(monkeypatch):
    page = TestEntities.get("PAGE", {"name": "Parent Page", "hash": "pgasset1"})
    target = TestEntities.get(
        "TASK",
        {"name": "Target task", "hash": "targetasset", "assets": {}},
        page=page,
    )
    source_asset = SimpleNamespace(
        name="task-signature-field",
        type="image",
        path="source-task_signature.png",
        visibility=AssetVisibility.private,
        content_type="image/png",
        extension="png",
        fingerprint="signature-md5",
        size=128,
    )
    calls = []

    def copy_file(
        source_path, source_visibility, destination_path, destination_visibility
    ):
        calls.append(
            (
                source_path,
                source_visibility,
                destination_path,
                destination_visibility,
            )
        )
        return SimpleNamespace(size=256)

    monkeypatch.setattr(
        "lagniappe.core.mixins.assets.database_assets.copy_file",
        copy_file,
    )

    copied = target.copy_asset(source_asset)

    assert copied.path == "targetasset_task-signature-field.png"
    assert calls == [
        (
            "source-task_signature.png",
            "private",
            "targetasset_task-signature-field.png",
            "private",
        )
    ]
    assert target.assets["task-signature-field"] == {
        "type": "image",
        "path": "targetasset_task-signature-field.png",
        "fingerprint": "signature-md5",
        "size": 256,
        "large": False,
    }
    assert json.loads(target.db["assets"]) == target.assets


# @pair document-history:asset-copy
@pytest.mark.unit
def test_document_history_create_copies_document_asset():
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Document Page",
            "hash": "pgdoch1",
            "assets": {
                "document": {"type": "html", "path": "page-document.html"},
            },
        },
    )
    document_asset = page.get_asset("document")

    with (
        patch(
            "lagniappe.core.entities.entity.database_utility.create_key",
            return_value="dochist1",
        ),
        patch.object(DocumentHistory, "copy_asset") as copy_asset,
    ):
        history = DocumentHistory.create(page)

    assert history.kind == "document_history"
    assert history.hash == (history.urlsafe_key or str(history.key))
    assert history.name is None
    assert history.pinned is False
    copied_asset, copied_name = copy_asset.call_args.args
    assert copied_asset.path == document_asset.path
    assert copied_asset.type == document_asset.type
    assert copied_name == DocumentHistory.DOCUMENT_ASSET


# @matrix document-history : asset-path batch-delete current-content legacy named ordering validation
@pytest.mark.unit
def test_document_history_named_versions_order_and_delete_in_bounded_batches():
    page = TestEntities.get("PAGE", {"name": "Document Page", "hash": "pgdoch2"})

    with (
        patch(
            "lagniappe.core.entities.entity.database_utility.create_key",
            side_effect=["dochist2", "dochist3"],
        ),
        patch.object(DocumentHistory, "save_asset") as save_asset,
    ):
        first = DocumentHistory.create(
            page,
            name="  <b>Launch</b> checkpoint  ",
            html="<p>First unsaved draft</p>",
        )
        second = DocumentHistory.create(
            page,
            name="Launch checkpoint",
            html="<p>Second unsaved draft</p>",
        )

    assert first.name == "Launch checkpoint"
    assert second.name == "Launch checkpoint"
    assert first.pinned is True
    assert second.pinned is True
    assert first.hash == (first.urlsafe_key or str(first.key))
    assert second.hash == (second.urlsafe_key or str(second.key))
    assert first.hash != second.hash
    assert save_asset.call_args_list[0].args == (
        "<p>First unsaved draft</p>",
        DocumentHistory.DOCUMENT_ASSET,
        "html",
    )

    legacy = DocumentHistory(testing=True)
    legacy.created = datetime(2025, 1, 3, tzinfo=timezone.utc)
    automatic = DocumentHistory(testing=True)
    automatic.created = datetime(2025, 1, 4, tzinfo=timezone.utc)
    first.created = datetime(2025, 1, 1, tzinfo=timezone.utc)
    second.created = datetime(2025, 1, 2, tzinfo=timezone.utc)

    assert legacy.name is None
    assert legacy.pinned is False
    assert DocumentHistory.ordered([legacy, first, automatic, second]) == [
        second,
        first,
        automatic,
        legacy,
    ]

    deleted_batches = []
    cleared = DocumentHistory.delete_unpinned(
        [legacy, first, automatic, second],
        batch_size=1,
        delete=lambda *batch: deleted_batches.append(list(batch)),
    )
    assert cleared == 2
    assert deleted_batches == [[legacy], [automatic]]


# @pair document-history:validation
@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "html"),
    [
        (" ", "<p>Content</p>"),
        ("x" * 101, "<p>Content</p>"),
        ("Checkpoint", ""),
        ("Checkpoint", "<p><br></p>"),
    ],
)
def test_document_history_named_version_rejects_invalid_name_or_content(name, html):
    page = TestEntities.get("PAGE", {"name": "Document Page", "hash": "pgdoch3"})

    with pytest.raises(ValidationError) as error:
        DocumentHistory.create(page, name=name, html=html)

    assert str(error.value)


# @matrix task-completion : attachments description explicit-overrides history live-task name submission
@pytest.mark.unit
def test_task_create_history_entry_accepts_completion_overrides(
    get_schema,
):
    """Explicit completed-event data creates history without mutating live task data."""
    page = TestEntities.get("PAGE", {"name": "Parent Page", "hash": "pgth03"})
    form = TestEntities.get("FORM", {"name": "Task Form", "hash": "frmth3"})
    form.schema = get_schema("text_input_only")
    live_file = TestEntities.get("FILE", {"name": "Live File", "hash": "filth3a"})
    event_file = TestEntities.get("FILE", {"name": "Event File", "hash": "filth3b"})
    task = TestEntities.get(
        "TASK",
        {"name": "Inspection", "hash": "tskth3"},
        page=page,
    )
    task.form = form
    task.description = "Current completion"
    task.completed = True
    task.completed_on = datetime(2025, 8, 5, 14, 30, tzinfo=timezone.utc)
    task.files = [live_file]

    with patch(
        "lagniappe.core.entities.entity.database_utility.create_key",
        return_value="histth3",
    ):
        history = task.create_history_entry(
            completed_on=datetime(2023, 6, 24, tzinfo=timezone.utc),
            files=[event_file],
            submission={"input-textab12": "Older event"},
            name="Older inspection visit",
            description="Older inspection",
            form=form,
        )

    assert history.task is task
    assert history.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert history.name == "Older inspection visit"
    assert history.description == "Older inspection"
    assert history.files == [event_file]
    assert history.form is form
    assert history.submission == {"input-textab12": "Older event"}
    assert task.completed_on == datetime(2025, 8, 5, 14, 30, tzinfo=timezone.utc)
    assert task.name == "Inspection"
    assert task.description == "Current completion"
    assert task.files == [live_file]
    plan = plan_mutation(MutationOperation.SAVE, task, registry=Entities)
    writes = {
        effect.entity.key: effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.UPSERT
    }
    assert writes[task.key].property_mask is None
    assert writes[history.key].property_mask is None
    assert set(writes[event_file.key].property_mask) == {
        "tasks",
        "requires",
        "modified",
    }


# @matrix task-completion : complete next-due-date schedule-queue
# @matrix task-scheduling : complete durable-uncomplete next-due-date post-commit schedule-queue timezone
@pytest.mark.unit
def test_task_complete_with_schedule_queues_uncomplete():
    """With an active schedule, ``complete`` advances due date then queues uncomplete (patched)."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "Recurring task",
            "hash": "tcl003",
            "page": {"name": "Parent Page", "hash": "pgtcl3"},
        },
    )
    completer = TestEntities.get(
        "USER",
        {
            "name": "Completer",
            "hash": "cmp004",
            "page": {"name": "Completer Page", "hash": "cpg004"},
        },
    )

    task.db["schedule"] = json.dumps(
        {"recurring": {"interval": 1, "unit": "day", "complete": True}}
    )
    task.processes.pop("schedule", None)
    task.properties.schedule.unset()

    task.due_date = datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc)

    mock_today = datetime(2025, 6, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today",
        return_value=mock_today,
    ):
        with patch(_USER_TZ, return_value=ZoneInfo("UTC")):
            with patch(
                "lagniappe.core.entities.task.scheduling.add_uncomplete_task_to_queue"
            ) as queue_mock:
                with patch("lagniappe.core.entities.task.current_user", completer):
                    task.complete()

    queue_mock.assert_called_once_with(task)
    assert task.completed is True
    assert task.completed_on is not None
    assert task.due_date is not None


# @matrix task-completion task-scheduling : complete schedule-queue
@pytest.mark.unit
def test_task_complete_with_near_term_schedule_uncompletes_immediately():
    """A near-term recurring completion reactivates immediately with its calculated next due date."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "Near-term recurring task",
            "hash": "tcl004",
            "page": {"name": "Parent Page", "hash": "pgtcl4"},
        },
    )
    completer = TestEntities.get(
        "USER",
        {
            "name": "Completer",
            "hash": "cmp005",
            "page": {"name": "Completer Page", "hash": "cpg005"},
        },
    )

    task.db["schedule"] = json.dumps(
        {"recurring": {"interval": 1, "unit": "day", "complete": True}}
    )
    task.processes.pop("schedule", None)
    task.properties.schedule.unset()

    mock_today = datetime(2025, 6, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    task.due_date = mock_today - timedelta(days=1)

    with (
        patch(
            "lagniappe.core.tools.tasks.scheduling.user_today",
            return_value=mock_today,
        ),
        patch(
            "lagniappe.core.properties.task_scheduling.dates.user_today",
            return_value=mock_today,
        ),
        patch(_USER_TZ, return_value=ZoneInfo("UTC")),
        patch("lagniappe.core.entities.task.current_user", completer),
        patch.object(task, "create_history_entry") as create_history_entry,
        patch(
            "lagniappe.core.tools.tasks.scheduling.task_queue.create_task"
        ) as create_task,
    ):
        task.complete()

    create_task.assert_not_called()
    create_history_entry.assert_called_once_with()
    assert task.completed is False
    assert task.completed_on is None
    assert task.properties.completed_by.value is None
    assert task.active is True
    assert task.due_date == mock_today + timedelta(days=1)
    assert task.db.get("postponed_from") is None


# @matrix cloud-tasks : durable-uncomplete idempotency post-commit
# @matrix task-scheduling : durable-uncomplete idempotency post-commit schedule-queue
# @pair task-completion:schedule-queue
@pytest.mark.unit
def test_add_uncomplete_task_to_queue_future_due_queues_in_production():
    """A future recurrence persists intent before its tokenized queue dispatch."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "Future recurring task",
            "hash": "tcl005",
            "page": {"name": "Parent Page", "hash": "pgtcl5"},
        },
    )
    next_due = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    task.completed = True
    task.completed_on = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    task.due_date = next_due

    with (
        patch(
            "lagniappe.core.tools.tasks.scheduling.CONFIG",
            SimpleNamespace(production=True),
        ),
        patch(
            "lagniappe.core.tools.tasks.scheduling.scheduled_uncomplete_time",
            return_value=datetime(2025, 6, 16, tzinfo=timezone.utc),
        ),
        patch(
            "lagniappe.core.tools.tasks.scheduling.due_in_home_task_window",
            return_value=False,
        ),
        patch(
            "lagniappe.core.tools.tasks.scheduling.url_for",
            return_value="https://example.test/process/uncomplete-task",
        ),
        patch(
            "lagniappe.core.tools.tasks.scheduling.task_queue.create_task",
            return_value="queued-task",
        ) as create_task,
    ):
        token = dates.add_uncomplete_task_to_queue(task)
        create_task.assert_not_called()
        task_name = dates.dispatch_scheduled_uncomplete(task)

    assert token == task.scheduled_uncomplete_token
    assert len(token) == 32
    assert task.scheduled_uncomplete_at == datetime(
        2025, 6, 16, tzinfo=timezone.utc
    )
    assert task_name == "queued-task"
    create_task.assert_called_once_with(
        endpoint="https://example.test/process/uncomplete-task",
        payload={
            "key": task.urlsafe_key,
            "token": token,
        },
        schedule_at=datetime(2025, 6, 16, tzinfo=timezone.utc),
        task_id=create_task.call_args.kwargs["task_id"],
    )
    assert create_task.call_args.kwargs["task_id"].startswith("task-uncomplete-")
    assert task.completed is True
    assert task.completed_on is not None
    assert task.active is True
    assert task.due_date == next_due


# @matrix task-completion task-scheduling : idempotency stale-delivery
@pytest.mark.unit
def test_manual_uncomplete_clears_pending_scheduled_delivery():
    task = TestEntities.get(
        "TASK",
        {
            "name": "Pending recurring task",
            "hash": "tcl006",
            "page": {"name": "Parent Page", "hash": "pgtcl6"},
        },
    )
    task.completed = True
    task.due_date = datetime(2025, 7, 1, tzinfo=timezone.utc)
    task._defer_scheduled_uncomplete(datetime(2025, 6, 16, tzinfo=timezone.utc))

    with patch.object(task, "create_history_entry"):
        task.uncomplete()

    assert task.scheduled_uncomplete_token == ""
    assert task.scheduled_uncomplete_at is None
    assert not any(
        intent.intent.value == "scheduled-uncomplete-dispatch"
        for intent in task.mutation_intents
    )
