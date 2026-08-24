"""
Test environment verification.

Ensures test infrastructure (server, database, cache, storage) is working correctly.
These tests run first to verify the test environment is properly configured before
running any application tests.

Related Files:
    Application:
        - lagniappe/__init__.py: CONFIG object with environment settings
        - lagniappe/core/tools/database/core.py: KINDS enum, DataServices (buckets)
        - lagniappe/core/tools/cache/core.py: Cache class (Redis connection, INDEX)
        - lagniappe/web/routes/home/site.py: /l/ping endpoint

    Configuration:
        - config/__init__.py: SETTINGS.test_config for PREFIX, BASE_URL, etc.
        - runner/testing.py: run_test_server() startup logic

    Test Framework:
        - testing/definitions/site_pages.py: SitePages.PING, LOGIN_PAGE, etc.
        - testing/definitions/users.py: Users.ANONYMOUS, OWNER
        - testing/resources/site.py: LoginPage selectors (EMAIL_CHECK_FORM, etc.)

Test Isolation Strategy:
    All test data is isolated from production by using a PREFIX (typically "test-"):
    - Database entity kinds: test-users, test-models, test-instances, etc.
    - Cache indexes: test-search-index
    - Storage buckets: test-public-bucket, test-private-bucket

    This allows tests to run against the same GCloud project as production
    without data collision. Cleanup happens in conftest.py teardown.
"""

import json
from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, database

from testing.definitions import SitePages, Users
from testing.utility import assert_same_etag

pytestmark = pytest.mark.e2e


PREFIX = SETTINGS.test_config["PREFIX"]


def test_database_setup():
    """
    Verify test database entity kinds use the test prefix.

    Checks that all Datastore entity kinds defined in database.core.KINDS
    are prefixed with the test PREFIX (e.g., "test-users" instead of "users").
    This ensures test data is isolated from production data.

    Verifies:
        - lagniappe/core/tools/database/core.py: KINDS enum values
        - config/__init__.py: SETTINGS.test_config["PREFIX"]

    Failure indicates:
        - FLASK_ENV not set to 'testing' when server started
        - PREFIX not correctly propagated to entity kind definitions
    """
    for kind in database.core.KINDS:
        assert kind.value == f"{PREFIX}{kind.name}"

    assert database.core.datastore is not None


# @pair cache:redis-connection
# @pair cache:cleanup
# @pair cache:index-recreation
def test_cache_setup():
    """
    Verify Redis cache is connected and using test-prefixed index.

    Checks that:
    1. The RediSearch index name starts with the test PREFIX
    2. Redis responds to ping (connection is alive)

    Verifies:
        - lagniappe/core/tools/cache/core.py: cache.INDEX, cache.redis
        - Redis connection pool configuration

    Failure indicates:
        - Redis server not running or unreachable
        - Cache not initialized with test configuration
        - REDIS_HOST/REDIS_PORT/REDIS_PASSWORD misconfigured
    """
    # Verify test prefix on the search index
    assert cache.core.cache.INDEX.startswith(PREFIX)

    # Verify Redis connection is alive
    assert cache.core.cache.redis.ping()
    assert cache.core.filter_cache.redis.ping()

    cache.cleanup_test_data()
    cache.initialize()

    assert cache.core.cache.redis.ft(cache.core.cache.INDEX).info()
    assert cache.core.filter_cache.redis.ft(cache.core.filter_cache.INDEX).info()


def test_storage_setup():
    """
    Verify test GCS buckets exist in Cloud Storage with the test prefix.

    Ensures buckets through DataServices (same path as the app), then confirms
    each expected bucket is present in GCS via the storage client rather than
    only checking in-memory DataServices state.

    Verifies:
        - lagniappe/core/tools/database/core.py: DataServices.bucket, storage client
        - Bucket naming convention: {PREFIX}{BUCKET_NAME}

    Failure indicates:
        - GCloud credentials not configured
        - Storage client unable to access/create buckets
        - PREFIX not correctly applied to bucket names
    """
    data = database.core.DATA
    data.initialize()

    for role in ("public", "private", "history"):
        data.bucket(role)

    storage = data.storage
    for config_name in (
        CONFIG.PUBLIC_BUCKET,
        CONFIG.PRIVATE_BUCKET,
        CONFIG.HISTORY_BUCKET,
    ):
        bucket_name = f"{PREFIX}{config_name}"
        assert bucket_name.startswith(PREFIX)
        bucket = storage.get_bucket(bucket_name)
        assert bucket.name == bucket_name


# @features server
# @dimensions initialization
def test_server_running(get_user):
    """
    Verify Flask test server is running and responding.

    Navigates to /l/ping endpoint which returns "pong" to confirm the server
    is running. Uses Users.ANONYMOUS since /l/ping doesn't require auth.

    Verifies:
        - lagniappe/web/routes/home/site.py: /l/ping route returns "pong"
        - runner/testing.py: run_test_server() started successfully
        - Server listening on SETTINGS.test_config["BASE_URL"]

    Failure indicates:
        - Test server failed to start (check conftest.setup_test_server)
        - Server not listening on expected port
        - /l/ping route not defined or returning wrong content
    """
    user = get_user(Users.ANONYMOUS)
    user.go(SitePages.PING)

    expect(user.locate("body")).to_contain_text("pong")


