"""Function declaration and handler for on-demand AI guideline bundles."""

from google.genai import types

from lagniappe.core.tools.ai.debug import ai_debug
from lagniappe.core.tools.ai.guidelines import (
    CATEGORY_GENERATION_GUIDELINES,
    REPORT_DOCUMENT_GUIDELINES,
    FORM_AUTOFILL_RULES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    ORGANIZE_ACTION_GUIDELINES,
    ORGANIZE_PLANNING_CONCEPTS,
    ORGANIZE_PLANNING_POLICY,
    ORGANIZE_PLANNING_PREFLIGHT,
    PAGE_FORM_CONTENT_GUIDELINES,
    PAGE_FORM_REQUIREMENTS,
    PAGE_FORM_SCHEMA_FORMAT,
    PROJECT_COMPLEXITY_GUIDELINES,
    PROJECT_GENERATION_GUIDELINES,
    REPORT_OUTPUT_REQUIREMENTS,
    REPORT_PREFLIGHT_CHECKS,
    SCHEMA_TYPE_GUIDELINES,
    SCHEMA_EVOLUTION_GUIDELINES,
    SUBMISSION_OUTPUT_REQUIREMENTS,
    SUMMARY_GENERATION_GUIDELINES,
    TASK_FORM_CONTENT_GUIDELINES,
    TASK_FORM_REQUIREMENTS,
    TASK_FORM_SCHEMA_FORMAT,
)


SCHEMA_FIELD_TYPES = (
    "checkbox",
    "html",
    "input",
    "link",
    "location",
    "radio",
    "select",
    "signature",
    "table",
    "textarea",
    "todo",
)
ACTION_GUIDELINES = {
    "create_form": "Create forms before actions that reference them; use the matching page_form or task_form bundle.",
    "create_category": "Create a category only for a durable collection; reference an earlier default page-form action only when the collection is homogeneous.",
    "create_project": "Create a project before its model tasks and use it for a durable area of goal-directed work.",
    "create_model_task": "Create a model task after its Project and optional task Form; model tasks describe reusable work types.",
    "create_page": "Choose the stable subject, verify no exact Page exists, use an executable Category/Form reference, and include grounded final submission values when form-backed.",
    "create_task": "Use an editable Page or earlier page action, a stable work name, task Forms only, and a source-backed completed_on date only for completed evidence.",
    "add_form_to_page": "Reference one editable existing Page and one page Form; this does not require a Category.",
    "add_category": "Reference both the editable existing Page and additional existing Category; readable names are not executable references.",
    "update_form_schema": "Use additive fields or select/radio options only and place the schema update before actions that use it.",
    "update_submission_fields": "Reference exactly one editable existing Page or Task and provide only grounded final field updates.",
    "attach_file_to_page": "Use the exact report file ref and an editable existing Page or earlier page action.",
    "attach_file_to_task": "Use the exact report file ref and an editable existing Task or earlier task action; completed-task evidence belongs here.",
    "move_page": "Use exact editable source and destination references; Organize should normally prefer needs_review for cleanup moves.",
    "move_task": "Use exact editable source and destination references; Organize should normally prefer needs_review for cleanup moves.",
    "move_file": "Use an exact file and editable source/destination; preserve evidence attachments required by the plan.",
    "rename_entity": "Use one exact editable target and a concise stable name supported by the request.",
    "delete_page": "Return only as a final manual-cleanup suggestion after useful content is preserved; the runner does not automatically delete it.",
    "summarize_file": "Use each exact report file ref once with a grounded full-file summary, two distinct broad retrieval terms, and normally search=true.",
    "skip": "Use only when an artifact truly should not be saved or the user explicitly excluded it.",
    "needs_review": "Use when a real human judgment remains; do not use it to avoid documented schema or reference work.",
}


