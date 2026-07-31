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
        - lagniappe/web/routes/home/main.py: /ping endpoint

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

from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from lagniappe.core.tools import cache, database

from testing.definitions import SitePages, Users

pytestmark = pytest.mark.e2e


PREFIX = SETTINGS.test_config["PREFIX"]


# @features database
# @dimensions datastore-creation
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


# @features storage
# @dimensions bucket-creation
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

    for role in ("public", "private", "history", "export"):
        data.bucket(role)

    storage = data.storage
    for config_name in (
        CONFIG.PUBLIC_BUCKET,
        CONFIG.PRIVATE_BUCKET,
        CONFIG.HISTORY_BUCKET,
        CONFIG.EXPORT_BUCKET,
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

    Navigates to /ping endpoint which returns "pong" to confirm the server
    is running. Uses Users.ANONYMOUS since /ping doesn't require auth.

    Verifies:
        - lagniappe/web/routes/home/main.py: /ping route returns "pong"
        - runner/testing.py: run_test_server() started successfully
        - Server listening on SETTINGS.test_config["BASE_URL"]

    Failure indicates:
        - Test server failed to start (check conftest.setup_test_server)
        - Server not listening on expected port
        - /ping route not defined or returning wrong content
    """
    user = get_user(Users.ANONYMOUS)
    user.go(SitePages.PING)

    expect(user.locate("body")).to_contain_text("pong")


# @pairs web-headers:etag web-headers:security web-headers:conditional-request
# @pairs web-headers:missing-fingerprint cache:etag cache:build-id
# @pairs cache:missing-fingerprint cache:standard-header
def test_authenticated_home_response_headers_include_etag(get_user):
    """Authenticated app responses should carry the common header envelope."""
    user = get_user(Users.OWNER)
    with user.page.expect_response("**/update-session") as session_info:
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
    assert headers.get("etag")
    assert headers["cache-control"] == "private, no-cache"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    csp = headers["content-security-policy"]
    assert "script-src 'self' https://accounts.google.com" in csp
    assert "connect-src 'self' https://*.googleapis.com" in csp
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

    uncached = requests.get(
        f"{SETTINGS.test_config['BASE_URL']}/",
        headers={"If-None-Match": '"not-the-current-fingerprint"'},
        cookies=cookies,
        allow_redirects=False,
        timeout=10,
    )
    assert uncached.status_code == 200


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
def test_error_handling(get_user):
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
    user.go(SitePages.NONEXISTENT_PAGE)

    expect(user.page).to_have_title("Error 404")
