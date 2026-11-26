from enum import Enum
import re

from playwright.sync_api import expect

from .combobox import Select


class ProjectFilterConditions(Enum):
    NAME = "Task Name"
    CATEGORY = "In Categories"
    DUE_DATE = "Due Date"
    ASSIGNED_TO = "Assigned To"
    COMPLETED = "Completed"
    HAS_STATUS = "Has Status"


class CategoryFilterConditions(Enum):
    NAME = "Page Name"
    DESCRIPTION = "Description"
    CATEGORY = "In Categories"
    DOCUMENT = "Has Document"
    IMAGE = "Has Image"
    PUBLIC = "Is Public"
    MODIFIED = "Modified"


class Filters:
    """Interaction helper for the shared FilterBar widget on categories and projects.

    Each condition-type method (name_contains, checkbox, due_date, etc.)
    configures options in the currently visible FilterBar add-popover form,
    then returns ``self`` for chaining. Adding a condition auto-runs the
    filter against the page's live IndexTable (``#table`` on categories,
    ``#project-tasks-table`` on projects):

        filters.set_condition(...)   # open add-popover, select field, wait for condition response
        filters.<type>(...)          # configure the options form inside the popover
        badges = filters.add_filter()  # apply options, wait for options + test responses, return chips
        results = filters.run()      # wait for idle match status and return results table

    For dynamic entity conditions (model tasks, attached forms) selecting the
    condition appends a chip and runs immediately without an options step:

        filters.set_condition(model_task_resource)
        results = filters.run()
    """

    FORM = "[data-widget='FilterBar']"

    ADD_TRIGGER = "button[data-role='add-trigger']"
    ADD_POPOVER = "[data-role='add-popover']"
    SAVED_TRIGGER = "button[data-role='saved-trigger']"
    SAVED_POPOVER = "[data-role='saved-popover']"

    SAVE_BUTTON = "button[data-role='save-filter']"
    RESET_BUTTON = "button[data-role='clear-filters']"
    BAR_ACTIONS = "[data-role='bar-actions']"
    MATCH_STATUS = "[data-role='match-status']"

    ERROR = "[data-role='popover-error']"
    ADD_FILTER_BUTTON = "button[data-role='add-filter']"

    BADGES = "[data-role='chips']"

    NAME_CONTAINS = "label:has-text('contains')"
    NAME_EQUALS = "label:has-text('matches')"
    NAME_VALUE = "[name='name_value']"

    def __init__(self, user, entity):
        self.user = user
        self.entity = entity

        self.section = entity.filter_section
        self.form = self.section.locator(self.FORM)
        expect(self.form).to_be_visible()

        table_target = self.form.get_attribute("data-table-target") or "table"
        self.results_table = self.user.locate(f"#{table_target}")

    @property
    def add_trigger(self):
        return self.form.locator(self.ADD_TRIGGER)

    @property
    def add_popover(self):
        return self.form.locator(self.ADD_POPOVER)

    @property
    def saved_trigger(self):
        return self.form.locator(self.SAVED_TRIGGER)

    @property
    def saved_popover(self):
        return self.form.locator(self.SAVED_POPOVER)

    @property
    def bar_actions(self):
        return self.form.locator(self.BAR_ACTIONS)

    @property
    def match_status(self):
        return self.form.locator(self.MATCH_STATUS)

    @property
    def options(self):
        return self.add_popover.locator("form")

    def open_add_popover(self):
        if self.add_popover.get_attribute("data-visible") != "true":
            self.add_trigger.click()
            expect(self.add_popover).to_have_attribute("data-visible", "true")
        return self.add_popover

    def open_saved_popover(self, *, expect_fetch=False):
        if self.saved_popover.get_attribute("data-visible") != "true":
            if expect_fetch:
                with self.user.page.expect_response("**/filters/*/get?**"):
                    self.saved_trigger.click()
            else:
                self.saved_trigger.click()
            expect(self.saved_popover).to_have_attribute("data-visible", "true")
        expect(self.saved_popover).not_to_contain_text("Loading")
        return self.saved_popover

    def field_option(self, label):
        return self.add_popover.locator("button").filter(
            has=self.user.page.locator(
                "span.truncate", has_text=re.compile(rf"^{re.escape(label)}$")
            )
        )

    def set_condition(self, condition):
        """Select a filter condition and wait for the condition response."""
        self.open_add_popover()
        all_fields_btn = self.add_popover.get_by_role("button", name="All fields")
        if all_fields_btn.count() and all_fields_btn.is_visible():
            all_fields_btn.click()

        is_core = isinstance(
            condition,
            (ProjectFilterConditions, CategoryFilterConditions),
        )
        label = condition.value if is_core else condition.definition.name
        option = self.field_option(label)
        expect(option).to_be_visible()

        if is_core:
            with self.user.page.expect_response("**/filters/*/condition?**"):
                option.click()
            expect(self.options).to_be_visible()
        else:
            with (
                self.user.page.expect_response("**/filters/*/condition?**"),
                self.user.page.expect_response("**/filters/*/test?**"),
            ):
                option.click()
            expect(self.match_status).not_to_have_text("Filtering…")
        return self

    def set_form_condition(self, condition):
        """Select a secondary field from an attached-form condition."""
        self.open_add_popover()
        option = self.field_option(condition)
        expect(option).to_be_visible()

        with self.user.page.expect_response("**/filters/*/condition?**"):
            option.click()
        expect(self.options).to_be_visible()
        return self

    @property
    def save_button(self):
        return self.form.locator(self.SAVE_BUTTON)

    @property
    def reset_button(self):
        return self.form.locator(self.RESET_BUTTON)

    @property
    def error(self):
        return self.add_popover.locator(self.ERROR)

    @property
    def badges(self):
        return self.form.locator(self.BADGES)

    def run(self):
        expect(self.match_status).not_to_have_text("Filtering…")
        return self.results_table

    def add_filter(self):
        with (
            self.user.page.expect_response("**/filters/*/options?**"),
            self.user.page.expect_response("**/filters/*/test?**"),
        ):
            self.add_popover.locator(self.ADD_FILTER_BUTTON).click()
        expect(self.add_popover).to_have_attribute("data-visible", "false")
        expect(self.match_status).not_to_have_text("Filtering…")
        return self.badges

    def save_filter(self):
        expect(self.save_button).to_be_visible()
        with self.user.page.expect_response("**/filters/*/save") as response_info:
            self.save_button.click()
        response = response_info.value
        assert response.ok, f"Saving filter failed with HTTP {response.status}"

        payload = response.json()
        saved = payload.get("filter") or {}
        assert saved.get("key"), "Saved-filter response did not identify the created filter"
        return saved

    def reset(self):
        expect(self.reset_button).to_be_visible()
        self.reset_button.click()
        expect(self.bar_actions).to_have_attribute("data-visible", "false")
        expect(self.results_table.locator("tbody")).to_have_attribute("loaded", "")

    # --- String conditions (Task Name) ---

    def text(self, comparator, value, field=None):
        """Select a string comparator and fill the visible text value."""
        options = self.options
        options.get_by_text(comparator, exact=True).click()

        input_selector = (
            f"[name='{field}_value']" if field else "input[type='text'][name$='_value']"
        )
        input = options.locator(input_selector)
        expect(input).to_be_visible()
        input.fill(value)
        return self

    def name_contains(self, value):
        return self.text("contains", value, field="name")

    def name_equals(self, value):
        return self.text("matches", value, field="name")

    # --- Boolean conditions ---

    def boolean(self, status):
        """Click a boolean status radio by its label text."""
        options = self.options
        label = options.get_by_text(status, exact=True)
        expect(label).to_be_visible()
        label.click()
        return self

    def checkbox(self, checked=True):
        return self.boolean("checked" if checked else "not checked")

    # --- Range / timestamp conditions (Due Date) ---

    def range(self, comparator, value, field=None):
        """Select a range comparator and fill the single-value input."""
        options = self.options
        options.get_by_text(comparator, exact=True).click()

        input_selector = (
            f"[name='{field}_value']" if field else "[data-role='single'] input"
        )
        input = options.locator(input_selector)
        expect(input).to_be_visible()
        input.fill(str(value))
        return self

    def due_date(self, comparator, value):
        """Select a date comparator label and fill the date value."""
        return self.range(comparator, value, field="due_date")

    def number(self, comparator, value):
        return self.range(comparator, value)

    def between(self, comparator, value_from, value_to, field=None):
        options = self.options
        options.get_by_text(comparator, exact=True).click()

        from_selector = (
            f"[name='{field}_value_from']"
            if field
            else "[data-role='range'] [name$='_value_from']"
        )
        to_selector = (
            f"[name='{field}_value_to']"
            if field
            else "[data-role='range'] [name$='_value_to']"
        )
        options.locator(from_selector).fill(str(value_from))
        options.locator(to_selector).fill(str(value_to))
        return self

    # --- List / facets conditions (Categories, Assigned To) ---

    def choice(self, name):
        """Select from the visible options combobox."""
        options = self.options
        select = Select(options.locator("[lp-select]"))
        select.select_by_name(name)
        return self

    def category(self, name):
        return self.choice(name)

    def assigned_to(self, name):
        return self.choice(name)
