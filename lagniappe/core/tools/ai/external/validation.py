"""External API validation."""

import json
from copy import deepcopy

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.report_contracts import MAX_PROPOSAL_ACTIONS as MAX_PROPOSAL_ACTIONS
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.files.html import render_markdown, strip_tags

from ..planner import file_usage_schema, validate_file_usage
from ..references import HASH_PREFIXED_ID_REGEX, HASH_REFERENCE_REGEX
from ..reporting.contracts.schema import external_report_proposal_response_schema
from ..reporting.proposals.validation import validate_proposal
from .contracts import _external_allowed_report_actions, report_file_references
from .definitions import (
    CONTRACT_VERSION,
    MAX_INSTRUCTIONS_BYTES,
    MAX_PLAN_NAME_CHARACTERS,
    MAX_PROPOSAL_BYTES,
    MAX_VALIDATION_ERRORS,
    REFERENCE_FIELDS,
    _text_bytes,
    submission_request_schema,
)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_submission_validation_collects_independent_field_errors
# @matrix agent-api : envelope schema field-path bounded-validation
def submission_validation_errors(data, report, user):
    """Collect safe independent envelope/schema errors before semantic validation."""
    errors = []
    if not isinstance(data, dict):
        return [
            {
                "code": "type",
                "path": "$",
                "message": "Submission must be a JSON object.",
                "expected": "object",
            }
        ]

    envelope = submission_request_schema()
    for field in envelope["required"]:
        if field not in data:
            errors.append(
                {
                    "code": "required",
                    "path": f"$.{field}",
                    "message": f"{field} is required.",
                    "expected": CONTRACT_VERSION
                    if field == "contract_version"
                    else "array"
                    if field == "file_usage"
                    else "object",
                }
            )
    for field in sorted(
        set(data) - set(envelope["properties"])
    ):
        errors.append(
            {
                "code": "additional_property",
                "path": f"$.{field}",
                "message": "Unsupported top-level submission field.",
            }
        )
    for field, maximum in (("name", MAX_PLAN_NAME_CHARACTERS), ("instructions", MAX_INSTRUCTIONS_BYTES)):
        if field in data and (
            not isinstance(data[field], str)
            or not data[field].strip()
            or (len(data[field]) if field == "name" else _text_bytes(data[field]))
            > maximum
        ):
            errors.append(
                {
                    "code": "invalid_brief",
                    "path": f"$.{field}",
                    "message": f"{field} must be non-empty text within its {maximum} limit.",
                }
            )

    version = data.get("contract_version")
    if "contract_version" in data and (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != CONTRACT_VERSION
    ):
        errors.append(
            {
                "code": "contract_version",
                "path": "$.contract_version",
                "message": "Unsupported plan contract version.",
                "expected": CONTRACT_VERSION,
            }
        )

    proposal = data.get("proposal")
    if "proposal" not in data:
        return _bounded_validation_errors(errors)
    if not isinstance(proposal, dict):
        errors.append(
            {
                "code": "type",
                "path": "$.proposal",
                "message": "proposal must be an object.",
                "expected": "object",
            }
        )
        return _bounded_validation_errors(errors)

    usage_schema = file_usage_schema()
    errors.extend(
        _schema_errors(
            data.get("file_usage"), usage_schema, usage_schema, "$.file_usage"
        )
    )
    schema = external_report_proposal_response_schema(
        allowed_actions=_external_allowed_report_actions(user),
        include_submission_fields=True,
        require_file_summary_terms=True,
    )
    errors.extend(_schema_errors(proposal, schema, schema, "$.proposal"))

    summary = proposal.get("summary")
    if isinstance(summary, str) and not summary.strip():
        errors.append(
            {
                "code": "min_length",
                "path": "$.proposal.summary",
                "message": "summary must be a non-empty string.",
                "expected": "non-empty string",
            }
        )
    confidence = proposal.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        if not 0 <= confidence <= 1:
            errors.append(
                {
                    "code": "range",
                    "path": "$.proposal.confidence",
                    "message": "confidence must be from 0 to 1.",
                    "expected": {"minimum": 0, "maximum": 1},
                }
            )
    return _bounded_validation_errors(errors)


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::submission_validation_errors
# @reason truncation is asserted through the public collector
def _bounded_validation_errors(errors):
    unique = []
    seen = set()
    for error in errors:
        identity = (error.get("code"), error.get("path"), error.get("message"))
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(error)
    if len(unique) <= MAX_VALIDATION_ERRORS:
        return unique
    omitted = len(unique) - (MAX_VALIDATION_ERRORS - 1)
    return unique[: MAX_VALIDATION_ERRORS - 1] + [
        {
            "code": "validation_errors_truncated",
            "path": "$",
            "message": f"{omitted} additional validation errors were omitted.",
            "expected": {"maximum_reported": MAX_VALIDATION_ERRORS},
        }
    ]


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::submission_validation_errors
# @reason the public collector exercises this bounded JSON Schema subset
def _schema_errors(value, schema, root, path):
    if not isinstance(schema, dict):
        return []
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return _schema_errors(value, target, root, path)

    errors = []
    discriminator = schema.get("discriminator")
    if (
        "oneOf" in schema
        and isinstance(discriminator, dict)
        and isinstance(value, dict)
    ):
        property_name = discriminator.get("propertyName")
        mapping = discriminator.get("mapping") or {}
        selected = mapping.get(value.get(property_name))
        if not selected:
            return [
                {
                    "code": "enum",
                    "path": f"{path}.{property_name}",
                    "message": "Unknown action type.",
                    "expected": sorted(mapping),
                }
            ]
        return _schema_errors(value, {"$ref": selected}, root, path)

    for child in schema.get("allOf") or []:
        errors.extend(_schema_errors(value, child, root, path))
    if "if" in schema:
        branch = "else" if _schema_errors(value, schema["if"], root, path) else "then"
        if branch in schema:
            errors.extend(_schema_errors(value, schema[branch], root, path))
    for keyword in ("anyOf", "oneOf"):
        choices = schema.get(keyword) or []
        if choices:
            candidates = [_schema_errors(value, child, root, path) for child in choices]
            matches = sum(not candidate for candidate in candidates)
            if not matches:
                errors.extend(min(candidates, key=len))
            elif keyword == "oneOf" and matches != 1:
                errors.append(
                    {
                        "code": "one_of",
                        "path": path,
                        "message": "Value must match exactly one schema alternative.",
                        "expected": "exactly one alternative",
                    }
                )

    expected_type = schema.get("type")
    if expected_type and not _schema_type_matches(value, expected_type):
        return errors + [
            {
                "code": "type",
                "path": path,
                "message": f"Value must be {expected_type}.",
                "expected": expected_type,
            }
        ]
    if "const" in schema and value != schema["const"]:
        errors.append(
            {
                "code": "const",
                "path": path,
                "message": "Value does not match the required constant.",
                "expected": schema["const"],
            }
        )
    if "enum" in schema and value not in schema["enum"]:
        errors.append(
            {
                "code": "enum",
                "path": path,
                "message": "Value is not one of the allowed values.",
                "expected": schema["enum"],
            }
        )

    if isinstance(value, dict):
        if len(value) < int(schema.get("minProperties") or 0):
            errors.append({"code": "minProperties", "path": path, "message": "Provide at least one changed field."})
        properties = schema.get("properties") or {}
        for field in schema.get("required") or []:
            if field not in value:
                errors.append(
                    {
                        "code": "required",
                        "path": f"{path}.{field}",
                        "message": f"{field} is required.",
                        "expected": "present",
                    }
                )
        if schema.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(
                    {
                        "code": "additional_property",
                        "path": f"{path}.{field}",
                        "message": "Unsupported field.",
                    }
                )
        for field, child in value.items():
            if field in properties:
                errors.extend(
                    _schema_errors(child, properties[field], root, f"{path}.{field}")
                )
    elif isinstance(value, list):
        if len(value) < int(schema.get("minItems") or 0):
            errors.append(
                {
                    "code": "min_items",
                    "path": path,
                    "message": "Array has too few items.",
                    "expected": {"minimum": schema["minItems"]},
                }
            )
        maximum = schema.get("maxItems")
        if maximum is not None and len(value) > maximum:
            errors.append(
                {
                    "code": "max_items",
                    "path": path,
                    "message": "Array has too many items.",
                    "expected": {"maximum": maximum},
                }
            )
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, default=str) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(
                    {
                        "code": "unique_items",
                        "path": path,
                        "message": "Array items must be unique.",
                        "expected": "unique items",
                    }
                )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    _schema_errors(item, item_schema, root, f"{path}[{index}]")
                )
    elif isinstance(value, str):
        if schema.get("format") == "date":
            from ..reporting.schedules import validate_task_due_date

            try:
                validate_task_due_date(value)
            except exceptions.AIException as error:
                errors.append(
                    {
                        "code": "format",
                        "path": path,
                        "message": str(error),
                        "expected": "YYYY-MM-DD",
                    }
                )
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(value) < minimum:
            errors.append(
                {
                    "code": "min_length",
                    "path": path,
                    "message": "String is too short.",
                    "expected": {"minimum_length": minimum},
                }
            )
        if maximum is not None and len(value) > maximum:
            errors.append(
                {
                    "code": "max_length",
                    "path": path,
                    "message": "String is too long.",
                    "expected": {"maximum_length": maximum},
                }
            )
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        for bound in ("minimum", "maximum"):
            threshold = schema.get(bound)
            if threshold is not None and (
                (bound == "minimum" and value < threshold)
                or (bound == "maximum" and value > threshold)
            ):
                errors.append(
                    {
                        "code": bound,
                        "path": path,
                        "message": f"Number is outside the allowed {bound}.",
                        "expected": {bound: threshold},
                    }
                )
    return errors


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::submission_validation_errors
# @reason type discrimination is asserted through public field errors
def _schema_type_matches(value, expected):
    expected = expected if isinstance(expected, list) else [expected]
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return any(checks.get(name, lambda _item: True)(value) for name in expected)


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::validate_external_proposal
# @reason recursive string discovery belongs to external proposal validation
def _walk_strings(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield value


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::validate_external_proposal
# @reason reference-field traversal belongs to external proposal validation
def _reference_values(proposal):
    for action in proposal.get("actions") or []:
        data = action.get("data") if isinstance(action, dict) else None
        if not isinstance(data, dict):
            continue
        for row in data.get("conversions", []):
            if isinstance(row, dict) and isinstance(row.get("entity"), str):
                yield "entity", row["entity"]
        changes = data.get("changes") or {}
        for field in ("page", "project", "model", "form", "assigned_to", "categories", "model_tasks"):
            value = changes.get(field) if isinstance(changes, dict) else None
            for reference in value if isinstance(value, list) else [value]:
                if isinstance(reference, str) and reference:
                    yield field, reference
        for field, value in data.items():
            if field not in REFERENCE_FIELDS:
                continue
            if isinstance(value, dict):
                value = value.get("id") or value.get("key") or value.get("hash")
            if isinstance(value, str) and value:
                yield field, value


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::validate_external_proposal
# @reason notation checks are exercised through the public validator
def _validate_reference_notation(proposal):
    for _field, value in _reference_values(proposal):
        if value.startswith(("$", "action:")):
            continue
        if HASH_REFERENCE_REGEX.fullmatch(value):
            continue
        if HASH_PREFIXED_ID_REGEX.fullmatch(value) or database_get.is_urlsafe_key(
            value
        ):
            raise exceptions.AIException(
                "Proposal references must use hash:<12-character-hash>, not internal ids."
            )
        raise exceptions.AIException(
            "Proposal contains an invalid existing-entity reference."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::validate_external_proposal
# @reason visibility checks are exercised through the public validator
def _validate_reference_visibility(proposal, report, user):
    hashes = {
        match
        for text in _walk_strings(proposal)
        for match in HASH_REFERENCE_REGEX.findall(text)
    }
    if not hashes:
        return
    details = cache.get_details_by_hash(sorted(hashes))
    if (
        not isinstance(details, dict)
        or set(details) != hashes
        or any(
            not isinstance(details.get(value), dict) or not details[value].get("id")
            for value in hashes
        )
    ):
        raise exceptions.AIException(
            "Proposal contains an inaccessible or unknown entity reference."
        )

    entities = Entities.fetch(
        *[details[value].get("id") for value in hashes],
        request=Fetch.nested(
            because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION
        ),
    )
    by_hash = {entity.hash: entity for entity in entities if entity}
    report_files = {file.hash for file in report.input_files}
    for value in hashes:
        entity = by_hash.get(value)
        if not entity or (
            value not in report_files and not entity.allowed(Action.VIEW, user=user)
        ):
            raise exceptions.AIException(
                "Proposal contains an inaccessible or unknown entity reference."
            )


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::validate_external_proposal
# @reason shape and size checks are exercised through the public validator
def _validate_top_level(proposal):
    if not isinstance(proposal, dict):
        raise exceptions.AIException("Proposal must be a JSON object.")
    unsupported = set(proposal) - {
        "summary",
        "answer_markdown",
        "confidence",
        "issues",
        "actions",
    }
    if unsupported:
        raise exceptions.AIException(
            f"Proposal contains unsupported fields: {', '.join(sorted(unsupported))}"
        )
    try:
        encoded = json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise exceptions.AIException(
            "Proposal must contain valid JSON values."
        ) from error
    if len(encoded.encode("utf-8")) > MAX_PROPOSAL_BYTES:
        raise exceptions.AIException("Proposal is too large.")
    if not isinstance(proposal.get("summary"), str) or not proposal["summary"].strip():
        raise exceptions.AIException("Proposal summary must be a non-empty string.")
    confidence = proposal.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        raise exceptions.AIException(
            "Proposal confidence must be a number from 0 to 1."
        )
    actions = proposal.get("actions")
    if not isinstance(actions, list):
        raise exceptions.AIException("Proposal actions must be a list.")
    if len(actions) > MAX_PROPOSAL_ACTIONS:
        raise exceptions.AIException("Proposal contains too many actions.")


# @testable false
# @covered-by lagniappe/core/tools/ai/external/validation.py::validate_external_proposal
# @reason Ask hash-token checks distinguish rendered labels from link destinations
def _answer_visible_text(field, value):
    if field == "answer_markdown":
        return strip_tags(render_markdown(value))
    return value


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_validation_enforces_permissions_files_and_shape
# @tests tests_unit/test_032_agent_api.py::test_external_ask_submission_allows_hash_token_in_named_link_destination
# @matrix agent-api ai-report : file-placement file-summary permissions proposal-validation references
# @pairs agent-api:ask ai-report:answer-only
def validate_external_proposal(
    proposal, report, user, *, file_usage, instructions=None, resolved_references=None
):
    """Validate an external final proposal without provider repair."""
    _validate_top_level(proposal)
    proposal = deepcopy(proposal)
    if not report.available:
        raise exceptions.AIException("this plan is no longer available")
    for field in ("summary", "answer_markdown"):
        value = proposal.get(field)
        visible = (
            _answer_visible_text(field, value) if isinstance(value, str) else value
        )
        if isinstance(visible, str) and HASH_REFERENCE_REGEX.search(visible):
            raise exceptions.AIException(
                "Answers must use human names and URLs instead of hash tokens."
            )
    usage = validate_file_usage(
        file_usage,
        report_file_references(report),
        require_organization=not str(
            instructions if instructions is not None else report.instructions or ""
        ).strip(),
    )
    _validate_reference_notation(proposal)
    _validate_reference_visibility(proposal, report, user)
    allowed = _external_allowed_report_actions(user)
    resolved_details = {}
    normalized = validate_proposal(
        proposal,
        allowed_actions=allowed,
        allow_pending_submissions=False,
        required_file_refs=[
            item["file"] for item in usage if item["usage"] == "organize"
        ],
        require_file_summaries=True,
        validate_reference_kinds=True,
        user=user,
        preserve_document_markdown=True,
        resolved_reference_details=resolved_details,
    )
    from ..reporting.schema_updates import prepare_schema_updates

    prepare_schema_updates(normalized, user)
    from ..reporting.entity_updates import prepare_entity_updates
    prepare_entity_updates(normalized, user)
    if resolved_references is not None:
        resolved_references.update(
            {
                item["id"]: f"hash:{entity_hash}"
                for entity_hash, item in resolved_details.items()
                if isinstance(item, dict) and item.get("id")
            }
        )
    return normalized
