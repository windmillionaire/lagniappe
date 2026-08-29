"""AI-powered page generation using web search and function calling."""

from ... import exceptions
from .autofill import citations, validate_submission
from .core import ai_model
from .guidelines import (
    DOCUMENT_GUIDELINES,
    FORM_ENTITY_BOUNDARIES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    PAGE_GENERATION_OUTPUT_REQUIREMENTS,
    PAGE_GENERATION_RULES,
    SCHEMA_TYPE_GUIDELINES,
)
from .prompt import Prompt

GENERIC_MESSAGE = "Generation failed. Please try again. "


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_generation_validators_reject_bad_payloads_and_clean_citations
# @tests tests_unit/test_015_ai_tools.py::test_page_generation_reconciles_page_and_form_default_fields
# @matrix ai : form-defaults no-form pages validation
def validate_examples(examples, form_schema=None):
    """Validate generated pages and reconcile form-backed default fields."""

    if not isinstance(examples, list):
        raise exceptions.AIException("Did not produce a valid array of examples")

    has_form = form_schema is not None
    schema_ids = {
        field.get("id")
        for field in form_schema or []
        if isinstance(field, dict) and field.get("id")
    }
    validated = []
    for generated in examples:
        if not isinstance(generated, dict):
            continue

        example = dict(generated)
        raw_submission = example.get("submission")
        if raw_submission is not None and not isinstance(raw_submission, dict):
            continue
        submission = validate_submission(dict(raw_submission or {}))

        name = example.get("name")
        if not isinstance(name, str) or not name.strip():
            name = submission.get("name") if has_form else None
        description = example.get("description")
        if not isinstance(description, str) or not description.strip():
            description = submission.get("description") if has_form else None
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(description, str) or not description.strip():
            continue

        example["name"] = name.strip()
        example["description"] = citations.sub(".", description.strip())

        if has_form:
            if "name" in schema_ids:
                submission["name"] = example["name"]
            if "description" in schema_ids:
                submission["description"] = example["description"]
            if not submission:
                continue
            example["submission"] = submission
        else:
            example.pop("submission", None)

        validated.append(example)

    return validated


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_generation_validators_reject_bad_payloads_and_clean_citations
# @tests tests_unit/test_015_ai_tools.py::test_page_generation_reconciles_page_and_form_default_fields
# @matrix ai : form-defaults no-form pages validation
def generate_pages(prompt, form_schema=None):
    """Generate and validate example pages from a Prompt."""
    try:
        return ai_model.generate_content(
            prompt,
            validator=lambda examples: validate_examples(
                examples,
                form_schema=form_schema,
            ),
        )
    except exceptions.AIException as e:
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}")
    except Exception as e:
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {str(e)}")


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @matrix ai : output-format prompt-builders search tools
def page_generation_prompt(**kwargs):
    """Build the AI prompt for generating example pages for a category.

    Args:
        **kwargs: category_name, category_id, category_description, user_description, form_schema,
            num_pages, tools, and user.
    """
    intro = """You are a page generation AI. Create pages for the category described below."""
    prompt = Prompt(intro, user=kwargs.get("user"), type="page generation")
    prompt.enable_search()

    if kwargs.get("user_request"):
        prompt.add_context("user_request", kwargs.get("user_request"))
    if kwargs.get("category_id"):
        prompt.add_context("category_id", kwargs.get("category_id"))
    prompt.add_context("category_name", kwargs.get("category_name"))
    if kwargs.get("category_description"):
        prompt.add_context("category_description", kwargs.get("category_description"))
    if kwargs.get("form_id"):
        prompt.add_context("form_id", kwargs.get("form_id"))
    if kwargs.get("form_schema"):
        prompt.add_context("form_schema", kwargs.get("form_schema"))
    if kwargs.get("num_pages"):
        prompt.add_context("number_of_pages", kwargs.get("num_pages"))

    if kwargs.get("user"):
        prompt.enable_tools(
            "search_entities", "get_entity", "get_category_forms", "get_category_pages"
        )

    prompt.add_instructions(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(FORM_ENTITY_BOUNDARIES)
    prompt.add_instructions(PAGE_GENERATION_RULES)
    if kwargs.get("form_schema"):
        prompt.add_instructions(SCHEMA_TYPE_GUIDELINES)
    prompt.add_instructions(DOCUMENT_GUIDELINES)

    prompt.set_output_format("JSON", description=PAGE_GENERATION_OUTPUT_REQUIREMENTS)

    return prompt
