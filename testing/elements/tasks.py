import re
from enum import Enum

from playwright.sync_api import expect

from .combobox import Dropdown

TASK_CHANGE_DUE_DATE = "button[data-role='change-due-date']"
THIS_WEEK_MENU = "This Week…"
NEXT_WEEK_MENU = "Next Week…"


class PostponeDropdown(Enum):
    TOMORROW = ("primary", "Tomorrow")
    THIS_MONDAY = ("this-week", "Monday")
    THIS_TUESDAY = ("this-week", "Tuesday")
    THIS_WEDNESDAY = ("this-week", "Wednesday")
    THIS_THURSDAY = ("this-week", "Thursday")
    THIS_FRIDAY = ("this-week", "Friday")
    THIS_SATURDAY = ("this-week", "Saturday")
    THIS_SUNDAY = ("this-week", "Sunday")
    NEXT_MONDAY = ("next-week", "Monday")
    NEXT_TUESDAY = ("next-week", "Tuesday")
    NEXT_WEDNESDAY = ("next-week", "Wednesday")
    NEXT_THURSDAY = ("next-week", "Thursday")
    NEXT_FRIDAY = ("next-week", "Friday")
    NO_DUE_DATE = ("primary", "No Due Date")

    @classmethod
    def open(cls, task_item):
        element = task_item.locator(TASK_CHANGE_DUE_DATE)
        dropdown = Dropdown(element)
        panel = dropdown.open()
        return dropdown, panel

    @classmethod
    def open_this_week(cls, task_item):
        dropdown, panel = cls.open(task_item)
        panel.get_by_role("option", name=THIS_WEEK_MENU, exact=True).click()
        expect(panel).to_be_visible()
        return dropdown, panel

    @classmethod
    def open_next_week(cls, task_item):
        dropdown, panel = cls.open(task_item)
        panel.get_by_role("option", name=NEXT_WEEK_MENU, exact=True).click()
        expect(panel).to_be_visible()
        return dropdown, panel

    def select(self, task_item):
        scope, label = self.value
        if scope == "this-week":
            dropdown, panel = self.open_this_week(task_item)
            option = panel.get_by_role("option", name=re.compile(rf"^{label} · "))
            expect(option).to_be_visible()
        elif scope == "next-week":
            dropdown, panel = self.open_next_week(task_item)
            option = panel.get_by_role("option", name=re.compile(rf"^{label} · "))
            expect(option).to_be_visible()
        else:
            element = task_item.locator(TASK_CHANGE_DUE_DATE)
            dropdown = Dropdown(element)
            option = None

        with task_item.page.expect_response("**/change-due-date"):
            if option is not None:
                option.click()
            else:
                dropdown.select_by_name(label)

        expect(dropdown.panel).to_be_hidden()
