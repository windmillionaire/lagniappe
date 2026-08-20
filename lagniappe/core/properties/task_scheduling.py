from ..tools import ai, dates
from ..exceptions import AIException, capture
from .base_process import ProcessProperty
from .base_property import Property


# @testable infrastructure
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.generate
# @covered-by lagniappe/core/properties/task_scheduling.py::ScheduleType.create
class ScheduleType(ProcessProperty):
    """Base class for all schedule types."""

    process_id = "schedule"
    _mode = None
    _prompt = None
    _user_prompt = None

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_scheduled
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @features task-scheduling
    # @dimensions ai-generation
    @property
    def generate(self):
        if self.error or not self.prompt:
            return False

        return True

    @property
    def prompt(self):
        return self._prompt

    @prompt.setter
    def prompt(self, value):
        mode = self._mode or self.mode
        if not mode:
            return

        self._user_prompt = value
        self._prompt = ai.scheduling_prompt(mode=mode, user_prompt=value)

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_scheduled
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @features task-scheduling
    # @dimensions ai-generation
    def create(self):
        if not self.prompt:
            return
        elif self._user_prompt == self.user_prompt:
            return

        try:
            result = ai.generate_schedule(self.prompt)
        except AIException as e:
            capture(e)
            self.error = str(e)
            return

        result["description"] = result.pop("text")
        result["user_prompt"] = self._user_prompt

        self.section.update(result)
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
    # @features task-scheduling
    # @dimensions recurring, update, validation, add
    def update(self, form_data):
        try:
            interval = int(form_data.get("interval"))
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
    _start_date = None

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @features task-scheduling
    # @dimensions periodic, update, validation
    def update(self, form_data):
        user_prompt = form_data.get("periodic-description")
        start_date = form_data.get("start-date")
        if not start_date:
            self.error = "Please provide a start date"
            return

        self._start_date = dates.user_date_string_to_utc_datetime(start_date)

        if user_prompt:
            self.prompt = user_prompt
        elif not user_prompt and not self.description:
            self.error = "Please provide a description"
            return

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_periodic
    # @features task-scheduling
    # @dimensions periodic, ai-generation
    def create(self):
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
    # @features task-scheduling
    # @dimensions scheduled, update, validation, add
    def update(self, form_data):
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
            self.prompt = user_prompt
        elif not user_prompt and not self.description:
            self.error = "Please provide a description"


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.value
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.update
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.active
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.skipped
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
class Schedule(Property):
    """Orchestrator for task scheduling (recurring, periodic, scheduled).

    Delegates to the active schedule type's ProcessProperty. Provides
    due date calculation and skipped-task detection.

    Get:
        schedule: The active schedule ProcessProperty (Recurring, Periodic, or Scheduled).
        skipped (int): Number of overdue occurrences since last completion.
        error (str | None): Error from the active schedule.
    """

    # Property Attributes
    _id = "schedule"
    _schedule = None
    _types = ("recurring", "periodic", "scheduled")

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_schedule
    # @features task-scheduling
    # @dimensions active-process, coordinator
    @property
    def value(self):
        if self.is_set:
            return self._value

        self._value = self.entity.get_process(self.id)

        return self._value

    # @testable true
    # @tests tests_unit/test_013a_task_scheduling.py::test_task_schedule
    # @features task-scheduling
    # @dimensions coordinator, update, active-process
    def update(self, form_data):
        new_schedule = None

        active = self.active

        if form_data.get("recurring"):
            new_schedule = self.entity.properties["recurring"]
        elif form_data.get("periodic"):
            new_schedule = self.entity.properties["periodic"]
        elif form_data.get("scheduled"):
            new_schedule = self.entity.properties["scheduled"]

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
    # @features task-scheduling
    # @dimensions active-process, coordinator
    @property
    def active(self):
        schedule = next(
            (s for s in self._types if s in self.value),
            None,
        )

        if schedule:
            return self.entity.properties[schedule]

        return None

    # @testable true
    # @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_recurring
    # @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled
    # @features task-scheduling
    # @dimensions skipped, recurring, periodic, scheduled
    @property
    def skipped(self):
        if not self.active:
            return 0
        elif self.active.section_id == "scheduled":
            return dates.calculate_skipped_scheduled_tasks(
                self.entity, self.active.section
            )
        elif self.active.section_id == "periodic":
            return dates.calculate_skipped_recurring_tasks(
                self.entity, self.active.section
            )
        return 0

    # @testable true
    # @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_recurring
    # @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_scheduled
    # @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_periodic
    # @features task-scheduling
    # @dimensions next-due-date, recurring, scheduled, periodic, postponed
    def set_next_due_date(self):
        if not self.active:
            return

        if self.active.section_id == "recurring":
            next_due_date = dates.get_next_recurring_date(self.active.section)
        elif self.active.section_id == "scheduled":
            starting_due_date = dates.get_starting_due_date(self.entity)
            next_due_date = dates.get_next_scheduled_date(
                starting_due_date, self.active.section
            )
        elif self.active.section_id == "periodic":
            starting_due_date = dates.get_starting_due_date(self.entity)
            next_due_date = dates.get_next_periodic_date(
                starting_due_date, self.active.section
            )

        self.entity.due_date = max(next_due_date, dates.user_today())
        self.entity.db.pop("postponed_from", None)

    # @testable true
    # @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_remove_schedule
    # @features task-scheduling
    # @dimensions scheduled, remove
    def clear(self):
        self._value = {}
        self.entity.processes.pop(self.id, None)
        self.entity.db.pop(self.id, None)
