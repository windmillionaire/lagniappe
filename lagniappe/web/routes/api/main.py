"""REST transport for provider-free external agent plans."""

from functools import wraps
import json
import logging
import re
import time
import uuid

from flask import g, jsonify, make_response, request, url_for
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from config.remote_mcp import mcp_issuer
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import summarize_actions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai.external import definitions
from lagniappe.core.tools.ai.external_operations import ExternalPlanError
from lagniappe.core.tools.ai.external.openapi import build_openapi_document
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai.references import hash_reference, normalize_hash_references
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

LOGGER = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_JSON_BODY_BYTES = external_api.MAX_PROPOSAL_BYTES + 64 * 1024
GENERAL_RATE_LIMIT = (60, 60)
PLAN_START_RATE_LIMIT = (100, 60 * 60)
PLAN_TOOL_RATE_WINDOW = 31 * 24 * 60 * 60


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_api_uses_only_a_configured_request_origin
# @matrix agent-api : discovery origin-validation proposal-contract
def _api_origin():
    """Use the configured site origin, or the authenticated remote OAuth issuer."""
    if getattr(g, "remote_mcp_authenticated", False):
        return mcp_issuer(vars(CONFIG))
    if CONFIG.hosted_e2e:
        return CONFIG.BASE_URL.rstrip("/")
    return absolute_url("/").rstrip("/")


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::_api_origin
# @reason URL joining is exercised across discovery, OpenAPI, plan, and contract links
def _api_absolute_url(path):
    """Build an API-advertised URL from the selected configured origin."""
    return f"{_api_origin()}/{str(path or '/').lstrip('/')}"


