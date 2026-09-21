"""Function declaration and handler for on-demand AI guideline bundles."""

from google.genai import types

from lagniappe.core.tools.ai.debug import ai_debug
from lagniappe.core.tools.ai.guidelines import (
    CATEGORY_GENERATION_GUIDELINES,
    REPORT_DOCUMENT_GUIDELINES,
    FORM_AUTOFILL_RULES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    FILE_ORGANIZATION_GUIDELINES,
    REPORT_PROPOSAL_GUIDELINES,
    PROJECT_COMPLEXITY_GUIDELINES,
    PROJECT_GENERATION_GUIDELINES,
    REPORT_TASK_SCHEDULING_GUIDELINES,
    SCHEMA_TYPE_GUIDELINES,
    SCHEMA_EVOLUTION_GUIDELINES,
    SUBMISSION_OUTPUT_REQUIREMENTS,
    SUMMARY_GENERATION_GUIDELINES,
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

SCHEMA_DEFINITION_RULES = {
    "input": "Specify input: text, number, email, tel, date or time.",
    "textarea": "Multi-line plain text. Use for narrative answers.",
    "checkbox": (
        "Boolean answer. A required checkbox must be checked to complete the task: "
        "use it for mandatory affirmative acknowledgements, not questions where No is valid. "
        "For a required Yes/No answer, use a radio or single selection with distinct "
        "non-empty string option values. An optional checkbox may remain unchecked."
    ),
    "radio": "Supply options as {value, label} objects with unique nonempty string values.",
    "select": (
        "Supply options as {value, label} objects with unique nonempty string values. "
        "Set multiple: true only for multiple choices."
    ),
    "table": (
        "Supply columns with exact row-prefixed IDs, titles and types. Columns allow "
        "input (with its input subtype), checkbox, and link. Include the actual "
        "column types in field_types when requesting guidance."
    ),
    "todo": "Ordered checklist; available only in Task Forms.",
    "link": "Specify location: in for a related workspace entity, out for an external URL.",
    "location": "Address field with place lookup. Use for geographic addresses.",
    "signature": "Electronic signature capture for consent or approval.",
    "html": (
        "Supply nonempty content_markdown, never raw html. Use only essential static "
        "information; omit generic instructions and filler."
    ),
}

FORM_DESIGN_GUIDELINES = """
### Form purpose

Add structured answers specific to the Page or Task. Avoid duplicating its name,
description, category, files, document, parent Page, project, assignee or due date
unless the user requests a separate field. Prefer useful repeatable data over
generic filler. Mark a field required only when its answer is necessary.
"""
ACTION_GUIDELINES = {
    **{name: 'Use data.entity and data.changes with exact references. Omitted fields are unchanged. Patch selected answers with changes.submission keyed by exact field IDs. Reassigning a Form requires a complete target submission, including empty values. Pair answer migration and description cleanup in one action. Use $action_id to refer to an earlier created Form or model task. Only active tasks can be restructured. Model defaults affect future tasks only. Project model_tasks must include every model exactly once. Example data: {"entity":"hash:012345abcdef","changes":{"submission":{"textarea-notes":"Updated notes"}}}.' for name in ("update_task", "update_page", "update_project", "update_model_task")},
    "append_page_document": "Add only the requested text in document_markdown to one editable Page (page or page_action). Starts a missing document; never replaces existing text. The server adds trusted source/time attribution. Read existing content first. Unsaved collaborative edits or an uninitialized older document stop execution for a safe retry. Inline edits belong in the editor.",
    "complete_task": "Check off one exact existing Task via data.task at the current execution time. No name-based matching, replacement submission, or historical completed_on override. For a source-dated completed occurrence, use create_task with completed=true, completed_on, and the exact task reference when reusing a Task. Preserve existing fields and attachments; normal required-field and recurring-task rules apply at browser execution. Put update_task first and list its action id in depends_on when completing with details. An already-completed Task is a no-op.",
    "create_form": "Create forms before actions that reference them; use the matching page_form or task_form bundle.",
    "create_category": "Create a category only for a durable collection; reference an earlier default page-form action only when the collection is homogeneous.",
    "create_project": "Create a project before its model tasks and use it for a durable area of goal-directed work.",
    "create_model_task": "Create a model task after its Project and optional task Form; model tasks describe reusable work types.",
    "create_page": "Choose the stable subject, compare plausible existing Pages, use an executable Category/Form reference, and include grounded final submission values when the workflow requires them.",
    "create_task": "Use an editable Page or earlier page action, a stable work name, and task Forms only. For one source-dated completed occurrence, use one create_task with completed=true and completed_on from the source; supply the exact task reference to reuse an existing Task, plus the required name and page/page_action. Future-dated work must remain open. Do not invent a second completion for today. To check off existing work now while preserving its details, use complete_task. Only when evidence contains multiple occurrences, create the latest dated completion first, then another create_task with task_action pointing to that earlier action and the older completed_on date. Both actions supply name and page/page_action; the older occurrence leaves the latest completion intact.",
    "update_form_schema": "Preview exact-ID schema operations, explain destructive changes, and place the update before actions that use it. The user reviews the plan.",
    "attach_file": "Attach the exact report file ref to data.entity (an editable existing Page, Task or task history) or data.entity_action (an earlier create_page/create_task action). This links the file; it does not convert it into document text. Use the completed occurrence as the target for its evidence.",
    "move_task": "Use exact editable source and destination references; propose only requested moves.",
    "move_file": "Use an exact file and editable source/destination; preserve evidence attachments required by the plan.",
    "suggest_page_deletion": "Return only as a final manual-cleanup suggestion after useful content is preserved; the runner does not automatically delete it.",
    "summarize_file": "Summarize only uploads classified as organize, once per exact report file ref, with a grounded full-file summary, two distinct broad retrieval terms, and normally search=true. Evidence-only uploads and existing workspace files do not require summary actions.",
    "skip": "Use only when an artifact truly should not be saved or the user explicitly excluded it.",
    "needs_review": "Use when a real human judgment remains; do not use it to avoid documented schema or reference work.",
}


GUIDELINE_BUNDLES = {
    "filing": {
        "description": "Organize uploaded or existing workspace files from evidence and context.",
        "instructions": (
            "Settle targets and structure, then author all final form submissions "
            "and updates in the same proposal. Use the current action contract. "
            "Read specialized guidelines only for rules not already supplied."
        ),
        "sections": (
            LAGNIAPPE_WORKSPACE_CONCEPTS,
            FILE_ORGANIZATION_GUIDELINES,
        ),
    },
    "category": {
        "description": "Rules for proposing a new category and optional page form.",
        "sections": (
            CATEGORY_GENERATION_GUIDELINES,
            "Read page_form guidance if proposing a default Page Form; a category does not require one.",
        ),
    },
    "project": {
        "description": "Rules for proposing projects, model tasks, and model-task forms.",
        "sections": (
            PROJECT_GENERATION_GUIDELINES,
            PROJECT_COMPLEXITY_GUIDELINES,
            "Read task_form guidance if proposing a Form for a model task.",
        ),
    },
    "page_form": {
        "description": "Rules for proposing a reusable page form schema.",
        "sections": (FORM_DESIGN_GUIDELINES,),
    },
    "task_form": {
        "description": "Rules for proposing a reusable task form schema.",
        "sections": (FORM_DESIGN_GUIDELINES,),
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
        "description": "Rules for reviewed schema edits, affected-entity previews and AI conversions.",
        "sections": (SCHEMA_EVOLUTION_GUIDELINES,),
    },
    "report_actions": {
        "description": "Detailed report action and output contract.",
        "sections": (REPORT_PROPOSAL_GUIDELINES,),
    },
}



EXTERNAL_FORM_AUTOFILL_BUNDLE = {
    "description": "Final form submissions and grounded field updates for external proposals.",
    "instructions": (
        "Author final values in the current external action schema. For "
        "update_task, return only the selected grounded updates; "
        "do not copy unrelated existing values into data.changes.submission."
    ),
    "sections": (
        FORM_AUTOFILL_RULES.replace(
            "- Preserve every non-empty value in the existing submission unchanged. Treat\n"
            "  blank or absent values as the fields available for autofill.",
            "- Preserve existing non-empty values by default. Fill blank or absent "
            "fields from evidence. Replace an existing value only when the user "
            "requests a grounded correction or the assigned evidence clearly "
            "supersedes it; preserve unresolved conflicts for review.",
        ),
        SUBMISSION_OUTPUT_REQUIREMENTS.replace(
            "- Submission objects should contain all properties from the partial submission (if provided) unaltered.",
            "- New submission objects retain supplied partial values unless a "
            "grounded correction is required. For update_task, "
            "include only grounded changes using exact schema field ids.",
        ),
        SCHEMA_TYPE_GUIDELINES,
    ),
}


SUBMISSION_PATCH_BUNDLE = {
    "description": "Grounded changes to selected existing form fields.",
    "instructions": "Return final updates in the current workflow's action schema.",
    "sections": (
        "Use exact Page/Task references and schema field ids. Reuse known schema "
        "and values, or get_schema(include_values=true) when needed. Include only "
        "requested, evidence-supported changes; omitted fields remain unchanged. "
        "Do not invent missing facts or silently resolve conflicting evidence. "
        "For newly added fields, depend on the preceding update_form_schema action. "
        "Use data.entity for the exact target and data.changes.submission for an "
        "object keyed by field IDs. Form reassignment requires all target fields; "
        "an unchanged Form accepts selected fields only.",
        SCHEMA_TYPE_GUIDELINES,
    ),
}


GET_GUIDELINES = types.FunctionDeclaration(
    name="get_guidelines",
    description=(
        "Return detailed prompt guidelines for one report-planning subtask. Use this "
        "tool with task=filing when organizing uploaded or existing workspace files; "
        "evidence-only questions do not need filing guidance. "
        "Use the other tasks for detailed rules about "
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
                    "Optional actual schema element types, including nested table "
                    "column types. For schema_evolution include source and destination "
                    "types. Filters both schema definitions and value guidance."
                ),
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": sorted(ACTION_GUIDELINES),
                },
                "description": (
                    "For task=report_actions, require a nonempty selection and return exact schemas and rules for "
                    "proposal action types. For task=form_autofill, select "
                    "[update_task] for patch guidance instead of full autofill."
                ),
            },
        },
        "required": ["task"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_guidelines_returns_named_bundle
# @tests tests_unit/test_015_ai_tools.py::test_get_guidelines_filters_actions_and_schema_field_types
# @tests tests_unit/test_032d_external_guidance.py::test_submission_patch_guidance_is_shared_and_omits_autofill_workflow
# @matrix ai : guidelines tool-dispatch
# @matrix ai guidelines : action-selection field-type-selection payload-size
def execute_get_guidelines(args, _user):
    """Return guidelines for the built-in provider's current workflow stage."""
    return _guidelines_result(args, external=False)


# @testable true
# @tests tests_unit/test_032d_external_guidance.py::test_organize_guidance_is_shared_across_provider_and_external_dispatch
# @tests tests_unit/test_032d_external_guidance.py::test_submission_patch_guidance_is_shared_and_omits_autofill_workflow
# @matrix ai agent-api : guidelines tool-dispatch
# @matrix ai guidelines : action-selection field-type-selection payload-size
# @matrix ai-report submission : preservation validation
def execute_external_get_guidelines(args, _user):
    """Compose external authoring guidance from trusted API dispatch context."""
    return _guidelines_result(args, external=True)


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @covered-by lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @reason shared bundle filtering is observed through both trusted entry points
def _guidelines_result(args, *, external):
    task = args.get("task")
    ai_debug("tool.get_guidelines.request", task=task)
    bundle = GUIDELINE_BUNDLES.get(task)
    if external and task == "form_autofill":
        bundle = EXTERNAL_FORM_AUTOFILL_BUNDLE
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
    if task == "report_actions" and not actions:
        return {"error": "report_actions requires a nonempty actions array."}
    if actions is not None and task == "form_autofill":
        if not actions or not set(actions) <= {"update_task", "update_page"}:
            return {"error": "form_autofill actions must select update_task and/or update_page."}
        bundle = SUBMISSION_PATCH_BUNDLE
    elif actions is not None and task != "report_actions":
        return {"error": "actions is supported only for task=report_actions or form_autofill."}

    if task in {"page_form", "task_form", "schema_evolution"}:
        bundle = {
            **bundle,
            "sections": (
                *bundle["sections"],
                _schema_definition_guidance(field_types, page_form=task == "page_form"),
            ),
        }

    sections = []
    for section in bundle["sections"]:
        if section == SCHEMA_TYPE_GUIDELINES and field_types is not None:
            section = _schema_type_guidance(field_types)
        sections.append(section)
    if task == "report_actions":
        sections.extend((
            _selected_action_guidance(actions),
            "### Output Boundary\n\nUse the action fields and final JSON "
            "shape defined by the current report response schema.",
        ))

    if task == "report_actions" and "create_task" in actions:
        sections.append(REPORT_TASK_SCHEDULING_GUIDELINES)

    if task == "report_actions" and "summarize_file" in actions:
        sections.append(SUMMARY_GENERATION_GUIDELINES)

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
    if external and task == "report_actions":
        instructions = (
            "Apply only the actions and fields in the current external plan "
            "contract; author all final submission/update values before saving "
            "the proposal. Read tools never execute the proposal."
        )
    content = f"{instructions}\n\n{guidelines}"
    result = {
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
    if task == "report_actions":
        from ..reporting.contracts.schema import report_proposal_response_schema, external_report_proposal_response_schema

        schema = (
            external_report_proposal_response_schema(allowed_actions=actions, include_submission_fields=True, require_file_summary_terms=True)
            if external else report_proposal_response_schema(actions, include_submission_fields=True)
        )
        result["action_schema"] = {**schema["properties"]["actions"]["items"], **({"$defs": schema["$defs"]} if "$defs" in schema else {})}
    return result


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
# @covered-by lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @reason schema-only guidance and field filtering are asserted through both tool entry points
def _schema_definition_guidance(field_types, *, page_form=False):
    selected = SCHEMA_FIELD_TYPES if field_types is None else field_types
    sections = [
        "### Form schema definitions\n\n"
        "A Form schema is an array of field objects with id, type and title. "
        "New IDs use type- plus eight alphanumeric characters starting with a letter; "
        "table column IDs use row- instead. Preserve existing IDs during updates. "
        "Optional shared settings include placeholder and required (boolean). "
        "Visibility/status conditions must reference actual field IDs."
    ]
    for field_type in selected:
        if page_form and field_type in {"todo", "signature", "html"}:
            continue
        sections.append(
            f"#### `{field_type}` schema\n\n{SCHEMA_DEFINITION_RULES[field_type]}"
        )
    return "\n\n".join(sections)


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
