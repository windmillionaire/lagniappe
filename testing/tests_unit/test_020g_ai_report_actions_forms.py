"""Focused AI-report characterization coverage."""

import copy
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
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
                "type": "attach_file",
                "data": {'entity_action': "page", "file": "july-receipt.pdf"},
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
        page.save_asset = lambda content, *_args, **_kwargs: SimpleNamespace(updated=False)
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
    assert "UTC · Application</p></blockquote>" in july_page.properties.document.html
    assert july_page.properties.document.ydoc
    assert july_page.properties.document.html.endswith(
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
