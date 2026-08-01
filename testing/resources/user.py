from datetime import datetime, timezone
from urllib.parse import urlencode


from config import SETTINGS
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities

from .core import SiteResource

# Viewport dimensions
MOBILE_VIEWPORT = {"width": 375, "height": 667}
DESKTOP_VIEWPORT = {"width": 1280, "height": 720}
class User(SiteResource):
    _initialize = True
    _sync = True
    _is_mobile = False
    _is_offline = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage_state = None
        self.console_messages = []
        self.page = None

    @property
    def email(self):
        return self.definition.email

    @property
    def offline(self):
        return self._is_offline

    @offline.setter
    def offline(self, value):
        if value == self._is_offline:
            return
        self._is_offline = value
        self.page.context.set_offline(value)
        self.page.wait_for_function(
            "(offline) => navigator.onLine === !offline",
            arg=value,
        )

    @property
    def mobile(self):
        """Check if currently in mobile viewport."""
        return self._is_mobile

    @mobile.setter
    def mobile(self, value):
        """
        Set mobile/desktop viewport.

        When set to True, viewport changes to mobile dimensions (375x667).
        When set to False, viewport changes to desktop dimensions (1280x720).
        """
        if value == self._is_mobile:
            return
        self._is_mobile = value
        self.page.set_viewport_size(
            MOBILE_VIEWPORT if self._is_mobile else DESKTOP_VIEWPORT
        )

    def create(self):
        """
        Create user entity programmatically.

        Uses the same Entities.USER.create() path as the route handler
        in lagniappe/web/routes/users/main.py.

        The creator parameter is accepted for compatibility with the
        Users enum .get() method but is not used for programmatic creation.
        """
        data = {
            "name": self.definition.name,
            "email": self.definition.email,
            "groups": [g.get(self.user).entity for g in self.definition.groups],
            "test_user": True,
        }
        if self.definition.ai_access is not None:
            data["ai_access"] = self.definition.ai_access.name

        entity = Entities.USER.create(data)
        self.entity = entity
        if self.definition.ai_access is not None:
            entity.ai_access = self.definition.ai_access.name

        if self.definition.email == SETTINGS.test_config["ADMIN_EMAIL"]:
            entity.last_login = datetime.now(timezone.utc)

        entity.save()

        return self

    def suffix(self):
        return f"/pages/{self.entity.page.urlsafe_key}"

    def navigate(self, url):
        return self.page.goto(url, wait_until="load")

    def go(self, site_resource, query_params=None):
        resource = (
            site_resource if hasattr(site_resource, "url") else site_resource.get(self)
        )
        resource.user = self

        url = (
            resource.url
            if not query_params
            else f"{resource.url}?{urlencode(query_params)}"
        )

        self.offline = False
        self.mobile = False

        response = self.navigate(url)
        if response and response.status >= 400:
            raise AssertionError(
                f"Navigation failed with HTTP {response.status}: {response.url}"
            )

        if resource.initialize:
            resource.initialize_view()

        return resource

    def reload(self, resource=None):
        self.page.reload()
        if resource and resource.initialize:
            resource.initialize_view()
        self.offline = False
        self.mobile = False
        return resource

    def back(self):
        self.page.go_back()
        return self

    def locate(self, selector):
        return self.page.locator(selector)

    def clear_cache_invalidation(self):
        if not self.email:
            return

        loaded = Entities.USER.load(self.email)
        if loaded:
            self.entity = loaded

        if getattr(self.entity, "invalidate_cache", False):
            self.entity = Entities.fetch_one(
                self.entity,
                request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
            )
            self.entity.invalidate_cache = False
            self.entity.save()

        loaded = Entities.USER.load(self.email)
        if loaded:
            self.entity = loaded
        if self.page:
            self.storage_state = self.page.context.storage_state()

    def login(self, browser):
        if self.storage_state:
            return

        context = browser.new_context()
        login_page = context.new_page()

        from ..definitions import SitePages

        login_url = SitePages.LOGIN_PAGE.get(self).login_url(self.email)

        with login_page.expect_navigation():
            login_page.goto(login_url, wait_until="load", timeout=15000)

        self.storage_state = context.storage_state()

        login_page.close()
        context.close()
