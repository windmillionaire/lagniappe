"""Validated task-schedule contracts shared by AI report planning and execution."""

from lagniappe.core import exceptions


SCHEDULE_KINDS = frozenset({"recurring", "scheduled", "periodic"})
SCHEDULE_UNITS = frozenset({"day", "week", "month", "year"})
SCHEDULED_MODES = frozenset({"daily", "weekly", "monthly", "yearly"})
SCHEDULE_PATTERN_TYPES = frozenset(
    {"specific_day", "ordinal_weekday", "last_day", "first_day"}
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_report_task_schedule_contract_validates_supported_patterns
# @features ai-report task-scheduling
# @dimensions structured-output recurring scheduled periodic validation
def task_schedule_response_schema():
    """Return the provider schema for one reviewed task schedule."""
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": sorted(SCHEDULE_KINDS)},
            "mode": {"type": "string", "enum": sorted(SCHEDULED_MODES)},
            "interval": {"type": "integer"},
            "unit": {"type": "string", "enum": sorted(SCHEDULE_UNITS)},
            "days": {
                "type": "array",
                # google.genai's Schema model currently types enum members as
                # strings, even for integer schemas. Keep the provider shape
                # broad and enforce the 0-6 range in validate_task_schedule().
                "items": {"type": "integer"},
            },
            "pattern_type": {
                "type": "string",
                "enum": sorted(SCHEDULE_PATTERN_TYPES),
            },
            "day": {"type": "integer"},
            "ordinal": {"type": "integer"},
            "weekday": {"type": "integer"},
            "month": {"type": "integer"},
            "user_prompt": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["kind"],
        "propertyOrdering": [
            "kind",
            "mode",
            "interval",
            "unit",
            "days",
            "pattern_type",
            "day",
            "ordinal",
            "weekday",
            "month",
            "user_prompt",
            "description",
        ],
        "additionalProperties": False,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/schedules.py::validate_task_schedule
# @reason numeric validation is exercised through the public schedule contract
def _positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise exceptions.AIException(
            f"Task schedule {label} must be a positive integer."
        )
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/schedules.py::validate_task_schedule
# @reason bounded numeric validation is exercised through the public schedule contract
def _bounded_integer(value, label, minimum, maximum, *, allowed=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise exceptions.AIException(f"Task schedule {label} must be an integer.")
    if allowed is not None and value not in allowed:
        raise exceptions.AIException(f"Task schedule {label} is invalid.")
    if value < minimum or value > maximum:
        raise exceptions.AIException(f"Task schedule {label} is out of range.")
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/schedules.py::validate_task_schedule
# @reason text normalization is exercised through the public schedule contract
def _optional_text(schedule, key):
    value = schedule.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise exceptions.AIException(f"Task schedule {key} must be non-empty text.")
    return value.strip()


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_report_task_schedule_contract_validates_supported_patterns
# @features ai-report task-scheduling
# @dimensions recurring scheduled periodic validation normalization
def validate_task_schedule(schedule):
    """Validate and normalize a report ``create_task.data.schedule`` object."""
    if not isinstance(schedule, dict):
        raise exceptions.AIException("Task schedule must be an object.")
    kind = schedule.get("kind")
    if kind not in SCHEDULE_KINDS:
        raise exceptions.AIException("Task schedule kind is invalid.")

    if kind in {"recurring", "periodic"}:
        normalized = {
            "kind": kind,
            "interval": _positive_integer(schedule.get("interval"), "interval"),
        }
        unit = schedule.get("unit")
        if unit not in SCHEDULE_UNITS:
            raise exceptions.AIException("Task schedule unit is invalid.")
        normalized["unit"] = unit
        if kind == "periodic":
            description = _optional_text(schedule, "description")
            if not description:
                raise exceptions.AIException(
                    "Periodic task schedule requires a description."
                )
            normalized["description"] = description
            normalized["user_prompt"] = (
                _optional_text(schedule, "user_prompt") or description
            )
        return normalized

    mode = schedule.get("mode")
    if mode not in SCHEDULED_MODES:
        raise exceptions.AIException("Scheduled task requires a valid mode.")
    normalized = {"kind": kind, "mode": mode}
    if mode == "weekly":
        days = schedule.get("days")
        if not isinstance(days, list) or not days:
            raise exceptions.AIException(
                "Weekly task schedule requires at least one weekday."
            )
        normalized["days"] = sorted(
            {_bounded_integer(day, "weekday", 0, 6) for day in days}
        )
    elif mode in {"monthly", "yearly"}:
        pattern_type = schedule.get("pattern_type")
        if pattern_type not in SCHEDULE_PATTERN_TYPES:
            raise exceptions.AIException(
                "Calendar task schedule requires a valid pattern_type."
            )
        normalized["pattern_type"] = pattern_type
        if pattern_type == "specific_day":
            normalized["day"] = _bounded_integer(schedule.get("day"), "day", 1, 31)
        elif pattern_type == "ordinal_weekday":
            normalized["ordinal"] = _bounded_integer(
                schedule.get("ordinal"),
                "ordinal",
                -1,
                4,
                allowed={-1, 1, 2, 3, 4},
            )
            normalized["weekday"] = _bounded_integer(
                schedule.get("weekday"), "weekday", 0, 6
            )
        if mode == "yearly":
            normalized["month"] = _bounded_integer(
                schedule.get("month"), "month", 1, 12
            )
        description = _optional_text(schedule, "description")
        if not description:
            raise exceptions.AIException(
                "Calendar task schedule requires a description."
            )
        normalized["description"] = description
        normalized["user_prompt"] = (
            _optional_text(schedule, "user_prompt") or description
        )
    return normalized


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_creates_task_with_reviewed_schedule
# @features ai-report task-scheduling
# @dimensions persistence recurring
def apply_task_schedule(task, schedule):
    """Apply an already validated schedule without making another model call."""
    normalized = validate_task_schedule(schedule)
    kind = normalized.pop("kind")
    if "pattern_type" in normalized:
        normalized["type"] = normalized.pop("pattern_type")
    process = task.properties[kind]
    for key, value in normalized.items():
        setattr(process, key, value)
    process.complete = True
    return {"kind": kind, **normalized, "complete": True}
