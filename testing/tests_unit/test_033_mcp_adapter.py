"""Standalone MCP adapter contracts; this module must run without app imports."""

from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import stat
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from lagniappe_mcp import schema as schema_module
from lagniappe_mcp.adapter import (
    AdapterResult,
    LagniappeAdapter,
    _reject_private_model_data,
)
from lagniappe_mcp.catalog import (
    READ_ANNOTATIONS,
    ToolDefinition,
    build_tool_registry,
    catalog_tools,
    get_file_output_schema,
    lifecycle_tools,
)
from lagniappe_mcp.configuration import ConnectionConfig
from lagniappe_mcp.errors import (
    AdapterError,
    ConfigurationError,
    SchemaError,
    TransportError,
)
from lagniappe_mcp.limits import (
    CONTRACT_VERSION_MAX,
    MAX_ERROR_BYTES,
    MAX_MEDIA_RAW_BYTES,
    MAX_STRUCTURED_RESULT_BYTES,
)
from lagniappe_mcp.rest import RESTClient
from lagniappe_mcp.schema import (
    compact_json,
    inject_plan_id,
    validate_schema_document,
    validate_value,
    wrap_result_schema,
)
from lagniappe_mcp.presentation import (
    _error_result,
    _success_result,
)
from lagniappe_mcp.url_security import normalize_site_url, validate_storage_url
from testing.utility import mcp_client_driver


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "mcp"


def _signed_download_url(**updates: str) -> str:
    values = {
        "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
        "X-Goog-Credential": "account/20990101/auto/storage/goog4_request",
        "X-Goog-Date": "20990101T000000Z",
        "X-Goog-Expires": "300",
        "X-Goog-SignedHeaders": "host",
        "X-Goog-Signature": "a" * 64,
    }
    values.update(updates)
    return f"https://storage.googleapis.com/bucket/object.png?{urlencode(values)}"


def _actor() -> dict[str, Any]:
    return {
        "user": {
            "name": "Person",
            "hash": "abcdefghijkl",
            "timezone": "UTC",
            "personal_page": {
                "kind": "page",
                "hash": "hash:abcdefghijkl",
                "name": "Personal Page",
                "url": "/pages/personal",
                "can_view": True,
                "can_edit": True,
            },
        },
        "credential": {
            "active": True,
            "display_prefix": "lgn_actor…",
            "issued_at": "2026-09-04T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "generation": 1,
        },
        "capabilities": {"ask": True, "create": True, "organize": True},
    }


def _plan() -> dict[str, Any]:
    return {
        "id": "abcdefghijkl",
        "status": "draft",
        "tool": "create",
        "name": "Draft",
        "instructions": "Prepare one safe change.",
        "files": [],
        "uploads_pending": False,
        "upload_batch_id": None,
        "contract_version": CONTRACT_VERSION_MAX,
        "contract_url": "https://example.com/api/v1/plans/abcdefghijkl/contract",
        "submit_url": "https://example.com/api/v1/plans/abcdefghijkl/submit",
        "status_url": "https://example.com/api/v1/plans/abcdefghijkl",
        "preview_url": "https://example.com/tools/api-plan/abcdefghijkl",
        "review_url": "https://example.com/tools/reports/abcdefghijkl",
        "proposal": None,
    }


def _contract() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION_MAX,
        "tool": "create",
        "current_date": "2026-09-04",
        "timezone": "UTC",
        "personal_page": {},
        "proposal_schema": {
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
        "permissions": {},
        "required_file_refs": [],
        "upload_inventory": None,
        "file_checklist": [],
        "guidance_requirements": {},
        "uploads_supported": False,
        "workflow_rules": [],
        "reference_rules": [],
        "limits": {},
        "payload_sizes": {},
        "submission_format": {
            "method": "POST",
            "url": "https://example.com/api/v1/plans/abcdefghijkl/submit",
            "contract_version": CONTRACT_VERSION_MAX,
            "body": {"contract_version": CONTRACT_VERSION_MAX, "proposal": {}},
            "rule": "Replace the empty proposal template.",
        },
    }


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
# @source mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def test_plan_free_reads_compact_contracts_and_revised_brief():
    class ConversationalREST(_WorkflowREST):
        async def request_json(self, method, target, *, body=None, **kwargs):
            if target == "answer-context":
                self.requests.append((method, target, body))
                return {
                    "current_date": "2026-09-06",
                    "timezone": "UTC",
                    "personal_page": {},
                    "report_created": False,
                    "workflow_rules": ["Answer first; save only on request."],
                }, "answer"
            if target.startswith("plans/abcdefghijkl/contract?"):
                self.requests.append((method, target, body))
                contract = _contract()
                contract["permissions"] = {
                    "allowed_actions": ["create_task", "create_page"]
                }
                if target.endswith("view=summary"):
                    contract.update(proposal_schema=None, schema_scope="summary")
                else:
                    assert "actions=create_task" in target
                    contract.update(
                        schema_scope="selected", schema_actions=["create_task"],
                        schema_instructions="Reuse plan context. Submit against current permissions.",
                    )
                    if target.endswith("view=schema"):
                        contract = {key: value for key, value in contract.items() if key in {
                            "contract_version", "tool", "proposal_schema", "schema_scope",
                            "schema_actions", "schema_instructions", "submission_format",
                        }}
                return contract, "contract"
            return await super().request_json(method, target, body=body, **kwargs)

    async def exercise():
        rest = ConversationalREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        context = await adapter.execute("answer_question", {})
        assert context.value["report_created"] is False
        found = await adapter.execute("search", {"query": "setup CLI"})
        assert found.value == ["first", "second"]
        assert [target for _, target, _ in rest.requests] == [
            "answer-context",
            "tools/search",
        ]
        started = await adapter.execute(
            "start_create", {"instructions": "Create a task"}
        )
        assert started.value["context"]["contract"]["proposal_schema"] is None
        selected = await adapter.execute(
            "get_plan_contract", {"plan_id": "abcdefghijkl", "actions": ["create_task"]}
        )
        assert selected.value["schema_scope"] == "selected"
        assert selected.value["permissions"]["allowed_actions"] == [
            "create_task",
            "create_page",
        ]
        compact = await adapter.execute("get_plan_contract", {
            "plan_id": "abcdefghijkl", "actions": ["create_task"], "view": "schema",
        })
        assert compact.value["proposal_schema"] == selected.value["proposal_schema"]
        assert compact.value["mcp_submission"] == selected.value["mcp_submission"]
        assert "workflow_rules" not in compact.value
        assert "submission_format" not in compact.value
        with pytest.raises(SchemaError):
            await adapter.execute(
                "submit_plan",
                {
                    "plan_id": "abcdefghijkl",
                    "contract_version": CONTRACT_VERSION_MAX,
                    "proposal": {"wrong": "shape"},
                },
            )
        receipt = await adapter.execute(
            "submit_plan",
            {
                "plan_id": "abcdefghijkl",
                "contract_version": CONTRACT_VERSION_MAX,
                "proposal": {"title": "Task"},
                "name": "Expanded request",
                "instructions": "Now includes another task",
            },
        )
        assert receipt.value["status"] == "ready"
        assert rest.requests[-2][1] == "plans/abcdefghijkl/contract"
        assert rest.requests[-1][2] == {
            "contract_version": CONTRACT_VERSION_MAX,
            "proposal": {"title": "Task"},
            "name": "Expanded request",
            "instructions": "Now includes another task",
        }
        assert (
            sum(
                method == "POST" and target == "plans"
                for method, target, _ in rest.requests
            )
            == 1
        )

    asyncio.run(exercise())


class _WorkflowREST:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []

    async def startup(self):
        return (
            {"version": "v1"},
            _actor(),
            {
                "tools": [
                    {
                        "name": "search",
                        "description": "Search within the current Plan.",
                        "input_schema": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {"query": {"type": "string"}},
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "result_paths": {
                            "primary_collection": "$",
                            "pagination": None,
                        },
                    }
                ],
                "view": "full",
                "selected_count": 1,
                "reference_format": "hash:<12-character-hash>",
                "execution_envelope": {
                    "success": {
                        "result": "<value matching the selected output_schema>"
                    },
                    "failure": {
                        "error": {"code": "tool_error", "message": "<message>"},
                        "request_id": "<request id>",
                    },
                },
            },
        )

    async def request_json(
        self, method: str, target: str, *, body: Any = None, **_kwargs: Any
    ):
        self.requests.append((method, target, body))
        if target == "me":
            return _actor(), "request-actor"
        if target == "plans":
            return _plan(), "request-start"
        if target == "plans/abcdefghijkl":
            return _plan(), "request-plan"
        if target.split("?", 1)[0] == "plans/abcdefghijkl/contract":
            return _contract(), "request-contract"
        if target in {"plans/abcdefghijkl/tools/search", "tools/search"}:
            return {"result": ["first", "second"]}, "request-search"
        if target == "https://example.com/api/v1/plans/abcdefghijkl/submit":
            return {
                "id": "abcdefghijkl",
                "status": "ready",
                "preview_url": "https://example.com/tools/api-plan/abcdefghijkl",
                "review_url": "https://example.com/tools/reports/abcdefghijkl",
                "status_url": "https://example.com/api/v1/plans/abcdefghijkl",
                "contract_version": CONTRACT_VERSION_MAX,
                "proposal_fingerprint": "f" * 64,
            }, "request-submit"
        raise AssertionError(f"Unexpected request: {method} {target}")

    async def aclose(self) -> None:
        return None


