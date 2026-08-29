import json
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lagniappe.core.definitions import Action, Comparator, MutationIntentType
from lagniappe.core.exceptions import unloaded_relations as unloaded_relations_module
from lagniappe.core.exceptions import UnloadedRelationError, ValidationError
from lagniappe.core.entities.task import Task
from lagniappe.core.mixins import ColumnMixin

from testing.utility.test_entities import TestEntities, TestUser as UtilityTestUser


# @matrix task : ai-value cache column description filter-value html-stripping
@pytest.mark.unit
def test_task_description(get_test_entities):
    """Test Description property for Task entities.

    Description has:
    - Setter strips HTML tags via utility.strip_tags
    - filter_value is lowercase
    - sort_value is boolean (True if has description)
    - cache_key is "desc"
    - ai_key is "task_description" for TASK
    """
    for task in get_test_entities():
        raw_value = task.test_spec.get("description")

        if raw_value:
            task.description = raw_value

            # Value should have HTML stripped (if any)
            assert task.description == task.properties.description.value
            assert "<" not in (task.description or "")  # No HTML tags

            # FilterMixin
            assert task.to_filter_index()["description"] == task.description

            # sort_value is True when description exists
            assert task.properties.description.sort_value is True

            # CacheMixin - cache_key is "desc"
            assert task.to_cache["desc"] == task.description

            # AIMixin - ai_key is "task_description" for TASK
            assert task.to_ai()["task_description"] == task.description

            # ColumnMixin - column_value returns entity.description
            assert task.column("description").column_value == task.description

        else:
            # No description case
            assert task.description is None
            assert task.properties.description.filter_value is None
            assert task.properties.description.sort_value is False
            assert task.properties.description.cache_value is None


# @matrix task : ai-value column date due-date filter-value
@pytest.mark.unit
def test_task_due_date(get_test_entities):
    """Test DueDate property for Task entities.

    DueDate (DateMixin) has:
    - value stored in UTC
    - to_filter_index includes due_date as timestamp
    - to_ai includes Due Date as formatted string
    """
    from datetime import timezone
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    user_tz = ZoneInfo("America/Chicago")

    with patch("lagniappe.core.tools.dates.user_timezone", return_value=user_tz):
        for task in get_test_entities():
            raw_value = task.test_spec.get("due_date")

            if raw_value:
                task.due_date = raw_value

                # value should be stored in UTC
                assert task.due_date is not None
                assert task.due_date.tzinfo == timezone.utc

                # column_value should be in user timezone
                column_val = task.column("due_date").column_value
                assert column_val.tzinfo == user_tz

                # to_filter_index includes due_date as timestamp
                filter_index = task.to_filter_index()
                assert filter_index["due_date"] == task.due_date.timestamp()

                # to_ai includes Due Date as formatted string
                ai_data = task.to_ai()
                assert isinstance(ai_data["Due Date"], str)

            else:
                # No due date - not included in filter index or ai
                assert task.due_date is None
                assert "due_date" not in task.to_filter_index()
                assert task.to_ai().get("Due Date") is None


# @matrix task : column completed details filter-value
@pytest.mark.unit
def test_task_completed(get_test_entities):
    """Test Completed property for Task entities.

    Completed stores boolean task status; filter and column surfaces expose the
    same boolean value.
    """
    for task in get_test_entities():
        is_completed = task.test_spec.get("completed", False)

        if is_completed:
            task.completed = True

            assert task.properties.completed.value is True
            assert task.completed is True

            # to_filter_index includes completed as boolean
            filter_index = task.to_filter_index()
            assert filter_index["completed"] is True

            # column_value is boolean
            assert task.column("completed").column_value is True
            assert task.details["completed"] is True

        else:
            # Not completed
            assert task.properties.completed.value is False
            assert task.completed is False

            # to_filter_index includes completed as False
            filter_index = task.to_filter_index()
            assert filter_index["completed"] is False

            # column_value is False
            assert task.column("completed").column_value is False
            assert "completed" not in task.details


