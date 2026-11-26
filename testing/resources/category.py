"""
Category resource for creation and index page interaction.

Categories are containers for pages. They can have an attached form
that defines fields for pages in the category.

Related Files:
    Application:
        - lagniappe/core/entities/category.py: Category entity
        - lagniappe/web/routes/categories/main.py: Category routes
        - lagniappe/web/templates/categories/index.html: Category index page
        - src/script/views/category.mjs: Category page JavaScript

    Test Framework:
        - testing/definitions/categories.py: Categories enum using this resource
        - testing/definitions/category_definitions.py: CategoryDefinition dataclass

Creation Flow:
    1. Navigate to home page
    2. Open create category form
    3. Fill name (manual) or AI description (AI mode)
    4. Optionally select form to attach
    5. Submit and capture key/url from new list item

Category Index Page:
    The category index (/categories/{key}) shows a table of pages
    in the category with tools panel for:
    - Creating new pages
    - Viewing/editing category info
    - Managing filters
"""

from playwright.sync_api import expect

from lagniappe.core.entities import Entities

from .core import SiteResource


class Category(SiteResource):
    """
    Resource for Category entity and its index page.

    Provides:
        - create(): Creates category programmatically
        - Selectors for category index page elements
        - Helper methods for tools panel widgets

    Selectors (for category index page):
        CREATE_PAGE_*: Create page form in tools panel
        CATEGORY_INFO_*: Category info/edit form
        CATEGORY_FILTERS_*: Filter management
        TABLE: Main pages table (#table)

    Properties:
        schema: Form field definitions if category has attached form
    """

    _initialize = True
    _sync = True

    # --- Header & Inline Controls ---
    CREATE_PAGE_TOGGLE = "button[lp-show='tools:CreatePage']"
    CREATE_PAGE_WIDGET = "[data-widget='CreatePage']"

    CATEGORY_TITLE = "[data-nav='view'] [data-role='title']"
    CATEGORY_DESCRIPTION = "[data-role='description']"
    CATEGORY_DEFAULT_FORM = "[data-role='default-form']"

    FILTER_BAR_COMPONENT = "#filter-bar"
    FILTER_BAR_WIDGET = "[data-widget='FilterBar']"

    # --- Page Table ---
    TABLE = "#table"
    TABLE_BODY = "#table tbody"
    VISIBLE_DATA_ROW = f"{TABLE} tbody tr:not([data-role='empty']):visible"
    VISIBLE_NAME_CELL = "td[data-column='name']:visible"
    EMPTY_ROW = "tr[data-role='empty']"
    TABLE_VISIBILITY_TOGGLE = "button[lp-show='table:TableVisibility']"
    TABLE_VISIBILITY_PANEL = "[data-widget='TableVisibility']"
    TABLE_SORTING_PANEL = "[data-widget='TableSorting']"
    COLUMN_HEADER = "th[data-column='{column}']"
    COLUMN_FILTER_BUTTON = "th[data-column='{column}'] button[data-toggle='filter']"

    def create(self):
        """
        Create category entity programmatically.

        Uses the same Entities.CATEGORY().create() path as the route handler
        in lagniappe/web/routes/categories/main.py.
        """
        assert self.definition, "Definition is required to create a category"

        form_resource = (
            self.definition.form.get(self.user) if self.definition.form else None
        )

        data = {
            "name": self.definition.name,
            "form": form_resource.entity if form_resource else None,
        }

        entity = Entities.CATEGORY.create(data)
        entity.save()
        self.entity = entity
        return self

    def initialize_view(self):
        super().initialize_view()
        table_body = self.user.locate(self.TABLE_BODY)
        expect(table_body).to_have_attribute("loaded", "")

    @property
    def url_suffix(self):
        return f"categories/{self.key}"

    def new_page_form(self):
        """
        Open and return the create page form from the category header button.

        Returns:
            Locator: The CreatePage widget form element
        """
        toggle = self.user.locate(self.CREATE_PAGE_TOGGLE)
        expect(toggle).to_be_visible()
        toggle.click()
        form = self.user.locate(self.CREATE_PAGE_WIDGET)
        expect(form).to_be_visible()
        return form

    def open_actions_menu(self):
        """Open and return the Category actions menu."""
        self.user.page.get_by_role("button", name="Category actions").click()
        menu = self.user.page.get_by_role("menu", name="Category actions")
        expect(menu).to_be_visible()
        return menu

    @property
    def filter_section(self):
        bar = self.user.locate(self.FILTER_BAR_COMPONENT)
        expect(bar).to_be_visible()
        return bar
