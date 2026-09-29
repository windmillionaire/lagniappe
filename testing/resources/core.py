from html.parser import HTMLParser
from weakref import WeakSet

from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities

from testing.elements import MobileNav


VIEW_INITIALIZATION_TIMEOUT = 15000


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


class SiteResource:
    _instances = WeakSet()
    _user = None
    _url_prefix = SETTINGS.test_config["BASE_URL"]
    _url_suffix = None
    _title = None
    _key = None
    _entity = None
    _definition = None
    _initialize = False
    _sync = False
    _expected_status = None

    def __init__(self, *args, **kwargs):
        self._key = None
        self._entity = None
        self._instances.add(self)
        self._url_suffix = kwargs.get("url")
        self.title = kwargs.get("title")
        self.definition = kwargs.get("definition")
        self.user = kwargs.get("user")
        self.expected_status = kwargs.get("expected_status", self._expected_status)

    def initialize_view(self):
        if self._initialize:
            # Locator assertions have their own 5-second default; use the
            # standard E2E timeout under full-suite load.
            expect(self.user.locate("[lp-view]")).to_have_attribute(
                "initialized", "", timeout=VIEW_INITIALIZATION_TIMEOUT
            )

    @staticmethod
    def entity_key_from_response(response):
        parser = _DataKeyParser()
        parser.feed(response.text())
        assert parser.key, "Create response did not include an entity data-key"
        return parser.key

    def wait_for_interaction_readiness(self):
        """Wait for deferred view startup and its visual transition to settle."""
        # Keep the complete boundary in one navigation-aware Playwright wait.
        # Cache invalidation can replace the document more than once; separate
        # evaluate calls (or a single manual retry) can race another replacement.
        self.user.page.wait_for_function(
            """() => {
                if (window.__NAVIGATION_TRANSITION_SETTLED__ !== true ||
                    performance.getEntriesByName(
                        "lagniappe:services-ready", "mark"
                    ).length === 0) return false;
                return window.__WAIT_FOR_VIEW_TRANSITIONS__().then(() => true);
            }""",
            timeout=VIEW_INITIALIZATION_TIMEOUT,
        )
        return self

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
        return f"{self._url_prefix.rstrip('/')}/{self.url_suffix.lstrip('/')}"

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
        if self._entity is None and self._key:
            self.refresh_entity()
        return self._entity

    @entity.setter
    def entity(self, value):
        self._entity = value
        self._key = value.urlsafe_key if value is not None else None

    @property
    def key(self):
        return self._key

    @key.setter
    def key(self, value):
        if value != self._key:
            self._entity = None
        self._key = value

    def refresh_entity(self, *, request=None):
        """Fetch once for explicit durable checks or setup within this test."""
        self._entity = Entities.fetch_one(self._key, request=request or Fetch.direct()) if self._key else None
        return self._entity

    @classmethod
    def forget_entities(cls):
        """Keep identities and browser metadata, discard per-test row snapshots."""
        for resource in cls._instances:
            resource._entity = None

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
