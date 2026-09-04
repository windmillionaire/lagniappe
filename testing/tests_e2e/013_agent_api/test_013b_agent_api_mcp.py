"""Real managed-server boundary coverage for the standalone MCP adapter."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
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
from testing.resources import Page
from testing.utility.network import browser_fetch
from testing.utility.user_settings import go_to_my_page, open_user_settings


pytestmark = pytest.mark.e2e

DRIVER = Path("testing/utility/mcp_client_driver.py")
LIFECYCLE_TOOLS = (
    "get_actor",
    "start_ask",
    "start_create",
    "start_organize",
    "get_plan",
    "get_plan_contract",
    "upload_local_files",
    "submit_plan",
)
LIFECYCLE_SCHEMA_SHA256 = {
    "get_actor": (
        "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa",
        "6ab4edef619a8f1857fa1a097319ba5b7d81d1358bd59644e762cb91a257805e",
    ),
    "start_ask": (
        "2c41ac72c1efd4aec4a9bda14694e47f627d577fbb92d1018dc0aa211d86bd2e",
        "a7a651527355d13929828b75165770e7efc4ed187d432a380b6327d5a76a89e8",
    ),
    "start_create": (
        "2c41ac72c1efd4aec4a9bda14694e47f627d577fbb92d1018dc0aa211d86bd2e",
        "a7a651527355d13929828b75165770e7efc4ed187d432a380b6327d5a76a89e8",
    ),
    "start_organize": (
        "2c41ac72c1efd4aec4a9bda14694e47f627d577fbb92d1018dc0aa211d86bd2e",
        "a7a651527355d13929828b75165770e7efc4ed187d432a380b6327d5a76a89e8",
    ),
    "get_plan": (
        "79fdf3b7715ee289b81b9fcd675247783d2114e5b6882d555bfefa34681705c9",
        "a7a651527355d13929828b75165770e7efc4ed187d432a380b6327d5a76a89e8",
    ),
    "get_plan_contract": (
        "79fdf3b7715ee289b81b9fcd675247783d2114e5b6882d555bfefa34681705c9",
        "fd3504fe9f48b8e0c32932e9545e1e661a37db950f9c96a53dcd00d808db514e",
    ),
    "upload_local_files": (
        "716aba2ac6b72fd22813194dcf1ea9c0b492c95d02857d691d62d5309c8db259",
        "39dbca1f224f9221c330aa3f382dac6ec8db46d36f028d67b31cd06832a28d9c",
    ),
    "submit_plan": (
        "beaa898006c4f48dcacd1966a2df136ac7cd95e09f01d1716d7e9e7817cc9662",
        "a5511c1c4827ad0c8a1aee2f3be5f66636b59fe630ec659036ee802c60c9965e",
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
    raw = (
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
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
    request_headers = {"Accept": "application/json", **(headers or {})}
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    options = {
        "headers": request_headers,
        "cookies": cookies,
        "timeout": 60,
        "allow_redirects": False,
    }
    if body is not None:
        options["json"] = body
    return requests.request(
        method,
        urljoin(f"{CONFIG.BASE_URL.rstrip('/')}/", path.lstrip("/")),
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
    assert result["diagnostics"]["events"] > 0
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


def _assert_safe_plan(result: dict, *, tool: str, status: str) -> dict:
    value = _structured(result)
    assert isinstance(value, dict)
    assert set(value) == PLAN_KEYS or set(value) == PLAN_KEYS - {"proposal"}
    assert value["tool"] == tool
    assert value["status"] == status
    assert not PRIVATE_TRANSPORT_FIELDS.intersection(value)
    _assert_human_url(value["preview_url"], preview=True)
    _assert_human_url(value["review_url"], preview=False)
    return value


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
        "description": "Opaque Plan ID returned by a start_* tool.",
    }
    result.setdefault("required", []).append("plan_id")
    return result


def _assert_catalog_matches_live_rest(tools: list[dict], catalog: dict) -> None:
    assert len(tools) <= 64
    assert (
        len(json.dumps(tools, ensure_ascii=False).encode("utf-8"))
        <= 12 * 1024 * 1024
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
        ) == expected_hashes

    for name, rest_tool in rest_by_name.items():
        published = by_name[name]
        assert published["inputSchema"] == _expected_catalog_input(
            rest_tool["input_schema"]
        )
        assert published["_meta"] == {
            "lagniappe/resultPaths": rest_tool["result_paths"]
        }
        if name != "get_file":
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


def _assert_setup_panel(owner) -> tuple[str, str]:
    seen_manifest_requests = []

    def capture(request):
        if urlsplit(request.url).path == "/mcp/manifest.json":
            seen_manifest_requests.append(request)

    owner.page.on("request", capture)
    go_to_my_page(owner)
    owner_page = Page(user=owner, definition=owner.definition)
    settings = open_user_settings(owner, owner_page)
    panel = settings.locator("[data-role='mcp-setup']")
    trial_authorized = (
        CONFIG.MCP_EVALUATION_ENABLED
        and owner.email.casefold() in CONFIG.MCP_EVALUATION_ACTORS
    )
    if trial_authorized:
        expect(panel).to_be_visible()
        expect(panel.locator("[data-role='mcp-setup-status']")).to_contain_text(
            "Verified adapter"
        )
        expect(panel.locator("[data-role='mcp-setup-commands']")).to_be_visible()
        assert seen_manifest_requests
        manifest_request = seen_manifest_requests[-1]
        assert manifest_request.method == "GET"
        assert _origin(manifest_request.url) == _origin(CONFIG.BASE_URL)
        headers = {
            key.casefold(): value for key, value in manifest_request.headers.items()
        }
        assert "authorization" not in headers
        assert "cookie" not in headers
        allowed_origins = json.loads(panel.get_attribute("data-allowed-origins"))
        assert allowed_origins == list(CONFIG.MCP_EVALUATION_ORIGINS)
        assert _origin(CONFIG.BASE_URL) in allowed_origins
        install = panel.locator("[data-role='mcp-install-command']").text_content()
        configure = panel.locator("[data-role='mcp-configure-command']").text_content()
        diagnostic = panel.locator(
            "[data-role='mcp-diagnostic-command']"
        ).text_content()
        assert install.startswith("pipx install --python python3.14 --backend pip ")
        assert "#sha256=" in install
        assert configure.startswith("lagniappe-mcp configure codex --url ")
        assert f'--url "{_origin(CONFIG.BASE_URL)}"' in configure
        assert "--allowed-root" not in configure
        assert "LAGNIAPPE_API_KEY" not in configure
        assert diagnostic == "lagniappe-mcp check --profile personal"
        return install, configure
    else:
        assert not trial_authorized
        expect(panel).to_have_count(0)
        return "", ""


# @matrix mcp-package web-headers : build-marker content-addressing immutable-cache public-artifact
def test_public_mcp_release_manifest_and_wheel_are_exact() -> None:
    manifest_response = _request("GET", "/mcp/manifest.json")
    assert manifest_response.status_code == 200
    assert manifest_response.history == []
    assert manifest_response.headers["Content-Type"] == (
        "application/json; charset=utf-8"
    )
    assert manifest_response.headers["Cache-Control"] == "no-store"
    assert manifest_response.headers["X-Lagniappe-Build-ID"] == CONFIG.BUILD_ID
    manifest = manifest_response.json()
    assert manifest_response.content == (
        json.dumps(manifest, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    assert manifest["schema"] == 1
    assert manifest["package"]["name"] == "lagniappe-mcp"
    assert manifest["package"]["entry_point"] == "lagniappe-mcp"
    assert manifest["application"]["build_id"] == CONFIG.BUILD_ID

    releases = manifest["releases"]
    assert releases and all(release["supported"] is True for release in releases)
    assert len({release["version"] for release in releases}) == len(releases)
    assert len({release["sha256"] for release in releases}) == len(releases)
    matching = [
        release
        for release in releases
        if release["version"] == manifest["current"]["version"]
    ]
    assert matching == [manifest["current"]]

    for release in releases:
        version = release["version"]
        digest = release["sha256"]
        filename = f"lagniappe_mcp-{version}-py3-none-any.whl"
        expected_path = f"/mcp/releases/{version}/{digest}/{filename}"
        assert release["filename"] == filename
        assert release["artifact_path"] == expected_path
        assert release["python_requirement"] == ">=3.14,<3.15"
        assert len(release["platforms"]) == 1
        platform = release["platforms"][0]
        assert {
            field: platform[field]
            for field in ("id", "system", "architecture", "libc", "python")
        } == {
            "id": "linux-x86_64-cpython-3.14",
            "system": "linux",
            "architecture": "x86_64",
            "libc": "glibc>=2.17",
            "python": "3.14",
        }
        dependencies = platform["dependencies"]
        assert dependencies
        assert platform["dependency_graph_sha256"] == _canonical_file_sha256(
            dependencies
        )
        dependency_fields = {
            "name",
            "version",
            "filename",
            "sha256",
            "size",
            "source_url",
        }
        assert all(set(dependency) == dependency_fields for dependency in dependencies)
        response = _request("GET", expected_path)
        assert response.status_code == 200
        assert response.history == []
        assert response.headers["Content-Type"] == "application/octet-stream"
        assert response.headers["Cache-Control"] == (
            "public, max-age=31536000, immutable"
        )
        assert len(response.content) == release["size"]
        assert hashlib.sha256(response.content).hexdigest() == digest


# @pairs agent-api:bearer-only agent-api:build-marker agent-api:contract
# @pairs agent-api:create-revision agent-api:discovery agent-api:entitlement-independent
# @pairs agent-api:origin-validation agent-api:plan-capability agent-api:plan-isolation
# @pairs agent-api:plan-session agent-api:proposal-contract agent-api:request-recheck
# @pairs agent-api:revoke agent-api:session-independent agent-api:submission
# @pairs agent-api:tool-catalog agent-api:tool-dispatch agent-api:tool-selection
# @pairs agent-api:uploads mcp-adapter:product-contract mcp-upload:safe-result
# @pairs mcp-upload:upload-all mcp-package:origin-validation mcp-package:setup-command
# @pairs user-settings:origin-validation user-settings:revoke user-settings:setup-command
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
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
# @source clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
# @source src/script/widgets/mcpSetup.mjs::McpSetup
# @styles modal.wrapper modal.content modal.header modal.actions button.close label.default
def test_managed_mcp_adapter_exercises_the_real_api_boundary(
    get_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_package_environment()
    owner = get_user(Users.OWNER)
    owner.go(SitePages.HOME)
    install_command, configure_command = _assert_setup_panel(owner)
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
    assert owner_token not in install_command + configure_command
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
            name: schema["type"]
            for name, schema in upload_schema["properties"].items()
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
        hostile = _request(
            "GET", "/api/v1", token=owner_token, headers=hostile_headers
        )
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
        assert submission["contract_version"] == forwarded["contract_version"] == 6
        assert submission["body"] == {"contract_version": 6, "proposal": {}}
        assert set(submission) == {"method", "url", "contract_version", "body", "rule"}
        assert "credential-thief.invalid" not in json.dumps(forwarded)

        browser_state = {
            cookie["name"]: cookie["value"]
            for cookie in owner.page.context.cookies()
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
                "revoke": {
                    "cookies": browser_state,
                    "csrf_token": csrf_token,
                },
            },
        )
        assert workflow["protocol_version"] == "2026-07-28"
        assert workflow["server_info"] == {
            "description": "Local typed adapter for the Lagniappe External Agent API.",
            "name": "lagniappe",
            "title": "Lagniappe",
            "version": workflow["server_info"]["version"],
        }
        assert re.fullmatch(r"\d+\.\d+\.\d+", workflow["server_info"]["version"])
        assert workflow["server_capabilities"].get("resources") is None
        assert "never execute workspace changes" in workflow["instructions"]
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

        ask_start = _assert_safe_plan(
            workflow["ask"]["start"], tool="ask", status="draft"
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
        ask_contract = _structured(workflow["ask"]["contract"])
        assert "submission_format" not in ask_contract
        assert ask_contract["mcp_submission"] == {
            "contract_version": 6,
            "proposal": {},
            "proposal_schema": "$.proposal_schema",
            "instructions": (
                "Call submit_plan with this plan_id, contract_version, and a "
                "proposal matching proposal_schema."
            ),
        }
        ask_receipt = _assert_safe_receipt(
            workflow["ask"]["receipt"], status="complete"
        )
        ask_get = _assert_safe_plan(
            workflow["ask"]["get"], tool="ask", status="complete"
        )
        assert ask_get["id"] == ask_start["id"] == ask_receipt["id"]
        assert ask_get["proposal"]["actions"] == []

        create_start = _assert_safe_plan(
            workflow["create"]["start"], tool="create", status="draft"
        )
        create_contract = _structured(workflow["create"]["contract"])
        assert "create_page" in create_contract["permissions"]["allowed_actions"]
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
        assert "Revised before browser review." in replacement_get["proposal"][
            "actions"
        ][0]["data"]["document_markdown"]

        organize_start = _assert_safe_plan(
            workflow["organize"]["start"], tool="organize", status="draft"
        )
        organize_contract_before = _structured(
            workflow["organize"]["contract_before_upload"]
        )
        assert organize_contract_before["required_file_refs"] == []
        _error(
            workflow["organize"]["invalid_type"], code="input_validation_failed"
        )
        _error(
            workflow["organize"]["invalid_field"], code="input_validation_failed"
        )
        upload = _structured(workflow["organize"]["upload"])
        assert workflow["organize"]["uploaded_count"] == 1
        assert upload["plan"]["files"] == upload["upload_inventory"]
        assert str(upload_path) not in json.dumps(upload)
        organize_contract = _structured(workflow["organize"]["contract"])
        assert organize_contract["required_file_refs"] == [
            organize_contract["upload_inventory"]["files"][0]["ref"]
        ]
        assert organize_contract["upload_inventory"]["status"] == "finalized"
        assert organize_contract["permissions"]["allowed_actions"]
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
        assert foreign["protocol_version"] == "2026-07-28"
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
            hostile_setup.status_code == 200
            or 400 <= hostile_setup.status_code < 500
        )
        assert "credential-thief.invalid" not in hostile_setup.text
    finally:
        _revoke_if_active(owner)
        _revoke_if_active(intruder)