# @pair mcp-adapter:product-contract
def test_schema_rejects_dangling_refs_and_non_finite_json() -> None:
    with pytest.raises(SchemaError, match="dangling"):
        validate_schema_document(
            {
                "type": "object",
                "properties": {"value": {"$ref": "#/$defs/missing"}},
                "$defs": {},
            }
        )
    with pytest.raises(SchemaError) as error:
        compact_json({"value": float("nan")})
    assert error.value.code == "invalid_json"
    with pytest.raises(SchemaError) as dynamic:
        validate_schema_document({"$dynamicRef": "https://attacker.invalid/schema"})
    assert dynamic.value.code == "unsupported_schema"
    with pytest.raises(SchemaError) as recursive:
        validate_schema_document(
            {
                "type": "object",
                "properties": {"child": {"$ref": "#"}},
            }
        )
    assert recursive.value.code == "unsupported_schema"

    # A top-level applicator can reject plan_id even after it is inserted into
    # ``properties``.  Refuse those future catalog shapes at startup instead of
    # advertising an unusable or misleading MCP tool schema.
    for constrained in (
        {"allOf": [{"type": "object", "additionalProperties": False}]},
        {"propertyNames": {"pattern": "^query$"}},
        {"minProperties": 1},
        {"maxProperties": 1},
        {"const": {"query": "fixed"}},
        {"enum": [{"query": "fixed"}]},
    ):
        with pytest.raises(SchemaError) as reserved:
            inject_plan_id(
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    **constrained,
                }
            )
        assert reserved.value.code == "reserved_tool_argument"


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def test_untrusted_schema_work_is_rejected_before_general_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator_called = False

    def unexpected_general_validation(_schema: Any) -> None:
        nonlocal validator_called
        validator_called = True
        raise AssertionError("unsafe schema reached the general validator")

    monkeypatch.setattr(
        schema_module.Draft202012Validator,
        "check_schema",
        unexpected_general_validation,
    )

    catastrophic_regex = {
        "type": "object",
        "properties": {
            "value": {
                "type": "string",
                "pattern": r"^(a+)+$",
            }
        },
    }
    started = time.monotonic()
    with pytest.raises(SchemaError) as regex_error:
        validate_schema_document(catastrophic_regex)
    assert regex_error.value.code == "unsupported_schema"

    # Each definition is tiny, but following both references doubles the
    # general validator's work at every level.  The preflight expansion budget
    # must reject this compact DAG without traversing its exponential closure.
    definitions: dict[str, Any] = {"level_0": {"type": "string"}}
    for level in range(1, 20):
        previous = f"#/$defs/level_{level - 1}"
        definitions[f"level_{level}"] = {
            "allOf": [{"$ref": previous}, {"$ref": previous}]
        }
    exponential_applicators = {
        "$defs": definitions,
        "$ref": "#/$defs/level_19",
    }
    with pytest.raises(SchemaError) as applicator_error:
        validate_schema_document(exponential_applicators)
    assert applicator_error.value.code == "schema_too_complex"

    with pytest.raises(SchemaError) as unbounded_unique_items:
        validate_schema_document(
            {
                "type": "array",
                "items": {"type": "object"},
                "uniqueItems": True,
            }
        )
    assert unbounded_unique_items.value.code == "schema_too_complex"
    assert validator_called is False
    assert time.monotonic() - started < 1.0


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def test_schema_subset_preserves_current_proposal_contract_features() -> None:
    schema = {
        "type": "object",
        "$defs": {
            "create_page": {
                "type": "object",
                "required": ["type", "data"],
                "properties": {
                    "type": {"type": "string", "const": "create_page"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "string"},
                            "page_action": {"type": "string"},
                        },
                        "allOf": [
                            {
                                "anyOf": [
                                    {"required": ["page"]},
                                    {"required": ["page_action"]},
                                ]
                            }
                        ],
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            }
        },
        "required": ["actions", "retrieval_terms"],
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "oneOf": [{"$ref": "#/$defs/create_page"}],
                    "discriminator": {
                        "propertyName": "type",
                        "mapping": {
                            "create_page": "#/$defs/create_page",
                        },
                    },
                },
            },
            "retrieval_terms": {
                "type": "array",
                "items": {"type": "string", "maxLength": 80},
                "minItems": 2,
                "maxItems": 2,
                "uniqueItems": True,
            },
        },
        "additionalProperties": False,
    }

    assert validate_schema_document(schema, input_root=True) == schema
    validate_value(
        schema,
        {
            "actions": [
                {
                    "type": "create_page",
                    "data": {"page": "hash:abcdefghijkl"},
                }
            ],
            "retrieval_terms": ["primary", "secondary"],
        },
        phase="proposal",
    )


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/catalog.py::catalog_tools
def test_catalog_requires_complete_frozen_metadata_and_result_paths() -> None:
    catalog = asyncio.run(_WorkflowREST().startup())[2]
    converted = catalog_tools(catalog)
    assert converted[0].result_paths == {
        "primary_collection": "$",
        "pagination": None,
    }

    for mutate in (
        lambda value: value.pop("reference_format"),
        lambda value: value.update(selected_count=2),
        lambda value: value["tools"][0].pop("result_paths"),
        lambda value: value["tools"][0].update(result_paths=[]),
    ):
        incompatible = deepcopy(catalog)
        mutate(incompatible)
        with pytest.raises(TransportError) as error:
            catalog_tools(incompatible)
        assert error.value.code == "invalid_catalog"

    invalid_names = ("start_ask", "BadName", "bad-name", "x" * 65)
    for name in invalid_names:
        incompatible = deepcopy(catalog)
        incompatible["tools"][0]["name"] = name
        with pytest.raises(TransportError) as error:
            catalog_tools(incompatible)
        assert error.value.code == "invalid_catalog"

    conflict = deepcopy(catalog)
    conflict["tools"][0]["input_schema"]["properties"]["plan_id"] = {"type": "string"}
    with pytest.raises(SchemaError) as reserved:
        catalog_tools(conflict)
    assert reserved.value.code == "reserved_tool_argument"

    too_many = deepcopy(catalog)
    template = too_many["tools"][0]
    too_many["tools"] = [
        {**deepcopy(template), "name": f"read_{index}"} for index in range(57)
    ]
    too_many["selected_count"] = len(too_many["tools"])
    with pytest.raises(TransportError) as count_error:
        build_tool_registry(too_many)
    assert count_error.value.code == "catalog_too_large"


# @pair mcp-adapter:product-contract
def test_model_visibility_screen_rejects_catalog_reflection_and_preserves_safe_result_paths() -> (
    None
):
    api_key = "lgn_exact_catalog_reflection_secret"
    base_catalog = asyncio.run(_WorkflowREST().startup())[2]
    safe_catalog = deepcopy(base_catalog)
    safe_catalog["tools"][0]["description"] = (
        "Explain storage.googleapis.com, X-Goog-Signature, and upload_id fields."
    )
    safe_catalog["tools"][0]["result_paths"] = {
        "primary_collection": "$.items[*].url",
        "pagination": "$.next_page",
    }

    class StartupREST(_WorkflowREST):
        def __init__(self, catalog: dict[str, Any], actor: dict[str, Any]) -> None:
            super().__init__()
            self.catalog = catalog
            self.startup_actor = actor

        async def startup(self):
            return {"version": "v1"}, self.startup_actor, self.catalog

    async def initialize(
        catalog: dict[str, Any], actor: dict[str, Any]
    ) -> LagniappeAdapter:
        rest = StartupREST(catalog, actor)
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            rest=rest,  # type: ignore[arg-type]
        )
        try:
            await adapter.initialize()
        except BaseException:
            await adapter.aclose()
            raise
        return adapter

    safe_adapter = asyncio.run(initialize(safe_catalog, _actor()))
    assert safe_adapter.tools["search"].as_mcp_tool().meta == {
        "lagniappe/resultPaths": {
            "primary_collection": "$.items[*].url",
            "pagination": "$.next_page",
        }
    }
    assert safe_adapter.tools["search"].description == (
        "Explain storage.googleapis.com, X-Goog-Signature, and upload_id fields."
    )
    asyncio.run(safe_adapter.aclose())

    hostile_values: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reflected_description = deepcopy(base_catalog)
    reflected_description["tools"][0]["description"] = (
        f"Compromised metadata reflected Bearer {api_key}."
    )
    hostile_values.append((reflected_description, _actor()))

    reflected_result_path = deepcopy(base_catalog)
    reflected_result_path["tools"][0]["result_paths"] = {
        "primary_collection": _signed_download_url(),
        "pagination": None,
    }
    hostile_values.append((reflected_result_path, _actor()))

    reflected_actor = _actor()
    reflected_actor["user"]["name"] = api_key
    hostile_values.append((deepcopy(base_catalog), reflected_actor))

    for catalog, actor in hostile_values:
        with pytest.raises(TransportError) as rejected:
            asyncio.run(initialize(catalog, actor))
        rendered = rejected.value.render()
        assert rejected.value.code == "unsafe_transport_extension"
        assert api_key not in rendered
        assert "storage.googleapis.com" not in rendered
        assert "x-goog-signature" not in rendered.casefold()


