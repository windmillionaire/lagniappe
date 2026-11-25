"""Shared HTTP handling for the external agent API blueprints."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from flask import Response
    from flask.typing import ResponseReturnValue

    from lagniappe.core.tools.cache.rate_limit import RateLimit

from functools import wraps
import re
import uuid

from flask import g, jsonify, make_response, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from config.remote_mcp import mcp_issuer
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai.external_operations import ExternalPlanError
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.email.notifications.links import absolute_url

from . import api, api_family


_DOMAIN_ERROR_STATUSES = {
    "file_too_large": 422,
    "files_too_large": 422,
    "invalid_content_type": 422,
    "invalid_file": 422,
    "invalid_file_size": 422,
    "invalid_files": 422,
    "invalid_upload_batch_id": 422,
    "invalid_upload_state": 409,
    "not_found": 404,
    "plan_not_draft": 409,
    "plan_not_found": 404,
    "plan_operation_in_progress": 409,
    "plan_operation_lost": 409,
    "plan_state_conflict": 409,
    "plan_unavailable": 410,
    "too_many_files": 422,
    "unsupported_field": 422,
    "upload_batch_mismatch": 409,
    "uploads_pending": 409,
    "validation_failed": 422,
}

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_JSON_BODY_BYTES = external_api.MAX_PROPOSAL_BYTES + 64 * 1024
GENERAL_RATE_LIMIT = (60, 60)


def _api_origin() -> str:
    """Use the configured site origin, or the authenticated remote OAuth issuer."""
    if getattr(g, "remote_mcp_authenticated", False):
        return mcp_issuer(vars(CONFIG))
    if CONFIG.hosted_e2e:
        return CONFIG.BASE_URL.rstrip("/")
    return absolute_url("/").rstrip("/")


def api_absolute_url(path: str) -> str:
    """Build an API-advertised URL from the selected configured origin."""
    return f"{_api_origin()}/{str(path or '/').lstrip('/')}"


class APIProblem(Exception):
    """Expected client-facing API failure."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int,
        *,
        details: object = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        self.retry_after = retry_after


def _request_id():
    supplied = str(request.headers.get("X-Request-ID") or "").strip()
    if REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


def _error(code, message, status, *, details=None, retry_after=None):
    payload = {
        "error": {
            "code": code,
            "message": message,
        },
        "request_id": getattr(g, "agent_api_request_id", _request_id()),
    }
    if details is not None:
        payload["error"]["details"] = details
    response = make_response(jsonify(payload), status)
    if retry_after is not None:
        response.headers["Retry-After"] = str(max(int(retry_after), 1))
    if status == 401:
        response.headers["WWW-Authenticate"] = 'Bearer realm="Lagniappe API"'
    return response


def rate_limit(scope: str, identifier: object, limit: int, window_seconds: int) -> RateLimit:
    try:
        state = check_limit(scope, identifier, limit, window_seconds)
    except Exception as error:
        exceptions.capture(
            error,
            context={
                "agent_api": {
                    "request_id": g.agent_api_request_id,
                    "phase": "rate_limit",
                    "scope": scope,
                }
            },
        )
        raise APIProblem(
            "service_unavailable",
            "API rate limiting is temporarily unavailable.",
            503,
            retry_after=30,
        ) from error
    if not state["allowed"]:
        raise APIProblem(
            "rate_limited",
            "Too many API requests.",
            429,
            retry_after=state["retry_after"],
        )
    return state


