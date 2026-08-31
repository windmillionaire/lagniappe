"""Focused AI-report characterization coverage."""

import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import create, organize, references as ai_references
from lagniappe.core.tools.ai.reporting.proposals import validation as proposal_validation
from testing.utility.ai_report_fakes import (
    _assert_repair_prompt_contract,
    _prompt_context,
    _with_validator,
)

# @matrix ai-report : generate validate
@pytest.mark.unit
def test_generate_organize_report_validates_ai_output(monkeypatch):
    proposal = {
        "summary": "Skip unsupported input.",
        "confidence": 0.6,
        "actions": [{"type": "skip", "reason": "Nothing to organize."}],
    }

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(lambda prompt: proposal),
    )

    assert organize.generate_organize_plan(object()) == proposal




# @matrix ai-report : generate repair validate
@pytest.mark.unit
def test_generate_organize_report_repairs_invalid_action_type_once(monkeypatch):
    invalid = {
        "summary": "Attach the file.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "attach_file",
                "type": "attach_file_page",
                "data": {"page": "page-id", "file": "file-id"},
            }
        ],
    }
    repaired = {
        "summary": "Attach the file.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "attach_file",
                "type": "attach_file_to_page",
                "data": {"page": "page-id", "file": "file-id"},
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["type"] == "attach_file_to_page"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    assert calls[1].thinking_budget is None




# @matrix ai-report : file-placement repair
@pytest.mark.unit
def test_generate_organize_report_repairs_missing_file_attachments(monkeypatch):
    invalid = {
        "summary": "Create two record pages.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "school_logs",
                "type": "create_page",
                "data": {"name": "School Logs"},
            },
            {
                "id": "school_resources",
                "type": "create_page",
                "data": {"name": "School Resources"},
            },
        ],
    }
    repaired = {
        **invalid,
        "summary": "Create two record pages and attach their source files.",
        "actions": [
            *invalid["actions"],
            {
                "id": "attach_log",
                "type": "attach_file_to_page",
                "data": {"page_action": "school_logs", "file": "file-log-id"},
            },
            {
                "id": "attach_resource",
                "type": "attach_file_to_page",
                "data": {
                    "page_action": "school_resources",
                    "file": "file-resource-id",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
        context_blocks=[
            {
                "label": "Report Input Files",
                "value": (
                    "```\n"
                    '[{"report_file_ref": "file-log-id"}, '
                    '{"report_file_ref": "file-resource-id"}]'
                    "\n```"
                ),
            }
        ],
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["data"]["file"] for action in result["actions"][2:]] == [
        "file-log-id",
        "file-resource-id",
    ]
    assert len(calls) == 2
    assert "attach every report input file" in _prompt_context(
        calls[1], "Validation Error"
    )
    repair_text = calls[1].preview()
    assert "Every exact report_file_ref must appear" in repair_text
    assert "Creating a page or task" in repair_text




# @matrix ai-report : fallback file-placement
@pytest.mark.unit
def test_generate_organize_report_reviews_files_missing_after_repair(monkeypatch):
    incomplete = {
        "summary": "Create the records page.",
        "confidence": 0.6,
        "issues": [],
        "actions": [
            {
                "id": "records",
                "type": "create_page",
                "data": {"name": "Records"},
            }
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return incomplete

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(context),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
        context_blocks=[
            {
                "label": "Report Input Files",
                "value": '```\n[{"report_file_ref": "missing-file-id"}]\n```',
            }
        ],
    )

    result = organize.generate_organize_plan(prompt)

    assert len(calls) == 2
    assert result["actions"][0]["type"] == "needs_review"
    assert result["confidence"] == 0
    assert captured == []




# @matrix ai-report : references repair
@pytest.mark.unit
def test_generate_organize_report_repairs_invalid_action_references_once(monkeypatch):
    invalid = {
        "summary": "Record the invoice.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_task_sousa_doors_final_invoice",
                "type": "create_task",
                "data": {
                    "name": "Sousa Doors Final Invoice",
                    "page_action": (
                        "2,000.00 deposit paid on Jan 27, 2021 via check 1096. "
                        "Remaining $2,250.00 balance due by Feb 26, 2021."
                    ),
                },
            }
        ],
    }
    repaired = {
        "summary": "Record the invoice.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_sousa_doors_page",
                "type": "create_page",
                "data": {"name": "Sousa Doors"},
            },
            {
                "id": "create_task_sousa_doors_final_invoice",
                "type": "create_task",
                "data": {
                    "name": "Sousa Doors Final Invoice",
                    "page_action": "create_sousa_doors_page",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_page", "create_task", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][1]["data"]["page_action"] == "create_sousa_doors_page"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )




# @matrix ai-report : references repair
@pytest.mark.unit
def test_generate_organize_report_repairs_category_used_as_page_reference(monkeypatch):
    invalid = {
        "summary": "File the attendance form.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "attach_attendance",
                "type": "attach_file_to_page",
                "data": {
                    "page": "hash:abc123def456",
                    "page_name": "Homeschool",
                    "file": "hash:def456abc789",
                },
            }
        ],
    }
    repaired = {
        "summary": "File the attendance form.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "create_administration_page",
                "type": "create_page",
                "data": {
                    "name": "Administration",
                    "category": "hash:abc123def456",
                },
            },
            {
                "id": "attach_attendance",
                "type": "attach_file_to_page",
                "data": {
                    "page_action": "create_administration_page",
                    "file": "hash:def456abc789",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "abc123def456": {
                "id": "category-id",
                "kind": "category",
                "name": "Homeschool",
            },
            "def456abc789": {
                "id": "file-id",
                "kind": "file",
                "name": "attendanceform",
            },
        },
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert len(calls) == 2
    assert result["actions"][0]["data"]["category"] == "category-id"
    assert result["actions"][1]["data"]["page_action"] == (
        "create_administration_page"
    )
    assert result["actions"][1]["data"]["file"] == "file-id"
    assert "uses category 'Homeschool' as its page reference" in _prompt_context(
        calls[1], "Validation Error"
    )




# @matrix ai-report : repair required-data
@pytest.mark.unit
def test_generate_organize_report_repairs_invalid_action_data_shape(monkeypatch):
    invalid = {
        "summary": "Centralize family files.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_family_records_page",
                "type": "create_page",
                "data": {},
            },
            {
                "id": "move_file_richardson",
                "type": "move_file",
                "data": {
                    "file": "richardson-file-id",
                    "display_name": "Richardson Family Records.pdf",
                    "to_page_action": "create_family_records_page",
                },
            },
        ],
    }
    repaired = {
        "summary": "Centralize family files.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_family_records_page",
                "type": "create_page",
                "data": {"name": "Family Records"},
            },
            {
                "id": "move_file_richardson",
                "type": "move_file",
                "data": {
                    "file": "richardson-file-id",
                    "display_name": "Richardson Family Records.pdf",
                    "from_page": "richardson-source-page-id",
                    "from_page_name": "Richardson Records",
                    "to_page_action": "create_family_records_page",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    captured_repairs = []
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured_repairs.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_page", "move_file", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="ask report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["data"]["name"] == "Family Records"
    assert result["actions"][1]["data"]["from_page"] == "richardson-source-page-id"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    assert captured_repairs == []




# @matrix ai-report : add-category repair required-data
@pytest.mark.unit
def test_generate_organize_report_repairs_missing_add_category_target(monkeypatch):
    invalid = {
        "summary": "Add Sheik Orthodontics to Lucy.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "add_sheik_ortho_to_lucy",
                "type": "add_category",
                "data": {
                    "page": "lucy-page-id",
                    "page_name": "Lucy",
                    "category_name": "Sheik Orthodontics",
                },
            }
        ],
    }
    repaired = {
        "summary": "Add Sheik Orthodontics to Lucy.",
        "confidence": 0.7,
        "issues": [
            (
                "The Sheik Orthodontics category could not be identified from "
                "the proposal."
            )
        ],
        "actions": [
            {
                "id": "review_sheik_ortho_category",
                "type": "needs_review",
                "data": {
                    "note": (
                        "Choose the Sheik Orthodontics category before adding "
                        "it to Lucy."
                    ),
                    "questions": [
                        "Which existing category should be added to Lucy?",
                    ],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("add_category", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["type"] == "needs_review"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )




# @matrix ai-report : submission validate
@pytest.mark.unit
def test_generate_organize_plan_leaves_form_submission_for_completion(monkeypatch):
    invalid = {
        "summary": "Create a pharmacy page.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_cvs_pharmacy",
                "type": "create_page",
                "data": {
                    "name": "CVS Pharmacy",
                    "form": "business-form-id",
                    "form_name": "Business",
                },
            }
        ],
    }
    repaired = {
        "summary": "Create a pharmacy page.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_cvs_pharmacy",
                "type": "create_page",
                "data": {
                    "name": "CVS Pharmacy",
                    "form": "business-form-id",
                    "form_name": "Business",
                    "submission": {
                        "input-business-name": "CVS Pharmacy",
                    },
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert "submission" not in result["actions"][0]["data"]
    assert len(calls) == 1




# @matrix ai-report : capture empty-form repair
@pytest.mark.unit
def test_generate_organize_report_repairs_empty_form_schema_without_capture(monkeypatch):
    invalid = {
        "summary": "Create a record form.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "record_form",
                "type": "create_form",
                "data": {
                    "name": "Record Form",
                    "form_type": "page",
                    "schema": [],
                },
            }
        ],
    }
    repaired = {
        "summary": "Create a record form.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "record_form_review",
                "type": "needs_review",
                "data": {
                    "note": "No useful structured fields were identified.",
                    "questions": ["What fields should the form collect?"],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    captured_repairs = []
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured_repairs.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_form", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["type"] == "needs_review"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    assert 'get_guidelines("page_form")' in calls[1].preview()
    assert "Do not merely claim a schema was corrected" in calls[1].preview()
    assert "Do not replace a form action with needs_review merely" in (
        calls[1].preview()
    )
    assert captured_repairs == []




# @matrix ai-report : deterministic-repair schema-field-id
@pytest.mark.unit
def test_generate_organize_report_repairs_create_form_field_missing_id(monkeypatch):
    invalid = {
        "summary": "Create an orthodontist form.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_orthodontist_form",
                "type": "create_form",
                "data": {
                    "name": "Orthodontist",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-practice-name",
                            "type": "input",
                            "title": "Practice Name",
                        },
                        {
                            "type": "textarea",
                            "title": "Treatment Notes",
                        },
                    ],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_form", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    fields = result["actions"][0]["data"]["schema"]
    assert [field["id"] for field in fields] == [
        "input-practice-name",
        "textarea-treatment-notes",
    ]
    assert fields[0]["input"] == "text"
    assert len(calls) == 1




# @matrix ai-report form-schema : deterministic-repair schema-update
@pytest.mark.unit
def test_generate_organize_report_completes_additive_schema_field(monkeypatch):
    proposal = {
        "summary": "Add a payment reference field.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "add_payment_reference",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {
                            "op": "add_field",
                            "field": {
                                "type": "input",
                                "label": "Payment Reference",
                            },
                        }
                    ],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return proposal

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("update_form_schema", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    field = result["actions"][0]["data"]["operations"][0]["field"]
    assert field == {
        "id": "input-payment-reference",
        "type": "input",
        "input": "text",
        "label": "Payment Reference",
        "title": "Payment Reference",
    }
    assert len(calls) == 1




# @matrix ai-report : deterministic-repair form-type
# @pair form-schema:form-type
@pytest.mark.unit
def test_generate_organize_report_infers_create_form_type_from_usage(monkeypatch):
    proposal = {
        "summary": "Propose a record category and form.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "create_record_form",
                "type": "create_form",
                "data": {
                    "name": "Record Form",
                    "schema": [
                        {
                            "id": "textarea-notes",
                            "type": "textarea",
                            "title": "Notes",
                        }
                    ],
                },
            },
            {
                "id": "create_record_category",
                "type": "create_category",
                "data": {
                    "name": "Records",
                    "form_action": "create_record_form",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return proposal

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_form", "create_category", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["data"]["form_type"] == "page"
    assert len(calls) == 1




# @matrix ai-report : deterministic-repair page-form references
@pytest.mark.unit
def test_generate_organize_report_infers_unambiguous_add_form_reference(monkeypatch):
    proposal = {
        "summary": "Use the property-tax form on the existing Toft page.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "create_property_tax_form",
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
                "id": "create_payment_form",
                "type": "create_form",
                "data": {
                    "name": "Payment Record",
                    "form_type": "task",
                    "schema": [
                        {
                            "id": "date-paid-on",
                            "type": "date",
                            "title": "Paid On",
                        }
                    ],
                },
            },
            {
                "id": "add_form_to_toft",
                "type": "add_form_to_page",
                "display_label": "Apply Property Tax Form to Toft Property Tax Page",
                "data": {"page": "toft-property-tax-page"},
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return proposal

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_form", "add_form_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][2]["data"] == {
        "page": "toft-property-tax-page",
        "form_action": "create_property_tax_form",
    }
    assert "form_action" not in proposal["actions"][2]["data"]
    assert len(calls) == 1




# @matrix ai-report : fallback needs-review page-form per-action-fallback references
@pytest.mark.unit
def test_generate_organize_report_reviews_ambiguous_missing_add_form_reference(
    monkeypatch,
):
    invalid = {
        "summary": "Prepare the property-tax records.",
        "confidence": 0.6,
        "issues": [],
        "actions": [
            {
                "id": "create_property_tax_form",
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
                "id": "create_property_summary_form",
                "type": "create_form",
                "data": {
                    "name": "Property Summary",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "textarea-notes",
                            "type": "textarea",
                            "title": "Notes",
                        }
                    ],
                },
            },
            {
                "id": "add_form_to_toft",
                "type": "add_form_to_page",
                "display_label": "Apply a Form to Toft Property Tax Page",
                "data": {"page": "toft-property-tax-page"},
            },
            {
                "id": "keep_source_summary",
                "type": "skip",
                "data": {"note": "The source summary is already retained."},
            },
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )
    prompt = SimpleNamespace(
        allowed_actions=(
            "create_form",
            "add_form_to_page",
            "skip",
            "needs_review",
        ),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["type"] for action in result["actions"]] == [
        "create_form",
        "create_form",
        "needs_review",
        "skip",
    ]
    review = result["actions"][2]
    assert review["id"] == "add_form_to_toft"
    assert review["display_label"] == "Apply a Form to Toft Property Tax Page"
    assert review["data"]["questions"] == [
        "Which existing or proposed form should this action use?"
    ]
    assert "workspace reference was unclear" in result["issues"][-1]
    assert result["summary"] == invalid["summary"]
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    repair_text = calls[1].preview()
    assert "add_form_to_page actions must include both" in repair_text
    assert "data.form/data.form_action" in repair_text
    assert captured == []




# @matrix ai-report : needs-review per-action-fallback references
@pytest.mark.unit
def test_generate_organize_report_reviews_unresolved_references_after_failed_repair(
    monkeypatch,
):
    invalid = {
        "summary": "Record the legal payment.",
        "confidence": 0.6,
        "issues": [],
        "actions": [
            {
                "id": "keep_summary",
                "type": "skip",
                "data": {"note": "The source file is already summarized."},
            },
            {
                "id": "create_task_legal_payment",
                "type": "create_task",
                "data": {
                    "name": "Legal Retainer Payment",
                    "page_action": (
                        "$1,500.00 credit card transaction for legal "
                        "representation retainer."
                    ),
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_task", "skip", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["type"] for action in result["actions"]] == [
        "skip",
        "needs_review",
    ]
    review = result["actions"][1]
    assert review["display_label"] == "Legal Retainer Payment"
    assert "could not be linked safely" in review["reason"]
    assert "needs review" in result["issues"][-1]
    assert len(calls) == 2
    assert "Do not mention validation errors" in calls[1].preview()




# @matrix ai-report : malformed-data needs-review per-action-fallback
@pytest.mark.unit
def test_generate_organize_report_downgrades_malformed_action_after_failed_repair(
    monkeypatch,
):
    invalid = {
        "summary": "Create a divorce form.",
        "confidence": 0.5,
        "actions": [
            {
                "id": "create_divorce_form",
                "type": "create_form",
                "data": {
                    "name": "Divorce",
                    "schema": [{"type": "textarea", "title": "Notes"}],
                },
            }
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_form", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["summary"] == "Create a divorce form."
    assert result["confidence"] == 0.5
    assert [action["type"] for action in result["actions"]] == ["needs_review"]
    assert result["actions"][0]["display_label"] == "Divorce"
    assert result["actions"][0]["data"]["questions"] == [
        "What exact workspace record and values should this action use?"
    ]
    assert "Divorce needs review because its action data was incomplete." in result[
        "issues"
    ]
    assert len(calls) == 2
    assert captured == []




# @matrix ai-report : needs-review per-action-fallback references
@pytest.mark.unit
def test_generate_organize_report_downgrades_missing_category_without_sentry_capture(
    monkeypatch,
):
    invalid = {
        "summary": "Organize the comic book drawer plans.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_comic_drawers_page",
                "type": "create_page",
                "display_label": "Create page for Comic Book Drawers Plan",
                "data": {"name": "Comic Book Drawers Plan"},
            },
            {
                "id": "add_comics_category_to_drawers",
                "type": "add_category",
                "display_label": "Add Comics category to Comic Book Drawers",
                "data": {
                    "completed": False,
                    "completed_on": None,
                    "due_date": None,
                    "note": None,
                    "page_action": "create_comic_drawers_page",
                    "questions": [],
                    "to_page": None,
                    "to_task": None,
                    "updates": [],
                },
            },
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "add_category", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["type"] for action in result["actions"]] == [
        "create_page",
        "needs_review",
    ]
    assert result["actions"][1]["id"] == "add_comics_category_to_drawers"
    assert result["actions"][1]["data"]["questions"] == [
        "Which existing or proposed category should this action use?"
    ]
    assert len(calls) == 2
    assert captured == []




# @matrix ai-report form-schema : proposal schema-update validation
@pytest.mark.unit
def test_validate_proposal_rejects_unsafe_schema_update_operations():
    proposal = {
        "summary": "Delete an existing form field.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "delete_payment_reference",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {"op": "delete_field", "schema_id": "input-reference"}
                    ],
                },
            }
        ],
    }

    with pytest.raises(exceptions.AIException, match="unsupported op"):
        organize.validate_proposal(proposal)




# @matrix ai-report : move-references proposal validation
@pytest.mark.unit
@pytest.mark.parametrize(
    ("action_type", "data", "missing"),
    [
        ("move_page", {"category": "medical"}, "page"),
        ("move_page", {"page": "eyes"}, "category"),
        ("move_task", {"page": "lucy-eyes"}, "task"),
        pytest.param(
            "move_task",
            {"task": "specialist-consultation"},
            "to_page",
            id="move_task-data3-page",
        ),
    ],
)
def test_validate_proposal_requires_move_entity_references(
    action_type,
    data,
    missing,
):
    proposal = {
        "summary": "Move an existing workspace record.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "move_record",
                "type": action_type,
                "data": data,
            }
        ],
    }

    with pytest.raises(exceptions.AIException, match=rf"requires data\.{missing}"):
        organize.validate_proposal(proposal)




# @matrix ai-report : canonical-target legacy-target proposal rename validation
@pytest.mark.unit
def test_validate_proposal_accepts_rename_and_move_task_target_aliases():
    proposal = {
        "summary": "Rename a page and consolidate its tasks.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "rename_page",
                "type": "rename_entity",
                "data": {"entity": "orthodontics-page", "name": "Teeth"},
            },
            {
                "id": "canonical_move",
                "type": "move_task",
                "data": {
                    "task": "invisalign-task",
                    "to_page": "orthodontics-page",
                },
            },
            {
                "id": "legacy_move",
                "type": "move_task",
                "data": {
                    "task": "sealants-task",
                    "page": "orthodontics-page",
                },
            },
        ],
    }

    assert organize.validate_proposal(proposal) == proposal

    for data, missing in (
        ({"name": "Teeth"}, "entity"),
        ({"entity": "orthodontics-page"}, "name"),
    ):
        invalid = copy.deepcopy(proposal)
        invalid["actions"] = [
            {"id": "rename_page", "type": "rename_entity", "data": data}
        ]
        with pytest.raises(
            exceptions.AIException,
            match=rf"rename_page \(rename_entity\) requires data\.{missing}",
        ):
            organize.validate_proposal(invalid)




# @matrix ai-report : create generate validate
@pytest.mark.unit
def test_generate_create_report_validates_non_empty_actions(monkeypatch):
    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(
            lambda prompt: {
                "summary": "No actions.",
                "confidence": 0.5,
                "actions": [],
            }
        ),
    )

    with pytest.raises(exceptions.AIException, match="at least one action"):
        create.generate_create_report(object())

    proposal = {
        "summary": "Create a page.",
        "confidence": 0.8,
        "actions": [{"type": "create_page", "data": {"name": "Generated"}}],
    }
    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(lambda prompt: proposal),
    )

    assert create.generate_create_report(object()) == proposal




