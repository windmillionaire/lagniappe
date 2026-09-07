"""Real managed-server boundary coverage for the standalone MCP adapter."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import pytest
import requests
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import AI
from runner import mcp_environment
from testing.definitions import Pages, SitePages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.utility.network import browser_fetch


pytestmark = pytest.mark.e2e

DRIVER = Path("testing/utility/mcp_client_driver.py")
LIFECYCLE_TOOLS = (
    "answer_question",
    "get_actor",
    "start_ask",
    "start_create",
    "start_organize",
    "get_plan",
    "get_plan_contract",
    "upload_local_files",
    "submit_plan",
)
# Reviewed conversational contracts: plan-free context, optional brief revisions,
# execution receipts, and compact/selected schemas in starter/upload context.
# Version 7 changes only the supported contract-version bounds in these schemas.
LIFECYCLE_SCHEMA_SHA256 = {
    "answer_question": (
        "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa",
        "f6adb29d9eb84fc5920b6c8a7bae19d4b4690f7a90003a4f076aaba06131e61d",
    ),
    "get_actor": (
        "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa",
        "6ab4edef619a8f1857fa1a097319ba5b7d81d1358bd59644e762cb91a257805e",
    ),
    "start_ask": (
        "2c41ac72c1efd4aec4a9bda14694e47f627d577fbb92d1018dc0aa211d86bd2e",
        "544d4448ac2af7f8d3685766fc86c5dadac524e062ba4ffa291a03808d54366d",
    ),
    "start_create": (
        "2c41ac72c1efd4aec4a9bda14694e47f627d577fbb92d1018dc0aa211d86bd2e",
        "544d4448ac2af7f8d3685766fc86c5dadac524e062ba4ffa291a03808d54366d",
    ),
    "start_organize": (
        "2c41ac72c1efd4aec4a9bda14694e47f627d577fbb92d1018dc0aa211d86bd2e",
        "544d4448ac2af7f8d3685766fc86c5dadac524e062ba4ffa291a03808d54366d",
    ),
    "get_plan": (
        "79fdf3b7715ee289b81b9fcd675247783d2114e5b6882d555bfefa34681705c9",
        "93ac7fd41d6414596b6c4a9ad555af53fe97f37c410f44a8bd736f67a562c287",
    ),
    "get_plan_contract": (
        "8054a33de0dcc82cb083398f7f8fb6bb0c2e72aa439f4bf21471e75ee7b44989",
        "ca7162560fcd6af6d04feb38860f43c10e55111951428d2dccf22baa029205c8",
    ),
    "upload_local_files": (
        "716aba2ac6b72fd22813194dcf1ea9c0b492c95d02857d691d62d5309c8db259",
        "95d57b63452cce0766c9ff0c636f61fc85fea02226d688435763b060bf556297",
    ),
    "submit_plan": (
        "18e44236fd78c5fa56314d6df698b339be168781d967947a7ac9efcfee57a9ef",
        "0062860fc35ce6a61f7a49c702558356f99553f6b8834e37816e63966e7fe062",
    ),
}
PLAN_KEYS = {
    "id",
    "status",
    "tool",
    "name",
    "instructions",
    "files",
    "uploads_pending",
    "contract_version",
    "preview_url",
    "review_url",
    "proposal",
}
RECEIPT_KEYS = {
    "id",
    "status",
    "preview_url",
    "review_url",
    "contract_version",
    "proposal_fingerprint",
}
PRIVATE_TRANSPORT_FIELDS = {
    "api_key",
    "authorization",
    "cookie",
    "download_url",
    "expires_in",
    "session_url",
    "token",
    "upload_id",
    "upload_batch_id",
    "upload_url",
    "x-goog-signature",
}
MCP_BOUNDARY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
    "AQUBAScY42YAAAAASUVORK5CYII="
)


def _canonical_sha256(value) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _canonical_file_sha256(value) -> str:
    raw = (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body=None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> requests.Response:
    url = urljoin(f"{CONFIG.BASE_URL.rstrip('/')}/", path.lstrip("/"))
    if _origin(url) != _origin(CONFIG.BASE_URL):
        raise ValueError("Direct test client refused a different origin")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    run_cookie = os.environ.get("LAGNIAPPE_HOSTED_E2E_TEST_COOKIE")
    request_cookies = dict(cookies or {})
    if run_cookie:
        request_cookies["__Host-lagniappe-e2e"] = run_cookie
    options = {
        "headers": request_headers,
        "cookies": request_cookies,
        "timeout": 60,
        "allow_redirects": False,
    }
    if body is not None:
        options["json"] = body
    return requests.request(
        method,
        url,
        **options,
    )


def _json_response(response: requests.Response, status: int) -> dict:
    assert response.status_code == status, response.text[:240]
    assert response.headers["Content-Type"].split(";", 1)[0] == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Lagniappe-Build-ID"] == CONFIG.BUILD_ID
    value = response.json()
    assert isinstance(value, dict)
    return value


def _issue_key(user) -> str:
    issued = browser_fetch(user, "/users/me/api-key", method="POST")
    assert issued["status"] == 201
    assert issued["data"]["shown_once"] is True
    token = issued["data"]["token"]
    assert isinstance(token, str) and token.startswith("lgn_")
    return token


def _revoke_if_active(user) -> None:
    status = browser_fetch(user, "/users/me/api-key", method="GET")
    if status["status"] == 200 and status["data"]["credential"]["active"] is True:
        revoked = browser_fetch(user, "/users/me/api-key", method="DELETE")
        assert revoked["status"] == 200
        assert revoked["data"]["credential"]["active"] is False


def _prepare_package_environment() -> None:
    if CONFIG.hosted_e2e_runner:
        mcp_environment.check_environment()
    else:
        mcp_environment.prepare_environment()


def _run_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
    token: str,
    specification: dict,
) -> dict:
    identifier = uuid4().hex
    specification_path = tmp_path / f"mcp-{identifier}.json"
    result_path = tmp_path / f"mcp-{identifier}-result.json"
    specification_path.write_text(
        json.dumps(specification, ensure_ascii=False), encoding="utf-8"
    )
    with monkeypatch.context() as environment:
        environment.setenv("LAGNIAPPE_URL", CONFIG.BASE_URL)
        environment.setenv("LAGNIAPPE_API_KEY", token)
        status = mcp_environment.run_python(
            [DRIVER, mode, specification_path, result_path],
            prepared=True,
        )
    assert result_path.is_file(), "The isolated MCP SDK driver returned no result."
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert status == 0, result.get("driver_error", "MCP SDK driver failed")
    assert "driver_error" not in result
    assert result["diagnostics"]["contains_sensitive_value"] is False
    assert result["diagnostics"]["invalid_events"] == 0
    assert result["diagnostics"]["max_event_bytes"] <= 8 * 1024
    assert result["diagnostics"]["truncated"] is False
    return result


def _structured(result: dict) -> object:
    assert result.get("resultType") == "complete"
    assert result.get("isError") is not True
    assert "structuredContent" in result
    return result["structuredContent"]


def _error(result: dict, *, code: str, status: int | None = None) -> dict:
    assert result.get("resultType") == "complete"
    assert result.get("isError") is True
    assert "structuredContent" not in result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    value = json.loads(result["content"][0]["text"])
    assert value["code"] == code
    if status is not None:
        assert value["http_status"] == status
    return value


def _assert_human_url(value: str, *, preview: bool) -> None:
    parsed = urlsplit(value)
    assert _origin(value) == _origin(CONFIG.BASE_URL)
    pattern = (
        r"/tools/api-plan/[A-Za-z0-9_-]{12}"
        if preview
        else r"/tools/reports/[A-Za-z0-9_-]+"
    )
    assert re.fullmatch(pattern, parsed.path)
    assert parsed.query == parsed.fragment == ""


def _assert_no_private_transport(value: object) -> None:
    if isinstance(value, dict):
        assert not PRIVATE_TRANSPORT_FIELDS.intersection(value)
        for child in value.values():
            _assert_no_private_transport(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_private_transport(child)
    elif isinstance(value, str):
        assert "storage.googleapis.com" not in value
        assert "x-goog-" not in value.casefold()


def _assert_safe_plan(
    result: dict, *, tool: str, status: str, context: str | None = None
) -> dict:
    value = _structured(result)
    assert isinstance(value, dict)
    expected_keys = PLAN_KEYS | {"original_brief"} | ({"execution"} if tool != "ask" else set()) | ({"context"} if context else set())
    assert set(value) in (expected_keys, expected_keys - {"proposal"})
    assert value["tool"] == tool
    assert value["status"] == status
    _assert_no_private_transport(value)
    if context:
        assert set(value["context"]) == {context}
    _assert_human_url(value["preview_url"], preview=True)
    _assert_human_url(value["review_url"], preview=False)
    return value


def _assert_mcp_contract(contract: dict, *, tool: str) -> None:
    _assert_no_private_transport(contract)
    assert "submission_format" not in contract
    assert contract["tool"] == tool
    submission = contract["mcp_submission"]
    assert set(submission) == {
        "contract_version",
        "proposal",
        "proposal_schema",
        "instructions",
    }
    assert submission["contract_version"] == contract["contract_version"] == 7
    assert submission["proposal"] == {}
    assert submission["proposal_schema"] == "$.proposal_schema"
    assert submission["instructions"].startswith("Call submit_plan")
    assert "to this contract object" in submission["instructions"]
    assert "current contract again" in submission["instructions"]
    workflow = "\n".join(contract["workflow_rules"])
    assert "fetch the latest contract and submit it" not in workflow
    assert "Fetch this contract after finalizing uploads" not in workflow
    if tool == "ask":
        assert "only after the user requests saving" in workflow
    elif tool == "organize" and contract["required_file_refs"]:
        assert "context.contract" in workflow
        assert "submit_plan performs the final fresh-contract check" in workflow


def _assert_safe_receipt(result: dict, *, status: str) -> dict:
    value = _structured(result)
    assert isinstance(value, dict) and set(value) == RECEIPT_KEYS
    assert value["status"] == status
    assert not PRIVATE_TRANSPORT_FIELDS.intersection(value)
    _assert_human_url(value["preview_url"], preview=True)
    _assert_human_url(value["review_url"], preview=False)
    return value


def _expected_catalog_input(schema: dict) -> dict:
    result = deepcopy(schema)
    result.setdefault("properties", {})["plan_id"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 2048,
        "description": "Optional existing Plan ID for report-scoped work. Omit for ordinary questions, task lookups and workspace reads; no Plan is created.",
    }
    result.setdefault("required", [])
    return result


def _assert_catalog_matches_live_rest(tools: list[dict], catalog: dict) -> None:
    assert len(tools) <= 64
    assert (
        len(json.dumps(tools, ensure_ascii=False).encode("utf-8")) <= 12 * 1024 * 1024
    )
    by_name = {tool["name"]: tool for tool in tools}
    rest_by_name = {tool["name"]: tool for tool in catalog["tools"]}
    assert list(by_name) == [*LIFECYCLE_TOOLS, *sorted(rest_by_name)]
    assert not set(LIFECYCLE_TOOLS).intersection(rest_by_name)
    assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in by_name)
    assert len(by_name) == len(tools)

    for name, expected_hashes in LIFECYCLE_SCHEMA_SHA256.items():
        assert (
            _canonical_sha256(by_name[name]["inputSchema"]),
            _canonical_sha256(by_name[name]["outputSchema"]),
        ) == expected_hashes, name

    # The adapter preserves REST descriptions and adds transport-specific
    # guidance for selected reads; these additions shipped in local 0.1.6.
    description_guidance = {
        "query_workspace_filter": (
            "Preserve counts, continuation/truncation flags, and partial errors.",
            "never start another Plan to change output formatting.",
        ),
        "search_entities": (
            "Returned hits are view-authorized; reuse their evidence.",
            "Load full details only for information missing from the results.",
        ),
        "get_entity": (
            "Reuse attached Form schemas and other returned evidence;",
            "fetch again only for missing information or relevant changes.",
        ),
    }
    for name, rest_tool in rest_by_name.items():
        published = by_name[name]
        assert published["inputSchema"] == _expected_catalog_input(
            rest_tool["input_schema"]
        )
        assert published["_meta"] == {
            "lagniappe/resultPaths": rest_tool["result_paths"]
        }
        if name != "get_file":
            if name in description_guidance:
                assert published["description"].startswith(
                    rest_tool["description"] + " "
                )
                for guidance in description_guidance[name]:
                    assert guidance in published["description"]
            else:
                assert published["description"] == rest_tool["description"]
            assert published["outputSchema"] == rest_tool["output_schema"]

    get_file = by_name["get_file"]["outputSchema"]
    assert not PRIVATE_TRANSPORT_FIELDS.intersection(get_file["properties"])
    assert set(get_file["properties"]["original_file"]["properties"]) == {
        "supported",
        "attached",
        "reason",
    }
    assert get_file["properties"]["original_file"]["additionalProperties"] is False
    assert get_file["properties"]["delivery"]["additionalProperties"] is False
    assert set(get_file["properties"]) == {
        "hash",
        "display_name",
        "filename",
        "mimetype",
        "large",
        "summary",
        "permissions",
        "url",
        "content",
        "error",
        "original_file",
        "delivery",
    }
    assert get_file["additionalProperties"] is False


# @pairs agent-api:bearer-only agent-api:build-marker agent-api:contract
# @pairs agent-api:create-revision agent-api:discovery agent-api:entitlement-independent
# @pairs agent-api:origin-validation agent-api:plan-capability agent-api:plan-isolation
# @pairs agent-api:plan-session agent-api:proposal-contract agent-api:request-recheck
# @pairs agent-api:revoke agent-api:session-independent agent-api:submission
# @pairs agent-api:tool-catalog agent-api:tool-dispatch agent-api:tool-selection
# @pairs agent-api:uploads mcp-adapter:product-contract mcp-upload:safe-result
# @pairs mcp-upload:upload-all
# @pair user-settings:revoke
# @matrix agent-api task-scheduling : periodic recurring scheduled structured-output validation
# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_task_schedule_response_schema
# @source lagniappe/web/routes/api/main.py::authenticate_request
# @source lagniappe/web/routes/api/main.py::annotate_response
# @source lagniappe/web/routes/api/main.py::api_index
# @source lagniappe/web/routes/api/main.py::openapi_document
# @source lagniappe/web/routes/api/main.py::me
# @source lagniappe/web/routes/api/main.py::tools
# @source lagniappe/web/routes/api/main.py::create_plan
# @source lagniappe/web/routes/api/main.py::_load_plan
# @source lagniappe/web/routes/api/main.py::get_plan
# @source lagniappe/web/routes/api/main.py::get_plan_contract
# @source lagniappe/web/routes/api/main.py::create_uploads
# @source lagniappe/web/routes/api/main.py::finalize_uploads
# @source lagniappe/web/routes/api/main.py::execute_tool
# @source lagniappe/web/routes/api/main.py::submit_plan
# @source lagniappe/web/routes/users/api_key.py::api_key
# @source lagniappe/core/tools/email/notifications/links.py::origin
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
# @source mcp/src/lagniappe_mcp/files.py::upload_local_files
# @styles modal.wrapper modal.content modal.header modal.actions button.close label.default
def test_managed_mcp_adapter_exercises_the_real_api_boundary(
    get_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setup_test_server,
) -> None:
    monkeypatch.delenv("LAGNIAPPE_HOSTED_E2E_TEST_COOKIE", raising=False)
    for cookie in setup_test_server.browser_cookies:
        if cookie["name"] == "__Host-lagniappe-e2e":
            monkeypatch.setenv("LAGNIAPPE_HOSTED_E2E_TEST_COOKIE", cookie["value"])
    with monkeypatch.context() as guarded:
        guarded.setattr(requests, "request", lambda *args, **kwargs: pytest.fail(
            "A foreign-origin request reached the network boundary"
        ))
        with pytest.raises(ValueError, match="different origin"):
            _request("GET", "https://storage.googleapis.com/object", token="test-only")
    _prepare_package_environment()
    owner = get_user(Users.OWNER)
    owner.go(SitePages.HOME)
    readable_page = Pages.test_create_page.get(owner)

    suffix = uuid4().hex
    intruder = get_user(
        UserDefinition(
            name=f"MCP Boundary Intruder {suffix}",
            email=f"mcp-boundary-intruder-{suffix}@example.test",
            ai_access=AI.NONE,
        ),
        creator=owner,
    )
    intruder.go(SitePages.HOME)

    owner_token = _issue_key(owner)
    intruder_token = _issue_key(intruder)
    upload_path = tmp_path / "mcp-boundary-image.png"
    upload_path.write_bytes(MCP_BOUNDARY_PNG)

    try:
        discovery_response = _request("GET", "/api/v1", token=owner_token)
        discovery = _json_response(discovery_response, 200)
        assert discovery["version"] == "v1"
        expected_api_origin = _origin(CONFIG.BASE_URL)
        for field, path in {
            "base_url": "/api/v1",
            "openapi_url": "/api/v1/openapi.json",
            "actor_url": "/api/v1/me",
            "tools_url": "/api/v1/tools",
            "plans_url": "/api/v1/plans",
            "client_skill_url": "/api/v1/client-skill.md",
        }.items():
            assert discovery[field] == f"{expected_api_origin}{path}"

        openapi = _json_response(
            _request("GET", "/api/v1/openapi.json", token=owner_token), 200
        )
        assert openapi["openapi"] == "3.1.0"
        expected_methods = {
            "/api/v1/answer-context": "get",
            "/api/v1/tools/{tool_name}": "post",
            "/api/v1": "get",
            "/api/v1/client-skill.md": "get",
            "/api/v1/me": "get",
            "/api/v1/plans": "post",
            "/api/v1/plans/{plan_id}": "get",
            "/api/v1/plans/{plan_id}/contract": "get",
            "/api/v1/plans/{plan_id}/submit": "post",
            "/api/v1/plans/{plan_id}/tools/{tool_name}": "post",
            "/api/v1/plans/{plan_id}/uploads": "post",
            "/api/v1/plans/{plan_id}/uploads/finalize": "post",
            "/api/v1/tools": "get",
        }
        assert set(openapi["paths"]) == set(expected_methods)
        assert all(
            set(openapi["paths"][path]) == {method}
            for path, method in expected_methods.items()
        )
        assert all("execute" not in path for path in openapi["paths"])
        upload_schema = openapi["components"]["schemas"]["UploadFile"]
        assert upload_schema["additionalProperties"] is False
        assert upload_schema["required"] == ["filename", "size"]
        assert {
            name: schema["type"] for name, schema in upload_schema["properties"].items()
        } == {
            "filename": "string",
            "content_type": "string",
            "size": "integer",
        }

        catalog = _json_response(
            _request("GET", "/api/v1/tools", token=owner_token), 200
        )
        assert catalog["view"] == "full"
        assert catalog["selected_count"] == len(catalog["tools"])

        invalid_plan = _json_response(
            _request(
                "POST",
                "/api/v1/plans",
                token=owner_token,
                body={
                    "tool": "organize",
                    "name": "MCP upload declaration parity",
                    "instructions": "Validate rejected upload declarations.",
                },
            ),
            201,
        )
        invalid_upload_path = f"/api/v1/plans/{invalid_plan['id']}/uploads"
        invalid_declarations = (
            (
                {"files": [{"filename": "note.txt", "size": 1, "extra": True}]},
                "unsupported_field",
                "$.files[0]",
            ),
            (
                {"files": [{"filename": 7, "size": 1}]},
                "invalid_file",
                "$.files[0].filename",
            ),
            (
                {"files": [{"filename": "note.txt", "content_type": 7, "size": 1}]},
                "invalid_content_type",
                "$.files[0].content_type",
            ),
        )
        for declaration, code, path in invalid_declarations:
            rejected = _json_response(
                _request(
                    "POST",
                    invalid_upload_path,
                    token=owner_token,
                    body=declaration,
                ),
                422,
            )
            assert rejected["error"]["code"] == code
            assert rejected["error"]["details"]["path"] == path

        hostile_headers = {
            "Host": "credential-thief.invalid",
            "X-Forwarded-Host": "credential-thief.invalid",
        }
        hostile = _request("GET", "/api/v1", token=owner_token, headers=hostile_headers)
        assert hostile.status_code == 200 or 400 <= hostile.status_code < 500
        assert "credential-thief.invalid" not in hostile.text
        forwarded = _json_response(
            _request(
                "GET",
                f"/api/v1/plans/{invalid_plan['id']}/contract",
                token=owner_token,
                headers={"X-Forwarded-Host": "credential-thief.invalid"},
            ),
            200,
        )
        submission = forwarded["submission_format"]
        assert submission["method"] == "POST"
        assert submission["url"] == (
            f"{expected_api_origin}/api/v1/plans/{invalid_plan['id']}/submit"
        )
        assert submission["contract_version"] == forwarded["contract_version"] == 7
        assert submission["body"] == {"contract_version": 7, "proposal": {}}
        assert set(submission) == {"method", "url", "contract_version", "body", "rule"}
        assert "credential-thief.invalid" not in json.dumps(forwarded)

        browser_state = {
            cookie["name"]: cookie["value"] for cookie in owner.page.context.cookies()
        }
        csrf_token = owner.page.locator("#token").input_value()
        workflow = _run_driver(
            tmp_path,
            monkeypatch,
            mode="workflow",
            token=owner_token,
            specification={
                "upload_path": str(upload_path),
                "search_name": readable_page.entity.name,
                "page_ref": f"hash:{readable_page.entity.hash}",
                "revoke": {
                    "cookies": browser_state,
                    "csrf_token": csrf_token,
                },
            },
        )
        _assert_catalog_matches_live_rest(workflow["tools"], catalog)

        actor = _structured(workflow["actor"])
        assert actor["user"]["hash"] == owner.entity.hash
        assert actor["user"]["name"] == owner.name
        assert actor["capabilities"] == {
            "ask": True,
            "create": True,
            "organize": True,
        }
        assert actor["credential"]["active"] is True
        assert _structured(workflow["answer_context"])["report_created"] is False
        schema_values = _structured(workflow["schema_values"])
        assert schema_values["entity"]["hash"] == f"hash:{readable_page.entity.hash}"
        if schema_values["form"]:
            assert isinstance(schema_values["values"], dict)
            assert set(schema_values["values"]) <= {field["id"] for field in schema_values["schema"]}
        else:
            assert schema_values["values"] is None
        assert any(item.get("hash") == f"hash:{readable_page.entity.hash}" for item in _structured(workflow["plan_free_search"]))

        ask_start = _assert_safe_plan(
            workflow["ask"]["start"], tool="ask", status="draft", context="contract"
        )
        search = _structured(workflow["ask"]["search"])
        assert isinstance(search, list) and search
        readable_matches = [
            item
            for item in search
            if item.get("hash") == f"hash:{readable_page.entity.hash}"
        ]
        assert len(readable_matches) == 1
        assert readable_matches[0]["permissions"] == {
            "can_view": True,
            "can_edit": True,
            "can_create": True,
        }
        ask_contract = ask_start["context"]["contract"]
        _assert_mcp_contract(ask_contract, tool="ask")
        assert ask_contract["required_file_refs"] == []
        ask_receipt = _assert_safe_receipt(
            workflow["ask"]["receipt"], status="complete"
        )
        ask_get = _assert_safe_plan(
            workflow["ask"]["get"], tool="ask", status="complete"
        )
        assert ask_get["id"] == ask_start["id"] == ask_receipt["id"]
        assert ask_get["proposal"]["actions"] == []

        create_start = _assert_safe_plan(
            workflow["create"]["start"],
            tool="create",
            status="draft",
            context="contract",
        )
        create_contract = create_start["context"]["contract"]
        _assert_mcp_contract(create_contract, tool="create")
        assert "create_page" in create_contract["permissions"]["allowed_actions"]
        assert create_contract["proposal_schema"] is None and create_contract["schema_scope"] == "summary"
        selected_contract = _structured(workflow["create"]["selected_contract"])
        assert selected_contract["schema_scope"] == "selected"
        assert "workflow_rules" not in selected_contract
        assert "submission_format" not in selected_contract
        assert selected_contract["mcp_submission"]["contract_version"] == 7
        assert set(selected_contract["proposal_schema"]["$defs"]) == {"create_page", "create_task"}
        create_receipt = _assert_safe_receipt(
            workflow["create"]["receipt"], status="ready"
        )
        create_get = _assert_safe_plan(
            workflow["create"]["get"], tool="create", status="ready"
        )
        replacement_receipt = _assert_safe_receipt(
            workflow["create"]["replacement_receipt"], status="ready"
        )
        replacement_get = _assert_safe_plan(
            workflow["create"]["replacement_get"], tool="create", status="ready"
        )
        assert {
            create_start["id"],
            create_receipt["id"],
            create_get["id"],
            replacement_receipt["id"],
            replacement_get["id"],
        } == {create_start["id"]}
        assert replacement_get["proposal"]["summary"] == (
            "Create the revised field guide Page."
        )
        assert replacement_get["name"] == "MCP revised Create"
        assert replacement_get["instructions"] == "Prepare the revised field guide Page for browser review."
        assert replacement_get["original_brief"]["name"] == "MCP live Create"
        assert (
            "Revised before browser review."
            in replacement_get["proposal"]["actions"][0]["data"]["document_markdown"]
        )

        update_start = _assert_safe_plan(
            workflow["update"]["start"],
            tool="organize",
            status="draft",
            context="contract",
        )
        update_context = update_start["context"]["contract"]
        assert update_context["proposal_schema"] is None
        assert not update_context["guidance_requirements"]["required_before_analysis"]
        update_contract = _structured(workflow["update"]["contract"])
        _assert_mcp_contract(update_contract, tool="organize")
        assert update_contract["required_file_refs"] == []
        assert set(update_contract["proposal_schema"]["$defs"]) == {
            "rename_entity",
            "complete_task",
        }
        assert "create_task" not in update_contract["permissions"]["allowed_actions"]
        _assert_safe_receipt(workflow["update"]["receipt"], status="ready")
        update_get = _assert_safe_plan(
            workflow["update"]["get"], tool="organize", status="ready"
        )
        assert (
            update_get["proposal"]["actions"][0]["data"]["entity"]
            == f"hash:{readable_page.entity.hash}"
        )
        assert (
            update_get["proposal"]["actions"][0]["data"]["name"]
            == "Proposed MCP Page name"
        )

        organize_start = _assert_safe_plan(
            workflow["organize"]["start"],
            tool="organize",
            status="draft",
            context="contract",
        )
        assert organize_start["context"]["contract"]["proposal_schema"] is None
        guidelines = _structured(workflow["organize"]["guidelines"])
        assert guidelines["task"] == "organize"
        assert (
            "author the final summaries and form submissions or updates yourself"
            in guidelines["guidelines"]
        )
        assert (
            "No action contains submission-generation fields"
            not in guidelines["guidelines"]
        )
        organize_contract_before = _structured(
            workflow["organize"]["contract_before_upload"]
        )
        _assert_mcp_contract(organize_contract_before, tool="organize")
        assert organize_contract_before["required_file_refs"] == []
        _error(workflow["organize"]["invalid_type"], code="input_validation_failed")
        _error(workflow["organize"]["invalid_field"], code="input_validation_failed")
        upload = _structured(workflow["organize"]["upload"])
        _assert_no_private_transport(upload)
        assert set(upload) == {"plan", "upload_inventory", "context"}
        assert set(upload["context"]) == {"contract"}
        assert workflow["organize"]["uploaded_count"] == 1
        assert upload["plan"]["files"] == upload["upload_inventory"]
        assert str(upload_path) not in json.dumps(upload)
        organize_contract = upload["context"]["contract"]
        _assert_mcp_contract(organize_contract, tool="organize")
        assert organize_contract["proposal_schema"] is None
        assert organize_contract["schema_scope"] == "summary"
        organize_selected = _structured(workflow["organize"]["selected_contract"])
        assert organize_selected["schema_scope"] == "selected"
        assert "workflow_rules" not in organize_selected
        assert "upload_inventory" not in organize_selected
        assert set(organize_selected["proposal_schema"]["$defs"]) == {
            "create_task", "attach_file", "summarize_file"
        }
        assert organize_contract["required_file_refs"] == [
            organize_contract["upload_inventory"]["files"][0]["ref"]
        ]
        assert organize_contract["upload_inventory"]["status"] == "finalized"
        assert organize_contract["permissions"]["allowed_actions"]
        assert (
            organize_contract["upload_inventory"]["files"] == upload["upload_inventory"]
        )
        for tool in ("create", "organize"):
            assert workflow[tool]["schedule_checks"] == {
                "recurring": True,
                "periodic": True,
                "weekly": True,
                "monthly": True,
                "yearly": True,
                "missing_interval": False,
                "zero_interval": False,
                "missing_periodic_description": False,
                "missing_mode": False,
                "empty_days": False,
                "invalid_weekday": False,
                "missing_month_day": False,
                "missing_year_month": False,
            }
        file_metadata = _structured(workflow["organize"]["file_metadata"])
        assert file_metadata["delivery"] == {"kind": "none"}
        assert len(workflow["organize"]["file_metadata"]["content"]) == 1
        file_original = _structured(workflow["organize"]["file_original"])
        assert file_original["delivery"] == {
            "kind": "image",
            "mime_type": "image/png",
            "size_bytes": len(MCP_BOUNDARY_PNG),
            "content_index": 1,
        }
        original_content = workflow["organize"]["file_original"]["content"]
        assert len(original_content) == 2
        assert original_content[1] == {
            "type": "image",
            "data": base64.b64encode(MCP_BOUNDARY_PNG).decode("ascii"),
            "mimeType": "image/png",
        }
        serialized_original = json.dumps(workflow["organize"]["file_original"])
        assert not PRIVATE_TRANSPORT_FIELDS.intersection(file_original)
        assert "storage.googleapis.com" not in serialized_original
        assert "x-goog-" not in serialized_original.casefold()
        organize_receipt = _assert_safe_receipt(
            workflow["organize"]["receipt"], status="ready"
        )
        organize_get = _assert_safe_plan(
            workflow["organize"]["get"], tool="organize", status="ready"
        )
        assert organize_get["id"] == organize_start["id"] == organize_receipt["id"]
        assert organize_get["files"] == upload["upload_inventory"]

        assert workflow["revocation"]["status"] == 200
        assert workflow["revocation"]["body"]["credential"]["active"] is False
        _error(workflow["revoked_call"], code="unauthorized", status=401)

        foreign = _run_driver(
            tmp_path,
            monkeypatch,
            mode="foreign",
            token=intruder_token,
            specification={"plan_id": create_start["id"]},
        )
        assert [tool["name"] for tool in foreign["tools"]] == [
            tool["name"] for tool in workflow["tools"]
        ]
        _error(foreign["foreign_plan"], code="not_found", status=404)

        review_response = owner.page.goto(
            create_receipt["review_url"], wait_until="load"
        )
        assert review_response is not None and review_response.status == 200
        expect(owner.page.get_by_role("button", name="Execute")).to_be_visible()
        assert "execute" not in {tool["name"] for tool in workflow["tools"]}

        hostile_setup = _request(
            "GET",
            owner.suffix(),
            headers=hostile_headers,
            cookies=browser_state,
        )
        assert (
            hostile_setup.status_code == 200 or 400 <= hostile_setup.status_code < 500
        )
        assert "credential-thief.invalid" not in hostile_setup.text
    finally:
        _revoke_if_active(owner)
        _revoke_if_active(intruder)
