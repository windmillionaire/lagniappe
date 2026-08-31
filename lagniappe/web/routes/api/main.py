"""REST resources for provider-free external organize plans."""

from functools import wraps
import json
import logging
import re
import time
import uuid

from flask import g, jsonify, make_response, request, url_for
from werkzeug.exceptions import HTTPException

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import AI, Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai.references import hash_reference, normalize_hash_references
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.core.tools.database import assets as storage_assets

from . import api


LOGGER = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_JSON_BODY_BYTES = external_api.MAX_PROPOSAL_BYTES + 64 * 1024
GENERAL_RATE_LIMIT = (60, 60)
PLAN_START_RATE_LIMIT = (10, 60 * 60)
PLAN_TOOL_RATE_WINDOW = 31 * 24 * 60 * 60
UPLOAD_INPUT_NAME = "agent-api-files"


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::authenticate_request
# @reason fail-closed feature normalization is exercised at the API boundary
def _feature_enabled():
    value = getattr(CONFIG, "EXTERNAL_AGENT_API_ENABLED", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


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
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : bearer-only error-envelope
@api.before_request
def authenticate_request():
    """Authenticate only a bearer token; browser sessions are never a fallback."""
    g.NO_CACHE = True
    g.agent_api_request_id = _request_id()
    if not _feature_enabled():
        return _error("not_found", "API resource not found.", 404)
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

    if getattr(actor, "is_public", False) or not actor.access(AI.CREATE):
        return _error(
            "forbidden",
            "This user cannot create external plans.",
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


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : error-envelope
@api.after_request
def annotate_response(response):
    response.headers["X-Request-ID"] = getattr(
        g,
        "agent_api_request_id",
        "",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# @testable true
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
    data = request.get_json(silent=True)
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
        "tool": report.tool,
        "name": report.name,
        "instructions": report.instructions,
        "files": [_file_payload(file) for file in report.input_files],
        "uploads_pending": bool(report.upload_manifest),
        "contract_version": external_api.CONTRACT_VERSION,
        "contract_url": url_for(
            "agent_api.get_plan_contract",
            plan_id=report.urlsafe_key,
            _external=True,
        ),
        "review_url": url_for(
            "tools.report",
            key=report.urlsafe_key,
            _external=True,
        ),
    }
    if include_proposal:
        payload["proposal"] = report.proposal
    return _json_safe(payload)


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::get_plan
# @reason creator-bound lookup is owned by the public plan resource
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
        "/api/v1/me": {
            "get": {
                "operationId": "getCurrentActor",
                "summary": "Describe the API actor",
                "description": (
                    "Call first to verify the bearer key, its user identity, and "
                    "the organize-only, no-execution capability boundary."
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
                    "user can access. Use returned hash: references in later calls "
                    "and in the proposal."
                ),
                "tags": ["Discovery"],
                "responses": {
                    "200": {
                        "description": "Read-tool catalog and reference format.",
                        **json_content({"type": "object"}),
                    },
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans": {
            "post": {
                "operationId": "createPlan",
                "summary": "Create an Organize plan draft",
                "description": (
                    "Starts a durable provider-free workspace. Creation does not run "
                    "a model or change workspace data. Keep the returned opaque ID "
                    "for every upload, tool, contract, and submission call."
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
                                    "const": "organize",
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
                                    "description": (
                                        "The organization goal, limited to 65,536 "
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
                    "contract and browser-review URLs, and any submitted proposal."
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
                    "Fetch after all uploads are finalized and immediately before "
                    "constructing the proposal. The response is plan-, user-, file-, "
                    "and permission-specific; its proposal_schema, workflow_rules, "
                    "reference_rules, and required_file_refs are authoritative."
                ),
                "tags": ["Plans"],
                "parameters": [plan_parameter],
                "responses": {
                    "200": {
                        "description": "Current proposal and permission contract.",
                        **json_content({"type": "object"}),
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
                    "Declare one or more local files while the plan is a draft. For "
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
                        **json_content({"type": "object"}),
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
                    "After every session upload completes, send an empty JSON object. "
                    "The server verifies the staged objects and attaches files to the "
                    "draft. Calling again with no pending batch simply returns state."
                ),
                "tags": ["Uploads"],
                "parameters": [plan_parameter],
                "requestBody": {
                    "required": False,
                    **json_content(
                        {
                            "type": "object",
                            "maxProperties": 0,
                            "additionalProperties": False,
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
                    "Runs one listTools definition while the plan remains a draft. "
                    "Put that definition's input in arguments. Calls read permitted "
                    "workspace data only; independent calls may be made in parallel."
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
                    "default": error_response,
                },
            }
        },
        "/api/v1/plans/{plan_id}/submit": {
            "post": {
                "operationId": "submitPlan",
                "summary": "Validate and publish the final proposal",
                "description": (
                    "Requires at least one finalized file, no pending uploads, and "
                    "the current contract version. A valid proposal becomes a ready "
                    "report for human browser review; it never executes actions. "
                    "Repeating the identical normalized proposal is idempotent, while "
                    "a different proposal after readiness returns a conflict."
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
                        "description": "Ready plan and browser review URL.",
                        **json_content({"$ref": "#/components/schemas/Plan"}),
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
                "Use this API as a permission-bounded Organize backend for an "
                "external model. Workflow: (1) verify the actor with getCurrentActor; "
                "(2) create a draft; (3) upload and finalize at least one file; "
                "(4) discover and call read tools as needed while the plan is a "
                "draft; (5) fetch the plan-specific contract after uploads and "
                "construct a conforming proposal; (6) submit it and stop for human "
                "browser review. This API does not execute proposed actions."
            ),
        },
        "servers": [{"url": request.url_root.rstrip("/")}],
        "security": [{"bearerAuth": []}],
        "tags": [
            {"name": "Discovery", "description": "Actor and tool discovery."},
            {"name": "Plans", "description": "Draft and review lifecycle."},
            {"name": "Uploads", "description": "Required plan-file staging."},
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
                                "details": {},
                            },
                        },
                        "request_id": {"type": "string"},
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
                        "contract_version",
                        "contract_url",
                        "review_url",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "status": {"type": "string", "enum": ["draft", "ready"]},
                        "tool": {"type": "string", "const": "organize"},
                        "name": {"type": "string"},
                        "instructions": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/PlanFile"},
                        },
                        "uploads_pending": {"type": "boolean"},
                        "contract_version": {
                            "type": "integer",
                            "const": external_api.CONTRACT_VERSION,
                        },
                        "contract_url": {"type": "string", "format": "uri"},
                        "review_url": {"type": "string", "format": "uri"},
                        "proposal": {"oneOf": [{"type": "object"}, {"type": "null"}]},
                    },
                },
                "UploadFile": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["filename", "size"],
                    "properties": {
                        "filename": {"type": "string", "minLength": 1},
                        "content_type": {
                            "type": "string",
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
            },
        },
        "paths": paths,
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : bearer-only
@api.get("/me")
@_route
def me():
    actor = g.agent_api_user
    return {
        "user": {
            "name": actor.name,
            "hash": actor.hash,
            "ai_access": actor.ai_access,
        },
        "credential": g.agent_api_credential,
        "capabilities": {"organize": True, "execute": False},
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : tool-catalog
@api.get("/tools")
@_route
def tools():
    return {
        "tools": ai_functions.tool_catalog(transport="rest"),
        "reference_format": "hash:<12-character-hash>",
    }


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : plan-session
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
    tool = str(data.get("tool") or "organize").strip().casefold()
    if tool != "organize":
        raise APIProblem(
            "unsupported_tool",
            "Only organize plans are supported by this API version.",
            422,
        )
    report = external_api.create_plan(
        actor,
        instructions=data.get("instructions"),
        name=data.get("name"),
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
    return external_api.plan_contract(report, g.agent_api_user)


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
# @matrix agent-api : uploads
@api.post("/plans/<plan_id>/uploads")
@_route
def create_uploads(plan_id):
    report = _load_plan(plan_id)
    _require_draft(report)
    if report.upload_manifest:
        raise APIProblem(
            "uploads_pending",
            "Finalize the current upload batch before starting another.",
            409,
        )
    data = _json_body()
    requested = data.get("files")
    if not isinstance(requested, list) or not requested:
        raise APIProblem("invalid_files", "files must be a non-empty list.", 422)

    normalized = []
    for item in requested:
        if not isinstance(item, dict):
            raise APIProblem("invalid_files", "Each file must be an object.", 422)
        filename = str(item.get("filename") or "").strip()
        content_type = str(
            item.get("content_type") or "application/octet-stream"
        ).strip()
        try:
            size = int(item.get("size"))
        except (TypeError, ValueError) as error:
            raise APIProblem(
                "invalid_file_size",
                "Each file must declare its byte size.",
                422,
            ) from error
        if not filename or size <= 0:
            raise APIProblem(
                "invalid_file",
                "Each file needs a filename and a positive byte size.",
                422,
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

    sessions = []
    records = []
    for index, item in enumerate(normalized):
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
    report.upload_manifest = external_api.prepare_upload_manifest(records)
    Entities.save(report)
    return {"plan_id": report.urlsafe_key, "uploads": sessions}, 201


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : uploads
@api.post("/plans/<plan_id>/uploads/finalize")
@_route
def finalize_uploads(plan_id):
    report = _load_plan(plan_id)
    _require_draft(report)
    if report.upload_manifest:
        external_api.finalize_uploads(report, g.agent_api_user)
    return _plan_payload(report)


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason signed original-file projection belongs to permission-bounded tool dispatch
def _original_file_download(tool_name, arguments, result):
    if tool_name != "get_file" or not isinstance(arguments, dict):
        return result
    include_original = arguments.get("include_original")
    if not (
        include_original is True
        or str(include_original).strip().casefold() in {"1", "true", "yes", "on"}
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

    download_url = storage_assets.get_signed_url(asset.path, expires_in=300)
    if not isinstance(result, dict):
        result = {"result": result}
    result = dict(result)
    result["original_file"] = {
        "supported": True,
        "attached": False,
        "download_url": download_url,
        "expires_in": 300,
    }
    return result


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : tool-dispatch
@api.post("/plans/<plan_id>/tools/<tool_name>")
@_route
def execute_tool(plan_id, tool_name):
    report = _load_plan(plan_id)
    _require_draft(report)
    if tool_name not in ai_functions.TOOL_DEFINITIONS:
        raise APIProblem("tool_not_found", "Tool not found.", 404)
    _rate_limit(
        "agent-api-plan-tools",
        report.urlsafe_key,
        external_api.MAX_PLAN_TOOL_CALLS,
        PLAN_TOOL_RATE_WINDOW,
    )
    data = _json_body()
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise APIProblem(
            "invalid_arguments",
            "arguments must be a JSON object.",
            422,
        )

    started = time.monotonic()
    outcome = "success"
    try:
        result, _file_parts = ai_functions.execute_registered_tool(
            tool_name,
            arguments,
            g.agent_api_user,
        )
        result = _original_file_download(tool_name, arguments, result)
        if isinstance(result, dict) and result.get("error"):
            outcome = "tool_error"
        return {"result": _json_safe(result)}
    except Exception:
        outcome = "exception"
        raise
    finally:
        LOGGER.info(
            "agent_api_tool request_id=%s user_hash=%s plan=%s tool=%s "
            "outcome=%s elapsed_ms=%d",
            g.agent_api_request_id,
            g.agent_api_user.hash,
            report.hash,
            tool_name,
            outcome,
            round((time.monotonic() - started) * 1000),
        )


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : submission
@api.post("/plans/<plan_id>/submit")
@_route
def submit_plan(plan_id):
    report = _load_plan(plan_id)
    if report.status not in {"draft", "ready"}:
        raise APIProblem(
            "plan_state_conflict",
            "This plan cannot accept a proposal in its current state.",
            409,
        )
    data = _json_body()
    try:
        submitted = external_api.submit_plan(
            report,
            g.agent_api_user,
            data.get("proposal"),
            contract_version=data.get("contract_version"),
        )
    except exceptions.ValidationError as error:
        if report.status == "ready":
            raise APIProblem("plan_state_conflict", str(error), 409) from error
        raise
    return _plan_payload(submitted)
