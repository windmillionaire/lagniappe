"""
Task resource for page tasks and personal (home) tasks.

Tasks belong to a page (including the current user's personal page for
home-created tasks). E2E tests for creating personal tasks from the home
page should use HomePage.create_personal_task() rather than duplicating
form steps.

Related Files:
    Application:
        - lagniappe/core/entities/task.py: Task entity
        - lagniappe/web/routes/tasks/main.py: Task routes (create, update, personal)
        - lagniappe/web/templates/pages/tasks.html: Page task tab templates
        - lagniappe/web/templates/home/tasks.html: CreateUserTask / HomeTaskList
        - src/script/views/page.mjs: Page task components
        - src/script/widgets/taskSettings.mjs: CreateUserTask, BaseTaskSettings

    Test Framework:
        - testing/definitions/tasks.py: Tasks enum using this resource
        - testing/definitions/task_definitions.py: TaskDefinition dataclass
        - testing/resources/home.py: HomePage.create_personal_task for UI creation

Creation Flow:
    Programmatic (create()):
        1. Resolve parent page from definition.origin (Pages enum or user's page
           for SitePages.HOME).
        2. Optional project, model task, form from related definitions.
        3. Entities.TASK.create(...) and entity.save().

    Home UI:
        Use HomePage.create_personal_task(definition) after Tasks.*.get(user,
        create=False); it fills CreateUserTask and waits for POST **/personal.
"""

from datetime import datetime

from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.utility import expect_successful_response
from testing.utility.local_time import local_date_iso, local_date_plus_days_iso
from ..elements import DateSelect, SpinnerButtons
from .core import SiteResource


def _resolve_due_date(due_date_enum):
    """Convert a DueDates enum to a date string for the task entity."""
    if not due_date_enum:
        return None

    definition = due_date_enum.value

    if definition.due_date:
        return definition.due_date

    if definition.days_from_today is not None:
        return local_date_plus_days_iso(definition.days_from_today)

    from testing.definitions.due_date_definitions import DueDateOptions

    if definition.option == DueDateOptions.TODAY:
        return local_date_iso()

    return None