# @matrix ai-report : explicit-task-identity proposal validation
@pytest.mark.unit
def test_validate_proposal_requires_completed_root_task_targets():
    with pytest.raises(
        exceptions.AIException,
        match="target an existing task only for a completed occurrence",
    ):
        organize.validate_proposal(
            {
                "summary": "Invalid active task target.",
                "actions": [
                    {
                        "id": "active_task",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": "prescriptions-page",
                            "task": "lisinopril-task",
                        },
                    }
                ],
            }
        )

    proposal = {
        "summary": "Record two occurrences of one prescription.",
        "actions": [
            {
                "id": "lisinopril_current",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": "prescriptions-page",
                    "completed_on": "2025-03-01",
                },
            },
            {
                "id": "lisinopril_prior",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": "prescriptions-page",
                    "task_action": "lisinopril_current",
                    "completed_on": "2024-03-01",
                },
            },
        ],
    }
    assert organize.validate_proposal(copy.deepcopy(proposal))["issues"] == []

    proposal["actions"].append(
        {
            "id": "lisinopril_chained",
            "type": "create_task",
            "data": {
                "name": "Lisinopril Prescription",
                "page": "prescriptions-page",
                "task_action": "lisinopril_prior",
                "completed": True,
            },
        }
    )
    with pytest.raises(
        exceptions.AIException,
        match="earlier untargeted completed create_task",
    ):
        organize.validate_proposal(proposal)


