"""AI-powered form autofill using context, files, and web search."""

import re

from ... import exceptions
from ...definitions import Action
from .core import ai_model
from .guidelines import (
    FILE_CONTEXT,
    FORM_AUTOFILL_RULES,
    SCHEMA_TYPE_GUIDELINES,
    SUBMISSION_OUTPUT_REQUIREMENTS,
)
from .prompt import Prompt

citations = re.compile(r"\. \[.*?\]")

GENERIC_MESSAGE = "Generation failed. Please try again. "
AUTOFILL_MAX_TOOL_ITERATIONS = 2


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @features ai
# @dimensions structured-output submission
def submission_response_schema():
    """Return the provider schema for one dynamic form submission object."""
    return {"type": "object"}


# @testable false
# @covered-by lagniappe/core/tools/ai/autofill.py::autofill_prompt_data
# @reason target normalization is private shared-context plumbing
def _autofill_page(entity):
    if getattr(entity, "entity_kind", None) == "task":
        return entity.page
    if getattr(entity, "entity_kind", None) == "page":
        return entity
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/autofill.py::autofill_attached_files
# @covered-by lagniappe/core/tools/ai/autofill.py::autofill_summary_dependencies
# @reason shared permission filtering is asserted through attachment and dependency projections
def _readable_autofill_files(entity, user):
    if getattr(entity, "entity_kind", None) not in {"page", "task"}:
        return []

    files = []
    seen = set()
    for file in getattr(entity, "files", None) or []:
        key = getattr(file, "key", None) or getattr(file, "hash", None)
        if not file or key in seen or not file.allowed(Action.VIEW, user=user):
            continue
        seen.add(key)
        files.append(file)
    return files


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_autofill_prompt_data_keeps_attachment_context_entity_specific
# @features ai files
# @dimensions attached-files entity-specific
def autofill_attached_files(entity, user):
    """Return readable projections for files attached directly to ``entity``."""
    return [file.to_ai(user) for file in _readable_autofill_files(entity, user)]


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_autofill_summary_dependencies_track_enabled_processing
# @features ai files
# @dimensions autofill summary-dependency pending failed complete
def autofill_summary_dependencies(entity, user):
    """Classify enabled attached-file summaries before autofill generation."""
    states = {"complete": [], "pending": [], "failed": []}
    for file in _readable_autofill_files(entity, user):
        summarize = file.properties.summarize
        if not summarize.enabled:
            continue
        if summarize.complete:
            states["complete"].append(file)
        elif summarize.error:
            states["failed"].append(file)
        else:
            states["pending"].append(file)
    return states


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_autofill_prompt_data_keeps_attachment_context_entity_specific
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
# @features ai files pages tasks
# @dimensions autofill shared-context attached-files entity-specific partial-submission
def autofill_prompt_data(
    entity,
    user,
    *,
    user_context=None,
    file=None,
    mimetype=None,
    create=False,
):
    """Build the shared page/task data contract consumed by autofill prompts."""
    page = _autofill_page(entity)
    task = entity if getattr(entity, "entity_kind", None) == "task" else None
    target = {
        "kind": getattr(entity, "entity_kind", None),
        "name": getattr(entity, "name", None),
        "description": getattr(entity, "description", None),
    }
    target = {key: value for key, value in target.items() if value is not None}
    parent_page = None
    if task and page:
        parent_page = {
            "name": getattr(page, "name", None),
            "description": getattr(page, "description", None),
        }
        parent_page = {
            key: value for key, value in parent_page.items() if value is not None
        }

    category_context = None
    category = getattr(page, "model", None) if page else None
    if category and category.allowed(Action.VIEW, user=user):
        category_context = {
            "name": getattr(category, "name", None),
            "description": getattr(category, "description", None),
        }
        category_context = {
            key: value
            for key, value in category_context.items()
            if value is not None
        }

    form = getattr(entity, "form", None)
    submission = None
    if form:
        submission_property = entity.properties.submission
        submission_property.user = user
        submission = submission_property.ai_value

    document = None
    if page and page.properties.document:
        document = page.properties.document.ai_value

    return {
        "file": file,
        "user": user,
        "user_context": user_context,
        "mimetype": mimetype,
        "document": document,
        "submission": submission,
        "schema": form.schema if form else None,
        "form_name": form.name if form else None,
        "target": target,
        "parent_page": parent_page,
        "category": category_context,
        "attached_files": autofill_attached_files(entity, user),
        "create": create,
    }


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_generation_validators_reject_bad_payloads_and_clean_citations
# @features ai
# @dimensions validation citations
def validate_submission(submission):
    """Strip citation markers from textarea values in a submission."""
    textareas = [
        (schema_id, v)
        for schema_id, v in submission.items()
        if (
            schema_id.startswith("textarea-") or schema_id == "description"
        )
        and isinstance(v, str)
    ]

    for schema_id, textarea in textareas:
        submission[schema_id] = citations.sub(".", textarea)

    return submission


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_exception_context_survives_autofill_wrapper_without_duplicate_capture
# @features ai
# @dimensions error-context terminal-capture
def generate_autofilled_submission(prompt):
    """Generate and validate an autofilled form submission from a Prompt."""
    try:
        return ai_model.generate_content(prompt, validator=validate_submission)
    except Exception as e:
        raise exceptions.AIException(
            f"{GENERIC_MESSAGE} {str(e)}",
            context=getattr(e, "context", None),
        ) from e


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @tests tests_unit/test_015_ai_tools.py::test_autofill_accepts_summary_backed_json_without_tool_or_final_call
# @features ai
# @dimensions prompt-builders search tools file-context output-format
def form_autofill_prompt(**kwargs):
    """Build the AI prompt for form autofilling based on existing data"""

    intro = """You complete one structured page or task form submission. Preserve existing values and fill only fields supported by the supplied context or focused public web research."""
    prompt = Prompt(intro, user=kwargs.get("user"), type="autofill")
    prompt.enable_search()

    form_name = (
        kwargs.get("form").name if kwargs.get("form") else kwargs.get("form_name")
    )
    form_schema = (
        kwargs.get("form").schema if kwargs.get("form") else kwargs.get("schema")
    )
    file = kwargs.get("file")
    attached_files = kwargs.get("attached_files") or []

    if attached_files and kwargs.get("user"):
        prompt.enable_tools("get_file")
        prompt.set_max_tool_iterations(AUTOFILL_MAX_TOOL_ITERATIONS)

    prompt.add_context("target_record", kwargs.get("target"))
    prompt.add_context("parent_page", kwargs.get("parent_page"))
    prompt.add_context("category", kwargs.get("category"))
    prompt.add_context("form_name", form_name)
    prompt.add_context("form_schema", form_schema)
    prompt.add_context("existing_submission", kwargs.get("submission"))
    prompt.add_context("user_provided_context", kwargs.get("user_context"))
    prompt.add_context("page_document", kwargs.get("document"))
    prompt.add_context("attached_files", attached_files)
    if file:
        mimetype = file.content_type or kwargs.get("mimetype")
        prompt.add_bytes(file, mimetype)

    if prompt.bytes:
        prompt.add_context("file_data", FILE_CONTEXT.strip())

    prompt.add_instructions(FORM_AUTOFILL_RULES)
    prompt.add_instructions(SCHEMA_TYPE_GUIDELINES)
    prompt.set_output_format("JSON", description=SUBMISSION_OUTPUT_REQUIREMENTS)

    return prompt
