"""AI-powered Markdown content generation from user requests."""

from ... import exceptions
from .core import ai_model
from .guidelines import (
    CONTEXT_USAGE_GUIDELINES,
    SELECTED_TEXT_HANDLING,
)
from .prompt import Prompt


GENERIC_MESSAGE = "Generation failed. Please try again. "


# @testable false
# @covered-by lagniappe/core/tools/ai/text.py::text_generation_prompt
# @reason provider-call wrapper; editor text-generation E2E story is still an explicit source gap
def generate_ai_text(prompt):
    """Generate Markdown text content from a Prompt."""
    try:
        return ai_model.generate_content(prompt)
    except exceptions.AIException as e:
        exceptions.capture(e)
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}")
    except Exception as e:
        exceptions.capture(e)
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}")


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_document_generation_context_builds_form_page_and_project_payloads
# @matrix ai : document-context project-context
def document_generation_context(entity, user, field=None):
    """Build text-generation context for collaborative and form documents."""
    context_data = {"user": user}
    kind = getattr(entity, "entity_kind", None)

    if kind == "form":
        if not field:
            raise exceptions.ValidationError("field is required")
        try:
            context_data["existing_document"] = entity.fields[field].ai_value
        except KeyError as e:
            raise exceptions.ValidationError("field is not available") from e
    elif kind == "page":
        context_data["page_info"] = entity.to_ai(user=user)
    elif kind == "project":
        context_data["project_info"] = entity.to_ai(user=user)
    else:
        raise exceptions.ValidationError(
            "text generation is not available for this document"
        )

    return context_data


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @tests tests_e2e/005_pages/test_005g_page_document_ai.py::test_generate_text_explain_includes_selected_text_context
# @matrix ai : output-format project-context prompt-builders search selected-text tools
def text_generation_prompt(user_prompt, context_data):
    """Build the AI prompt for text generation from page context.

    Args:
        context_data: Dict with user_request, page_info, project_info,
            existing_document, related_tasks, selected_text, and user.
    """
    intro = "You are a content generation AI. Generate clear, well-formatted Markdown based on the user's request."

    user = context_data.get("user")
    prompt = Prompt(intro, user=user, type="document text")
    prompt.enable_search()
    prompt.add_instructions(CONTEXT_USAGE_GUIDELINES)

    prompt.add_context("user_request", user_prompt)

    tools = ["search_entities"]

    if context_data.get("page_info"):
        prompt.add_context("page_info", context_data.get("page_info"))
        tools.extend(["get_page_file_list", "get_page_tasks", "get_file"])
    elif context_data.get("project_info"):
        prompt.add_context("project_info", context_data.get("project_info"))
    elif context_data.get("existing_document"):
        prompt.add_context("existing_document", context_data.get("existing_document"))

    if user:
        prompt.enable_tools(*tools)

    if context_data.get("selected_text"):
        prompt.add_context("selected_text", context_data.get("selected_text"))
        prompt.add_instructions(SELECTED_TEXT_HANDLING)

    prompt.set_output_format("MARKDOWN")

    return prompt