# @pair task:completed-on
@pytest.mark.unit
def test_task_completed_on_stores_timestamp():
    task = TestEntities.get(
        "TASK",
        {
            "name": "Completed On",
            "hash": "tcpon1",
            "page": {"name": "Parent Page", "hash": "pgcpon1"},
        },
    )
    completed_on = datetime(2025, 2, 3, 14, 30, tzinfo=timezone.utc)

    task.completed_on = completed_on

    assert task.completed_on == completed_on
    assert task.properties.completed_on.value == completed_on
    assert task.db["completed_on"] == completed_on


# @matrix filters signature task : filter-value schema-field
@pytest.mark.unit
def test_task_has_signature_filter_value(get_schema):
    """Task-level signature filter distinguishes signed, unsigned, and inapplicable tasks."""
    signature_schema = [
        {"id": "signature-signop", "type": "signature", "title": "Signature"}
    ]
    plain_schema = get_schema("basic_inputs")

    signed_form = TestEntities.get("FORM", {"name": "Signed Form", "hash": "frm013s"})
    signed_form.schema = signature_schema
    signed = TestEntities.get(
        "TASK",
        {
            "name": "Signed Task",
            "hash": "tsk013s",
            "page": {"name": "Signed Page", "hash": "pg013s"},
            "assets": {
                "signature-signop": {
                    "type": "image",
                    "path": "tsk013s_signature-signop.png",
                }
            },
        },
    )
    signed.properties.form._value = signed_form

    unsigned_form = TestEntities.get(
        "FORM", {"name": "Unsigned Form", "hash": "frm013u"}
    )
    unsigned_form.schema = signature_schema
    unsigned = TestEntities.get(
        "TASK",
        {
            "name": "Unsigned Task",
            "hash": "tsk013u",
            "page": {"name": "Unsigned Page", "hash": "pg013u"},
        },
    )
    unsigned.properties.form._value = unsigned_form

    plain_form = TestEntities.get("FORM", {"name": "Plain Form", "hash": "frm013p"})
    plain_form.schema = plain_schema
    plain = TestEntities.get(
        "TASK",
        {
            "name": "Plain Task",
            "hash": "tsk013p",
            "page": {"name": "Plain Page", "hash": "pg013p"},
        },
    )
    plain.properties.form._value = plain_form

    assert signed.has_signature is True
    assert signed.to_filter_index()["has_signature"] is True

    assert unsigned.has_signature is False
    assert unsigned.to_filter_index()["has_signature"] is False

    assert plain.has_signature is None
    assert "has_signature" not in plain.to_filter_index()


# @matrix filters status task : filter-value schema-field
@pytest.mark.unit
def test_task_has_status_filter_value(get_schema):
    """Task-level status filter distinguishes active, inactive, and inapplicable tasks."""
    status_schema = get_schema("status_only")
    plain_schema = get_schema("basic_inputs")

    active_form = TestEntities.get("FORM", {"name": "Status Form", "hash": "frm013a"})
    active_form.schema = status_schema
    active = TestEntities.get(
        "TASK",
        {
            "name": "Active Status Task",
            "hash": "tsk013a",
            "page": {"name": "Active Status Page", "hash": "pg013a"},
        },
    )
    active.properties.form._value = active_form
    active.db["submission"] = json.dumps({"checkbox-trigger": True})

    inactive_form = TestEntities.get(
        "FORM", {"name": "Inactive Status Form", "hash": "frm013i"}
    )
    inactive_form.schema = status_schema
    inactive = TestEntities.get(
        "TASK",
        {
            "name": "Inactive Status Task",
            "hash": "tsk013i",
            "page": {"name": "Inactive Status Page", "hash": "pg013i"},
        },
    )
    inactive.properties.form._value = inactive_form
    inactive.db["submission"] = json.dumps({"checkbox-trigger": False})

    plain_form = TestEntities.get("FORM", {"name": "Plain Form", "hash": "frm013p"})
    plain_form.schema = plain_schema
    plain = TestEntities.get(
        "TASK",
        {
            "name": "Plain Task",
            "hash": "tsk013p",
            "page": {"name": "Plain Page", "hash": "pg013p"},
        },
    )
    plain.properties.form._value = plain_form

    assert active.properties.submission.fields["status-ab12"].column_value == [
        "Completed"
    ]
    assert active.has_status is True
    assert active.to_filter_index()["has_status"] is True

    assert inactive.properties.submission.fields["status-ab12"].column_value == []
    assert inactive.has_status is False
    assert inactive.to_filter_index()["has_status"] is False

    assert plain.has_status is None
    assert "has_status" not in plain.to_filter_index()


