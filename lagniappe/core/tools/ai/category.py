"""AI-powered category creation with conservative optional default forms."""

from typing import NotRequired, TypedDict, cast

from ... import exceptions
from ...properties.schema import canonicalize_schema
from .core import ai_model
from .examples import CATEGORY_CONTEXT_EXAMPLE, CATEGORY_EXAMPLE
from .guidelines import (
    CATEGORY_GENERATION_GUIDELINES,
    CATEGORY_OUTPUT_REQUIREMENTS,
    FORM_ENTITY_BOUNDARIES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    PAGE_FORM_CONTENT_GUIDELINES,
    PAGE_FORM_REQUIREMENTS,
    PAGE_FORM_SCHEMA_FORMAT,
)
from .prompt import Prompt

class GeneratedCategory(TypedDict):
    category_name: str
    category_description: NotRequired[str | None]
    form_name: NotRequired[str]
    form_schema: NotRequired[list[dict[str, object]]]


GENERIC_MESSAGE = "Generation failed. Please try again. "


def validate_category(category_data: object) -> GeneratedCategory:
    """Validate category output and normalize an omitted default form."""
    if not isinstance(category_data, dict) or not isinstance(category_data.get("category_name"), str) or not category_data["category_name"]:
        raise exceptions.AIException(
            "Generated category data missing required field: category_name"
        )

    if category_data.get("category_description") is not None and not isinstance(category_data["category_description"], str):
        raise exceptions.AIException("Generated category description must be text.")
    form_schema = category_data.get("form_schema")
    if form_schema is None or form_schema == []:
        category_data.pop("form_name", None)
        category_data.pop("form_schema", None)
        return cast(GeneratedCategory, category_data)

    if not isinstance(form_schema, list) or not all(isinstance(field, dict) for field in form_schema):
        raise exceptions.AIException("Generated form schema is not a valid array")
    if not isinstance(category_data.get("form_name"), str) or not category_data["form_name"].strip():
        raise exceptions.AIException(
            "Generated category default form missing required field: form_name"
        )
    return cast(GeneratedCategory, category_data)


def generate_category(prompt: Prompt) -> GeneratedCategory:
    """Generate category data with an optional, conservatively chosen form."""
    def validate_generated(category_data):
        if isinstance(category_data, dict) and isinstance(
            category_data.get("form_schema"), list
        ):
            category_data["form_schema"] = canonicalize_schema(
                category_data["form_schema"],
                form_type="page",
                discard_invalid=True,
            )
        return validate_category(category_data)

    try:
        return ai_model.generate_content(prompt, validator=validate_generated)
    except exceptions.AIException as e:
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}") from e
    except Exception as e:
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}") from e


def category_creation_prompt(user_description: str) -> Prompt:
    """Build the AI prompt for creating a category from a user description."""
    intro = """
Based on the user's description, create a category. Include a default page form
only when the category clearly represents repeated instances of one type with
shared structured fields.
    """

    prompt = Prompt(intro, type="category generation")

    prompt.add_context("user_description", user_description)
    prompt.add_instructions(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(FORM_ENTITY_BOUNDARIES)
    prompt.add_instructions(CATEGORY_GENERATION_GUIDELINES)
    prompt.add_instructions(PAGE_FORM_SCHEMA_FORMAT)
    prompt.add_instructions(PAGE_FORM_REQUIREMENTS)
    prompt.add_instructions(PAGE_FORM_CONTENT_GUIDELINES)

    prompt.set_output_format("JSON", description=CATEGORY_OUTPUT_REQUIREMENTS)
    prompt.set_thinking_budget(1024)
    prompt.add_example(
        CATEGORY_EXAMPLE,
        title="Homogeneous collection with default form",
    )
    prompt.add_example(
        CATEGORY_CONTEXT_EXAMPLE,
        title="Context category without default form",
    )

    return prompt
