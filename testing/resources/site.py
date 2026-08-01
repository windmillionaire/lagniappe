"""
Site-level page resources for static application routes.

These resources represent pages that always exist (no creation needed).
They provide selectors for UI elements on each page.

Related Files:
    Templates:
        - lagniappe/web/templates/users/login.html: Login forms
        - lagniappe/web/templates/forms/index.html: Form index page
        - lagniappe/web/templates/users/index.html: User management page

    Routes:
        - lagniappe/web/routes/users/main.py: /users/login, /users/index
        - lagniappe/web/routes/forms/main.py: /forms/index

    Definition:
        - testing/definitions/site_pages.py: SitePages enum using these

Usage:
    login_page = user.go(SitePages.LOGIN_PAGE)
    expect(user.locate(login_page.EMAIL_CHECK_FORM)).to_be_visible()
"""

from playwright.sync_api import expect

from testing.elements import List, SpinnerButtons, Tools

from .core import SiteResource


INDEX_TABLE_TIMEOUT = 30000


def wait_for_index_table_loaded(resource, selector):
    table_body = resource.user.locate(selector)
    expect(table_body).to_have_attribute("loaded", "", timeout=INDEX_TABLE_TIMEOUT)
    expect(table_body.locator("tr[lp-load]")).to_have_count(
        0, timeout=INDEX_TABLE_TIMEOUT
    )


class LoginPage(SiteResource):
    """
    Login page resource with authentication form selectors.

    Template: lagniappe/web/templates/users/login.html
    Route: /users/login

    The login page uses Identity Platform with custom forms and shows different forms
    based on authentication state (email check → sign in → setup, etc.).

    Selectors:
        EMAIL_CHECK_FORM: Initial email input form
        SIGN_IN_FORM: Password entry form (after email verified)
        FIRST_TIME_SETUP_FORM: New user profile setup
        FORGOT_PASSWORD_FORM: Password reset request
        RESET_PASSWORD_FORM: New password entry (from reset link)
        VERIFY_EMAIL_FORM: Email verification prompt
        SIGN_IN_FORGOT_PASSWORD: Forgot-password control inside sign-in (not verify-email duplicate)
    """

    EMAIL_CHECK_FORM = "#emailCheck"
    SIGN_IN_FORM = "#signIn"
    FIRST_TIME_SETUP_FORM = "#firstTimeSetup"
    FORGOT_PASSWORD_FORM = "#forgotPassword"
    RESET_PASSWORD_FORM = "#resetPassword"
    VERIFY_EMAIL_FORM = "#verifyEmail"
    SIGN_IN_FORGOT_PASSWORD = "#signIn button[data-role='show-forgot-form']"

    _title = "Login"

    def login_url(self, email):
        """
        Generate a test login URL that bypasses external authentication.

        In test environment, /users/login?test_user={email} creates a
        session directly without requiring password authentication.

        Args:
            email: Email address of user to authenticate as

        Returns:
            str: Full URL with test_user query parameter
        """
        return f"{self.url}?test_user={email}"


class SitePage(SiteResource):
    """
    Generic site page with no specific selectors.

    Used for simple pages that only need URL navigation:
    - /ping (health check)
    - /nonexistent (404 testing)
    """

    pass


class AdminPage(SiteResource):
    """Admin settings page at /admin."""

    _initialize = True
    _sync = True

    SITE_SETTINGS_FORM = "[data-widget='SiteSettings']"
    SITE_EXPORT_FORM = "[data-widget='SiteExport']"
    SITE_EXPORT_TOGGLE = "#tabs button[lp-show='exports:active']"
    SITE_EXPORT_START = "[data-role='start-export']"
    SITE_EXPORT_ITEM = "[data-role='site-export-item']"
    SITE_IMPORT_TOGGLE = "#tabs button[lp-show='ingress:active']"
    IMPORT_UPLOAD_TOGGLE = "#tabs button[lp-show='ingress:IngressFileUpload']"
    IMPORT_LIST = "#ingress ul[data-widget='IngressList']"
    INGRESS_UPLOAD_FORM = "form[data-widget='IngressFileUpload']"

    def open_import_tab(self):
        self.user.locate(self.SITE_IMPORT_TOGGLE).click()
        expect(self.user.locate(self.IMPORT_LIST)).to_have_attribute("loaded", "")

    def open_import_upload_form(self):
        self.open_import_tab()
        form = self.user.locate(self.INGRESS_UPLOAD_FORM)
        import_items = self.user.locate(self.IMPORT_LIST).locator("li[lp-entity]")
        if import_items.count() == 0:
            expect(form).to_be_visible()
        elif not form.is_visible():
            toggle = self.user.locate(self.IMPORT_UPLOAD_TOGGLE)
            expect(toggle).to_be_visible()
            toggle.click()
        expect(form).to_be_visible()
        return form

    def import_file(self, upload):
        form = self.open_import_upload_form()

        upload.set(form)
        with self.user.page.expect_response("**/ingress", timeout=20000):
            SpinnerButtons.UPLOAD.click(form)

        expect(form).not_to_be_visible()
        file_list = self.import_list
        expect(file_list.list).to_be_visible()
        return file_list.new_item(upload.definition.filename, flash=False)

    @property
    def import_list(self):
        ingress = List(self.user.locate(self.IMPORT_LIST))
        assert ingress.is_loaded
        return ingress


