"""Structured-output schemas for AI report proposals."""

from ...autofill import submission_response_schema
from ..schedules import task_schedule_response_schema
from .actions import ACTION_ORDER, REPORT_ACTION_DATA_CONTRACTS


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason nested schema contract is asserted through the public response schema
def _report_schema_field_response_schema():
    """Return an explicit provider schema for executable form fields."""
    option_schema = {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "label": {"type": "string"},
        },
        "required": ["value", "label"],
        "propertyOrdering": ["value", "label"],
        "additionalProperties": False,
    }
    column_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string"},
            "title": {"type": "string"},
            "input": {"type": "string"},
            "placeholder": {"type": "string"},
            "required": {"type": "boolean"},
            "location": {"type": "string"},
        },
        "required": ["id", "type", "title"],
        "propertyOrdering": [
            "id",
            "type",
            "title",
            "input",
            "placeholder",
            "required",
            "location",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string"},
            "title": {"type": "string"},
            "label": {"type": "string"},
            "input": {"type": "string"},
            "placeholder": {"type": "string"},
            "required": {"type": "boolean"},
            "multiple": {"type": "boolean"},
            "location": {"type": "string"},
            "options": {"type": "array", "items": option_schema},
            "columns": {"type": "array", "items": column_schema},
            "html": {"type": "string"},
            "address": {"type": "string"},
            "icon": {"type": "string"},
            "kind": {"type": "string"},
        },
        "required": ["id", "type", "title"],
        "propertyOrdering": [
            "id",
            "type",
            "title",
            "label",
            "input",
            "placeholder",
            "required",
            "multiple",
            "location",
            "options",
            "columns",
            "html",
            "address",
            "icon",
            "kind",
        ],
        "additionalProperties": False,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason nested operation contract is asserted through the public response schema
