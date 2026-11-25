"""AI-powered Markdown content generation from user requests."""

from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from ...entities.entity import Entity
    from ...entities.form import Form
    from ...entities.user import User

from ... import exceptions
from .core import ai_model
from .guidelines import (
    CONTEXT_USAGE_GUIDELINES,
    SELECTED_TEXT_HANDLING,
)
from .prompt import Prompt


class DocumentGenerationContext(TypedDict, total=False):
    user: User
    page_info: dict[str, object]
    project_info: dict[str, object]
    selected_text: str
    existing_document: object
    related_tasks: object


GENERIC_MESSAGE = "Generation failed. Please try again. "


def generate_ai_text(prompt: Prompt) -> str:
    """Generate Markdown text content from a Prompt."""
    try:
        result = ai_model.generate_content(prompt)
        if not isinstance(result, str):
            raise exceptions.AIException("Expected Markdown text from the document prompt.")
        return result
    except exceptions.AIException as e:
        exceptions.capture(e)
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}") from e
    except Exception as e:
        exceptions.capture(e)
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}") from e


def document_generation_context(entity: Entity, user: User, field: str | None = None) -> DocumentGenerationContext:
    """Build text-generation context for collaborative and form documents."""
    context_data: DocumentGenerationContext = {"user": user}
    kind = getattr(entity, "entity_kind", None)

    if kind == "form":
        if not field:
            raise exceptions.ValidationError("field is required")
        try:
            context_data["existing_document"] = cast("Form", entity).fields[field].ai_value
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


def text_generation_prompt(user_prompt: str, context_data: DocumentGenerationContext) -> Prompt:
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

    tools = ["search_entities", "get_help"]

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
