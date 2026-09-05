"""Real stateless MCP protocol over the shared adapter and fake upstream HTTP."""

import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import time

import httpx
import pytest
from mcp.shared.inbound import encode_header_value

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lagniappe_mcp_remote import hosted
from lagniappe_mcp_remote import hosted_files
from lagniappe_mcp.adapter import LagniappeAdapter
from lagniappe_mcp.configuration import ConnectionConfig
from lagniappe_mcp.errors import AdapterError, ConfigurationError
from lagniappe_mcp.url_security import normalize_site_url


CONFIG = hosted.HostedConfig(
    issuer="https://example.com", resource="https://pilot.run.app/mcp"
)
TOKEN_A = "lgmo_a_" + "a" * 43
TOKEN_B = "lgmo_a_" + "b" * 43
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "remote-test", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


# @matrix mcp-remote : parity privacy
# @matrix mcp-upload : remote cleanup partial-failure upload-all finalize-once
@pytest.mark.parametrize("storage_failure", [False, True])
def test_remote_attachment_uses_shared_upload_and_preserves_pending_failure(
    monkeypatch, storage_failure
):
    from lagniappe_mcp.limits import CONTRACT_VERSION_MAX, MIN_UPLOAD_CHUNK_BYTES

    async def scenario():
        requests, revoked, downloads, storage_requests = [], set(), [], []
        declarations, finalized = [], False
        content = b"remote attachment bytes"
        batch_id = "batch-aaaaaaaaaaaaaaaa"
        session_url = "https://storage.googleapis.com/upload/storage/v1/b/bucket/o?uploadType=resumable&upload_id=private"
        attachment = {
            "download_url": "https://files.example.com/attachment?private=link",
            "file_id": "file-1",
            "file_name": "notes.txt",
            "mime_type": "text/plain",
        }
        plan_url = CONFIG.audience + "/plans/plan-1"

        async def download(item, directory, index, *, cap):
            assert item == attachment and cap >= len(content)
            path = directory / "notes.txt"
            path.write_bytes(content)
            downloads.append(path)
            return path, len(content)

        monkeypatch.setattr(hosted_files, "download_attachment", download)

        def inventory():
            return (
                [
                    {
                        "ref": "hash:abcdefghijkl",
                        "name": "notes.txt",
                        "filename": "notes.txt",
                        "mimetype": "text/plain",
                        "size": len(content),
                    }
                ]
                if finalized
                else []
            )

        def override(request):
            nonlocal declarations, finalized
            path = request.url.path
            if path.endswith("/contract"):
                return httpx.Response(
                    200,
                    json={
                        "contract_version": CONTRACT_VERSION_MAX,
                        "tool": "organize",
                        "current_date": "2026-09-05",
                        "timezone": "UTC",
                        "personal_page": {},
                        "proposal_schema": {
                            "type": "object",
                            "additionalProperties": False,
                        },
                        "permissions": {},
                        "required_file_refs": [item["ref"] for item in inventory()],
                        "file_checklist": [],
                        "guidance_requirements": {},
                        "uploads_supported": True,
                        "workflow_rules": [],
                        "reference_rules": [],
                        "payload_sizes": {},
                        "limits": {
                            "max_files": 20,
                            "max_file_bytes": 1024,
                            "max_total_file_bytes": 1024,
                        },
                        "upload_inventory": {
                            "status": "finalized",
                            "authoritative": True,
                            "count": len(inventory()),
                            "files": inventory(),
                        },
                        "submission_format": {
                            "method": "POST",
                            "url": plan_url + "/submit",
                            "contract_version": CONTRACT_VERSION_MAX,
                            "body": {
                                "contract_version": CONTRACT_VERSION_MAX,
                                "proposal": {},
                            },
                            "rule": "Review first.",
                        },
                    },
                )
            if path.endswith("/uploads"):
                declarations = json.loads(request.content)["files"]
                assert declarations == [
                    {
                        "filename": "notes.txt",
                        "content_type": "text/plain",
                        "size": len(content),
                    }
                ]
                return httpx.Response(
                    200,
                    json={
                        "plan_id": "plan-1",
                        "upload_batch_id": batch_id,
                        "uploads": [
                            {
                                "index": 0,
                                "filename": "notes.txt",
                                "session_url": session_url,
                                "chunk_size": MIN_UPLOAD_CHUNK_BYTES,
                            }
                        ],
                    },
                )
            if path.endswith("/uploads/finalize"):
                assert json.loads(request.content) == {"upload_batch_id": batch_id}
                assert not storage_failure
                finalized = True
                return httpx.Response(
                    200,
                    json={
                        "id": "plan-1",
                        "status": "draft",
                        "tool": "organize",
                        "name": "Attachment plan",
                        "instructions": "Organize the notes.",
                        "files": inventory(),
                        "uploads_pending": False,
                        "contract_version": CONTRACT_VERSION_MAX,
                        "upload_batch_id": batch_id,
                        "preview_url": CONFIG.issuer + "/tools/api-plan/abcdefghijkl",
                        "review_url": CONFIG.issuer + "/tools/reports/abcdefghijkl",
                        "status_url": plan_url,
                        "submit_url": plan_url + "/submit",
                        "contract_url": plan_url + "/contract",
                    },
                )

        async def storage(request):
            data = await request.aread()
            storage_requests.append((request, data))
            assert str(request.url) == session_url
            assert (
                "authorization" not in request.headers
                and "cookie" not in request.headers
            )
            assert hosted.USER_TOKEN_HEADER not in request.headers
            if storage_failure:
                return httpx.Response(403)
            if request.headers["content-range"].startswith("bytes */"):
                return httpx.Response(308)
            assert data == content
            return httpx.Response(200)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(storage)
        ) as storage_client:
            app = hosted.create_app(
                CONFIG,
                adapter_factory=lambda token: _adapter(
                    token, requests, revoked, override, storage=storage_client
                ),
            )
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
                ) as client:
                    response = await _rpc(
                        client,
                        "tools/call",
                        params={
                            "name": "upload_files",
                            "arguments": {"plan_id": "plan-1", "files": [attachment]},
                        },
                    )
                    result = response.json()["result"]
                    assert result["isError"] is storage_failure, response.text
                    if not storage_failure:
                        value = result["structuredContent"]
                        assert (
                            value["plan"]["status"] == "draft"
                            and value["plan"]["uploads_pending"] is False
                        )
                        assert value["upload_inventory"] == inventory()
                        assert (
                            value["context"]["contract"]["upload_inventory"]["files"]
                            == inventory()
                        )
                    else:
                        assert declarations and not finalized
                    assert (
                        TOKEN_A not in response.text
                        and session_url not in response.text
                        and attachment["download_url"] not in response.text
                    )
        assert (
            storage_requests
            and downloads
            and all(not path.exists() for path in downloads)
        )
        paths = [path for _, path in requests]
        assert paths.count("/api/v1/plans/plan-1/uploads") == 1
        assert paths.count("/api/v1/plans/plan-1/uploads/finalize") == (
            0 if storage_failure else 1
        )
        assert not any(path.endswith("/submit") for path in paths)

    asyncio.run(scenario())


