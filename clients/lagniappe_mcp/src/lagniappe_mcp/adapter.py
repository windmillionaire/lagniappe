"""Typed MCP-facing adapter over the authenticated Lagniappe REST API."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .catalog import (
    ACTOR_SCHEMA,
    GET_FILE_PRIVATE_FIELDS,
    GET_FILE_SAFE_PROPERTIES,
    REST_CONTRACT_SCHEMA,
    SAFE_CONTRACT_SCHEMA,
    SAFE_PLAN_SCHEMA,
    SAFE_RECEIPT_SCHEMA,
    UPLOAD_RESULT_SCHEMA,
    ToolDefinition,
    build_tool_registry,
)
from .configuration import ConnectionConfig
from .errors import AdapterError, SchemaError, TransportError
from .limits import (
    CONTRACT_VERSION_MAX,
    MAX_MEDIA_RAW_BYTES,
    MAX_STRUCTURED_RESULT_BYTES,
    MAX_TEXT_FALLBACK_BYTES,
)
from .rest import RESTClient
from .schema import compact_json, json_size, validate_schema_document, validate_value
from .url_security import quote_path_segment, validate_api_url, validate_human_url


PLAN_ROUTES = {
    "start_ask": ("POST", "plans", "ask"),
    "start_create": ("POST", "plans", "create"),
    "start_organize": ("POST", "plans", "organize"),
    "get_plan": ("GET", "plans/{plan_id}", None),
    "get_plan_contract": ("GET", "plans/{plan_id}/contract", None),
    "upload_sessions": ("POST", "plans/{plan_id}/uploads", None),
    "upload_finalize": ("POST", "plans/{plan_id}/uploads/finalize", None),
}

SUPPORTED_IMAGE_MIMES = frozenset(
    {"image/gif", "image/jpeg", "image/png", "image/webp"}
)
SUPPORTED_AUDIO_MIMES = frozenset(
    {"audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-wav"}
)
_PRIVATE_TRANSPORT_FIELDS = frozenset(GET_FILE_PRIVATE_FIELDS)
_PRIVATE_STORAGE_QUERY_FIELDS = frozenset({"upload_id", "x-goog-signature"})
_URL_CANDIDATE_PATTERN = re.compile(r"(?i)https://[^\s\"'<>]+")
_MAX_PRIVATE_QUERY_CHARS = 16 * 1024


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::_reject_private_model_data
def _query_has_private_storage_parameter(query: str) -> bool:
    """Recognize a bounded query that carries a nonempty storage capability."""
    if not query or len(query) > _MAX_PRIVATE_QUERY_CHARS:
        return any(
            f"{field}=" in query.casefold()
            for field in _PRIVATE_STORAGE_QUERY_FIELDS
        )
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=64)
    except ValueError:
        return any(
            f"{field}=" in query.casefold()
            for field in _PRIVATE_STORAGE_QUERY_FIELDS
        )
    return any(
        name.casefold() in _PRIVATE_STORAGE_QUERY_FIELDS and bool(parameter)
        for name, parameter in pairs
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::_reject_private_model_data
def _has_private_transport_shape(value: str) -> bool:
    """Recognize an actual signed/session value, not ordinary prose about one."""
    stripped = value.strip()
    raw_query = stripped.removeprefix("?")
    if (
        raw_query
        and not any(character.isspace() for character in raw_query)
        and all("=" in component for component in raw_query.split("&"))
        and _query_has_private_storage_parameter(raw_query)
    ):
        return True

    for match in _URL_CANDIDATE_PATTERN.finditer(value):
        try:
            parsed = urlsplit(match.group(0))
            hostname = parsed.hostname
        except ValueError:
            continue
        if (
            hostname is not None
            and hostname.casefold() == "storage.googleapis.com"
            and _query_has_private_storage_parameter(parsed.query)
        ):
            return True
    return False


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_model_visibility_screen_rejects_catalog_reflection_and_preserves_safe_result_paths
# @tests tests_unit/test_033_mcp_adapter.py::test_model_visibility_screen_rejects_successful_output_reflection
def _reject_private_model_data(value: Any, *, bearer: str) -> None:
    """Reject credentials and storage capabilities at the MCP boundary.

    Catalog metadata and successful tool values both reach the model.  Walk
    their complete public representation here so a compromised configured API
    cannot reflect the process credential or a temporary storage capability
    through an otherwise valid description, schema, result-path hint, or
    domain value.
    """
    pending: list[tuple[str | None, Any]] = [(None, value)]
    bearer_bytes = bearer.encode("utf-8")
    while pending:
        field, current = pending.pop()
        unsafe = False
        if isinstance(current, str):
            unsafe = (
                bearer in current
                or _has_private_transport_shape(current)
                or (
                    field in _PRIVATE_TRANSPORT_FIELDS
                    and bool(current.strip())
                )
            )
        elif isinstance(current, bytes):
            encoded_bytes = base64.b64encode(current)
            unsafe = (
                bearer_bytes in current
                or bearer_bytes in encoded_bytes
                or (field in _PRIVATE_TRANSPORT_FIELDS and bool(current))
            )
        elif isinstance(current, dict):
            for key, item in current.items():
                pending.append((None, key))
                pending.append((key.casefold() if isinstance(key, str) else None, item))
        elif isinstance(current, (list, tuple)):
            pending.extend((None, item) for item in current)
        if unsafe:
            raise TransportError(
                "unsafe_transport_extension",
                "Private transport data cannot cross the MCP presentation boundary.",
            )


@dataclass(frozen=True, slots=True)
class MediaContent:
    """One bounded original-file payload for an MCP content block."""

    kind: str
    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """A validated structured result plus optional non-text content."""

    value: Any
    media: tuple[MediaContent, ...] = ()


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
# @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper
# @tests tests_unit/test_033_mcp_adapter.py::test_requested_unsupported_original_is_a_bounded_tool_error
# @tests tests_unit/test_033_mcp_adapter.py::test_requested_missing_original_is_a_bounded_tool_error
class LagniappeAdapter:
    """Own startup catalog state and dispatch only fixed, typed operations."""

    def __init__(
        self, config: ConnectionConfig, *, rest: RESTClient | None = None
    ) -> None:
        self.config = config
        self.rest = rest or RESTClient(config)
        self.discovery: dict[str, Any] | None = None
        self.actor: dict[str, Any] | None = None
        self.tools: dict[str, ToolDefinition] = {}

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
    async def initialize(self) -> None:
        discovery, actor, catalog = await self.rest.startup()
        validate_value(ACTOR_SCHEMA, actor, phase="actor")
        actor_user = actor.get("user") if isinstance(actor, dict) else None
        actor_hash = actor_user.get("hash") if isinstance(actor_user, dict) else None
        if self.config.actor_hash is not None and actor_hash != self.config.actor_hash:
            raise TransportError(
                "actor_mismatch",
                "The API credential no longer belongs to this profile's actor.",
            )
        registry = build_tool_registry(catalog)
        published_tools = [
            definition.as_mcp_tool().model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            for definition in registry.values()
        ]
        _reject_private_model_data(actor, bearer=self.config.api_key)
        _reject_private_model_data(published_tools, bearer=self.config.api_key)
        self.discovery = discovery
        self.actor = deepcopy(actor)
        self.tools = registry

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
    async def aclose(self) -> None:
        await self.rest.aclose()

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
    # @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper
    async def execute(self, name: str, arguments: Any) -> AdapterResult:
        """Validate, dispatch, project, and validate one known MCP tool call."""
        definition = self.tools.get(name)
        if definition is None:
            raise KeyError(name)
        value = {} if arguments is None else arguments
        validate_value(definition.input_schema, value, phase="input")

        try:
            if definition.kind == "actor":
                result = await self._get_actor()
            elif definition.kind.startswith("start_"):
                result = await self._start_plan(definition.kind, value)
            elif definition.kind == "get_plan":
                result = await self._get_plan(value["plan_id"])
            elif definition.kind == "get_plan_contract":
                result = await self._get_contract_projection(value["plan_id"])
            elif definition.kind == "submit":
                result = await self._submit_plan(value)
            elif definition.kind == "upload":
                result = await self._upload_files(value)
            elif definition.kind == "read":
                result = await self._read_tool(definition, value)
            else:  # The registry is adapter-owned; this is startup incompatibility.
                raise TransportError(
                    "invalid_catalog", "MCP tool has an unsupported dispatch kind."
                )
        except asyncio.CancelledError:
            raise

        _reject_private_model_data(result.value, bearer=self.config.api_key)
        _reject_private_model_data(
            tuple(item.data for item in result.media),
            bearer=self.config.api_key,
        )
        validate_value(definition.output_schema, result.value, phase="output")
        self._enforce_result_limits(result)
        return result

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _get_actor(self) -> AdapterResult:
        value, _request_id = await self.rest.request_json(
            "GET", "me", max_bytes=128 * 1024
        )
        validate_value(ACTOR_SCHEMA, value, phase="upstream_output")
        actor_hash = value["user"]["hash"]
        if self.config.actor_hash is not None and actor_hash != self.config.actor_hash:
            raise TransportError(
                "actor_mismatch",
                "The API credential no longer belongs to this profile's actor.",
            )
        self.actor = deepcopy(value)
        return AdapterResult(value)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _start_plan(self, kind: str, arguments: dict[str, Any]) -> AdapterResult:
        method, route, tool = PLAN_ROUTES[kind]
        body = {"tool": tool, "instructions": arguments["instructions"]}
        if "name" in arguments:
            body["name"] = arguments["name"]
        value, _request_id = await self.rest.request_json(method, route, body=body)
        return AdapterResult(self._safe_plan(value, expected_tool=tool))

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _get_plan(self, plan_id: str) -> AdapterResult:
        encoded = quote_path_segment(plan_id)
        method, route, _tool = PLAN_ROUTES["get_plan"]
        value, _request_id = await self.rest.request_json(
            method,
            route.format(plan_id=encoded),
        )
        return AdapterResult(self._safe_plan(value, expected_plan_id=plan_id))

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _load_contract(self, plan_id: str) -> dict[str, Any]:
        encoded = quote_path_segment(plan_id)
        method, route, _tool = PLAN_ROUTES["get_plan_contract"]
        value, _request_id = await self.rest.request_json(
            method,
            route.format(plan_id=encoded),
        )
        if not isinstance(value, dict):
            raise TransportError(
                "invalid_response", "Plan contract must be a JSON object."
            )
        validate_value(REST_CONTRACT_SCHEMA, value, phase="contract")
        proposal_schema = validate_schema_document(
            value["proposal_schema"], input_root=True
        )
        submission = value["submission_format"]
        if (
            value["contract_version"] != CONTRACT_VERSION_MAX
            or submission["contract_version"] != value["contract_version"]
            or submission["body"]["contract_version"] != value["contract_version"]
            or submission["body"]["proposal"] != {}
        ):
            raise TransportError(
                "incompatible_contract",
                "Plan contract versions or submission template disagree.",
            )
        expected_path = f"/api/v1/plans/{encoded}/submit"
        validate_api_url(
            self.config.authority,
            submission["url"],
            expected_path=expected_path,
        )
        result = deepcopy(value)
        result["proposal_schema"] = proposal_schema
        return result

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _get_contract_projection(self, plan_id: str) -> AdapterResult:
        contract = await self._load_contract(plan_id)
        submission = contract.pop("submission_format")
        contract["mcp_submission"] = {
            "contract_version": submission["contract_version"],
            "proposal": {},
            "proposal_schema": "$.proposal_schema",
            "instructions": (
                "Call submit_plan with this plan_id, contract_version, and a "
                "proposal matching proposal_schema."
            ),
        }
        validate_value(SAFE_CONTRACT_SCHEMA, contract, phase="output")
        return AdapterResult(contract)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _submit_plan(self, arguments: dict[str, Any]) -> AdapterResult:
        plan_id = arguments["plan_id"]
        contract = await self._load_contract(plan_id)
        if arguments["contract_version"] != contract["contract_version"]:
            raise SchemaError(
                "stale_contract_version",
                "contract_version does not match the current Plan contract.",
                details={"expected": contract["contract_version"]},
            )
        validate_value(
            contract["proposal_schema"], arguments["proposal"], phase="proposal"
        )
        submission = contract["submission_format"]
        body = deepcopy(submission["body"])
        body["proposal"] = deepcopy(arguments["proposal"])
        value, _request_id = await self.rest.request_json(
            submission["method"],
            submission["url"],
            body=body,
        )
        return AdapterResult(self._safe_receipt(value, expected_plan_id=plan_id))

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _upload_files(self, arguments: dict[str, Any]) -> AdapterResult:
        from .files import upload_local_files

        plan_id = arguments["plan_id"]
        contract = await self._load_contract(plan_id)
        if contract["tool"] != "organize" or contract["uploads_supported"] is not True:
            raise AdapterError(
                "uploads_not_supported", "This Plan does not accept file uploads."
            )
        raw = await upload_local_files(
            self.rest,
            plan_id=plan_id,
            file_items=arguments["files"],
            contract=contract,
        )
        if not isinstance(raw, dict) or set(raw) != {"plan", "upload_inventory"}:
            raise TransportError(
                "invalid_response", "Upload completion returned an invalid result."
            )
        value = {
            "plan": self._safe_plan(raw["plan"], expected_plan_id=plan_id),
            "upload_inventory": raw["upload_inventory"],
        }
        validate_value(UPLOAD_RESULT_SCHEMA, value, phase="upstream_output")
        return AdapterResult(value)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _read_tool(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
    ) -> AdapterResult:
        rest_arguments = deepcopy(arguments)
        plan_id = rest_arguments.pop("plan_id")
        route = f"plans/{quote_path_segment(plan_id)}/tools/{definition.name}"
        envelope, _request_id = await self.rest.request_json(
            "POST",
            route,
            body={"arguments": rest_arguments},
        )
        if not isinstance(envelope, dict) or set(envelope) != {"result"}:
            raise TransportError(
                "invalid_response", "Tool response has an invalid success envelope."
            )
        result = envelope["result"]
        rest_schema = definition.rest_output_schema or definition.output_schema
        validate_value(rest_schema, result, phase="upstream_output")
        if definition.name != "get_file":
            return AdapterResult(result)
        return await self._project_file_result(result, rest_arguments)

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_requested_unsupported_original_is_a_bounded_tool_error
    # @tests tests_unit/test_033_mcp_adapter.py::test_requested_missing_original_is_a_bounded_tool_error
    # @tests tests_unit/test_033_mcp_adapter.py::test_original_download_mime_must_match_upstream_file_metadata
    async def _project_file_result(
        self,
        raw_value: Any,
        arguments: dict[str, Any],
    ) -> AdapterResult:
        if not isinstance(raw_value, dict):
            raise TransportError(
                "invalid_response", "get_file result must be an object."
            )
        known_fields = set(GET_FILE_SAFE_PROPERTIES) | {
            "original_file",
            *GET_FILE_PRIVATE_FIELDS,
        }
        if any(not isinstance(field, str) or field not in known_fields for field in raw_value):
            raise TransportError(
                "unsafe_transport_extension",
                "get_file returned an unrecognized transport or metadata field.",
            )
        value = {
            field: deepcopy(item)
            for field, item in raw_value.items()
            if field in GET_FILE_SAFE_PROPERTIES
        }
        original = raw_value.get("original_file")
        media: tuple[MediaContent, ...] = ()
        value["delivery"] = {"kind": "none"}
        requested = arguments.get("include_original") is True
        if requested and not isinstance(original, dict):
            raise TransportError(
                "original_unavailable",
                "The requested original did not include a safe download.",
            )
        if isinstance(original, dict):
            download_url = original.get("download_url")
            value["original_file"] = {
                field: deepcopy(original[field])
                for field in ("supported", "attached", "reason")
                if field in original
            }
            if requested and original.get("supported") is False:
                raise TransportError(
                    "unsupported_media",
                    "The requested original is not available as supported MCP media.",
                )
            if requested:
                if not isinstance(download_url, str):
                    raise TransportError(
                        "original_unavailable",
                        "The requested original did not include a safe download.",
                    )
                data, mime_type = await self.rest.download_media(
                    download_url,
                    cap=MAX_MEDIA_RAW_BYTES,
                )
                # ``mimetype`` is upstream metadata used to validate the
                # downloaded bytes, but it is intentionally not part of the
                # projected MCP result.  Read it from the validated REST value
                # rather than the allowlisted result projection.
                declared_mime = raw_value.get("mimetype")
                if (
                    isinstance(declared_mime, str)
                    and declared_mime
                    and declared_mime != mime_type
                ):
                    raise TransportError(
                        "mime_mismatch",
                        "Original media type contradicts file metadata.",
                    )
                if mime_type in SUPPORTED_IMAGE_MIMES:
                    kind = "image"
                elif mime_type in SUPPORTED_AUDIO_MIMES:
                    kind = "audio"
                else:
                    raise TransportError(
                        "unsupported_media",
                        "Original MIME type is not supported by this MCP adapter.",
                    )
                value["delivery"] = {
                    "kind": kind,
                    "mime_type": mime_type,
                    "size_bytes": len(data),
                    "content_index": 1,
                }
                media = (MediaContent(kind, mime_type, data),)
        _reject_private_model_data(value, bearer=self.config.api_key)
        return AdapterResult(value, media)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    def _safe_plan(
        self,
        value: Any,
        *,
        expected_plan_id: str | None = None,
        expected_tool: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TransportError(
                "invalid_response", "Plan response must be a JSON object."
            )
        result = deepcopy(value)
        result.pop("upload_batch_id", None)
        plan_id = result.get("id")
        if not isinstance(plan_id, str) or (
            expected_plan_id is not None and plan_id != expected_plan_id
        ):
            raise TransportError(
                "invalid_response", "Plan response identity does not match the request."
            )
        if expected_tool is not None and result.get("tool") != expected_tool:
            raise TransportError(
                "invalid_response", "Plan response tool does not match the request."
            )
        encoded = quote_path_segment(plan_id)
        for field, suffix in {
            "contract_url": "contract",
            "submit_url": "submit",
            "status_url": "",
        }.items():
            url = result.get(field)
            if not isinstance(url, str):
                raise TransportError(
                    "invalid_response", f"Plan response is missing {field}."
                )
            path = f"/api/v1/plans/{encoded}" + (f"/{suffix}" if suffix else "")
            validate_api_url(self.config.authority, url, expected_path=path)
            result.pop(field)
        for field in ("preview_url", "review_url"):
            url = result.get(field)
            if not isinstance(url, str):
                raise TransportError(
                    "invalid_response", f"Plan response is missing {field}."
                )
            result[field] = validate_human_url(self.config.authority, url)
        validate_value(SAFE_PLAN_SCHEMA, result, phase="upstream_output")
        return result

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    def _safe_receipt(self, value: Any, *, expected_plan_id: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TransportError(
                "invalid_response", "Submission receipt must be a JSON object."
            )
        result = deepcopy(value)
        if result.get("id") != expected_plan_id:
            raise TransportError(
                "invalid_response",
                "Submission receipt identity does not match the Plan.",
            )
        encoded = quote_path_segment(expected_plan_id)
        status_url = result.pop("status_url", None)
        if not isinstance(status_url, str):
            raise TransportError(
                "invalid_response", "Submission receipt is missing status_url."
            )
        validate_api_url(
            self.config.authority,
            status_url,
            expected_path=f"/api/v1/plans/{encoded}",
        )
        for field in ("preview_url", "review_url"):
            url = result.get(field)
            if not isinstance(url, str):
                raise TransportError(
                    "invalid_response", f"Submission receipt is missing {field}."
                )
            result[field] = validate_human_url(self.config.authority, url)
        validate_value(SAFE_RECEIPT_SCHEMA, result, phase="upstream_output")
        return result

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    @staticmethod
    def _enforce_result_limits(result: AdapterResult) -> None:
        structured_size = json_size(result.value)
        if structured_size > MAX_STRUCTURED_RESULT_BYTES:
            raise TransportError(
                "result_too_large", "Structured tool result exceeds the MCP limit."
            )
        text_size = len(compact_json(result.value).encode("utf-8"))
        if text_size > MAX_TEXT_FALLBACK_BYTES:
            raise TransportError(
                "result_too_large", "Tool result text fallback exceeds the MCP limit."
            )