def _report_schema_operation_response_schema():
    """Return typed provider variants for bounded additive schema operations."""
    add_field = {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["add_field"]},
            "field": _report_schema_field_response_schema(),
        },
        "required": ["op", "field"],
        "propertyOrdering": ["op", "field"],
        "additionalProperties": False,
    }
    add_select_option = {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["add_select_option"]},
            "schema_id": {"type": "string"},
            "option": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["value", "label"],
                "propertyOrdering": ["value", "label"],
                "additionalProperties": False,
            },
        },
        "required": ["op", "schema_id", "option"],
        "propertyOrdering": ["op", "schema_id", "option"],
        "additionalProperties": False,
    }
    return {
        "anyOf": [add_field, add_select_option],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason nested update contract is asserted through the public response schema
def _report_submission_update_response_schema():
    """Return the provider schema for one exact submission field update."""
    return {
        "type": "object",
        "properties": {
            "page": {"type": "string"},
            "page_action": {"type": "string"},
            "task": {"type": "string"},
            "task_action": {"type": "string"},
            "schema_id": {"type": "string"},
            "field_id": {"type": "string"},
            # Form fields accept heterogeneous JSON values. Declaring the key
            # while leaving its value schema open prevents structured-output
            # providers from collapsing the entire update row to {}.
            "new_value": {},
        },
        "required": ["schema_id", "new_value"],
        "propertyOrdering": [
            "page",
            "page_action",
            "task",
            "task_action",
            "schema_id",
            "field_id",
            "new_value",
        ],
        "additionalProperties": False,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason action data variants are asserted through the public response schema
def _report_action_data_properties():
    """Return the complete field vocabulary used by typed action variants."""
    return {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "form_type": {"type": "string", "enum": ["page", "task"]},
        "schema": {
            "type": "array",
            "items": _report_schema_field_response_schema(),
            "minItems": 1,
        },
        "category": {"type": "string"},
        "category_action": {"type": "string"},
        "category_name": {"type": "string"},
        "form": {"type": "string"},
        "form_action": {"type": "string"},
        "form_name": {"type": "string"},
        "page": {"type": "string"},
        "page_action": {"type": "string"},
        "page_name": {"type": "string"},
        "entity": {"type": "string"},
        "entity_action": {"type": "string"},
        "entity_name": {"type": "string"},
        "task": {"type": "string"},
        "task_action": {"type": "string"},
        "task_name": {"type": "string"},
        "project": {"type": "string"},
        "project_action": {"type": "string"},
        "project_name": {"type": "string"},
        "model": {"type": "string"},
        "model_action": {"type": "string"},
        "model_name": {"type": "string"},
        "file": {"type": "string"},
        "display_name": {"type": "string"},
        "from_page": {"type": "string"},
        "from_page_action": {"type": "string"},
        "from_task": {"type": "string"},
        "from_task_action": {"type": "string"},
        "to_page": {"type": "string"},
        "to_page_action": {"type": "string"},
        "to_task": {"type": "string"},
        "to_task_action": {"type": "string"},
        "operations": {
            "type": "array",
            "items": _report_schema_operation_response_schema(),
            "minItems": 1,
        },
        "updates": {
            "type": "array",
            "items": _report_submission_update_response_schema(),
            "minItems": 1,
        },
        "submission": submission_response_schema(),
        "submission_empty_reason": {"type": "string"},
        "document": {"type": "string"},
        "due_date": {"type": "string"},
        "schedule": task_schedule_response_schema(),
        "completed": {"type": "boolean"},
        "completed_on": {"type": "string"},
        "note": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "search": {"type": "boolean"},
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason per-action required fields are asserted through the public response schema
def _report_action_data_response_schema(action_type, include_submission_fields):
    """Return only the fields and requirements valid for one action type."""
    contract = REPORT_ACTION_DATA_CONTRACTS[action_type]
    vocabulary = _report_action_data_properties()
    omitted = (
        set()
        if include_submission_fields
        else {"submission", "submission_empty_reason", "updates"}
    )
    fields = [field for field in contract["fields"] if field not in omitted]
    required = [field for field in contract.get("required", ()) if field in fields]
    schema = {
        "type": "object",
        "properties": {field: vocabulary[field] for field in fields},
        "propertyOrdering": fields,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    # Cross-field reference alternatives remain an application validation
    # concern. Gemini requires ``anyOf`` to be the only field at its schema
    # node, which makes composing those alternatives with this typed object
    # contract provider-invalid.
    return schema


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason action variants are asserted through the public response schema
def _report_action_response_schema(action_type, include_submission_fields):
    """Return one discriminated action variant with its exact data contract."""
    properties = {
        "id": {"type": "string"},
        "type": {"type": "string", "enum": [action_type]},
        "display_label": {"type": "string"},
        "reason": {"type": "string"},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "data": _report_action_data_response_schema(
            action_type,
            include_submission_fields,
        ),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["type", "data"],
        "propertyOrdering": list(properties),
        "additionalProperties": False,
    }


# @testable true
# @tests tests_unit/test_020d_ai_report_prompts.py::test_report_prompts_attach_provider_json_schema
# @tests tests_unit/test_020d_ai_report_prompts.py::test_report_response_schema_uses_provider_compatible_any_of_nodes
# @matrix ai-report : allowed-actions provider-validation schema structured-output
def report_proposal_response_schema(
    allowed_actions=None,
    *,
    allow_answer_html=False,
    require_issues=False,
    include_submission_fields=True,
):
    """Return typed provider JSON variants for report proposal responses."""
    action_types = tuple(allowed_actions or ACTION_ORDER)
    unknown_actions = [
        action for action in action_types if action not in REPORT_ACTION_DATA_CONTRACTS
    ]
    if unknown_actions:
        raise ValueError(
            "Missing report response schema for action types: "
            f"{', '.join(unknown_actions)}"
        )

    properties = {
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
        },
        "actions": {
            "type": "array",
            "items": {
                "anyOf": [
                    _report_action_response_schema(
                        action_type,
                        include_submission_fields,
                    )
                    for action_type in action_types
                ]
            },
        },
    }
    if allow_answer_html:
        properties["answer_html"] = {"type": "string"}

    required = ["summary", "confidence"]
    if require_issues:
        required.append("issues")
    required.append("actions")
    property_ordering = ["summary"]
    if allow_answer_html:
        property_ordering.append("answer_html")
    property_ordering.extend(["confidence", "issues", "actions"])

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "propertyOrdering": property_ordering,
        "additionalProperties": False,
    }
