"""
Home page resource with selectors for all dashboard components.

The home page is the main dashboard for authenticated users, containing
collapsible components for pages, projects, categories, tasks, starred items,
notes, directory links, and tools.

Related Files:
    Application:
        - lagniappe/web/routes/home/main.py: Home route (/)
        - lagniappe/web/templates/home/home.html: Main template
        - lagniappe/web/templates/home/pages.html: Page component
        - lagniappe/web/templates/home/projects.html: Project component
        - lagniappe/web/templates/home/categories.html: Category component
        - lagniappe/web/templates/home/tasks.html: Task component
        - lagniappe/web/templates/home/starred.html: Starred component
        - lagniappe/web/templates/home/notes.html: Notes component
        - lagniappe/web/templates/home/tools.html: Tools component
        - src/script/views/home.mjs: View initialization
        - src/script/widgets/home/: Home list, activity, and task widget classes

    Core Entity:
        - lagniappe/core/entities/home.py: Home entity

Selector Patterns:
    Each component follows a consistent pattern:
    - *_COMPONENT: The lp-component container (#id[lp-component])
    - *_LIST_TOGGLE: Button to show/hide the list (button[lp-show][data-toggle])
    - CREATE_*_TOGGLE: Button to show/hide creation form
    - CREATE_*_FORM: The creation form (form[data-widget='...'])
    - *_LIST: The list container (e.g. #tasks ul[data-widget='HomeTaskList'])

Usage:
    home = user.go(SitePages.HOME)
    user.locate(home.PROJECT_LIST_TOGGLE).click()
    project_list = List(user.locate(home.PROJECT_LIST))
    assert project_list.is_loaded
"""

import re
from html.parser import HTMLParser

from playwright.sync_api import expect

from ..elements import List, SpinnerButtons, FormElements

from .site import SitePage


class _DataKeyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.key = None

    def handle_starttag(self, tag, attrs):
        if self.key:
            return
        attr_map = dict(attrs)
        if "data-key" in attr_map:
            self.key = attr_map["data-key"]


