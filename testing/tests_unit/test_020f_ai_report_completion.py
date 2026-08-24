"""Focused AI-report characterization coverage."""

from types import SimpleNamespace

import pytest

from lagniappe.core.tools.ai import organize
from testing.utility.ai_report_fakes import (
    _fetch_one_from,
    _prompt_context_json,
    _test_file,
    _test_user,
    _with_validator,
)
from testing.utility.test_entities import TestEntities

# @features ai-report
# @dimensions validation page-form no-category
@pytest.mark.unit
def test_validate_proposal_accepts_add_form_to_page_without_category():
    proposal = {
        "summary": "Create a property-tax form and add it to the existing page.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "property_tax_form",
                "type": "create_form",
                "data": {
                    "name": "Property Tax Record",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-apn",
                            "type": "input",
                            "input": "text",
                            "title": "Assessor Parcel Number",
                        }
                    ],
                },
            },
            {
                "id": "add_property_tax_form",
                "type": "add_form_to_page",
                "depends_on": ["property_tax_form"],
                "data": {
                    "page": "existing-property-tax-page",
                    "form_action": "property_tax_form",
                },
            },
        ],
    }

    assert organize.validate_proposal(proposal) is proposal




# @pair ai-report:submission-completion
# @pair ai-report:generate
# @pair ai-report:pipeline
# @pair form-schema:structured-output
# @pair submission:focused-prompt
# @pair submission:evidence-mapping
@pytest.mark.unit
def test_generate_organize_report_completes_planned_submissions(monkeypatch):
    user = _test_user("complete-pipeline-owner")
    file = _test_file("pipeline-receipt.pdf", "application/pdf")
    file.summary = "Receipt from Acme dated 2026-07-10 for $42.00."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Complete pipeline report",
            "hash": "complete-pipeline-report",
            "parent": user,
            "user": user,
            "instructions": "Save this receipt.",
            "input_files": [file],
        },
    )
    planned = {
        "summary": "Create a receipt record.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "receipt_form",
                "type": "create_form",
                "data": {
                    "name": "Receipt",
                    "form_type": "page",
                    "schema": [
                        {"id": "input-merchant", "type": "input", "title": "Merchant"}
                    ],
                },
            },
            {
                "id": "receipt_category",
                "type": "create_category",
                "data": {"name": "Receipts", "form_action": "receipt_form"},
            },
            {
                "id": "receipt_page",
                "type": "create_page",
                "data": {"name": "Acme Receipt", "category_action": "receipt_category"},
            },
            {
                "id": "attach_receipt",
                "type": "attach_file_to_page",
                "data": {"page_action": "receipt_page", "file": file.urlsafe_key},
            },
        ],
    }
    calls = []

    def generate(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return planned
        return {
            "submissions": [
                {
                    "action_id": "receipt_page",
                    "submission": {"input-merchant": "Acme"},
                }
            ]
        }

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=(
            "create_form",
            "create_category",
            "create_page",
            "attach_file_to_page",
            "needs_review",
        ),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
        tools=None,
        max_tool_iterations=None,
        max_tool_file_parts_per_turn=None,
    )

    result = organize.generate_organize_report(prompt, report, user)

    assert len(calls) == 2
    assert calls[1].prompt_type == "organize submission completion"
    assert result["actions"][2]["data"]["submission"] == {
        "input-merchant": "Acme"
    }




