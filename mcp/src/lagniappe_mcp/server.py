"""Stateless Cloud Run MCP resource using request-scoped existing adapters."""

import asyncio
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit
import uuid

import httpx
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    ListToolsResult,
    Tool,
    jsonrpc_message_adapter,
)
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lagniappe_mcp import __version__
from lagniappe_mcp.adapter import LagniappeAdapter, _reject_private_model_data
from lagniappe_mcp.configuration import ConnectionConfig
from lagniappe_mcp.errors import AdapterError, ConfigurationError
from lagniappe_mcp.files import _preflight_contract, _preflight_requested_count
from .attachments import spool_attachments
from . import terminal_files
from lagniappe_mcp.schema import validate_value
from lagniappe_mcp.limits import (
    MAX_REQUEST_FRAME_BYTES,
    MAX_REQUEST_ID_BYTES,
    MCP_INSTRUCTIONS,
    UPLOAD_OPERATION_TIMEOUT_SECONDS,
)
from lagniappe_mcp.rest import (
    RESTClient,
    _finite_json_float,
    _reject_json_constant,
    _unique_json_object,
)
from lagniappe_mcp.presentation import _error_result, _success_result, _REQUEST_ID_TOKEN
from lagniappe_mcp.url_security import normalize_site_url, validate_api_url


LOGGER = logging.getLogger("lagniappe_mcp.hosted")
USER_TOKEN_HEADER = "X-Lagniappe-MCP-Token"
_ACCESS_TOKEN = re.compile(r"lgmo_a_[A-Za-z0-9_-]{43}")
_SCHEMES = [{"type": "oauth2", "scopes": []}]
_METADATA_PATH = "/.well-known/oauth-protected-resource"
_LOG_METHODS = {
    "initialize",
    "ping",
    "tools/list",
    "tools/call",
    "server/discover",
    "notifications/initialized",
    "notifications/cancelled",
}


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_hosted_configuration_and_public_discovery_are_exact
# @matrix mcp-remote : configuration discovery
@dataclass(frozen=True)
class HostedConfig:
    issuer: str
    resource: str

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::HostedConfig
    def __post_init__(self):
        for value in (self.issuer, self.resource):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.netloc != parsed.hostname
                or parsed.query
                or parsed.fragment
                or "?" in value
                or "#" in value
                or "\\" in value
                or any(ord(char) <= 32 for char in value)
            ):
                raise ConfigurationError(
                    "invalid_hosted_config",
                    "Hosted MCP requires exact canonical HTTPS URLs.",
                )
        if (
            urlsplit(self.issuer).path
            or urlsplit(self.resource).path != "/mcp"
            or self.origin == self.issuer
        ):
            raise ConfigurationError(
                "invalid_hosted_config",
                "Hosted MCP requires separate issuer and /mcp origins.",
            )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::HostedConfig
    @property
    def origin(self):
        return self.resource.removesuffix("/mcp")

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::HostedConfig
    @property
    def audience(self):
        return self.issuer + "/api/v1"

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::HostedConfig
    @property
    def challenge(self):
        return (
            f'Bearer resource_metadata="{self.origin}{_METADATA_PATH}"'
        )


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_workload_identity_uses_only_metadata_and_envelope_uses_fixed_api_origin
# @matrix mcp-remote : service-identity token-separation
class WorkloadIdentity:
    """Cache only this service's short-lived Google identity, never a user token."""

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::WorkloadIdentity
    def __init__(self, audience):
        self.audience = audience
        self._token = None
        self._until = 0
        self._lock = asyncio.Lock()

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::WorkloadIdentity
    async def token(self):
        async with self._lock:
            if self._token and time.monotonic() < self._until:
                return self._token
            try:
                async with httpx.AsyncClient(
                    trust_env=False, timeout=5, follow_redirects=False
                ) as client:
                    response = await client.get(
                        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity",
                        params={"audience": self.audience, "format": "full"},
                        headers={"Metadata-Flavor": "Google"},
                    )
                if (
                    response.status_code != 200
                    or len(response.content) > 8192
                    or response.headers.get("Metadata-Flavor") != "Google"
                ):
                    raise ValueError()
                token = response.text
                if not re.fullmatch(
                    r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token
                ):
                    raise ValueError()
                payload = json.loads(
                    base64.urlsafe_b64decode(token.split(".")[1] + "==")
                )
                # This decode only bounds cache lifetime. The main application
                # verifies Google's signature and every identity claim.
                seconds = min(300, int(payload["exp"]) - time.time() - 60)
                if seconds <= 0:
                    raise ValueError()
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise AdapterError(
                    "service_identity_unavailable",
                    "The remote connection is temporarily unavailable.",
                    retryable=True,
                    status=503,
                ) from None
            self._token, self._until = token, time.monotonic() + seconds
            return token


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_workload_identity_uses_only_metadata_and_envelope_uses_fixed_api_origin
# @matrix mcp-remote : service-identity token-separation
class EnvelopeClient(httpx.AsyncClient):
    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::EnvelopeClient
    def __init__(self, config, identity, **kwargs):
        super().__init__(trust_env=False, follow_redirects=False, **kwargs)
        self.config = config
        self.identity = identity
        self.workload_token = None

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::EnvelopeClient
    async def send(self, request, **kwargs):
        validate_api_url(
            self.config.authority,
            str(request.url),
            allow_contract_query=request.method == "GET",
        )
        self.workload_token = await self.identity.token()
        request.headers["Authorization"] = "Bearer " + self.workload_token
        request.headers[USER_TOKEN_HEADER] = self.config.api_key
        return await super().send(request, **kwargs)