# @matrix signature submission task : asset-lifecycle db-value
@pytest.mark.unit
def test_task_signature_form_submission_saves_asset_id(get_schema):
    """Submitting a signature file saves it as a task asset and stores the field id."""
    form = TestEntities.get("FORM", {"name": "Signature Form", "hash": "frm013sig"})
    form.schema = [
        {"id": "signature-signop", "type": "signature", "title": "Signature"}
    ]
    task = TestEntities.get(
        "TASK",
        {
            "name": "Signature Submit Task",
            "hash": "tsk013sig",
            "page": {"name": "Signature Page", "hash": "pg013sig"},
            "assets": {},
        },
    )
    task.properties.form._value = form

    upload = BytesIO(b"signature image")
    upload.content_type = "image/png"
    request = SimpleNamespace(
        form=SimpleNamespace(
            keys=lambda: ["signature-signop"],
            get=lambda key, default=None: "signature-signop",
            getlist=lambda key: ["signature-signop"],
        ),
        files={"signature-signop": upload},
    )

    with patch("lagniappe.core.definitions.asset.database_assets.save_file"):
        task.form_submission(request)

    assert json.loads(task.db["submission"]) == {"signature-signop": "signature-signop"}
    assert task.assets["signature-signop"]["type"] == "image"
    assert task.has_signature is True
    assert task.to_filter_index()["has_signature"] is True


# @matrix signature submission task : asset-lifecycle db-value multiple-fields schema-id
@pytest.mark.unit
def test_task_signature_form_submission_saves_multiple_assets_by_field_id():
    """Multiple signature uploads are matched by each field's schema id."""
    form = TestEntities.get(
        "FORM", {"name": "Multi Signature Form", "hash": "frm013ms"}
    )
    form.schema = [
        {"id": "signature-approver", "type": "signature", "title": "Approver"},
        {"id": "signature-witness", "type": "signature", "title": "Witness"},
    ]
    task = TestEntities.get(
        "TASK",
        {
            "name": "Multi Signature Submit Task",
            "hash": "tsk013ms",
            "page": {"name": "Multi Signature Page", "hash": "pg013ms"},
            "assets": {},
        },
    )
    task.properties.form._value = form

    approver_upload = BytesIO(b"approver signature")
    approver_upload.content_type = "image/png"
    witness_upload = BytesIO(b"witness signature")
    witness_upload.content_type = "image/png"
    fields = {
        "signature-approver": "signature-approver",
        "signature-witness": "signature-witness",
    }
    request = SimpleNamespace(
        form=SimpleNamespace(
            keys=lambda: fields.keys(),
            get=lambda key, default=None: fields.get(key, default),
            getlist=lambda key: [fields[key]] if key in fields else [],
        ),
        files={
            "signature-approver": approver_upload,
            "signature-witness": witness_upload,
        },
    )

    saved = {}

    def _capture_save_file(file, path, _content_type, _visibility):
        saved[path] = file.read()
        return True

    with patch(
        "lagniappe.core.definitions.asset.database_assets.save_file",
        side_effect=_capture_save_file,
    ):
        task.form_submission(request)

    assert json.loads(task.db["submission"]) == {
        "signature-approver": "signature-approver",
        "signature-witness": "signature-witness",
    }
    assert set(task.assets) == {"signature-approver", "signature-witness"}
    assert saved[task.assets["signature-approver"]["path"]] == b"approver signature"
    assert saved[task.assets["signature-witness"]["path"]] == b"witness signature"


