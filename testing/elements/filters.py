from enum import Enum

from playwright.sync_api import expect

from .combobox import Dropdown, Select


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
    """Interaction helper for project/category filters tabs.

    Each condition-type method (name_contains, checkbox, due_date, etc.)
    configures options in the currently visible options panel, then returns
    ``self`` for chaining.  The typical flow is:

        filters.set_condition(...)   # select from dropdown, wait for condition response
        filters.<type>(...)          # configure the options panel
        badges = filters.add_filter()  # submit options, wait for response, return badges
        results = filters.run()      # run the filter, wait for response, return results

    For dynamic entity conditions (model tasks) the condition response
    produces a filter badge directly -- no options panel or add_filter step:

        filters.set_condition(model_task_resource)
        results = filters.run()
    """

    FORM = "[data-widget='Filters']"

    SAVE_BUTTON = "button[data-role='save']"
    RUN_BUTTON = "button[data-role='run']"
    RESET_BUTTON = "button[data-role='reset']"

    CONDITIONS = "[data-role='conditions']"
    FORM_CONDITIONS = "[data-role='form-conditions']"
    ERROR = "[data-role='error']"
    ADD_FILTER_BUTTON = "button[data-role='add-filter']"

    OPTIONS = '[data-role="options"]'
    BADGES = "[data-role='filters']"

    NAME_CONTAINS = "label:has-text('contains')"
    NAME_EQUALS = "label:has-text('matches')"
    NAME_VALUE = "[name='name_value']"

    RESULTS = "[data-widget='FilterResults']"
    SAVED_FILTERS = "[data-role='saved-filters']"

    def __init__(self, user, entity):
        self.user = user
        self.entity = entity

        self.form = self.user.locate(self.FORM)
        self.section = entity.filter_section

        expect(self.form).to_be_visible()

    def set_condition(self, condition):
        """Select a filter condition and wait for the condition response."""
        select = Dropdown(self.form.locator(self.CONDITIONS))

        with self.user.page.expect_response("**/filters/*/condition?**"):
            if isinstance(
                condition,
                (ProjectFilterConditions, CategoryFilterConditions),
            ):
                select.select_by_name(condition.value)
            else:
                select.select_by_name(condition.definition.name)
        return self

    def set_form_condition(self, condition):
        """Select a secondary field from an attached-form condition."""
        form_conditions = self.form_conditions
        expect(form_conditions).to_be_visible()
        select = Dropdown(form_conditions)

        with self.user.page.expect_response("**/filters/*/condition?**"):
            select.select_by_name(condition)
        return self

    @property
    def save_button(self):
        return self.section.locator(self.SAVE_BUTTON)

    @property
    def run_button(self):
        return self.section.locator(self.RUN_BUTTON)

    @property
    def reset_button(self):
        return self.section.locator(self.RESET_BUTTON)

    @property
    def conditions(self):
        return self.section.locator(self.CONDITIONS)

    @property
    def form_conditions(self):
        return self.section.locator(self.FORM_CONDITIONS)

    @property
    def error(self):
        return self.section.locator(self.ERROR)

    @property
    def badges(self):
        return self.section.locator(self.BADGES)

    def run(self):
        with self.user.page.expect_response("**/filters/*/test?**"):
            self.run_button.click()
        return self.section.locator(self.RESULTS)

    def add_filter(self):
        with self.user.page.expect_response("**/filters/*/options?**"):
            self.section.locator(self.ADD_FILTER_BUTTON).click()
        return self.section.locator(self.BADGES)

    def save_filter(self):
        with self.user.page.expect_response("**/filters/*/save"):
            self.save_button.click()
        saved = self.user.page.locator(self.SAVED_FILTERS)
        expect(saved).to_be_visible()
        return saved

    def reset(self):
        self.reset_button.click()

    # --- String conditions (Task Name) ---

    def text(self, comparator, value, field=None):
        """Select a string comparator and fill the visible text value."""
        options = self.section.locator(self.OPTIONS)
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
        options = self.section.locator(self.OPTIONS)
        label = options.get_by_text(status, exact=True)
        expect(label).to_be_visible()
        label.click()
        return self

    def checkbox(self, checked=True):
        return self.boolean("checked" if checked else "not checked")

    # --- Range / timestamp conditions (Due Date) ---

    def range(self, comparator, value, field=None):
        """Select a range comparator and fill the single-value input."""
        options = self.section.locator(self.OPTIONS)
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
        options = self.section.locator(self.OPTIONS)
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
        options = self.section.locator(self.OPTIONS)
        select = Select(options.locator("[lp-select]"))
        select.select_by_name(name)
        return self

    def category(self, name):
        return self.choice(name)

    def assigned_to(self, name):
        return self.choice(name)
