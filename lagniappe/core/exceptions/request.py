"""Bound and sanitize request context used in error reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from sentry_sdk.types import Attributes, DataCollectionUserOptions, Event, Hint, SpanJSON
import re
from urllib.parse import urlsplit

from flask import has_request_context, request

REDACTED = "[REDACTED]"
MAX_CONTEXT_DEPTH = 8
MAX_CONTEXT_ITEMS = 25
MAX_CONTEXT_KEY_LENGTH = 80
MAX_CONTEXT_STRING_LENGTH = 512
MAX_HEADER_VALUE_LENGTH = 256
MAX_REPORTED_CONTENT_LENGTH = 1_000_000_000

_ALLOWED_HEADERS = frozenset(
    {
        "accept",
        "user-agent",
        "x-lagniappe-request",
        "x-requested-with",
    }
)
SENTRY_DATA_COLLECTION: DataCollectionUserOptions = {
    "user_info": False,
    "http_headers": {"request": {"mode": "allowlist", "terms": sorted(_ALLOWED_HEADERS)}},
    "http_bodies": [],
    "cookies": {"mode": "off"},
    "url_query_params": {"mode": "off"},
    "gen_ai": {"inputs": False, "outputs": False},
    "mcp": {"inputs": False, "outputs": False},
    "graphql": {"document": False, "variables": False},
    "queues": False,
    "database_query_data": False,
    "stack_frame_variables": False,
}

_DIRECT_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "dsn",
        "email",
        "email_address",
        "ip_address",
        "password",
        "passwd",
        "passphrase",
        "proxy_authorization",
        "remote_addr",
        "secret",
        "session",
        "sessionid",
        "set_cookie",
        "user",
        "user_id",
        "username",
        "state",
        "code_verifier",
        "code_challenge",
    }
)
_SAFE_TOKEN_METADATA_KEYS = frozenset(
    {
        "input_token_count",
        "input_tokens",
        "output_token_count",
        "output_tokens",
        "token_count",
        "total_token_count",
        "total_tokens",
    }
)
_PAYLOAD_KEYS = frozenset(
    {
        "body",
        "content",
        "contents",
        "data_uri",
        "document",
        "document_text",
        "entity",
        "file_name",
        "filename",
        "form",
        "input",
        "inputs",
        "json",
        "locals",
        "message_history",
        "messages",
        "output",
        "outputs",
        "payload",
        "prompt",
        "prompts",
        "query",
        "query_string",
        "http_query",
        "request_body",
        "response_body",
        "vars",
    }
)
_AUTH_VALUE_PATTERN = re.compile(
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_MCP_OAUTH_PATTERN = re.compile(r"\blgmo_[pcar]_[A-Za-z0-9_-]+\b")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (
        ["']?
        (?:
            password|passwd|passphrase|secret|api[_-]?key|private[_-]?key|
            access[_-]?token|refresh[_-]?token|auth(?:orization)?|cookie|
            session(?:id)?|state|code[_-]?verifier|code[_-]?challenge
        )
        ["']?
        \s*[:=]\s*
    )
    (?:
        "[^"]*" |
        '[^']*' |
        [^\s,;}]+
    )
    """,
)


def _normalized_key(key):
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
    return re.sub(r"[^a-z0-9]+", "_", expanded.lower()).strip("_")


def _is_sensitive_key(key):
    normalized = _normalized_key(key)
    if normalized in {"url_path", "url_query", "url_fragment", "http_fragment"}:
        return True
    if normalized in _DIRECT_SENSITIVE_KEYS or normalized in _PAYLOAD_KEYS:
        return True

    parts = set(normalized.split("_"))
    if parts.intersection(
        {
            "authorization",
            "cookie",
            "credential",
            "password",
            "passwd",
            "passphrase",
            "secret",
            "session",
        }
    ):
        return True
    if parts.intersection({"token", "tokens"}):
        return normalized not in _SAFE_TOKEN_METADATA_KEYS
    return bool(
        {"api", "key"} <= parts
        or {"private", "key"} <= parts
        or {"signing", "key"} <= parts
        or {"access", "code"} <= parts
    )


