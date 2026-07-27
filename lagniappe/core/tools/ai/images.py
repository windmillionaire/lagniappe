"""AI-powered image generation for pages."""

from ... import exceptions
from .core import ai_model, provider_error_message
from .guidelines import IMAGE_PROMPT_RULES
from .prompt import Prompt

GENERIC_MESSAGE = "Image generation failed."

VALID_ASPECT_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}

ASPECT_RATIO_INSTRUCTIONS = """
Choose the single best aspect ratio for this image.

- 9:16 — tall portrait, full-body people, vertical subjects, buildings
- 3:4 — mild portrait, headshots, objects taller than wide
- 1:1 — balanced, square, icons, abstract, centered subjects
- 4:3 — mild landscape, general scenes, groups of people
- 16:9 — wide landscape, panoramic, cinematic, wide establishing shots

Respond with ONLY the ratio (e.g. "3:4"). Nothing else.
"""


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_image_prompting_and_aspect_ratio_selection
# @features ai
# @dimensions image-prompt aspect-ratio fallback
def _choose_aspect_ratio(prompt):
    """Ask the text model to recommend an aspect ratio from the image context."""
    ratio_prompt = Prompt(type="image aspect ratio")
    ratio_prompt.intro = (
        "You are an image composition expert. Based on the context, "
        "choose the most appropriate aspect ratio for the image."
    )
    ratio_prompt.context_blocks = list(prompt.context_blocks)
    ratio_prompt.add_instructions(ASPECT_RATIO_INSTRUCTIONS)
    ratio_prompt.set_output_format("TEXT")
    ratio_prompt.set_thinking_budget(0)
    ratio_prompt.set_model_tier("utility")

    try:
        result = ai_model.generate_content(ratio_prompt)
        ratio = result.strip().strip('"').strip("'")
        if ratio in VALID_ASPECT_RATIOS:
            return ratio
    except Exception:
        pass
    return None


# @testable true
# @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
# @tests tests_unit/test_015_ai_tools.py::test_generate_ai_image_returns_clean_provider_message
# @features pages ai
# @dimensions image-generate
def generate_ai_image(prompt):
    """Generate an image from a Prompt and return a BytesIO buffer."""
    try:
        aspect_ratio = _choose_aspect_ratio(prompt)
        return ai_model.generate_image(prompt, aspect_ratio=aspect_ratio)
    except Exception as e:
        exceptions.capture(e)
        detail = provider_error_message(e)
        raise exceptions.AIException(f"{GENERIC_MESSAGE} {detail}") from e


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_image_prompting_and_aspect_ratio_selection
# @features ai
# @dimensions image-prompt
def page_image_generation_prompt(**kwargs):
    """Build the AI prompt for generating an image from page context.

    Args:
        **kwargs: user_prompt and page_details dict with context fields.
    """
    prompt = Prompt(type="image generation")

    prompt.intro = (
        "You are an image generation AI. Generate a single image that "
        "best represents the content described by the context provided. "
        "Produce a visually compelling, high-quality image."
    )

    if kwargs.get("user_prompt"):
        prompt.add_context("user_request", kwargs.get("user_prompt"))
    if kwargs.get("page_details"):
        for key, value in kwargs.get("page_details").items():
            if value:
                prompt.add_context(key, value)

    prompt.add_instructions(IMAGE_PROMPT_RULES)

    return prompt