def _actor(token):
    name = "Alice" if token == TOKEN_A else "Bob"
    return {
        "user": {
            "name": name,
            "hash": name.lower() * 3,
            "timezone": "UTC",
            "personal_page": {
                "kind": "page",
                "hash": "hash:abcdefghijkl",
                "name": "Personal",
                "url": "/pages/personal",
                "can_view": True,
                "can_edit": True,
            },
        },
        "credential": {
            "active": True,
            "display_prefix": None,
            "issued_at": "2026-09-05T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "generation": 1,
        },
        "capabilities": {"ask": True, "create": True, "organize": True},
    }


def _catalog(token):
    entries = (
        [
            {
                "name": "get_entity",
                "description": "Read a permitted entity.",
                "input_schema": {
                    "type": "object",
                    "properties": {"hash": {"type": "string"}},
                    "required": ["hash"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "result_paths": {},
            }
        ]
        if token == TOKEN_A
        else []
    )
    return {
        "view": "full",
        "tools": entries,
        "selected_count": len(entries),
        "reference_format": "hash:<12-character-hash>",
        "execution_envelope": {
            "success": {"result": "<value matching the selected output_schema>"},
            "failure": {
                "error": {"code": "tool_error", "message": "<message>"},
                "request_id": "<request id>",
            },
        },
    }


@asynccontextmanager
async def _adapter(token, requests, revoked, override=None, proof=None, storage=None):
    async def upstream(request):
        requests.append((token, request.url.path))
        if override is not None:
            response = override(request)
            if response is not None:
                return response
        if token in revoked:
            return httpx.Response(
                401, json={"error": {"code": "unauthorized", "message": "Revoked"}}
            )
        path = request.url.path
        if path == "/api/v1":
            value = {
                "version": "v1",
                **{
                    key: "https://example.com" + suffix
                    for key, suffix in {
                        "base_url": "/api/v1",
                        "openapi_url": "/api/v1/openapi.json",
                        "actor_url": "/api/v1/me",
                        "tools_url": "/api/v1/tools",
                        "plans_url": "/api/v1/plans",
                        "client_skill_url": "/api/v1/client-skill.md",
                    }.items()
                },
            }
        elif path == "/api/v1/me":
            value = _actor(token)
        elif path == "/api/v1/tools":
            value = _catalog(token)
        elif path.endswith("/tools/get_entity"):
            value = {"result": {"name": "Alice's record"}}
        else:
            return httpx.Response(
                404, json={"error": {"code": "not_found", "message": "Missing"}}
            )
        await asyncio.sleep(0)
        return httpx.Response(200, json=value)

    config = ConnectionConfig(normalize_site_url(CONFIG.issuer), api_key=token)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        client.workload_token = proof
        rest = hosted.RequestREST(config, client=client, storage_client=storage)
        adapter = hosted.HostedAdapter(config, rest=rest)
        try:
            yield adapter
        finally:
            await adapter.aclose()


async def _rpc(
    client, method, *, token=TOKEN_A, params=None, request_id=1, version="2025-03-26"
):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
    }
    if version == "2026-07-28":
        payload["params"] = {**(params or {}), "_meta": MODERN_META}
        headers["Mcp-Method"] = method
        name = (params or {}).get("name")
        if isinstance(name, str):
            headers["Mcp-Name"] = encode_header_value(name)
    if token:
        headers["Authorization"] = "Bearer " + token
    return await client.post("/mcp", json=payload, headers=headers)


# @matrix mcp-remote : configuration discovery bounds
def test_hosted_configuration_and_public_discovery_are_exact():
    for issuer, resource in (
        ("http://example.com", CONFIG.resource),
        ("https://example.com/", CONFIG.resource),
        (CONFIG.issuer, CONFIG.resource + "/"),
        (CONFIG.issuer, "https://example.com/mcp"),
    ):
        with pytest.raises(ConfigurationError):
            hosted.HostedConfig(issuer, resource)

    async def scenario():
        app = hosted.create_app(CONFIG)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                response = await client.get("/.well-known/oauth-protected-resource")
                assert response.json()["resource"] == CONFIG.resource
                assert response.json()["authorization_servers"] == [CONFIG.issuer]
                assert (await client.get("/health")).json() == {"status": "ok"}
                response = await _rpc(client, "initialize", token=None)
                assert response.status_code == 401
                assert response.headers["www-authenticate"] == CONFIG.challenge
                assert (
                    await _rpc(client, "ping", token="lgn_existing-key")
                ).status_code == 401

    asyncio.run(scenario())


# @matrix mcp-remote : catalog isolation parity discovery bounds
@pytest.mark.parametrize("version", ["2025-03-26", "2026-07-28"])
def test_remote_catalog_and_calls_reuse_adapter_behavior_and_isolate_users(version):
    async def scenario():
        requests, revoked = [], set()
        app = hosted.create_app(
            CONFIG, adapter_factory=lambda token: _adapter(token, requests, revoked)
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                initialized = await _rpc(
                    client,
                    "initialize",
                    params={
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                assert initialized.status_code == 200, initialized.text
                assert initialized.json()["result"]["protocolVersion"] == "2025-03-26"
                a, b = await asyncio.gather(
                    _rpc(client, "tools/list", version=version),
                    _rpc(client, "tools/list", token=TOKEN_B, version=version),
                )
                assert a.status_code == b.status_code == 200
                alice = {item["name"]: item for item in a.json()["result"]["tools"]}
                bob = {item["name"]: item for item in b.json()["result"]["tools"]}
                assert "get_entity" in alice and "get_entity" not in bob
                assert "upload_files" in alice and "upload_local_files" not in alice
                upload = alice["upload_files"]
                assert upload["_meta"]["openai/fileParams"] == ["files"]
                assert set(
                    upload["inputSchema"]["properties"]["files"]["items"]["properties"]
                ) == {"download_url", "file_id", "mime_type", "file_name"}
                for item in alice.values():
                    assert (
                        item["securitySchemes"]
                        == item["_meta"]["securitySchemes"]
                        == [{"type": "oauth2", "scopes": ["mcp:use"]}]
                    )
                a, b = await asyncio.gather(
                    _rpc(
                        client,
                        "tools/call",
                        params={"name": "get_actor", "arguments": {}},
                        version=version,
                    ),
                    _rpc(
                        client,
                        "tools/call",
                        token=TOKEN_B,
                        params={"name": "get_actor", "arguments": {}},
                        version=version,
                    ),
                )
                assert a.json()["result"]["structuredContent"] == _actor(TOKEN_A)
                assert b.json()["result"]["structuredContent"] == _actor(TOKEN_B)
                async with _adapter(TOKEN_A, requests, revoked) as shared:
                    local = LagniappeAdapter(shared.config, rest=shared.rest)
                    await local.initialize()
                    expected = await local.execute("get_actor", {})
                    assert a.json()["result"]["structuredContent"] == expected.value
                denied = await _rpc(
                    client,
                    "tools/call",
                    token=TOKEN_B,
                    params={
                        "name": "get_entity",
                        "arguments": {"plan_id": "test", "hash": "hash:abcdefghijkl"},
                    },
                    version=version,
                )
                assert denied.json()["error"]["code"] == -32602
                bad_path = await _rpc(
                    client,
                    "tools/call",
                    params={
                        "name": "upload_files",
                        "arguments": {
                            "plan_id": "test",
                            "files": [{"path": "/etc/passwd"}],
                        },
                    },
                    version=version,
                )
                assert bad_path.json()["result"]["isError"]
                rendered = a.text + b.text
                assert TOKEN_A not in rendered and TOKEN_B not in rendered
                expected_calls = [
                    (TOKEN_A, "/api/v1/me"),
                    (TOKEN_A, "/api/v1"),
                    (TOKEN_A, "/api/v1/tools"),
                ]
                assert sorted(requests[-3:]) == sorted(expected_calls)

    asyncio.run(scenario())


# @matrix mcp-remote : authentication bounds privacy
@pytest.mark.parametrize("version", ["2025-03-26", "2026-07-28"])
def test_http_errors_are_private_and_mid_request_expiry_requests_reconnect(
    version, caplog
):
    async def scenario():
        requests, revoked = [], set()
        fail_catalog = False

        def override(request):
            if fail_catalog and request.url.path == "/api/v1/tools":
                return httpx.Response(
                    401, json={"error": {"code": "unauthorized", "message": "expired"}}
                )

        app = hosted.create_app(
            CONFIG,
            adapter_factory=lambda token: _adapter(token, requests, revoked, override),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                secret = "https://files.example.com/file?temporary=private"
                for request_id in (
                    secret,
                    "x" * 1000,
                    {"secret": secret},
                    True,
                    None,
                    1.5,
                ):
                    response = await _rpc(
                        client, "ping", request_id=request_id, version=version
                    )
                    assert response.status_code == 400
                    assert response.json() == {"error": "invalid_request"}
                headers = {
                    "Authorization": "bearer " + TOKEN_A,
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": version,
                    "Content-Type": "application/json",
                }
                for payload in (
                    '{"jsonrpc":"2.0","method":"ping","id":1,"id":2}',
                    json.dumps({"jsonrpc": secret, "method": "ping", "id": 1}),
                    json.dumps({"jsonrpc": "2.0", "method": [secret], "id": 1}),
                    '{"jsonrpc":"2.0","method":"ping","id":1,"params":{"value":NaN}}',
                ):
                    response = await client.post(
                        "/mcp", content=payload, headers=headers
                    )
                    assert response.status_code == 400
                    assert response.json() == {"error": "invalid_request"}
                valid_method = "server/discover" if version == "2026-07-28" else "ping"
                valid_payload = {"jsonrpc": "2.0", "method": valid_method, "id": 1}
                if version == "2026-07-28":
                    valid_payload["params"] = {"_meta": MODERN_META}
                    headers["Mcp-Method"] = valid_method
                valid = await client.post("/mcp", json=valid_payload, headers=headers)
                assert valid.status_code == 200
                oversized = await client.post(
                    "/mcp",
                    content=b" " * (hosted.MAX_REQUEST_FRAME_BYTES + 1),
                    headers=headers,
                )
                assert oversized.status_code == 413
                malformed = await _rpc(
                    client, "tools/call", params={"name": [secret]}, version=version
                )
                assert "error" in malformed.json()
                unknown = await _rpc(client, secret, version=version)
                assert unknown.json()["error"]["code"] == -32601
                assert secret not in malformed.text + unknown.text

                fail_catalog = True
                listing = await _rpc(client, "tools/list", version=version)
                assert listing.status_code == 401
                assert 'error="invalid_token"' in listing.headers["www-authenticate"]
                call = await _rpc(
                    client,
                    "tools/call",
                    params={"name": "get_actor", "arguments": {}},
                    version=version,
                )
                assert call.status_code == 401
                result = call.json()["result"]
                assert result["isError"]
                assert result["_meta"]["mcp/www_authenticate"] == [
                    CONFIG.challenge + ', error="invalid_token"'
                ]
                assert secret not in listing.text + call.text
                assert call.headers["cache-control"] == "no-store"
                assert "x-request-id" in call.headers

    with caplog.at_level("INFO", logger=hosted.LOGGER.name):
        asyncio.run(scenario())
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == hosted.LOGGER.name
    ]
    assert events[-1]["status"] == 401 and events[-1]["method"] == "tools/call"
    assert events[-1]["api_json_calls"] == 3
    assert all(
        set(event)
        == {
            "event",
            "correlation_id",
            "duration_ms",
            "revision",
            "status",
            "method",
            "tool",
            "api_json_calls",
        }
        for event in events
    )
    assert "temporary=private" not in json.dumps(events) and TOKEN_A not in json.dumps(
        events
    )


# @matrix mcp-remote : privacy token-separation
def test_hosted_catalog_and_error_results_cannot_reflect_workload_identity(monkeypatch):
    proof = "google.identity.proof"

    async def scenario():
        requests, revoked = [], set()

        def override(request):
            if request.url.path == "/api/v1/tools":
                catalog = _catalog(TOKEN_A)
                catalog["tools"][0]["description"] = proof
                return httpx.Response(200, json=catalog)

        app = hosted.create_app(
            CONFIG,
            adapter_factory=lambda token: _adapter(
                token, requests, revoked, override, proof
            ),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                response = await _rpc(client, "tools/list")
                assert response.json()["error"]["code"] == -32603
                assert proof not in response.text

        async def fail(self, name, arguments):
            raise AdapterError("upstream_error", proof)

        monkeypatch.setattr(hosted.HostedAdapter, "execute", fail)
        app = hosted.create_app(
            CONFIG,
            adapter_factory=lambda token: _adapter(
                token, requests, revoked, proof=proof
            ),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                response = await _rpc(
                    client, "tools/call", params={"name": "get_actor", "arguments": {}}
                )
                assert response.json()["result"]["isError"]
                assert proof not in response.text

    asyncio.run(scenario())


# @matrix mcp-remote : authentication isolation bounds
def test_http_authentication_preflights_every_request_and_reconnects_on_revocation():
    async def scenario():
        requests, revoked = [], set()
        app = hosted.create_app(
            CONFIG, adapter_factory=lambda token: _adapter(token, requests, revoked)
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                assert (await _rpc(client, "ping")).status_code == 200
                assert requests == [(TOKEN_A, "/api/v1/me")]
                revoked.add(TOKEN_A)
                response = await _rpc(client, "ping")
                assert response.status_code == 401
                assert 'error="invalid_token"' in response.headers["www-authenticate"]
                assert len(requests) == 2
                assert (await _rpc(client, "ping", token=TOKEN_B)).status_code == 200
                response = await _rpc(
                    client, "ping", token=TOKEN_B, request_id="x" * 1000
                )
                assert response.status_code == 400
                for method in ("GET", "DELETE"):
                    response = await client.request(
                        method,
                        "/mcp",
                        headers={
                            "Authorization": "Bearer " + TOKEN_B,
                            "Accept": "text/event-stream",
                        },
                    )
                    assert response.status_code == 405
                    assert response.headers["allow"] == "POST"
                    assert response.headers["cache-control"] == "no-store"
                response = await client.get(
                    "/mcp", headers={"Authorization": "Bearer " + TOKEN_A}
                )
                assert response.status_code == 401
                assert requests[-1] == (TOKEN_A, "/api/v1/me")

    asyncio.run(scenario())


# @matrix mcp-remote : service-identity token-separation
def test_workload_identity_uses_only_metadata_and_envelope_uses_fixed_api_origin(
    monkeypatch,
):
    async def scenario():
        payload = (
            base64.urlsafe_b64encode(
                json.dumps({"exp": int(time.time()) + 3600}).encode()
            )
            .decode()
            .rstrip("=")
        )
        proof = "header." + payload + ".signature"
        calls = []
        original_client = httpx.AsyncClient

        def metadata(request):
            calls.append(request)
            assert request.url.host == "metadata.google.internal"
            assert request.url.params["audience"] == CONFIG.audience
            assert request.headers["Metadata-Flavor"] == "Google"
            assert (
                "authorization" not in request.headers
                and "cookie" not in request.headers
            )
            return httpx.Response(
                200, text=proof, headers={"Metadata-Flavor": "Google"}
            )

        monkeypatch.setattr(
            hosted.httpx,
            "AsyncClient",
            lambda **kwargs: original_client(
                transport=httpx.MockTransport(metadata), **kwargs
            ),
        )
        identity = hosted.WorkloadIdentity(CONFIG.audience)
        assert await identity.token() == await identity.token() == proof
        assert len(calls) == 1
        monkeypatch.setattr(hosted.httpx, "AsyncClient", original_client)
        seen = []
        async with hosted.EnvelopeClient(
            ConnectionConfig(normalize_site_url(CONFIG.issuer), api_key=TOKEN_A),
            identity,
            transport=httpx.MockTransport(
                lambda request: seen.append(request) or httpx.Response(200, json={})
            ),
        ) as client:
            request = httpx.Request(
                "GET",
                CONFIG.audience + "/me",
                headers={"Authorization": "Bearer " + TOKEN_A},
            )
            await client.send(request, auth=None)
            assert seen[0].headers["Authorization"] == "Bearer " + proof
            assert seen[0].headers[hosted.USER_TOKEN_HEADER] == TOKEN_A
            with pytest.raises(Exception):
                await client.send(
                    httpx.Request("GET", "https://attacker.test/api/v1/me"), auth=None
                )
            assert len(seen) == 1

    asyncio.run(scenario())
