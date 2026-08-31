"""Function declaration and handler for on-demand AI guideline bundles."""

from google.genai import types

from lagniappe.core.tools.ai.debug import ai_debug
from lagniappe.core.tools.ai.guidelines import (
    CATEGORY_GENERATION_GUIDELINES,
    DOCUMENT_GUIDELINES,
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
            "will return: category for category structure, project for project/model "
            "structure, page_form or task_form for standalone forms, "
            "schema_evolution only for schema updates, and page_document only for "
            "page documents. File-summary rules are already included here; do not "
            "fetch file_summary separately for an Organize proposal. Do not fetch "
            "report_actions because this organize bundle and the live contract "
            "already provide the action/preflight rules. An external client must "
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
            ORGANIZE_ACTION_GUIDELINES,
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
        "description": "Rules for optional page document HTML.",
        "sections": (DOCUMENT_GUIDELINES,),
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
            }
        },
        "required": ["task"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_guidelines_returns_named_bundle
# @matrix ai : guidelines tool-dispatch
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

    guidelines = "\n\n".join(section.strip() for section in bundle["sections"])
    ai_debug(
        "tool.get_guidelines.result",
        task=task,
        description=bundle["description"],
        section_count=len(bundle["sections"]),
        chars=len(guidelines),
    )
    instructions = bundle.get(
        "instructions",
        "Apply these guidelines when deciding or shaping report proposal action "
        "data. Do not change the final report JSON shape.",
    )
    return {
        "task": task,
        "description": bundle["description"],
        "guidelines": f"{instructions}\n\n{guidelines}",
    }
