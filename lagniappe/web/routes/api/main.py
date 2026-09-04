"""REST resources for provider-free external Ask, Create, and Organize plans."""

from contextlib import suppress
from copy import deepcopy
from functools import wraps
import json
import logging
import re
import time
import uuid

from flask import g, jsonify, make_response, request, url_for
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.mutations import (
    consume_mutation_intents,
    execute_post_commit,
    plan_mutation,
    prepare_durable_writes,
)
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai.reporting.uploads import (
    CHECKPOINT_AMBIGUOUS,
    CHECKPOINT_NOT_COMMITTED,
)
from lagniappe.core.tools.ai.references import hash_reference, normalize_hash_references
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.email.notifications.links import absolute_url

from . import api, api_family


LOGGER = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_JSON_BODY_BYTES = external_api.MAX_PROPOSAL_BYTES + 64 * 1024
GENERAL_RATE_LIMIT = (60, 60)
PLAN_START_RATE_LIMIT = (10, 60 * 60)
PLAN_TOOL_RATE_WINDOW = 31 * 24 * 60 * 60
UPLOAD_INPUT_NAME = "agent-api-files"
UPLOAD_BATCH_ID_PATTERN = re.compile(external_api.UPLOAD_BATCH_ID_PATTERN)


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_api_uses_only_a_configured_request_origin
# @matrix agent-api mcp-package : discovery origin-validation proposal-contract setup-command
def _api_origin():
    """Use the request origin only when it is an exact configured MCP origin."""
    request_origin = request.host_url.rstrip("/")
    allowed = tuple(getattr(CONFIG, "MCP_EVALUATION_ORIGINS", ()) or ())
    if request_origin in allowed:
        return request_origin
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
# @matrix agent-api : bearer-only body-limit entitlement-independent error-envelope public-user request-correlation request-recheck session-independent streaming
@api.before_request
def authenticate_request():
    """Authenticate only a bearer token; browser sessions are never a fallback."""
    g.NO_CACHE = True
    g.agent_api_request_id = _request_id()
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
# @reason domain-exception translation is exercised through public API routes
def _route(handler):
    """Translate expected domain failures into stable JSON envelopes."""

    # @testable false
    # @covered-by lagniappe/web/routes/api/main.py::_route
    # @reason generated decorator closure delegates to the route translator
    @wraps(handler)
    def wrapped(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
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
# @covered-by lagniappe/web/routes/api/main.py::finalize_uploads
# @reason persisted batch-record consistency is asserted through the bound finalize route
def _upload_batch_id(report):
    """Return the persisted batch identity, rejecting inconsistent state."""
    manifest = (
        report.agent_manifest
        if isinstance(getattr(report, "agent_manifest", None), dict)
        else {}
    )
    batch_id = manifest.get("upload_batch_id")
    pending = getattr(report, "upload_manifest", None)
    if batch_id is None and not pending:
        return None
    if (
        not isinstance(batch_id, str)
        or not UPLOAD_BATCH_ID_PATTERN.fullmatch(batch_id)
        or (
            pending
            and (
                not isinstance(pending, list)
                or any(
                    not isinstance(record, dict)
                    or record.get("upload_batch_id") != batch_id
                    for record in pending
                )
            )
        )
    ):
        raise APIProblem(
            "invalid_upload_state",
            "The current upload batch state is invalid.",
            409,
        )
    return batch_id


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::create_uploads
# @covered-by lagniappe/web/routes/api/main.py::finalize_uploads
# @reason claim outcomes are exercised through both public upload routes
def _raise_plan_operation_problem(outcome):
    """Map a transactional Plan-operation outcome to a bounded API conflict."""
    if outcome == agent_api_store.PLAN_OPERATION_PENDING:
        raise APIProblem(
            "uploads_pending",
            "Finalize the current upload batch before starting another.",
            409,
        )
    if outcome == agent_api_store.PLAN_OPERATION_BUSY:
        raise APIProblem(
            "plan_operation_in_progress",
            "Another request is already changing this Plan.",
            409,
        )
    if outcome == agent_api_store.PLAN_OPERATION_MISMATCH:
        raise APIProblem(
            "upload_batch_mismatch",
            "This upload batch is no longer current for the Plan.",
            409,
        )
    if outcome == agent_api_store.PLAN_OPERATION_MISSING:
        raise APIProblem("plan_not_found", "Plan not found.", 404)
    raise APIProblem(
        "invalid_upload_state",
        "The current upload batch state is invalid.",
        409,
    )


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::create_uploads
# @covered-by lagniappe/web/routes/api/main.py::finalize_uploads
# @reason expiry provides recovery when best-effort cleanup itself is unavailable
def _release_plan_operation_claim(
    report,
    *,
    phase,
    operation_id,
    claim_token,
):
    """Best-effort release; a crashed cleanup remains bounded by the lease."""
    with suppress(Exception):
        agent_api_store.release_plan_operation(
            report.key,
            phase=phase,
            operation_id=operation_id,
            claim_token=claim_token,
        )


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::create_uploads
# @covered-by lagniappe/web/routes/api/main.py::finalize_uploads
# @covered-by lagniappe/web/routes/api/main.py::submit_plan
# @reason route interleaving tests exercise exact-token transactional checkpoints
def _claimed_plan_save(report, *, phase, operation_id, claim_token):
    """Return a mutation writer fenced by one exact Plan-operation claim."""
    expected_report = deepcopy(dict(report.db))

    # @testable false
    # @covered-by lagniappe/web/routes/api/main.py::_claimed_plan_save
    # @reason the closure delegates each checkpoint to the route-owned claim writer
    def save(*entities):
        nonlocal expected_report
        try:
            plan = plan_mutation(MutationOperation.SAVE, *entities)
            writes = prepare_durable_writes(plan)
        except BaseException as error:
            error.checkpoint_disposition = CHECKPOINT_NOT_COMMITTED
            raise
        try:
            outcome = agent_api_store.commit_plan_operation(
                report.key,
                phase=phase,
                operation_id=operation_id,
                claim_token=claim_token,
                expected_report=expected_report,
                writes=[(effect.entity, effect.property_mask) for effect in writes],
            )
        except BaseException as error:
            error.checkpoint_disposition = CHECKPOINT_AMBIGUOUS
            raise
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            if outcome == agent_api_store.PLAN_OPERATION_LOST:
                problem = APIProblem(
                    "plan_operation_lost",
                    "This request no longer owns the Plan operation.",
                    409,
                )
            elif outcome == agent_api_store.PLAN_OPERATION_STALE:
                problem = APIProblem(
                    "plan_state_conflict",
                    "The Plan changed while this operation was in progress.",
                    409,
                )
            else:
                try:
                    _raise_plan_operation_problem(outcome)
                except APIProblem as error:
                    problem = error
            problem.checkpoint_disposition = CHECKPOINT_NOT_COMMITTED
            raise problem

        expected_report = deepcopy(dict(report.db))
        consume_mutation_intents(plan)
        try:
            execute_post_commit(plan)
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "agent_api": {
                        "request_id": g.agent_api_request_id,
                        "phase": f"{phase}_post_commit",
                    }
                },
            )

    return save


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::get_plan
# @reason plan projection is asserted through the public plan resource
def _plan_payload(report, *, include_proposal=True):
    payload = {
        "id": report.urlsafe_key,
        "status": report.status,
        "tool": report.tool,
        "name": report.name,
        "instructions": report.instructions,
        "files": [_file_payload(file) for file in report.input_files],
        "uploads_pending": bool(report.upload_manifest),
        "upload_batch_id": _upload_batch_id(report),
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
        payload["proposal"] = external_api.public_plan_proposal(report)
    return _json_safe(payload)


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::submit_plan
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
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_api_ignores_provider_entitlement_but_rechecks_public_eligibility
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_resources_hide_other_users_plans
# @matrix agent-api : creator-bound entitlement-independent generic-not-found plan-isolation stale-plan
def _load_plan(plan_id):
    report = Entities.fetch_one(plan_id, request=Fetch.direct())
    actor = g.agent_api_user
    owner_key = getattr(report.properties.user, "key", None) if report else None
    if (
        not isinstance(report, Entities.REPORT)
        or report.origin != "api"
        or owner_key != actor.key
    ):
        raise APIProblem("not_found", "Plan not found.", 404)
    return report


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason draft-state gating is exercised through plan-scoped operations
def _require_draft(report):
    if report.status != "draft":
        raise APIProblem(
            "plan_not_draft",
            "This operation is only available while the plan is a draft.",
            409,
        )


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason availability is exercised through the public plan-scoped tool resource
def _require_tools_available(report):
    if report.status == "draft":
        return
    if report.tool == "ask" and report.status == "complete":
        return
    if report.tool in {"create", "organize"} and report.status == "ready":
        return
    raise APIProblem(
        "plan_tools_unavailable",
        "Read tools are available only for draft plans, completed Ask plans, and "
        "ready Create or Organize plans.",
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
        "openapi_url": _api_absolute_url(
            url_for("agent_api.openapi_document")
        ),
        "actor_url": _api_absolute_url(url_for("agent_api.me")),
        "tools_url": _api_absolute_url(url_for("agent_api.tools")),
        "plans_url": _api_absolute_url(url_for("agent_api.create_plan")),
        "client_skill_url": _api_absolute_url(
            url_for("agent_api.client_skill")
        ),
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
    """Return the machine-readable workflow and contract for external agents."""
    plan_parameter = {
        "name": "plan_id",
        "in": "path",
        "required": True,
        "description": "The opaque plan ID returned by createPlan.",
        "schema": {"type": "string", "minLength": 1},
    }
    upload_batch_id_schema = {
        "type": "string",
        "pattern": external_api.UPLOAD_BATCH_ID_PATTERN,
        "description": (
            "Opaque server-issued identity for exactly one upload batch. "
            "Return it unchanged when finalizing that batch."
        ),
    }
    tool_parameter = {
        "name": "tool_name",
        "in": "path",
        "required": True,
        "description": "A registered read-tool name returned by listTools.",
        "schema": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_]*$",
        },
    }

    # @testable false
    # @covered-by lagniappe/web/routes/api/main.py::openapi_document
    # @reason local response-content shorthand is exercised through the public document
    def json_content(schema):
        return {"content": {"application/json": {"schema": schema}}}

    error_response = {
        "description": "The request failed. Inspect error.code and request_id.",
        **json_content({"$ref": "#/components/schemas/Error"}),
    }
    paths = {
        "/api/v1": {
            "get": {
                "operationId": "discoverApi",
                "summary": "Discover the external-agent API",
                "description": (
                    "Start here when given only the versioned API base URL. Returns "
                    "the authenticated OpenAPI, actor, tool-catalog, and plan URLs."
                ),
                "tags": ["Discovery"],
                "responses": {
                    "200": {
                        "description": "Current version discovery links.",
                        **json_content({"type": "object"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/client-skill.md": {
            "get": {
                "operationId": "downloadClientSkill",
                "summary": "Download the minimal client skill",
                "description": (
                    "Returns a short, copyable SKILL.md that teaches a client to "
                    "start with live discovery, verify the actor, and follow the "
                    "authoritative OpenAPI and plan contracts. It intentionally "
                    "does not duplicate action schemas or permission rules."
                ),
                "tags": ["Discovery"],
                "responses": {
                    "200": {
                        "description": "Canonical minimal client skill.",
                        "content": {
                            "text/markdown": {"schema": {"type": "string"}}
                        },
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/me": {
            "get": {
                "operationId": "getCurrentActor",
                "summary": "Describe the API actor",
                "description": (
                    "Call first to verify the bearer key, its user identity, and "
                    "its external-plan capabilities. These provider-free capabilities "
                    "are independent of the site's model-provider access setting. "
                    "The user object also identifies the actor's editable personal "
                    "Page, which intentionally may not appear in workspace search."
                ),
                "tags": ["Discovery"],
                "responses": {
                    "200": {
                        "description": "Authenticated user and capabilities.",
                        **json_content({"type": "object"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/tools": {
            "get": {
                "operationId": "listTools",
                "summary": "List permission-bounded read tools",
                "description": (
                    "Returns every available tool with its JSON input schema. Tool "
                    "calls run as the bearer-key user and may only inspect data that "
                    "user can access. Inspect the selected tool's exact input_schema "
                    "instead of guessing argument names. Select Ask, Create, or "
                    "Organize when creating a plan; Organize clients should fetch "
                    "get_guidelines task=organize before analyzing files. Use returned "
                    "hash: references only as allowed by the selected plan contract."
                ),
                "tags": ["Discovery"],
                "parameters": [
                    {
                        "name": "names",
                        "in": "query",
                        "required": False,
                        "description": (
                            "Optional comma-separated or repeated exact tool names. "
                            "Use this to retrieve only selected definitions."
                        ),
                        "schema": {"type": "array", "items": {"type": "string"}},
                        "style": "form",
                        "explode": True,
                    },
                    {
                        "name": "view",
                        "in": "query",
                        "required": False,
                        "description": (
                            "Use names for a compact array of exact registered names; "
                            "the default full view includes input and output schemas."
                        ),
                        "schema": {
                            "type": "string",
                            "enum": ["full", "names"],
                            "default": "full",
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Read-tool catalog and reference format.",
                        **json_content(
                            {
                                "type": "object",
                                "required": [
                                    "tools",
                                    "view",
                                    "selected_count",
                                    "reference_format",
                                    "execution_envelope",
                                ],
                                "properties": {
                                    "tools": {
                                        "type": "array",
                                        "items": {
                                            "oneOf": [
                                                {"$ref": "#/components/schemas/ToolDefinition"},
                                                {"type": "string"},
                                            ]
                                        },
                                    },
                                    "view": {"type": "string", "enum": ["full", "names"]},
                                    "selected_count": {"type": "integer"},
                                    "reference_format": {"type": "string"},
                                    "execution_envelope": {"type": "object"},
                                },
                            }
                        ),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans": {
            "post": {
                "operationId": "createPlan",
                "summary": "Create an Ask, Create, or Organize plan draft",
                "description": (
                    "Starts a durable provider-free workspace. Creation does not run "
                    "a model or change workspace data. The client chooses one fixed "
                    "tool for this plan and may create another plan if the conversation "
                    "later changes modes. Keep the returned opaque ID for Plan-scoped "
                    "read tools and uploads when supported. Follow the returned "
                    "contract_url, submit_url, and status_url exactly instead of "
                    "reconstructing those lifecycle paths."
                ),
                "tags": ["Plans"],
                "requestBody": {
                    "required": True,
                    **json_content(
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["instructions"],
                            "properties": {
                                "tool": {
                                    "type": "string",
                                    "enum": list(external_api.SUPPORTED_PLAN_TOOLS),
                                    "default": "organize",
                                },
                                "name": {
                                    "type": "string",
                                    "maxLength": 120,
                                    "description": "Optional browser-review label.",
                                },
                                "instructions": {
                                    "type": "string",
                                    "minLength": 1,
                                    "pattern": "\\S",
                                    "description": (
                                        "The question or requested work, limited to 65,536 "
                                        "UTF-8 bytes."
                                    ),
                                },
                            },
                        }
                    ),
                },
                "responses": {
                    "201": {
                        "description": "New draft plan.",
                        **json_content({"$ref": "#/components/schemas/Plan"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}": {
            "get": {
                "operationId": "getPlan",
                "summary": "Get plan state",
                "description": (
                    "Checks draft/ready state, finalized files, pending uploads, "
                    "contract and browser-review URLs, and any submitted execution-"
                    "normalized proposal. The proposal is projected back into the "
                    "public hash-reference and Markdown submission contract so a "
                    "reusable Plan can be edited and submitted again. The plan ID is "
                    "the top-level id field in every plan response."
                ),
                "tags": ["Plans"],
                "parameters": [plan_parameter],
                "responses": {
                    "200": {
                        "description": "Current plan state.",
                        **json_content({"$ref": "#/components/schemas/Plan"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}/contract": {
            "get": {
                "operationId": "getPlanContract",
                "summary": "Get the final proposal contract",
                "description": (
                    "Fetch immediately before constructing the final response. For "
                    "Organize, fetch after all uploads are finalized. The response is "
                    "tool-, plan-, user-, file-, and permission-specific; its "
                    "proposal_schema, workflow_rules, reference_rules, and "
                    "required_file_refs are authoritative."
                ),
                "tags": ["Plans"],
                "parameters": [plan_parameter],
                "responses": {
                    "200": {
                        "description": "Current proposal and permission contract.",
                        **json_content(
                            {"$ref": "#/components/schemas/PlanContract"}
                        ),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}/uploads": {
            "post": {
                "operationId": "createUploadSessions",
                "summary": "Create resumable file upload sessions",
                "description": (
                    "For an Organize draft, declare one or more local files. Ask and "
                    "Create plans reject uploads. For "
                    "each response entry, PUT exactly the declared bytes and content "
                    "type to session_url, treating that URL as a short-lived secret "
                    "and not forwarding the Lagniappe bearer key. Then call "
                    "finalizeUploads before starting another batch or submitting."
                ),
                "tags": ["Uploads"],
                "parameters": [plan_parameter],
                "requestBody": {
                    "required": True,
                    **json_content(
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["files"],
                            "properties": {
                                "files": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": external_api.MAX_PLAN_FILES,
                                    "items": {
                                        "$ref": "#/components/schemas/UploadFile"
                                    },
                                }
                            },
                        }
                    ),
                },
                "responses": {
                    "201": {
                        "description": "Upload sessions in request-array order.",
                        **json_content(
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "plan_id",
                                    "upload_batch_id",
                                    "uploads",
                                ],
                                "properties": {
                                    "plan_id": {"type": "string"},
                                    "upload_batch_id": upload_batch_id_schema,
                                    "uploads": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "additionalProperties": False,
                                            "required": [
                                                "index",
                                                "filename",
                                                "session_url",
                                                "chunk_size",
                                            ],
                                            "properties": {
                                                "index": {
                                                    "type": "integer",
                                                    "minimum": 0,
                                                },
                                                "filename": {"type": "string"},
                                                "session_url": {
                                                    "type": "string",
                                                    "format": "uri",
                                                },
                                                "chunk_size": {
                                                    "type": "integer",
                                                    "minimum": 1,
                                                },
                                            },
                                        },
                                    },
                                },
                            }
                        ),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}/uploads/finalize": {
            "post": {
                "operationId": "finalizeUploads",
                "summary": "Finalize staged uploads",
                "description": (
                    "After every session upload completes, return the exact "
                    "upload_batch_id issued with those sessions. The server verifies "
                    "that batch is still authoritative before attaching files to the "
                    "draft. Repeating the same finalized identity simply returns state."
                ),
                "tags": ["Uploads"],
                "parameters": [plan_parameter],
                "requestBody": {
                    "required": True,
                    **json_content(
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["upload_batch_id"],
                            "properties": {
                                "upload_batch_id": upload_batch_id_schema,
                            },
                        }
                    ),
                },
                "responses": {
                    "200": {
                        "description": "Plan with finalized file metadata.",
                        **json_content({"$ref": "#/components/schemas/Plan"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}/tools/{tool_name}": {
            "post": {
                "operationId": "executeTool",
                "summary": "Run one permission-bounded read tool",
                "description": (
                    "Runs one listTools definition during interactive planning. "
                    "Completed Ask plans and ready Create or Organize plans may "
                    "continue reading for conversational refinement. Put that "
                    "definition's complete input in the "
                    "top-level arguments object. Other top-level fields are rejected. "
                    "Calls read permitted workspace data only; independent calls may "
                    "be made in parallel. A handler-level failure returns HTTP 422 "
                    "with error.code=tool_error and corrective details rather than a "
                    "success-shaped result."
                ),
                "tags": ["Tools"],
                "parameters": [plan_parameter, tool_parameter],
                "requestBody": {
                    "required": True,
                    **json_content(
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "arguments": {
                                    "type": "object",
                                    "default": {},
                                }
                            },
                        }
                    ),
                },
                "responses": {
                    "200": {
                        "description": "The tool result in the result field.",
                        **json_content({"type": "object"}),
                    },
                    "422": {
                        "description": (
                            "The selected tool rejected its arguments or could not "
                            "produce a result. Inspect error.message and error.details."
                        ),
                        **json_content({"$ref": "#/components/schemas/Error"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}/submit": {
            "post": {
                "operationId": "submitPlan",
                "summary": "Validate and publish the final proposal",
                "description": (
                    "Requires the current tool-specific contract and no pending "
                    "uploads; Organize also requires at least one finalized file. A "
                    "valid Ask response becomes a completed read-only report and "
                    "should be submitted without separate save confirmation. A valid "
                    "Create or Organize proposal becomes ready for review and returns "
                    "preview_url. Submission itself never executes actions. Repeating "
                    "the identical normalized result is accepted. While the report "
                    "remains reusable, a later valid Ask answer or Create/Organize "
                    "proposal replaces the saved result: revise the complete result, "
                    "then submit it again. Present each Create or Organize preview_url "
                    "and direct the user to the authenticated website to review and "
                    "approve it. This API has no operation that applies proposals to "
                    "the workspace."
                ),
                "tags": ["Plans"],
                "parameters": [plan_parameter],
                "requestBody": {
                    "required": True,
                    **json_content(
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["contract_version", "proposal"],
                            "properties": {
                                "contract_version": {
                                    "type": "integer",
                                    "const": external_api.CONTRACT_VERSION,
                                },
                                "proposal": {
                                    "type": "object",
                                    "description": (
                                        "Must match the current plan contract's "
                                        "proposal_schema."
                                    ),
                                },
                            },
                        }
                    ),
                },
                "responses": {
                    "200": {
                        "description": (
                            "Compact publication receipt. Present preview_url to the user "
                            "for browser review; retain review_url as the canonical full "
                            "URL. Fetch status_url for detailed plan state. Create and "
                            "Organize can only be applied with the existing Execute "
                            "control on that authenticated browser page."
                        ),
                        **json_content(
                            {"$ref": "#/components/schemas/SubmissionReceipt"}
                        ),
                    },
                    "422": {
                        "description": (
                            "Invalid submission. Independent wrapper and schema "
                            "failures are returned together in "
                            "error.details.errors; later semantic failures retain "
                            "the concise Error envelope."
                        ),
                        **json_content({"$ref": "#/components/schemas/Error"}),
                    },
                    "default": error_response,
                },
            }
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"{CONFIG.APP_NAME} External Agent API",
            "version": "1.0.0",
            "description": (
                "Use this API as a permission-bounded Ask, Create, and Organize backend "
                "for an external model. The client selects the appropriate tool per "
                "plan and may create a different plan as the conversation changes. "
                "Verify the actor, create a draft, use permitted read tools, fetch the "
                "tool-specific plan contract, and submit a conforming final result. "
                "Organize additionally uploads files and follows the get_guidelines "
                "task=organize two-phase workflow, including one summary and two "
                "retrieval terms per file. Ask publishes a read-only answer. Create "
                "and Organize publish proposals for authenticated browser review. "
                "The external API never applies those proposals; direct the user to "
                "preview_url, where the existing website Execute control is the only "
                "approval and application path. The server does not call a model to "
                "choose the tool, complete, repair, or summarize the result. When an "
                "Ask answer is ready, submit it without separate save confirmation, "
                "then answer the user with the returned preview_url; Ask submission "
                "is read-only and later valid answers may replace it. Ready Create and "
                "Organize proposals may likewise be revised and submitted again until "
                "browser execution starts."
            ),
        },
        "servers": [{"url": _api_absolute_url("/").rstrip("/")}],
        "security": [{"bearerAuth": []}],
        "tags": [
            {"name": "Discovery", "description": "Actor and tool discovery."},
            {"name": "Plans", "description": "Draft and review lifecycle."},
            {"name": "Uploads", "description": "Organize-only plan-file staging."},
            {"name": "Tools", "description": "Permission-bounded reads."},
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "A shown-once user API key generated in Settings.",
                }
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["error", "request_id"],
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {
                                    "type": "object",
                                    "properties": {
                                        "errors": {
                                            "type": "array",
                                            "maxItems": external_api.MAX_VALIDATION_ERRORS,
                                            "items": {
                                                "$ref": "#/components/schemas/ValidationErrorDetail"
                                            },
                                        }
                                    },
                                    "additionalProperties": True,
                                },
                            },
                        },
                        "request_id": {"type": "string"},
                    },
                },
                "ValidationErrorDetail": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "path", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "path": {"type": "string"},
                        "message": {"type": "string"},
                        "expected": {},
                    },
                },
                "PlanFile": {
                    "type": "object",
                    "required": ["ref", "name", "filename", "mimetype", "size"],
                    "properties": {
                        "ref": {
                            "type": "string",
                            "pattern": "^hash:[A-Za-z0-9_-]{12}$",
                        },
                        "name": {"type": "string"},
                        "filename": {"type": "string"},
                        "mimetype": {"type": "string"},
                        "size": {"type": "integer", "minimum": 0},
                    },
                },
                "Plan": {
                    "type": "object",
                    "required": [
                        "id",
                        "status",
                        "tool",
                        "name",
                        "instructions",
                        "files",
                        "uploads_pending",
                        "upload_batch_id",
                        "contract_version",
                        "contract_url",
                        "submit_url",
                        "status_url",
                        "preview_url",
                        "review_url",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": [
                                "draft",
                                "ready",
                                "running",
                                "complete",
                                "failed",
                                "undoing",
                                "undo_failed",
                            ],
                        },
                        "tool": {
                            "type": "string",
                            "enum": list(external_api.SUPPORTED_PLAN_TOOLS),
                        },
                        "name": {"type": "string"},
                        "instructions": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/PlanFile"},
                        },
                        "uploads_pending": {"type": "boolean"},
                        "upload_batch_id": {
                            "oneOf": [
                                upload_batch_id_schema,
                                {"type": "null"},
                            ],
                            "description": (
                                "The current or most recently finalized upload batch "
                                "identity, retained so an uncertain finalize response "
                                "can be resolved without replaying the write."
                            ),
                        },
                        "contract_version": {
                            "type": "integer",
                            "const": external_api.CONTRACT_VERSION,
                        },
                        "contract_url": {"type": "string", "format": "uri"},
                        "submit_url": {"type": "string", "format": "uri"},
                        "status_url": {"type": "string", "format": "uri"},
                        "preview_url": {
                            "type": "string",
                            "format": "uri",
                            "description": (
                                "Preferred human-facing browser-session URL for the "
                                "plan creator; it redirects to the full review report."
                            ),
                        },
                        "review_url": {
                            "type": "string",
                            "format": "uri",
                            "description": "Canonical full browser report URL.",
                        },
                        "proposal": {
                            "oneOf": [{"type": "object"}, {"type": "null"}],
                            "description": (
                                "The public submission representation: existing "
                                "entities use hash: references and generated rich "
                                "text uses Markdown. A reusable plan's proposal may "
                                "be edited and submitted again."
                            ),
                        },
                    },
                },
                "PlanSubmissionFormat": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "method",
                        "url",
                        "contract_version",
                        "body",
                        "rule",
                    ],
                    "properties": {
                        "method": {"type": "string", "const": "POST"},
                        "url": {"type": "string", "format": "uri"},
                        "contract_version": {
                            "type": "integer",
                            "const": external_api.CONTRACT_VERSION,
                        },
                        "body": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["contract_version", "proposal"],
                            "properties": {
                                "contract_version": {
                                    "type": "integer",
                                    "const": external_api.CONTRACT_VERSION,
                                },
                                "proposal": {"type": "object"},
                            },
                        },
                        "rule": {"type": "string"},
                    },
                },
                "PlanContract": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "contract_version",
                        "tool",
                        "current_date",
                        "timezone",
                        "personal_page",
                        "submission_format",
                        "proposal_schema",
                        "permissions",
                        "required_file_refs",
                        "upload_inventory",
                        "file_checklist",
                        "guidance_requirements",
                        "uploads_supported",
                        "workflow_rules",
                        "reference_rules",
                        "limits",
                        "payload_sizes",
                    ],
                    "properties": {
                        "contract_version": {
                            "type": "integer",
                            "const": external_api.CONTRACT_VERSION,
                        },
                        "tool": {
                            "type": "string",
                            "enum": list(external_api.SUPPORTED_PLAN_TOOLS),
                        },
                        "current_date": {"type": "string", "format": "date"},
                        "timezone": {"type": "string"},
                        "personal_page": {"type": "object"},
                        "submission_format": {
                            "$ref": "#/components/schemas/PlanSubmissionFormat"
                        },
                        "proposal_schema": {"type": "object"},
                        "permissions": {"type": "object"},
                        "required_file_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "upload_inventory": {
                            "oneOf": [{"type": "object"}, {"type": "null"}]
                        },
                        "file_checklist": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "guidance_requirements": {"type": "object"},
                        "uploads_supported": {"type": "boolean"},
                        "workflow_rules": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "reference_rules": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "limits": {"type": "object"},
                        "payload_sizes": {"type": "object"},
                    },
                },
                "SubmissionReceipt": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "status",
                        "preview_url",
                        "review_url",
                        "status_url",
                        "contract_version",
                        "proposal_fingerprint",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["ready", "complete"],
                        },
                        "preview_url": {"type": "string", "format": "uri"},
                        "review_url": {"type": "string", "format": "uri"},
                        "status_url": {"type": "string", "format": "uri"},
                        "contract_version": {
                            "type": "integer",
                            "const": external_api.CONTRACT_VERSION,
                        },
                        "proposal_fingerprint": {
                            "oneOf": [
                                {"type": "string", "minLength": 1},
                                {"type": "null"},
                            ],
                            "description": (
                                "Digest of the validated normalized proposal. It may "
                                "differ from a digest of the raw request body."
                            ),
                        },
                    },
                },
                "UploadFile": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["filename", "size"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "minLength": 1,
                            "pattern": "\\S",
                        },
                        "content_type": {
                            "type": "string",
                            "minLength": 1,
                            "pattern": "\\S",
                            "default": "application/octet-stream",
                        },
                        "size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": external_api.MAX_FILE_BYTES,
                            "description": "Exact file size in bytes.",
                        },
                    },
                },
                "ToolDefinition": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name",
                        "description",
                        "input_schema",
                        "output_schema",
                        "result_paths",
                    ],
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "input_schema": {"type": "object"},
                        "output_schema": {
                            "type": "object",
                            "description": (
                                "Schema for a successful direct shared-tool value. "
                                "REST places it beneath the success result field."
                            ),
                        },
                        "result_paths": {
                            "type": "object",
                            "description": (
                                "JSON paths for the primary entity or collection "
                                "and any pagination metadata within result."
                            ),
                        },
                    },
                },
            },
        },
        "paths": paths,
    }


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
            "ask": True,
            "create": True,
            "organize": True,
        },
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
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_types_are_available_without_provider_access
# @matrix agent-api : entitlement-independent plan-session tool-selection
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
    unsupported_fields = sorted(set(data) - {"instructions", "name", "tool"})
    if unsupported_fields:
        raise APIProblem(
            "unsupported_field",
            "Plan request contains unsupported fields.",
            422,
            details={
                "path": "$",
                "fields": unsupported_fields,
                "allowed_fields": ["instructions", "name", "tool"],
            },
        )
    tool = data.get("tool", "organize")
    if not isinstance(tool, str) or tool not in external_api.SUPPORTED_PLAN_TOOLS:
        raise APIProblem(
            "unsupported_tool",
            "Plan tool must be ask, create, or organize.",
            422,
            details={"path": "$.tool"},
        )
    instructions = data.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise APIProblem(
            "invalid_instructions",
            '"instructions" must be a non-empty string.',
            422,
            details={
                "path": "$.instructions",
                "expected": "non-empty string",
            },
        )
    name = data.get("name")
    if "name" in data and (
        not isinstance(name, str) or len(name) > 120
    ):
        raise APIProblem(
            "invalid_name",
            '"name" must be a string of at most 120 characters.',
            422,
            details={
                "path": "$.name",
                "expected": "string with at most 120 characters",
            },
        )
    report = external_api.create_plan(
        actor,
        instructions=instructions,
        tool=tool,
        name=name,
    )
    return _plan_payload(report), 201


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : plan-session
@api.get("/plans/<plan_id>")
@_route
def get_plan(plan_id):
    return _plan_payload(_load_plan(plan_id))


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : proposal-contract
@api.get("/plans/<plan_id>/contract")
@_route
def get_plan_contract(plan_id):
    report = _load_plan(plan_id)
    contract = external_api.plan_contract(
        report,
        g.agent_api_user,
        submit_url=_api_absolute_url(
            url_for(
                "agent_api.submit_plan",
                plan_id=report.urlsafe_key,
            )
        ),
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


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::create_uploads
# @reason aggregate limits are exercised through the public upload resource
def _upload_sizes(report, requested):
    existing_sizes = [int(file.size or 0) for file in report.input_files]
    requested_sizes = [int(item["size"]) for item in requested]
    if len(existing_sizes) + len(requested_sizes) > external_api.MAX_PLAN_FILES:
        raise APIProblem(
            "too_many_files",
            f"A plan can contain at most {external_api.MAX_PLAN_FILES} files.",
            422,
        )
    if sum(existing_sizes) + sum(requested_sizes) > external_api.MAX_TOTAL_FILE_BYTES:
        raise APIProblem(
            "files_too_large",
            "The plan's files exceed the total upload limit.",
            422,
        )


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
    _require_draft(report)
    if report.tool != "organize":
        raise APIProblem(
            "uploads_not_supported",
            "File uploads are supported only for Organize plans.",
            409,
        )
    if report.upload_manifest:
        raise APIProblem(
            "uploads_pending",
            "Finalize the current upload batch before starting another.",
            409,
        )
    data = _json_body()
    unsupported_fields = sorted(set(data) - {"files"})
    if unsupported_fields:
        raise APIProblem(
            "unsupported_field",
            "Upload-session request contains unsupported fields.",
            422,
            details={
                "path": "$",
                "fields": unsupported_fields,
                "allowed_fields": ["files"],
            },
        )
    requested = data.get("files")
    if not isinstance(requested, list) or not requested:
        raise APIProblem("invalid_files", "files must be a non-empty list.", 422)

    normalized = []
    for index, item in enumerate(requested):
        if not isinstance(item, dict):
            raise APIProblem("invalid_files", "Each file must be an object.", 422)
        unsupported_fields = sorted(
            set(item) - {"filename", "content_type", "size"}
        )
        if unsupported_fields:
            details = {
                "path": f"$.files[{index}]",
                "fields": unsupported_fields,
                "allowed_fields": ["content_type", "filename", "size"],
            }
            if "size_bytes" in unsupported_fields:
                details["use_field"] = "size"
            raise APIProblem(
                "unsupported_field",
                "Upload file entry contains unsupported fields.",
                422,
                details=details,
            )
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise APIProblem(
                "invalid_file",
                'Each file\'s "filename" must be a non-empty string.',
                422,
                details={
                    "path": f"$.files[{index}].filename",
                    "expected": "non-empty string",
                },
            )
        filename = filename.strip()
        content_type = item.get("content_type", "application/octet-stream")
        if not isinstance(content_type, str) or not content_type.strip():
            raise APIProblem(
                "invalid_content_type",
                'Each file\'s "content_type" must be a non-empty string.',
                422,
                details={
                    "path": f"$.files[{index}].content_type",
                    "expected": "non-empty string",
                },
            )
        content_type = content_type.strip()
        size_details = {
            "path": f"$.files[{index}].size",
            "expected": "positive integer byte size",
        }
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise APIProblem(
                "invalid_file_size",
                'Each file\'s "size" must be a positive integer byte size.',
                422,
                details=size_details,
            )
        if size <= 0:
            raise APIProblem(
                "invalid_file_size",
                'Each file\'s "size" must be a positive integer byte size.',
                422,
                details=size_details,
            )
        if size > external_api.MAX_FILE_BYTES:
            raise APIProblem(
                "file_too_large",
                f"{filename} exceeds the per-file upload limit.",
                422,
            )
        normalized.append(
            {
                "filename": filename,
                "content_type": content_type,
                "size": size,
            }
        )
    _upload_sizes(report, normalized)

    upload_batch_id = uuid.uuid4().hex
    claim_token = uuid.uuid4().hex
    claim_outcome = agent_api_store.claim_plan_operation(
        report.key,
        phase="create",
        operation_id=upload_batch_id,
        claim_token=claim_token,
    )
    if claim_outcome != agent_api_store.PLAN_OPERATION_CLAIMED:
        _raise_plan_operation_problem(claim_outcome)

    try:
        # The pre-claim entity may predate a completed upload operation. Always
        # resume from the authoritative state protected by this claim.
        report = _load_plan(plan_id)
        _require_draft(report)
        if report.tool != "organize":
            raise APIProblem(
                "uploads_not_supported",
                "File uploads are supported only for Organize plans.",
                409,
            )
        if report.upload_manifest:
            raise APIProblem(
                "uploads_pending",
                "Finalize the current upload batch before starting another.",
                409,
            )
        _upload_sizes(report, normalized)
        save = _claimed_plan_save(
            report,
            phase="create",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )
        sessions = []
        records = []
        for index, item in enumerate(normalized):
            if not agent_api_store.renew_plan_operation(
                report.key,
                phase="create",
                operation_id=upload_batch_id,
                claim_token=claim_token,
            ):
                raise APIProblem(
                    "plan_operation_lost",
                    "This request no longer owns the Plan's upload batch.",
                    409,
                )
            session = storage_assets.create_direct_upload_session(
                item["filename"],
                content_type=item["content_type"],
                size=item["size"],
                input_name=UPLOAD_INPUT_NAME,
                origin=None,
            )
            records.append(
                {
                    "token": session["token"],
                    "input_name": UPLOAD_INPUT_NAME,
                    **item,
                }
            )
            sessions.append(
                {
                    "index": index,
                    "filename": item["filename"],
                    "session_url": session["session_url"],
                    "chunk_size": session["chunk_size"],
                }
            )
        prepared = external_api.prepare_upload_manifest(
            records,
            upload_batch_id=upload_batch_id,
        )
        report.upload_manifest = external_api.bind_upload_file_identities(
            report,
            prepared,
            upload_batch_id=upload_batch_id,
        )
        agent_manifest = (
            dict(report.agent_manifest)
            if isinstance(getattr(report, "agent_manifest", None), dict)
            else {}
        )
        agent_manifest["upload_batch_id"] = upload_batch_id
        report.agent_manifest = agent_manifest
        save(report)
        return {
            "plan_id": report.urlsafe_key,
            "upload_batch_id": upload_batch_id,
            "uploads": sessions,
        }, 201
    finally:
        _release_plan_operation_claim(
            report,
            phase="create",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )


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
    _require_draft(report)
    if report.tool != "organize":
        raise APIProblem(
            "uploads_not_supported",
            "File uploads are supported only for Organize plans.",
            409,
        )
    data = _json_body()
    unsupported_fields = sorted(set(data) - {"upload_batch_id"})
    if unsupported_fields:
        raise APIProblem(
            "unsupported_field",
            "Upload finalization request contains unsupported fields.",
            422,
            details={
                "path": "$",
                "fields": unsupported_fields,
                "allowed_fields": ["upload_batch_id"],
            },
        )
    upload_batch_id = data.get("upload_batch_id")
    if (
        not isinstance(upload_batch_id, str)
        or not UPLOAD_BATCH_ID_PATTERN.fullmatch(upload_batch_id)
    ):
        raise APIProblem(
            "invalid_upload_batch_id",
            "upload_batch_id must be the opaque identity returned at creation.",
            422,
            details={
                "path": "$.upload_batch_id",
                "expected": "server-issued upload batch identity",
            },
        )
    current_batch_id = _upload_batch_id(report)
    if current_batch_id != upload_batch_id:
        raise APIProblem(
            "upload_batch_mismatch",
            "This upload batch is no longer current for the Plan.",
            409,
        )
    if not report.upload_manifest:
        return _plan_payload(report)

    claim_token = uuid.uuid4().hex
    claim_outcome = agent_api_store.claim_plan_operation(
        report.key,
        phase="finalize",
        operation_id=upload_batch_id,
        claim_token=claim_token,
    )
    if claim_outcome == agent_api_store.PLAN_OPERATION_COMPLETE:
        current = _load_plan(plan_id)
        return _plan_payload(current)
    if claim_outcome != agent_api_store.PLAN_OPERATION_CLAIMED:
        _raise_plan_operation_problem(claim_outcome)

    try:
        # A prior worker may have checkpointed one or more records between this
        # request's first fetch and claim acquisition. Never finalize its stale
        # in-memory manifest.
        report = _load_plan(plan_id)
        _require_draft(report)
        if report.tool != "organize":
            raise APIProblem(
                "uploads_not_supported",
                "File uploads are supported only for Organize plans.",
                409,
            )
        if _upload_batch_id(report) != upload_batch_id:
            raise APIProblem(
                "upload_batch_mismatch",
                "This upload batch is no longer current for the Plan.",
                409,
            )
        if not report.upload_manifest:
            return _plan_payload(report)

        # @testable false
        # @covered-by lagniappe/web/routes/api/main.py::finalize_uploads
        # @reason the route-owned callback only maps lease renewal loss to its API conflict
        def ensure_active():
            if not agent_api_store.renew_plan_operation(
                report.key,
                phase="finalize",
                operation_id=upload_batch_id,
                claim_token=claim_token,
            ):
                raise APIProblem(
                    "plan_operation_lost",
                    "This request no longer owns the Plan's upload batch.",
                    409,
                )

        save = _claimed_plan_save(
            report,
            phase="finalize",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )
        external_api.finalize_uploads(
            report,
            g.agent_api_user,
            asset_nonce=claim_token,
            ensure_active=ensure_active,
            save=save,
        )
        report = _load_plan(plan_id)
    finally:
        _release_plan_operation_claim(
            report,
            phase="finalize",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )
    return _plan_payload(report)


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason signed original-file projection belongs to permission-bounded tool dispatch
def _original_file_download(tool_name, arguments, result):
    if tool_name != "get_file" or not isinstance(arguments, dict):
        return result
    include_original = arguments.get("include_original")
    include_original = (
        include_original is True
        or str(include_original).strip().casefold() in {"1", "true", "yes", "on"}
    )
    original_file = result.get("original_file") if isinstance(result, dict) else None
    if (
        not include_original
        and isinstance(original_file, dict)
        and original_file.get("supported") is not False
    ):
        return result

    normalized = normalize_hash_references(arguments)
    entity = Entities.fetch_one(normalized.get("id"), request=Fetch.direct())
    if (
        not isinstance(entity, Entities.FILE)
        or not entity.allowed(Action.VIEW, user=g.agent_api_user)
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
# @pairs agent-api:ask-refinement agent-api:create-revision agent-api:organize-revision agent-api:envelope-validation
@api.post("/plans/<plan_id>/tools/<tool_name>")
@_route
def execute_tool(plan_id, tool_name):
    report = _load_plan(plan_id)
    _require_tools_available(report)
    if tool_name not in ai_functions.TOOL_DEFINITIONS:
        raise APIProblem("tool_not_found", "Tool not found.", 404)
    rate_state = _rate_limit(
        "agent-api-plan-tools",
        report.urlsafe_key,
        external_api.MAX_PLAN_TOOL_CALLS,
        PLAN_TOOL_RATE_WINDOW,
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
            report.hash,
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
    reusable_status = "complete" if report.tool == "ask" else "ready"
    if report.status not in {"draft", reusable_status}:
        raise APIProblem(
            "plan_state_conflict",
            "This plan cannot accept a proposal in its current state.",
            409,
        )
    data = _json_body()
    operation_id = uuid.uuid4().hex
    claim_token = uuid.uuid4().hex
    claim_outcome = agent_api_store.claim_plan_operation(
        report.key,
        phase="submit",
        operation_id=operation_id,
        claim_token=claim_token,
    )
    if claim_outcome != agent_api_store.PLAN_OPERATION_CLAIMED:
        if claim_outcome == agent_api_store.PLAN_OPERATION_INVALID:
            raise APIProblem(
                "plan_state_conflict",
                "This plan cannot accept a proposal in its current state.",
                409,
            )
        _raise_plan_operation_problem(claim_outcome)

    try:
        # Submission shares the per-report operation claim so it cannot
        # overwrite a newly staged manifest or be overwritten by a stale
        # upload creator.
        report = _load_plan(plan_id)
        reusable_status = "complete" if report.tool == "ask" else "ready"
        if report.status not in {"draft", reusable_status}:
            raise APIProblem(
                "plan_state_conflict",
                "This plan cannot accept a proposal in its current state.",
                409,
            )
        validation_errors = external_api.submission_validation_errors(
            data,
            report,
            g.agent_api_user,
        )
        if validation_errors:
            raise APIProblem(
                "validation_failed",
                "Submission failed validation.",
                422,
                details={"errors": validation_errors},
            )
        save = _claimed_plan_save(
            report,
            phase="submit",
            operation_id=operation_id,
            claim_token=claim_token,
        )
        try:
            submitted = external_api.submit_plan(
                report,
                g.agent_api_user,
                data.get("proposal"),
                contract_version=data.get("contract_version"),
                save=save,
            )
        except exceptions.ValidationError as error:
            if report.status == reusable_status:
                raise APIProblem("plan_state_conflict", str(error), 409) from error
            raise
    finally:
        _release_plan_operation_claim(
            report,
            phase="submit",
            operation_id=operation_id,
            claim_token=claim_token,
        )
    return _submission_receipt(submitted)
