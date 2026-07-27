from enum import Enum

from playwright.sync_api import expect

from testing.utility.local_time import local_date_plus_days_iso

from .due_date_definitions import (
    DueDateDefinition,
    DueDateOptions,
)


class DueDates(Enum):
    personal_task_due_today = DueDateDefinition(
        option=DueDateOptions.TODAY,
    )
    personal_task_due_in_four_days = DueDateDefinition(
        due_date=local_date_plus_days_iso(4),
    )

    def set(self, form):
        if self.value.due_date:
            due_date_input = form.locator('[name="due-date"]')
            expect(due_date_input).to_be_visible()
            due_date_input.fill(self.value.due_date)

        if self.value.option:
            self.value.option.set(form)

        if self.value.interval:
            interval_input = form.locator('[name="interval"]')
            expect(interval_input).to_be_visible()
            interval_input.fill(str(self.value.interval))

        if self.value.unit:
            self.value.unit.set(form)

        if self.value.schedule_type:
            self.value.schedule_type.set(form)

        if self.value.description:
            schedule_type = self.value.schedule_type.value
            description_input = form.locator(f'[name="{schedule_type}-description"]')
            expect(description_input).to_be_visible()
            description_input.fill(self.value.description)

        for day in self.value.weekly_days:
            day.set(form)
