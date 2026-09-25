"""Pure OpenAPI document assembly from external contract definitions."""

from copy import deepcopy

from . import definitions
from ..planner import file_usage_schema


# @testable true
# @tests tests_unit/test_032i_external_contracts.py::test_openapi_publishes_runtime_defaults_limits_and_independent_documents
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix agent-api : contract
def build_openapi_document(*, app_name, server_url):
    """Return the machine-readable workflow and contract for external agents."""
    plan_parameter = {
        "name": "plan_id",
        "in": "path",
        "required": True,
        "description": "The opaque plan ID returned by createPlan.",
        "schema": {"type": "string", "minLength": 1},
    }
    upload_batch_id_schema = definitions.upload_batch_schema()
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
    # @covered-by lagniappe/core/tools/ai/external/openapi.py::build_openapi_document
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
                        "content": {"text/markdown": {"schema": {"type": "string"}}},
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
                    "instead of guessing argument names. Reuse one Plan for saved answers and workspace changes; clients organizing files should fetch "
                    "get_guidelines task=filing before analyzing files. Use returned "
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
                                                {
                                                    "$ref": "#/components/schemas/ToolDefinition"
                                                },
                                                {"type": "string"},
                                            ]
                                        },
                                    },
                                    "view": {
                                        "type": "string",
                                        "enum": ["full", "names"],
                                    },
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
                "summary": "Create an AI plan draft",
                "description": (
                    "Starts a durable provider-free workspace. Creation does not run "
                    "a model or change workspace data. Reuse the same Plan for questions, "
                    "creation, updates, and filing. Keep the returned opaque ID for Plan-scoped "
                    "read tools and uploads when supported. Follow the returned "
                    "contract_url, submit_url, and status_url exactly instead of "
                    "reconstructing those lifecycle paths."
                ),
                "tags": ["Plans"],
                "requestBody": {
                    "required": True,
                    **json_content(
                        definitions.create_plan_request_schema()
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
                    "uploaded files, fetch after finalization. The response is "
                    "plan-, user-, file-, and permission-specific; its "
                    "proposal_schema, workflow_rules, reference_rules, and "
                    "required_file_refs are authoritative."
                ),
                "tags": ["Plans"],
                "parameters": [plan_parameter],
                "responses": {
                    "200": {
                        "description": "Current proposal and permission contract.",
                        **json_content({"$ref": "#/components/schemas/PlanContract"}),
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
                    "For a draft Plan, declare one or more local files. For "
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
                        definitions.upload_request_schema()
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
                        definitions.finalize_request_schema()
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
                    "Completed answers and ready proposals may "
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
                    "Requires the current contract and no pending uploads. Updates and creation "
                    "do not require files. Supply file_usage for every upload; only organize files "
                    "require summaries and placement. Empty actions save an answer, only after "
                    "the user requests saving. A mutation proposal becomes ready for review. "
                    "Submission never executes actions. Repeating the same result is accepted; "
                    "a later valid mutation proposal replaces the saved result until execution "
                    "begins. Revise the complete result and submit it again. Direct the user to "
                    "preview_url in the authenticated website to review and approve changes."

                ),
                "tags": ["Plans"],
                "parameters": [plan_parameter],
                "requestBody": {
                    "required": True,
                    **json_content(
                        definitions.submission_request_schema()
                    ),
                },
                "responses": {
                    "200": {
                        "description": (
                            "Compact publication receipt. Present preview_url to the user "
                            "for browser review; retain review_url as the canonical full "
                            "URL. Fetch status_url for detailed plan state. Proposals can only be applied with the existing Execute "
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
    # The plan-free endpoint has exactly the same argument and result boundary,
    # but no report lifecycle, owner lookup, or per-Plan budget.
    plan_free = deepcopy(paths["/api/v1/plans/{plan_id}/tools/{tool_name}"]["post"])
    plan_free.update(
        operationId="readWorkspaceTool",
        parameters=[tool_parameter],
        description="Run a permission-bounded read without creating a Plan or saving an answer. Use the same arguments/result envelope as Plan-scoped reads. Normal authentication, revocation, and general rate limits apply on every call.",
    )
    paths["/api/v1/tools/{tool_name}"] = {"post": plan_free}
    paths["/api/v1/answer-context"] = {
        "get": {
            "operationId": "answerQuestion",
            "summary": "Get plan-free answering guidance",
            "description": "The client model answers using authorized read tools, then offers to save. This endpoint creates no report/session and invokes no model. Start a Plan only after save consent.",
            "tags": ["Tools"],
            "responses": {
                "200": {
                    "description": "Current date, timezone, personal Page, report_created=false and workflow_rules.",
                    **json_content({"type": "object"}),
                },
                "default": error_response,
            },
        }
    }
    paths["/api/v1/plans/{plan_id}/contract"]["get"]["parameters"].extend(
        [
            {
                "name": "view",
                "in": "query",
                "schema": {"enum": list(definitions.CONTRACT_VIEWS), "default": definitions.DEFAULT_CONTRACT_VIEW},
                "description": "summary omits the proposal schema; schema returns only exact schemas and submission metadata for follow-ups using previously obtained plan context.",
            },
            {
                "name": "actions",
                "in": "query",
                "schema": {"type": "string"},
                "allowEmptyValue": True,
                "description": "Comma-separated allowed action names for selected schemas. Pass actions= for a saved-answer schema with no changes. Omit for all schemas in full/schema views, or no schema in summary view. This is context selection, not a permission change.",
            },
        ]
    )
    
    document = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{app_name} External Agent API",
            "version": "1.0.0",
            "description": (
                "Use one provider-free Plan for workspace questions, creation, updates, and filing. "
                "Answer ordinary questions with answer-context and plan-free read tools. Only save "
                "answers when requested. Requested mutations require a proposal. Start with compact "
                "context; load selected action schemas and get_guidelines task=filing for artifacts. "
                "Classify every upload in file_usage as evidence or organize. Only organize files "
                "require an attachment, one summary and two retrieval terms. The server does not call a model "
                "to complete or repair external proposals. The external API never applies those proposals; "
                "the website Execute control is the only approval and application path. Reuse a Plan "
                "for revisions until execution begins; follow returned lifecycle URLs."

            ),
        },
        "servers": [{"url": server_url.rstrip("/")}],
        "security": [{"bearerAuth": []}],
        "tags": [
            {"name": "Discovery", "description": "Actor and tool discovery."},
            {"name": "Plans", "description": "Draft and review lifecycle."},
            {"name": "Uploads", "description": "Draft plan-file staging."},
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
                                            "maxItems": definitions.MAX_VALIDATION_ERRORS,
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
                        "name": {"type": "string"},
                        "instructions": {"type": "string"},
                        "output_kind": {"enum": ["answer", "proposal", None]},
                        "file_usage": file_usage_schema(),
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
                            "const": definitions.CONTRACT_VERSION,
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
                        "execution": {
                            "type": ["object", "null"],
                            "description": "Proposal action outcomes and permission-rechecked result entity references; no private ledger data. Absent for saved answers.",
                        },
                        "action_summary": {"$ref": "#/components/schemas/ActionSummary"},
                        "original_brief": {
                            "type": ["object", "null"],
                            "description": "Initial name/instructions, retained when the current brief is revised.",
                        },
                    },
                },
                "ActionSummary": {
                    "type": "object",
                    "required": ["total", "by_type"],
                    "properties": {
                        "total": {"type": "integer", "minimum": 0},
                        "by_type": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
                        "maximum": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
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
                            "const": definitions.CONTRACT_VERSION,
                        },
                        "body": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["contract_version", "proposal", "file_usage"],
                            "properties": {
                                "contract_version": {
                                    "type": "integer",
                                    "const": definitions.CONTRACT_VERSION,
                                },
                                "file_usage": file_usage_schema(),
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
                        "current_date",
                        "timezone",
                        "personal_page",
                        "submission_format",
                        "proposal_schema",
                    "file_usage_schema",
                        "schema_scope",
                        "schema_actions",
                        "schema_instructions",
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
                            "const": definitions.CONTRACT_VERSION,
                        },
                        "current_date": {"type": "string", "format": "date"},
                        "timezone": {"type": "string"},
                        "personal_page": {"type": "object"},
                        "submission_format": {
                            "$ref": "#/components/schemas/PlanSubmissionFormat"
                        },
                        "proposal_schema": {"type": ["object", "null"]},
                        "file_usage_schema": {"type": "object"},
                        "schema_scope": {"enum": ["full", "selected", "summary"]},
                        "schema_actions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "schema_instructions": {"type": "string"},
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
                            "const": definitions.CONTRACT_VERSION,
                        },
                        "action_summary": {"$ref": "#/components/schemas/ActionSummary"},
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
                "UploadFile": definitions.upload_file_schema(),
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
    schemas = document["components"]["schemas"]
    schema_keys = definitions.SCHEMA_CONTRACT_FIELDS
    schemas["PlanSchemaContract"] = {
        "type": "object", "additionalProperties": False,
        "required": list(schema_keys),
        "properties": {
            key: ({"type": "object"} if key == "proposal_schema" else schemas["PlanContract"]["properties"][key])
            for key in schema_keys
        },
    }
    paths["/api/v1/plans/{plan_id}/contract"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = {
        "oneOf": [
            {"$ref": "#/components/schemas/PlanContract"},
            {"$ref": "#/components/schemas/PlanSchemaContract"},
        ],
    }
    return document