# @pair mcp-adapter:product-contract
def test_model_visibility_screen_rejects_successful_output_reflection() -> None:
    api_key = "lgn_exact_result_reflection_secret"

    class ReflectingREST(_WorkflowREST):
        result: Any = []

        async def request_json(
            self, method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if target.endswith("/tools/search"):
                self.requests.append((method, target, body))
                return {"result": deepcopy(self.result)}, "request-search"
            return await super().request_json(method, target, body=body, **kwargs)

    async def exercise() -> list[str]:
        rest = ReflectingREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        rest.result = [
            "https://example.com/tools/reports/abcdefghijkl",
            "$.items[*].url",
            "ordinary storage guidance",
            "storage.googleapis.com is the documented storage hostname",
            "X-Goog-Signature and upload_id are transport field names",
        ]
        safe = await adapter.execute(
            "search", {"plan_id": "abcdefghijkl", "query": "safe"}
        )
        for reflected in (
            f"prefix {api_key} suffix",
            _signed_download_url(),
            "?X-Goog-Signature=opaque",
            "upload_id=opaque",
        ):
            rest.result = [reflected]
            with pytest.raises(TransportError) as rejected:
                await adapter.execute(
                    "search",
                    {"plan_id": "abcdefghijkl", "query": "unsafe"},
                )
            rendered = rejected.value.render()
            assert rejected.value.code == "unsafe_transport_extension"
            assert api_key not in rendered
            assert "storage.googleapis.com" not in rendered
            assert "x-goog-signature" not in rendered.casefold()
            assert "upload_id" not in rendered.casefold()
        await adapter.aclose()
        return safe.value

    assert asyncio.run(exercise()) == [
        "https://example.com/tools/reports/abcdefghijkl",
        "$.items[*].url",
        "ordinary storage guidance",
        "storage.googleapis.com is the documented storage hostname",
        "X-Goog-Signature and upload_id are transport field names",
    ]

    for reflected in (
        {"download_url": "https://example.com/private"},
        {"session_url": "opaque-session"},
        {"upload_id": "opaque-id"},
    ):
        with pytest.raises(TransportError) as rejected:
            _reject_private_model_data(reflected, bearer=api_key)
        assert rejected.value.code == "unsafe_transport_extension"

    with pytest.raises(TransportError) as encoded_bearer:
        _reject_private_model_data((b"ABC",), bearer="QUJD")
    assert encoded_bearer.value.code == "unsafe_transport_extension"


# @pair mcp-adapter:product-contract
def test_get_file_schema_projects_every_transport_extension() -> None:
    projected = get_file_output_schema(
        {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "mimetype": {"type": "string"},
                "summary": {"type": "string"},
                "content": {"type": "string"},
                "session_url": {"type": "string"},
                "original_file": {
                    "type": "object",
                    "required": ["supported", "attached", "session_token"],
                    "properties": {
                        "supported": {"type": "boolean"},
                        "attached": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "download_url": {"type": "string"},
                        "expires_in": {"type": "integer"},
                        "session_token": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "additionalProperties": True,
        }
    )

    assert set(projected["properties"]) == {
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
    assert projected["additionalProperties"] is False
    with pytest.raises(SchemaError):
        validate_value(
            projected,
            {
                "filename": "safe.txt",
                "original_file": {"supported": False, "attached": False},
                "signed_url": "https://storage.googleapis.com/private",
                "delivery": {"kind": "none"},
            },
            phase="output",
        )
    original = projected["properties"]["original_file"]
    assert set(original["properties"]) == {"supported", "attached", "reason"}
    assert original["required"] == ["supported", "attached"]
    assert original["additionalProperties"] is False


# @pair mcp-adapter:product-contract
def test_storage_url_requires_exact_resumable_and_signed_parameters() -> None:
    valid_upload = (
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o"
        "?uploadType=resumable&upload_id=opaque"
    )
    official_json_api_upload = (
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o"
        "?uploadType=resumable&name=tmp%2Ffile.png"
        "&ifGenerationMatch=0&upload_id=opaque"
    )
    assert validate_storage_url(valid_upload, upload=True) == valid_upload
    assert (
        validate_storage_url(official_json_api_upload, upload=True)
        == official_json_api_upload
    )
    assert validate_storage_url(_signed_download_url(), upload=False).startswith(
        "https://storage.googleapis.com/"
    )

    for unsafe in (
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o?upload_id=opaque",
        valid_upload + "&upload_id=second",
        valid_upload.replace("upload_id=opaque", "upload_id="),
        valid_upload + "&name=",
        valid_upload + "&ifGenerationMatch=1",
        valid_upload + "&unexpected=value",
    ):
        with pytest.raises(TransportError):
            validate_storage_url(unsafe, upload=True)
    with pytest.raises(TransportError):
        validate_storage_url(
            _signed_download_url(**{"X-Goog-Expires": "301"}), upload=False
        )


# @pair mcp-adapter:product-contract
def test_site_url_normalizes_only_canonical_https_or_loopback_origins() -> None:
    assert (
        normalize_site_url("https://EXAMPLE.com:443/").origin == "https://example.com"
    )
    assert normalize_site_url("http://127.0.0.1:5050").origin == "http://127.0.0.1:5050"
    assert normalize_site_url("http://[::1]:5050").origin == "http://[::1]:5050"
    for unsafe in (
        "http://example.com",
        "https://example.com:444",
        "https://user@example.com",
        "https://example.com/path",
        "https://example.com./",
        "https://münich.example",
        "https://bad_host.example",
        "http://127.0.0.1:0",
    ):
        with pytest.raises(ConfigurationError):
            normalize_site_url(unsafe)


class _CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.headers: httpx.Headers | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.headers = request.headers
        return httpx.Response(
            200,
            headers={"Content-Length": "3", "Content-Type": "image/png"},
            content=b"png",
            request=request,
        )


# @pair mcp-adapter:product-contract
def test_media_download_does_not_inherit_client_credentials_or_cookies() -> None:
    async def exercise() -> tuple[bytes, str, httpx.Headers]:
        transport = _CaptureTransport()
        storage = httpx.AsyncClient(
            transport=transport,
            auth=httpx.BasicAuth("wrong", "secret"),
            cookies={"session": "secret"},
        )
        config = ConnectionConfig(
            normalize_site_url("https://example.com"), "api-secret"
        )
        rest = RESTClient(config, storage_client=storage)
        try:
            data, mime = await rest.download_media(_signed_download_url(), cap=1024)
            assert transport.headers is not None
            return data, mime, transport.headers
        finally:
            await rest.aclose()
            await storage.aclose()

    data, mime, headers = asyncio.run(exercise())
    assert (data, mime) == (b"png", "image/png")
    assert "authorization" not in headers
    assert "cookie" not in headers


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
def test_original_media_enforces_length_cap_status_and_redirect_boundaries() -> None:
    class MediaTransport(httpx.AsyncBaseTransport):
        def __init__(self, outcomes: list[tuple[int, dict[str, str], bytes]]) -> None:
            self.outcomes = list(outcomes)
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            status, headers, data = self.outcomes.pop(0)
            return httpx.Response(
                status,
                headers=headers,
                stream=httpx.ByteStream(data),
                request=request,
            )

    async def exercise() -> tuple[list[str], int]:
        transport = MediaTransport(
            [
                (200, {"Content-Type": "image/png"}, b"x"),
                (
                    200,
                    {"Content-Type": "image/png", "Content-Length": "2"},
                    b"x",
                ),
                (
                    200,
                    {"Content-Type": "image/png", "Content-Length": "5"},
                    b"12345",
                ),
                (302, {"Location": "https://attacker.invalid"}, b""),
                (
                    404,
                    {"Content-Type": "application/json", "Content-Length": "2"},
                    b"{}",
                ),
            ]
        )
        storage = httpx.AsyncClient(transport=transport)
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            storage_client=storage,
        )
        codes: list[str] = []
        try:
            for cap in (16, 16, 4, 16, 16):
                with pytest.raises(TransportError) as caught:
                    await rest.download_media(_signed_download_url(), cap=cap)
                codes.append(caught.value.code)
            return codes, transport.calls
        finally:
            await rest.aclose()
            await storage.aclose()

    codes, calls = asyncio.run(exercise())
    assert codes == [
        "invalid_download",
        "invalid_download",
        "media_too_large",
        "redirect_rejected",
        "download_failed",
    ]
    assert calls == 5


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
@pytest.mark.parametrize(
    ("mime_type", "kind"),
    [("image/png", "image"), ("audio/mpeg", "audio")],
)
def test_original_media_delivery_matches_the_emitted_content_index(
    mime_type: str,
    kind: str,
) -> None:
    rest = _WorkflowREST()

    async def download_media(_url: str, *, cap: int):
        assert cap == MAX_MEDIA_RAW_BYTES
        return b"original-bytes", mime_type

    rest.download_media = download_media
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
        rest=rest,  # type: ignore[arg-type]
    )
    raw = {
        "content": "extracted text",
        "mimetype": mime_type,
        "original_file": {
            "supported": True,
            "attached": False,
            "download_url": _signed_download_url(),
            "expires_in": 300,
        },
    }
    result = asyncio.run(adapter._project_file_result(raw, {"include_original": True}))
    rendered = _success_result(result).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert result.value["delivery"] == {
        "kind": kind,
        "mime_type": mime_type,
        "size_bytes": len(b"original-bytes"),
        "content_index": 1,
    }
    assert rendered["content"][1]["type"] == kind
    assert rendered["content"][1]["mimeType"] == mime_type
    assert "storage.googleapis.com" not in json.dumps(rendered)
    asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
def test_original_media_rejects_unsupported_binary_after_safe_download() -> None:
    rest = _WorkflowREST()

    async def download_media(_url: str, *, cap: int):
        assert cap == MAX_MEDIA_RAW_BYTES
        return b"pdf", "application/pdf"

    rest.download_media = download_media
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
        rest=rest,  # type: ignore[arg-type]
    )
    raw = {
        "content": "extracted text",
        "mimetype": "application/pdf",
        "original_file": {
            "supported": True,
            "attached": False,
            "download_url": _signed_download_url(),
            "expires_in": 300,
        },
    }
    try:
        with pytest.raises(TransportError) as caught:
            asyncio.run(adapter._project_file_result(raw, {"include_original": True}))
        assert caught.value.code == "unsupported_media"
        assert "storage.googleapis.com" not in caught.value.render()
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_api_request_uses_only_explicit_bearer_credentials() -> None:
    class APICaptureTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.request: httpx.Request | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.request = request
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"ok": True},
                request=request,
            )

    async def exercise() -> tuple[Any, httpx.Request]:
        transport = APICaptureTransport()
        injected = httpx.AsyncClient(
            transport=transport,
            auth=httpx.BasicAuth("wrong", "secret"),
            cookies={"session": "secret"},
            headers={"X-Unrelated-Default": "must-not-leak"},
        )
        config = ConnectionConfig(
            normalize_site_url("https://example.com"), "api-secret"
        )
        rest = RESTClient(config, client=injected)
        try:
            value, _request_id = await rest.request_json(
                "POST", "plans", body={"kind": "ask"}
            )
            assert transport.request is not None
            return value, transport.request
        finally:
            await rest.aclose()
            await injected.aclose()

    value, request = asyncio.run(exercise())
    assert value == {"ok": True}
    assert request.headers["authorization"] == "Bearer api-secret"
    assert request.headers["content-type"] == "application/json"
    assert "cookie" not in request.headers
    assert "x-unrelated-default" not in request.headers
    assert request.content == b'{"kind":"ask"}'


# @matrix hosted-e2e mcp-adapter : authentication transport origin-isolation
def test_hosted_driver_transport_scopes_only_run_cookie():
    requests = []

    async def exercise():
        transport = mcp_client_driver.HostedRunTransport(
            "https://hosted.example",
            "run-cookie",
            httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200)
            ),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get(
                "https://hosted.example/api/v1",
                headers={
                    "Authorization": "Bearer api-key",
                    "Cookie": "session=must-not-forward",
                },
            )
            for target in (
                "https://storage.googleapis.com/object",
                "http://hosted.example/api/v1",
                "https://hosted.example:444/api/v1",
                "https://hosted.example.evil/api/v1",
            ):
                with pytest.raises(RuntimeError, match="different origin"):
                    await client.get(target)

    asyncio.run(exercise())
    assert len(requests) == 1
    assert requests[0].headers["Cookie"] == "__Host-lagniappe-e2e=run-cookie"
    assert requests[0].headers["Authorization"] == "Bearer api-key"


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/errors.py::AdapterError
def test_bounded_error_rendering_remains_valid_json() -> None:
    error = AdapterError(
        "validation_failed",
        "The request contains invalid fields.",
        status=422,
        request_id="request-123",
        details={"items": ["x" * 1024] * 20},
    )

    rendered = error.render()
    assert len(rendered.encode("utf-8")) <= MAX_ERROR_BYTES
    assert json.loads(rendered) == {
        "code": "validation_failed",
        "message": "The request contains invalid fields.",
        "retryable": False,
        "http_status": 422,
        "request_id": "request-123",
        "details": {"truncated": True},
    }

    control_heavy = AdapterError(
        "\x00" * 200,
        "\x00" * 2048,
        retryable=True,
        status=503,
    ).render()
    assert len(control_heavy.encode("utf-8")) <= MAX_ERROR_BYTES
    assert json.loads(control_heavy) == {
        "code": "adapter_error",
        "message": "The bounded error could not be rendered safely.",
        "retryable": True,
        "http_status": 503,
    }