# @matrix task : categories filter-value parent-derived
@pytest.mark.unit
def test_task_categories_follow_parent_page_categories():
    """Task categories are derived from the parent page, including filter details."""
    category_spec = {"name": "Safety", "hash": "cat013"}
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Parent Page",
            "hash": "pg013a",
            "categories": [category_spec],
        },
    )
    task = TestEntities.get(
        "TASK",
        {"name": "Categorized Task", "hash": "tsk013a"},
        page=page,
    )

    categories = task.properties.categories.value

    assert [category.hash for category in categories] == ["cat013"]
    assert task.properties.categories.filter_value == ["cat013"]
    assert task.properties.categories.sort_value == {"cat013": "Safety"}

    condition = SimpleNamespace(
        comparator=Comparator.CONTAINS,
        value="cat013",
        value_list=["cat013"],
        entity_map={"cat013": categories[0]},
    )
    details = task.properties.categories.filter_details(condition)

    assert details["kind"] == "category"
    assert details["label"] == "In Category"
    assert details["entity"] == categories[0].reference_details
    assert "text" not in details


# @matrix filter-index permissions task : column-view permission-neutral related-values
@pytest.mark.unit
def test_task_filter_index_includes_restricted_related_values():
    """Filter index export includes related values hidden from column display."""
    outsider = UtilityTestUser(owner=False, permissions={"models": "VIEW"})
    task = TestEntities.get(
        "TASK",
        {
            "name": "Restricted Assignee Task",
            "hash": "tsk013r",
            "page": {"name": "Parent", "hash": "pg013r"},
            "assigned_to": {
                "name": "Restricted Assignee",
                "hash": "usr013r",
                "page": {
                    "name": "Restricted Assignee Page",
                    "hash": "upg013r",
                    "restricted_to": ["secret_group"],
                },
            },
        },
    )

    task.properties.assigned_to.user = outsider

    assert not task.assigned_to.allowed(Action.VIEW, user=outsider)
    assert task.properties.assigned_to.column_value is None
    assert task.properties.assigned_to.filter_value == "upg013r"
    assert task.to_filter_index(user=outsider)["assigned_to"] == "upg013r"