GUIDELINE_BUNDLES = {
    "organize": {
        "description": (
            "Shared end-to-end workflow for constructing an Organize proposal."
        ),
        "instructions": (
            "Apply this as a two-phase workflow. First use the planning sections "
            "to settle structure and file assignments without submission fields; "
            "do not submit that intermediate plan. Then use Action Planning, the "
            "form_autofill bundle when form values are needed, each exact form "
            "schema, and the current plan contract to add final submission or "
            "update values. Fetch only specialized bundles required by actions you "
            "will return: report_actions with the chosen action names, category "
            "for category structure, project for project/model "
            "structure, page_form or task_form for standalone forms, "
            "schema_evolution only for schema updates, and page_document only for "
            "page documents. File-summary rules are already included here; do not "
            "fetch file_summary separately for an Organize proposal. The live "
            "contract remains the exact action schema. An external client must "
            "complete both applicable phases before "
            "/submit because the server will not call a model to finish or repair "
            "the proposal. The current plan contract is authoritative if an "
            "illustrative shape differs. Read tools only inspect context and never "
            "execute the proposal."
        ),
        "sections": (
            LAGNIAPPE_WORKSPACE_CONCEPTS,
            ORGANIZE_PLANNING_CONCEPTS,
            ORGANIZE_PLANNING_POLICY,
            ORGANIZE_PLANNING_PREFLIGHT,
            SUMMARY_GENERATION_GUIDELINES,
            REPORT_PREFLIGHT_CHECKS,
        ),
    },
    "category": {
        "description": "Rules for proposing a new category and optional page form.",
        "sections": (
            CATEGORY_GENERATION_GUIDELINES,
            PAGE_FORM_REQUIREMENTS,
            PAGE_FORM_SCHEMA_FORMAT,
            PAGE_FORM_CONTENT_GUIDELINES,
            SCHEMA_TYPE_GUIDELINES,
        ),
    },
    "project": {
        "description": "Rules for proposing projects, model tasks, and model-task forms.",
        "sections": (
            PROJECT_GENERATION_GUIDELINES,
            PROJECT_COMPLEXITY_GUIDELINES,
            TASK_FORM_REQUIREMENTS,
            TASK_FORM_SCHEMA_FORMAT,
            TASK_FORM_CONTENT_GUIDELINES,
            SCHEMA_TYPE_GUIDELINES,
        ),
    },
    "page_form": {
        "description": "Rules for proposing a reusable page form schema.",
        "sections": (
            PAGE_FORM_REQUIREMENTS,
            PAGE_FORM_SCHEMA_FORMAT,
            PAGE_FORM_CONTENT_GUIDELINES,
            SCHEMA_TYPE_GUIDELINES,
        ),
    },
    "task_form": {
        "description": "Rules for proposing a reusable task form schema.",
        "sections": (
            TASK_FORM_REQUIREMENTS,
            TASK_FORM_SCHEMA_FORMAT,
            TASK_FORM_CONTENT_GUIDELINES,
            SCHEMA_TYPE_GUIDELINES,
        ),
    },
    "form_autofill": {
        "description": "Rules for filling a page or task submission from context/files.",
        "sections": (
            FORM_AUTOFILL_RULES,
            SUBMISSION_OUTPUT_REQUIREMENTS,
            SCHEMA_TYPE_GUIDELINES,
        ),
    },
    "page_document": {
        "description": "Rules for optional report page document Markdown.",
        "sections": (REPORT_DOCUMENT_GUIDELINES,),
    },
    "file_summary": {
        "description": "Rules for deciding when and how a file summary should support search.",
        "sections": (SUMMARY_GENERATION_GUIDELINES,),
    },
    "schema_evolution": {
        "description": "Rules for bounded additive form schema updates.",
        "sections": (SCHEMA_EVOLUTION_GUIDELINES, SCHEMA_TYPE_GUIDELINES),
    },
    "report_actions": {
        "description": "Detailed report action and output contract.",
        "sections": (ORGANIZE_ACTION_GUIDELINES, REPORT_OUTPUT_REQUIREMENTS),
    },
}


