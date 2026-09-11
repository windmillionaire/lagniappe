"""MCP result presentation for the remote HTTP transport."""

from __future__ import annotations

import base64
import re
from typing import Any

from mcp_types import (AudioContent, CallToolResult, ImageContent, JSONRPCResponse,
                       RequestId, SERVER_INFO_META_KEY, TextContent)

from .adapter import AdapterResult
from .errors import AdapterError, TransportError
from .limits import MAX_COMPLETE_FRAME_BYTES
from .schema import compact_json

_REQUEST_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")


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
# @covered-by mcp/src/lagniappe_mcp/presentation.py::_success_result
# @covered-by mcp/src/lagniappe_mcp/presentation.py::_error_result
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
# @tests tests_unit/test_033_mcp_adapter.py::test_server_presents_matching_schemas_and_values_for_each_protocol
def _success_result(
    result: AdapterResult,
    *,
    request_id: RequestId = 0,
    server_info: dict[str, Any] | None = None,
    wrap_result: bool = False,
) -> CallToolResult:
    value = {"result": result.value} if wrap_result else result.value
    content: list[Any] = [TextContent(type="text", text=compact_json(value))]
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
        structured_content=value,
        is_error=False,
        result_type="complete",
    )
    _ensure_frame_limit(
        response,
        request_id=request_id,
        server_info=server_info,
    )
    return response