class Task(SiteResource):
    """
    Resource for Task entity and list row interactions.

    Selectors (task row on page or home list):
        ACTION_BUTTONS: Schedule/settings row (data-role='action-buttons')
        HEADER: Clickable header to expand settings (data-role='header')

    Methods:
        create(): Programmatic creation (page tasks, fixtures, personal tasks
            without UI).
        element / action_buttons: Locators for the task row.
        set_due_date(): Due date picker on an open task row.
        save(): Submit update after editing a task.
    """

    _initialize = True
    _sync = True

    ACTION_BUTTONS = "[data-role='action-buttons']"
    HEADER = "[data-role='header']"
    COMPLETE_TASK_CHECKBOX = "input[data-role='complete-toggle']"
    NAV_TOGGLES = "[data-role='nav-toggles']"
    PAGE_TASK_LIST = "[data-widget='PageTaskList']"

    SETTINGS_FORM_TOGGLE = "button[lp-control='task']"
    SETTINGS_FORM = "[data-widget='TaskSettings']"
    TASK_FORM_TOGGLE = "button[lp-control='form']"
    TASK_FORM = "[data-widget='TaskForm']"
    TASK_HISTORY_TOGGLE = "button[lp-control='history']:visible"
    TASK_HISTORY = "[data-widget='TaskHistory']"
    _element = None

    def create(self):
        """
        Create task entity programmatically.

        Uses the same Entities.TASK.create() path as the route handler
        in lagniappe/web/routes/tasks/main.py.

        Handles both page tasks (origin is a Pages enum) and personal
        tasks (origin is SitePages.HOME) by resolving the parent page.
        """
        from ..definitions import Pages

        assert self.definition, "Definition is required to create a task"
        assert self.definition.origin, "Origin is required to create a task"

        if isinstance(self.definition.origin, Pages):
            page_entity = self.definition.origin.get(self.user).entity
        else:
            user_entity = Entities.fetch_one(
                self.user.entity, request=Fetch.direct()
            )
            page_entity = user_entity.page

        project_resource = (
            self.definition.project.get(self.user) if self.definition.project else None
        )

        model_resource = (
            self.definition.model_task.get(self.user)
            if self.definition.model_task
            else None
        )

        if model_resource and model_resource.definition.form:
            form_resource = model_resource.definition.form.get(self.user)
        else:
            form_resource = (
                self.definition.form.get(self.user) if self.definition.form else None
            )

        if self.definition.submission:
            submission = {s.id: s.submission_value for s in self.definition.submission}
        else:
            submission = None

        assigned_to = None
        if self.definition.assigned_to:
            assigned_user = self.definition.assigned_to.get(self.user)
            assigned_to = assigned_user.entity.page if assigned_user else None

        data = {
            "name": self.definition.name,
            "description": self.definition.description or "",
            "page": page_entity,
            "model": model_resource.entity if model_resource else None,
            "project": project_resource.entity if project_resource else None,
            "form": form_resource.entity if form_resource else None,
            "due_date": _resolve_due_date(self.definition.due_date),
            "assigned_to": assigned_to,
            "submission": submission,
        }

        entity = Entities.TASK.create(data)
        entity = Entities.fetch_one(
            entity,
            request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
        )
        entity.save()

        self.entity = entity

        return self

    def wait_for_load(self):
        self.element = self.user.locate(f"[data-key='{self.key}']")
        expect(self.element).to_be_visible()

    def _wait_for_page_task_list(self):
        task_list = self.user.locate(self.PAGE_TASK_LIST)
        if task_list.count() == 0:
            return

        expect(self.user.locate("[lp-view]")).to_have_attribute("initialized", "")
        expect(task_list).to_have_attribute("loaded", "")
        if self.key:
            self.element = self.user.locate(f"[data-key='{self.key}']")

    @property
    def project(self):
        return self.definition.project.get(self.user)

    @property
    def url_suffix(self):
        return f"tasks/{self.key}"

    @property
    def element(self):
        if getattr(self, "_element", None):
            return self._element
        elif self.key:
            self._element = self.user.locate(f"[data-key='{self.key}']")
            return self._element
        else:
            raise ValueError("Task key is required to get the element")

    @element.setter
    def element(self, element):
        self._element = element

    @property
    def completed(self):
        return self.element.locator(self.COMPLETE_TASK_CHECKBOX).is_checked()

    def _open_task(self):
        nav_toggles = self.element.locator(self.NAV_TOGGLES)
        if nav_toggles.is_visible():
            self.element.locator(self.HEADER).click()
            expect(nav_toggles).to_be_hidden()

    def _close_task(self):
        nav_toggles = self.element.locator(self.NAV_TOGGLES)
        if nav_toggles.is_visible():
            return

        close_toggle = self.element.locator("[lp-control='close']:visible")
        if close_toggle.count() > 0:
            close_toggle.first.click()
        else:
            self.element.locator(self.HEADER).click()

        expect(nav_toggles).to_be_visible()

    def _click_visible_settings_toggle(self):
        settings_toggle = self.element.locator(f"{self.SETTINGS_FORM_TOGGLE}:visible")
        if settings_toggle.count() == 0:
            return False

        settings_toggle.first.click()
        return True

    def _wait_for_settings_form(self, settings_form, timeout=1500):
        try:
            expect(settings_form).to_be_visible(timeout=timeout)
            return True
        except AssertionError:
            return False

    def _wait_for_task_form(self, task_form, timeout=1500):
        try:
            expect(task_form).to_be_visible(timeout=timeout)
            return True
        except AssertionError:
            return False

    @property
    def settings_form(self):
        self._wait_for_page_task_list()
        settings_form = self.element.locator(self.SETTINGS_FORM)
        if settings_form.is_visible() or self._wait_for_settings_form(settings_form):
            return settings_form

        if self._click_visible_settings_toggle():
            expect(settings_form).to_have_attribute("rendered", "")
            expect(settings_form).to_be_visible()
            return settings_form

        self._close_task()

        if settings_form.is_visible():
            return settings_form

        assert self._click_visible_settings_toggle(), "Task settings toggle is not visible"

        expect(settings_form).to_have_attribute("rendered", "")
        expect(settings_form).to_be_visible()
        return settings_form

    @property
    def task_form(self):
        self._wait_for_page_task_list()
        task_form = self.element.locator(self.TASK_FORM)
        if task_form.is_visible() or self._wait_for_task_form(task_form):
            return task_form

        self._close_task()
        self._open_task()

        if task_form.is_visible():
            return task_form

        task_toggle = self.element.locator(self.TASK_FORM_TOGGLE)
        if task_toggle.is_visible():
            task_toggle.click()

        expect(task_form).to_be_visible()
        expect(task_form).to_have_attribute("rendered", "")
        return task_form

    def set_due_date(self, due_date_definition):
        due_date_form = DateSelect(self.settings_form).form()
        due_date_definition.set(due_date_form)

    def complete(self):
        page = self.definition.origin.get(self.user)
        page.complete_task(self)

    def uncomplete(self):
        page = self.definition.origin.get(self.user)
        page.uncomplete_task(self)

    def mark_completed(self):
        """Establish an already-completed setup task without UI navigation.

        Do not use this helper when completion or its persistence is the E2E
        behavior under test; use the visible completion control in that story.
        """
        self.entity.completed = True
        self.entity.completed_on = datetime.now()
        self.entity.save()

    def save(self):
        settings_form = self.settings_form
        with expect_successful_response(
            self.user.page,
            method="PUT",
            path=f"/tasks/{self.key}/update",
            entity_key=self.key,
        ):
            SpinnerButtons.UPDATE.click(settings_form)
        assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_form)
