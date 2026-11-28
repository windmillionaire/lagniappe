"""Discovery, plan and tool endpoints for external planning agents."""

from __future__ import annotations

from typing import TYPE_CHECKING
from functools import lru_cache
from hashlib import sha256

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

import json
import logging
import re
import time

from flask import g, make_response, request, url_for

from lagniappe import CONFIG
from lagniappe.core.properties.ai_report_proposal import summarize_actions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai.external import definitions
from lagniappe.core.tools.ai.external.openapi import build_openapi_document
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai.references import HASH_REFERENCE_REGEX, hash_reference
from lagniappe.core.tools.cache.rate_limit import client_ip

from . import api, api_family
from .http import APIProblem, api_absolute_url, api_route, json_body, rate_limit


LOGGER = logging.getLogger(__name__)
PLAN_START_RATE_LIMIT = (100, 60 * 60)
PLAN_TOOL_RATE_WINDOW = 31 * 24 * 60 * 60


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _file_payload(file):
    return {
        "ref": hash_reference(file),
        "name": file.name,
        "filename": file.filename,
        "mimetype": file.mimetype,
        "size": file.size,
    }






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
        "contract_url": api_absolute_url(
            url_for(
                "agent_api.get_plan_contract",
                plan_id=report.urlsafe_key,
            )
        ),
        "submit_url": api_absolute_url(
            url_for(
                "agent_api.submit_plan",
                plan_id=report.urlsafe_key,
            )
        ),
        "status_url": api_absolute_url(
            url_for(
                "agent_api.get_plan",
                plan_id=report.urlsafe_key,
            )
        ),
        "preview_url": api_absolute_url(
            url_for(
                "tools.api_plan_preview",
                plan_hash=report.hash,
            )
        ),
        "review_url": api_absolute_url(
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
        payload["action_summary"] = summarize_actions(report.proposal, maximum=external_api.MAX_PROPOSAL_ACTIONS)
    payload["correction"] = report.db.get("correction")
    payload["superseded_by"] = report.db.get("superseded_by")
    payload["original_brief"] = (report.agent_manifest or {}).get("original_brief")
    if (report.agent_manifest or {}).get("require_review") is True:
        payload["require_review"] = True
    return _json_safe(payload)


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


def _load_plan(plan_id):
    return external_api.load_plan(plan_id, g.agent_api_user)



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


def _discovery_payload():
    return {
        "name": "Lagniappe External Agent API",
        "version": "v1",
        "base_url": api_absolute_url(url_for("agent_api.api_index")).rstrip("/"),
        "openapi_url": api_absolute_url(url_for("agent_api.openapi_document")),
        "actor_url": api_absolute_url(url_for("agent_api.me")),
        "tools_url": api_absolute_url(url_for("agent_api.tools")),
        "plans_url": api_absolute_url(url_for("agent_api.create_plan")),
        "answer_context_url": api_absolute_url(url_for("agent_api.answer_context")),
        "client_skill_url": api_absolute_url(url_for("agent_api.client_skill")),
        "authentication": "Authorization: Bearer <user API key>",
        "instructions": (
            "Read openapi_url before using or guessing resource paths, then call "
            "actor_url to verify the user and capabilities."
        ),
    }


@api_family.get("/", strict_slashes=False)
@api_route
def api_family_index() -> ResponseReturnValue:
    """Identify the current version without duplicating its contract."""
    current = _discovery_payload()
    return {
        "name": current["name"],
        "current_version": current["version"],
        "versions": [current],
    }


@api.get("/", strict_slashes=False)
@api_route
def api_index() -> ResponseReturnValue:
    """Point an authenticated client directly to API discovery resources."""
    return _discovery_payload()


@api.get("/client-skill.md")
@api_route
def client_skill() -> ResponseReturnValue:
    """Return a copyable, discovery-first client skill without API schemas."""
    response = make_response(
        external_api.client_skill_markdown(
            api_absolute_url(url_for("agent_api.api_index")).rstrip("/")
        )
    )
    response.headers["Content-Type"] = "text/markdown; charset=utf-8"
    response.headers["Content-Disposition"] = 'inline; filename="SKILL.md"'
    return response


@api.get("/openapi.json")
@api_route
def openapi_document() -> ResponseReturnValue:
    """Return the authenticated external-agent contract."""
    return build_openapi_document(
        app_name=CONFIG.APP_NAME, server_url=api_absolute_url("/"),
    )


@api.get("/me")
@api_route
def me() -> ResponseReturnValue:
    actor = g.agent_api_user
    if getattr(g, "remote_mcp_authenticated", False):
        discovery = json.dumps(_discovery_payload(), sort_keys=True, separators=(",", ":"))
        g.mcp_metadata_digest = _metadata_digest(discovery)
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
            "execute_plan": _execution_allowed(),
        },
        **({"installation": {
            "project": CONFIG.GOOGLE_CLOUD_PROJECT,
            "experiments": True,
            "source_id": CONFIG.EXPERIMENTS_SOURCE_ID or None,
        }} if CONFIG.EXPERIMENTS_ENABLED else {}),
    }


