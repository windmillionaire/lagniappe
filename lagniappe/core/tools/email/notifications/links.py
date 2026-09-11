"""Stable delivery identities and application links."""

from hashlib import sha256
import os
from urllib.parse import urlsplit, urlunsplit

from lagniappe import CONFIG

from ....entities import Entities
from ...database import notification_email as email_database


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason stable identities are exercised through idempotent capture
def identity(*parts):
    return sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


# @testable true
# @tests tests_unit/test_029b_notification_email_events.py::test_managed_local_test_origin_ignores_request_host_headers
# @matrix agent-api testing web-headers : origin-validation
def origin():
    managed_test_mode = os.environ.get("LAGNIAPPE_TEST_SESSION_MODE")
    if (
        CONFIG.testing
        and not CONFIG.hosted_e2e
        and managed_test_mode in {"local-e2e", "managed-server"}
    ):
        configured = str(getattr(CONFIG, "BASE_URL", "") or "").strip()
    else:
        configured = (
            str(getattr(CONFIG, "GOOGLE_LOGIN_URI", "") or "").strip()
            or str(getattr(CONFIG, "APP_URL", "") or "").strip()
            or str(getattr(CONFIG, "BASE_URL", "") or "").strip()
        )
    parsed = urlsplit(configured)
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
    return configured.rstrip("/")


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason absolute links are exercised through rendered delivery
def absolute_url(path):
    path = str(path or "/").strip()
    if path.startswith(("https://", "http://")):
        return path
    return f"{origin()}/{path.lstrip('/')}"


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification
# @reason target resolution is exercised through notification capture
def target_path(target):
    if isinstance(target, Entities.REPORT):
        return f"/tools/reports/{target.urlsafe_key}"
    if target is not None:
        try:
            path = target.url
        except (AttributeError, RuntimeError):
            path = None
        if path:
            return str(path)
    return "/"


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason stable SMTP identity is exercised through delivery
def message_id(row):
    domain = urlsplit(origin()).hostname or "localhost"
    version = (
        row.get("message_sequence")
        or row.get("source_key")
        or row.get("bucket")
        or "delivery"
    )
    value = identity(email_database.encoded_key(row.key), version)[:32]
    return f"<notification-{value}@{domain}>"
