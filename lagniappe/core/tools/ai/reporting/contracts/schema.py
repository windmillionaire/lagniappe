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
            "content_markdown": {"type": "string"},
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
            "content_markdown",
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
    """Return typed provider variants for exact-ID schema operations."""
    patch = {
        key: {**value, **({"nullable": True} if key not in {"type", "title"} else {})}
        for key, value in _report_schema_field_response_schema()["properties"].items()
        if key not in {"id", "content_markdown"}
    }
    patch.update(
        visibility={"type": "array", "items": {"type": "object"}, "nullable": True},
        status={"type": "array", "items": {"type": "object"}, "nullable": True},
        layout={"type": "string", "nullable": True},
        checked={"type": "boolean", "nullable": True},
    )
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
        "anyOf": [
            add_field,
            add_select_option,
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["update_field"]},
                    "schema_id": {"type": "string"},
                    "patch": {
                        "type": "object",
                        "properties": patch,
                        "minProperties": 1,
                        "additionalProperties": False,
                    },
                },
                "required": ["op", "schema_id", "patch"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["remove_field"]},
                    "schema_id": {"type": "string"},
                },
                "required": ["op", "schema_id"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["reorder_fields"]},
                    "ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["op", "ids"],
                "additionalProperties": False,
            },
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason conversion envelopes are asserted through the public response schema
def _report_conversion_response_schema():
    """Keep Todo item objects typed while allowing exact dynamic table columns."""
    identity = {
        "entity": {"type": "string"},
        "schema_id": {"type": "string"},
        "source_fingerprint": {"type": "string"},
    }
    value = {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "minLength": 1},
                                "checked": {"type": "boolean"},
                            },
                            "required": ["text", "checked"],
                            "propertyOrdering": ["text", "checked"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["items"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "minItems": 1,
                        # Column IDs come from the runtime preview. An object
                        # with no declared properties can constrain Vertex to empty
                        # rows; preparation validates these open row values.
                        "items": {},
                        "description": "Rows must be objects keyed by exact destination column IDs; omit absent cells.",
                    },
                },
                "required": ["rows"],
                "additionalProperties": False,
            },
        ],
    }
    return {
        "anyOf": [
            {
                "type": "object",
                "properties": {**identity, outcome: schema},
                "required": [*identity, outcome],
                "additionalProperties": False,
            }
            for outcome, schema in (
                ("value", value),
                ("unresolved_reason", {"type": "string", "minLength": 1}),
            )
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @reason action data variants are asserted through the public response schema
def _report_action_data_properties():
    """Return the complete field vocabulary used by typed action variants."""
    action_reference = {
        "type": "string",
        "description": (
            "Exact id of an earlier action in this proposal that creates the "
            "referenced entity; not a workspace hash or entity id."
        ),
    }
    submission = submission_response_schema()
    submission["description"] = (
        "Form field values to submit on the Page or Task created by this action, "
        "keyed by the exact ids from the referenced Form schema. This creates a "
        "new submission with the entity; it is not a reference to an existing "
        "submission."
    )
    return {
        "changes": {"type": "object"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "form_type": {"type": "string", "enum": ["page", "task"]},
        "schema": {
            "type": "array",
            "items": _report_schema_field_response_schema(),
            "minItems": 1,
        },
        "category": {"type": "string"},
        "category_action": action_reference,
        "category_name": {"type": "string"},
        "form": {"type": "string"},
        "form_action": action_reference,
        "form_name": {"type": "string"},
        "page": {"type": "string"},
        "page_action": action_reference,
        "page_name": {"type": "string"},
        "entity": {"type": "string"},
        "entity_action": action_reference,
        "entity_name": {"type": "string"},
        "task": {"type": "string"},
        "task_action": action_reference,
        "task_name": {"type": "string"},
        "project": {"type": "string"},
        "project_action": action_reference,
        "project_name": {"type": "string"},
        "model": {"type": "string"},
        "model_action": action_reference,
        "model_name": {"type": "string"},
        "file": {"type": "string"},
        "display_name": {"type": "string"},
        "from_page": {"type": "string"},
        "from_page_action": action_reference,
        "from_task": {"type": "string"},
        "from_task_action": action_reference,
        "to_page": {"type": "string"},
        "to_page_action": action_reference,
        "to_task": {"type": "string"},
        "to_task_action": action_reference,
        "operations": {
            "type": "array",
            "items": _report_schema_operation_response_schema(),
            "minItems": 1,
        },
        "baseline": {"type": "string"},
        "scope_fingerprint": {"type": "string"},
        "conversions": {
            "type": "array",
            "items": _report_conversion_response_schema(),
        },
        "submission": submission,
        "submission_empty_reason": {
            "type": "string",
            "description": (
                "Why no Form values can be grounded when this action still needs "
                "to create an intentionally empty submission."
            ),
        },
        "document_markdown": {
            "type": "string",
            "description": "Markdown for the new document or requested addition only. append_page_document preserves existing content; the server prefixes trusted source/time attribution.",
        },
        "due_date": {"type": "string"},
        "schedule": task_schedule_response_schema(),
        "completed": {"type": "boolean"},
        "completed_on": {"type": "string"},
        "note": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "retrieval_terms": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 2,
        },
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
    if action_type in {"update_task", "update_model_task", "update_project", "update_page", "update_file"}:
        from lagniappe.core.tools.entity_patches import PATCH_FIELDS
        kind = {"update_task": "task", "update_model_task": "model", "update_project": "project", "update_page": "page", "update_file": "file"}[action_type]
        fields = {}
        for field in sorted(PATCH_FIELDS[kind]):
            if field in {"categories", "model_tasks"}:
                fields[field] = {"type": "array", "items": {"type": "string"}}
            else:
                fields[field] = {**vocabulary.get(field, {"type": "string"})}
                if field not in {"name", "page", "submission"}:
                    fields[field]["nullable"] = True
        schema["properties"]["changes"] = {"type": "object", "properties": fields, "minProperties": 1, "additionalProperties": False}
        schema["properties"]["entity"]["description"] = "Exact existing entity reference or $id of an earlier action. Omitted changes preserve values; null explicitly clears a supported field."


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
# @tests tests_unit/test_004l_form_schema_updates.py::test_report_conversion_schema_rejects_flattened_items
# @matrix ai-report : allowed-actions provider-validation schema structured-output
def report_proposal_response_schema(
    allowed_actions=None,
    *,
    allow_answer_html=False,
    require_issues=False,
    include_submission_fields=True,
):
    """Return typed provider JSON variants for report proposal responses."""
    action_types = tuple(ACTION_ORDER if allowed_actions is None else allowed_actions)
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
        "answer_markdown": {"type": "string"},
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


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @reason external required-group composition is asserted through the public transport schema
def _external_required_group_schema(fields):
    """Require at least one field from an external action reference group."""
    fields = tuple(fields)
    return {
        "description": f"At least one of {', '.join(fields)} is required.",
        "anyOf": [{"required": [field]} for field in fields],
    }


# @testable true
# @tests tests_unit/test_032d_external_guidance.py::test_external_schedule_schema_matches_repeating_schedule_requirements
# @matrix agent-api task-scheduling : periodic recurring scheduled structured-output validation
def external_task_schedule_response_schema():
    """Add conditional public requirements without changing the Gemini schema."""
    schema = _standard_json_schema(task_schedule_response_schema())
    schema["description"] = (
        "Repeating work only. A one-time reminder uses due_date without schedule. "
        "The kind selects the required interval or calendar fields below."
    )
    schema["allOf"] = [
        {
            "if": {"properties": {"kind": {"enum": ["recurring", "periodic"]}}},
            "then": {
                "required": ["interval", "unit"],
                "properties": {"interval": {"minimum": 1}},
            },
        },
        {
            "if": {"properties": {"kind": {"const": "periodic"}}},
            "then": {
                "required": ["description"],
                "properties": {"description": {"minLength": 1}},
            },
        },
        {
            "if": {"properties": {"kind": {"const": "scheduled"}}},
            "then": {"required": ["mode"]},
        },
        {
            "if": {
                "required": ["mode"],
                "properties": {
                    "kind": {"const": "scheduled"},
                    "mode": {"const": "weekly"},
                },
            },
            "then": {
                "required": ["days"],
                "properties": {
                    "days": {
                        "minItems": 1,
                        "items": {"minimum": 0, "maximum": 6},
                    }
                },
            },
        },
        {
            "if": {
                "required": ["mode"],
                "properties": {
                    "kind": {"const": "scheduled"},
                    "mode": {"enum": ["monthly", "yearly"]},
                },
            },
            "then": {
                "required": ["pattern_type", "description"],
                "properties": {"description": {"minLength": 1}},
                "allOf": [
                    {
                        "if": {
                            "required": ["pattern_type"],
                            "properties": {"pattern_type": {"const": "specific_day"}},
                        },
                        "then": {
                            "required": ["day"],
                            "properties": {"day": {"minimum": 1, "maximum": 31}},
                        },
                    },
                    {
                        "if": {
                            "required": ["pattern_type"],
                            "properties": {
                                "pattern_type": {"const": "ordinal_weekday"}
                            },
                        },
                        "then": {
                            "required": ["ordinal", "weekday"],
                            "properties": {
                                "ordinal": {"enum": [-1, 1, 2, 3, 4]},
                                "weekday": {"minimum": 0, "maximum": 6},
                            },
                        },
                    },
                ],
            },
        },
        {
            "if": {
                "required": ["mode"],
                "properties": {
                    "kind": {"const": "scheduled"},
                    "mode": {"const": "yearly"},
                },
            },
            "then": {
                "required": ["month"],
                "properties": {"month": {"minimum": 1, "maximum": 12}},
            },
        },
    ]
    return schema


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @reason external action variants are asserted through the public transport schema
def _external_report_action_response_schema(
    action_type,
    include_submission_fields,
    require_file_summary_terms,
):
    """Return a standard JSON Schema action variant for external clients."""
    schema = _report_action_response_schema(
        action_type,
        include_submission_fields,
    )
    schema["properties"]["type"] = {
        "type": "string",
        "const": action_type,
    }
    data_schema = schema["properties"]["data"]
    required_groups = REPORT_ACTION_DATA_CONTRACTS[action_type].get(
        "required_groups",
        (),
    )
    if required_groups:
        data_schema["allOf"] = [
            _external_required_group_schema(group) for group in required_groups
        ]


    if action_type == "create_task":
        data_schema["properties"]["schedule"] = external_task_schedule_response_schema()
        descriptions = {
            "due_date": "One-time deadline or first due date. Omit schedule for a one-time reminder.",
            "page": "Hash token of the editable destination Page; a Task or model-task reference cannot replace it.",
            "page_action": "Id of an earlier create_page action for the editable destination Page.",
            "model": "Hash token of the reusable model task describing this work type.",
            "model_action": "Id of an earlier create_model_task action; use this for a reusable work type.",
            "task": "Exact existing Task override for a completed occurrence, not a reusable model task or open-task dependency.",
            "task_action": "Id of an earlier create_task action used as an exact completed-occurrence target; not model_action or an open-task dependency.",
        }
        for field, description in descriptions.items():
            data_schema["properties"][field] = {
                **data_schema["properties"][field],
                "description": description,
            }


    if action_type == "update_task":
        changes = data_schema["properties"]["changes"]["properties"]
        changes["due_date"] = {"type": ["string", "null"], "format": "date"}
        changes["schedule"] = {"anyOf": [external_task_schedule_response_schema(), {"type": "null"}]}

    if action_type == "summarize_file":
        terms_schema = data_schema["properties"]["retrieval_terms"]
        terms_schema["uniqueItems"] = True
        terms_schema["items"]["maxLength"] = 80
        if require_file_summary_terms:
            required = list(data_schema.get("required", ()))
            if "retrieval_terms" not in required:
                required.append("retrieval_terms")
            data_schema["required"] = required
    return schema


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @covered-by lagniappe/core/tools/ai/external/contracts.py::plan_contract
# @reason provider-only ordering hints are removed through the public external serializer
def _standard_json_schema(value):
    """Translate provider annotations into standard JSON Schema semantics."""
    if isinstance(value, dict):
        result = {
            key: _standard_json_schema(child)
            for key, child in value.items()
            if key not in {"propertyOrdering", "nullable"}
        }
        if value.get("nullable") is True:
            return {"anyOf": [result, {"type": "null"}]}
        return result
    if isinstance(value, list):
        return [_standard_json_schema(child) for child in value]
    return value


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_schema_has_named_discriminated_actions
# @tests tests_unit/test_004l_form_schema_updates.py::test_report_conversion_schema_rejects_flattened_items
# @matrix agent-api ai-report : external-schema proposal-contract structured-output
def external_report_proposal_response_schema(
    allowed_actions=None,
    *,
    require_issues=False,
    include_submission_fields=True,
    require_file_summary_terms=False,
):
    """Return a named, machine-readable proposal schema for external clients.

    The internal Gemini schema intentionally keeps its provider-compatible
    inline ``anyOf`` representation. This transport adapter can use standard
    JSON Schema composition to expose named action variants and executable
    reference-group requirements without changing internal model prompts.
    """
    action_types = tuple(ACTION_ORDER if allowed_actions is None else allowed_actions)
    provider_schema = report_proposal_response_schema(
        allowed_actions=action_types,
        require_issues=require_issues,
        include_submission_fields=include_submission_fields,
    )
    schema = _standard_json_schema(provider_schema)
    if not action_types:
        schema["properties"]["actions"] = {"type": "array", "maxItems": 0}
        return schema
    definitions = {
        action_type: _standard_json_schema(
            _external_report_action_response_schema(
                action_type,
                include_submission_fields,
                require_file_summary_terms,
            )
        )
        for action_type in action_types
    }
    mapping = {action_type: f"#/$defs/{action_type}" for action_type in action_types}
    schema["$defs"] = definitions
    schema["properties"]["actions"]["items"] = {
        "oneOf": [{"$ref": reference} for reference in mapping.values()],
        "discriminator": {
            "propertyName": "type",
            "mapping": mapping,
        },
    }
    return schema
