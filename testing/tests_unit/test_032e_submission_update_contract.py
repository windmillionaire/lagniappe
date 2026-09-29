"""Cohesive updates use the same selected contract for native and external plans."""

from types import SimpleNamespace

import pytest
from google.genai import types

from lagniappe.core.tools.ai.external.validation import _schema_errors
from lagniappe.core.tools.ai.function_definitions.get_guidelines import (
    execute_external_get_guidelines,
)
from lagniappe.core.tools.ai.reporting.contracts.schema import (
    external_report_proposal_response_schema,
    report_proposal_response_schema,
)

pytestmark = pytest.mark.unit


# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @matrix agent-api ai-report : external-schema proposal-contract structured-output
@pytest.mark.parametrize(
    "kind", ["update_task", "update_page", "update_project", "update_model_task", "update_file"]
)
def test_cohesive_update_contract_requires_target_and_nonempty_known_patch(kind):
    schema = external_report_proposal_response_schema([kind])
    proposal = {
        "summary": "Edit",
        "confidence": 1,
        "actions": [
            {
                "id": "edit",
                "type": kind,
                "data": {
                    "entity": "hash:012345abcdef",
                    "changes": {"name": "Updated"},
                },
            }
        ],
    }
    assert not _schema_errors(proposal, schema, schema, "$.proposal")

    valid_data = proposal["actions"][0]["data"]
    for invalid_data in (
        {"entity": valid_data["entity"], "changes": {}},
        {"entity": valid_data["entity"], "changes": {"invented": True}},
        {"changes": {"name": "Updated"}},
    ):
        proposal["actions"][0]["data"] = invalid_data
        assert _schema_errors(proposal, schema, schema, "$.proposal")

    proposal["actions"][0]["data"] = valid_data
    types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=report_proposal_response_schema([kind]),
    )


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai-report submission : validation preservation
@pytest.mark.parametrize("kind", ["update_task", "update_page"])
def test_selected_patch_guidance_uses_cohesive_contract(kind):
    result = execute_external_get_guidelines(
        {"task": "form_autofill", "actions": [kind]}, SimpleNamespace()
    )
    assert "error" not in result
    assert "data.entity" in result["guidelines"]
    assert "data.changes.submission" in result["guidelines"]
    assert "update_form_values" not in result["guidelines"]


# @source lagniappe/core/tools/ai/reporting/display/actions/forms.py::schema_details
# @matrix ai-report form-schema : details proposal
def test_schema_review_displays_exact_form_and_change_count():
    from lagniappe.core.tools.ai.reporting.display.actions.forms import schema_details

    fields = []
    details = SimpleNamespace(
        reference=lambda label, data, field: fields.append((label, data[field])),
        add=lambda label, value: fields.append((label, value)),
    )
    schema_details(
        details,
        {
            "form": "hash:012345abcdef",
            "operations": [{"op": "add_field"}, {"op": "remove_field"}],
        },
    )
    assert fields == [
        ("Form", "hash:012345abcdef"),
        ("Updates", "2 schema changes"),
    ]
