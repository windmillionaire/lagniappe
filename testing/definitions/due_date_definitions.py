from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from playwright.sync_api import expect


class DueDateOptions(Enum):
    TODAY = "Today"
    REPEATS_WHEN_COMPLETED = "recurring"
    REPEATS_ON_SCHEDULE = "scheduled"
    REPEATS_PERIODICALLY = "periodic"

    def set(self, form):
        if self == DueDateOptions.TODAY:
            button = form.get_by_role("button", name=self.value)
            expect(button).to_be_visible()
            button.click()
        else:
            button = form.locator(f'[name="{self.value}"]')
            expect(button).to_be_visible()
            button.click()


class DueDateUnit(Enum):
    DAYS = "day"
    WEEKS = "week"
    MONTHS = "month"
    YEARS = "year"

    def set(self, form):
        radio = form.locator(f'input[name="unit"][value="{self.value}"]')
        expect(radio).to_be_visible()
        radio.check()


class DueDateScheduleType(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"

    def set(self, form):
        radio = form.locator(f'input[name="schedule-type"][value="{self.value}"]')
        expect(radio).to_be_visible()
        radio.check()


class DueDateScheduleDay(Enum):
    MONDAY = "weekly-day-0"
    TUESDAY = "weekly-day-1"
    WEDNESDAY = "weekly-day-2"
    THURSDAY = "weekly-day-3"
    FRIDAY = "weekly-day-4"
    SATURDAY = "weekly-day-5"
    SUNDAY = "weekly-day-6"

    def set(self, form):
        checkbox = form.locator(f'input[name="{self.value}"]')
        expect(checkbox).to_be_visible()
        checkbox.check()


@dataclass
class DueDateDefinition:
    option: Optional[DueDateOptions] = None
    due_date: Optional[str] = None
    days_from_today: Optional[int] = None
    unit: Optional[DueDateUnit] = None
    interval: Optional[int] = None
    schedule_type: Optional[DueDateScheduleType] = None
    weekly_days: Optional[List[DueDateScheduleDay]] = field(default_factory=list)
    description: Optional[str] = None
