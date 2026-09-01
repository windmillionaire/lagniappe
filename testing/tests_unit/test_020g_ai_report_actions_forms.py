"""Focused AI-report characterization coverage."""

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.ai.reporting.execution import undo as report_undo
from lagniappe.core.tools.ai.reporting.execution.actions import common as report_common
from lagniappe.core.tools.ai.reporting.execution.actions import results as report_results
from testing.utility.ai_report_fakes import (
    _fetch_one_from,
    _patch_fake_keys,
    _permissioned_user,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities


# @matrix ai-report : attachments create-order default-category deterministic-run execute file-summary grouping partial-result persistence result skip-action
@pytest.mark.unit
def test_run_report_creates_form_category_page_and_project_chain(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-owner")
    file = _test_file("july-receipt.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Run report",
            "hash": "runner-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
        },
    )
    report.proposal = {
        "summary": "Create a small workspace chain.",
        "confidence": 0.92,
        "actions": [
            {
                "id": "page_form",
                "type": "create_form",
                "data": {
                    "name": "Record Form",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-vendor",
                            "type": "input",
                            "input": "text",
                            "title": "Vendor",
                        }
                    ],
                },
            },
            {
                "id": "category",
                "type": "create_category",
                "data": {"name": "Receipts", "form_action": "page_form"},
            },
            {
                "id": "page",
                "type": "create_page",
                "data": {
                    "name": "July Receipt",
                    "category_action": "category",
                    "document_markdown": "# Receipt notes\n\n- Review the total",
                },
            },
            {
                "id": "attachment",
                "type": "attach_file_to_page",
                "data": {"page_action": "page", "file": "july-receipt.pdf"},
            },
            {
                "id": "summary",
                "type": "summarize_file",
                "data": {
                    "file": "july-receipt.pdf",
                    "summary": "Receipt for July house supplies.",
                    "search": True,
                },
            },
            {
                "id": "uncategorized_page",
                "type": "create_page",
                "data": {"name": "Loose scan"},
            },
            {
                "id": "skipped_page",
                "type": "create_page",
                "skip": True,
                "data": {"name": "Intentionally skipped"},
            },
            {
                "id": "project",
                "type": "create_project",
                "data": {"name": "House Admin"},
            },
            {
                "id": "task_form",
                "type": "create_form",
                "data": {
                    "name": "Follow-up Form",
                    "form_type": "task",
                    "schema": [
                        {
                            "id": "textarea-notes",
                            "type": "textarea",
                            "title": "Notes",
                        },
                        {
                            "id": "html-warning",
                            "type": "html",
                            "title": "Warning",
                            "content_markdown": (
                                "**Review carefully.**"
                                "<script>unsafe()</script>"
                            ),
                        }
                    ],
                },
            },
            {
                "id": "model",
                "type": "create_model_task",
                "data": {
                    "name": "Review receipt",
                    "project_action": "project",
                    "form_action": "task_form",
                },
            },
        ],
    }
    saved_batches = []
    saved_entities = []

    def save_entities(*entities):
        saved_entities.extend(entities)
        saved_batches.append([getattr(entity, "kind", None) for entity in entities])

    monkeypatch.setattr(report_runner.Entities, "save", save_entities)
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        lambda key, request: None,
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY", {"name": "Uncategorized Pages", "hash": "uncategorized"}
        ),
    )
    create_page = report_runner.Entities.PAGE.create

    def create_page_with_in_memory_assets(data):
        page = create_page(data)
        page.save_asset = lambda content, *_args, **_kwargs: content
        return page

    monkeypatch.setattr(
        report_runner.Entities.PAGE,
        "create",
        create_page_with_in_memory_assets,
    )
    create_form = report_runner.Entities.FORM.create

    def create_form_with_in_memory_assets(data):
        form = create_form(data)
        form.generated_static_content = {}
        form.set_html_field = lambda field_id, content: (
            form.generated_static_content.__setitem__(field_id, content)
        )
        return form

    monkeypatch.setattr(
        report_runner.Entities.FORM,
        "create",
        create_form_with_in_memory_assets,
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert report.status == "complete"
    assert report.pending is False
    created_kinds = [
        action["entity"]["kind"] for action in result["actions"] if action.get("entity")
    ]
    assert created_kinds == [
        "form",
        "category",
        "page",
        "file",
        "file",
        "page",
        "project",
        "form",
        "model",
    ]
    assert result["actions"][5]["entity"]["name"] == "Loose scan"
    loose_page = next(
        entity
        for entity in saved_entities
        if getattr(entity, "entity_kind", None) == "page"
        and entity.name == "Loose scan"
    )
    assert loose_page.model.name == "Uncategorized Pages"
    assert result["actions"][6]["status"] == "skipped"
    assert result["actions"][9]["entity"]["parent"]["name"] == "House Admin"
    assert result["actions"][3]["target"]["kind"] == "page"
    assert result["actions"][3]["target"]["name"] == "July Receipt"
    july_page = next(
        entity
        for entity in saved_entities
        if getattr(entity, "entity_kind", None) == "page"
        and entity.name == "July Receipt"
    )
    assert july_page.properties.document.html == (
        "<h1>Receipt notes</h1><ul><li>Review the total</li></ul>"
    )
    assert "document_markdown" not in report.proposal["actions"][2]["data"]
    task_form = next(
        entity
        for entity in saved_entities
        if getattr(entity, "entity_kind", None) == "form"
        and entity.name == "Follow-up Form"
    )
    assert task_form.generated_static_content == {
        "html-warning": "<p><strong>Review carefully.</strong></p>"
    }
    assert "content_markdown" not in task_form.schema[1]
    assert result["actions"][4]["type"] == "summarize_file"
    assert result["actions"][4]["entity"]["kind"] == "file"
    assert result["actions"][4]["file_summary"] == {
        "enabled": True,
        "complete": True,
        "present": True,
        "status": "Summary saved from report.",
    }
    assert file.summary == "Receipt for July house supplies."
    assert file.properties.summarize.search is True
    grouped = report.properties.result.grouped_actions
    assert [action["type"] for action in grouped] == [
        "create_form",
        "create_category",
        "create_page",
        "create_page",
        "create_page",
        "create_project",
        "create_form",
        "create_model_task",
    ]
    assert grouped[2]["attachments"][0]["entity"]["name"] == "july-receipt"
    assert grouped[2]["attachments"][0]["file_summary"]["complete"] is True
    assert saved_batches[0] == ["report"]
    assert saved_batches[-1] == ["report"]




# @matrix ai-report form-schema submission : deterministic-run stale-proposal validation
@pytest.mark.unit
def test_run_report_rejects_saved_pending_submissions_before_execution():
    user = _test_user("runner-pending-submission-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Stale pending submission report",
            "hash": "runner-pending-submission-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Create a dental page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "create_dental_page",
                        "type": "create_page",
                        "skip": True,
                        "data": {
                            "name": "Pediatric Dentistry",
                            "form_name": "Business",
                            "submission_needed": True,
                        },
                    }
                ],
            },
        },
    )

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        report_runner.run_report(report, user)




