"""AI-powered project generation from natural language descriptions."""

from ...exceptions import AIException
from .core import ai_model
from .examples import ROOM_CLEANING_PROJECT_EXAMPLE, WOODWORKING_PROJECT_EXAMPLE
from .guidelines import (
    FORM_ENTITY_BOUNDARIES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    PROJECT_COMPLEXITY_GUIDELINES,
    PROJECT_GENERATION_GUIDELINES,
    PROJECT_OUTPUT_REQUIREMENTS,
    TASK_FORM_CONTENT_GUIDELINES,
    TASK_FORM_REQUIREMENTS,
    TASK_FORM_SCHEMA_FORMAT,
)
from .prompt import Prompt

GENERIC_MESSAGE = "Generation failed. Please try again. "


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_generation_validators_reject_bad_payloads_and_clean_citations
# @features ai
# @dimensions validation project
def validate_project(project_data):
    """Validate that generated project data has all required fields."""
    if "project_name" not in project_data:
        raise AIException(
            "Project data missing required field: project_name",
        )
    if "project_description" not in project_data:
        raise AIException(
            "Project data missing required field: project_description",
        )
    if "model_tasks" not in project_data:
        raise AIException(
            "Project data missing required field: model_tasks",
        )
    if not isinstance(project_data["model_tasks"], list):
        raise AIException("Model tasks is not a valid array")
    for model_task in project_data["model_tasks"]:
        if not isinstance(model_task, dict):
            raise AIException("Model task is not a valid object")
        if "name" not in model_task:
            raise AIException("Model task missing required field: name")
        if "form_schema" not in model_task:
            raise AIException(
                "Model task missing required field: form_schema",
            )
    return project_data


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_ai_mode
# @features projects
# @dimensions ai-create ai-generated
def generate_project(prompt):
    """Generate and validate a project specification from a Prompt."""
    try:
        return ai_model.generate_content(prompt, validator=validate_project)
    except (AIException, Exception) as e:
        raise AIException(f"{GENERIC_MESSAGE} {str(e)}")


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @features ai
# @dimensions prompt-builders output-format
def project_creation_prompt(user_description):
    """Build the AI prompt for creating a project from a user description."""
    intro = """You are a project creation AI. Based on the user's description, create a comprehensive project specification with appropriate model tasks and forms for data collection."""

    prompt = Prompt(intro, type="project generation")
    prompt.add_context("user_request", user_description)

    prompt.add_instructions(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(FORM_ENTITY_BOUNDARIES)
    prompt.add_instructions(PROJECT_GENERATION_GUIDELINES)
    prompt.add_instructions(PROJECT_COMPLEXITY_GUIDELINES)
    prompt.add_instructions(TASK_FORM_SCHEMA_FORMAT)
    prompt.add_instructions(TASK_FORM_REQUIREMENTS)
    prompt.add_instructions(TASK_FORM_CONTENT_GUIDELINES)

    prompt.add_example(WOODWORKING_PROJECT_EXAMPLE, title="Woodworking Project")
    prompt.add_example(ROOM_CLEANING_PROJECT_EXAMPLE, title="Room Cleaning Project")

    prompt.set_output_format("JSON", description=PROJECT_OUTPUT_REQUIREMENTS)

    return prompt