# @pair mcp-adapter:product-contract
def test_api_errors_redact_credentials_and_duplicate_json_is_rejected() -> None:
    signed = _signed_download_url()

    async def exercise() -> tuple[AdapterError, TransportError]:
        responses = [
            httpx.Response(
                422,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": "super-secret",
                },
                json={
                    "error": {
                        "code": "validation_failed",
                        "message": f"super-secret appeared beside {signed}",
                        "details": {
                            "api_key": "super-secret",
                            "nested": [signed, "upload_id=opaque"],
                        },
                    }
                },
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b'{"value":1,"value":2}',
            ),
        ]

        async def handler(request: httpx.Request) -> httpx.Response:
            response = responses.pop(0)
            response.request = request
            return response

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "super-secret"),
            client=injected,
        )
        try:
            with pytest.raises(AdapterError) as api_error:
                await rest.request_json("GET", "me")
            with pytest.raises(TransportError) as duplicate_error:
                await rest.request_json("GET", "me")
            return api_error.value, duplicate_error.value
        finally:
            await rest.aclose()
            await injected.aclose()

    api_error, duplicate_error = asyncio.run(exercise())
    rendered = api_error.render()
    assert api_error.code == "validation_failed"
    assert "super-secret" not in rendered
    assert "storage.googleapis.com" not in rendered
    assert "upload_id=opaque" not in rendered
    assert duplicate_error.code == "invalid_response"


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
@pytest.mark.parametrize("status", [401, 403, 404, 409, 422, 429, 500, 503])
def test_api_status_errors_remain_typed_text_only_and_are_never_retried(
    status: int,
) -> None:
    async def exercise() -> tuple[AdapterError, int]:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                status,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": request.headers["x-request-id"],
                },
                json={
                    "error": {
                        "code": f"status_{status}",
                        "message": "A bounded API failure.",
                        "details": {"field": "proposal"},
                    },
                    "request_id": request.headers["x-request-id"],
                },
                request=request,
            )

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=injected,
        )
        try:
            with pytest.raises(AdapterError) as caught:
                await rest.request_json("POST", "plans", body={"tool": "ask"})
            return caught.value, calls
        finally:
            await rest.aclose()
            await injected.aclose()

    error, calls = asyncio.run(exercise())
    assert calls == 1
    assert error.code == f"status_{status}"
    assert error.status == status
    assert error.request_id is not None
    assert error.request_id.startswith("mcp-")
    # A returned 429 is an unambiguous rejection with a server wait hint.
    # Stateful POST failures remain non-retryable even for transient 5xx status.
    assert error.retryable is (status == 429)
    result = _error_result(error).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert result["isError"] is True
    assert result["resultType"] == "complete"
    assert "structuredContent" not in result


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def test_api_transport_failures_are_bounded_distinct_and_never_retried() -> None:
    async def exercise() -> tuple[list[str], int]:
        outcomes: list[object] = [
            httpx.Response(302, headers={"Location": "https://attacker.invalid"}),
            httpx.Response(200, headers={"Content-Type": "text/html"}, text="no"),
            httpx.Response(
                200, headers={"Content-Type": "application/json"}, content=b"{"
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json", "Content-Length": "9"},
                content=b'{"ok":1}',
            ),
            "timeout",
            "connection",
            "cancel",
        ]
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            outcome = outcomes.pop(0)
            if outcome == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if outcome == "connection":
                raise httpx.ConnectError("unavailable", request=request)
            if outcome == "cancel":
                raise asyncio.CancelledError
            assert isinstance(outcome, httpx.Response)
            outcome.request = request
            return outcome

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=injected,
        )
        codes: list[str] = []
        try:
            for max_bytes in (1024, 1024, 1024, 4, 1024, 1024):
                with pytest.raises(AdapterError) as caught:
                    await rest.request_json("GET", "me", max_bytes=max_bytes)
                codes.append(caught.value.code)
                assert len(caught.value.render().encode("utf-8")) <= 4096
            with pytest.raises(asyncio.CancelledError):
                await rest.request_json("GET", "me")
            return codes, calls
        finally:
            await rest.aclose()
            await injected.aclose()

    codes, calls = asyncio.run(exercise())
    assert codes == [
        "redirect_rejected",
        "invalid_response",
        "invalid_response",
        "response_too_large",
        "api_timeout",
        "api_unavailable",
    ]
    assert calls == 7


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def test_api_retryability_distinguishes_safe_reads_from_ambiguous_posts() -> None:
    async def exercise(method: str, outcome: str) -> TransportError:
        async def handler(request: httpx.Request) -> httpx.Response:
            if outcome == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if outcome == "connection":
                raise httpx.ConnectError("unavailable", request=request)
            return httpx.Response(
                503,
                headers={"Content-Type": "application/json"},
                json={},
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=client,
        )
        try:
            with pytest.raises(TransportError) as caught:
                await rest.request_json(
                    method, "plans", body={} if method == "POST" else None
                )
            return caught.value
        finally:
            await rest.aclose()
            await client.aclose()

    for outcome in ("timeout", "connection", "status"):
        assert asyncio.run(exercise("GET", outcome)).retryable is True
        assert asyncio.run(exercise("POST", outcome)).retryable is False


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
def test_rest_operations_have_total_wall_clock_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import rest as rest_module

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": "2",
            },
            content=b"{}",
            request=request,
        )

    async def exercise() -> tuple[TransportError, TransportError]:
        api_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
        storage_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=api_client,
            storage_client=storage_client,
        )
        try:
            with pytest.raises(TransportError) as api_error:
                await rest.request_json("GET", "me")
            with pytest.raises(TransportError) as media_error:
                await rest.download_media(_signed_download_url(), cap=1024)
            return api_error.value, media_error.value
        finally:
            await rest.aclose()
            await api_client.aclose()
            await storage_client.aclose()

    monkeypatch.setattr(rest_module, "RESPONSE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(rest_module, "MEDIA_TIMEOUT_SECONDS", 0.01)
    api_error, media_error = asyncio.run(exercise())
    assert (api_error.code, api_error.retryable) == ("api_timeout", True)
    assert (media_error.code, media_error.retryable) == ("download_timeout", True)


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/presentation.py::_success_result
def test_structured_and_complete_frame_limits_fail_as_tool_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = AdapterResult({"value": "x" * MAX_STRUCTURED_RESULT_BYTES})
    with pytest.raises(TransportError) as structured:
        LagniappeAdapter._enforce_result_limits(oversized)
    assert structured.value.code == "result_too_large"

    from lagniappe_mcp import presentation as server_module

    monkeypatch.setattr(server_module, "MAX_COMPLETE_FRAME_BYTES", 128)
    with pytest.raises(TransportError) as frame:
        _success_result(AdapterResult({"value": "bounded"}))
    assert frame.value.code == "result_too_large"

    monkeypatch.setattr(server_module, "MAX_COMPLETE_FRAME_BYTES", 1024)
    with pytest.raises(TransportError) as request_id_frame:
        _success_result(
            AdapterResult({"value": "bounded"}),
            request_id="r" * 900,
            server_info={"name": "lagniappe", "version": "test"},
        )
    assert request_id_frame.value.code == "result_too_large"


def test_mcp_driver_persists_only_owner_only_bounded_privacy_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "lgn_driver_result_secret"
    csrf_token = "driver-csrf-secret"
    session_cookie = "driver-session-secret"
    upload_path = tmp_path / "boundary-note.txt"
    signed_url = _signed_download_url()
    specification = {
        "upload_path": str(upload_path),
        "revoke": {
            "csrf_token": csrf_token,
            "cookies": {"session": session_cookie},
        },
    }
    specification_path = tmp_path / "driver-specification.json"
    result_path = tmp_path / "driver-result.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    async def leaking_workflow(_specification: dict[str, Any]):
        return (
            {
                "many": [signed_url for _index in range(100)],
                "storage": {"googleapis": {"com": f"nested reflection {api_key}"}},
                api_key: "credential also appeared in an object key",
                "credential": f"reflected Bearer {api_key}",
                "local_path": f"opened {upload_path}",
                "transport": signed_url,
            },
            f"stderr reflected {csrf_token} and {session_cookie}",
        )

    temporary_modes: list[int] = []
    real_replace = mcp_client_driver.os.replace

    def capture_replace(source: str | Path, destination: str | Path) -> None:
        temporary_modes.append(stat.S_IMODE(Path(source).stat().st_mode))
        real_replace(source, destination)

    monkeypatch.setenv("LAGNIAPPE_API_KEY", api_key)
    monkeypatch.setenv("LAGNIAPPE_URL", "https://example.com")
    monkeypatch.setattr(mcp_client_driver, "_workflow", leaking_workflow)
    monkeypatch.setattr(mcp_client_driver.os, "replace", capture_replace)

    status = mcp_client_driver.main(
        ["workflow", str(specification_path), str(result_path)]
    )

    assert status == 1
    assert temporary_modes == [0o600]
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(f".{result_path.name}.*.tmp"))
    assert result_path.stat().st_size <= 8 * 1024
    persisted = result_path.read_text(encoding="utf-8")
    for private in (
        api_key,
        csrf_token,
        session_cookie,
        str(upload_path),
        "storage.googleapis.com",
        "x-goog-",
        "upload_id",
    ):
        assert private.casefold() not in persisted.casefold()
    value = json.loads(persisted)
    assert set(value) == {
        "diagnostics",
        "driver_error",
        "privacy_findings",
        "privacy_findings_truncated",
    }
    assert value["driver_error"] == "MCP evidence failed privacy screening."
    assert value["diagnostics"]["contains_sensitive_value"] is True
    assert value["privacy_findings_truncated"] is True
    assert value["privacy_findings"]
    assert len(value["privacy_findings"]) <= 24
    assert {finding["kind"] for finding in value["privacy_findings"]} == {
        "credential",
        "local_path",
        "transport",
    }
    assert all(
        set(finding) == {"kind", "path", "redacted", "type"}
        and finding["redacted"] is True
        and len(finding["path"]) <= 160
        and finding["type"] in {"object_key", "string"}
        for finding in value["privacy_findings"]
    )

    async def leaking_failure(_specification: dict[str, Any]):
        raise RuntimeError(f"failed with {api_key} at {upload_path}: {signed_url}")

    failed_result_path = tmp_path / "driver-failed-result.json"
    monkeypatch.setattr(mcp_client_driver, "_workflow", leaking_failure)
    failed_status = mcp_client_driver.main(
        ["workflow", str(specification_path), str(failed_result_path)]
    )
    failed_persisted = failed_result_path.read_text(encoding="utf-8")

    assert failed_status == 1
    assert temporary_modes == [0o600, 0o600]
    assert stat.S_IMODE(failed_result_path.stat().st_mode) == 0o600
    assert json.loads(failed_persisted)["driver_error"] == (
        "MCP evidence failed privacy screening."
    )
    for private in (api_key, str(upload_path), "storage.googleapis.com", "x-goog-"):
        assert private.casefold() not in failed_persisted.casefold()


