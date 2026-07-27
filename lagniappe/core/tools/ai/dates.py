"""AI-powered parsing of natural language scheduling descriptions."""

from ...exceptions import AIException, capture

from .core import ai_model
from .examples import (
    MONTHLY_SCHEDULING_EXAMPLES,
    PERIODIC_SCHEDULING_EXAMPLES,
    YEARLY_SCHEDULING_EXAMPLES,
)
from .guidelines import (
    MONTHLY_SCHEDULING_OUTPUT_REQUIREMENTS,
    MONTHLY_SCHEDULING_PROMPT_RULES,
    PERIODIC_SCHEDULING_OUTPUT_REQUIREMENTS,
    PERIODIC_SCHEDULING_PROMPT_RULES,
    YEARLY_SCHEDULING_OUTPUT_REQUIREMENTS,
    YEARLY_SCHEDULING_PROMPT_RULES,
)
from .prompt import Prompt


VALID_TYPES = [
    "specific_day",
    "ordinal_weekday",
    "last_day",
    "first_day",
]
VALID_UNITS = ["day", "week", "month", "year"]
SCHEDULED_REQUIRED_FIELDS = ["type", "day", "ordinal", "weekday", "text"]
PERIODIC_REQUIRED_FIELDS = ["unit", "interval", "text"]


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_generation_validators_reject_bad_payloads_and_clean_citations
# @features ai
# @dimensions validation schedule
def validate_schedule(schedule_data, mode):
    """Validate generated schedule data against the expected mode schema.

    Args:
        schedule_data: Dict of parsed schedule fields from the model.
        mode: One of "monthly", "yearly", or "periodic".

    Returns:
        schedule_data
    """
    if all(value is None for value in schedule_data.values()):
        raise AIException("Could not understand user request")

    if mode == "periodic":
        for field in PERIODIC_REQUIRED_FIELDS:
            if field not in schedule_data:
                raise AIException(
                    "Generated schedule data missing required field: {field}"
                )

        if schedule_data["unit"] not in VALID_UNITS:
            raise AIException("Invalid unit generated: {schedule_data['unit']}")

        interval = schedule_data.get("interval")
        if not isinstance(interval, int) or interval < 1:
            raise AIException("Interval generated was not a positive integer.")

        return schedule_data

    for field in SCHEDULED_REQUIRED_FIELDS:
        if field not in schedule_data:
            raise AIException("Generated schedule data missing required field: {field}")

    if schedule_data["type"] not in VALID_TYPES:
        raise AIException("Invalid schedule type generated: {schedule_data['type']}")

    if mode == "yearly":
        month = schedule_data.get("month")
        if not isinstance(month, int) or month < 1 or month > 12:
            raise AIException("Month generated was not an integer between 1 and 12.")

    if schedule_data["type"] == "specific_day":
        day = schedule_data.get("day")
        if not isinstance(day, int) or day < 1 or day > 31:
            raise AIException("Day generated was not an integer between 1 and 31.")

    if schedule_data["type"] == "ordinal_weekday":
        ordinal = schedule_data.get("ordinal")
        weekday = schedule_data.get("weekday")
        if not isinstance(ordinal, int) or ordinal not in [1, 2, 3, 4, -1]:
            raise AIException(
                "Ordinal generated was not an integer between 1-4 or -1 for last"
            )
        if not isinstance(weekday, int) or weekday < 0 or weekday > 6:
            raise AIException("Weekday generated was not an integer between 0 and 6.")

    return schedule_data


# @testable false
# @covered-by lagniappe/core/tools/ai/dates.py::validate_schedule
# @covered-by lagniappe/core/tools/ai/dates.py::scheduling_prompt
# @reason provider-call wrapper; natural-language model quality belongs in AI E2E/manual provider validation
def generate_schedule(prompt):
    """Generate and validate a schedule from a Prompt."""
    schedule_data = None
    try:
        schedule_data = ai_model.generate_content(
            prompt,
            validator=lambda result: validate_schedule(result, mode=prompt.mode),
        )
        return schedule_data
    except Exception as e:
        capture(e, context={"prompt": prompt.build(), "schedule_data": schedule_data})
        raise AIException(f"Unable to generate schedule: {str(e)}")


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_prompt_builders_capture_product_context_and_tool_choices
# @features ai
# @dimensions prompt-builders output-format thinking
def scheduling_prompt(**kwargs):
    """Build the AI prompt for parsing natural language scheduling descriptions"""

    prompt = Prompt(type="scheduling")
    prompt.mode = kwargs.get("mode")
    user_prompt = kwargs.get("user_prompt")

    if prompt.mode == "monthly":
        prompt.intro = """Parse the user's request describing when a task should repeat monthly and return structured JSON."""

        prompt.add_context("user_request", user_prompt)

        prompt.add_instructions(MONTHLY_SCHEDULING_PROMPT_RULES)
        for example in MONTHLY_SCHEDULING_EXAMPLES:
            prompt.add_example(example.get("example"), title=example.get("request"))

        prompt.set_output_format(
            "JSON", description=MONTHLY_SCHEDULING_OUTPUT_REQUIREMENTS
        )
    elif prompt.mode == "yearly":
        prompt.intro = """Parse the user's request describing when a task should repeat yearly and return structured JSON."""

        prompt.add_context("user_request", user_prompt)

        prompt.add_instructions(YEARLY_SCHEDULING_PROMPT_RULES)
        for example in YEARLY_SCHEDULING_EXAMPLES:
            prompt.add_example(example.get("example"), title=example.get("request"))

        prompt.set_output_format(
            "JSON", description=YEARLY_SCHEDULING_OUTPUT_REQUIREMENTS
        )
    elif prompt.mode == "periodic":
        prompt.intro = """Parse the user's request describing a periodic/repeating schedule and return structured JSON."""

        prompt.add_context("user_request", user_prompt)

        prompt.add_instructions(PERIODIC_SCHEDULING_PROMPT_RULES)
        for example in PERIODIC_SCHEDULING_EXAMPLES:
            prompt.add_example(example.get("example"), title=example.get("request"))

        prompt.set_output_format(
            "JSON", description=PERIODIC_SCHEDULING_OUTPUT_REQUIREMENTS
        )

    prompt.set_thinking_budget(0)
    prompt.set_model_tier("utility")
    return prompt
