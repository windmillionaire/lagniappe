"""
Static site page definitions for navigation.

Unlike entity definitions (Categories, Pages, etc.), these represent fixed
application routes that don't require creation - they always exist.

Related Files:
    Application Routes:
        - lagniappe/web/routes/home/main.py: / (HOME), /l/ping (PING)
        - lagniappe/web/routes/forms/main.py: /forms/index (FORM_INDEX)
        - lagniappe/web/routes/tasks/main.py: /tasks/index (TASK_INDEX)
        - lagniappe/web/routes/users/main.py: /users/index, /users/login

    Resources:
        - testing/resources/home.py: HomePage (HOME selectors)
        - testing/resources/site.py: LoginPage, FormIndex, UserIndex, SitePage

Usage:
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)  # Navigate and get HomePage resource
    user.locate(home.PROJECT_LIST_TOGGLE).click()  # Use resource's selectors
"""

from enum import Enum

from ..resources import (
    AdminPage,
    FormIndex,
    HomePage,
    LoginPage,
    SitePage,
    TaskIndex,
    UserIndex,
)


class SitePages(Enum):
    """
    Enum of static site pages for test navigation.

    Each member wraps a resource class that provides:
    - url: The route path to navigate to
    - title: Expected page title (optional)
    - Selectors: CSS selectors for page elements (as class attributes)

    Members:
        HOME: Main dashboard at / (HomePage resource with project/category lists)
        ADMIN: Administrator settings page at /admin
        PING: Health check endpoint at /l/ping (returns "pong")
        FORM_INDEX: Form builder index at /forms/index
        SEARCH_PAGE: Full search results page at /l/search-page
        TASK_INDEX: Global task list at /tasks/index
        USER_INDEX: User management at /users/index
        LOGIN_PAGE: Authentication page at /users/login
        PRIVACY_POLICY: Public privacy policy at /privacy-policy
        REPORTING_PRIVACY: Maintainer error-reporting notice at /reporting_privacy
        NONEXISTENT_PAGE: Invalid route for 404 testing
    """

    HOME = HomePage(url="/", title="Home")
    ADMIN = AdminPage(url="/admin", title="Admin")
    PING = SitePage(url="/l/ping")
    FORM_INDEX = FormIndex(url="/forms/index")
    SEARCH_PAGE = SitePage(url="/l/search-page", title="Search")
    TASK_INDEX = TaskIndex(url="/tasks/index")
    USER_INDEX = UserIndex(url="/users/index")
    LOGIN_PAGE = LoginPage(url="/users/login")
    PRIVACY_POLICY = SitePage(url="/privacy-policy", title="Privacy Policy")
    REPORTING_PRIVACY = SitePage(
        url="/reporting_privacy", title="Error-Reporting Privacy Notice"
    )
    NONEXISTENT_PAGE = SitePage(url="/nonexistent", expected_status=404)

    def get(self, user):
        """
        Get the resource with user context attached.

        Unlike entity definitions, site pages don't need creation logic.
        The calling `user.go(...)` flow attaches the user context.

        Args:
            user: User resource performing the navigation

        Returns:
            SiteResource: The resource for this route
        """
        self.value.user = user
        return self.value
