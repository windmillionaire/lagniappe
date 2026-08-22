"""Text-only metadata previews for editor links."""

from ipaddress import ip_address
import socket
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import requests

from lagniappe import CONFIG
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from . import metadata as link_metadata

ALLOWED_EXTERNAL_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
MAX_METADATA_BYTES = 262_144
METADATA_TIMEOUT = 0.5
METADATA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
DIRECT_ENTITY_ROUTES = {
    "categories": ("category",),
    "files": ("file",),
    "forms": ("form",),
    "pages": ("page",),
    "projects": ("project",),
    "tasks": ("task",),
}
RESTRICTED_TITLE = "Access Restricted"
RESTRICTED_DESCRIPTION = "You do not have access to preview this link."


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason exception carrier for preview validation failures
class PreviewError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _parse_url(value, base_url=None):
    try:
        return urlparse(urljoin(base_url or "http://localhost/", value))
    except ValueError as error:
        raise PreviewError("Invalid URL") from error


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _is_internal_url(parsed, base_url=None):
    base = urlparse(base_url or "")
    if not parsed.netloc:
        return True
    return (
        parsed.scheme in ALLOWED_EXTERNAL_SCHEMES
        and bool(base.netloc)
        and parsed.netloc == base.netloc
    )


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _configured_hostnames():
    hosts = set()
    custom_domain = getattr(CONFIG, "CUSTOM_DOMAIN", None)
    if custom_domain:
        parsed = urlparse(
            custom_domain
            if "://" in custom_domain
            else f"https://{custom_domain}"
        )
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())

    return hosts


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _is_app_url(parsed, base_url=None):
    if _is_internal_url(parsed, base_url=base_url):
        return True
    if parsed.scheme not in ALLOWED_EXTERNAL_SCHEMES or not parsed.hostname:
        return False

    return parsed.hostname.lower() in _configured_hostnames()


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _internal_url(parsed):
    path = parsed.path or "/"
    return urlunparse(("", "", path, "", parsed.query, parsed.fragment))


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _external_url(parsed):
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _display_url(parsed, internal=False):
    if internal:
        return _internal_url(parsed)

    path = parsed.path if parsed.path and parsed.path != "/" else ""
    return f"{parsed.netloc}{path}{('?' + parsed.query) if parsed.query else ''}"


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _route_parts(path):
    return [part for part in path.split("/") if part]


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _restricted_preview(parsed, kind="internal"):
    return {
        "title": RESTRICTED_TITLE,
        "description": RESTRICTED_DESCRIPTION,
        "url": _internal_url(parsed),
        "display_url": _display_url(parsed, internal=True),
        "kind": kind,
        "internal": True,
    }


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _status_route_preview(parts, parsed):
    project = Entities.fetch_one(parts[1], request=Fetch.direct())
    if not project or project.kind != "project":
        return {"recognized": True, "entity": None, "kind": "project"}

    task_key = parts[3]
    model = next(
        (model for model in project.model_tasks if model.urlsafe_key == task_key),
        None,
    )
    completed = parse_qs(parsed.query).get("completed", ["false"])[0] == "true"
    status = "Completed" if completed else "In Progress"
    title = f"{status} {model.name}" if model else f"{status} Tasks"

    return {
        "recognized": True,
        "entity": project,
        "kind": "project",
        "title": title,
        "description": f"{project.name} task status",
    }


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _route_preview(parsed):
    parts = _route_parts(parsed.path or "")
    if len(parts) < 2:
        return {"recognized": False}

    if (
        parts[0] == "projects"
        and len(parts) >= 4
        and parts[2] == "status"
    ):
        return _status_route_preview(parts, parsed)

    expected_kinds = DIRECT_ENTITY_ROUTES.get(parts[0])
    if not expected_kinds:
        return {"recognized": False}

    entity = Entities.fetch_one(parts[1], request=Fetch.direct())
    if not entity or entity.kind not in expected_kinds:
        return {
            "recognized": True,
            "entity": None,
            "kind": expected_kinds[0],
        }

    return {
        "recognized": True,
        "entity": entity,
        "kind": entity.kind,
        "title": entity.name,
        "description": getattr(entity, "description", None),
    }


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason helper-owned-by-preview-url-resolution
def _internal_preview(parsed, user=None, route_preview=None):
    route_preview = route_preview or _route_preview(parsed)
    if not route_preview.get("recognized"):
        raise PreviewError("Preview not found", status=404)

    entity = route_preview.get("entity")
    kind = route_preview.get("kind", "internal")
    if not entity or not entity.allowed(Action.VIEW, user=user):
        return _restricted_preview(parsed, kind=kind)

    url = _internal_url(parsed)
    return {
        "title": route_preview.get("title") or entity.name,
        "description": route_preview.get("description"),
        "url": url,
        "display_url": _display_url(parsed, internal=True),
        "kind": kind,
        "internal": True,
    }


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason external URL safety is owned by the preview workflow
def _safe_ip(value):
    address = ip_address(value)
    return not (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason external URL safety is owned by the preview workflow
def _safe_host(host):
    value = (host or "").strip().lower().rstrip(".")
    if not value or value == "localhost":
        return False

    try:
        return _safe_ip(value)
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(value, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    return bool(addresses) and all(_safe_ip(address[4][0]) for address in addresses)


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason external URL safety is owned by the preview workflow
def _validate_external_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_EXTERNAL_SCHEMES:
        raise PreviewError("Preview URL must use http or https")
    if parsed.username or parsed.password:
        raise PreviewError("Preview URL is not allowed")
    if not parsed.hostname or not _safe_host(parsed.hostname):
        raise PreviewError("Preview URL is not allowed")
    return parsed


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason response size limiting is owned by the preview fetch workflow
def _read_limited_response(response):
    chunks = []
    total = 0
    for chunk in response.iter_content(8192):
        if not chunk:
            continue
        total += len(chunk)
        chunks.append(chunk)
        if total >= MAX_METADATA_BYTES:
            break

    content = b"".join(chunks)
    encoding = response.encoding or response.apparent_encoding or "utf-8"
    return content.decode(encoding, errors="replace")


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason external metadata fetch is owned by preview_for_url
def _external_metadata(url):
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        _validate_external_url(current_url)
        response = requests.get(
            current_url,
            headers=METADATA_HEADERS,
            allow_redirects=False,
            timeout=METADATA_TIMEOUT,
            stream=True,
        )
        try:
            if response.is_redirect and response.headers.get("Location"):
                if redirect_count >= MAX_REDIRECTS:
                    raise PreviewError("Too many preview redirects")
                current_url = urljoin(current_url, response.headers["Location"])
                parsed = _validate_external_url(current_url)
                if parsed.path.startswith("/users/login") or parsed.path == "/login":
                    return {"name": RESTRICTED_TITLE, "description": None}
                continue

            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type and "html" not in content_type and "xml" not in content_type:
                return {}

            return link_metadata.extract_link_metadata(_read_limited_response(response))
        except requests.RequestException:
            return {}
        finally:
            response.close()

    return {}


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason external preview formatting is owned by preview_for_url
def _external_title(parsed):
    host = (parsed.hostname or parsed.netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason external preview formatting is owned by preview_for_url
def _external_preview(parsed):
    url = _external_url(parsed)
    _validate_external_url(url)
    metadata = _external_metadata(url)

    return {
        "title": metadata.get("name") or _external_title(parsed) or url,
        "description": metadata.get("description"),
        "url": url,
        "display_url": _display_url(parsed),
        "kind": "external",
        "internal": False,
    }


# @testable true
# @tests tests_unit/test_019_link_preview.py::test_internal_preview_returns_allowed_entity_metadata
# @tests tests_unit/test_019_link_preview.py::test_internal_status_preview_uses_project_permission
# @tests tests_unit/test_019_link_preview.py::test_internal_preview_hides_missing_or_forbidden_entities
# @tests tests_unit/test_019_link_preview.py::test_external_preview_maps_metadata_and_falls_back
# @tests tests_unit/test_019_link_preview.py::test_external_preview_rejects_unsafe_urls
# @features editor link-preview
# @dimensions internal external permissions metadata url-safety
def preview_for_url(url, user=None, base_url=None):
    value = str(url or "").strip()
    if not value:
        raise PreviewError("URL is required")

    parsed = _parse_url(value, base_url=base_url)
    route_preview = _route_preview(parsed) if _is_app_url(parsed, base_url) else None
    if route_preview and route_preview.get("recognized"):
        return _internal_preview(parsed, user=user, route_preview=route_preview)
    if _is_internal_url(parsed, base_url=base_url):
        return _internal_preview(parsed, user=user, route_preview=route_preview)

    return _external_preview(parsed)