@api.before_request
def authenticate_request() -> ResponseReturnValue | None:
    """Authenticate only a bearer token; browser sessions are never a fallback."""
    g.NO_CACHE = True
    g.agent_api_request_id = _request_id()
    if not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED:
        return _error("external_ai_disabled", "External AI access is disabled.", 403)
    # ``Content-Length`` is not guaranteed (for example with chunked transfer).
    # Werkzeug's limited request stream enforces this cap while JSON is read as
    # well as rejecting an oversized declared length up front.
    request.max_content_length = MAX_JSON_BODY_BYTES
    if request.content_length and request.content_length > MAX_JSON_BODY_BYTES:
        return _error("request_too_large", "Request body is too large.", 413)

    authorization = str(request.headers.get("Authorization") or "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        return _error("unauthorized", "A bearer API key is required.", 401)
    try:
        from config.remote_mcp import USER_TOKEN_HEADER
        from lagniappe.core.tools.auth import remote_mcp as remote_auth

        if USER_TOKEN_HEADER in request.headers:
            try:
                rate_limit(
                    "remote-mcp-envelope", client_ip(request), *GENERAL_RATE_LIMIT
                )
                actor, credential = remote_auth.authenticate_envelope(
                    token.strip(), request.headers[USER_TOKEN_HEADER]
                )
                g.remote_mcp_authenticated = True
            except remote_auth.OAuthError:
                return _error(
                    "unauthorized",
                    "The remote MCP connection is invalid or expired.",
                    401,
                )
            except APIProblem as problem:
                return _error(
                    problem.code,
                    problem.message,
                    problem.status,
                    retry_after=problem.retry_after,
                )
        else:
            actor, credential = agent_auth.authenticate_credential(token.strip())
    except agent_auth.AgentAPICredentialError:
        return _error("unauthorized", "The API key is invalid or expired.", 401)

    if actor is None:
        return _error("invalid_token", "Invalid bearer credential.", 401)
    if getattr(actor, "is_public", False):
        return _error(
            "forbidden",
            "This user cannot use external agent plans.",
            403,
        )
    g.agent_api_user = actor
    g.agent_api_credential = credential
    try:
        rate_limit(
            "agent-api-general",
            f"{actor.urlsafe_key}:{client_ip(request)}",
            *GENERAL_RATE_LIMIT,
        )
    except APIProblem as problem:
        return _error(
            problem.code,
            problem.message,
            problem.status,
            retry_after=problem.retry_after,
        )
    return None


api_family.before_request(authenticate_request)


@api.after_request
def annotate_response(response: Response) -> Response:
    response.headers["X-Request-ID"] = getattr(
        g,
        "agent_api_request_id",
        "",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Lagniappe-Build-ID"] = CONFIG.BUILD_ID
    if digest := getattr(g, "mcp_metadata_digest", None):
        response.headers["X-Lagniappe-MCP-Metadata"] = digest
    return response


api_family.after_request(annotate_response)


def handle_api_http_error(error: HTTPException) -> Response:
    """Render routing-level API failures with the normal JSON envelope."""
    g.NO_CACHE = True
    if not getattr(g, "agent_api_request_id", None):
        g.agent_api_request_id = _request_id()
    if not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED:
        return _error("external_ai_disabled", "External AI access is disabled.", 403)

    status = (error.code or 500) if isinstance(error, HTTPException) else 500
    code, message = {
        404: ("not_found", "API resource not found."),
        405: ("method_not_allowed", "Method not allowed for this API resource."),
    }.get(status, ("request_failed", "The API request could not be completed."))
    response = _error(code, message, status)
    if status == 405 and isinstance(error, HTTPException):
        allow = error.get_response().headers.get("Allow")
        if allow:
            response.headers["Allow"] = allow
    return annotate_response(response)


@api.errorhandler(APIProblem)
def handle_api_problem(problem: APIProblem) -> ResponseReturnValue:
    return _error(
        problem.code,
        problem.message,
        problem.status,
        details=problem.details,
        retry_after=problem.retry_after,
    )


@api.errorhandler(Exception)
def handle_unexpected_error(error: Exception) -> Response:
    if isinstance(error, HTTPException):
        return _error(
            "request_failed",
            error.description or "Request failed.",
            error.code or 500,
        )
    exceptions.capture(
        error,
        context={
            "agent_api": {
                "request_id": getattr(g, "agent_api_request_id", None),
                "path": request.path,
            }
        },
    )
    return _error(
        "internal_error",
        "The API request could not be completed.",
        500,
    )


def api_route[**P](
    handler: Callable[P, ResponseReturnValue],
) -> Callable[P, ResponseReturnValue]:
    """Qualify record links and translate expected domain failures."""

    @wraps(handler)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> ResponseReturnValue:
        try:
            response = handler(*args, **kwargs)
            return cast(
                "ResponseReturnValue",
                external_api.absolute_entity_links(response, origin=_api_origin()),
            )
        except ExternalPlanError as error:
            raise APIProblem(
                error.reason, str(error), _DOMAIN_ERROR_STATUSES[error.reason],
                details=error.details,
            ) from error
        except APIProblem:
            raise
        except (exceptions.AIException, exceptions.ValidationError) as error:
            raise APIProblem("validation_failed", str(error), 422) from error
        except (storage_assets.DirectUploadError, ValueError, TypeError) as error:
            raise APIProblem("invalid_request", str(error), 422) from error

    return wrapped


def json_body() -> dict[str, Any]:
    try:
        data = request.get_json(silent=True)
    except RequestEntityTooLarge as error:
        raise APIProblem(
            "request_too_large", "Request body is too large.", 413
        ) from error
    if not isinstance(data, dict):
        raise APIProblem(
            "invalid_json",
            "Request body must be a JSON object.",
            400,
        )
    return data