# @features ai-report
# @dimensions submission-completion focused-prompt evidence-mapping json-output prompt validation partial
@pytest.mark.unit
def test_complete_organize_submissions_uses_one_focused_prompt(
    monkeypatch,
    get_schema,
):
    user = _test_user("focused-completion-owner")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Medical Providers", "hash": "focused-medical"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Provider", "hash": "focused-provider-form"},
    )
    form.form_type = "page"
    form.schema = get_schema("text_input_only")
    category.db["form"] = form.key
    first = _test_file("visit-summary.pdf", "application/pdf")
    first.summary = (
        "Patient Lucy visited Stanford Children's Health on 2024-08-20; "
        "the provider was Dr. Rivera."
    )
    second = _test_file("provider-card.png", "image/png")
    second.summary = "Provider address is 725 Welch Road, Palo Alto."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Focused completion report",
            "hash": "focused-completion-report",
            "parent": user,
            "user": user,
            "instructions": "Save the provider and supporting visit records.",
            "input_files": [first, second],
        },
    )
    proposal = {
        "summary": "Create the provider record.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "provider_page",
                "type": "create_page",
                "reason": "The files support one provider record.",
                "data": {
                    "name": "Stanford Children's Health",
                    "category": category.urlsafe_key,
                },
            },
            {
                "id": "attach_visit",
                "type": "attach_file_to_page",
                "data": {"page_action": "provider_page", "file": first.urlsafe_key},
            },
            {
                "id": "attach_card",
                "type": "attach_file_to_page",
                "data": {"page_action": "provider_page", "file": second.urlsafe_key},
            },
        ],
    }
    entities = {
        category.urlsafe_key: category,
        category.key: category,
        form.urlsafe_key: form,
        form.key: form,
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return {
            "submissions": [
                {
                    "action_id": "provider_page",
                    "submission": {
                        "input-textab12": "Stanford Children's Health",
                        "Provider Name": "ignored label",
                    },
                }
            ]
        }

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=generate,
        service_tier="priority",
    )

    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.prompt_type == "organize submission completion"
    assert prompt.model_tier == "primary"
    assert prompt.thinking_budget is None
    assert prompt.service_tier == "priority"
    assert prompt.build().index("## Instructions") < prompt.build().index(
        "## Context"
    )
    assert prompt.search is False
    assert prompt.tools is None
    assert prompt.response_schema is None
    assert prompt.output_format["type"] == "JSON"
    context = _prompt_context_json(prompt, "Completion Context")
    assert context["report_intent"] == report.instructions
    assert len(context["forms"]) == 1
    assert len(context["records"]) == 1
    assert context["records"][0]["action_id"] == "provider_page"
    assert context["records"][0]["supporting_file_refs"] == [
        first.urlsafe_key,
        second.urlsafe_key,
    ]
    assert [item["summary"] for item in context["evidence_files"]] == [
        first.summary,
        second.summary,
    ]
    assert completed["actions"][0]["data"]["submission"] == {
        "input-textab12": "Stanford Children's Health"
    }
    assert "submission_empty_reason" not in completed["actions"][0]["data"]




# @features ai-report
# @dimensions submission-completion explicit-task-identity inherited-form
@pytest.mark.unit
def test_complete_organize_submissions_uses_target_task_form(
    monkeypatch,
    get_schema,
):
    user = _test_user("targeted-task-completion-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Prescriptions", "hash": "targeted-prescriptions-page"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Prescription", "hash": "targeted-prescription-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {"name": "Lisinopril Prescription", "hash": "targeted-lisinopril-task"},
        page=page,
    )
    task.form = form
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Targeted prescription completion",
            "hash": "targeted-prescription-report",
            "parent": user,
            "user": user,
            "input_files": [],
        },
    )
    proposal = {
        "summary": "Record a Lisinopril occurrence.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "lisinopril_completion",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": page.urlsafe_key,
                    "task": task.urlsafe_key,
                    "completed": True,
                },
            }
        ],
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                task.urlsafe_key: task,
                form.urlsafe_key: form,
                form.key: form,
            }
        ),
    )

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=lambda prompt: {
            "submissions": [
                {
                    "action_id": "lisinopril_completion",
                    "submission": {"input-textab12": "10 mg daily"},
                }
            ]
        },
    )

    data = completed["actions"][0]["data"]
    assert data["form"] == form.urlsafe_key
    assert data["submission"] == {"input-textab12": "10 mg daily"}