# @matrix task : assigned-by assignee assignment
@pytest.mark.unit
def test_task_assignment_records_assigned_by_user_page():
    """Assigning to a user stores page keys and records the authenticated assigner."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "Assignable",
            "hash": "tsk013b",
            "page": {"name": "Parent", "hash": "pg013b"},
        },
    )
    assigner = TestEntities.get(
        "USER",
        {
            "name": "Assigner",
            "hash": "usr013b",
            "page": {"name": "Assigner Page", "hash": "pgusr13b"},
        },
    )
    assignee = TestEntities.get(
        "USER",
        {
            "name": "Assignee",
            "hash": "usr013c",
            "page": {"name": "Assignee Page", "hash": "pgusr13c"},
        },
    )

    with patch("lagniappe.core.properties.task_related.current_user", assigner):
        task.assigned_to = assignee

    assert task.assigned_to is assignee.page
    assert task.assigned_by is assigner.page
    assert task.db["assigned_to"] == assignee.page.key
    assert task.db["assigned_by"] == assigner.page.key

    task.assigned_to = None

    assert task.assigned_to is None
    assert task.assigned_by is None
    assert "assigned_to" not in task.db
    assert "assigned_by" not in task.db


# @matrix task : linked-pages related-files replacement unloaded-fallback
@pytest.mark.unit
def test_task_related_lists_replace_linked_pages_and_report_unloaded_files(
    monkeypatch,
):
    """Linked pages persist keys; task file keys report instead of lazy-loading."""
    captured = []
    monkeypatch.setattr(
        unloaded_relations_module,
        "CONFIG",
        SimpleNamespace(CAPTURE_UNLOADED_RELATIONS=True, STRICT_RELATION_LOADS=False),
    )
    monkeypatch.setattr(
        unloaded_relations_module,
        "capture",
        lambda error, context=None, level="error": captured.append(
            (error, context, level)
        ),
    )
    parent = TestEntities.get("PAGE", {"name": "Parent", "hash": "pg013d"})
    visible = TestEntities.get("PAGE", {"name": "Visible", "hash": "pg013e"})
    restricted = TestEntities.get("PAGE", {"name": "Restricted", "hash": "pg013f"})
    task = Task(testing=True)
    task.page = parent

    visible.allowed = MagicMock(return_value=True)
    restricted.allowed = MagicMock(return_value=False)
    task.properties.linked_pages._value = [restricted]

    task.linked_pages = [parent, visible]

    assert task.linked_pages == [visible]
    assert task.db["linked_pages"] == [visible.key]
    assert task.properties.linked_pages.column_value == [visible.reference_details]
    assert any(
        intent.entity is restricted and intent.intent is MutationIntentType.TOUCH
        for intent in task.mutation_intents
    )

    task.linked_pages = []

    assert task.page is parent
    assert task.linked_pages == []
    assert "linked_pages" not in task.db
    assert any(
        intent.entity is visible and intent.intent is MutationIntentType.TOUCH
        for intent in task.mutation_intents
    )

    task.db["files"] = ["fil013"]
    task.properties.files.unset()
    files = task.files

    assert files == []
    assert task.properties.files.sort_value is None
    assert len(captured) == 1
    error, context, level = captured[0]
    assert isinstance(error, UnloadedRelationError)
    assert level == "warning"
    assert context["relation_type"] == "list"
    assert context["entity"]["kind"] == "task"
    assert context["property"]["id"] == "files"
    assert context["keys"] == ["fil013"]


# @matrix task : attach details model page
@pytest.mark.unit
def test_task_model_and_page_details_attach_from_key_map():
    """Task model/page related properties expose filter and parent-detail contracts."""
    page = TestEntities.get("PAGE", {"name": "Parent", "hash": "pg013g"})
    model = TestEntities.get(
        "MODEL_TASK",
        {
            "name": "Review",
            "hash": "mdl013",
            "project": {"name": "Project", "hash": "prj013"},
        },
    )
    task = Task(testing=True)
    task.db["hash"] = "tsk013d"
    task._urlsafe_key = "tsk013d"
    task.db["page"] = page.key
    task.model = model

    task.properties.page.attach({page.key: page})

    assert task.properties.model.filter_key == "model"
    assert task.model is model
    assert task.page is page
    assert task.properties.page.details_key == "parent"
    assert task.properties.page.details_value == page.reference_details


# @matrix task : inheritance model-form
@pytest.mark.unit
def test_task_model_tracking_inherits_model_form(monkeypatch):
    """Tasks inherit loaded model forms without lazy-loading missing relations."""
    model_form = TestEntities.get(
        "FORM", {"name": "Invoice", "hash": "model-form-inherit"}
    )
    custom_form = TestEntities.get(
        "FORM", {"name": "Custom", "hash": "custom-form-inherit"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Remodeling", "hash": "project-form-inherit"}
    )
    loaded_model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Invoices", "hash": "loaded-model-form"},
        project=project,
    )
    loaded_model.form = model_form

    task = Task(testing=True)
    task.model = loaded_model

    assert task.form is model_form

    task_with_custom = Task(testing=True)
    task_with_custom.form = custom_form
    task_with_custom.model = loaded_model

    assert task_with_custom.form is custom_form

    lazy_model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Lazy Invoices", "hash": "lazy-model-form"},
        project=project,
    )
    lazy_model.db["form"] = model_form.key

    lazy_task = Task(testing=True)
    lazy_task.model = lazy_model

    assert lazy_task.form is None


# @matrix permissions task : allowed assignee-override
@pytest.mark.unit
def test_task_allowed_assigned_user_page_override():
    """Assigned users can view/edit tasks even when base permissions deny access."""
    assigned = TestEntities.get(
        "USER",
        {
            "name": "Assigned",
            "hash": "usr013d",
            "page": {"name": "Assigned Page", "hash": "pgusr13d"},
        },
    )
    other = TestEntities.get(
        "USER",
        {
            "name": "Other",
            "hash": "usr013e",
            "page": {"name": "Other Page", "hash": "pgusr13e"},
        },
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Permission Task",
            "hash": "tsk013c",
            "page": {"name": "Parent", "hash": "pg013h"},
        },
    )
    task.properties.assigned_to._value = assigned.page
    task.db["assigned_to"] = assigned.page.key

    with patch("lagniappe.core.entities.task.Entity.allowed", return_value=False):
        assert task.allowed(Action.VIEW, user=assigned)
        assert task.allowed(Action.EDIT, user=assigned)
        assert not task.allowed(Action.VIEW, user=other)


# @matrix permissions task : lazy-parent-check shallow-page stored-requires
@pytest.mark.unit
def test_task_allowed_skips_unloaded_page_when_stored_permission_suffices():
    task = TestEntities.get(
        "TASK",
        {"name": "Stored Permission Task", "hash": "tsk013stored"},
    )
    task.db["page"] = "unloaded-parent-page"
    task.properties.page.unset()

    with patch("lagniappe.core.entities.task.Entity.allowed", return_value=True):
        assert task.allowed(Action.VIEW)

    assert task.properties.page.is_set is False


# @matrix permissions task : allowed parent-page restricted-access
@pytest.mark.unit
def test_task_allowed_restricted_form_blocks_page_permission():
    """Task/form restrictions are a ceiling even when the parent page is visible."""
    outsider = TestEntities.get(
        "USER",
        {
            "name": "Outside Adopter",
            "hash": "usr013r",
            "page": {"name": "Outside Page", "hash": "pgusr13r"},
        },
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Staff Review",
            "hash": "tsk013r",
            "page": {"name": "Visible Pet", "hash": "pg013r"},
            "form": {
                "name": "Application Review",
                "hash": "frm013r",
                "restricted_to": ["grp013r"],
            },
        },
    )

    with (
        patch("lagniappe.core.entities.task.Entity.allowed", return_value=False),
        patch.object(task.page, "allowed", return_value=True),
    ):
        assert not task.allowed(Action.VIEW, user=outsider)
        assert not task.allowed(Action.EDIT, user=outsider)


# @matrix permissions task users : allowed models-scope user-page
@pytest.mark.unit
def test_task_allowed_models_view_requires_models_marker():
    """Models VIEW only grants task access when the task requirements include models."""
    model_viewer = TestEntities.get(
        "USER",
        {
            "name": "Model Viewer",
            "hash": "usr013model",
            "page": {"name": "Model Viewer Page", "hash": "pgusr13model"},
            "permissions": {"models": "VIEW"},
        },
    )
    page_owner = TestEntities.get(
        "USER",
        {
            "name": "User Page Owner",
            "hash": "usr013owner",
            "page": {"name": "Owner User Page", "hash": "pgusr13owner"},
        },
    )
    category = TestEntities.get(
        "CATEGORY", {"name": "Visible Category", "hash": "cat013model"}
    )
    user_page_task = TestEntities.get(
        "TASK",
        {"name": "User Page Task", "hash": "tsk013user"},
        page=page_owner.page,
    )
    category_page = TestEntities.get(
        "PAGE",
        {
            "name": "Category Page",
            "hash": "pg013model",
            "categories": [{"name": "Visible Category", "hash": "cat013model"}],
        },
    )
    category_task = TestEntities.get(
        "TASK",
        {"name": "Category Task", "hash": "tsk013model"},
        page=category_page,
    )

    assert user_page_task.required == ["users", "pgusr13owner"]
    assert category_task.required == ["models", "pg013model", category.hash]
    assert user_page_task.allowed(Action.VIEW, user=model_viewer) is False
    assert category_task.allowed(Action.VIEW, user=model_viewer) is True


# @matrix permissions task : assignment restricted-access
@pytest.mark.unit
def test_task_update_rejects_assignee_without_restricted_task_access():
    """Assignment cannot grant access through a restricted task form."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "Staff Review",
            "hash": "tsk013s",
            "page": {"name": "Visible Pet", "hash": "pg013s"},
        },
    )
    restricted_form = TestEntities.get(
        "FORM",
        {
            "name": "Application Review",
            "hash": "frm013s",
            "restricted_to": ["grp013s"],
        },
    )
    outsider = TestEntities.get(
        "USER",
        {
            "name": "Outside Adopter",
            "hash": "usr013s",
            "page": {"name": "Outside Page", "hash": "pgusr13s"},
        },
    )
    outsider_page = outsider.page
    outsider_page.user = outsider

    with pytest.raises(
        ValidationError,
        match="Assigned user does not have access",
    ):
        task.update(
            {
                "page": task.page,
                "form": restricted_form,
                "name": task.name,
                "description": task.description,
                "due_date": task.due_date,
                "assigned_to": outsider_page,
            }
        )

    assert task.assigned_to is None
    assert "assigned_to" not in task.db