class HomePage(SitePage):
    """
    Home page resource with selectors for dashboard components.

    Organized by component section. Each section typically has:
    - Component container (lp-component)
    - List toggle button
    - Create toggle button
    - Create form
    - List container
    """

    _initialize = True
    _sync = True

    # --- Page Section ---
    # Template: lagniappe/web/templates/home/home.html
    PAGES_COMPONENT = "#pages[lp-component]"
    PAGE_LIST_TOGGLE = "button[lp-show='pages:HomePageList'][data-toggle]"
    CREATE_PAGE_TOGGLE = "button[lp-show='pages:CreatePage'][data-toggle]"
    CREATE_PAGE_FORM = "form[data-widget='CreatePage']"
    PAGE_LIST = "#pages ul[data-widget='HomePageList']"
    PAGE_LOADING = (
        "#pages [data-role='list-loading']"
        "[data-indicator='HomePageList']"
    )

    # --- Project Section ---
    # Template: lagniappe/web/templates/home/home.html
    PROJECTS_COMPONENT = "#projects[lp-component]"
    PROJECT_LIST_TOGGLE = "button[lp-show='projects:HomeProjectList'][data-toggle]"
    CREATE_PROJECT_TOGGLE = "button[lp-show='projects:CreateProject'][data-toggle]"
    CREATE_PROJECT_FORM = "form[data-widget='CreateProject']"
    PROJECT_LIST = "#projects ul[data-widget='HomeProjectList']"
    PROJECT_LOADING = (
        "#projects [data-role='list-loading']"
        "[data-indicator='HomeProjectList']"
    )

    # --- Category Section ---
    # Template: lagniappe/web/templates/home/home.html
    CATEGORIES_COMPONENT = "#categories[lp-component]"
    CATEGORY_LIST_TOGGLE = "button[lp-show='categories:HomeCategoryList'][data-toggle]"
    CREATE_CATEGORY_TOGGLE = "button[lp-show='categories:CreateCategory'][data-toggle]"
    CREATE_CATEGORY_FORM = "form[data-widget='CreateCategory']"
    CATEGORY_LIST = "#categories ul[data-widget='HomeCategoryList']"
    CATEGORY_LOADING = (
        "#categories [data-role='list-loading']"
        "[data-indicator='HomeCategoryList']"
    )

    # --- Task Section ---
    # Template: lagniappe/web/templates/home/home.html
    # Loaded lazily when toggled open
    TASKS_COMPONENT = "#tasks[lp-component]"
    TASK_LIST_TOGGLE = "button[lp-show='tasks:HomeTaskList'][data-toggle]"
    CREATE_TASK_TOGGLE = "button[lp-show='tasks:CreateUserTask'][data-toggle]"
    CREATE_TASK_FORM = "form[data-widget='CreateUserTask']"
    TASK_LIST = "#tasks ul[data-widget='HomeTaskList']"
    TASK_COMPLETE_CHECKBOX = "input[data-role='complete']"
    TASK_COUNT = "[data-role='task-count']"
    USER_TASK_COUNT = "[data-role='user-task-count']"
    COMPLETE_TASK_CHECKBOX = "input[data-role='complete']"

    # --- User Page Section ---
    USER_PAGE_BUTTON = "a[data-kind='user']:has-text('My Page')"

    # --- Starred Section ---
    # Template: lagniappe/web/templates/home/home.html
    STARRED_COMPONENT = "#starred[lp-component]"
    STARRED_LIST_TOGGLE = "button[lp-show='starred:StarredList'][data-toggle]"
    STARRED_LIST = "#starred ul[data-widget='StarredList']"
    STARRED_COUNT = "[data-role='starred-count']"
    STARRED_LOADING = (
        "#starred [data-role='list-loading']"
        "[data-indicator='StarredList']"
    )

    # --- Notes Section ---
    # Template: lagniappe/web/templates/home/home.html
    # Uses HomeActivityList for Home-scoped notes.
    NOTES_COMPONENT = "#notes[lp-component]"
    NOTE_LIST_TOGGLE = "button[lp-show='notes:HomeActivityList'][data-toggle]"
    CREATE_NOTE_TOGGLE = "button[lp-show='notes:CreateNote'][data-toggle]"
    CREATE_NOTE_FORM = "form[data-widget='CreateNote']"
    NOTE_LIST = "#notes ul[data-widget='HomeActivityList']"
    NOTE_LOADING = (
        "#notes [data-role='list-loading']"
        "[data-indicator='HomeActivityList']"
    )

    # --- Directory Section ---
    # Template: lagniappe/web/templates/home/home.html (inline)
    # Contains navigation links to Tasks, Forms, Users
    DIRECTORY_COMPONENT = "#directory[lp-component]"
    DIRECTORY_LIST_TOGGLE = "button[lp-show='directory:DirectoryList'][data-toggle]"
    DIRECTORY_LIST = "#directory ul[data-widget='DirectoryList']"
    MANUAL_BUTTON = "a[href='/manual/'][data-kind='page']:has-text('Manual')"

    # --- Tools Section ---
    # Template: lagniappe/web/templates/home/home.html
    # For creating and running AI-generated tool reports.
    TOOLS_COMPONENT = "#tools[lp-component]"
    TOOL_REPORT_LIST_TOGGLE = "button[lp-show='tools:ToolReportList'][data-toggle]"
    CREATE_TOOL_REPORT_TOGGLE = (
        "button[lp-show='tools:CreateToolReport'][data-toggle]"
    )
    TOOL_REPORT_LIST = "#tools ul[data-widget='ToolReportList']"
    CREATE_TOOL_REPORT_FORM = "form[data-widget='CreateToolReport']"
    TOOL_REPORT_LOADING = (
        "#tools [data-role='list-loading']"
        "[data-indicator='ToolReportList']"
    )

    @staticmethod
    def entity_key_from_response(response):
        parser = _DataKeyParser()
        parser.feed(response.text())
        assert parser.key, "Create response did not include an entity data-key"
        return parser.key

    def initialize_view(self):
        super().initialize_view()
        assert List(self.user.locate(self.TASK_LIST)).is_loaded

    @property
    def url_suffix(self):
        return ""

    @property
    def user_task_count(self):
        task_list = List(self.user.locate(self.TASK_LIST))
        assert task_list.is_loaded
        return int(self.user.locate(self.TASK_COUNT).text_content())

    @property
    def user_page_button(self):
        return self.user.locate(self.USER_PAGE_BUTTON)

    def _open_loaded_list(self, list_selector, toggle_selector, wait_for_toggle=True):
        list_helper = List(self.user.locate(list_selector))

        if list_helper.list.get_attribute("data-visible") != "true":
            toggle = self.user.locate(toggle_selector)
            if wait_for_toggle:
                expect(toggle).not_to_have_class(
                    re.compile(".*pointer-events-none.*")
                )
            toggle.click()

        assert list_helper.is_loaded
        expect(list_helper.list).to_be_visible()
        return list_helper

    @property
    def task_list(self):
        """
        Open the task list and wait for lazy loading to complete.

        Returns:
            List: Helper wrapping the task list for item access
        """

        return self._open_loaded_list(self.TASK_LIST, self.TASK_LIST_TOGGLE)

    @property
    def page_list(self):
        """
        Get the page list after opening and ensuring it's loaded.
        """
        return self._open_loaded_list(self.PAGE_LIST, self.PAGE_LIST_TOGGLE)

    @property
    def activity_list(self):
        """
        Open the activity list and wait for prefetch loading to complete.

        Returns:
            List: Helper wrapping the Home note list
        """

        return self._open_loaded_list(
            self.NOTE_LIST,
            self.NOTE_LIST_TOGGLE,
            wait_for_toggle=False,
        )

    @property
    def starred_list(self):
        """
        Get the starred list after opening and ensuring it's loaded.

        Opens the starred list toggle and waits for the lp-load shell to clear, then returns a List helper.

        Returns:
            List: Helper wrapping the starred list for item access
        """
        return self._open_loaded_list(self.STARRED_LIST, self.STARRED_LIST_TOGGLE)

    @property
    def category_list(self):
        """
        Get the category list after opening and ensuring it's loaded.
        """
        return self._open_loaded_list(self.CATEGORY_LIST, self.CATEGORY_LIST_TOGGLE)

    @property
    def project_list(self):
        """
        Get the project list after opening and ensuring it's loaded.
        """
        return self._open_loaded_list(self.PROJECT_LIST, self.PROJECT_LIST_TOGGLE)

    def create_project_form(self):
        toggle = self.user.locate(self.CREATE_PROJECT_TOGGLE)
        toggle.click()
        create_form = self.user.locate(self.CREATE_PROJECT_FORM)
        expect(create_form).to_be_visible()
        expect(toggle).not_to_have_attribute(
            "aria-busy", "true", timeout=15000
        )
        return create_form

    def create_category_form(self):
        self.user.locate(self.CREATE_CATEGORY_TOGGLE).click()
        create_form = self.user.locate(self.CREATE_CATEGORY_FORM)
        expect(create_form).to_be_visible()
        return create_form

    def create_page_form(self):
        self.user.locate(self.CREATE_PAGE_TOGGLE).click()
        create_form = self.user.locate(self.CREATE_PAGE_FORM)
        expect(create_form).to_be_visible()
        return create_form

    def create_task_form(self):
        self.user.locate(self.CREATE_TASK_TOGGLE).click()
        create_form = self.user.locate(self.CREATE_TASK_FORM)
        expect(create_form).to_be_visible()
        return create_form

    @property
    def directory(self):
        """
        Get the directory list after opening and ensuring it's loaded.
        """
        directory = List(self.user.locate(self.DIRECTORY_LIST))
        if not directory.is_visible:
            self.user.locate(self.DIRECTORY_LIST_TOGGLE).click()

        assert directory.is_loaded
        expect(directory.list).to_be_visible()
        return directory

    def create_manual_project(self, project):
        definition = project.definition

        create_form = self.create_project_form()
        create_form.locator(FormElements.NAME).fill(definition.name)
        create_form.locator(FormElements.DESCRIPTION).fill(definition.description)
        with self.user.page.expect_response("**/create") as response_info:
            SpinnerButtons.CREATE.click(create_form)

        expect(create_form).not_to_be_visible()
        project.key = self.entity_key_from_response(response_info.value)
        project_list = self.project_list
        new_project_element = project_list.get_item(project)
        expect(new_project_element).to_be_visible()
        return new_project_element