# @matrix ai-report : deterministic-run persistence submission-completion
@pytest.mark.unit
def test_run_report_uses_category_form_from_stored_key_for_page_submission(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-page-form-owner")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Medical Providers", "hash": "medical-providers"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Provider", "hash": "provider-form"},
    )
    form.form_type = "page"
    form.schema = get_schema("text_input_only")
    category.db["form"] = form.key
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Page submission report",
            "hash": "runner-page-submission-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Create a provider page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "provider_page",
                        "type": "create_page",
                        "data": {
                            "name": "Lucile Packard Children's Hospital Stanford",
                            "category": category.urlsafe_key,
                            "submission": {
                                "input-textab12": "Pediatric hospital provider.",
                                "unknown-field": "must not persist",
                            },
                        },
                    }
                ],
            },
        },
    )
    saved = []
    entities = {
        category.urlsafe_key: category,
        form.urlsafe_key: form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    pages = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "page"
    ]
    assert result["status"] == "complete"
    assert len(pages) == 1
    assert pages[0].form is form
    assert pages[0].submission == {
        "input-textab12": "Pediatric hospital provider."
    }
    assert result["actions"][0]["submission"] == {"created": True, "field_count": 1}




# @matrix ai-report : batch-field-patch deterministic-run moves schema-update undo
@pytest.mark.unit
def test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo(
    monkeypatch,
):
    user = _test_user("runner-edit-owner")
    old_category = TestEntities.get(
        "CATEGORY",
        {"name": "Open Invoices", "hash": "open-invoices"},
    )
    paid_category = TestEntities.get(
        "CATEGORY",
        {"name": "Paid Invoices", "hash": "paid-invoices"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Invoice Form", "hash": "invoice-form"},
    )
    form.form_type = "task"
    form.schema = [
        {
            "id": "select-status",
            "type": "select",
            "title": "Status",
            "options": [{"value": "due", "label": "Due"}],
        }
    ]
    page = TestEntities.get(
        "PAGE",
        {"name": "Sousa Doors", "hash": "invoice-page"},
    )
    page.model = old_category
    page.form = form
    page.properties.submission.value = {"select-status": "due"}
    task_target_page = TestEntities.get(
        "PAGE",
        {"name": "Paid Archive", "hash": "paid-archive-page"},
    )
    task_target_page.model = paid_category
    task = TestEntities.get(
        "TASK",
        {"name": "July invoice", "hash": "invoice-task"},
        page=page,
    )
    task.form = form
    task.properties.submission.value = {"select-status": "due"}

    report = TestEntities.get(
        "REPORT",
        {
            "name": "Invoice edit report",
            "hash": "runner-edit-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Mark paid invoices and move them.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "schema",
                        "type": "update_form_schema",
                        "data": {
                            "form": "invoice-form",
                            "operations": [
                                {
                                    "op": "add_select_option",
                                    "schema_id": "select-status",
                                    "option": {
                                        "value": "paid",
                                        "label": "Paid",
                                    },
                                },
                                {
                                    "op": "add_field",
                                    "field": {
                                        "id": "input-payment-reference",
                                        "type": "input",
                                        "input": "text",
                                        "title": "Payment Reference",
                                        "required": True,
                                        "visibility": [
                                            {
                                                "id": "select-status",
                                                "value": "paid",
                                            }
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "id": "field_updates",
                        "type": "update_submission_fields",
                        "depends_on": ["schema"],
                        "data": {
                            "updates": [
                                {
                                    "page": "invoice-page",
                                    "schema_id": "select-status",
                                    "new_value": "paid",
                                },
                                {
                                    "task": "invoice-task",
                                    "schema_id": "select-status",
                                    "new_value": "paid",
                                },
                                {
                                    "task": "invoice-task",
                                    "schema_id": "input-missing",
                                    "new_value": "kept only if schema exists",
                                },
                            ]
                        },
                    },
                    {
                        "id": "move_page",
                        "type": "move_page",
                        "data": {
                            "page": "invoice-page",
                            "category": "paid-invoices",
                        },
                    },
                    {
                        "id": "move_task",
                        "type": "move_task",
                        "data": {
                            "task": "invoice-task",
                            "to_page": "paid-archive-page",
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (
            old_category,
            paid_category,
            form,
            page,
            task_target_page,
            task,
        )
    }
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert [action["status"] for action in result["actions"]] == [
        "complete",
        "complete",
        "complete",
        "complete",
    ]
    status_field = next(field for field in form.schema if field["id"] == "select-status")
    assert {"value": "paid", "label": "Paid"} in status_field["options"]
    payment_field = next(
        field for field in form.schema if field["id"] == "input-payment-reference"
    )
    assert payment_field["required"] is False
    assert "visibility" not in payment_field
    assert page.submission == {"select-status": "paid"}
    assert task.submission == {"select-status": "paid"}
    assert page.model is None
    assert "model" not in page.db
    assert page.categories == [paid_category]
    assert page.db["categories"] == [paid_category.key]
    assert task.page is task_target_page
    assert result["actions"][0]["schema_updates"]["applied"] == [
        {
            "index": 1,
            "op": "add_select_option",
            "schema_id": "select-status",
            "value": "paid",
            "label": "Paid",
        },
        {
            "index": 2,
            "op": "add_field",
            "schema_id": "input-payment-reference",
            "label": "Payment Reference",
        },
    ]
    assert result["actions"][1]["updates"]["applied"] == [
        {
            "index": 1,
            "entity": {
                "id": "invoice-page",
                "kind": "page",
                "name": "Sousa Doors",
                "url": "/test/page/invoice-page",
            },
            "schema_id": "select-status",
        },
        {
            "index": 2,
            "entity": {
                "id": "invoice-task",
                "kind": "task",
                "name": "July invoice",
                "url": "/test/task/invoice-task",
            },
            "schema_id": "select-status",
        },
    ]
    assert result["actions"][1]["updates"]["skipped"][0]["schema_id"] == "input-missing"
    assert result["actions"][1]["previous"] == [
        {
            "index": 1,
            "entity": {
                "id": "invoice-page",
                "kind": "page",
                "name": "Sousa Doors",
                "url": "/test/page/invoice-page",
            },
            "schema_id": "select-status",
            "had_value": True,
            "previous_value": "due",
        },
        {
            "index": 2,
            "entity": {
                "id": "invoice-task",
                "kind": "task",
                "name": "July invoice",
                "url": "/test/task/invoice-task",
            },
            "schema_id": "select-status",
            "had_value": True,
            "previous_value": "due",
        },
    ]
    assert result["actions"][2]["moved"]["from"]["id"] == "open-invoices"
    assert result["actions"][2]["moved"]["to"]["id"] == "paid-invoices"
    assert result["actions"][3]["moved"]["from"]["id"] == "invoice-page"
    assert result["actions"][3]["moved"]["to"]["id"] == "paid-archive-page"

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert report.status == "ready"
    assert report.pending is False
    assert report.result["status"] == "undone"
    assert report.result["undone"] is True
    assert form.schema == [
        {
            "id": "select-status",
            "type": "select",
            "title": "Status",
            "options": [{"value": "due", "label": "Due"}],
        }
    ]
    assert page.submission == {"select-status": "due"}
    assert task.submission == {"select-status": "due"}
    assert page.model is old_category
    assert page.db["model"] == old_category.key
    assert page.categories == [old_category]
    assert task.page is page
    assert saved




# @matrix ai-report : deterministic-run rename undo
@pytest.mark.unit
def test_run_report_renames_entity_without_submission_and_undoes(monkeypatch):
    user = _test_user("runner-rename-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Orthodontics", "hash": "orthodontics-page"},
    )
    assert page.form is None
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Rename page report",
            "hash": "runner-rename-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Rename Orthodontics to Teeth.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "rename_page",
                        "type": "rename_entity",
                        "data": {
                            "entity": page.urlsafe_key,
                            "name": " Teeth ",
                        },
                    }
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page}),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert page.name == "Teeth"
    assert result["actions"][0]["entity"]["name"] == "Teeth"
    assert result["actions"][0]["before"]["name"] == "Orthodontics"
    assert result["actions"][0]["expected"]["name"] == "Teeth"

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert page.name == "Orthodontics"
    assert saved




# @matrix ai-report submission : continue deterministic-run empty-update recoverable
@pytest.mark.unit
def test_run_report_skips_empty_submission_update_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-empty-submission-update-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Empty submission update report",
            "hash": "runner-empty-submission-update-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Skip the no-op update and keep building.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "empty_submission_update",
                        "type": "update_submission_fields",
                        "display_label": "Submission Update: Rank",
                        "data": {"updates": []},
                    },
                    {
                        "id": "built_page",
                        "type": "create_page",
                        "data": {"name": "Kung Fu"},
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "skipped"
    assert result["actions"][0]["error"] == report_common.SUBMISSION_UPDATE_ROWS_ERROR
    assert result["actions"][0]["note"] == (
        "Skipped because no executable submission field updates were provided."
    )
    assert result["actions"][1]["status"] == "complete"
    assert result["actions"][1]["entity"]["name"] == "Kung Fu"
    assert report.status == "complete"
    assert saved




# @matrix ai-report : deterministic-run idempotent page-form undo
@pytest.mark.unit
def test_run_report_adds_form_to_existing_page_with_undo(monkeypatch):
    user = _test_user("runner-add-page-form-owner")
    category = TestEntities.get(
        "CATEGORY", {"name": "Property Tax", "hash": "property-tax-category"}
    )
    old_form = TestEntities.get(
        "FORM", {"name": "General Record", "hash": "general-record-form"}
    )
    old_form.form_type = "page"
    property_tax_form = TestEntities.get(
        "FORM", {"name": "Property Tax Record", "hash": "property-tax-form"}
    )
    property_tax_form.form_type = "page"
    page = TestEntities.get(
        "PAGE", {"name": "Toft Property Taxes", "hash": "toft-property-taxes"}
    )
    page.model = category
    page.form = old_form
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Add property-tax form",
            "hash": "runner-add-page-form-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Use the property-tax form on the existing page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "add_property_tax_form",
                        "type": "add_form_to_page",
                        "data": {
                            "page": page.urlsafe_key,
                            "form": property_tax_form.urlsafe_key,
                        },
                    },
                    {
                        "id": "add_property_tax_form_again",
                        "type": "add_form_to_page",
                        "data": {
                            "page": page.urlsafe_key,
                            "form": property_tax_form.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (category, old_form, property_tax_form, page)
    }
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    grouped = report.properties.proposal.display_actions
    assert grouped[0]["type"] == "page_group"
    assert grouped[0]["support"][0]["label"] == "Add Form"
    assert grouped[0]["support"][0]["value"] == property_tax_form.urlsafe_key

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert page.form is property_tax_form
    assert property_tax_form in category.forms
    assert result["actions"][0]["target"]["id"] == property_tax_form.urlsafe_key
    assert result["actions"][0]["previous"] == {
        "form": report_results._entity_result(old_form),
        "had_form": False,
    }
    assert result["actions"][1]["previous"] == {
        "form": report_results._entity_result(property_tax_form),
        "had_form": True,
    }
    assert result["actions"][1]["note"] == "Page already had this form."

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert page.form is old_form
    assert undo["actions"][0]["note"] == (
        "Page already had this form; nothing changed."
    )
    assert undo["actions"][1]["note"] == "Restored previous page form."
    assert saved




# @matrix ai-report form-schema : deterministic-run permission-failure schema-update
@pytest.mark.unit
def test_run_report_rejects_schema_update_without_form_edit_permission(monkeypatch):
    user = _permissioned_user(
        "runner-schema-denied-user",
        {
            "page-editable": "EDIT",
        },
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Restricted Invoice Form", "hash": "restricted-invoice-form"},
    )
    form.schema = []
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Denied schema update report",
            "hash": "runner-schema-denied-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Try to add a field.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "schema",
                        "type": "update_form_schema",
                        "data": {
                            "form": "restricted-invoice-form",
                            "operations": [
                                {
                                    "op": "add_field",
                                    "field": {
                                        "id": "input-note",
                                        "type": "input",
                                        "input": "text",
                                        "title": "Note",
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        },
    )

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"restricted-invoice-form": form}),
    )
    monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)

    result = report_runner.run_report(report, user)

    assert result["status"] == "failed"
    assert report.status == "failed"
    assert result["actions"][0]["status"] == "failed"
    assert result["actions"][0]["error"] == (
        "You do not have permission to update this form schema."
    )
    assert form.schema == []