# @matrix task task-scheduling : due-date postpone
@pytest.mark.unit
def test_task_postpone_preserves_original_due_date_once():
    """Postponing preserves the original due date across later postponements."""
    task = Task(testing=True)
    first_due = datetime(2025, 7, 1, 12, tzinfo=timezone.utc)
    first_postponed = datetime(2025, 7, 3, 12, tzinfo=timezone.utc)
    second_postponed = datetime(2025, 7, 5, 12, tzinfo=timezone.utc)
    task.due_date = first_due

    with patch(
        "lagniappe.core.entities.task.scheduling.calculate_postponed_due_date",
        side_effect=[first_postponed, second_postponed],
    ):
        task.postpone(first_due)
        task.postpone(first_postponed)

    assert task.postponed_from == first_due
    assert task.due_date == second_postponed


# @matrix task : tracking update uploaded-files
@pytest.mark.unit
def test_task_update_tracks_project_model_and_uploaded_file():
    """Task updates track project/model transitions and uploaded file relations."""
    project = TestEntities.get("PROJECT", {"name": "Project", "hash": "prj014"})
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Model", "hash": "mdl014"},
        project=project,
    )
    page = TestEntities.get("PAGE", {"name": "Page", "hash": "pg014"})
    other_page = TestEntities.get("PAGE", {"name": "Other Page", "hash": "pg014b"})
    file_entity = TestEntities.get("FILE", {"name": "Attachment", "hash": "fil014"})
    task = Task(testing=True)
    task._key = "tsk014"
    task.page = page

    task.update(
        {
            "page": other_page,
            "name": "Updated",
            "description": "New description",
            "due_date": datetime(2025, 8, 1, tzinfo=timezone.utc),
            "model": model,
            "asset_files": [file_entity],
        }
    )

    assert task.page is other_page
    assert task.name == "Updated"
    assert task.description == "New description"
    assert task.model is model
    assert task.project is project
    assert task.files == [file_entity]
    assert task.db["files"] == [file_entity.key]
    assert any(
        intent.entity is page and intent.intent is MutationIntentType.TOUCH
        for intent in task.mutation_intents
    )
    assert any(
        intent.entity is file_entity and intent.intent is MutationIntentType.PATCH
        for intent in task.mutation_intents
    )
    assert task.updated is True
    assert task.properties.files.label == "Attachments"
    assert isinstance(task.properties.files, ColumnMixin)
    assert task.properties.files.sort_value == 1
    assert file_entity.tasks == [task]
    assert file_entity.db["tasks"] == [task.key]

    file_entity.properties.preview._value = "/preview/attachment"
    attachment = task.properties.files.column_value[0]
    assert attachment["id"] == file_entity.urlsafe_key
    assert attachment["name"] == "Attachment"
    assert "url" not in attachment

    task.properties.files._column_value = None
    file_entity.properties.preview._value = None
    attachment = task.properties.files.column_value[0]
    assert attachment["id"] == file_entity.urlsafe_key
    assert "url" not in attachment

    task.update({"project": project})

    assert task.project is project
    assert task.model is None

    task.update({})

    assert task.project is None
    assert task.model is None