# @features ai-report
# @dimensions submission-completion existing-task partial-update evidence-mapping
@pytest.mark.unit
def test_complete_organize_submissions_updates_existing_task_submission(
    monkeypatch,
    get_schema,
):
    user = _test_user("existing-task-completion-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Accounts Payable", "hash": "existing-invoice-page"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Invoice", "hash": "existing-invoice-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {"name": "Acme invoice", "hash": "existing-invoice-task"},
        page=page,
    )
    task.form = form
    task.submission = {"input-textab12": "Pending"}
    file = _test_file("acme-paid.pdf", "application/pdf")
    file.summary = "Acme invoice paid. Confirmation number 834921."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Update invoice confirmation",
            "hash": "existing-invoice-report",
            "parent": user,
            "user": user,
            "instructions": "Add the payment confirmation to the existing invoice.",
            "input_files": [file],
        },
    )
    proposal = {
        "summary": "Update the invoice and retain its confirmation.",
        "confidence": 0.95,
        "issues": [],
        "actions": [
            {
                "id": "update_invoice",
                "type": "update_submission_fields",
                "display_label": "Update Acme invoice",
                "data": {"task": task.urlsafe_key},
            },
            {
                "id": "attach_confirmation",
                "type": "attach_file_to_task",
                "data": {"task": task.urlsafe_key, "file": file.urlsafe_key},
            },
        ],
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                task.urlsafe_key: task,
                form.urlsafe_key: form,
                form.key: form,
            }
        ),
    )
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return {
            "submissions": [
                {
                    "action_id": "update_invoice",
                    "submission": {
                        "input-textab12": "Confirmation 834921",
                    },
                }
            ]
        }

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=generate,
    )

    context = _prompt_context_json(prompts[0], "Completion Context")
    assert context["records"][0]["existing_submission"] == {
        "input-textab12": "Pending"
    }
    assert context["records"][0]["supporting_file_refs"] == [file.urlsafe_key]
    assert completed["actions"][0]["data"]["updates"] == [
        {
            "task": task.urlsafe_key,
            "schema_id": "input-textab12",
            "new_value": "Confirmation 834921",
        }
    ]
    assert completed["actions"][1]["type"] == "attach_file_to_task"




# @features ai-report form-schema submission
# @dimensions submission-completion empty preservation issue
@pytest.mark.unit
def test_complete_organize_submissions_preserves_empty_form_records(
    monkeypatch,
    get_schema,
):
    user = _test_user("empty-focused-completion-owner")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Providers", "hash": "empty-focused-category"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Provider", "hash": "empty-focused-form"},
    )
    form.form_type = "page"
    form.schema = get_schema("text_input_only")
    category.db["form"] = form.key
    file = _test_file("unclear-provider.pdf", "application/pdf")
    file.summary = "A provider document with no matching form values."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Empty focused completion report",
            "hash": "empty-focused-completion-report",
            "parent": user,
            "user": user,
            "input_files": [file],
        },
    )
    proposal = {
        "summary": "Keep the provider record and its evidence.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "provider_page",
                "type": "create_page",
                "display_label": "Create provider",
                "data": {"name": "Unknown Provider", "category": category.urlsafe_key},
            },
            {
                "id": "attach_provider",
                "type": "attach_file_to_page",
                "data": {"page_action": "provider_page", "file": file.urlsafe_key},
            },
        ],
    }
    entities = {
        category.urlsafe_key: category,
        category.key: category,
        form.key: form,
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=lambda _prompt: {
            "submissions": [
                {
                    "action_id": "provider_page",
                    "submission": {},
                    "empty_reason": "The assigned summary supports no form fields.",
                }
            ]
        },
    )

    assert completed["actions"][0]["type"] == "create_page"
    assert completed["actions"][1]["type"] == "attach_file_to_page"
    assert completed["actions"][0]["data"]["submission"] == {}
    assert completed["actions"][0]["data"]["submission_empty_reason"] == (
        "The assigned summary supports no form fields."
    )
    assert completed["issues"] == [
        "Create provider: The assigned summary supports no form fields."
    ]