@lru_cache(maxsize=4)
def _metadata_digest(discovery: str) -> str:
    """Fingerprint only deployment-wide descriptions, independently of live grants."""
    full = _catalog_payload(ai_functions.tool_catalog(transport="rest"), "full")
    catalog = json.dumps(full, sort_keys=True, separators=(",", ":"))
    return sha256(f"{discovery}\n{catalog}".encode()).hexdigest()


@api.get("/tools")
@api_route
def tools() -> ResponseReturnValue:
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
    return _catalog_payload(catalog, view)


def _catalog_payload(catalog, view):
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


@api.get("/answer-context")
@api_route
def answer_context() -> ResponseReturnValue:
    return external_api.answer_context(g.agent_api_user)


@api.post("/plans")
@api_route
def create_plan() -> ResponseReturnValue:
    actor = g.agent_api_user
    rate_limit(
        "agent-api-plan-start",
        f"{actor.urlsafe_key}:{client_ip(request)}",
        *PLAN_START_RATE_LIMIT,
    )
    data = json_body()
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
    require_review = data.get("require_review", False)
    if "require_review" in data and not isinstance(require_review, bool):
        raise APIProblem(
            "invalid_require_review",
            "require_review must be a boolean.",
            422,
            details={"path": "$.require_review", "expected": "boolean"},
        )
    report = external_api.create_plan(
        actor,
        instructions=instructions,
        name=name,
        remote_mcp=bool(getattr(g, "remote_mcp_authenticated", False)),
        revises_plan_id=data.get("revises_plan_id"),
        require_review=require_review,
    )
    return _plan_payload(report), 201


@api.get("/plans/<plan_id>")
@api_route
def get_plan(plan_id: str) -> ResponseReturnValue:
    raw_include = request.args.get("include_proposal")
    if raw_include is None:
        include_proposal = True
    else:
        normalized = str(raw_include).strip().casefold()
        if normalized in {"true", "1"}:
            include_proposal = True
        elif normalized in {"false", "0"}:
            include_proposal = False
        else:
            raise APIProblem(
                "invalid_query",
                "include_proposal must be true or false.",
                422,
            )
    return _plan_payload(_load_plan(plan_id), include_proposal=include_proposal)


def _execution_allowed():
    from lagniappe.core.tools.ai.auto_execute import can_execute_external_plan

    return can_execute_external_plan(
        g.agent_api_user,
        remote_mcp=bool(getattr(g, "remote_mcp_authenticated", False)),
    )


def _experiments_execution_allowed():
    return _execution_allowed()