# @pairs notifications:ping notifications:redis-projection
# @pair web-headers:notification-state
def test_ping_notification_state_is_redis_only_and_optional(get_user):
    """A real notification reaches a reloaded page through the ping header."""
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    # Establish the empty durable/projection baseline before measuring mutation
    # propagation. Otherwise initial page startup can race the first mutation's
    # cold aggregate repair and leave the projection one revision behind.
    existing = Entities.NOTIFICATION.keys_for_parent(user.entity)
    assert not existing
    aggregate = database.ensure_notification_aggregate(user.entity)
    cache.repair_notification_state(user.entity, existing, aggregate=aggregate)

    notification = Entities.NOTIFICATION.create(
        {
            "parent": user.entity,
            "body": "Ping projection notification",
        }
    )
    Entities.save(notification)

    notification_requests = []

    def record_request(request):
        if urlsplit(request.url).path == "/l/notifications":
            notification_requests.append(request.url)

    user.page.on("request", record_request)
    with user.page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/l/ping"
            and response.request.method == "HEAD"
        )
    ) as ping_info:
        user.page.reload()

    state = json.loads(
        ping_info.value.headers["x-lagniappe-notification-state"]
    )
    assert isinstance(state["generation"], str)
    assert state["revision"] >= 1
    assert state["count"] == 1
    expect(user.page.locator("[data-role='notification-count']")).to_have_text("1")
    expect(user.page.locator("[data-role='notifications']")).to_have_attribute(
        "data-visible", "true"
    )
    assert notification_requests == []


# @pairs web-headers:etag web-headers:security web-headers:conditional-request
# @pairs web-headers:missing-fingerprint cache:etag cache:build-id
# @pairs cache:missing-fingerprint cache:standard-header
def test_authenticated_home_response_headers_include_etag(get_user):
    """Authenticated app responses should carry the common header envelope."""
    user = get_user(Users.OWNER)
    with user.page.expect_response("**/l/update-session") as session_info:
        user.page.goto(f"{SETTINGS.test_config['BASE_URL']}/")
    assert session_info.value.ok
    expect(user.page).to_have_title("Home")

    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in user.page.context.cookies()
    }
    direct = requests.get(
        f"{SETTINGS.test_config['BASE_URL']}/",
        cookies=cookies,
        allow_redirects=False,
        timeout=10,
    )
    headers = direct.headers

    assert direct.status_code == 200
    assert headers["content-type"].startswith("text/html")
    assert headers.get("etag")
    assert headers["cache-control"] == "private, no-cache"
    assert headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains; preload"
    )
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "content-security-policy-report-only" not in headers
    assert '<div lp-view data-kind="home"' in direct.text
    csp = headers["content-security-policy"]
    assert "script-src 'self' https://accounts.google.com/gsi/client" in csp
    assert (
        "style-src 'self' 'unsafe-inline' "
        "https://accounts.google.com/gsi/style" in csp
    )
    assert (
        "connect-src 'self' https://*.googleapis.com "
        "https://accounts.google.com/gsi/" in csp
    )
    assert (
        "frame-src 'self' https://www.youtube-nocookie.com "
        "https://accounts.google.com/gsi/" in csp
    )
    assert "frame-ancestors 'self'" in csp
    assert "img-src 'self' blob: data: https://storage.googleapis.com" in csp
    assert "media-src 'self' https://storage.googleapis.com" in csp
    if CONFIG.capture_errors:
        sentry_dsn = urlsplit(CONFIG.SENTRY_JS_DSN)
        sentry_origin = f"{sentry_dsn.scheme}://{sentry_dsn.hostname}"
        if sentry_dsn.port:
            sentry_origin += f":{sentry_dsn.port}"
        assert sentry_origin in csp
        assert "@" not in csp
    else:
        assert "sentry" not in csp

    conditional = requests.get(
        f"{SETTINGS.test_config['BASE_URL']}/",
        headers={"If-None-Match": headers["etag"]},
        cookies=cookies,
        allow_redirects=False,
        timeout=10,
    )
    assert conditional.status_code == 304
    assert_same_etag(conditional.headers.get("etag"), headers["etag"])
    assert conditional.headers["cache-control"] == "private, no-cache"
    assert conditional.content == b""

    uncached = requests.get(
        f"{SETTINGS.test_config['BASE_URL']}/",
        headers={"If-None-Match": '"not-the-current-fingerprint"'},
        cookies=cookies,
        allow_redirects=False,
        timeout=10,
    )
    assert uncached.status_code == 200
    assert_same_etag(uncached.headers.get("etag"), headers["etag"])
    assert uncached.headers["content-type"].startswith("text/html")
    assert '<div lp-view data-kind="home"' in uncached.text