# @testable false
# @covered-by mcp/src/lagniappe_mcp/server.py::create_app
class RequestREST(RESTClient):
    """Reuse the actor preflight within this HTTP request only."""

    actor_preflight = None
    api_json_calls = 0

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::RequestREST
    async def request_json(self, method, target, **kwargs):
        if method == "GET" and target == "me" and self.actor_preflight is not None:
            return deepcopy(self.actor_preflight), None
        self.api_json_calls += 1
        return await super().request_json(method, target, **kwargs)


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_remote_catalog_and_calls_reuse_adapter_behavior_and_isolate_users
# @tests tests_unit/test_033c_mcp_server.py::test_hosted_catalog_and_error_results_cannot_reflect_workload_identity
# @tests tests_unit/test_033c_mcp_server.py::test_remote_attachment_uses_shared_upload_and_preserves_pending_failure
# @matrix mcp-remote : catalog isolation parity privacy token-separation
# @matrix mcp-upload : remote cleanup partial-failure upload-all finalize-once
class HostedAdapter(LagniappeAdapter):
    _remote_initialized = False

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::HostedAdapter
    async def initialize(self):
        if self._remote_initialized:
            return
        await super().initialize()
        proof = getattr(self.rest.client, "workload_token", None)
        if proof:
            _reject_private_model_data(self.actor, bearer=proof)
            _reject_private_model_data(
                [
                    tool.as_mcp_tool().model_dump(by_alias=True, exclude_none=True)
                    for tool in self.tools.values()
                ],
                bearer=proof,
            )
        local = self.tools.pop("upload_local_files")
        schema = deepcopy(local.input_schema)
        schema["properties"]["files"]["items"] = {
            "type": "object",
            "required": ["download_url", "file_id"],
            "properties": {
                "download_url": {"type": "string", "minLength": 1, "maxLength": 8192},
                "file_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "file_name": {"type": "string", "maxLength": 1024},
                "mime_type": {"type": "string", "maxLength": 256},
            },
            "additionalProperties": False,
        }
        self.tools["upload_files"] = replace(
            local,
            name="upload_files",
            input_schema=schema,
            description="Upload files attached to this ChatGPT conversation into the existing Organize Plan, then finalize them. Reuse plan_id. Files are prepared for browser review and never applied automatically. If an attachment link expires, ask the user to reattach it.",
        )
        self.tools.update(
            {tool.name: tool for tool in terminal_files.tool_definitions(local)}
        )
        self._remote_initialized = True

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/terminal_files.py::prepare_uploads
    # @covered-by mcp/src/lagniappe_mcp/terminal_files.py::finalize_uploads
    async def execute(self, name, arguments):
        if name not in {"prepare_file_uploads", "finalize_file_uploads"}:
            return await super().execute(name, arguments)
        definition = self.tools[name]
        validate_value(definition.input_schema, arguments, phase="input")
        operation = (
            terminal_files.prepare_uploads
            if name == "prepare_file_uploads"
            else terminal_files.finalize_uploads
        )
        result = await operation(self, arguments)
        if name == "prepare_file_uploads":
            terminal_files.validate_manifest(result.value, bearer=self.config.api_key)
        else:
            _reject_private_model_data(result.value, bearer=self.config.api_key)
        validate_value(definition.output_schema, result.value, phase="output")
        self._enforce_result_limits(result)
        return result

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::HostedAdapter
    async def _upload_files(self, arguments):
        try:
            async with asyncio.timeout(UPLOAD_OPERATION_TIMEOUT_SECONDS):
                contract = await self._load_contract(arguments["plan_id"])
                _preflight_requested_count(contract, arguments["files"])
                max_file, max_total = _preflight_contract(contract, ())
                async with spool_attachments(
                    arguments["files"],
                    max_file_bytes=max_file,
                    max_total_bytes=max_total,
                ) as files:
                    return await super()._upload_files(
                        {"plan_id": arguments["plan_id"], "files": files}
                    )
        except TimeoutError:
            raise AdapterError(
                "upload_timeout",
                "Attachment transfer exceeded the total upload deadline. Check the existing Plan before retrying.",
            ) from None


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_hosted_configuration_and_public_discovery_are_exact
# @tests tests_unit/test_033c_mcp_server.py::test_remote_catalog_and_calls_reuse_adapter_behavior_and_isolate_users
# @tests tests_unit/test_033c_mcp_server.py::test_http_authentication_preflights_every_request_and_reconnects_on_revocation
# @tests tests_unit/test_033c_mcp_server.py::test_http_errors_are_private_and_mid_request_expiry_requests_reconnect
# @tests tests_unit/test_033c_mcp_server.py::test_hosted_catalog_and_error_results_cannot_reflect_workload_identity
# @matrix mcp-remote : discovery authentication isolation parity bounds privacy token-separation
def create_app(config, *, adapter_factory=None):
    identity = WorkloadIdentity(config.audience)

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    @asynccontextmanager
    async def request_adapter(token):
        connection = ConnectionConfig(normalize_site_url(config.issuer), api_key=token)
        async with EnvelopeClient(connection, identity) as client:
            rest = RequestREST(connection, client=client)
            adapter = HostedAdapter(connection, rest=rest)
            try:
                yield adapter
            finally:
                await adapter.aclose()

    factory = adapter_factory or request_adapter

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    async def list_tools(ctx, _params):
        adapter = ctx.request.state.mcp_adapter
        await adapter.initialize()
        tools = []
        for definition in adapter.tools.values():
            tool = definition.as_mcp_tool(ctx.protocol_version)
            values = tool.model_dump(by_alias=True, exclude_none=True)
            values["_meta"] = {**values.get("_meta", {}), "securitySchemes": _SCHEMES}
            if definition.name == "upload_files":
                values["_meta"]["openai/fileParams"] = ["files"]
            tools.append(Tool(**values))
        return ListToolsResult(tools=tools, result_type="complete")

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    async def call_tool(ctx, params):
        adapter = ctx.request.state.mcp_adapter
        try:
            await adapter.initialize()
            definition = adapter.tools.get(params.name)
            if definition is None:
                raise MCPError(
                    code=INVALID_PARAMS, message="Unknown Lagniappe MCP tool."
                )
            ctx.request.state.mcp_tool = params.name
            result = await adapter.execute(params.name, params.arguments)
            client = adapter.rest.client
            proof = getattr(client, "workload_token", None)
            if proof:
                if params.name == "prepare_file_uploads":
                    terminal_files.validate_manifest(result.value, bearer=proof)
                else:
                    _reject_private_model_data(result.value, bearer=proof)
                _reject_private_model_data(
                    tuple(item.data for item in result.media), bearer=proof
                )
            if params.name == "upload_files":
                for item in (params.arguments or {}).get("files", []):
                    _reject_private_model_data(
                        result.value, bearer=item["download_url"]
                    )
            return _success_result(
                result,
                request_id=ctx.request_id or 0,
                server_info=server.server_info_stamp
                if ctx.protocol_version == "2026-07-28"
                else None,
                wrap_result=definition.requires_result_wrapper(ctx.protocol_version),
            )
        except AdapterError as error:
            if error.status == 401:
                ctx.request.state.mcp_auth_failed = True
                result = _error_result(
                    AdapterError(
                        "authentication_required", "Reconnect Lagniappe to continue."
                    )
                )
                result.meta = {
                    "mcp/www_authenticate": [
                        config.challenge + ', error="invalid_token"'
                    ]
                }
                return result
            try:
                proof = getattr(adapter.rest.client, "workload_token", None)
                if proof:
                    _reject_private_model_data(error.render(), bearer=proof)
                if params.name == "upload_files":
                    for item in (params.arguments or {}).get("files", []):
                        url = (
                            item.get("download_url") if isinstance(item, dict) else None
                        )
                        if isinstance(url, str) and url:
                            _reject_private_model_data(error.render(), bearer=url)
            except AdapterError:
                error = AdapterError(
                    "adapter_failure",
                    "The remote adapter could not complete this call.",
                )
            return _error_result(error, request_id=ctx.request_id or 0)
        except MCPError:
            raise
        except Exception:
            return _error_result(
                AdapterError(
                    "adapter_failure",
                    "The remote adapter could not complete this call.",
                )
            )

    server = Server(
        "lagniappe",
        version=__version__,
        title="Lagniappe",
        instructions=MCP_INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    server.middleware.clear()

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    async def chatgpt_metadata(ctx, call_next):
        # SDK 2.1.1's version serializer strips unknown Tool fields. Its public
        # middleware runs after that serializer, so mirror the standard _meta
        # declaration here for ChatGPT clients that inspect the top-level field.
        try:
            result = await call_next(ctx)
        except AdapterError as error:
            if error.status == 401:
                ctx.request.state.mcp_auth_failed = True
                raise MCPError(
                    code=-32001, message="Reconnect Lagniappe to continue."
                ) from None
            raise MCPError(
                code=INTERNAL_ERROR,
                message="The remote adapter is temporarily unavailable.",
            ) from None
        except ValidationError:
            raise MCPError(
                code=INVALID_PARAMS, message="Invalid request parameters."
            ) from None
        except MCPError as error:
            message = (
                "Unknown MCP method."
                if error.code == METHOD_NOT_FOUND
                else "The MCP request could not be completed."
            )
            raise MCPError(code=error.code, message=message) from None
        except Exception:
            raise MCPError(
                code=INTERNAL_ERROR,
                message="The remote adapter could not complete this request.",
            ) from None
        if ctx.method == "tools/list":
            for tool in result["tools"]:
                tool["securitySchemes"] = deepcopy(_SCHEMES)
        return result

    server.middleware.append(chatgpt_metadata)
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(config.origin).netloc],
            allowed_origins=[config.origin, "https://chatgpt.com"],
        ),
    )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    async def metadata(_request):
        return JSONResponse(
            {
                "resource": config.resource,
                "authorization_servers": [config.issuer],
                "bearer_methods_supported": ["header"],
                "resource_name": "Lagniappe MCP",
            }
        )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    async def health(_request):
        return JSONResponse({"status": "ok"})

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
    class ProtectedMCP:
        # @testable false
        # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
        async def __call__(self, scope, receive, send):
            started, correlation = time.monotonic(), uuid.uuid4().hex
            request = Request(scope, receive)
            authorization = request.headers.get("authorization", "").split(" ")
            token = (
                authorization[1]
                if len(authorization) == 2 and authorization[0].casefold() == "bearer"
                else ""
            )
            headers = {"Cache-Control": "no-store", "X-Request-ID": correlation}
            status, method, adapter = 500, "other", None

            # @testable false
            # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
            async def annotate(message):
                nonlocal status
                if message["type"] == "http.response.start":
                    message["headers"] = list(message.get("headers", [])) + [
                        (key.lower().encode(), value.encode())
                        for key, value in headers.items()
                    ]
                    if scope.get("state", {}).get("mcp_auth_failed"):
                        message["status"] = 401
                        message["headers"].append(
                            (
                                b"www-authenticate",
                                (config.challenge + ', error="invalid_token"').encode(),
                            )
                        )
                    status = message["status"]
                await send(message)

            try:
                if (
                    not _ACCESS_TOKEN.fullmatch(token)
                    or len(request.headers.getlist("authorization")) != 1
                ):
                    await JSONResponse(
                        {"error": "authentication_required"},
                        401,
                        headers={"WWW-Authenticate": config.challenge},
                    )(scope, receive, annotate)
                    return
                async with factory(token) as adapter:
                    # Even initialize, ping, GET, and notifications validate the
                    # live grant at the main API before the SDK can process them.
                    actor = await adapter._get_actor()
                    adapter.rest.actor_preflight = actor.value
                    scope.setdefault("state", {})["mcp_adapter"] = adapter
                    if request.method != "POST":
                        # This service sends complete JSON responses and has no
                        # resumable sessions or server-to-client event stream.
                        await JSONResponse(
                            {"error": "method_not_allowed"},
                            405,
                            headers={"Allow": "POST"},
                        )(scope, receive, annotate)
                        return
                    if request.method == "POST":
                        body = bytearray()
                        async with asyncio.timeout(30):
                            async for chunk in request.stream():
                                if len(chunk) > MAX_REQUEST_FRAME_BYTES - len(body):
                                    await JSONResponse(
                                        {"error": "request_too_large"}, 413
                                    )(scope, receive, annotate)
                                    return
                                body.extend(chunk)
                        try:
                            payload = json.loads(
                                body,
                                object_pairs_hook=_unique_json_object,
                                parse_constant=_reject_json_constant,
                                parse_float=_finite_json_float,
                            )
                            request_id = (
                                payload.get("id") if isinstance(payload, dict) else None
                            )
                            if not isinstance(payload, dict):
                                raise ValueError()
                            if "id" in payload and (
                                type(request_id) not in {str, int}
                                or isinstance(request_id, str)
                                and not _REQUEST_ID_TOKEN.fullmatch(request_id)
                                or len(
                                    json.dumps(request_id, ensure_ascii=False).encode()
                                )
                                > MAX_REQUEST_ID_BYTES
                            ):
                                raise ValueError()
                            # The SDK's raw-envelope validation includes input
                            # values in failures. Validate here so malformed
                            # frames get a fixed error without reflecting data.
                            jsonrpc_message_adapter.validate_python(
                                payload, by_name=False
                            )
                            method = payload.get("method", "other")
                            if method not in _LOG_METHODS:
                                method = "other"
                        except (ValueError, RecursionError):
                            await JSONResponse({"error": "invalid_request"}, 400)(
                                scope, receive, annotate
                            )
                            return
                        sent = False
                        original_receive = receive

                        # @testable false
                        # @covered-by mcp/src/lagniappe_mcp/server.py::create_app
                        async def replay():
                            nonlocal sent
                            if not sent:
                                sent = True
                                return {
                                    "type": "http.request",
                                    "body": bytes(body),
                                    "more_body": False,
                                }
                            return await original_receive()

                        receive = replay

                    await manager.handle_request(scope, receive, annotate)
            except AdapterError as error:
                if error.status == 401:
                    await JSONResponse(
                        {"error": "authentication_required"},
                        401,
                        headers={
                            "WWW-Authenticate": config.challenge
                            + ', error="invalid_token"'
                        },
                    )(scope, receive, annotate)
                else:
                    await JSONResponse({"error": "upstream_unavailable"}, 503)(
                        scope, receive, annotate
                    )
            except TimeoutError:
                await JSONResponse({"error": "request_timeout"}, 408)(
                    scope, receive, annotate
                )
            finally:
                LOGGER.info(
                    json.dumps(
                        {
                            "event": "remote_mcp_request",
                            "correlation_id": correlation,
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "revision": os.environ.get("K_REVISION", "local"),
                            "status": status,
                            "method": method,
                            "tool": scope.get("state", {}).get("mcp_tool"),
                            "api_json_calls": getattr(
                                getattr(adapter, "rest", None), "api_json_calls", 0
                            ),
                        }
                    )
                )

    return Starlette(
        routes=[
            Route("/health", health),
            Route(_METADATA_PATH, metadata),
            Route("/mcp", ProtectedMCP(), methods=["GET", "POST", "DELETE"]),
        ],
        lifespan=lifespan,
    )


# @testable infrastructure
def main():
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in ("httpx", "httpcore", "httpx2", "httpcore2", "mcp", "mcp.server"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    if os.environ.get("LAGNIAPPE_MCP_ENABLED", "false") != "true":
        # @testable false
        # @covered-by mcp/src/lagniappe_mcp/server.py::main
        async def unavailable(_request):
            return JSONResponse({"status": "unavailable"}, 503)

        app = Starlette(
            routes=[
                Route("/{path:path}", unavailable, methods=["GET", "POST", "DELETE"])
            ]
        )
    else:
        app = create_app(
            HostedConfig(
                issuer=os.environ["LAGNIAPPE_MCP_ISSUER"],
                resource=os.environ["LAGNIAPPE_MCP_RESOURCE"],
            )
        )
    uvicorn.run(
        app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False
    )


if __name__ == "__main__":
    main()
