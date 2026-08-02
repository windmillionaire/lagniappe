"""
Helper for the Page entity.

Maps to:
- Entity: lagniappe/core/entities/page.py
- Routes: lagniappe/web/routes/pages/
- Templates: lagniappe/web/templates/pages/
- View: src/script/views/page.mjs
"""

from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from testing.utility import expect_successful_response

from ..elements import Editor, List, SpinnerButtons, Tabs
from .core import SiteResource


class Page(SiteResource):
    """
    Resource for creating and interacting with Page entities.

    Pages are created programmatically using the same entity creation
    path as the route handler in lagniappe/web/routes/pages/main.py.
    """

    _initialize = True
    _sync = True

    # Task Tab
    CREATE_TASK_TOGGLE = "#tabs [lp-show='tasks:CreateTask']"
    CREATE_TASK_FORM = "[data-widget='CreateTask']"
    TASK_LIST = "#tasks [data-widget='PageTaskList']"
    ACTIVE_TASK_LIST = "[data-role='active-tasks']"
    COMPLETED_HEADER = "[data-role='completed-header']"
    COMPLETED_TASK_LIST = "[data-role='completed-tasks']"
    COMPLETE_TASK_CHECKBOX = "input[data-role='complete-toggle']"

    # Info Tab
    INFO_FORM = "[data-widget='PageInfo']"
    INFO_NAME = ":is(#name, [id^='name-renderer-'])"
    INFO_DESCRIPTION = ":is(#description, [id^='description-renderer-'])"
    INFO_ATTRIBUTES = "[data-role='attributes']"
    PHOTO_PROMPT = "[data-role='photo-prompt']"
    PHOTO_PROMPT_UPLOAD = "[data-role='photo-upload']"
    PHOTO_PROMPT_GENERATE = "[data-role='photo-generate']"
    PHOTO_PROMPT_DISABLE = "[data-role='photo-disable']"

    SITE_SETTINGS_TOGGLE = "[data-nav='tabs'] button[lp-show='info:SiteSettings']"
    SITE_SETTINGS_FORM = "[data-widget='SiteSettings']"
    USER_SETTINGS_TOGGLE = "[data-nav='tabs'] button[lp-show='info:UserSettings']"
    USER_SETTINGS_FORM = "[data-widget='UserSettings']"
    PAGE_PERMISSIONS_TOGGLE = (
        "[data-nav='tabs'] button[lp-show='info:PagePermissions']"
    )
    PAGE_PERMISSIONS_FORM = "[data-widget='PagePermissions'][data-visible='true']"
    PAGE_PERMISSIONS_VISIBLE_TO = "[data-role='visible-to']"
    PAGE_PERMISSIONS_RESTRICT_ACCESS = "[data-role='restrict-access']"
    PAGE_RESTRICT_OWNER = "input[data-role='specific-access'][name='owner']"
    PAGE_RESTRICT_GROUP_INPUT = "[data-role='restrict-group-input']"
    PAGE_RESTRICTED_GROUP_LIST = "[data-role='restricted-group-list'] li"

    # Photo Tab
    PHOTO_DROPZONE = "#photo [data-role='dropzone']"
    PHOTO_FORM = "#photo form[data-widget='PagePhoto']"
    PHOTO_MENU_BUTTON = "#photo [data-role='upload-menu']"
    PHOTO_EXISTING_IMAGE = "#photo [data-role='existing-image']"
    PHOTO_NEW_IMAGE = "#photo [data-role='new-image']"
    PHOTO_FEEDBACK = "#photo [data-role='feedback']"

    # Mobile Navigation
    MOBILE_NAV = "[lp-nav][data-nav='mobile']"
    DESKTOP_TAB_NAV = "#tabs [lp-nav][data-nav='tabs']"
    MOBILE_CREATE_TASK_BUTTON = (
        "[lp-nav][data-nav='mobile'] button[lp-show='tasks:CreateTask']"
    )
    MOBILE_UPLOAD_FILE_BUTTON = (
        "[lp-nav][data-nav='mobile'] button[lp-show='files:FileUpload']"
    )

    # Files Tab
    FILE_LIST = "#files [data-widget='BaseList']"
    EMPTY_FILE_LIST_ITEM = "#files [data-widget='BaseList'] [data-role='empty']"
    UPLOAD_FILE_TOGGLE = "#tabs [lp-show='files:FileUpload']"
    UPLOAD_FILE_FORM = "[data-widget='FileUpload']"

    # Document Tab
    DOCUMENT_SETTINGS_TOGGLE = "#tabs [lp-show='document:DocumentSettings']"
    DOCUMENT_SETTINGS_FORM = "[data-widget='DocumentSettings']"

    # --- Project Page Header ---
    PAGE_TITLE = "[data-nav='view'] [data-role='title']"
    PAGE_DESCRIPTION = "[data-role='description']"

    def create(self):
        """
        Create page entity programmatically.

        Uses the same Entities.PAGE.create() path as the route handler
        in lagniappe/web/routes/pages/main.py.
        """
        assert self.definition, "Definition is required to create a page"
        assert self.definition.category, "Category is required to create a page"

        category = self.definition.category.get(self.user)
        if category.definition.form:
            form_entity = category.definition.form.get(self.user).entity
        elif self.definition.form:
            form_entity = self.definition.form.get(self.user).entity
        else:
            form_entity = None

        if self.definition.submission:
            submission = {
                s.id: s.submission_value for s in self.definition.submission.get()
            }
        else:
            submission = None

        data = {
            "name": self.definition.name,
            "description": self.definition.description,
            "model": category.entity,
            "form": form_entity,
            "attributes": self.definition.attributes,
            "submission": submission,
        }

        entity = Entities.PAGE.create(data)
        entity.save()

        self.entity = entity

        return self

    @property
    def form_definition(self):
        if self.definition.form:
            return self.definition.form.get(self.user).definition
        elif self.definition.category:
            category = self.definition.category.get(self.user)
            if category.definition.form:
                return category.definition.form.get(self.user).definition
            else:
                return None
        else:
            return None

    @property
    def url_suffix(self):
        return f"pages/{self.key}"

    @property
    def create_task_form(self):
        tabs = Tabs(self.user)
        tasks_tab = tabs.tasks
        expect(tasks_tab).to_be_visible()
        create_form = tasks_tab.locator(self.CREATE_TASK_FORM)
        if not create_form.is_visible():
            self.user.locate(self.CREATE_TASK_TOGGLE).click()
            expect(create_form).to_be_visible()
        return create_form

    @property
    def info_form(self):
        tabs = Tabs(self.user)

        info_tab = tabs.info
        expect(info_tab).to_be_visible()

        info_form = info_tab.locator(self.INFO_FORM)
        expect(info_form).to_have_attribute("rendered", "")

        return info_form

    @property
    def task_list(self):
        tabs = Tabs(self.user)
        tasks_tab = tabs.tasks
        expect(tasks_tab).to_be_visible()

        task_list = self.user.locate(self.TASK_LIST)
        expect(task_list).to_be_visible()
        expect(task_list).to_have_attribute("loaded", "")

        return task_list

    @property
    def document_tab(self):
        tabs = Tabs(self.user)

        document_tab = tabs.document
        expect(document_tab).to_be_visible()
        return document_tab

    @property
    def editor(self):
        return Editor(self.document_tab)

    @property
    def files_tab(self):
        tabs = Tabs(self.user)
        files_tab = tabs.files
        expect(files_tab).to_be_visible()
        return files_tab

    @property
    def active_task_list(self):
        active_tasks = self.task_list.locator(self.ACTIVE_TASK_LIST)
        return List(active_tasks)

    @property
    def completed_task_list(self):
        task_list = self.task_list
        completed_task_list = task_list.locator(self.COMPLETED_TASK_LIST)
        if not completed_task_list.is_visible():
            task_list.locator(self.COMPLETED_HEADER).click()
        expect(completed_task_list).to_be_visible()
        return List(completed_task_list)

    def complete_task(self, task):
        task_item = self.active_task_list.get_item(task)

        with expect_successful_response(
            self.user.page,
            method="PUT",
            path=f"/tasks/{task.key}/update",
            entity_key=task.key,
        ):
            task_item.locator(self.COMPLETE_TASK_CHECKBOX).click()

        completed_task = self.completed_task_list.get_item(task)
        expect(completed_task).to_be_visible()
        task.element = completed_task

    def uncomplete_task(self, task):
        task_item = self.completed_task_list.get_item(task)

        with expect_successful_response(
            self.user.page,
            method="PUT",
            path=f"/tasks/{task.key}/update",
            entity_key=task.key,
        ):
            task_item.locator(self.COMPLETE_TASK_CHECKBOX).click()

        active_task = self.active_task_list.get_item(task)
        expect(active_task).to_be_visible()
        task.element = active_task

    def set_submission(self, submission):
        info_form = self.info_form
        for sub in submission:
            sub.set_submission_value(info_form)

    def submit_and_verify_submission(self, submission):
        info_form = self.info_form

        with self.user.page.expect_response("**/update"):
            SpinnerButtons.UPDATE.click(info_form)

        assert SpinnerButtons.UPDATE_SUCCESS.successful(info_form)
        return self.verify_submission(submission)

    def verify_submission(self, submission):
        info_form = self.info_form
        return all(sub.verify_submission_value(info_form) for sub in submission)