GET_GUIDELINES = types.FunctionDeclaration(
    name="get_guidelines",
    description=(
        "Return detailed prompt guidelines for one report-planning subtask. Use this "
        "tool with task=organize when the caller has not already received the shared "
        "end-to-end Organize workflow. Use the other tasks for detailed rules about "
        "generated structure, form schemas, form submissions, page documents, file "
        "summaries, or action data. Request one bundle per call. Independent bundles "
        "may be requested in parallel when the client supports it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "enum": sorted(GUIDELINE_BUNDLES),
                "description": "The guideline bundle to retrieve.",
            },
            "field_types": {
                "type": "array",
                "items": {"type": "string", "enum": list(SCHEMA_FIELD_TYPES)},
                "description": (
                    "Optional actual schema element types. For bundles containing "
                    "Form value guidance, return only matching type sections."
                ),
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": sorted(ACTION_GUIDELINES),
                },
                "description": (
                    "For task=report_actions, return only rules for the selected "
                    "proposal action types."
                ),
            },
        },
        "required": ["task"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_guidelines_returns_named_bundle
# @tests tests_unit/test_015_ai_tools.py::test_get_guidelines_filters_actions_and_schema_field_types
# @matrix ai : guidelines tool-dispatch
# @matrix ai guidelines : action-selection field-type-selection payload-size
def execute_get_guidelines(args, _user):
    """Return one named guideline bundle without requiring a larger base prompt."""
    task = args.get("task")
    ai_debug("tool.get_guidelines.request", task=task)
    bundle = GUIDELINE_BUNDLES.get(task)
    if not bundle:
        ai_debug(
            "tool.get_guidelines.result",
            task=task,
            error="unknown",
            available=sorted(GUIDELINE_BUNDLES),
        )
        return {
            "error": "Unknown guidelines task.",
            "available": sorted(GUIDELINE_BUNDLES),
        }

    field_types, error = _selected_values(
        args.get("field_types"), SCHEMA_FIELD_TYPES, "field_types"
    )
    if error:
        return error
    actions, error = _selected_values(
        args.get("actions"), tuple(ACTION_GUIDELINES), "actions"
    )
    if error:
        return error
    if actions is not None and task != "report_actions":
        return {"error": "actions is supported only for task=report_actions."}

    sections = []
    for section in bundle["sections"]:
        if section == SCHEMA_TYPE_GUIDELINES and field_types is not None:
            section = _schema_type_guidance(field_types)
        if task == "report_actions" and actions is not None:
            if section == ORGANIZE_ACTION_GUIDELINES:
                section = _selected_action_guidance(actions)
            elif section == REPORT_OUTPUT_REQUIREMENTS:
                section = (
                    "### Output Boundary\n\nReturn the complete proposal object "
                    "defined by the current plan contract."
                )
        sections.append(section)

    guidelines = "\n\n".join(section.strip() for section in sections)
    ai_debug(
        "tool.get_guidelines.result",
        task=task,
        description=bundle["description"],
        section_count=len(sections),
        chars=len(guidelines),
    )
    instructions = bundle.get(
        "instructions",
        "Apply these guidelines when deciding or shaping report proposal action "
        "data. Do not change the final report JSON shape.",
    )
    content = f"{instructions}\n\n{guidelines}"
    return {
        "task": task,
        "description": bundle["description"],
        "guidelines": content,
        "content_bytes": len(content.encode("utf-8")),
        "section_count": len(sections),
        "filters": {
            **({"field_types": field_types} if field_types is not None else {}),
            **({"actions": actions} if actions is not None else {}),
        },
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @reason option validation and stable deduplication are observed through filtered guidance
def _selected_values(value, allowed, field):
    if value is None:
        return None, None
    if not isinstance(value, list):
        return None, {"error": f"{field} must be an array."}
    normalized = list(dict.fromkeys(str(item).strip().casefold() for item in value))
    invalid = [item for item in normalized if item not in allowed]
    if invalid:
        return None, {
            "error": f"Unknown {field} value.",
            "invalid": invalid,
            "allowed": sorted(allowed),
        }
    return normalized, None


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @reason field-type section routing is asserted through filtered public guidance
def _schema_type_guidance(field_types):
    preamble, marker, remainder = SCHEMA_TYPE_GUIDELINES.partition("\n#### `input`")
    if not marker:
        return SCHEMA_TYPE_GUIDELINES
    chunks = (marker + remainder).split("\n#### ")
    selected = [preamble.strip()]
    wanted = set(field_types)
    for chunk in chunks:
        if not chunk.strip():
            continue
        heading = chunk.splitlines()[0].casefold()
        applies = {
            field_type
            for field_type in SCHEMA_FIELD_TYPES
            if f"`{field_type}`" in heading
        }
        if applies & wanted:
            selected.append(f"#### {chunk.strip()}")
    return "\n\n".join(selected)


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @reason selected action text is asserted through filtered public guidance
def _selected_action_guidance(actions):
    lines = [
        "### Selected Action Planning",
        "",
        "Actions must be ordered before their dependants. Existing entities use "
        "exact tool-returned hash tokens; newly created entities use earlier action ids.",
    ]
    lines.extend(f"- `{action}`: {ACTION_GUIDELINES[action]}" for action in actions)
    return "\n".join(lines)