# @pair mcp-adapter:product-contract
def test_failed_concurrent_startup_cancels_sibling_requests() -> None:
    class FailingStartup:
        def __init__(self) -> None:
            self.cancelled: set[str] = set()

        async def request_json(self, _method: str, target: str, **_kwargs: Any):
            if target == "":
                await asyncio.sleep(0)
                raise TransportError("startup_failed", "startup failed")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.add(target)
                raise

    fake = FailingStartup()
    with pytest.raises(TransportError):
        asyncio.run(RESTClient.startup(fake))  # type: ignore[arg-type]
    assert fake.cancelled == {"me", "tools"}


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def test_plan_start_rejects_whitespace_instructions_before_dispatch() -> None:
    async def exercise() -> list[tuple[str, str, Any]]:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(
                normalize_site_url("https://example.com"),
                "api-secret",
            ),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        with pytest.raises(SchemaError) as rejected:
            await adapter.execute("start_ask", {"instructions": " \t\n "})
        assert rejected.value.code == "input_validation_failed"
        await adapter.aclose()
        return rest.requests

    assert asyncio.run(exercise()) == []


@pytest.mark.parametrize(
    ("status", "code"), [(401, "unauthorized"), (403, "forbidden")]
)
# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
def test_published_tools_still_honor_next_request_revocation_or_permission_loss(
    status: int,
    code: str,
) -> None:
    class AccessREST(_WorkflowREST):
        blocked = False

        async def request_json(
            self, method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if self.blocked and target.endswith("/tools/search"):
                self.requests.append((method, target, body))
                raise AdapterError(
                    code,
                    "Access changed after MCP tool discovery.",
                    status=status,
                )
            return await super().request_json(
                method,
                target,
                body=body,
                **kwargs,
            )

    async def exercise() -> tuple[AdapterError, AccessREST]:
        rest = AccessREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(
                normalize_site_url("https://example.com"),
                "api-secret",
            ),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        assert "search" in adapter.tools
        rest.blocked = True
        with pytest.raises(AdapterError) as rejected:
            await adapter.execute(
                "search",
                {"plan_id": "abcdefghijkl", "query": "must reauthorize"},
            )
        await adapter.aclose()
        return rejected.value, rest

    rejected, rest = asyncio.run(exercise())
    assert (rejected.code, rejected.status) == (code, status)
    assert rest.requests == [
        (
            "POST",
            "plans/abcdefghijkl/tools/search",
            {"arguments": {"query": "must reauthorize"}},
        )
    ]


# @pair mcp-adapter:product-contract
def test_adapter_executes_only_typed_lifecycle_and_catalog_routes() -> None:
    async def exercise() -> tuple[_WorkflowREST, dict[str, Any]]:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(
                normalize_site_url("https://example.com"),
                "api-secret",
            ),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        assert list(adapter.tools)[-1] == "search"
        assert adapter.tools["search"].as_mcp_tool().meta == {
            "lagniappe/resultPaths": {
                "primary_collection": "$",
                "pagination": None,
            }
        }

        actor = await adapter.execute("get_actor", {})
        assert actor.value["user"]["hash"] == "abcdefghijkl"
        started = await adapter.execute(
            "start_create", {"instructions": "Prepare one safe change."}
        )
        assert (
            not {
                "contract_url",
                "submit_url",
                "status_url",
                "upload_batch_id",
            }
            & started.value.keys()
        )
        fetched = await adapter.execute("get_plan", {"plan_id": "abcdefghijkl"})
        assert fetched.value["id"] == "abcdefghijkl"
        projected = await adapter.execute(
            "get_plan_contract", {"plan_id": "abcdefghijkl"}
        )
        assert "submission_format" not in projected.value
        assert (
            projected.value["mcp_submission"]["proposal_schema"] == "$.proposal_schema"
        )
        searched = await adapter.execute(
            "search", {"plan_id": "abcdefghijkl", "query": "needle"}
        )
        assert searched.value == ["first", "second"]
        await adapter.aclose()
        return rest, projected.value

    rest, projected = asyncio.run(exercise())
    assert projected["proposal_schema"]["required"] == ["title"]
    assert (
        "POST",
        "plans",
        {"tool": "create", "instructions": "Prepare one safe change."},
    ) in rest.requests
    assert (
        "POST",
        "plans/abcdefghijkl/tools/search",
        {"arguments": {"query": "needle"}},
    ) in rest.requests

    unsafe_actor = _actor()
    unsafe_actor["credential"]["api_key"] = "must-not-cross-mcp"
    with pytest.raises(SchemaError):
        validate_value(lifecycle_tools()[0].output_schema, unsafe_actor, phase="output")


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_plan_start_rejects_a_valid_plan_for_the_wrong_requested_tool() -> None:
    async def exercise() -> None:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        with pytest.raises(TransportError) as error:
            await adapter.execute(
                "start_ask",
                {"instructions": "Answer one question."},
            )
        assert error.value.code == "invalid_response"
        assert rest.requests[-1] == (
            "POST",
            "plans",
            {"tool": "ask", "instructions": "Answer one question."},
        )
        await adapter.aclose()

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_read_arguments_and_results_are_validated_at_the_dispatch_boundary() -> None:
    async def exercise() -> None:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        before = list(rest.requests)
        with pytest.raises(SchemaError) as invalid_input:
            await adapter.execute("search", {"plan_id": "abcdefghijkl"})
        assert invalid_input.value.code == "input_validation_failed"
        assert rest.requests == before

        original_request = rest.request_json

        async def invalid_result(
            method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if target.endswith("/tools/search"):
                rest.requests.append((method, target, body))
                return {"result": [1]}, "request-invalid-result"
            return await original_request(method, target, body=body, **kwargs)

        rest.request_json = invalid_result  # type: ignore[method-assign]
        with pytest.raises(SchemaError) as invalid_output:
            await adapter.execute(
                "search", {"plan_id": "abcdefghijkl", "query": "needle"}
            )
        assert invalid_output.value.code == "upstream_output_validation_failed"
        assert rest.requests[-1][1] == "plans/abcdefghijkl/tools/search"
        await adapter.aclose()

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_lifecycle_transport_and_human_links_fail_closed() -> None:
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    )
    try:
        transport_variants = (
            "https://attacker.invalid/api/v1/plans/abcdefghijkl/contract",
            "https://user@example.com/api/v1/plans/abcdefghijkl/contract",
            "https://example.com:444/api/v1/plans/abcdefghijkl/contract",
            "https://example.com/not-api/plans/abcdefghijkl/contract",
            "https://example.com/api/v1/plans/other/contract",
            "https://example.com/api/v1/plans/abcdefghijkl/contract?next=1",
        )
        for value in transport_variants:
            plan = _plan()
            plan["contract_url"] = value
            with pytest.raises(TransportError) as error:
                adapter._safe_plan(plan)
            assert error.value.code == "incompatible_url"
            assert "attacker.invalid" not in error.value.render()

        human_variants = (
            "https://attacker.invalid/tools/api-plan/abcdefghijkl",
            "https://example.com/tools/api-plan/abcdefghijkl?token=secret",
            "https://example.com/unexpected/abcdefghijkl",
        )
        for value in human_variants:
            plan = _plan()
            plan["preview_url"] = value
            with pytest.raises(TransportError) as error:
                adapter._safe_plan(plan)
            assert error.value.code == "incompatible_link"
            assert "token=secret" not in error.value.render()
    finally:
        asyncio.run(adapter.aclose())

    class HostileContractREST(_WorkflowREST):
        async def request_json(
            self, method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if target.endswith("/contract"):
                self.requests.append((method, target, body))
                value = _contract()
                value["submission_format"]["url"] = (
                    "https://attacker.invalid/api/v1/plans/abcdefghijkl/submit"
                )
                return value, "request-contract"
            return await super().request_json(method, target, body=body, **kwargs)

    async def reject_submission() -> HostileContractREST:
        rest = HostileContractREST()
        candidate = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await candidate.initialize()
        with pytest.raises(TransportError) as error:
            await candidate.execute(
                "submit_plan",
                {
                    "plan_id": "abcdefghijkl",
                    "contract_version": CONTRACT_VERSION_MAX,
                    "proposal": {"title": "Safe"},
                },
            )
        assert error.value.code == "incompatible_url"
        assert not any(
            method == "POST"
            for method, target, _ in rest.requests
            if target.endswith("/submit")
        )
        await candidate.aclose()
        return rest

    rejected = asyncio.run(reject_submission())
    assert [target for _, target, _ in rejected.requests].count(
        "plans/abcdefghijkl/contract"
    ) == 1


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_lifecycle_responses_reject_values_outside_the_frozen_contract() -> None:
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    )
    try:
        invalid_plans: list[dict[str, Any]] = []
        for field, value in (
            ("status", "queued"),
            ("name", None),
            ("contract_version", CONTRACT_VERSION_MAX + 1),
        ):
            plan = _plan()
            plan[field] = value
            invalid_plans.append(plan)
        invalid_file = _plan()
        invalid_file["files"] = [
            {
                "ref": "not-a-reference",
                "name": None,
                "filename": "file.txt",
                "mimetype": "text/plain",
                "size": -1,
            }
        ]
        invalid_plans.append(invalid_file)

        for plan in invalid_plans:
            with pytest.raises(SchemaError) as plan_error:
                adapter._safe_plan(plan)
            assert plan_error.value.code == "upstream_output_validation_failed"

        receipt = {
            "id": "abcdefghijkl",
            "status": "ready",
            "preview_url": "https://example.com/tools/api-plan/abcdefghijkl",
            "review_url": "https://example.com/tools/reports/abcdefghijkl",
            "status_url": "https://example.com/api/v1/plans/abcdefghijkl",
            "contract_version": CONTRACT_VERSION_MAX,
            "proposal_fingerprint": "f" * 64,
        }
        for field, value in (
            ("status", "draft"),
            ("contract_version", CONTRACT_VERSION_MAX + 1),
            ("proposal_fingerprint", ""),
        ):
            invalid_receipt = {**receipt, field: value}
            with pytest.raises(SchemaError) as receipt_error:
                adapter._safe_receipt(invalid_receipt, expected_plan_id="abcdefghijkl")
            assert receipt_error.value.code == "upstream_output_validation_failed"
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper() -> None:
    async def exercise() -> _WorkflowREST:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        with pytest.raises(SchemaError) as stale:
            await adapter.execute(
                "submit_plan",
                {"plan_id": "abcdefghijkl", "contract_version": 5, "proposal": {}},
            )
        assert stale.value.code == "stale_contract_version"
        with pytest.raises(SchemaError):
            await adapter.execute(
                "submit_plan",
                {
                    "plan_id": "abcdefghijkl",
                    "contract_version": CONTRACT_VERSION_MAX,
                    "proposal": {"title": 7},
                },
            )
        assert not any(target.endswith("/submit") for _, target, _ in rest.requests)

        receipt = await adapter.execute(
            "submit_plan",
            {
                "plan_id": "abcdefghijkl",
                "contract_version": CONTRACT_VERSION_MAX,
                "proposal": {"title": "Approved in the browser"},
            },
        )
        assert receipt.value["status"] == "ready"
        assert "status_url" not in receipt.value
        await adapter.aclose()
        return rest

    rest = asyncio.run(exercise())
    assert sum(target.endswith("/contract") for _, target, _ in rest.requests) == 3
    assert rest.requests[-1] == (
        "POST",
        "https://example.com/api/v1/plans/abcdefghijkl/submit",
        {
            "contract_version": CONTRACT_VERSION_MAX,
            "proposal": {"title": "Approved in the browser"},
        },
    )


# @pair mcp-adapter:product-contract
def test_mcp_v2_results_use_direct_structured_values_and_complete_aliases() -> None:
    success = _success_result(AdapterResult([{"hash": "abcdefghijkl"}]))
    dumped = success.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped["resultType"] == "complete"
    assert dumped["structuredContent"] == [{"hash": "abcdefghijkl"}]
    assert dumped["content"] == [{"type": "text", "text": '[{"hash":"abcdefghijkl"}]'}]

    error = _error_result(TransportError("failed", "Bounded failure."))
    dumped_error = error.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped_error["resultType"] == "complete"
    assert dumped_error["isError"] is True
    assert "structuredContent" not in dumped_error


# @pair mcp-adapter:product-contract
def test_wrapped_result_schema_preserves_local_references() -> None:
    schema = validate_schema_document(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"amount": {"type": "integer", "minimum": 1}},
            "type": "array",
            "items": {
                "oneOf": [{"$ref": "#/items/$defs/entry"}],
                "discriminator": {
                    "propertyName": "kind",
                    "mapping": {"entry": "#/items/$defs/entry"},
                },
                "$defs": {
                    "entry": {
                        "type": "object",
                        "properties": {
                            "kind": {"const": "entry"},
                            "amount": {"$ref": "#/$defs/amount"},
                            "literal": {"const": "#/$defs/amount"},
                        },
                        "required": ["kind", "amount", "literal"],
                    }
                },
            },
        }
    )
    original = deepcopy(schema)
    wrapped = wrap_result_schema(schema)
    assert schema == original
    assert wrapped["properties"]["result"]["items"]["discriminator"]["mapping"] == {
        "entry": "#/properties/result/items/$defs/entry",
    }
    value = [{"kind": "entry", "amount": 1, "literal": "#/$defs/amount"}]
    validate_schema_document(wrapped)
    validate_value(wrapped, {"result": value}, phase="output")
    for invalid in (
        {},
        value,
        {"result": value, "extra": True},
        {
            "result": [
                {
                    "kind": "entry",
                    "amount": 0,
                    "literal": "#/$defs/amount",
                }
            ]
        },
    ):
        with pytest.raises(SchemaError):
            validate_value(wrapped, invalid, phase="output")