class FormIndex(SiteResource):
    """
    Form builder index page resource.

    Template: lagniappe/web/templates/forms/index.html
    Route: /forms/index

    Selectors:
        CREATE_FORM_BUTTON: Opens the create form widget
        CREATE_FORM_WIDGET: The form creation panel
        FORM_TYPE_PAGE: Radio button for page-type forms
        FORM_TYPE_TASK: Radio button for task-type forms
    """

    _initialize = True
    _sync = True

    TOOLS_TOGGLE = "button[lp-show='tools:default']"

    CREATE_FORM_BUTTON = "button[lp-show='tools:CreateForm']"
    CREATE_FORM_WIDGET = "[data-widget='CreateForm']"

    FORM_TYPE_PAGE = "input[name='form-type'][value='page']"
    FORM_TYPE_TASK = "input[name='form-type'][value='task']"

    TABLE_BODY = "#table tbody"

    def initialize_view(self):
        super().initialize_view()
        wait_for_index_table_loaded(self, self.TABLE_BODY)

    def create_form_form(self):
        tools = Tools(self.user)
        tools.open()
        tools.locate(self.CREATE_FORM_BUTTON).click()
        create_form = tools.locate(self.CREATE_FORM_WIDGET)
        expect(create_form).to_be_visible()
        return create_form


class UserIndex(SiteResource):
    """
    User management index page resource.

    Template: lagniappe/web/templates/users/index.html
    Route: /users/index

    Selectors:
        CREATE_USER_BUTTON: Opens the create user widget (in tools panel)
        CREATE_USER_WIDGET: The user creation form panel
    """

    _initialize = True
    _sync = True

    CREATE_USER_BUTTON = "button[lp-show='tools:CreateUser']"
    CREATE_USER_WIDGET = "[data-widget='CreateUser']"
    TABLE_BODY = "#table tbody"

    PUBLIC_USERS_TOGGLE = "[data-role='public-users-toggle']"
    PUBLIC_USERS_TOGGLE_DESKTOP = "[data-role='public-users-toggle'].desktop"
    USER_GROUPS_BUTTON = "button[lp-show='user-groups:nav']"
    USER_GROUPS_COMPONENT = "#user-groups"
    NEW_USER_GROUP_BUTTON = "button[lp-show='user-groups:CreateUserGroup']"
    NEW_USER_GROUP_WIDGET = "[data-widget='CreateUserGroup']"
    PUBLIC_PERMISSIONS_BUTTON = "button[lp-show='user-groups:PublicPermissions']"
    PUBLIC_PERMISSIONS_WIDGET = "[data-widget='PublicPermissions']"
    GROUP_NAME_INPUT = "input[name='name']"

    GROUPS_NAV = "[data-nav='user-groups']"

    def initialize_view(self):
        super().initialize_view()
        wait_for_index_table_loaded(self, self.TABLE_BODY)

    @property
    def create_user_form(self):
        tools = Tools(self.user)
        tools.open()
        tools.locate(self.CREATE_USER_BUTTON).click()
        create_user = tools.locate(self.CREATE_USER_WIDGET)
        expect(create_user).to_be_visible()
        expect(create_user).to_have_attribute("initialized", "")
        return create_user

    @property
    def user_groups(self):
        tools = Tools(self.user)
        tools.open()
        tools.locate(self.USER_GROUPS_BUTTON).click()
        user_groups = tools.locate(self.USER_GROUPS_COMPONENT)
        expect(user_groups).to_be_visible()
        return user_groups

    @property
    def create_user_group_form(self):
        groups = self.user_groups
        groups.locator(self.NEW_USER_GROUP_BUTTON).click()
        create_user_group = groups.locator(self.NEW_USER_GROUP_WIDGET)
        expect(create_user_group).to_be_visible()
        return create_user_group

    @property
    def public_permissions_form(self):
        groups = self.user_groups
        groups.locator(self.PUBLIC_PERMISSIONS_BUTTON).click()
        public_permissions = groups.locator(self.PUBLIC_PERMISSIONS_WIDGET)
        expect(public_permissions).to_be_visible()
        expect(public_permissions).to_have_attribute("rendered", "")
        return public_permissions


class TaskIndex(SiteResource):
    """
    Task index page resource.

    Template: lagniappe/web/templates/tasks/index.html
    Route: /tasks/index
    """

    _initialize = True
    _sync = True

    TABLE_BODY = "#table tbody"

    def initialize_view(self):
        super().initialize_view()
        wait_for_index_table_loaded(self, self.TABLE_BODY)