# @matrix task : file-assets file-details preload update uploaded-files
@pytest.mark.unit
def test_task_update_saves_file_relations_from_upload_assets():
    """Task upload saves file relations while preloading file details."""
    page = TestEntities.get("PAGE", {"name": "Page", "hash": "pg015a"})
    file_entity = TestEntities.get(
        "FILE",
        {
            "name": "Attachment",
            "filename": "attachment.csv",
            "hash": "fil015a",
            "assets": {"file": {"type": "file", "path": "fil015a_file.csv"}},
        },
    )
    file_entity.filename = "attachment.csv"
    task = Task(testing=True)
    task._key = "tsk015a"
    task.page = page

    task.update(
        {
            "asset_files": [file_entity],
        }
    )

    assert task.files == [file_entity]
    assert task.db["files"] == [file_entity.key]
    assert file_entity.tasks == [task]

    assert task.assets == {}

    preload = task.properties.files.preload
    assert preload["attachment.csv"]["id"] == file_entity.urlsafe_key
    assert preload["attachment.csv"]["name"] == "Attachment"
    assert preload["attachment.csv"]["attached"] is True
    assert "url" not in preload["attachment.csv"]
    assert "preview" not in preload["attachment.csv"]
    assert "preview_url" not in preload["attachment.csv"]
    preload["attachment.csv"]["id"] = "mutated"
    assert file_entity.details["id"] == file_entity.urlsafe_key