def _sanitize_text(value, *, limit=MAX_CONTEXT_STRING_LENGTH):
    text = str(value)
    if "-----BEGIN" in text.upper() and "PRIVATE KEY-----" in text.upper():
        return REDACTED

    text = _SECRET_ASSIGNMENT_PATTERN.sub(rf"\1{REDACTED}", text)
    text = _AUTH_VALUE_PATTERN.sub(REDACTED, text)
    text = _JWT_PATTERN.sub(REDACTED, text)
    text = _MCP_OAUTH_PATTERN.sub(REDACTED, text)
    if len(text) > limit:
        return f"{text[:limit]}… [truncated]"
    return text


def _sanitize_url(value: object) -> dict[str, str | int | bool]:
    metadata: dict[str, str | int | bool] = {
        "parseable": False,
        "has_path": False,
        "has_query": False,
        "has_fragment": False,
        "has_credentials": False,
    }
    if not isinstance(value, str):
        return metadata

    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return metadata

    metadata.update(
        {
            "parseable": bool(parsed.scheme and host),
            "has_path": bool(parsed.path),
            "has_query": bool(parsed.query),
            "has_fragment": bool(parsed.fragment),
            "has_credentials": parsed.username is not None
            or parsed.password is not None,
        }
    )
    if parsed.scheme:
        metadata["scheme"] = _sanitize_text(parsed.scheme.casefold(), limit=16)
    if host:
        metadata["host"] = _sanitize_text(host.casefold(), limit=MAX_CONTEXT_KEY_LENGTH)
    if port is not None:
        metadata["port"] = port
    return metadata


def _sanitize_value(value, *, key=None, depth=0):
    if key is not None and _normalized_key(key) in {"url", "http_url", "url_full"}:
        return _sanitize_url(value)
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if depth >= MAX_CONTEXT_DEPTH:
        return "[MAX DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Mapping):
        sanitized = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= MAX_CONTEXT_ITEMS:
                sanitized["_truncated_items"] = len(value) - MAX_CONTEXT_ITEMS
                break
            safe_key = _sanitize_text(child_key, limit=MAX_CONTEXT_KEY_LENGTH)
            sanitized[safe_key] = _sanitize_value(
                child_value,
                key=child_key,
                depth=depth + 1,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(child, depth=depth + 1)
            for child in value[:MAX_CONTEXT_ITEMS]
        ]
    if isinstance(value, (set, frozenset)):
        return f"<{type(value).__name__}:{len(value)}>"
    return f"<{type(value).__name__}>"


@overload
def sanitize_error_context(value: Mapping[str, object]) -> dict[str, object]: ...


@overload
def sanitize_error_context(value: object) -> object: ...


def sanitize_error_context(value: object) -> object:
    """Return a bounded, serialization-safe copy with sensitive values removed."""
    return _sanitize_value(value)


def _summarize_parameters(parameters):
    fields = []
    for name in list(parameters.keys())[:MAX_CONTEXT_ITEMS]:
        fields.append(
            {
                "name": _sanitize_text(name, limit=MAX_CONTEXT_KEY_LENGTH),
                "value_count": len(parameters.getlist(name)),
            }
        )
    return {
        "field_count": len(parameters),
        "fields": fields,
        "truncated": len(parameters) > MAX_CONTEXT_ITEMS,
    }


def _bounded_content_length(content_length):
    if content_length is None:
        return None, False
    value = max(0, int(content_length))
    return min(value, MAX_REPORTED_CONTENT_LENGTH), value > MAX_REPORTED_CONTENT_LENGTH


