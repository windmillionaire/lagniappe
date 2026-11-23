from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..entities.task import Task
    from ..tools.ai.prompt import Prompt

    from ..tools.tasks.scheduling import Recurrence, ScheduleRule

    class _ScheduleParameters(Recurrence, ScheduleRule):
        """Calendar or interval fields read from a persisted schedule section."""

from ..tools import dates
from ..tools.ai import dates as ai_dates
from ..tools.tasks import scheduling
from ..exceptions import AIException, capture
from .base_process import ProcessProperty
from .base_property import Property


# @testable infrastructure
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.generate
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.create
class ScheduleType(ProcessProperty):
    """Base class for all schedule types."""

    section_id: str
    process_id = "schedule"
    _mode: str | None = None
    _prompt: Prompt | None = None
    _user_prompt: str | None = None

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_scheduled
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @pair task-scheduling:ai-generation
    @property
    def generate(self) -> bool:
        return not (self.error or not self.prompt)

    @property
    def prompt(self) -> Prompt | None:
        return self._prompt

    @prompt.setter
    def prompt(self, value: str | None) -> None:
        mode = self._mode or cast("str | None", self.mode)
        if not mode:
            return

        self._user_prompt = value
        self._prompt = ai_dates.scheduling_prompt(mode=mode, user_prompt=value)

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_scheduled
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @pair task-scheduling:ai-generation
    # @tests tests_unit/test_013a_task_scheduling.py::test_generated_schedule_prompt_survives_reload_and_avoids_regeneration
    # @matrix task-scheduling : periodic scheduled prompt-reuse
    def create(self) -> None:
        if not self.prompt or self._user_prompt == self.user_prompt:
            return

        try:
            result = ai_dates.generate_schedule(self.prompt)
        except AIException as e:
            capture(e)
            self.error = str(e)
            return

        result["description"] = result.pop("text")
        result["user-prompt"] = self._user_prompt

        self.section.update(result)
        self.section.pop("user_prompt", None)  # Retire the old spelling on regeneration.
        self.complete = True


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Recurring.update
class Recurring(ScheduleType):
    """Simple recurring schedule (e.g. every N days/weeks/months).

    Attributes: interval (int), unit (str).
    """

    # Property Attributes
    section_id = "recurring"
    attributes = ("interval", "unit")

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_recurring
    # @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_add_recurring
    # @matrix task-scheduling : add recurring update validation
    def update(self, form_data: Mapping[str, object]) -> None:
        try:
            interval = int(cast("str | int", form_data.get("interval")))
        except ValueError:
            self.error = "Invalid interval"
            return

        self.interval = interval
        self.unit = form_data.get("unit")

        self.complete = True


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Periodic.update
# @covered-by lagniappe/core/properties/task_scheduling.py::Periodic.create
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.generate
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.create
class Periodic(ScheduleType):
    """AI-generated periodic schedule from a natural-language description.

    The user provides a prompt (e.g. "every other Tuesday"), which is
    sent to AI to generate interval/unit parameters.

    Attributes: user_prompt, description, unit, interval.
    """

    # Property Attributes
    section_id = "periodic"
    attributes = ("user_prompt", "description", "unit", "interval")
    _mode = "periodic"
    _start_date: datetime | None = None

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @matrix task-scheduling : periodic update validation
    def update(self, form_data: Mapping[str, object]) -> None:
        user_prompt = form_data.get("periodic-description")
        start_date = form_data.get("start-date")
        if not start_date:
            self.error = "Please provide a start date"
            return

        self._start_date = dates.user_date_string_to_utc_datetime(cast(str, start_date))

        if user_prompt:
            self.prompt = cast(str, user_prompt)
        elif not user_prompt and not self.description:
            self.error = "Please provide a description"
            return

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @matrix task-scheduling : ai-generation periodic
    def create(self) -> None:
        super().create()
        self.entity.due_date = self._start_date


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Scheduled.update
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.generate
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.create
class Scheduled(ScheduleType):
    """Calendar-based schedule (daily, weekly, monthly, yearly).

    Weekly mode stores selected day indices directly. Monthly/yearly
    modes use AI to generate day/ordinal/weekday/month parameters
    from a natural-language prompt.
    """

    # Property Attributes
    section_id = "scheduled"
    attributes = (
        "mode",
        "user_prompt",
        "description",
        "days",
        "type",
        "day",
        "ordinal",
        "weekday",
        "month",
    )

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_scheduled
    # @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_add_schedule
    # @matrix task-scheduling : add scheduled update validation
    def update(self, form_data: Mapping[str, object]) -> None:
        self.mode = form_data.get("schedule-type")

        if self.mode == "daily":
            return
        elif self.mode == "weekly":
            days = [f"weekly-day-{i}" for i in range(0, 7)]
            self.days = [int(key.split("-")[-1]) for key in days if form_data.get(key)]
            return

        user_prompt = form_data.get("monthly-description") or form_data.get(
            "yearly-description"
        )

        if user_prompt:
            self.prompt = cast(str, user_prompt)
        elif not user_prompt and not self.description:
            self.error = "Please provide a description"


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.value
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.update
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.active
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.skipped
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
class Schedule(Property[dict[str, object], "Task"]):
    """Orchestrator for task scheduling (recurring, periodic, scheduled).

    Delegates to the active schedule type's ProcessProperty. Provides
    due date calculation and skipped-task detection.

    Get:
        schedule: The active schedule ProcessProperty (Recurring, Periodic, or Scheduled).
        skipped (int): Additional missed occurrences after the due-date baseline,
            excluding the original outstanding occurrence and today.
        error (str | None): Error from the active schedule.
    """

    # Property Attributes
    _id = "schedule"
    _schedule = None
    _types = ("recurring", "periodic", "scheduled")

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_schedule
    # @matrix task-scheduling : active-process coordinator
    @property
    def value(self) -> dict[str, object]:  # pyright: ignore[reportIncompatibleMethodOverride] -- The coordinator exposes its live section read-only.
        if self.is_set:
            return cast("dict[str, object]", self._value)

        self._value = self.entity.get_process(self.id)

        return self._value

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_schedule
    # @matrix task-scheduling : active-process coordinator update
    def update(self, form_data: Mapping[str, object]) -> ScheduleType | None:
        new_schedule = None

        active = self.active

        if form_data.get("recurring"):
            new_schedule = self.entity.properties.recurring
        elif form_data.get("periodic"):
            new_schedule = self.entity.properties.periodic
        elif form_data.get("scheduled"):
            new_schedule = self.entity.properties.scheduled

        if new_schedule:
            new_schedule.update(form_data)
        else:
            self.clear()
            return None

        if active and active.section_id != new_schedule.section_id:
            active.clear()
            self.value.pop(active.section_id, None)

        return new_schedule

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_schedule
    # @matrix task-scheduling : active-process coordinator
    @property
    def active(self) -> ScheduleType | None:
        schedule = next(
            (s for s in self._types if s in self.value),
            None,
        )

        if schedule:
            # Every validated name maps to a ScheduleType in the Task registry.
            return cast(ScheduleType, self.entity.properties[schedule])

        return None

    # @testable true
    # @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_recurring
    # @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled
    # @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled_counts_only_occurrences_between_baseline_and_today
    # @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled_preserves_earliest_due_date_baseline
    # @matrix task-scheduling : periodic recurring scheduled skipped
    @property
    def skipped(self) -> int:
        active = self.active
        if not active:
            return 0
        parameters = cast("_ScheduleParameters", active.section)
        if active.section_id == "scheduled":
            return scheduling.calculate_skipped_scheduled_tasks(
                self.entity, parameters
            )
        elif active.section_id == "periodic":
            return scheduling.calculate_skipped_recurring_tasks(
                self.entity, parameters
            )
        return 0

    # @testable true
    # @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_recurring
    # @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_scheduled
    # @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_periodic
    # @matrix task-scheduling : next-due-date periodic postponed recurring scheduled
    def set_next_due_date(self) -> None:
        task: Task = self.entity
        active = self.active
        if not active:
            return
        parameters = cast("_ScheduleParameters", active.section)

        if active.section_id == "recurring":
            next_due_date = scheduling.get_next_recurring_date(parameters)
        elif active.section_id == "scheduled":
            starting_due_date = scheduling.get_starting_due_date(task)
            next_due_date = scheduling.get_next_scheduled_date(
                starting_due_date, parameters
            )
        elif active.section_id == "periodic":
            starting_due_date = scheduling.get_starting_due_date(task)
            next_due_date = scheduling.get_next_periodic_date(
                starting_due_date, parameters
            )

        else:
            raise ValueError(f"Unknown schedule type: {active.section_id!r}")

        if next_due_date is None:
            raise TypeError("Schedule has no next due date")
        task.due_date = max(next_due_date, scheduling.user_today())
        task.db.pop("postponed_from", None)

    # @testable true
    # @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_remove_schedule
    # @matrix task-scheduling : remove scheduled
    def clear(self) -> None:
        clear_pending = getattr(self.entity, "_clear_scheduled_uncomplete", None)
        if clear_pending:
            clear_pending()
        self._value = {}
        self.entity.processes.pop(self.id, None)
        self.entity.db.pop(self.id, None)