# @matrix ai-report : completed-task future-date proposal validation
@pytest.mark.unit
def test_validate_proposal_rejects_future_completed_dates(monkeypatch):
    monkeypatch.setattr(
        proposal_validation.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    proposal = {
        "summary": "Record a completed inspection.",
        "actions": [
            {
                "id": "inspection",
                "type": "create_task",
                "data": {
                    "name": "Hive Inspection",
                    "page": "hive-page",
                    "completed_on": "2026-09-01",
                },
            }
        ],
    }

    with pytest.raises(
        exceptions.AIException,
        match="completion date cannot be in the future",
    ):
        organize.validate_proposal(copy.deepcopy(proposal))

    proposal["actions"][0]["data"]["completed_on"] = "2026-08-31"
    assert organize.validate_proposal(proposal)["issues"] == []




# @matrix ai-report : dependencies proposal validation
@pytest.mark.unit
def test_validate_proposal_rejects_unknown_actions_and_bad_dependencies(monkeypatch):
    hash_lookups = []

    def fake_get_details_by_hash(hashes):
        hash_lookups.append(list(hashes))
        return {
            "abc123def456": {"id": "page-id"},
            "def456abc789": {"id": "file-id"},
        }

    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        fake_get_details_by_hash,
    )

    with pytest.raises(exceptions.AIException, match="Unknown organize action"):
        organize.validate_proposal(
            {"summary": "Nope", "confidence": 0.1, "actions": [{"type": "dance"}]}
        )

    with pytest.raises(exceptions.AIException, match="depends on unknown"):
        organize.validate_proposal(
            {
                "summary": "Bad dependency",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {
                            "name": "Bad Reference Page",
                            "category_action": "later",
                        },
                    },
                    {"id": "later", "type": "create_category", "data": {}},
                ],
            }
        )

    cleaned_dependencies = organize.validate_proposal(
        {
            "summary": "Bad explicit dependency note",
            "confidence": 0.5,
            "actions": [
                {"id": "page", "type": "create_page", "data": {"name": "Page"}},
                {
                    "id": "create_task_sousa_doors_final_invoice",
                    "type": "create_task",
                    "depends_on": [
                        "$page",
                        (
                            "2,000.00 deposit paid on Jan 27, 2021 via check 1096. "
                            "Remaining $2,250.00 balance due by Feb 26, 2021."
                        ),
                    ],
                    "data": {"name": "Sousa Doors Final Invoice"},
                },
            ],
        }
    )
    assert cleaned_dependencies["actions"][1]["depends_on"] == ["$page"]
    assert cleaned_dependencies["issues"] == []

    with pytest.raises(exceptions.AIException, match="not allowed"):
        organize.validate_proposal(
            {
                "summary": "Forbidden",
                "confidence": 0.1,
                "actions": [{"type": "create_category", "data": {}}],
            },
            allowed_actions={"skip", "needs_review"},
        )

    with pytest.raises(exceptions.AIException, match="issues"):
        organize.validate_proposal(
            {
                "summary": "Bad issues",
                "confidence": 0.1,
                "issues": "Nope",
                "actions": [],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"create_page\) requires data.name",
    ):
        organize.validate_proposal(
            {
                "summary": "Nameless page",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "create_morrissey_compton_page",
                        "type": "create_page",
                        "display_label": (
                            "Create Morrissey-Compton Educational Center Page"
                        ),
                        "data": {},
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"create_form\) requires at least one data.schema field",
    ):
        organize.validate_proposal(
            {
                "summary": "Blank form",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "empty_form",
                        "type": "create_form",
                        "data": {
                            "name": "Empty Form",
                            "form_type": "page",
                            "schema": [],
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"data.schema\[1\] requires title",
    ):
        organize.validate_proposal(
            {
                "summary": "Bad form field",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "bad_form",
                        "type": "create_form",
                        "data": {
                            "name": "Bad Form",
                            "form_type": "page",
                            "schema": [{"id": "input-name", "type": "input"}],
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        organize.validate_proposal(
            {
                "summary": "Page form without submission",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "cvs_pharmacy_page",
                        "type": "create_page",
                        "data": {
                            "name": "CVS Pharmacy",
                            "form_name": "Business",
                        },
                    },
                ],
            }
        )

    pending_submission = organize.validate_proposal(
        {
            "summary": "Page form with pending completion",
            "confidence": 0.8,
            "actions": [
                {
                    "id": "cvs_pharmacy_page",
                    "type": "create_page",
                    "data": {
                        "name": "CVS Pharmacy",
                        "form_name": "Business",
                    },
                },
            ],
        },
        allow_pending_submissions=True,
    )
    assert "submission" not in pending_submission["actions"][0]["data"]
    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        organize.validate_proposal(
            pending_submission,
            allow_pending_submissions=False,
        )

    empty_completed_submission = organize.validate_proposal(
        {
            "summary": "Page form with completed empty submission pass",
            "confidence": 0.8,
            "actions": [
                {
                    "id": "cvs_pharmacy_page",
                    "type": "create_page",
                    "data": {
                        "name": "CVS Pharmacy",
                        "form_name": "Business",
                        "submission": {},
                        "submission_empty_reason": (
                            "No submission fields were filled from the available evidence."
                        ),
                    },
                },
            ],
        },
        allow_pending_submissions=False,
    )
    assert empty_completed_submission["actions"][0]["data"][
        "submission_empty_reason"
    ] == "No submission fields were filled from the available evidence."

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        organize.validate_proposal(
            {
                "summary": "Task form with empty submission",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "screening_task",
                        "type": "create_task",
                        "data": {
                            "name": "Athletic Screening",
                            "page": "julie-page-id",
                            "form": "doctor-appointment-form-id",
                            "submission": {},
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"move_file\) requires exactly one source",
    ):
        organize.validate_proposal(
            {
                "summary": "Missing move source",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "family_records",
                        "type": "create_page",
                        "data": {"name": "Family Records"},
                    },
                    {
                        "id": "move_file_richardson",
                        "type": "move_file",
                        "data": {
                            "file": "richardson-file-id",
                            "display_name": "Richardson Family Records.pdf",
                            "to_page_action": "family_records",
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"add_category\) requires data.page",
    ):
        organize.validate_proposal(
            {
                "summary": "Missing page category add",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "add_records_category",
                        "type": "add_category",
                        "data": {"category": "records-category-id"},
                    },
                ],
            }
        )
    with pytest.raises(
        exceptions.AIException,
        match=r"update_submission_fields\) requires at least one data.updates row",
    ):
        organize.validate_proposal(
            {
                "summary": "Empty submission update",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "empty_submission_update",
                        "type": "update_submission_fields",
                        "data": {"updates": []},
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"data.updates\[1\] requires exactly one page or task",
    ):
        organize.validate_proposal(
            {
                "summary": "Malformed submission update",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "bad_submission_update",
                        "type": "update_submission_fields",
                        "data": {
                            "updates": [
                                {
                                    "schema_id": "select-rank",
                                    "new_value": "white-belt",
                                }
                            ]
                        },
                    },
                ],
            }
        )

    recoverable_file_reference_proposal = organize.validate_proposal(
        {
            "summary": "Recoverable file reference problems",
            "confidence": 0.1,
            "issues": [
                "Some file references were readable labels instead of executable refs."
            ],
            "actions": [
                {
                    "id": "create_pettis_remodeling_design_page",
                    "type": "create_page",
                    "data": {"name": "Pettis Remodeling Design"},
                },
                {
                    "id": "attachment",
                    "type": "attach_file_to_page",
                    "data": {
                        "page": "existing-page",
                        "file_name": "Pettis Proposal",
                    },
                },
                {
                    "id": "completed_task_display_file",
                    "type": "create_task",
                    "data": {
                        "page": "existing-page",
                        "completed_on": "2023-06-24",
                        "file_label": "Pettis Proposal",
                    },
                },
                {
                    "id": "completed_task_no_file",
                    "type": "create_task",
                    "display_label": "ToDo's? All Done! Service Agreement",
                    "data": {
                        "name": "Robbyn Willebeek-LeMair PM Agreement",
                        "page": "$create_pettis_remodeling_design_page",
                        "completed_on": "2014-06-09",
                        "model": "project-management-design-model",
                    },
                },
            ],
        }
    )
    assert recoverable_file_reference_proposal["summary"] == (
        "Recoverable file reference problems"
    )
    assert recoverable_file_reference_proposal["issues"] == [
        "Some file references were readable labels instead of executable refs."
    ]

    with pytest.raises(exceptions.AIException, match="attach_file_to_task"):
        organize.validate_proposal(
            {
                "summary": "Invalid task attachment shape",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "completed_task_with_file",
                        "type": "create_task",
                        "data": {
                            "page": "existing-page",
                            "completed_on": "2023-06-24",
                            "file": "registration.pdf",
                        },
                    },
                ],
            }
        )

    proposal = organize.validate_proposal(
        {
            "summary": "OK",
            "confidence": 0.9,
            "actions": [
                {
                    "id": "form",
                    "type": "create_form",
                    "data": {
                        "name": "Record Form",
                        "form_type": "page",
                        "schema": [
                            {
                                "id": "input-name",
                                "type": "input",
                                "input": "text",
                                "title": "Name",
                            }
                        ],
                    },
                },
                {
                    "id": "category",
                    "type": "create_category",
                    "data": {"form_action": "form"},
                },
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {"page": "existing-page"},
                },
                {
                    "id": "completed_task",
                    "type": "create_task",
                    "data": {
                        "page": "existing-page",
                        "completed_on": "2023-06-24",
                    },
                },
                {
                    "id": "completed_task_attachment",
                    "type": "attach_file_to_task",
                    "data": {
                        "task_action": "completed_task",
                        "file": "registration.pdf",
                    },
                },
            ],
        }
    )
    assert proposal["summary"] == "OK"
    assert proposal["issues"] == []

    normalized = organize.validate_proposal(
        {
            "summary": "Normalize hash refs",
            "confidence": 0.9,
            "actions": [
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {
                        "page": "hash:abc123def456",
                        "description": "Unknown hash:000000000000 stays visible.",
                        "submission": {
                            "input-abc123def456": "Schema ids are not references."
                        },
                    },
                },
                {
                    "id": "attach_task_file",
                    "type": "attach_file_to_task",
                    "data": {
                        "task_action": "task",
                        "file": "hash:def456abc789",
                    },
                },
            ],
        }
    )

    assert set(hash_lookups[0]) == {
        "abc123def456",
        "def456abc789",
        "000000000000",
    }
    assert normalized["actions"][0]["data"]["page"] == "page-id"
    assert normalized["actions"][1]["data"]["file"] == "file-id"
    assert normalized["actions"][0]["data"]["description"] == (
        "Unknown hash:000000000000 stays visible."
    )
    assert normalized["actions"][0]["data"]["submission"] == {
        "input-abc123def456": "Schema ids are not references."
    }




# @matrix ai-report : action-reference-namespace proposal submission validation
@pytest.mark.unit
def test_validate_proposal_treats_action_like_submission_fields_as_content():
    proposal = {
        "summary": "Record contract and compensation details.",
        "issues": [],
        "actions": [
            {
                "id": "contracts_page",
                "type": "create_page",
                "data": {"name": "Contracts"},
            },
            {
                "id": "contract_task",
                "type": "create_task",
                "data": {
                    "name": "Nate Patrin 2021 contract",
                    "page_action": "contracts_page",
                    "submission": {
                        "action": (
                            "4,175.00 in nonemployee compensation. No federal "
                            "or state income tax withholding was reported."
                        ),
                        "payment_action": (
                            "2500 total payment for 100 capsule album reviews."
                        ),
                    },
                },
            },
        ],
    }

    validated = organize.validate_proposal(copy.deepcopy(proposal))

    assert validated["actions"][1]["data"]["submission"] == proposal["actions"][1][
        "data"
    ]["submission"]




# @matrix ai-report : file-placement proposal validation
@pytest.mark.unit
def test_validate_proposal_requires_every_report_file_attachment(monkeypatch):
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "aaaaaaaaaaaa": {"id": "first-file-id", "kind": "file"},
            "bbbbbbbbbbbb": {"id": "second-file-id", "kind": "file"},
        },
    )
    proposal = {
        "summary": "Attach one of two files.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "attach_first",
                "type": "attach_file_to_page",
                "data": {
                    "page": "existing-page",
                    "file": "hash:aaaaaaaaaaaa",
                },
            },
            {
                "id": "unresolved_second",
                "type": "attach_file_to_page",
                "data": {"file": "hash:bbbbbbbbbbbb"},
            },
        ],
    }

    with pytest.raises(
        exceptions.AIException,
        match=r"Missing report_file_ref values: hash:bbbbbbbbbbbb",
    ):
        organize.validate_proposal(
            proposal,
            required_file_refs=("hash:aaaaaaaaaaaa", "hash:bbbbbbbbbbbb"),
        )

    proposal["actions"][1]["data"]["task"] = "existing-task"
    proposal["actions"][1]["type"] = "attach_file_to_task"

    validated = organize.validate_proposal(
        proposal,
        required_file_refs=("hash:aaaaaaaaaaaa", "hash:bbbbbbbbbbbb"),
    )
    assert validated["actions"][0]["data"]["file"] == "first-file-id"
    assert validated["actions"][1]["data"]["file"] == "second-file-id"