def extract_request_info() -> dict[str, object] | None:
    """Extract bounded request structure without payload or identifier values."""
    if not has_request_context():
        return None

    rule = request.url_rule
    content_length, content_length_capped = _bounded_content_length(
        request.content_length
    )
    info = {
        "method": _sanitize_text(request.method, limit=16),
        "endpoint": _sanitize_text(request.endpoint, limit=MAX_CONTEXT_KEY_LENGTH)
        if request.endpoint
        else None,
        "route": _sanitize_text(rule.rule, limit=MAX_CONTEXT_STRING_LENGTH)
        if rule
        else None,
        "route_parameters": sorted(rule.arguments)[:MAX_CONTEXT_ITEMS] if rule else [],
        "query_parameters": _summarize_parameters(request.args),
        "body_metadata": {
            "content_type": _sanitize_text(
                request.mimetype, limit=MAX_CONTEXT_KEY_LENGTH
            )
            if request.mimetype
            else None,
            "content_length": content_length,
            "content_length_capped": content_length_capped,
        },
    }

    headers = {}
    for name, value in request.headers.items():
        if name.lower() in _ALLOWED_HEADERS:
            headers[name] = _sanitize_text(value, limit=MAX_HEADER_VALUE_LENGTH)
    if headers:
        info["headers"] = headers

    return info


def sanitize_sentry_event(event: Event, _hint: Hint | None = None) -> Event:
    """Apply the privacy boundary to SDK-generated Sentry event fields."""
    if not isinstance(event, Mapping):
        return event

    sanitized = dict(event)
    sanitized.pop("user", None)

    request_data = event.get("request")
    if isinstance(request_data, Mapping):
        safe_request = {}
        if request_data.get("method"):
            safe_request["method"] = _sanitize_text(request_data["method"], limit=16)

        raw_headers = request_data.get("headers")
        if isinstance(raw_headers, Mapping):
            safe_headers = {
                str(name): _sanitize_text(value, limit=MAX_HEADER_VALUE_LENGTH)
                for name, value in raw_headers.items()
                if str(name).lower() in _ALLOWED_HEADERS
            }
            if safe_headers:
                safe_request["headers"] = safe_headers

        if safe_request:
            sanitized["request"] = safe_request
        else:
            sanitized.pop("request", None)

    for key in (
        "breadcrumbs",
        "contexts",
        "exception",
        "extra",
        "fingerprint",
        "logentry",
        "message",
        "spans",
        "tags",
        "threads",
    ):
        if key in sanitized:
            sanitized[key] = sanitize_error_context(sanitized[key])

    return cast("Event", sanitized)


def sanitize_sentry_span(span: SpanJSON, _hint: Hint) -> SpanJSON:
    """Keep route templates and operation timing without recording raw span descriptions."""
    attributes = span.get("attributes", {})
    safe: Attributes = {}
    for key in ("sentry.op", "sentry.origin", "http.request.method", "http.route", "db.system.name"):
        value = attributes.get(key)
        if isinstance(value, str):
            safe[key] = _sanitize_text(value)
    for key in (
        "http.response.status_code", "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens", "gen_ai.usage.cache_read.input_tokens",
    ):
        value = attributes.get(key)
        if isinstance(value, int):
            safe[key] = value

    # Integrations may use a raw URL, a Redis command or a query as the span name.
    name = safe.get("http.route") or safe.get("sentry.op") or "operation"
    return {**span, "name": str(name), "attributes": safe}


def _is_expected_ai_document_limit(event):
    exception = event.get("exception") if isinstance(event, Mapping) else None
    values = exception.get("values") if isinstance(exception, Mapping) else None
    if not isinstance(values, list):
        return False
    return any(
        isinstance(value, Mapping)
        and value.get("type") == "ClientError"
        and "exceeds the supported page limit"
        in str(value.get("value") or "").casefold()
        for value in values
    )


def filter_sentry_event(event: Event, hint: Hint | None = None) -> Event | None:
    """Drop known user-input limits, then sanitize every reported error."""
    if _is_expected_ai_document_limit(event):
        return None
    return sanitize_sentry_event(event, hint)
