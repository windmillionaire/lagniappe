"""Shared action contracts, response schemas, and permissions for AI reports."""

from ..autofill import submission_response_schema
from .schedules import task_schedule_response_schema

READ_ONLY_CONTEXT_TOOLS = (
    "list_workspace_resources",
    "get_guidelines",
    "search_entities",
    "get_entity",
    "get_schema",
    "get_file",
    "get_category_forms",
    "get_category_pages",
    "get_page_details",
    "get_page_file_list",
    "get_page_tasks",
    "get_form_instances",
    "get_category_details",
)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts.py::report_proposal_response_schema
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
# @covered-by lagniappe/core/tools/ai/reporting/contracts.py::report_proposal_response_schema
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
# @covered-by lagniappe/core/tools/ai/reporting/contracts.py::report_proposal_response_schema
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


REPORT_ACTION_DATA_CONTRACTS = {
    "create_form": {
        "fields": ("name", "form_type", "schema"),
        "required": ("name", "form_type", "schema"),
    },
    "create_category": {
        "fields": (
            "name",
            "description",
            "form",
            "form_action",
            "form_name",
        ),
        "required": ("name",),
    },
    "create_project": {
        "fields": ("name", "description"),
        "required": ("name",),
    },
    "create_model_task": {
        "fields": (
            "name",
            "project",
            "project_action",
            "project_name",
            "form",
            "form_action",
            "form_name",
        ),
        "required": ("name",),
        "required_groups": (("project", "project_action"),),
    },
    "create_page": {
        "fields": (
            "name",
            "description",
            "category",
            "category_action",
            "category_name",
            "form",
            "form_action",
            "form_name",
            "document",
            "submission",
            "submission_empty_reason",
        ),
        "required": ("name",),
    },
    "create_task": {
        "fields": (
            "name",
            "description",
            "page",
            "page_action",
            "page_name",
            "task",
            "task_action",
            "task_name",
            "project",
            "project_action",
            "project_name",
            "model",
            "model_action",
            "model_name",
            "form",
            "form_action",
            "form_name",
            "due_date",
            "schedule",
            "completed",
            "completed_on",
            "submission",
            "submission_empty_reason",
        ),
        "required": ("name",),
        "required_groups": (("page", "page_action"),),
    },
    "add_form_to_page": {
        "fields": (
            "page",
            "page_action",
            "page_name",
            "form",
            "form_action",
            "form_name",
        ),
        "required_groups": (
            ("page", "page_action"),
            ("form", "form_action"),
        ),
    },
    "add_category": {
        "fields": (
            "page",
            "page_action",
            "page_name",
            "category",
            "category_action",
            "category_name",
        ),
        "required_groups": (
            ("page", "page_action"),
            ("category", "category_action"),
        ),
    },
    "move_page": {
        "fields": (
            "page",
            "page_action",
            "page_name",
            "category",
            "category_action",
            "category_name",
        ),
        "required_groups": (
            ("page", "page_action"),
            ("category", "category_action"),
        ),
    },
    "move_task": {
        "fields": (
            "task",
            "task_action",
            "task_name",
            "to_page",
            "to_page_action",
            "page_name",
        ),
        "required_groups": (
            ("task", "task_action"),
            ("to_page", "to_page_action"),
        ),
    },
    "move_file": {
        "fields": (
            "file",
            "display_name",
            "from_page",
            "from_page_action",
            "from_task",
            "from_task_action",
            "to_page",
            "to_page_action",
            "to_task",
            "to_task_action",
        ),
        "required": ("file",),
        "required_groups": (
            ("from_page", "from_page_action", "from_task", "from_task_action"),
            ("to_page", "to_page_action", "to_task", "to_task_action"),
        ),
    },
    "rename_entity": {
        "fields": ("entity", "entity_action", "entity_name", "name"),
        "required": ("name",),
        "required_groups": (("entity", "entity_action"),),
    },
    "update_form_schema": {
        "fields": ("form", "form_action", "form_name", "operations"),
        "required": ("operations",),
        "required_groups": (("form", "form_action"),),
    },
    "update_submission_fields": {
        "fields": ("page", "page_name", "task", "task_name", "updates"),
        "required": ("updates",),
    },
    "attach_file_to_page": {
        "fields": ("page", "page_action", "page_name", "file", "display_name"),
        "required": ("file",),
        "required_groups": (("page", "page_action"),),
    },
    "attach_file_to_task": {
        "fields": ("task", "task_action", "task_name", "file", "display_name"),
        "required": ("file",),
        "required_groups": (("task", "task_action"),),
    },
    "delete_page": {
        "fields": ("page", "page_action", "page_name"),
        "required_groups": (("page", "page_action"),),
    },
    "skip": {
        "fields": ("note",),
        "required": ("note",),
    },
    "needs_review": {
        "fields": ("note", "questions"),
        "required": ("note", "questions"),
    },
    "summarize_file": {
        "fields": ("file", "summary", "search"),
        "required": ("file", "summary"),
    },
}

