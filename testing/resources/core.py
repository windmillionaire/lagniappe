from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities

from testing.elements import MobileNav


class SiteResource:
    _user = None
    _url_prefix = SETTINGS.test_config["BASE_URL"]
    _url_suffix = None
    _title = None
    _key = None
    _entity = None
    _definition = None
    _initialize = False
    _sync = False

    def __init__(self, *args, **kwargs):
        self._url_suffix = kwargs.get("url")
        self.title = kwargs.get("title")
        self.definition = kwargs.get("definition")
        self.user = kwargs.get("user")

    def initialize_view(self):
        if self._initialize:
            expect(self.user.locate("[lp-view]")).to_have_attribute("initialized", "")

    def reload(self, wait_until="load"):
        self.user.page.reload(wait_until=wait_until)
        self.initialize_view()
        return self

    @property
    def sync(self):
        return self._sync

    @property
    def initialize(self):
        return self._initialize

    @property
    def name(self):
        return self.definition.name

    @property
    def definition(self):
        return self._definition

    @definition.setter
    def definition(self, value):
        self._definition = value
        if value:
            self.title = value.name

    @property
    def url_suffix(self):
        return self._url_suffix if self._url_suffix else ""

    @url_suffix.setter
    def url_suffix(self, value):
        self._url_suffix = value

    @property
    def url(self):
        return f"{self._url_prefix}/{self.url_suffix}"

    @property
    def title(self):
        if getattr(self, "definition", None):
            return self.definition.name
        return self._title

    @title.setter
    def title(self, value):
        self._title = value

    @property
    def entity(self):
        return self._entity

    @entity.setter
    def entity(self, value):
        self._entity = value

    @property
    def key(self):
        return self.entity.urlsafe_key if self.entity else None

    @key.setter
    def key(self, value):
        if not self.entity:
            self.entity = Entities.fetch_one(value, request=Fetch.root())

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, value):
        self._user = value

    @property
    def mobile_nav(self):
        self.user.mobile = True
        mobile_nav = MobileNav(self.user)
        expect(mobile_nav.nav).to_be_visible()
        return mobile_nav