# @matrix ai-report : file-summary proposal validation
@pytest.mark.unit
def test_validate_proposal_requires_external_file_summaries(monkeypatch):
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "aaaaaaaaaaaa": {"id": "first-file-id", "kind": "file"},
            "bbbbbbbbbbbb": {"id": "second-file-id", "kind": "file"},
        },
    )
    proposal = {
        "summary": "Attach and summarize two files.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "attach_first",
                "type": "attach_file_to_page",
                "data": {"page": "existing-page", "file": "hash:aaaaaaaaaaaa"},
            },
            {
                "id": "attach_second",
                "type": "attach_file_to_task",
                "data": {"task": "existing-task", "file": "hash:bbbbbbbbbbbb"},
            },
        ],
    }
    required = ("hash:aaaaaaaaaaaa", "hash:bbbbbbbbbbbb")

    with pytest.raises(
        exceptions.AIException,
        match=r"Missing report_file_ref values: hash:aaaaaaaaaaaa, hash:bbbbbbbbbbbb",
    ):
        organize.validate_proposal(
            copy.deepcopy(proposal),
            required_file_refs=required,
            require_file_summaries=True,
        )

    proposal["actions"].extend(
        [
            {
                "id": "summarize_first",
                "type": "summarize_file",
                "data": {
                    "file": "hash:aaaaaaaaaaaa",
                    "summary": "The first source concerns Avery's contact details.",
                    "retrieval_terms": ["Avery", "contacts"],
                    "search": True,
                },
            },
            {
                "id": "summarize_second",
                "type": "summarize_file",
                "data": {
                    "file": "hash:bbbbbbbbbbbb",
                    "summary": "The second source records apiary maintenance.",
                    "retrieval_terms": ["apiary", "maintenance"],
                    "search": True,
                },
            },
        ]
    )

    validated = organize.validate_proposal(
        copy.deepcopy(proposal),
        required_file_refs=required,
        require_file_summaries=True,
    )
    assert validated["actions"][2]["data"]["file"] == "first-file-id"
    assert validated["actions"][3]["data"]["retrieval_terms"] == [
        "apiary",
        "maintenance",
    ]

    missing_terms = copy.deepcopy(proposal)
    missing_terms["actions"][2]["data"].pop("retrieval_terms")
    with pytest.raises(exceptions.AIException, match="exactly two distinct"):
        organize.validate_proposal(
            missing_terms,
            required_file_refs=required,
            require_file_summaries=True,
        )

    duplicate = copy.deepcopy(proposal)
    duplicate["actions"].append(
        {
            **copy.deepcopy(duplicate["actions"][3]),
            "id": "summarize_second_again",
        }
    )
    with pytest.raises(exceptions.AIException, match="exactly one summary"):
        organize.validate_proposal(
            duplicate,
            required_file_refs=required,
            require_file_summaries=True,
        )

    unexpected = copy.deepcopy(proposal)
    unexpected["actions"].append(
        {
            "id": "summarize_other",
            "type": "summarize_file",
            "data": {
                "file": "other-file-id",
                "summary": "This file is not part of the report.",
                "retrieval_terms": ["other", "unrelated"],
            },
        }
    )
    with pytest.raises(exceptions.AIException, match="must target report input"):
        organize.validate_proposal(
            unexpected,
            required_file_refs=required,
            require_file_summaries=True,
        )




