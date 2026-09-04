"""Strict JSON Schema validation for live REST-owned contracts."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError as JSONSchemaDefinitionError
from jsonschema.exceptions import ValidationError

from .errors import SchemaError
from .limits import MAX_SCHEMA_BYTES, SUPPORTED_SCHEMA_DIALECTS


# The catalog and Plan contract are authenticated, but they are still remote
# input.  ``jsonschema`` implements the complete draft, including regular
# expressions and applicators whose running time is controlled by an untrusted
# schema.  The adapter needs only this deliberately small subset of 2020-12.
# Keep it closed so a new upstream keyword requires an adapter review rather
# than silently extending the local execution surface.
_ALLOWED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$defs",
        "$ref",
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minProperties",
        "maxProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "description",
        # The REST proposal contract uses this OpenAPI annotation.  It does
        # not participate in jsonschema evaluation, but its local-reference
        # mapping is checked below before it is published to MCP clients.
        "discriminator",
    }
)
_REGEX_OR_UNBOUNDED_SCHEMA_KEYWORDS = frozenset(
    {
        "pattern",
        "patternProperties",
        "propertyNames",
        # FormatChecker dispatches to keyword-selected Python callables.  The
        # live remote schemas do not need formats; adapter-owned schemas may
        # still use their fixed date/URI checks directly in ``validate_value``.
        "format",
        # These are either unbounded collection scans, schema-valued dynamic
        # evaluation, or draft features absent from the frozen API contract.
        "contains",
        "minContains",
        "maxContains",
        "dependentSchemas",
        "dependencies",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_SCHEMA_APPLICATORS = ("allOf", "anyOf", "oneOf")
_SINGLE_SCHEMA_APPLICATORS = ("not", "if", "then", "else")

# These limits are intentionally above the current largest permission-scoped
# proposal schema (roughly 1,300 JSON values, 20 action branches, and three
# nested applicators) while keeping adversarial validation work small and
# deterministic.  MAX_SCHEMA_BYTES remains the first aggregate bound.
_MAX_SCHEMA_NODES = 2_048
_MAX_SCHEMA_DEPTH = 32
_MAX_SCHEMA_MAP_ENTRIES = 128
_MAX_SCHEMA_LIST_ENTRIES = 128
_MAX_APPLICATOR_BRANCHES = 32
_MAX_APPLICATOR_DEPTH = 8
_MAX_EXPANDED_VALIDATION_NODES = 8_192
_MAX_UNIQUE_ITEMS = 8
_MAX_REFERENCE_CHARS = 512
_MAX_REFERENCE_TOKENS = 32


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_schema_rejects_dangling_refs_and_non_finite_json
# @tests tests_unit/test_033_mcp_adapter.py::test_mcp_v2_results_use_direct_structured_values_and_complete_aliases
def compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise SchemaError("invalid_json", "Value is not finite JSON data.") from error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
def json_size(value: Any) -> int:
    return len(compact_json(value).encode("utf-8"))


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _walk(value: Any):
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > 128:
            raise SchemaError("invalid_schema", "Upstream schema nesting is too deep.")
        yield current
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _resolve_local_reference(schema: dict[str, Any], reference: str) -> Any:
    if reference == "#":
        return schema
    if not reference.startswith("#/"):
        raise SchemaError(
            "unsupported_schema",
            "Only local JSON Pointer schema references are supported.",
        )
    if (
        len(reference) > _MAX_REFERENCE_CHARS
        or reference.count("/") > _MAX_REFERENCE_TOKENS
    ):
        raise SchemaError(
            "schema_too_complex",
            "Upstream schema reference exceeds the adapter limit.",
        )
    current: Any = schema
    for encoded in unquote(reference[2:]).split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif (
            isinstance(current, list) and token.isdigit() and int(token) < len(current)
        ):
            current = current[int(token)]
        else:
            raise SchemaError(
                "invalid_schema", "Upstream schema contains a dangling local reference."
            )
    return current


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _bounded_non_negative_integer(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _reject_unsafe_schema_subset(schema: dict[str, Any]) -> None:
    """Reject remote schema features outside the frozen, bounded subset.

    This runs before ``Draft202012Validator.check_schema`` so an upstream
    schema cannot select a regular-expression engine path or make the general
    validator traverse an attacker-sized applicator graph.
    """
    pending: list[tuple[dict[str, Any], int, int]] = [(schema, 0, 0)]
    node_count = 0
    while pending:
        node, depth, applicator_depth = pending.pop()
        node_count += 1
        if node_count > _MAX_SCHEMA_NODES or depth > _MAX_SCHEMA_DEPTH:
            raise SchemaError(
                "schema_too_complex",
                "Upstream schema exceeds the adapter structural limit.",
            )
        if any(not isinstance(keyword, str) for keyword in node):
            raise SchemaError(
                "invalid_schema", "Upstream schema keywords must be strings."
            )
        keywords = set(node)
        if keywords.intersection(_REGEX_OR_UNBOUNDED_SCHEMA_KEYWORDS):
            raise SchemaError(
                "unsupported_schema",
                "Upstream schema uses an unbounded validation keyword.",
            )
        if not keywords.issubset(_ALLOWED_SCHEMA_KEYWORDS):
            raise SchemaError(
                "unsupported_schema",
                "Upstream schema uses a keyword outside the adapter subset.",
            )

        for keyword in ("properties", "$defs"):
            if keyword not in node:
                continue
            mapping = node[keyword]
            if not isinstance(mapping, dict):
                raise SchemaError(
                    "invalid_schema", f"Upstream schema {keyword} must be an object."
                )
            if len(mapping) > _MAX_SCHEMA_MAP_ENTRIES:
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream schema contains too many mapped schemas.",
                )
            for name, child in mapping.items():
                if not isinstance(name, str) or not isinstance(child, dict):
                    raise SchemaError(
                        "unsupported_schema",
                        "Upstream schema maps must contain object schemas.",
                    )
                pending.append((child, depth + 1, applicator_depth))

        if "items" in node:
            items = node["items"]
            if not isinstance(items, dict):
                raise SchemaError(
                    "unsupported_schema",
                    "Upstream array items must use one object schema.",
                )
            pending.append((items, depth + 1, applicator_depth))

        for keyword in _SCHEMA_APPLICATORS:
            if keyword not in node:
                continue
            branches = node[keyword]
            if (
                not isinstance(branches, list)
                or not branches
                or len(branches) > _MAX_APPLICATOR_BRANCHES
                or any(not isinstance(branch, dict) for branch in branches)
            ):
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream schema applicator branches are not safely bounded.",
                )
            next_applicator_depth = applicator_depth + 1
            if next_applicator_depth > _MAX_APPLICATOR_DEPTH:
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream schema applicators are nested too deeply.",
                )
            pending.extend(
                (branch, depth + 1, next_applicator_depth) for branch in branches
            )

        for keyword in _SINGLE_SCHEMA_APPLICATORS:
            if keyword not in node:
                continue
            branch = node[keyword]
            if not isinstance(branch, dict):
                raise SchemaError(
                    "unsupported_schema",
                    "Upstream schema applicators must contain object schemas.",
                )
            next_applicator_depth = applicator_depth + 1
            if next_applicator_depth > _MAX_APPLICATOR_DEPTH:
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream schema applicators are nested too deeply.",
                )
            pending.append((branch, depth + 1, next_applicator_depth))

        if "additionalProperties" in node and not isinstance(
            node["additionalProperties"], bool
        ):
            raise SchemaError(
                "unsupported_schema",
                "Upstream additionalProperties must be a boolean.",
            )

        required = node.get("required")
        if required is not None and (
            not isinstance(required, list)
            or len(required) > _MAX_SCHEMA_LIST_ENTRIES
            or any(not isinstance(item, str) for item in required)
        ):
            raise SchemaError(
                "schema_too_complex",
                "Upstream schema required fields are not safely bounded.",
            )

        enum = node.get("enum")
        if enum is not None and (
            not isinstance(enum, list)
            or not enum
            or len(enum) > _MAX_SCHEMA_LIST_ENTRIES
            or any(not _is_json_scalar(item) for item in enum)
        ):
            raise SchemaError(
                "schema_too_complex",
                "Upstream schema enum values are not safely bounded scalars.",
            )
        if "const" in node and not _is_json_scalar(node["const"]):
            raise SchemaError(
                "unsupported_schema", "Upstream schema const must be a scalar."
            )

        schema_type = node.get("type")
        if schema_type is not None and not (
            isinstance(schema_type, str)
            or (
                isinstance(schema_type, list)
                and 0 < len(schema_type) <= 7
                and all(isinstance(item, str) for item in schema_type)
            )
        ):
            raise SchemaError("invalid_schema", "Upstream schema type is invalid.")

        for keyword in (
            "minItems",
            "maxItems",
            "minLength",
            "maxLength",
            "minProperties",
            "maxProperties",
        ):
            if keyword in node and not _bounded_non_negative_integer(node[keyword]):
                raise SchemaError(
                    "invalid_schema",
                    "Upstream schema contains an invalid non-negative limit.",
                )
        for minimum, maximum in (
            ("minItems", "maxItems"),
            ("minLength", "maxLength"),
            ("minProperties", "maxProperties"),
        ):
            if minimum in node and maximum in node and node[minimum] > node[maximum]:
                raise SchemaError(
                    "invalid_schema", "Upstream schema contains contradictory limits."
                )

        for keyword in ("minimum", "maximum"):
            value = node.get(keyword)
            if keyword in node and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise SchemaError(
                    "invalid_schema", "Upstream schema numeric limit is invalid."
                )

        unique_items = node.get("uniqueItems")
        if unique_items is not None and not isinstance(unique_items, bool):
            raise SchemaError(
                "invalid_schema", "Upstream schema uniqueItems must be a boolean."
            )
        if unique_items is True and (
            not _bounded_non_negative_integer(node.get("maxItems"))
            or node["maxItems"] > _MAX_UNIQUE_ITEMS
        ):
            raise SchemaError(
                "schema_too_complex",
                "Upstream uniqueItems requires a small explicit maxItems.",
            )

        if "description" in node and not isinstance(node["description"], str):
            raise SchemaError(
                "invalid_schema", "Upstream schema description must be a string."
            )

        discriminator = node.get("discriminator")
        if discriminator is not None:
            if not isinstance(discriminator, dict) or set(discriminator) != {
                "propertyName",
                "mapping",
            }:
                raise SchemaError(
                    "unsupported_schema",
                    "Upstream discriminator has an unsupported shape.",
                )
            property_name = discriminator.get("propertyName")
            mapping = discriminator.get("mapping")
            if (
                not isinstance(property_name, str)
                or not property_name
                or not isinstance(mapping, dict)
                or not mapping
                or len(mapping) > _MAX_SCHEMA_MAP_ENTRIES
                or any(
                    not isinstance(name, str)
                    or not name
                    or not isinstance(reference, str)
                    or not reference.startswith("#")
                    for name, reference in mapping.items()
                )
            ):
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream discriminator mapping is not safely bounded.",
                )
            for reference in mapping.values():
                _resolve_local_reference(schema, reference)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _reject_expensive_reference_expansion(schema: dict[str, Any]) -> None:
    """Bound the validator work hidden behind a compact local-reference DAG."""
    pending: list[tuple[dict[str, Any], int]] = [(schema, 0)]
    expanded_nodes = 0
    while pending:
        node, applicator_depth = pending.pop()
        expanded_nodes += 1
        if expanded_nodes > _MAX_EXPANDED_VALIDATION_NODES:
            raise SchemaError(
                "schema_too_complex",
                "Upstream schema expands beyond the validation-work limit.",
            )

        reference = node.get("$ref")
        if isinstance(reference, str):
            target = _resolve_local_reference(schema, reference)
            if not isinstance(target, dict):
                raise SchemaError(
                    "invalid_schema", "Upstream schema reference is not a schema."
                )
            pending.append((target, applicator_depth))

        properties = node.get("properties")
        if isinstance(properties, dict):
            pending.extend((child, applicator_depth) for child in properties.values())
        items = node.get("items")
        if isinstance(items, dict):
            pending.append((items, applicator_depth))

        for keyword in _SCHEMA_APPLICATORS:
            branches = node.get(keyword)
            if not isinstance(branches, list):
                continue
            next_applicator_depth = applicator_depth + 1
            if next_applicator_depth > _MAX_APPLICATOR_DEPTH:
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream schema applicators expand too deeply through references.",
                )
            pending.extend((branch, next_applicator_depth) for branch in branches)
        for keyword in _SINGLE_SCHEMA_APPLICATORS:
            branch = node.get(keyword)
            if not isinstance(branch, dict):
                continue
            next_applicator_depth = applicator_depth + 1
            if next_applicator_depth > _MAX_APPLICATOR_DEPTH:
                raise SchemaError(
                    "schema_too_complex",
                    "Upstream schema applicators expand too deeply through references.",
                )
            pending.append((branch, next_applicator_depth))


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def _reject_recursive_reference_graph(schema: dict[str, Any]) -> None:
    """Reject cycles formed by ordinary local ``$ref`` edges.

    Draft 2020-12 can express recursive schemas with an ordinary local
    reference as well as with the explicit dynamic keywords.  The adapter does
    not need recursive input/output contracts and rejects them before a value
    validator can recurse unpredictably.
    """
    states: dict[int, int] = {}

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::_reject_recursive_reference_graph
    def visit(node: Any) -> None:
        if not isinstance(node, (dict, list)):
            return
        identity = id(node)
        state = states.get(identity, 0)
        if state == 1:
            raise SchemaError(
                "unsupported_schema",
                "Recursive JSON Schema references are not supported.",
            )
        if state == 2:
            return
        states[identity] = 1
        children = list(node.values()) if isinstance(node, dict) else node
        for child in children:
            visit(child)
        if isinstance(node, dict) and "$ref" in node:
            reference = node["$ref"]
            if isinstance(reference, str):
                visit(_resolve_local_reference(schema, reference))
        states[identity] = 2

    visit(schema)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_schema_rejects_dangling_refs_and_non_finite_json
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
def validate_schema_document(
    schema: Any, *, input_root: bool = False
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise SchemaError("invalid_schema", "Upstream schema must be a JSON object.")
    if json_size(schema) > MAX_SCHEMA_BYTES:
        raise SchemaError(
            "schema_too_large", "Upstream schema exceeds the adapter limit."
        )
    dialect = schema.get("$schema")
    if dialect is not None and dialect not in SUPPORTED_SCHEMA_DIALECTS:
        raise SchemaError(
            "unsupported_schema", "Upstream schema dialect is not supported."
        )
    if input_root and schema.get("type") != "object":
        raise SchemaError(
            "invalid_schema", "MCP tool input schema must have an object root."
        )
    _reject_unsafe_schema_subset(schema)
    for node in _walk(schema):
        if not isinstance(node, dict):
            continue
        if "$dynamicRef" in node or "$recursiveRef" in node:
            raise SchemaError(
                "unsupported_schema",
                "Dynamic or recursive schema references are not supported.",
            )
        if "$ref" in node:
            reference = node["$ref"]
            if not isinstance(reference, str) or not reference.startswith("#"):
                raise SchemaError(
                    "unsupported_schema",
                    "Only local JSON Schema references are supported.",
                )
            _resolve_local_reference(schema, reference)
    _reject_recursive_reference_graph(schema)
    _reject_expensive_reference_expansion(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except JSONSchemaDefinitionError as error:
        raise SchemaError(
            "invalid_schema", "Upstream JSON Schema is invalid."
        ) from error
    return deepcopy(schema)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
def inject_plan_id(schema: Any) -> dict[str, Any]:
    # ``plan_id`` must genuinely be injectable, not merely present in the
    # rendered ``properties`` map.  Root-level applicators can independently
    # reject or reinterpret a newly added property (for example an ``allOf``
    # branch with ``additionalProperties: false`` or a ``propertyNames``
    # pattern).  The current REST catalog uses plain object roots, so fail
    # closed if a future catalog introduces an ambiguous root constraint rather
    # than publishing an MCP schema that no value can satisfy consistently.
    unsafe_root_keywords = {
        "$ref",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "patternProperties",
        "propertyNames",
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "minProperties",
        "maxProperties",
    }
    conflicts = (
        sorted(unsafe_root_keywords.intersection(schema))
        if isinstance(schema, dict)
        else []
    )
    if conflicts:
        raise SchemaError(
            "reserved_tool_argument",
            "Upstream tool input schema cannot safely accept reserved plan_id.",
            details={"keywords": conflicts},
        )
    projected = validate_schema_document(schema, input_root=True)
    properties = projected.setdefault("properties", {})
    if not isinstance(properties, dict):
        raise SchemaError("invalid_schema", "Tool schema properties must be an object.")
    if "plan_id" in properties:
        raise SchemaError(
            "reserved_tool_argument", "Upstream tool conflicts with reserved plan_id."
        )
    properties["plan_id"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 2048,
        "description": "Opaque Plan ID returned by a start_* tool.",
    }
    required = projected.setdefault("required", [])
    if not isinstance(required, list) or any(
        not isinstance(item, str) for item in required
    ):
        raise SchemaError(
            "invalid_schema", "Tool schema required must be a string array."
        )
    if "plan_id" not in required:
        required.append("plan_id")
    return projected


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
# @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper
def validate_value(schema: dict[str, Any], value: Any, *, phase: str) -> None:
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as error:
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        raise SchemaError(
            f"{phase}_validation_failed",
            f"Value does not match the published schema at {path}.",
            details={"path": path, "validator": error.validator},
        ) from error
