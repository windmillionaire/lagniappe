"""Stable delivery identities and application links."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud.datastore import Entity as DatastoreRow
    from lagniappe.core.entities.entity import Entity

from hashlib import sha256
import os
from urllib.parse import urlsplit, urlunsplit

from lagniappe import CONFIG

from ....entities import Entities
from ...database import notification_email as email_database


def identity(*parts: object) -> str:
    return sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def origin() -> str:
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


def absolute_url(path: str | None) -> str:
    path = str(path or "/").strip()
    if path.startswith(("https://", "http://")):
        return path
    return f"{origin()}/{path.lstrip('/')}"


def target_path(target: Entity | None) -> str:
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


def message_id(row: DatastoreRow) -> str:
    domain = urlsplit(origin()).hostname or "localhost"
    version = (
        row.get("message_sequence")
        or row.get("source_key")
        or row.get("bucket")
        or "delivery"
    )
    value = identity(email_database.encoded_key(row.key), version)[:32]
    return f"<notification-{value}@{domain}>"