@api.post("/plans/<plan_id>/execute")
@api_route
def execute_plan(plan_id: str) -> ResponseReturnValue:
    if not _execution_allowed():
        raise APIProblem(
            "execution_forbidden",
            "Automatic plan execution is not enabled for this connection.",
            403,
        )
    data = json_body()
    if (
        set(data) != {"proposal_fingerprint", "operation_id"}
        or not isinstance(data.get("proposal_fingerprint"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", data["proposal_fingerprint"])
        or not isinstance(data.get("operation_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", data["operation_id"])
    ):
        raise APIProblem(
            "invalid_execution",
            "Supply the submitted proposal_fingerprint and a stable operation_id (1–128 letters, digits, dots, underscores or hyphens).",
            422,
        )
    report = _load_plan(plan_id)
    from lagniappe.core.tools.ai.reporting.execution.request import request_execution

    remote_mcp = bool(getattr(g, "remote_mcp_authenticated", False))
    job, _notification = request_execution(
        report,
        g.agent_api_user,
        operation_id=data["operation_id"],
        expected_fingerprint=data["proposal_fingerprint"],
        remote_mcp=remote_mcp,
        external_execution=True,
    )
    if job is None:
        raise APIProblem("execution_unavailable", "Execution was not started.", 409)
    return {
        "plan": _plan_payload(_load_plan(plan_id), include_proposal=False),
        "operation": {"id": job.idempotency_key, "status": job.status},
    }, 202


@api.get("/plans/<plan_id>/contract")
@api_route
def get_plan_contract(plan_id: str) -> ResponseReturnValue:
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
        submit_url=api_absolute_url(
            url_for(
                "agent_api.submit_plan",
                plan_id=report.urlsafe_key,
            )
        ),
        **({"actions": actions} if actions is not None else {}),
        **({"view": request.args["view"]} if "view" in request.args else {}),
        execution_allowed=_experiments_execution_allowed(),
    )
    payload_sizes = contract.get("payload_sizes")
    LOGGER.info(
        "agent_api_contract request_id=%s user_hash=%s plan=%s "
        "contract_bytes=%d proposal_schema_bytes=%d",
        g.agent_api_request_id,
        g.agent_api_user.hash,
        report.hash,
        len(json.dumps(contract, ensure_ascii=False, default=str).encode("utf-8")),
        payload_sizes.get("proposal_schema_bytes", 0) if isinstance(payload_sizes, dict) else 0,
    )
    return contract



@api.post("/plans/<plan_id>/uploads")
@api_route
def create_uploads(plan_id: str) -> ResponseReturnValue:
    report = _load_plan(plan_id)
    external_api.require_uploads_available(report)
    data = json_body()
    return external_api.create_upload_sessions(
        report, g.agent_api_user, data, request_id=g.agent_api_request_id,
    ), 201


@api.post("/plans/<plan_id>/uploads/finalize")
@api_route
def finalize_uploads(plan_id: str) -> ResponseReturnValue:
    report = _load_plan(plan_id)
    external_api.require_draft(report)
    data = json_body()
    finalized = external_api.finalize_upload_batch(
        report, g.agent_api_user, data, request_id=g.agent_api_request_id,
    )
    return _plan_payload(finalized)


@api.post("/plans/<plan_id>/artifacts")
@api_route
def create_artifact(plan_id: str) -> ResponseReturnValue:
    """Submit one interactive HTML File for attachment by the normal Plan runner."""
    report = _load_plan(plan_id)
    external_api.require_draft(report)
    data = json_body()
    page = data.get("page")
    if (
        set(data) != {"page", "name", "html"}
        or not isinstance(page, str)
        or not HASH_REFERENCE_REGEX.fullmatch(page)
    ):
        raise APIProblem("invalid_artifact", "Supply an exact Page hash, name, and self-contained HTML.", 422)
    submitted = external_api.submit_plan_request(
        report,
        g.agent_api_user,
        {
            "contract_version": external_api.CONTRACT_VERSION,
            "file_usage": [],
            "proposal": {
                "summary": "Attach an interactive HTML artifact to the selected Page.",
                "confidence": 1,
                "actions": [{
                    "id": "artifact",
                    "type": "create_artifact",
                    "data": {"page": page, "name": data["name"], "artifact_html": data["html"]},
                }],
            },
        },
        request_id=g.agent_api_request_id,
        draft_only=True,
    )
    return _submission_receipt(submitted)


@api.post("/tools/<tool_name>", defaults={"plan_id": None})
@api.post("/plans/<plan_id>/tools/<tool_name>")
@api_route
def execute_tool(plan_id: str, tool_name: str) -> ResponseReturnValue:
    report = _load_plan(plan_id) if plan_id is not None else None
    if report is not None:
        _require_tools_available(report)
    if tool_name not in ai_functions.TOOL_DEFINITIONS:
        raise APIProblem("tool_not_found", "Tool not found.", 404)
    rate_state = (
        rate_limit(
            "agent-api-plan-tools",
            report.urlsafe_key,
            external_api.MAX_PLAN_TOOL_CALLS,
            PLAN_TOOL_RATE_WINDOW,
        )
        if report is not None
        else {"count": 0}
    )
    data = json_body()
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


@api.post("/plans/<plan_id>/submit")
@api_route
def submit_plan(plan_id: str) -> ResponseReturnValue:
    report = _load_plan(plan_id)
    external_api.require_submission_available(report)
    data = json_body()
    submitted = external_api.submit_plan_request(
        report, g.agent_api_user, data, request_id=g.agent_api_request_id,
    )
    receipt = _submission_receipt(submitted)
    if data.get("execute") is True and submitted.output_kind == "proposal":
        from lagniappe.core.tools.ai.auto_execute import (
            experiments_execution_allowed,
            plan_requires_review,
        )
        from lagniappe.core.tools.ai.reporting.execution.request import (
            request_execution,
        )

        if not _execution_allowed():
            receipt["execution"] = {
                "started": False,
                "reason": "Automatic plan execution is not enabled for this connection.",
            }
        else:
            remote_mcp = bool(getattr(g, "remote_mcp_authenticated", False))
            is_experiments = experiments_execution_allowed(
                g.agent_api_user, remote_mcp=remote_mcp
            )
            pause_reason = plan_requires_review(
                submitted, enforce_safety_pause=not is_experiments
            )
            if pause_reason:
                receipt["execution"] = {"started": False, "reason": pause_reason}
            else:
                job, _notification = request_execution(
                    submitted,
                    g.agent_api_user,
                    operation_id=data["operation_id"],
                    expected_fingerprint=receipt["proposal_fingerprint"],
                    remote_mcp=remote_mcp,
                    external_execution=True,
                )
                if job is None:
                    raise APIProblem("execution_unavailable", "Execution was not started.", 409)
                refreshed = _load_plan(plan_id)
                receipt["status"] = refreshed.status
                receipt["operation"] = {
                    "id": job.idempotency_key,
                    "status": job.status,
                }
                receipt["execution"] = {"started": True}
    return receipt