# @features session location timezone
# @dimensions validation atomic-update coordinates
def test_update_session_rejects_invalid_timezone_and_location_atomically(
    get_user, browser_failures
):
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)
    persisted = Entities.USER.load(user.email)
    timezone_before = persisted.db.get("timezone")
    location_before = persisted.db.get("location")

    def update_session(raw_body):
        return user.page.evaluate(
            """async (body) => {
                const token = await (await fetch("/l/token")).text();
                const response = await fetch("/l/update-session", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": token,
                        "X-Lagniappe-Request": "true",
                    },
                    body,
                });
                return { status: response.status, body: await response.text() };
            }""",
            raw_body,
        )

    invalid_payloads = [
        "{",
        json.dumps({"timezone": "Mars/Olympus"}),
        json.dumps({"location": "not-an-object"}),
        json.dumps({"location": {"latitude": True, "longitude": 1}}),
        '{"location":{"latitude":1e999,"longitude":1}}',
        json.dumps(
            {
                "timezone": "UTC",
                "location": {"latitude": 91, "longitude": -90},
            }
        ),
    ]
    with browser_failures.expect_http_error(
        user,
        status=422,
        path="/l/update-session",
        count=len(invalid_payloads),
    ):
        results = [update_session(payload) for payload in invalid_payloads]

    assert [result["status"] for result in results] == [422] * len(invalid_payloads)
    persisted = Entities.USER.load(user.email)
    assert persisted.db.get("timezone") == timezone_before

    valid = update_session(
        json.dumps(
            {
                "timezone": "UTC",
                "location": {
                    "latitude": 29.9511,
                    "longitude": -90.0715,
                    "ignored": "not persisted",
                },
            }
        )
    )
    assert valid["status"] == 200
    assert Entities.USER.load(user.email).db.get("timezone") == "UTC"

    persisted = Entities.USER.load(user.email)
    if timezone_before is None:
        persisted.db.pop("timezone", None)
    else:
        persisted.db["timezone"] = timezone_before
    if location_before is None:
        persisted.db.pop("location", None)
    else:
        persisted.db["location"] = location_before
    persisted.save()


# @features privacy public-pages
# @dimensions anonymous-access document-load
def test_privacy_policy_is_public(get_user):
    """Verify anonymous visitors can load the public privacy policy."""
    user = get_user(Users.ANONYMOUS)
    user.go(SitePages.PRIVACY_POLICY)

    expect(user.page).to_have_title("Privacy Policy")
    body = user.locate("body")
    expect(body).to_contain_text("Who This Policy Is For")
    expect(body).to_contain_text("does not contact the Lagniappe project")
    expect(body).to_contain_text("Optional Analytics and Error Reporting")


# @features privacy public-pages error-reporting
# @dimensions anonymous-access document-load maintainer-destination
def test_reporting_privacy_notice_is_public(get_user):
    """Verify anonymous visitors can load the maintainer reporting notice."""
    user = get_user(Users.ANONYMOUS)
    user.go(SitePages.REPORTING_PRIVACY)

    expect(user.page).to_have_title("Error-Reporting Privacy Notice")
    body = user.locate("body")
    expect(body).to_contain_text(
        "Lagniappe Maintainer Error-Reporting Privacy Notice"
    )
    expect(body).to_contain_text("Maintainer error reporting is off by default")
    expect(body).to_contain_text("Caleb Wright")
    expect(body).to_contain_text("privacy@lagniappe.site")
    expect(body).to_contain_text("Retention and deletion")
    expect(body).to_contain_text("supplies a Sentry DSN")


# @features error-handling
# @dimensions http-404 error-page
def test_error_handling(get_user, browser_failures):
    """
    Verify 404 error page renders correctly.

    Navigates to a non-existent URL and verifies the error page is shown
    with the correct title. Tests Flask error handling configuration.

    Verifies:
        - lagniappe/web/routes/errors.py: 404 error handler
        - lagniappe/web/templates/errors/404.html: Error page template
        - Flask abort(404) handling works correctly

    Failure indicates:
        - Error handlers not registered with Flask app
        - Error template missing or has wrong title
        - Server returning wrong status code for 404
    """
    user = get_user(Users.ANONYMOUS)
    with browser_failures.expect_http_error(
        user,
        status=404,
        path=SitePages.NONEXISTENT_PAGE.get(user).url,
    ):
        user.go(SitePages.NONEXISTENT_PAGE)

    expect(user.page).to_have_title("Error 404")


def test_browser_failure_guard_detects_unhandled_page_errors(
    get_user, browser_failures
):
    """The guard rejects a real page error unless a narrow scope accounts for it."""
    user = get_user(Users.OWNER)
    sentinel = "browser-failure-guard-sentinel"

    with browser_failures.expect(
        user,
        kind="pageerror",
        exception_type="Error",
        message=sentinel,
    ):
        with user.page.expect_event("pageerror") as page_error:
            user.page.evaluate(
                "message => setTimeout(() => { throw new Error(message); }, 0)",
                sentinel,
            )

        assert str(page_error.value) == sentinel
        with pytest.raises(AssertionError, match="Unexpected browser failures"):
            browser_failures.assert_clean()
