"""Function declaration and handler for on-demand AI guideline bundles."""

from google.genai import types

from lagniappe.core.tools.ai.debug import ai_debug
from lagniappe.core.tools.ai.guidelines import (
    CATEGORY_GENERATION_GUIDELINES,
    DOCUMENT_GUIDELINES,
    FORM_AUTOFILL_RULES,
    ORGANIZE_ACTION_GUIDELINES,
    PAGE_FORM_CONTENT_GUIDELINES,
    PAGE_FORM_REQUIREMENTS,
    PAGE_FORM_SCHEMA_FORMAT,
    PROJECT_COMPLEXITY_GUIDELINES,
    PROJECT_GENERATION_GUIDELINES,
    REPORT_OUTPUT_REQUIREMENTS,
    SCHEMA_TYPE_GUIDELINES,
    SCHEMA_EVOLUTION_GUIDELINES,
    SUBMISSION_OUTPUT_REQUIREMENTS,
    SUMMARY_GENERATION_GUIDELINES,
    TASK_FORM_CONTENT_GUIDELINES,
    TASK_FORM_REQUIREMENTS,
    TASK_FORM_SCHEMA_FORMAT,
)


GUIDELINE_BUNDLES = {
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
        "when a proposal would benefit from detailed rules for generated structure, "
        "form schemas, form submissions, page documents, file summaries, or "
        "action data. Before the tool turn, identify every relevant bundle whose need "
        "is already known and request those get_guidelines calls together."
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
# @features ai
# @dimensions guidelines tool-dispatch
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
    return {
        "task": task,
        "description": bundle["description"],
        "guidelines": (
            "Apply these guidelines when deciding or shaping report proposal action data. "
            "Do not change the final report JSON shape.\n\n"
            f"{guidelines}"
        ),
    }