# @pair mcp-adapter:product-contract
def test_requested_unsupported_original_is_a_bounded_tool_error() -> None:
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    adapter = LagniappeAdapter(config)
    raw = {
        "filename": "notes.txt",
        "mimetype": "text/plain",
        "summary": "Safe metadata",
        "content": "Extracted text",
        "session_url": "https://storage.googleapis.com/private?upload_id=secret",
        "original_file": {
            "supported": False,
            "attached": False,
            "reason": "Unavailable",
        },
    }
    try:
        with pytest.raises(TransportError) as error:
            asyncio.run(adapter._project_file_result(raw, {"include_original": True}))
        assert error.value.code == "unsupported_media"
        assert len(error.value.render().encode("utf-8")) < 4096
        projected = asyncio.run(
            adapter._project_file_result(raw, {"include_original": False})
        )
        assert "session_url" not in projected.value
        assert projected.value["filename"] == "notes.txt"
        assert projected.value["mimetype"] == "text/plain"
        assert projected.value["summary"] == "Safe metadata"
        domain_error = asyncio.run(
            adapter._project_file_result(
                {"error": "File not found"}, {"include_original": False}
            )
        )
        assert domain_error.value == {
            "error": "File not found",
            "delivery": {"kind": "none"},
        }
        with pytest.raises(TransportError) as extension_error:
            asyncio.run(
                adapter._project_file_result(
                    {
                        **raw,
                        "signed_url": _signed_download_url(),
                    },
                    {"include_original": False},
                )
            )
        assert extension_error.value.code == "unsafe_transport_extension"
        for alias in ("href", "location"):
            with pytest.raises(TransportError) as alias_error:
                asyncio.run(
                    adapter._project_file_result(
                        {
                            **raw,
                            alias: _signed_download_url(),
                        },
                        {"include_original": False},
                    )
                )
            assert alias_error.value.code == "unsafe_transport_extension"
        with pytest.raises(TransportError) as value_error:
            asyncio.run(
                adapter._project_file_result(
                    {
                        **raw,
                        "summary": _signed_download_url(),
                    },
                    {"include_original": False},
                )
            )
        assert value_error.value.code == "unsafe_transport_extension"
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_requested_missing_original_is_a_bounded_tool_error() -> None:
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    adapter = LagniappeAdapter(config)
    try:
        with pytest.raises(TransportError) as error:
            asyncio.run(
                adapter._project_file_result(
                    {"content": "Extracted text"}, {"include_original": True}
                )
            )
        assert error.value.code == "original_unavailable"
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_original_download_mime_must_match_upstream_file_metadata() -> None:
    """Transport-only file metadata still constrains emitted MCP media."""
    rest = _WorkflowREST()
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    adapter = LagniappeAdapter(config, rest=rest)

    async def download_media(_url: str, *, cap: int):
        assert cap == MAX_MEDIA_RAW_BYTES
        return b"not-a-png", "audio/mpeg"

    rest.download_media = download_media
    raw = {
        "content": "extracted text",
        "mimetype": "image/png",
        "original_file": {
            "supported": True,
            "attached": False,
            "download_url": _signed_download_url(),
            "expires_in": 300,
        },
    }

    try:
        with pytest.raises(TransportError) as error:
            asyncio.run(adapter._project_file_result(raw, {"include_original": True}))
        assert error.value.code == "mime_mismatch"
    finally:
        asyncio.run(adapter.aclose())


def test_standalone_sources_have_no_application_imports() -> None:
    sources = [Path(__file__), *(PACKAGE_ROOT / "src" / "lagniappe_mcp").glob("*.py")]
    imported: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text())
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
    assert not any(
        name == "lagniappe" or name.startswith("lagniappe.") for name in imported
    )


_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {
        "name": "lagniappe-adapter-test",
        "version": "1",
    },
    "io.modelcontextprotocol/clientCapabilities": {},
}


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient
def test_rest_rejects_encoded_or_over_cap_raw_bodies_before_buffering() -> None:
    class NeverRead(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.iterated = False

        async def __aiter__(self):
            self.iterated = True
            raise AssertionError("encoded response body must not be consumed")
            yield b""  # pragma: no cover

    class OneChunk(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 64

    async def exercise() -> tuple[list[str], list[str], bool, bool]:
        api_encoded = NeverRead()
        storage_encoded = NeverRead()
        api_outcomes: list[httpx.Response] = [
            httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                    "Content-Length": "1",
                },
                stream=api_encoded,
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=OneChunk(),
            ),
        ]
        storage_outcomes: list[httpx.Response] = [
            httpx.Response(
                200,
                headers={
                    "Content-Type": "image/png",
                    "Content-Encoding": "br",
                    "Content-Length": "1",
                },
                stream=storage_encoded,
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "image/png", "Content-Length": "4"},
                stream=OneChunk(),
            ),
        ]

        async def api_handler(request: httpx.Request) -> httpx.Response:
            response = api_outcomes.pop(0)
            response.request = request
            return response

        async def storage_handler(request: httpx.Request) -> httpx.Response:
            response = storage_outcomes.pop(0)
            response.request = request
            return response

        api_client = httpx.AsyncClient(transport=httpx.MockTransport(api_handler))
        storage_client = httpx.AsyncClient(
            transport=httpx.MockTransport(storage_handler)
        )
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=api_client,
            storage_client=storage_client,
        )
        api_codes: list[str] = []
        storage_codes: list[str] = []
        try:
            for _index in range(2):
                with pytest.raises(TransportError) as error:
                    await rest.request_json("GET", "me", max_bytes=4)
                api_codes.append(error.value.code)
            for _index in range(2):
                with pytest.raises(TransportError) as error:
                    await rest.download_media(_signed_download_url(), cap=4)
                storage_codes.append(error.value.code)
        finally:
            await rest.aclose()
            await api_client.aclose()
            await storage_client.aclose()
        return api_codes, storage_codes, api_encoded.iterated, storage_encoded.iterated

    api_codes, storage_codes, api_read, storage_read = asyncio.run(exercise())
    assert api_codes == ["invalid_response", "response_too_large"]
    assert storage_codes == ["invalid_download", "media_too_large"]
    assert api_read is False
    assert storage_read is False


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def test_upstream_error_details_use_a_control_free_safe_key_allowlist() -> None:
    api_key = "error-detail-secret-key"
    hostile_url = _signed_download_url()

    async def exercise() -> AdapterError:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                headers={"Content-Type": "application/json"},
                json={
                    "error": {
                        "code": "validation_failed",
                        "message": f"bad\x00value {api_key} {hostile_url}",
                        "details": {
                            "path": "$.proposal\x07.summary",
                            "errors": [
                                {
                                    "code": "type",
                                    "path": "$\x1f.proposal",
                                    "message": f"bad {api_key} {hostile_url}",
                                    "credential_backup": "must not survive",
                                }
                            ],
                            "api_secret_backup": "must not survive",
                            "callback_url": hostile_url,
                            "unexpected": "must not survive",
                        },
                    }
                },
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            client=client,
        )
        try:
            with pytest.raises(AdapterError) as caught:
                await rest.request_json("POST", "plans", body={"private": True})
            return caught.value
        finally:
            await rest.aclose()
            await client.aclose()

    rendered = asyncio.run(exercise()).render()
    payload = json.loads(rendered)
    assert api_key not in rendered
    assert "storage.googleapis.com" not in rendered
    assert "must not survive" not in rendered
    assert "callback_url" not in rendered
    assert "api_secret_backup" not in rendered
    assert not any(ord(character) < 32 for character in rendered)
    assert payload["details"] == {
        "path": "$.proposal .summary",
        "errors": [
            {
                "code": "type",
                "path": "$ .proposal",
                "message": "bad [redacted] [redacted URL]",
            }
        ],
    }