# @matrix task : create entity-lifecycle list-owner-fingerprint readonly save
@pytest.mark.unit
def test_task_entity_lifecycle_readonly_and_save_relations():
    """Task lifecycle helpers expose readonly and save relation contracts."""
    page = TestEntities.get("PAGE", {"name": "Page", "hash": "pg015"})
    project = TestEntities.get("PROJECT", {"name": "Project", "hash": "prj015"})
    form = TestEntities.get("FORM", {"name": "Form", "hash": "frm015"})
    schema = [
        {
            "id": "input-textab12",
            "type": "input",
            "input": "text",
            "title": "Text Field",
        }
    ]
    form.schema = schema
    form.version = "schema-v1"
    created_db = {"created": datetime(2025, 1, 1, tzinfo=timezone.utc)}

    with patch(
        "lagniappe.core.entities.entity.database_utility.create_key",
        return_value="tsk015created",
    ):
        with patch(
            "lagniappe.core.entities.entity.database_get.entity", return_value=None
        ):
            with patch(
                "lagniappe.core.entities.entity.database_utility.create_entity",
                return_value=created_db,
            ):
                created = Task.create(
                    {"page": page, "form": form, "project": project, "name": "Created"}
                )

    assert created.kind == "task"
    assert created.page is page
    assert created.form is form
    assert created.project is project
    assert created.name == "Created"

    task = Task(testing=True)
    task.db.update(
        {
            "hash": "tsk015",
            "name": "Stateful",
            "modified": datetime(2025, 1, 2, tzinfo=timezone.utc),
        }
    )
    task._key = "tsk015"
    linked_page = TestEntities.get("PAGE", {"name": "Linked", "hash": "pg015link"})
    assigned_page = TestEntities.get("PAGE", {"name": "Assigned", "hash": "pg015asgn"})
    task.page = page
    task.project = project
    task.properties.assigned_to._value = assigned_page
    task.db["assigned_to"] = assigned_page.key
    task.linked_pages = [page, linked_page]
    task.form = form
    task.submission = {"input-textab12": "hello"}

    assert task.task_list_owners == [page, project, assigned_page, linked_page]

    assert task.readonly is False

    task.completed = True
    task.completed_on = datetime(2025, 1, 3, tzinfo=timezone.utc)
    task._readonly = None

    assert task.readonly is False
    assert task.column("completed").editable is True
    assert task.column("due_date").editable is False
    assert task.column("name").editable is False

    task._testing = False
    with patch("lagniappe.core.entities.entity.Entities.save") as save_mock:
        task.save()

    save_mock.assert_called_once_with(task)
