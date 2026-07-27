"""AI-powered form schema generation from natural language descriptions."""

from ... import exceptions

from .core import ai_model
from .guidelines import (
    FORM_ENTITY_BOUNDARIES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    PAGE_FORM_CONTENT_GUIDELINES,
    PAGE_FORM_REQUIREMENTS,
    PAGE_FORM_SCHEMA_FORMAT,
    TASK_FORM_CONTENT_GUIDELINES,
    TASK_FORM_REQUIREMENTS,
    TASK_FORM_SCHEMA_FORMAT,
)
from .prompt import Prompt

GENERIC_MESSAGE = "Generation failed. Please try again. "


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_generation_validators_reject_bad_payloads_and_clean_citations
# @features ai
# @dimensions validation schema
def validate_schema(schema):
    validated_schema = []
    """Validate that each generated schema element has a type and id."""
    if not isinstance(schema, list):
        raise exceptions.AIException("Generated schema is not a valid array")
    for element in schema:
        if not isinstance(element, dict):
            continue
        elif not _valid_schema_attribute(element.get("type")):
            continue
        elif not _valid_schema_attribute(element.get("id")):
            continue
        validated_schema.append(element)
    return validated_schema


# @testable false
# @covered-by lagniappe/core/tools/ai/schema.py::validate_schema
# @reason small validation helper owned by schema ingress validation
def _valid_schema_attribute(value):
    return isinstance(value, str) and bool(value.strip())


# @testable false
# @covered-by lagniappe/core/tools/ai/schema.py::validate_schema
# @covered-by lagniappe/core/tools/ai/schema.py::form_generation_prompt
# @reason provider-call wrapper; deterministic schema validation and prompt construction are tracked separately
def generate_schema(prompt):
    """Generate and validate a form schema from a Prompt."""
    try:
        return ai_model.generate_content(prompt, validator=validate_schema)
    except Exception as e:
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}")


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @features ai
# @dimensions prompt-builders output-format thinking
def form_generation_prompt(form_type, description=None):
    """Build the AI prompt for generating a page or task form schema.

    Args:
        form_type: Either "page" or "task" to select the appropriate guidelines.
        description: User's natural language description of the desired form.
    """
    intro = "You are a form builder AI. Generate a JSON schema for a form based on the user's description."

    prompt = Prompt(intro, type="form generation")

    prompt.add_context("user_request", description)
    prompt.add_instructions(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(FORM_ENTITY_BOUNDARIES)

    if form_type == "page":
        prompt.add_instructions(PAGE_FORM_SCHEMA_FORMAT)
        prompt.add_instructions(PAGE_FORM_REQUIREMENTS)
        prompt.add_instructions(PAGE_FORM_CONTENT_GUIDELINES)
    elif form_type == "task":
        prompt.add_instructions(TASK_FORM_SCHEMA_FORMAT)
        prompt.add_instructions(TASK_FORM_REQUIREMENTS)
        prompt.add_instructions(TASK_FORM_CONTENT_GUIDELINES)

    prompt.set_output_format("JSON")
    prompt.set_thinking_budget(1024)
    prompt.set_model_tier("utility")

    return prompt