class _SelectedStartREST(_WorkflowREST):
    def __init__(self):
        super().__init__()
        self.allowed = ["create_task", "create_page"]
        self.failure = None

    async def request_json(self, method, target, *, body=None, **kwargs):
        if target.split("?", 1)[0] != "plans/abcdefghijkl/contract":
            return await super().request_json(method, target, body=body, **kwargs)
        self.requests.append((method, target, body))
        if self.failure:
            raise self.failure
        query = parse_qs(urlsplit(target).query)
        selected = query.get("actions", [None])[0]
        actions = selected.split(",") if selected is not None else self.allowed
        if any(action not in self.allowed for action in actions):
            raise AdapterError(
                "validation_failed", "private upstream details", status=422
            )
        contract = _contract()
        contract["permissions"] = {"allowed_actions": list(self.allowed)}
        contract["schema_actions"] = actions
        contract["schema_scope"] = "selected" if selected is not None else "full"
        contract["proposal_schema"] = {
            "type": "object",
            "required": ["actions"],
            "additionalProperties": False,
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {"type": {"enum": actions}},
                        "additionalProperties": False,
                    },
                }
            },
        }
        if query.get("view") == ["summary"]:
            contract.update(proposal_schema=None, schema_scope="summary")
        return contract, "contract"


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
# @source mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
@pytest.mark.parametrize(
    "actions", [None, ["create_task"], ["create_task", "create_page"]]
)
def test_create_start_selected_schemas_and_submit_reuse_one_plan(actions):
    async def exercise():
        rest = _SelectedStartREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        result = await adapter.execute(
            "start_create",
            {
                "instructions": "File this bug.",
                **({"actions": actions} if actions is not None else {}),
            },
        )
        plan_id = result.value["id"]
        contract = result.value["context"]["contract"]
        assert contract["contract_version"] == CONTRACT_VERSION_MAX
        assert contract["permissions"]["allowed_actions"] == rest.allowed
        assert rest.requests == [
            ("POST", "plans", {"tool": "create", "instructions": "File this bug."}),
            (
                "GET",
                f"plans/{plan_id}/contract?"
                + (
                    urlencode({"actions": ",".join(actions)})
                    if actions is not None
                    else "view=summary"
                ),
                None,
            ),
        ]
        if actions is None:
            assert contract["proposal_schema"] is None
            assert contract["schema_scope"] == "summary"
            return
        assert contract["schema_scope"] == "selected"
        assert contract["schema_actions"] == actions
        proposal = {"actions": [{"type": action} for action in actions]}
        validate_value(contract["proposal_schema"], proposal, phase="proposal")
        receipt = await adapter.execute(
            "submit_plan",
            {
                "plan_id": plan_id,
                "contract_version": contract["contract_version"],
                "proposal": proposal,
            },
        )
        assert receipt.value["id"] == plan_id
        assert receipt.value["status"] == "ready"
        # The only subsequent schema read is the adapter's fresh submission check.
        assert rest.requests[-2] == ("GET", f"plans/{plan_id}/contract", None)
        assert rest.requests[-1][2]["proposal"] == proposal
        assert sum(target == "plans" for _, target, _ in rest.requests) == 1
        rest.allowed = ["create_page"]
        with pytest.raises(SchemaError):
            await adapter.execute(
                "submit_plan",
                {
                    "plan_id": plan_id,
                    "contract_version": contract["contract_version"],
                    "proposal": proposal,
                },
            )
        assert sum(target.endswith("/submit") for _, target, _ in rest.requests) == 1
        # The same Plan remains usable for later schemas and proposal revisions.
        later = await adapter.execute(
            "get_plan_contract", {"plan_id": plan_id, "actions": ["create_page"]}
        )
        assert later.value["schema_actions"] == ["create_page"]
        revised = await adapter.execute(
            "submit_plan",
            {
                "plan_id": plan_id,
                "contract_version": contract["contract_version"],
                "proposal": {"actions": [{"type": "create_page"}]},
            },
        )
        assert revised.value["id"] == plan_id

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
@pytest.mark.parametrize(
    "actions",
    [
        [],
        "create_task",
        [None],
        [""],
        ["create_task,create_page"],
        ["create_task"] * 101,
    ],
)
def test_create_start_rejects_malformed_selections_before_creating_plan(actions):
    async def exercise():
        rest = _SelectedStartREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        with pytest.raises(SchemaError):
            await adapter.execute(
                "start_create", {"instructions": "File this bug.", "actions": actions}
            )
        assert rest.requests == []

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
# @source mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
@pytest.mark.parametrize("failure", ["transport", "disallowed", "unknown"])
def test_create_start_schema_recovery_preserves_selection_and_created_plan(failure):
    async def exercise():
        rest = _SelectedStartREST()
        if failure == "transport":
            rest.failure = TransportError("offline", "private upstream details")
        elif failure == "disallowed":
            rest.allowed = ["create_page"]
        actions = ["unknown_action"] if failure == "unknown" else ["create_task"]
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        started = await adapter.execute(
            "start_create", {"instructions": "File this bug.", "actions": actions}
        )
        assert started.value["status"] == "draft"
        recovery = started.value["context"]["recovery"]
        assert recovery["tool"] == "get_plan_contract"
        assert recovery["arguments"] == {
            "plan_id": started.value["id"],
            "actions": actions,
            "view": "full",
        }
        assert "private upstream details" not in compact_json(started.value)
        if failure != "transport":
            assert "rejected" in recovery["message"]
            assert "view=summary" in recovery["message"]
        rest.failure = None
        rest.allowed = ["create_task", "create_page"]
        arguments = {**recovery["arguments"], "actions": ["create_task"]}
        recovered = await adapter.execute(recovery["tool"], arguments)
        assert recovered.value["schema_actions"] == ["create_task"]
        assert sum(target == "plans" for _, target, _ in rest.requests) == 1

    asyncio.run(exercise())