# The ordered contract registry is the source of truth for action vocabulary.
# Keep summarize_file valid for older saved proposals and direct runner tests,
# but do not advertise it to new report prompts.
ALLOWED_ACTIONS = frozenset(REPORT_ACTION_DATA_CONTRACTS)
ACTION_ORDER = tuple(
    action_type
    for action_type in REPORT_ACTION_DATA_CONTRACTS
    if action_type != "summarize_file"
)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/contracts.py::report_proposal_response_schema
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
# @covered-by lagniappe/core/tools/ai/reporting/contracts.py::report_proposal_response_schema
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
# @covered-by lagniappe/core/tools/ai/reporting/contracts.py::report_proposal_response_schema
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
# @tests tests_unit/test_020_ai_reports.py::test_report_prompts_attach_provider_json_schema
# @tests tests_unit/test_020_ai_reports.py::test_report_response_schema_uses_provider_compatible_any_of_nodes
# @features ai-report
# @dimensions structured-output schema allowed-actions provider-validation
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


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_report_prompts_filter_actions_by_user_permissions
# @features ai-report
# @dimensions action-capabilities permissions
def allowed_report_actions(user):
    """Return report action types this user may ask the runner to execute."""
    capabilities = user.properties.restrictions.ai_action_capabilities
    allowed = {"skip", "needs_review"}

    if capabilities["can_create_forms"]:
        allowed.add("create_form")
    if capabilities["can_create_categories"]:
        allowed.add("create_category")
    if capabilities["can_create_projects"]:
        allowed.add("create_project")
    if capabilities["can_create_model_tasks"]:
        allowed.add("create_model_task")
    if capabilities["can_create_pages"]:
        allowed.add("create_page")
    if capabilities["can_create_tasks"]:
        allowed.add("create_task")
    if capabilities["can_attach_files_to_pages"]:
        allowed.add("add_form_to_page")
        allowed.add("attach_file_to_page")
    if capabilities["can_attach_files_to_tasks"]:
        allowed.add("attach_file_to_task")
    if capabilities["can_move_pages"]:
        allowed.add("add_category")
        allowed.add("move_page")
    if capabilities["can_move_tasks"]:
        allowed.add("move_task")
    if capabilities["can_move_files"]:
        allowed.add("move_file")
    if capabilities["can_rename_entities"]:
        allowed.add("rename_entity")
    if capabilities["can_update_form_schemas"]:
        allowed.add("update_form_schema")
    if capabilities["can_update_submissions"]:
        allowed.add("update_submission_fields")
    if capabilities["can_delete_pages"]:
        allowed.add("delete_page")

    return tuple(action for action in ACTION_ORDER if action in allowed)


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @reason prompt text is verified through public prompt builders
def report_action_permission_context(user, allowed_actions=None):
    allowed = tuple(allowed_actions or allowed_report_actions(user))
    allowed_set = set(allowed)
    user_capabilities = user.properties.restrictions.ai_action_capabilities
    capabilities = {
        "can_create_forms": (
            user_capabilities["can_create_forms"] and "create_form" in allowed_set
        ),
        "can_create_categories": (
            user_capabilities["can_create_categories"]
            and "create_category" in allowed_set
        ),
        "can_create_projects": (
            user_capabilities["can_create_projects"] and "create_project" in allowed_set
        ),
        "can_create_pages": (
            user_capabilities["can_create_pages"] and "create_page" in allowed_set
        ),
        "can_create_model_tasks": (
            user_capabilities["can_create_model_tasks"]
            and "create_model_task" in allowed_set
        ),
        "can_create_tasks": (
            user_capabilities["can_create_tasks"] and "create_task" in allowed_set
        ),
        "can_attach_files_to_pages": (
            user_capabilities["can_attach_files_to_pages"]
            and "attach_file_to_page" in allowed_set
        ),
        "can_add_forms_to_pages": (
            user_capabilities["can_attach_files_to_pages"]
            and "add_form_to_page" in allowed_set
        ),
        "can_attach_files_to_tasks": (
            user_capabilities["can_attach_files_to_tasks"]
            and "attach_file_to_task" in allowed_set
        ),
        "can_move_pages": (
            user_capabilities["can_move_pages"]
            and bool({"add_category", "move_page"} & allowed_set)
        ),
        "can_move_tasks": (
            user_capabilities["can_move_tasks"] and "move_task" in allowed_set
        ),
        "can_move_files": (
            user_capabilities["can_move_files"] and "move_file" in allowed_set
        ),
        "can_rename_entities": (
            user_capabilities["can_rename_entities"] and "rename_entity" in allowed_set
        ),
        "can_update_form_schemas": (
            user_capabilities["can_update_form_schemas"]
            and "update_form_schema" in allowed_set
        ),
        "can_update_submissions": (
            user_capabilities["can_update_submissions"]
            and "update_submission_fields" in allowed_set
        ),
        "can_delete_pages": (
            user_capabilities["can_delete_pages"] and "delete_page" in allowed_set
        ),
    }
    rules = ["Only return action types listed in allowed_actions."]
    if "create_page" in allowed_set:
        rules.append("Creating pages requires an editable category.")
    if "create_model_task" in allowed_set:
        rules.append("Creating model tasks requires an editable project.")
    if "create_task" in allowed_set:
        rules.append("Creating tasks requires an editable target.")
    if {"attach_file_to_page", "attach_file_to_task"} & allowed_set:
        rules.append("Attaching files requires an editable target.")
    if "add_form_to_page" in allowed_set:
        rules.append(
            "Adding a form to a page requires an editable page and does not require a category."
        )
    if "add_category" in allowed_set:
        rules.append(
            "Adding page categories requires editable source and target entities."
        )
    if {"move_page", "move_task"} & allowed_set:
        rules.append("Moving pages/tasks requires editable source and target entities.")
    if "move_file" in allowed_set:
        rules.append("Moving files requires editable source and target pages or tasks.")
    if "rename_entity" in allowed_set:
        rules.append("Renaming requires an exact editable entity target.")
    if "update_form_schema" in allowed_set:
        rules.append("Schema edits are additive only and require editable forms.")
    if "update_submission_fields" in allowed_set:
        rules.append("Submission updates require exact editable page/task targets.")
    if "delete_page" in allowed_set:
        rules.append("Page deletion is manual cleanup rendered after report execution.")
    rules.append(
        "If the useful action is not allowed, use needs_review or answer without actions."
    )
    return {
        "allowed_actions": list(allowed),
        "capabilities": capabilities,
        "rules": rules,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @reason filtered contracts are observed through prompt output tests
def permission_filtered_output_contract(contract, allowed_actions):
    allowed_lines = "\n".join(f"- {action}" for action in allowed_actions)
    marker = "Allowed action types:"
    next_section = "\n\nReference rules:"
    if marker not in contract or next_section not in contract:
        return contract
    before, rest = contract.split(marker, 1)
    _old_actions, after = rest.split(next_section, 1)
    return f"{before}{marker}\n{allowed_lines}{next_section}{after}"


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @reason permission instruction composition is verified through prompt tests
def report_action_permission_instructions():
    return """
The allowed action list is user-specific. Do not include action types that are
not listed in Report Action Permissions. When using an existing category,
project, page, task, or model task, first confirm the relevant tool result says
it can be edited for the intended action. If a useful workspace change would
require a forbidden action or an uneditable target, return needs_review or
explain the limitation instead of proposing work the runner will reject.
    """