# @matrix ai-report : dependencies proposal skip
@pytest.mark.unit
def test_skip_proposal_actions_marks_dependencies():
    proposal = {
        "summary": "Create then attach.",
        "confidence": 0.9,
        "actions": [
            {"id": "category", "type": "create_category", "data": {}},
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "Scanned Page", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file_to_page",
                "data": {"page_action": "page", "file": "scan.pdf"},
            },
            {"id": "other", "type": "needs_review", "data": {}},
        ],
    }

    skipped = organize.skip_proposal_actions(proposal, 0)

    assert skipped == [1, 2, 3]
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]




# @matrix ai-report : dependencies grouped-display proposal restore skip
@pytest.mark.unit
def test_toggle_proposal_action_skip_restores_dependencies():
    proposal = {
        "summary": "Create then attach.",
        "confidence": 0.9,
        "actions": [
            {"id": "category", "type": "create_category", "data": {}},
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "Scanned Page", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file_to_page",
                "data": {"page_action": "page", "file": "scan.pdf"},
            },
            {"id": "other", "type": "needs_review", "data": {}},
        ],
    }

    skipped = organize.toggle_proposal_action_skip(proposal, 0)

    assert skipped == {"changed": [1, 2, 3], "skipped": [1, 2, 3]}
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]

    restored = organize.toggle_proposal_action_skip(proposal, 0)

    assert restored == {"changed": [1, 2, 3], "skipped": []}
    assert [action.get("skip") for action in proposal["actions"]] == [
        None,
        None,
        None,
        None,
    ]

    grouped = organize.toggle_proposal_action_indexes(proposal, 1, [0, 1])

    assert grouped == {"changed": [1, 2, 3], "skipped": [1, 2, 3]}
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]