class _LifecycleContextREST(_WorkflowREST):
    """Deterministic REST boundary for post-write context reads."""

    def __init__(self, tool="create", failure=None):
        super().__init__()
        self.tool = tool
        self.failure = failure
        self.files = []

    async def startup(self):
        discovery, actor, catalog = await super().startup()
        catalog["tools"].append(
            {
                "name": "get_guidelines",
                "description": "Get canonical workflow guidance.",
                "input_schema": {
                    "type": "object",
                    "required": ["task"],
                    "properties": {"task": {"const": "organize"}},
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "required": ["task", "guidelines"],
                    "properties": {
                        "task": {"const": "organize"},
                        "guidelines": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "result_paths": {"primary_collection": None, "pagination": None},
            }
        )
        catalog["selected_count"] += 1
        return discovery, actor, catalog

    async def request_json(self, method, target, *, body=None, **kwargs):
        if target.endswith("/tools/get_guidelines"):
            self.requests.append((method, target, body))
            self._fail_context()
            return {
                "result": {"task": "organize", "guidelines": "Full workflow."}
            }, "guidance"
        if target.split("?", 1)[0].endswith("/contract"):
            self.requests.append((method, target, body))
            self._fail_context()
            contract = _contract()
            contract["tool"] = self.tool
            contract["uploads_supported"] = self.tool == "organize"
            if self.tool == "organize":
                files = deepcopy(self.files)
                if self.failure == "different_files":
                    files[0]["ref"] = "hash:zyxwvutsrqpo"
                contract["upload_inventory"] = {
                    "status": "pending" if self.failure == "pending" else "finalized",
                    "authoritative": True,
                    "count": len(files),
                    "files": files,
                }
                contract["required_file_refs"] = [item["ref"] for item in files]
            if self.failure == "oversize":
                contract["workflow_rules"] = ["x" * MAX_STRUCTURED_RESULT_BYTES]
            if self.failure == "private":
                contract["workflow_rules"] = ["api-secret"]
            if self.failure == "wrong_tool":
                contract["tool"] = "ask" if self.tool != "ask" else "create"
            return contract, "contract"
        result, request_id = await super().request_json(
            method, target, body=body, **kwargs
        )
        if target == "plans":
            result["tool"] = self.tool
        return result, request_id

    def _fail_context(self):
        if self.failure == "transport":
            raise TransportError("offline", "private upstream error api-secret")
        if self.failure == "cancel":
            raise asyncio.CancelledError()


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
@pytest.mark.parametrize("tool", ["ask", "create", "organize"])
def test_starters_bundle_current_context_without_an_actor_or_inventory_read(tool):
    async def exercise():
        rest = _LifecycleContextREST(tool)
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        result = await adapter.execute(
            f"start_{tool}", {"instructions": "A natural request."}
        )
        return result.value, rest.requests

    value, requests = asyncio.run(exercise())
    assert value["id"] == "abcdefghijkl"
    assert len(requests) == 2
    assert requests[0][0:2] == ("POST", "plans")
    assert "submission_format" not in compact_json(value)
    assert "guidelines" not in value["context"]
    assert "view=summary" in requests[1][1]
    assert "contract" in value["context"]
    contract = value["context"]["contract"]
    assert contract["current_date"] == "2026-09-04"
    assert contract["timezone"] == "UTC"
    assert contract["tool"] == tool
    assert contract["proposal_schema"] == _contract()["proposal_schema"]
    assert "personal_page" in contract
    instructions = contract["mcp_submission"]["instructions"]
    assert "do not add a separate final contract read" in instructions
    assert (
        "Keep this plan_id for investigation, submission, and revisions"
        in instructions
    )
    assert "starting again creates another report" in instructions
    assert "one complete text or structured representation" in instructions
    assert (
        "counts, continuation/truncation flags, and partial errors" in instructions
    )
    assert "re-render the retained result in smaller sections" in instructions
    assert "repeat only the necessary read with the same plan_id" in instructions


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
@pytest.mark.parametrize("failure", ["transport", "oversize", "private", "wrong_tool"])
def test_failed_start_context_preserves_the_created_plan_and_offers_only_a_read(
    failure,
):
    async def exercise():
        rest = _LifecycleContextREST(failure=failure)
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        result = await adapter.execute(
            "start_create", {"instructions": "Create a reminder."}
        )
        return result.value, rest.requests

    value, requests = asyncio.run(exercise())
    assert value["status"] == "draft"
    assert value["id"] == "abcdefghijkl"
    recovery = value["context"]["recovery"]
    assert recovery["tool"] == "get_plan_contract"
    assert recovery["arguments"] == {"plan_id": value["id"]}
    assert "do not repeat" in recovery["message"]
    assert "api-secret" not in compact_json(value)
    assert sum(target == "plans" for _, target, _ in requests) == 1


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
@pytest.mark.parametrize("failure", [None, "transport", "pending", "different_files"])
def test_upload_bundles_final_contract_without_replaying_successful_finalization(
    monkeypatch, failure
):
    from lagniappe_mcp import files as files_module

    uploads = []
    finalized_files = [
        {
            "ref": "hash:mnopqrstuvwx",
            "name": "Fixture",
            "filename": "fixture.txt",
            "mimetype": "text/plain",
            "size": 17,
        }
    ]

    async def uploaded(rest, *, plan_id, file_items, contract):
        uploads.append((plan_id, file_items))
        assert contract["upload_inventory"]["status"] == "finalized"
        assert contract["upload_inventory"]["files"] == []
        plan = _plan()
        plan["tool"] = "organize"
        plan["files"] = deepcopy(finalized_files)
        rest.files = deepcopy(finalized_files)
        rest.failure = failure
        return {"plan": plan, "upload_inventory": deepcopy(finalized_files)}

    monkeypatch.setattr(files_module, "upload_local_files", uploaded)

    async def exercise():
        rest = _LifecycleContextREST("organize")
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        result = await adapter.execute(
            "upload_local_files",
            {
                "plan_id": "abcdefghijkl",
                "files": [{"path": "/private/fixture.txt"}],
            },
        )
        return result.value, rest.requests

    value, requests = asyncio.run(exercise())
    assert len(uploads) == 1
    assert value["plan"]["id"] == "abcdefghijkl"
    assert value["plan"]["files"] == finalized_files
    assert value["plan"]["uploads_pending"] is False
    assert value["upload_inventory"] == finalized_files
    assert "/private/fixture.txt" not in compact_json(value)
    assert len(requests) == 2  # Existing upload preflight, then finalized context.
    if failure:
        recovery = value["context"]["recovery"]
        assert recovery["tool"] == "get_plan_contract"
        assert recovery["arguments"] == {"plan_id": "abcdefghijkl"}
        assert "do not repeat" in recovery["message"]
        assert "contract" not in value["context"]
        assert "hash:zyxwvutsrqpo" not in compact_json(value)
    else:
        contract = value["context"]["contract"]
        assert contract["tool"] == "organize"
        assert contract["upload_inventory"]["status"] == "finalized"
        assert contract["upload_inventory"]["authoritative"] is True
        assert contract["upload_inventory"]["count"] == 1
        assert contract["upload_inventory"]["files"] == finalized_files
        assert contract["required_file_refs"] == ["hash:mnopqrstuvwx"]


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_context_enrichment_remains_cancellable():
    async def exercise():
        rest = _LifecycleContextREST(failure="cancel")
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,
        )
        await adapter.initialize()
        with pytest.raises(asyncio.CancelledError):
            await adapter.execute("start_create", {"instructions": "Make a reminder."})
        assert len(rest.requests) == 2

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_mcp_contract_replaces_rest_refetch_steps_and_resolves_contract_relative_schema():
    class RestWorkflowRules(_LifecycleContextREST):
        async def request_json(self, method, target, **kwargs):
            result, request_id = await super().request_json(method, target, **kwargs)
            if target.split("?", 1)[0].endswith("/contract"):
                result["workflow_rules"] = [
                    "When an answer is ready, fetch the latest contract and submit it without "
                    "waiting for separate save confirmation. Submission only saves the "
                    "read-only answer report; it does not modify workspace records. Then give "
                    "the user the answer and preview_url.",
                    "Fetch this contract after finalizing uploads and immediately before "
                    "constructing the proposal.",
                    "Every uploaded file still requires a grounded summary.",
                ]
            return result, request_id

    async def exercise():
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=RestWorkflowRules(),
        )
        await adapter.initialize()
        started = await adapter.execute(
            "start_create", {"instructions": "A natural request."}
        )
        direct = await adapter.execute(
            "get_plan_contract", {"plan_id": started.value["id"]}
        )
        return started.value["context"]["contract"], direct.value

    bundled, direct = asyncio.run(exercise())
    for contract in (bundled, direct):
        rules = "\n".join(contract["workflow_rules"])
        assert "fetch the latest contract" not in rules
        assert "without waiting for separate save confirmation" not in rules
        assert "Only when the user asks to save the answer" in rules
        assert "Fetch this contract after finalizing" not in rules
        assert "does not modify workspace records" in rules
        assert "Every uploaded file still requires a grounded summary." in rules
        assert "submit_plan performs the final fresh-contract check" in rules
        pointer = contract["mcp_submission"]["proposal_schema"]
        assert contract[pointer.removeprefix("$.")] == _contract()["proposal_schema"]
        assert (
            "relative to this contract object"
            in contract["mcp_submission"]["instructions"]
        )


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def test_mcp_discovery_exposes_tool_purpose_before_shared_workflow(monkeypatch):
    async def exercise():
        from lagniappe_mcp.limits import MCP_INSTRUCTIONS

        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=_LifecycleContextREST(),
        )
        await adapter.initialize()
        return MCP_INSTRUCTIONS, {
            name: tool.as_mcp_tool() for name, tool in adapter.tools.items()
        }

    instructions, tools = asyncio.run(exercise())
    # A host may prepend initialization instructions before a short description
    # excerpt. Each purpose must still be visible in the 180-character excerpts
    # used by the trial's discovery calls, not hidden behind a common workflow.
    assert instructions is not None
    assert len(instructions) <= 96
    purposes = {
        "get_actor": "Return the current actor",
        "answer_question": "Get lightweight guidance and personal Page context",
        "start_ask": "Start a durable Ask report only when the user requests saving",
        "start_create": "Start a Create Plan to create pages, tasks, or workspace structure",
        "start_organize": "Start an Organize Plan to update existing records",
        "get_plan": "Return current Plan state",
        "get_plan_contract": "Load exact schemas for selected allowed actions",
        "upload_local_files": "Upload explicit readable nonempty regular files",
        "submit_plan": "Save an explicitly requested Ask answer or a Create/Organize proposal",
        "search": "Search within the current Plan",
    }
    for name, purpose in purposes.items():
        description = tools[name].description
        assert description.startswith(purpose)
        assert purpose in f"{instructions}\n{description}"[:180]

    for name in ("start_ask", "start_create", "start_organize"):
        tool = tools[name]
        assert tool.annotations.idempotent_hint is False
        assert "Each call creates a new report" in tool.description
        assert "Reuse the returned id as plan_id" in tool.description
        assert "Never restart to recover clipped output" in tool.description
        assert (
            "recovery read without repeating the successful start" in tool.description
        )

    assert "submit the already-agreed answer" in tools["start_ask"].description
    for name in ("start_create", "start_organize"):
        assert "never executes workspace changes" in tools[name].description
    assert "Remote updates do not require a file" in tools["start_organize"].description
    assert "get_plan_contract(actions=[...])" in tools["start_organize"].description
    assert "complete_task" not in tools
    for name in ("upload_local_files",):
        assert "complete file evidence" in tools[name].description
        assert "not complete inspection" in tools[name].description
    assert (
        "without repeating the successful upload"
        in tools["upload_local_files"].description
    )
    submit = tools["submit_plan"].description
    assert "existing plan_id" in submit
    assert "Reuse for revisions" in submit
    assert "Never executes workspace changes" in submit
    assert "no separate final contract read" in submit
    assert "preview_url for authenticated review" in submit


# @pair mcp-adapter:product-contract
# @source mcp/src/lagniappe_mcp/catalog.py::catalog_tools
def test_read_descriptions_localize_result_recovery_without_changing_catalog_schemas():
    catalog = asyncio.run(_WorkflowREST().startup())[2]
    template = catalog["tools"][0]
    catalog["tools"] = []
    for name, purpose in (
        ("search_entities", "Search for matching workspace records."),
        ("query_workspace_filter", "Query records using workspace filters."),
        ("get_entity", "Load full details and attached Form schemas."),
        ("get_file", "Read file metadata and extracted text."),
    ):
        entry = deepcopy(template)
        entry.update(name=name, description=purpose)
        if name == "get_file":
            entry["output_schema"] = {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "original_file": {
                        "type": "object",
                        "properties": {
                            "supported": {"type": "boolean"},
                            "attached": {"type": "boolean"},
                        },
                    },
                },
            }
        catalog["tools"].append(entry)
    catalog["selected_count"] = len(catalog["tools"])
    original = deepcopy(catalog)
    tools = {tool.name: tool for tool in catalog_tools(catalog)}

    assert catalog == original  # MCP notes never mutate the native/REST catalog.
    assert set(tools) == {entry["name"] for entry in original["tools"]}
    for entry in original["tools"]:
        tool = tools[entry["name"]]
        published = tool.as_mcp_tool()
        assert published.description.startswith(entry["description"])
        assert tool.input_schema == inject_plan_id(entry["input_schema"])
        assert tool.rest_output_schema == entry["output_schema"]
        assert tool.result_paths == entry["result_paths"]
        if entry["name"] != "get_file":
            assert tool.output_schema == entry["output_schema"]

    for name in ("query_workspace_filter", "get_file"):
        description = tools[name].description
        assert "one complete text or structured representation" in description
        assert "separately delivered media" in description
        assert (
            "counts, continuation/truncation flags, and partial errors" in description
        )
        assert "re-render the retained result in smaller sections" in description
        assert "same plan_id; never start another Plan" in description
    assert (
        "view-authorized; reuse their evidence" in tools["search_entities"].description
    )
    assert "only for information missing" in tools["search_entities"].description
    assert "Reuse attached Form schemas" in tools["get_entity"].description
    assert "not complete inspection" in tools["get_file"].description
    assert (
        "include_original=true delivers only bounded supported image/audio"
        in tools["get_file"].description
    )


# @pair mcp-adapter:product-contract
@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_server_presents_matching_schemas_and_values_for_each_protocol(
    mode: str,
) -> None:
    referenced_schema = {
        "$defs": {"item": {"type": "integer", "minimum": 0}},
        "type": "array",
        "items": {"$ref": "#/$defs/item"},
    }
    cases = {
        "array_read": (referenced_schema, [1, 2]),
        "empty_read": (referenced_schema, []),
        "scalar_read": ({"type": "string"}, "hello"),
        "nullable_object_read": ({"type": ["object", "null"]}, {"name": "hello"}),
        "union_read": ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, 7),
        "object_read": ({"type": "object"}, {"result": [1, 2]}),
    }
    # The v2 SDK client treats a direct JSON null as missing structured content.
    # A legacy wrapper must retain null; the live REST catalog has no null root.
    if mode == "legacy":
        cases["null_read"] = ({"type": ["object", "null"]}, None)
    definitions = {
        name: ToolDefinition(
            name,
            "Read a fixture value.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            validate_schema_document(schema),
            "read",
            READ_ANNOTATIONS,
            result_paths={"primary_collection": "$", "pagination": None},
        )
        for name, (schema, _) in cases.items()
    }
    original_definitions = deepcopy(definitions)

    protocol = "2025-11-25" if mode == "legacy" else "2026-07-28"
    for name, definition in definitions.items():
        tool = definition.as_mcp_tool(protocol)
        raw_schema, raw_value = cases[tool.name]
        wrapped = mode == "legacy" and raw_schema.get("type") != "object"
        expected = {"result": raw_value} if wrapped else raw_value
        if mode == "legacy":
            assert tool.output_schema["type"] == "object"
        else:
            assert tool.output_schema == raw_schema
        called = _success_result(
            AdapterResult(raw_value),
            wrap_result=definition.requires_result_wrapper(protocol),
        )
        assert called.is_error is False
        assert called.structured_content == expected
        assert json.loads(called.content[0].text) == expected
        validate_value(tool.output_schema, expected, phase="output")
        assert tool.meta["lagniappe/resultPaths"] == {
            "primary_collection": "$.result" if wrapped else "$",
            "pagination": None,
        }
    assert definitions == original_definitions
