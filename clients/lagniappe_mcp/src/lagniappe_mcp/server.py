"""Official low-level MCP server presentation over the typed adapter."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
import re
import sys
from typing import Any, AsyncIterator, BinaryIO

from anyio import to_thread
from mcp.server import Server, ServerRequestContext
from mcp.server import stdio as mcp_stdio
from mcp.shared.exceptions import MCPError
from mcp_types import (
    INVALID_REQUEST,
    INVALID_PARAMS,
    PARSE_ERROR,
    AudioContent,
    CallToolRequestParams,
    CallToolResult,
    ErrorData,
    ImageContent,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    RequestId,
    SERVER_INFO_META_KEY,
    TextContent,
)
from mcp.shared.message import SessionMessage

from . import __version__
from ._telemetry import classify_error, telemetry_scope
from .adapter import AdapterResult, LagniappeAdapter
from .configuration import ConnectionConfig
from .errors import AdapterError, TransportError
from .limits import (
    MAX_COMPLETE_FRAME_BYTES,
    MAX_REQUEST_FRAME_BYTES,
    MAX_REQUEST_ID_BYTES,
    MCP_INSTRUCTIONS,
)
from .schema import compact_json


_REQUEST_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
_STDIO_DRAIN_CHUNK_BYTES = 64 * 1024
_OVERSIZED_FRAME_SENTINEL = "{\n"


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_mcp_v2_results_use_direct_structured_values_and_complete_aliases
def _error_result(
    error: AdapterError,
    *,
    request_id: RequestId = 0,
    server_info: dict[str, Any] | None = None,
) -> CallToolResult:
    response = CallToolResult(
        content=[TextContent(type="text", text=error.render())],
        structured_content=None,
        is_error=True,
        result_type="complete",
    )
    _ensure_frame_limit(response, request_id=request_id, server_info=server_info)
    return response


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/server.py::_success_result
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/server.py::_error_result
def _ensure_frame_limit(
    response: CallToolResult,
    *,
    request_id: RequestId,
    server_info: dict[str, Any] | None,
) -> None:
    result = response.model_dump(by_alias=True, mode="json", exclude_none=True)
    if server_info is not None:
        result["_meta"] = {SERVER_INFO_META_KEY: server_info}
    frame = JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result)
    serialized = frame.model_dump_json(by_alias=True, exclude_unset=True).encode(
        "utf-8"
    )
    if len(serialized) + 1 > MAX_COMPLETE_FRAME_BYTES:
        raise TransportError(
            "result_too_large", "Complete MCP result exceeds the frame limit."
        )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_mcp_v2_results_use_direct_structured_values_and_complete_aliases
def _success_result(
    result: AdapterResult,
    *,
    request_id: RequestId = 0,
    server_info: dict[str, Any] | None = None,
) -> CallToolResult:
    content: list[Any] = [TextContent(type="text", text=compact_json(result.value))]
    for media in result.media:
        encoded = base64.b64encode(media.data).decode("ascii")
        if media.kind == "image":
            content.append(ImageContent(data=encoded, mime_type=media.mime_type))
        elif media.kind == "audio":
            content.append(AudioContent(data=encoded, mime_type=media.mime_type))
        else:
            raise TransportError(
                "invalid_media", "Adapter produced an unsupported content block."
            )
    response = CallToolResult(
        content=content,
        structured_content=result.value,
        is_error=False,
        result_type="complete",
    )
    _ensure_frame_limit(
        response,
        request_id=request_id,
        server_info=server_info,
    )
    return response


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_stdio_rejects_oversized_request_ids_without_reflecting_them
# @tests tests_unit/test_033_mcp_adapter.py::test_real_stdio_subprocess_rejects_oversized_frame_and_resumes
async def _bounded_stdio_requests(
    read_stream: Any, write_stream: Any
) -> AsyncIterator[Any]:
    """Reject unsafe request identities without reflecting them on stdout."""
    async for item in read_stream:
        if isinstance(item, Exception):
            await write_stream.send(
                SessionMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=None,
                        error=ErrorData(
                            code=PARSE_ERROR,
                            message="Invalid JSON-RPC message.",
                        ),
                    )
                )
            )
            continue
        if isinstance(item, SessionMessage) and isinstance(
            item.message, JSONRPCRequest
        ):
            request_id = item.message.id
            encoded_id = json.dumps(
                request_id,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            invalid_string = isinstance(request_id, str) and not (
                _REQUEST_ID_TOKEN.fullmatch(request_id)
            )
            if invalid_string or len(encoded_id) > MAX_REQUEST_ID_BYTES:
                await write_stream.send(
                    SessionMessage(
                        JSONRPCError(
                            jsonrpc="2.0",
                            id=None,
                            error=ErrorData(
                                code=INVALID_REQUEST,
                                message="Request id is outside the supported format.",
                            ),
                        )
                    )
                )
                continue
        yield item


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_bounded_raw_stdio_input_discards_oversized_frame_and_resumes
async def _bounded_stdin_lines(stream: BinaryIO) -> AsyncIterator[str]:
    """Yield UTF-8 JSONL frames without ever buffering an unbounded line."""
    while True:
        raw = await to_thread.run_sync(stream.readline, MAX_REQUEST_FRAME_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_REQUEST_FRAME_BYTES:
            while not raw.endswith(b"\n"):
                raw = await to_thread.run_sync(
                    stream.readline,
                    _STDIO_DRAIN_CHUNK_BYTES,
                )
                if not raw:
                    break
            # The SDK converts this constant, data-free sentinel into an
            # exception item.  ``_bounded_stdio_requests`` returns one generic
            # parse error and allows the next independent JSONL frame through.
            yield _OVERSIZED_FRAME_SENTINEL
            continue
        yield raw.decode("utf-8", errors="replace")


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_low_level_server_negotiates_modern_types_without_resources
def create_server(config: ConnectionConfig) -> Server[LagniappeAdapter]:
    """Create a stdio-only server whose lifespan owns one authenticated client."""

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
    @asynccontextmanager
    async def lifespan(
        _server: Server[LagniappeAdapter],
    ) -> AsyncIterator[LagniappeAdapter]:
        adapter = LagniappeAdapter(config)
        try:
            with telemetry_scope("startup", "bootstrap"):
                await adapter.initialize()
            yield adapter
        finally:
            await adapter.aclose()

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
    async def list_tools(
        ctx: ServerRequestContext[LagniappeAdapter],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        tools = [
            definition.as_mcp_tool()
            for definition in ctx.lifespan_context.tools.values()
        ]
        return ListToolsResult(tools=tools, result_type="complete")

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
    async def call_tool(
        ctx: ServerRequestContext[LagniappeAdapter],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        adapter = ctx.lifespan_context
        request_id = ctx.request_id if ctx.request_id is not None else 0
        server_info = (
            server.server_info_stamp
            if ctx.protocol_version == "2026-07-28"
            else None
        )
        definition = adapter.tools.get(params.name)
        operation = definition.kind if definition is not None else "protocol"
        with telemetry_scope("call", operation) as metric:
            if definition is None:
                metric.complete("error", error_kind="protocol_error")
                raise MCPError(
                    code=INVALID_PARAMS,
                    message="Unknown Lagniappe MCP tool.",
                )
            try:
                result = await adapter.execute(params.name, params.arguments)
                response = _success_result(
                    result,
                    request_id=request_id,
                    server_info=server_info,
                )
                metric.complete("success")
                return response
            except asyncio.CancelledError:
                raise
            except AdapterError as error:
                response = _error_result(
                    error,
                    request_id=request_id,
                    server_info=server_info,
                )
                metric.complete("error", error_kind=classify_error(error))
                return response
            except Exception:
                response = _error_result(
                    AdapterError(
                        "adapter_failure",
                        "The Lagniappe MCP adapter could not complete this tool call.",
                        retryable=False,
                    ),
                    request_id=request_id,
                    server_info=server_info,
                )
                metric.complete("error", error_kind="adapter_failure")
                return response

    server = Server(
        "lagniappe",
        version=__version__,
        title="Lagniappe",
        description="Local typed adapter for the Lagniappe External Agent API.",
        instructions=MCP_INSTRUCTIONS,
        lifespan=lifespan,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    # Disable SDK/OpenTelemetry middleware. Evaluation metrics use only the
    # private closed-vocabulary JSONL writer and never enter MCP results.
    server.middleware.clear()
    return server


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_real_stdio_subprocess_rejects_oversized_frame_and_resumes
async def serve(config: ConnectionConfig) -> None:
    """Run one local stdio connection until its client disconnects."""
    server = create_server(config)
    # Reuse the exactly pinned SDK's descriptor claim before giving it an
    # explicit bounded reader.  This retains the SDK's claim registry and its
    # fd-0 diversion, so handlers and child processes see EOF rather than the
    # private MCP wire.
    stdin_buffer, restore_stdin = mcp_stdio._claim_fd(
        0,
        sys.stdin,
        "rb",
        mcp_stdio._open_stdin_diversion,
    )
    try:
        bounded_stdin = _bounded_stdin_lines(stdin_buffer)
        async with mcp_stdio.stdio_server(stdin=bounded_stdin) as (
            read_stream,
            write_stream,
        ):
            await server.run(
                _bounded_stdio_requests(read_stream, write_stream),
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        if restore_stdin is not None:
            restore_stdin()


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.initialize
async def check(config: ConnectionConfig) -> tuple[str, str]:
    """Validate startup compatibility without exposing catalog or credentials."""
    adapter = LagniappeAdapter(config)
    try:
        with telemetry_scope("startup", "check"):
            await adapter.initialize()
            await adapter.rest.check_openapi_compatibility()
        actor = adapter.actor or {}
        user = actor.get("user") if isinstance(actor.get("user"), dict) else {}
        return str(user.get("name") or "unknown"), str(user.get("hash") or "unknown")
    finally:
        await adapter.aclose()