# @testable infrastructure
class APIProblem(Exception):
    """Expected client-facing API failure."""

    def __init__(self, code, message, status, *, details=None, retry_after=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        self.retry_after = retry_after


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::authenticate_request
# @reason request correlation is part of the public authentication envelope
def _request_id():
    supplied = str(request.headers.get("X-Request-ID") or "").strip()
    if REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::authenticate_request
# @reason stable errors are asserted through the public bearer boundary
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


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::authenticate_request
# @reason shared Redis limiter behavior is owned by the authenticated API boundary
def _rate_limit(scope, identifier, limit, window_seconds):
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


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_external_api_authentication_and_header_contract
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_external_api_bounds_json_without_a_declared_content_length
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_api_ignores_provider_entitlement_but_rechecks_public_eligibility
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_token_api_envelope_and_browser_revocation
# @matrix agent-api : site-policy bearer-only body-limit entitlement-independent error-envelope public-user request-correlation request-recheck session-independent streaming
# @pairs agent-api:rate-limit
@api.before_request
def authenticate_request():
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
                _rate_limit(
                    "remote-mcp-envelope", client_ip(request), *GENERAL_RATE_LIMIT
                )
                actor, credential = remote_auth.authenticate_envelope(
                    token.strip(), request.headers.get(USER_TOKEN_HEADER)
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

    if getattr(actor, "is_public", False):
        return _error(
            "forbidden",
            "This user cannot use external agent plans.",
            403,
        )
    g.agent_api_user = actor
    g.agent_api_credential = credential
    try:
        _rate_limit(
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


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_external_api_authentication_and_header_contract
# @matrix agent-api : build-marker error-envelope no-store request-correlation
@api.after_request
def annotate_response(response):
    response.headers["X-Request-ID"] = getattr(
        g,
        "agent_api_request_id",
        "",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Lagniappe-Build-ID"] = CONFIG.BUILD_ID
    return response


api_family.after_request(annotate_response)


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_csrf_exempt_surfaces_reach_replacement_authentication_gates
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : error-envelope routing
def handle_api_http_error(error):
    """Render routing-level API failures with the normal JSON envelope."""
    g.NO_CACHE = True
    if not getattr(g, "agent_api_request_id", None):
        g.agent_api_request_id = _request_id()
    if not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED:
        return _error("external_ai_disabled", "External AI access is disabled.", 403)

    status = error.code if isinstance(error, HTTPException) else 500
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


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::authenticate_request
# @reason expected problem rendering uses the same tested error envelope
@api.errorhandler(APIProblem)
def handle_api_problem(problem):
    return _error(
        problem.code,
        problem.message,
        problem.status,
        details=problem.details,
        retry_after=problem.retry_after,
    )


# @testable infrastructure
@api.errorhandler(Exception)
def handle_unexpected_error(error):
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


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::create_plan
# @covered-by lagniappe/web/routes/api/main.py::_api_origin
# @reason domain-exception translation is exercised through public API routes
def _route(handler):
    """Qualify record links and translate expected domain failures."""

    # @testable false
    # @covered-by lagniappe/web/routes/api/main.py::_route
    # @reason generated decorator closure delegates to the route translator
    @wraps(handler)
    def wrapped(*args, **kwargs):
        try:
            return external_api.absolute_entity_links(
                handler(*args, **kwargs), origin=_api_origin()
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


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::create_plan
# @reason request normalization is exercised through plan creation
def _json_body():
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


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason response normalization is exercised through tool dispatch
def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::_plan_payload
# @reason file projection is part of the plan response contract
def _file_payload(file):
    return {
        "ref": hash_reference(file),
        "name": file.name,
        "filename": file.filename,
        "mimetype": file.mimetype,
        "size": file.size,
    }






# @testable false
# @covered-by lagniappe/web/routes/api/main.py::get_plan
# @reason plan projection is asserted through the public plan resource
def _plan_payload(report, *, include_proposal=True):
    payload = {
        "id": report.urlsafe_key,
        "status": report.status,
        "output_kind": report.output_kind,
        "file_usage": report.file_usage or [],
        "name": report.name,
        "instructions": report.instructions,
        "files": [_file_payload(file) for file in report.input_files],
        "uploads_pending": bool(report.upload_manifest),
        "upload_batch_id": external_api.current_upload_batch_id(report),
        "contract_version": external_api.CONTRACT_VERSION,
        "contract_url": _api_absolute_url(
            url_for(
                "agent_api.get_plan_contract",
                plan_id=report.urlsafe_key,
            )
        ),
        "submit_url": _api_absolute_url(
            url_for(
                "agent_api.submit_plan",
                plan_id=report.urlsafe_key,
            )
        ),
        "status_url": _api_absolute_url(
            url_for(
                "agent_api.get_plan",
                plan_id=report.urlsafe_key,
            )
        ),
        "preview_url": _api_absolute_url(
            url_for(
                "tools.api_plan_preview",
                plan_hash=report.hash,
            )
        ),
        "review_url": _api_absolute_url(
            url_for(
                "tools.report",
                key=report.urlsafe_key,
            )
        ),
    }
    if include_proposal:
        payload["proposal"] = external_api.public_plan_proposal(report, g.agent_api_user)
        if report.output_kind == "proposal":
            payload["execution"] = external_api.public_execution_receipt(
                report, g.agent_api_user
            )
        payload["correction"] = report.db.get("correction")
        payload["superseded_by"] = report.db.get("superseded_by")
        payload["original_brief"] = (report.agent_manifest or {}).get("original_brief")
    if report.output_kind == "proposal":
        payload["action_summary"] = summarize_actions(report.proposal, maximum=external_api.MAX_PROPOSAL_ACTIONS)
    return _json_safe(payload)


# @testable false
# @covered-by lagniappe/core/tools/ai/external/plans.py::submit_plan_request
# @reason compact publication fields are asserted through the public submit resource
def _submission_receipt(report):
    """Return a compact receipt without echoing the normalized proposal."""
    plan = _plan_payload(report, include_proposal=False)
    manifest = (
        report.agent_manifest
        if isinstance(getattr(report, "agent_manifest", None), dict)
        else {}
    )
    return {
        "id": plan["id"],
        "status": plan["status"],
        "preview_url": plan["preview_url"],
        "review_url": plan["review_url"],
        "status_url": plan["status_url"],
        "contract_version": plan["contract_version"],
        "proposal_fingerprint": manifest.get("proposal_fingerprint"),
        **({"action_summary": plan["action_summary"]} if "action_summary" in plan else {}),
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_api_ignores_provider_entitlement_but_rechecks_public_eligibility
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_resources_hide_other_users_plans
# @matrix agent-api : creator-bound entitlement-independent generic-not-found plan-isolation stale-plan
def _load_plan(plan_id):
    return external_api.load_plan(plan_id, g.agent_api_user)



# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason availability is exercised through the public plan-scoped tool resource
def _require_tools_available(report):
    if report.status == "draft":
        return
    if report.output_kind == "answer" and report.status == "complete":
        return
    if report.output_kind == "proposal" and report.status == "ready":
        return
    raise APIProblem(
        "plan_tools_unavailable",
        "Read tools are available only for draft plans, completed answers, and "
        "ready proposals. For ordinary workspace reads after "
        "execution, omit plan_id; use get_plan for the execution outcomes.",
        409,
    )


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::api_index
# @reason shared URL assembly is exercised by both authenticated discovery resources
def _discovery_payload():
    return {
        "name": "Lagniappe External Agent API",
        "version": "v1",
        "base_url": _api_absolute_url(url_for("agent_api.api_index")).rstrip("/"),
        "openapi_url": _api_absolute_url(url_for("agent_api.openapi_document")),
        "actor_url": _api_absolute_url(url_for("agent_api.me")),
        "tools_url": _api_absolute_url(url_for("agent_api.tools")),
        "plans_url": _api_absolute_url(url_for("agent_api.create_plan")),
        "answer_context_url": _api_absolute_url(url_for("agent_api.answer_context")),
        "client_skill_url": _api_absolute_url(url_for("agent_api.client_skill")),
        "authentication": "Authorization: Bearer <user API key>",
        "instructions": (
            "Read openapi_url before using or guessing resource paths, then call "
            "actor_url to verify the user and capabilities."
        ),
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : discovery bearer-only
@api_family.get("/", strict_slashes=False)
@_route
def api_family_index():
    """Identify the current version without duplicating its contract."""
    current = _discovery_payload()
    return {
        "name": current["name"],
        "current_version": current["version"],
        "versions": [current],
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : discovery bearer-only
@api.get("/", strict_slashes=False)
@_route
def api_index():
    """Point an authenticated client directly to API discovery resources."""
    return _discovery_payload()


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : bootstrap bearer-only discovery
@api.get("/client-skill.md")
@_route
def client_skill():
    """Return a copyable, discovery-first client skill without API schemas."""
    response = make_response(
        external_api.client_skill_markdown(
            _api_absolute_url(url_for("agent_api.api_index")).rstrip("/")
        )
    )
    response.headers["Content-Type"] = "text/markdown; charset=utf-8"
    response.headers["Content-Disposition"] = 'inline; filename="SKILL.md"'
    return response


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : contract
@api.get("/openapi.json")
@_route
def openapi_document():
    """Return the authenticated external-agent contract."""
    return build_openapi_document(
        app_name=CONFIG.APP_NAME, server_url=_api_absolute_url("/"),
    )


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_types_are_available_without_provider_access
# @matrix agent-api : bearer-only entitlement-independent plan-capability
@api.get("/me")
@_route
def me():
    actor = g.agent_api_user
    return {
        "user": {
            "name": actor.name,
            "hash": actor.hash,
            "timezone": external_api.user_timezone_name(actor),
            "personal_page": external_api.personal_page_reference(actor),
        },
        "credential": g.agent_api_credential,
        "capabilities": {
            "plans": True,
            **({"execute_plan": _experiments_execution_allowed()} if CONFIG.EXPERIMENTS_ENABLED else {}),
        },
        **({"installation": {
            "project": CONFIG.GOOGLE_CLOUD_PROJECT,
            "experiments": True,
            "source_id": CONFIG.EXPERIMENTS_SOURCE_ID or None,
        }} if CONFIG.EXPERIMENTS_ENABLED else {}),
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : tool-catalog
@api.get("/tools")
@_route
def tools():
    selected = []
    for value in request.args.getlist("names"):
        selected.extend(name.strip() for name in value.split(",") if name.strip())
    selected = selected or None
    view = str(request.args.get("view") or "full").strip().casefold()
    if view not in {"full", "names"}:
        raise APIProblem(
            "invalid_tool_catalog_view",
            "Tool catalog view must be full or names.",
            422,
        )
    try:
        catalog = ai_functions.tool_catalog(
            names=selected,
            names_only=view == "names",
            transport="rest",
        )
    except ValueError as error:
        raise APIProblem(
            "unknown_tool_selection",
            str(error),
            422,
            details={"available": list(ai_functions.DECLARATIONS)},
        ) from error
    return {
        "tools": catalog,
        "view": view,
        "selected_count": len(catalog),
        "reference_format": "hash:<12-character-hash>",
        "execution_envelope": {
            "success": {"result": "<value matching the selected output_schema>"},
            "failure": {
                "error": {"code": "tool_error", "message": "<message>"},
                "request_id": "<request id>",
            },
        },
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_plan_free_reads_and_answer_context_do_not_create_reports
# @pair agent-api:answer-context
@api.get("/answer-context")
@_route
def answer_context():
    return external_api.answer_context(g.agent_api_user)


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_types_are_available_without_provider_access
# @matrix agent-api : entitlement-independent plan-session tool-selection
# @pairs agent-api:rate-limit
@api.post("/plans")
@_route
def create_plan():
    actor = g.agent_api_user
    _rate_limit(
        "agent-api-plan-start",
        f"{actor.urlsafe_key}:{client_ip(request)}",
        *PLAN_START_RATE_LIMIT,
    )
    data = _json_body()
    envelope = definitions.create_plan_request_schema()
    unsupported_fields = sorted(set(data) - set(envelope["properties"]))
    if unsupported_fields:
        raise APIProblem(
            "unsupported_field",
            "Plan request contains unsupported fields.",
            422,
            details={
                "path": "$",
                "fields": unsupported_fields,
                "allowed_fields": list(envelope["properties"]),
            },
        )
    instructions = data.get("instructions", "")
    if not isinstance(instructions, str):
        raise APIProblem(
            "invalid_instructions", "instructions must be a string.", 422,
            details={"path": "$.instructions", "expected": "string"},
        )
    name = data.get("name")
    if "name" in data and (not isinstance(name, str) or len(name) > definitions.MAX_PLAN_NAME_CHARACTERS):
        raise APIProblem(
            "invalid_name",
            f'"name" must be a string of at most {definitions.MAX_PLAN_NAME_CHARACTERS} characters.',
            422,
            details={
                "path": "$.name",
                "expected": f"string with at most {definitions.MAX_PLAN_NAME_CHARACTERS} characters",
            },
        )
    report = external_api.create_plan(
        actor,
        instructions=instructions,
        name=name,
        remote_mcp=bool(getattr(g, "remote_mcp_authenticated", False)),
        revises_plan_id=data.get("revises_plan_id"),
    )
    return _plan_payload(report), 201


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : plan-session
@api.get("/plans/<plan_id>")
@_route
def get_plan(plan_id):
    return _plan_payload(_load_plan(plan_id))


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_plan
# @reason capability discovery and the write boundary share this gate
def _experiments_execution_allowed():
    from lagniappe.core.tools.experiments import can_execute
    return can_execute(g.agent_api_user, remote_mcp=bool(getattr(g, "remote_mcp_authenticated", False)))


# @testable true
# @tests tests_e2e/013_agent_api/test_013g_experiments.py::test_experiments_execute_requires_remote_admin_and_exact_proposal
# @matrix experiments : http-execution
@api.post("/plans/<plan_id>/execute")
@_route
def execute_plan(plan_id):
    if not _experiments_execution_allowed():
        raise APIProblem("execution_forbidden", "This connection cannot execute experiments plans.", 403)
    data = _json_body()
    if set(data) != {"proposal_fingerprint", "operation_id"} or not isinstance(data.get("proposal_fingerprint"), str) or not re.fullmatch(r"[a-f0-9]{64}", data["proposal_fingerprint"]) or not isinstance(data.get("operation_id"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", data["operation_id"]):
        raise APIProblem("invalid_execution", "Supply the submitted proposal_fingerprint and a stable operation_id (1–128 letters, digits, dots, underscores or hyphens).", 422)
    report = _load_plan(plan_id)
    from lagniappe.core.tools.ai.reporting.execution.request import request_execution
    job, _notification = request_execution(
        report, g.agent_api_user,
        operation_id=data["operation_id"],
        expected_fingerprint=data["proposal_fingerprint"],
        remote_mcp=True,
    )
    return {
        "plan": _plan_payload(_load_plan(plan_id)),
        "operation": {"id": job.idempotency_key, "status": job.status},
    }, 202


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : proposal-contract
@api.get("/plans/<plan_id>/contract")
@_route
def get_plan_contract(plan_id):
    report = _load_plan(plan_id)
    actions = [
        name.strip()
        for value in request.args.getlist("actions")
        for name in value.split(",")
        if name.strip()
    ] if "actions" in request.args else None
    contract = external_api.plan_contract(
        report,
        g.agent_api_user,
        submit_url=_api_absolute_url(
            url_for(
                "agent_api.submit_plan",
                plan_id=report.urlsafe_key,
            )
        ),
        **({"actions": actions} if actions is not None else {}),
        **({"view": request.args["view"]} if "view" in request.args else {}),
        execution_allowed=_experiments_execution_allowed(),
    )
    LOGGER.info(
        "agent_api_contract request_id=%s user_hash=%s plan=%s "
        "contract_bytes=%d proposal_schema_bytes=%d",
        g.agent_api_request_id,
        g.agent_api_user.hash,
        report.hash,
        len(json.dumps(contract, ensure_ascii=False, default=str).encode("utf-8")),
        (contract.get("payload_sizes") or {}).get("proposal_schema_bytes", 0),
    )
    return contract



# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_upload_batch_identity_rejects_a_same_metadata_last_writer
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_claimed_upload_routes_reload_before_storage_side_effects
# @matrix agent-api mcp-upload : last-writer upload-batch-identity uploads
# @pairs agent-api:authoritative-reload agent-api:concurrency agent-api:stale-snapshot
# @pairs mcp-upload:authoritative-reload mcp-upload:concurrency mcp-upload:stale-snapshot
@api.post("/plans/<plan_id>/uploads")
@_route
def create_uploads(plan_id):
    report = _load_plan(plan_id)
    external_api.require_uploads_available(report)
    data = _json_body()
    return external_api.create_upload_sessions(
        report, g.agent_api_user, data, request_id=g.agent_api_request_id,
    ), 201


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_upload_batch_identity_rejects_a_same_metadata_last_writer
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_claimed_upload_routes_reload_before_storage_side_effects
# @matrix agent-api mcp-upload : last-writer upload-batch-identity uploads
# @matrix agent-api mcp-upload : authoritative-reload concurrency checkpoint resume stale-snapshot
@api.post("/plans/<plan_id>/uploads/finalize")
@_route
def finalize_uploads(plan_id):
    report = _load_plan(plan_id)
    external_api.require_draft(report)
    data = _json_body()
    finalized = external_api.finalize_upload_batch(
        report, g.agent_api_user, data, request_id=g.agent_api_request_id,
    )
    return _plan_payload(finalized)


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason signed original-file projection belongs to permission-bounded tool dispatch
def _original_file_download(tool_name, arguments, result):
    if tool_name != "get_file" or not isinstance(arguments, dict):
        return result
    include_original = arguments.get("include_original")
    include_original = include_original is True or str(
        include_original
    ).strip().casefold() in {"1", "true", "yes", "on"}
    original_file = result.get("original_file") if isinstance(result, dict) else None
    if (
        not include_original
        and isinstance(original_file, dict)
        and original_file.get("supported") is not False
    ):
        return result

    normalized = normalize_hash_references(arguments)
    entity = Entities.fetch_one(normalized.get("id"), request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    if not isinstance(entity, Entities.FILE) or not entity.allowed(
        Action.VIEW, user=g.agent_api_user
    ):
        return result
    asset = entity.properties.file.value
    if not asset or not asset.path:
        return result

    if not isinstance(result, dict):
        result = {"result": result}
    result = dict(result)
    if not include_original:
        result["original_file"] = {
            "supported": True,
            "attached": False,
            "reason": (
                "Original content was not included by default. Call get_file "
                "again with include_original=true to receive a five-minute signed "
                "download URL."
            ),
        }
        return result

    download_url = storage_assets.get_signed_url(asset.path, expires_in=300)
    result["original_file"] = {
        "supported": True,
        "attached": False,
        "download_url": download_url,
        "expires_in": 300,
    }
    return result


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_types_are_available_without_provider_access
# @matrix agent-api : tool-dispatch
# @pair agent-api:answer-context
# @pairs agent-api:ask-refinement agent-api:create-revision agent-api:organize-revision agent-api:envelope-validation
# @pairs agent-api:rate-limit
@api.post("/tools/<tool_name>", defaults={"plan_id": None})
@api.post("/plans/<plan_id>/tools/<tool_name>")
@_route
def execute_tool(plan_id, tool_name):
    report = _load_plan(plan_id) if plan_id is not None else None
    if report is not None:
        _require_tools_available(report)
    if tool_name not in ai_functions.TOOL_DEFINITIONS:
        raise APIProblem("tool_not_found", "Tool not found.", 404)
    rate_state = (
        _rate_limit(
            "agent-api-plan-tools",
            report.urlsafe_key,
            external_api.MAX_PLAN_TOOL_CALLS,
            PLAN_TOOL_RATE_WINDOW,
        )
        if report is not None
        else {"count": 0}
    )
    data = _json_body()
    unsupported = sorted(set(data) - {"arguments"})
    if unsupported:
        raise APIProblem(
            "invalid_arguments",
            "Put tool inputs inside the top-level arguments object; unsupported "
            f"top-level fields: {', '.join(unsupported)}.",
            422,
        )
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise APIProblem(
            "invalid_arguments",
            "arguments must be a JSON object.",
            422,
        )

    started = time.monotonic()
    outcome = "success"
    result_bytes = 0
    try:
        result, _file_parts = ai_functions.execute_registered_tool(
            tool_name,
            arguments,
            g.agent_api_user,
            external=True,
        )
        result = _original_file_download(tool_name, arguments, result)
        safe_result = _json_safe(result)
        result_bytes = len(
            json.dumps(safe_result, ensure_ascii=False, default=str).encode("utf-8")
        )
        if isinstance(result, dict) and result.get("error"):
            outcome = "tool_error"
            details = {
                "tool": tool_name,
                **{
                    key: _json_safe(value)
                    for key, value in result.items()
                    if key != "error"
                },
            }
            raise APIProblem(
                "tool_error",
                str(result["error"]),
                422,
                details=details,
            )
        return {"result": safe_result}
    except APIProblem:
        if outcome != "tool_error":
            outcome = "api_error"
        raise
    except Exception:
        outcome = "exception"
        raise
    finally:
        LOGGER.info(
            "agent_api_tool request_id=%s user_hash=%s plan=%s tool=%s "
            "outcome=%s call_number=%d result_bytes=%d elapsed_ms=%d",
            g.agent_api_request_id,
            g.agent_api_user.hash,
            report.hash if report is not None else "none",
            tool_name,
            outcome,
            rate_state["count"],
            result_bytes,
            round((time.monotonic() - started) * 1000),
        )


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_submission_is_serialized_with_upload_operations
# @matrix agent-api : submission
# @pairs agent-api:concurrency agent-api:plan-operation
# @pairs mcp-upload:concurrency mcp-upload:plan-operation
@api.post("/plans/<plan_id>/submit")
@_route
def submit_plan(plan_id):
    report = _load_plan(plan_id)
    external_api.require_submission_available(report)
    data = _json_body()
    submitted = external_api.submit_plan_request(
        report, g.agent_api_user, data, request_id=g.agent_api_request_id,
    )
    return _submission_receipt(submitted)
