"""
Project resource for creation and project page interaction.

Projects are top-level containers that can have model tasks and documents.
They appear in the project list on the home page.

Related Files:
    Application:
        - lagniappe/core/entities/project.py: Project entity
        - lagniappe/web/routes/projects/main.py: Project routes
        - lagniappe/web/templates/projects/: Project page templates
        - src/script/views/project.mjs: Project page JavaScript

    Test Framework:
        - testing/definitions/projects.py: Projects enum using this resource
        - testing/definitions/project_definitions.py: ProjectDefinition dataclass

Creation Flow:
    1. Navigate to home page
    2. Open create project form
    3. Fill name/description (manual) or AI description (AI mode)
    4. Submit and capture key/url from new list item

Project Page:
    The project page (/projects/{key}) shows:
    - Model tasks card
    - Document tab
    - Info tab with project details
"""

from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from ..elements import Tabs, Editor
from .core import SiteResource


class Project(SiteResource):
    """
    Resource for Project entity and its page.

    Provides:
        - create(): Creates project programmatically
        - Selectors for project page elements

    Selectors (for project page):
        MODEL_TASKS_CARD: Container for model tasks (#models)
        CREATE_MODEL_*: Create model task form
        MODEL_TASKS_LIST: List of model tasks

    Mobile Selectors:
        MOBILE_NAV: Mobile navigation bar
        MOBILE_SECTION_TITLE: Section title in mobile nav
        MOBILE_SLIDER: Slider button to reveal section icons
        MOBILE_SECTION_ICONS: Container for section toggle buttons

    """

    _initialize = True
    _sync = True

    # --- Model Tasks Card ---
    MODEL_TASKS_CARD = "#model-tasks"
    CREATE_MODEL_BUTTON = "#model-tasks button[lp-show='model-tasks:CreateModelTask']"
    CREATE_MODEL_WIDGET = "[data-widget='CreateModelTask']"
    MODEL_TASKS_LIST = "#model-tasks [data-widget='ModelTaskList']"
    MODEL_TASK_INFO_FORM = "[data-widget='ModelTaskInfo']"

    # --- Tabs Card ---
    TABS_CARD = "#tabs"

    # --- Mobile Navigation ---
    MOBILE_NAV = "[lp-nav][data-nav='mobile']"
    MOBILE_SECTION_TITLE = "[lp-nav][data-nav='mobile'] [data-role='title']"
    MOBILE_SLIDER = "[lp-nav][data-nav='mobile'] [data-role='flipper']"
    MOBILE_SECTION_ICONS = "[lp-nav][data-nav='mobile'] .slide-left"
    MOBILE_SECTION_CONTROLS = "[lp-nav][data-nav='mobile'] [data-role='controls']"
    MOBILE_CREATE_MODEL_TASK_BUTTON = (
        "[lp-nav][data-nav='mobile'] button[lp-show='model-tasks:CreateModelTask']"
    )

    DOCUMENT_TOGGLE = "button[lp-show='document:active']"

    # --- Desktop Tab Nav ---
    DESKTOP_TAB_NAV = "#tabs [lp-nav][data-nav='tabs']"

    # --- Info Tab ---
    INFO_FORM = "[data-widget='ProjectInfo']"
    INFO_NAME = "#name"
    INFO_DESCRIPTION = "#description"

    # --- Filters Tab ---
    FILTERS_TAB = "#filters"

    # --- Project Page Header ---
    PROJECT_TITLE = "[data-nav='view'] [data-role='title']"
    PROJECT_DESCRIPTION = "[data-role='description']"

    def create(self):
        """
        Create project entity programmatically.

        Uses the same Entities.PROJECT.create() path as the route handler
        in lagniappe/web/routes/projects/main.py.
        """
        assert self.definition, "Definition is required to create a project"

        data = {
            "name": self.definition.name,
            "description": self.definition.description,
        }

        entity = Entities.PROJECT.create(data)
        entity.save()
        self.entity = entity
        return self

    def create_model_task_form(self):
        form_toggle = self.user.locate(self.CREATE_MODEL_BUTTON)
        expect(form_toggle).to_be_visible()
        form_toggle.click()

        create_form = self.user.locate(self.CREATE_MODEL_WIDGET)
        expect(create_form).to_be_visible()
        return create_form

    @property
    def url_suffix(self):
        return f"projects/{self.key}"

    @property
    def info_form(self):
        tabs = Tabs(self.user)

        info_tab = tabs.info
        expect(info_tab).to_be_visible()

        info_form = info_tab.locator(self.INFO_FORM)
        expect(info_form).to_have_attribute("rendered", "")

        return info_form

    @property
    def filter_section(self):
        tabs = Tabs(self.user)
        filters_tab = tabs.filters
        expect(filters_tab).to_be_visible()
        return filters_tab

    @property
    def editor(self):
        tabs = Tabs(self.user)

        document_tab = tabs.document
        expect(document_tab).to_be_visible()
        toolbar = document_tab.locator("[data-role='toolbar']")
        expect(toolbar).to_be_visible()
        return Editor(document_tab)

    @property
    def model_tasks_card(self):
        return self.user.locate(self.MODEL_TASKS_CARD)
