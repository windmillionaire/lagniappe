"""Typed MCP-facing adapter over the authenticated Lagniappe REST API."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from .catalog import (
    ACTOR_SCHEMA,
    GET_FILE_PRIVATE_FIELDS,
    GET_FILE_SAFE_PROPERTIES,
    REST_CONTRACT_SCHEMA,
    REST_SCHEMA_CONTRACT_SCHEMA,
    SAFE_CONTRACT_SCHEMA,
    SAFE_SCHEMA_CONTRACT_SCHEMA,
    SAFE_PLAN_SCHEMA,
    SAFE_RECEIPT_SCHEMA,
    UPLOAD_RESULT_SCHEMA,
    ToolDefinition,
    build_tool_registry,
)
from .configuration import ConnectionConfig
from .errors import AdapterError, TransportError
from .limits import (
    CONTRACT_VERSION_MAX,
    MAX_MEDIA_RAW_BYTES,
    MAX_STRUCTURED_RESULT_BYTES,
    MAX_TEXT_FALLBACK_BYTES,
    MCP_SUBMISSION_INSTRUCTIONS,
)
from .rest import RESTClient
from .schema import compact_json, json_size, validate_schema_document, validate_value
from .url_security import (
    quote_path_segment, validate_api_url, validate_human_url, validate_storage_url,
)


PLAN_ROUTES = {
    "start_plan": ("POST", "plans", None),
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
# @covered-by mcp/src/lagniappe_mcp/adapter.py::_reject_private_model_data
def _query_has_private_storage_parameter(query: str) -> bool:
    """Recognize a bounded query that carries a nonempty storage capability."""
    if not query or len(query) > _MAX_PRIVATE_QUERY_CHARS:
        return any(
            f"{field}=" in query.casefold() for field in _PRIVATE_STORAGE_QUERY_FIELDS
        )
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=64)
    except ValueError:
        return any(
            f"{field}=" in query.casefold() for field in _PRIVATE_STORAGE_QUERY_FIELDS
        )
    return any(
        name.casefold() in _PRIVATE_STORAGE_QUERY_FIELDS and bool(parameter)
        for name, parameter in pairs
    )


# @testable false
# @covered-by mcp/src/lagniappe_mcp/adapter.py::_reject_private_model_data
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
                or (field in _PRIVATE_TRANSPORT_FIELDS and bool(current.strip()))
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


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_original_download_capability_is_scoped_to_requested_file_result
def validate_file_result(value: Any, *, arguments: dict, bearer: str) -> None:
    """Permit one explicitly requested, validated original download capability."""
    screened = deepcopy(value)
    delivery = screened.get("delivery") if isinstance(screened, dict) else None
    if isinstance(delivery, dict) and delivery.get("kind") == "download":
        original = screened.get("original_file")
        if (
            arguments.get("include_original") is not True
            or not isinstance(original, dict)
            or original.get("supported") is not True
            or original.get("attached") is not False
            or not isinstance(original.get("download_url"), str)
        ):
            raise TransportError(
                "invalid_download", "Original download delivery is invalid."
            )
        url = original.pop("download_url")
        if bearer in url or bearer in unquote(url):
            raise TransportError(
                "unsafe_transport_extension",
                "Original download contains private authentication data.",
            )
        validate_storage_url(url, upload=False)
        expires = original.get("expires_in")
        signed_expires = dict(parse_qsl(urlsplit(url).query))["X-Goog-Expires"]
        if type(expires) is not int or expires != int(signed_expires):
            raise TransportError(
                "invalid_download", "Original download expiration is inconsistent."
            )
    _reject_private_model_data(screened, bearer=bearer)


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
# @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_summary_and_preserves_candidate_and_api_errors
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
        registry = build_tool_registry(catalog, execute_plan=actor["capabilities"].get("execute_plan") is True)
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
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
    async def aclose(self) -> None:
        await self.rest.aclose()

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
    # @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_summary_and_preserves_candidate_and_api_errors
    async def execute(self, name: str, arguments: Any) -> AdapterResult:
        """Validate, dispatch, project, and validate one known MCP tool call."""
        definition = self.tools.get(name)
        if definition is None:
            raise KeyError(name)
        value = {} if arguments is None else arguments
        validate_value(definition.input_schema, value, phase="input")

        try:
            if definition.kind == "answer_context":
                context, _request_id = await self.rest.request_json(
                    "GET", "answer-context"
                )
                result = AdapterResult(context)
            elif definition.kind == "actor":
                result = await self._get_actor()
            elif definition.kind.startswith("start_"):
                result = await self._start_plan(definition.kind, value)
            elif definition.kind == "get_plan":
                result = await self._get_plan(value["plan_id"])
            elif definition.kind == "get_plan_contract":
                result = await self._get_contract_projection(
                    value["plan_id"],
                    actions=value.get("actions"),
                    view=value.get("view", "summary"),
                )
            elif definition.kind == "submit":
                result = await self._submit_plan(value)
            elif definition.kind == "execute_plan":
                raw, _request_id = await self.rest.request_json(
                    "POST", f"plans/{quote_path_segment(value['plan_id'])}/execute",
                    body={key: value[key] for key in ("proposal_fingerprint", "operation_id")},
                )
                if not isinstance(raw, dict) or set(raw) != {"plan", "operation"}:
                    raise TransportError("invalid_response", "Execution returned an invalid receipt.")
                result = AdapterResult({"plan": self._safe_plan(raw["plan"], expected_plan_id=value["plan_id"]), "operation": raw["operation"]})
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

        if name == "get_file":
            validate_file_result(result.value, arguments=value, bearer=self.config.api_key)
        else:
            _reject_private_model_data(result.value, bearer=self.config.api_key)
        _reject_private_model_data(
            tuple(item.data for item in result.media),
            bearer=self.config.api_key,
        )
        validate_value(definition.output_schema, result.value, phase="output")
        self._enforce_result_limits(result)
        return result

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _get_actor(self) -> AdapterResult:
        value, _request_id = await self.rest.request_json(
            "GET", "me", max_bytes=128 * 1024
        )
        validate_value(ACTOR_SCHEMA, value, phase="upstream_output")
        self.actor = deepcopy(value)
        return AdapterResult(value)

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _start_plan(self, kind: str, arguments: dict[str, Any]) -> AdapterResult:
        method, route, _ = PLAN_ROUTES[kind]
        body = {"instructions": arguments.get("instructions", "")}
        if "name" in arguments:
            body["name"] = arguments["name"]
        if "revises_plan_id" in arguments:
            body["revises_plan_id"] = arguments["revises_plan_id"]
        value, _request_id = await self.rest.request_json(method, route, body=body)
        plan = self._safe_plan(value)
        return await self._with_lifecycle_context(
            plan, plan_id=plan["id"], actions=arguments.get("actions")
        )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _with_lifecycle_context(
        self,
        value: dict[str, Any],
        *,
        plan_id: str,
        actions: list[str] | None = None,
    ) -> AdapterResult:
        """Bundle a read without turning a successful mutation into a retry."""
        tool = "get_plan_contract"
        arguments = {"plan_id": plan_id}
        if actions is not None:
            arguments.update(actions=actions, view="full")
        try:
            result = await self._get_contract_projection(
                plan_id, actions=actions, view="full" if actions is not None else "summary",
            )
            if "upload_inventory" in value:
                # A second caller can change the Plan between successful
                # finalization and this read. Keep the completed upload's
                # receipt, but do not bundle contradictory working context.
                finalized_files = value["upload_inventory"]
                inventory = result.value["upload_inventory"]
                if (
                    not isinstance(inventory, dict)
                    or inventory.get("status") != "finalized"
                    or inventory.get("authoritative") is not True
                    or type(inventory.get("count")) is not int
                    or inventory["count"] != len(finalized_files)
                    or inventory.get("files") != finalized_files
                    or result.value["required_file_refs"]
                    != [item["ref"] for item in finalized_files]
                ):
                    raise TransportError(
                        "context_changed",
                        "Upload context no longer matches finalization.",
                    )
            context = {"contract": result.value}
            enriched = AdapterResult({**value, "context": context})
            _reject_private_model_data(enriched.value, bearer=self.config.api_key)
            self._enforce_result_limits(enriched)
            return enriched
        except AdapterError as exc:
            # Never reflect the failed read's body or error details. The Plan
            # or finalized upload already exists, so recovery must be a read.
            return AdapterResult(
                {
                    **value,
                    "context": {
                        "recovery": {
                            "tool": tool,
                            "arguments": arguments,
                            "message": (
                                "The Plan was created, but the requested action schemas "
                                "were rejected. Read get_plan_contract with view=summary "
                                "on this Plan to see current allowed actions, then correct "
                                "the selection in this recovery read. Do not repeat the start."
                                if actions is not None and exc.status in (400, 403, 422)
                                else "The operation succeeded, but its working context "
                                "could not be included. Use this recovery read; "
                                "do not repeat the start or upload."
                            ),
                        },
                    },
                }
            )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _get_plan(self, plan_id: str) -> AdapterResult:
        encoded = quote_path_segment(plan_id)
        method, route, _tool = PLAN_ROUTES["get_plan"]
        value, _request_id = await self.rest.request_json(
            method,
            route.format(plan_id=encoded),
        )
        return AdapterResult(self._safe_plan(value, expected_plan_id=plan_id))

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _load_contract(
        self, plan_id: str, *, view, actions=None
    ) -> dict[str, Any]:
        encoded = quote_path_segment(plan_id)
        method, route, _tool = PLAN_ROUTES["get_plan_contract"]
        value, _request_id = await self.rest.request_json(
            method,
            route.format(plan_id=encoded)
            + (
                "?"
                + urlencode(
                    {
                        **(
                            {"actions": ",".join(actions)}
                            if actions is not None
                            else {}
                        ),
                        "view": view,
                    }
                )
            ),
        )
        if not isinstance(value, dict):
            raise TransportError(
                "invalid_response", "Plan contract must be a JSON object."
            )
        validate_value(
            REST_SCHEMA_CONTRACT_SCHEMA if view == "schema" else REST_CONTRACT_SCHEMA,
            value, phase="contract",
        )
        proposal_schema = (
            validate_schema_document(value["proposal_schema"], input_root=True)
            if value["proposal_schema"] is not None
            else None
        )
        if proposal_schema is None and (
            view != "summary" or value.get("schema_scope") != "summary"
        ):
            raise TransportError(
                "invalid_response", "A full contract must include its proposal schema."
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
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _get_contract_projection(
        self, plan_id: str, *, actions=None, view="summary"
    ) -> AdapterResult:
        contract = await self._load_contract(plan_id, actions=actions, view=view)
        submission = contract.pop("submission_format")
        contract["mcp_submission"] = {
            "contract_version": submission["contract_version"],
            "proposal": {},
            "file_usage": [],
            "proposal_schema": "$.proposal_schema",
            "instructions": MCP_SUBMISSION_INSTRUCTIONS,
        }
        validate_value(
            SAFE_SCHEMA_CONTRACT_SCHEMA if view == "schema" else SAFE_CONTRACT_SCHEMA,
            contract, phase="output",
        )
        return AdapterResult(contract)

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _submit_plan(self, arguments: dict[str, Any]) -> AdapterResult:
        plan_id = arguments["plan_id"]
        # The API validates the candidate against live permissions and state.
        # Only fetch the transport contract here: interpreting every action's
        # schema would add a second, potentially divergent rejection boundary.
        contract = await self._load_contract(plan_id, view="summary")
        submission = contract["submission_format"]
        body = deepcopy(submission["body"])
        # Preserve the submitted version so the API can reject stale clients;
        # copying the current template's version would silently upgrade them.
        body["contract_version"] = arguments["contract_version"]
        body["file_usage"] = deepcopy(arguments["file_usage"])
        body["proposal"] = deepcopy(arguments["proposal"])
        for field in ("name", "instructions"):
            if field in arguments:
                body[field] = arguments[field]
        value, _request_id = await self.rest.request_json(
            submission["method"],
            submission["url"],
            body=body,
        )
        return AdapterResult(self._safe_receipt(value, expected_plan_id=plan_id))

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _upload_files(self, arguments: dict[str, Any]) -> AdapterResult:
        from .files import upload_local_files

        plan_id = arguments["plan_id"]
        contract = await self._load_contract(plan_id, view="summary")
        if contract["uploads_supported"] is not True:
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
        return await self._with_lifecycle_context(value, plan_id=plan_id)

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    async def _read_tool(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
    ) -> AdapterResult:
        rest_arguments = deepcopy(arguments)
        plan_id = rest_arguments.pop("plan_id", None)
        route = (
            f"plans/{quote_path_segment(plan_id)}/tools/{definition.name}"
            if plan_id is not None
            else f"tools/{definition.name}"
        )
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
    # @tests tests_unit/test_033_mcp_adapter.py::test_original_download_fallback_preserves_source_without_fetching_binary
    # @tests tests_unit/test_033_mcp_adapter.py::test_oversized_original_media_falls_back_only_for_size_limit
    # @tests tests_unit/test_033_mcp_adapter.py::test_original_media_delivery_matches_the_emitted_content_index
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
        if any(
            not isinstance(field, str) or field not in known_fields
            for field in raw_value
        ):
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
            value["original_file"]["attached"] = False
            if requested and original.get("supported") is False:
                raise TransportError(
                    "original_unavailable",
                    "Original content is unavailable for this file.",
                )
            if not requested and original.get("supported") is True:
                value["original_file"]["reason"] = (
                    "Call get_file with include_original=true to read the original. "
                    "Small supported images/audio are delivered inline; other originals "
                    "use a five-minute download URL for your file or browsing tools."
                )
            if requested:
                if not isinstance(download_url, str):
                    raise TransportError(
                        "original_unavailable",
                        "The requested original did not include a safe download.",
                    )
                declared_mime = raw_value.get("mimetype") or "application/octet-stream"
                value["original_file"] = {
                    "supported": True,
                    "attached": False,
                    "download_url": download_url,
                    "expires_in": original.get("expires_in"),
                }
                value["delivery"] = {
                    "kind": "download",
                    "mime_type": declared_mime,
                }
                validate_file_result(value, arguments=arguments, bearer=self.config.api_key)
                if (
                    declared_mime in SUPPORTED_IMAGE_MIMES | SUPPORTED_AUDIO_MIMES
                    and raw_value.get("large") is not True
                ):
                    try:
                        data, mime_type = await self.rest.download_media(
                            download_url, cap=MAX_MEDIA_RAW_BYTES,
                        )
                    except TransportError as error:
                        if error.code != "media_too_large":
                            raise
                    else:
                        if declared_mime != mime_type:
                            raise TransportError(
                                "mime_mismatch",
                                "Original media type contradicts file metadata.",
                            )
                        kind = "image" if mime_type in SUPPORTED_IMAGE_MIMES else "audio"
                        value["original_file"] = {"supported": True, "attached": True}
                        value["delivery"] = {
                            "kind": kind,
                            "mime_type": mime_type,
                            "size_bytes": len(data),
                            "content_index": 1,
                        }
                        media = (MediaContent(kind, mime_type, data),)
        validate_file_result(value, arguments=arguments, bearer=self.config.api_key)
        return AdapterResult(value, media)

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
    def _safe_plan(
        self,
        value: Any,
        *,
        expected_plan_id: str | None = None,
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
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
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
    # @covered-by mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
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
