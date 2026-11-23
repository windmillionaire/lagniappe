"""Versioned, authorized contracts for filter requests and saved filters."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from ...entities.category import Category
    from ...entities.project import Project
    from ...entities.form import Form
    from ...entities.entity import Entity
    from ...mixins.field_host import FieldUser
    from ...mixins.filter import FilterMixin

from dataclasses import dataclass
from datetime import datetime, time, UTC
import json
from typing import Never
from math import isfinite

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    Comparator,
    Fetch,
    FieldType,
    FilterDefinition,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, dates


type FilterParent = Category | Project


class FilterCondition(TypedDict):
    source_id: str
    field: str
    comparator: str
    values: list[object]


class FilterContract(TypedDict):
    version: int
    conditions: list[FilterCondition]


FILTER_CONTRACT_VERSION = 1
MAX_CONTRACT_BYTES = 32 * 1024
MAX_EFFECTIVE_CONDITIONS = 12
MAX_VALUES_PER_CONDITION = 25
MAX_SCALAR_BYTES = 512
SUPPORTED_PARENT_KINDS = frozenset({"category", "project"})
SUPPORTED_COMPARATORS = frozenset(
    {
        Comparator.IS_TRUE,
        Comparator.IS_FALSE,
        Comparator.EQUALS,
        Comparator.GREATER_THAN,
        Comparator.LESS_THAN,
        Comparator.GREATER_EQUAL,
        Comparator.LESS_EQUAL,
        Comparator.CONTAINS,
        Comparator.IN,
        Comparator.SUBSTRING,
        Comparator.CONTAINS_ANY,
        Comparator.BETWEEN,
    }
)
_CONTRACT_KEYS = frozenset({"version", "conditions"})
_CONDITION_KEYS = frozenset({"source_id", "field", "comparator", "values"})


class FilterContractError(exceptions.ValidationError):
    """A safe filter-contract error with a stable location and HTTP status."""

    def __init__(self, message: str, *, path: str = "filter", code: str = "invalid", status: int = 422) -> None:
        super().__init__(message)
        self.path = path
        self.code = code
        self.status = status


@dataclass(frozen=True)
class FilterField:
    """An authorized filter field and any exact entity values it accepts."""

    source: Entity
    field: FilterMixin
    allowed_values: dict[str, Entity] | None = None


@dataclass(frozen=True)
class CompiledFilter:
    """Validated query predicates plus their canonical persisted contract."""

    definitions: tuple[FilterDefinition, ...]
    contract: FilterContract
    related: tuple[Entity, ...]


def _error(message: str, *, path: str = "filter", code: str = "invalid", status: int = 422) -> Never:
    raise FilterContractError(message, path=path, code=code, status=status)


def _json_bytes(value):
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _bounded_text(value, path, *, allow_empty=False):
    if not isinstance(value, str):
        _error(f"{path} must be a string.", path=path, code="shape")
    value = value.strip()
    if not value and not allow_empty:
        _error(f"{path} must not be empty.", path=path, code="value")
    if len(value.encode("utf-8")) > MAX_SCALAR_BYTES:
        _error(
            f"{path} is too long.",
            path=path,
            code="limit",
        )
    return value


def parse_filter_request(contract_value: object, definition_values: Iterable[object] | None) -> object:
    """Parse one v1 request envelope or adapt repeated legacy definitions."""
    definition_values = list(definition_values or ())
    if contract_value and definition_values:
        _error(
            "Submit either contract or definition values, not both.",
            code="shape",
            status=400,
        )
    if contract_value:
        if not isinstance(contract_value, str):
            _error("Filter contract must be JSON.", code="shape", status=400)
        if len(contract_value.encode("utf-8")) > MAX_CONTRACT_BYTES:
            _error("Filter contract is too large.", code="limit")
        try:
            return json.loads(contract_value)
        except (TypeError, json.JSONDecodeError):
            _error(
                "Filter contract contains malformed JSON.", code="malformed", status=400
            )

    if not definition_values:
        return {"version": FILTER_CONTRACT_VERSION, "conditions": []}
    if sum(len(str(value).encode("utf-8")) for value in definition_values) > (
        MAX_CONTRACT_BYTES
    ):
        _error("Filter contract is too large.", code="limit")

    decoded = []
    try:
        for value in definition_values:
            decoded.append(json.loads(value) if isinstance(value, str) else value)
    except (TypeError, json.JSONDecodeError):
        _error(
            "Filter definition contains malformed JSON.", code="malformed", status=400
        )

    if all(isinstance(value, dict) for value in decoded):
        return {"version": FILTER_CONTRACT_VERSION, "conditions": decoded}
    if not all(isinstance(value, list) for value in decoded):
        _error(
            "Filter definitions use mixed or invalid shapes.", code="shape", status=400
        )
    return legacy_definitions_to_contract(decoded)


def legacy_definitions_to_contract(definitions: object) -> dict[str, object]:
    """Convert compact v0 definition lists without trusting their type flags."""
    if not isinstance(definitions, list):
        _error("Saved filter definitions must be a list.", code="shape")

    conditions = []
    for index, definition in enumerate(definitions):
        path = f"conditions[{index}]"
        if not isinstance(definition, list) or not 4 <= len(definition) <= 6:
            _error(f"{path} has an invalid legacy shape.", path=path, code="shape")
        source_id, field, _discarded_type, comparator = definition[:4]
        value = definition[4] if len(definition) > 4 else None
        values = (
            value if isinstance(value, list) else ([] if value is None else [value])
        )
        conditions.append(
            {
                "source_id": source_id,
                "field": field,
                "comparator": comparator,
                "values": values,
            }
        )
    return {"version": FILTER_CONTRACT_VERSION, "conditions": conditions}


def load_filter_contract(value: object) -> object:
    """Decode a saved v1 contract or adapt the legacy top-level list."""
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        _error("Saved filter is malformed.", code="malformed")
    if isinstance(decoded, list):
        return legacy_definitions_to_contract(decoded)
    return decoded


def condition_contract(definition: FilterDefinition) -> FilterCondition:
    """Project a derived predicate into one explicit v1 condition object."""
    value = definition.value
    values = value if isinstance(value, list) else ([] if value is None else [value])
    return {
        "source_id": definition.entity_hash,
        "field": definition.field,
        "comparator": definition.comparator.value,
        "values": values,
    }


def _validate_parent(parent, user):
    if not parent or getattr(parent, "kind", None) not in SUPPORTED_PARENT_KINDS:
        _error("Filter parent must be a project or category.", code="parent")
    if not parent.allowed(Action.VIEW, user=user):
        _error("Access denied.", code="unavailable")


def _source_identifiers(source):
    return {
        str(identifier)
        for identifier in (
            getattr(source, "hash", None),
            getattr(source, "urlsafe_key", None),
            getattr(source, "key", None),
        )
        if identifier is not None
    }


def _catalog_source(catalog, source_id):
    normalized = str(source_id or "").removeprefix("hash:")
    return next(
        (
            entry.source
            for entry in catalog.values()
            if normalized in _source_identifiers(entry.source)
        ),
        None,
    )


def _add_catalog_field(catalog: dict[tuple[str, str], FilterField], source: Entity, field: FilterMixin, allowed_value: Entity | None = None) -> None:
    key = (source.hash, field.filter_key)
    entry = catalog.get(key)
    if not entry:
        entry = FilterField(
            source,
            field,
            allowed_values={} if allowed_value else None,
        )
        catalog[key] = entry
    if allowed_value:
        assert entry.allowed_values is not None
        entry.allowed_values[allowed_value.hash] = allowed_value


def field_catalog(parent: FilterParent, user: FieldUser) -> dict[tuple[str, str], FilterField]:
    """Return the filter surface visible under ``parent`` to ``user``."""
    _validate_parent(parent, user)
    if hasattr(parent, "properties"):
        # Fetching an instantiated entity keeps its concrete kind.
        parent = cast("FilterParent", Entities.fetch_one(parent, request=Fetch.direct()) or parent)
    catalog = {}
    for field in parent.filters.fields.values():
        _add_catalog_field(catalog, parent, field)

    for relation_field in parent.filters.entity_fields.values():
        related = cast("Entity | None", relation_field.value)
        if (
            not related
            or getattr(related, "reserved", False)
            or not related.allowed(Action.VIEW, user=user)
        ):
            continue
        _add_catalog_field(catalog, parent, relation_field, allowed_value=related)
        if getattr(related, "kind", None) == "form":
            if getattr(related, "db", {}).get("pending_form_change"):
                continue
            for field in cast("Form", related).filters.fields.values():
                _add_catalog_field(catalog, related, field)
    return catalog


def resolve_filter_field(parent: FilterParent, source_id: object, field_name: str | None, user: FieldUser) -> FilterField:
    """Resolve a submitted source and field only through the authorized catalog."""
    catalog = field_catalog(parent, user)
    source = _catalog_source(catalog, source_id)
    entry = catalog.get((source.hash, field_name)) if source and field_name else None
    if not entry and source:
        normalized_field = str(field_name or "").removeprefix("hash:")
        entry = next(
            (
                candidate
                for candidate in catalog.values()
                if candidate.source.hash == source.hash
                and any(
                    normalized_field in _source_identifiers(value)
                    for value in (candidate.allowed_values or {}).values()
                )
            ),
            None,
        )
    if not entry:
        _error("Filter field is unavailable.", path="field", code="unavailable")
    return entry


def resolve_allowed_value(entry: FilterField, value: object) -> Entity:
    """Resolve a dynamic selector value from an entry's exact allowed set."""
    normalized = str(value or "").removeprefix("hash:")
    entity = next(
        (
            candidate
            for candidate in (entry.allowed_values or {}).values()
            if normalized in _source_identifiers(candidate)
        ),
        None,
    )
    if not entity:
        _error("Filter entity is unavailable.", path="values", code="unavailable")
    return entity


def _effective_field_type(field):
    if getattr(field, "_is_categorical", False):
        return FieldType.LIST
    return field.field_type


def field_comparators(field: FilterMixin) -> list[Comparator]:
    """Return the canonical comparator set for one field."""
    options = field.field_options or ()
    available = {
        Comparator[option.name]
        for option in options
        if option.name in Comparator.__members__
    }
    supported = available & SUPPORTED_COMPARATORS
    field_type = _effective_field_type(field)
    if field_type == FieldType.BOOLEAN:
        supported &= {Comparator.IS_TRUE, Comparator.IS_FALSE}
    elif field_type == FieldType.LIST:
        supported &= {Comparator.CONTAINS, Comparator.CONTAINS_ANY}
    elif field.is_entity_valued:
        supported = {Comparator.EQUALS, Comparator.IN}
    elif field_type == FieldType.STRING:
        supported &= {Comparator.EQUALS, Comparator.IN, Comparator.SUBSTRING}
    return sorted(supported, key=lambda comparator: comparator.value)


def _comparator(value, field, index):
    path = f"conditions[{index}].comparator"
    value = _bounded_text(value, path).lower()
    try:
        comparator = Comparator(value)
    except ValueError:
        _error(f"{path} is unknown.", path=path, code="comparator")

    # Older AI callers described categorical membership as ``in``. Normalize
    # that spelling to the list semantics used by the browser and cache.
    if getattr(field, "_is_categorical", False) and comparator == Comparator.IN:
        comparator = Comparator.CONTAINS_ANY

    if comparator not in field_comparators(field):
        allowed = ", ".join(item.value for item in field_comparators(field))
        _error(
            f"{path} is not valid for {field.filter_key}. Allowed: {allowed}.",
            path=path,
            code="comparator",
        )
    return comparator


def _entity_filter_value(entry, value, user, index):
    path = f"conditions[{index}].values"
    identifier = _bounded_text(value, path)
    entity = Entities.fetch_one(identifier, request=Fetch.direct())
    if not entity:
        normalized = identifier.removeprefix("hash:")
        details = cache.get_details_by_hash([normalized]).get(normalized)
        if details and (entity_id := details.get("id")):
            entity = Entities.fetch_one(entity_id, request=Fetch.direct())
    if not entity or not entity.allowed(Action.VIEW, user=user):
        _error(
            f"Filter condition {index + 1} references an unavailable entity.",
            path=path,
            code="unavailable",
        )
    if entry.allowed_values and entity.hash not in entry.allowed_values:
        _error(
            f"Filter condition {index + 1} entity is not valid for {entry.field.filter_key}.",
            path=path,
            code="unavailable",
        )

    expected_index = getattr(entry.field, "index", None)
    if expected_index == "user":
        if isinstance(entity, Entities.USER):
            entity = entity.page
        if (
            not entity
            or getattr(entity, "kind", None) != "page"
            or not entity.allowed(Action.VIEW, user=user)
        ):
            _error("Filter assignee is unavailable.", path=path, code="unavailable")
    elif (
        expected_index in {"category", "project"}
        and getattr(entity, "kind", None) != expected_index
    ):
        _error("Filter entity has the wrong type.", path=path, code="unavailable")

    return entity.hash, entity


def _scalar_filter_value(field, value, user, index):
    path = f"conditions[{index}].values"
    if isinstance(value, (dict, list, tuple, set)) or value is None:
        _error(f"{path} must contain scalar values.", path=path, code="shape")

    choices = getattr(field, "choices", None)
    if isinstance(choices, dict) and choices:
        if value in choices:
            return value
        label_match = next(
            (
                choice
                for choice, label in choices.items()
                if str(label).casefold() == str(value).casefold()
            ),
            None,
        )
        if label_match is not None:
            return label_match
        _error(
            f"Filter condition {index + 1} value is not an available choice.",
            path=path,
            code="value",
        )

    field_type = _effective_field_type(field)
    if field_type == FieldType.NUMBER:
        if isinstance(value, bool):
            _error(f"{path} requires a number.", path=path, code="value")
        try:
            number = float(value)
        except (TypeError, ValueError):
            _error(f"{path} requires a number.", path=path, code="value")
        if not isfinite(number):
            _error(f"{path} requires a finite number.", path=path, code="value")
        return number
    if field_type == FieldType.TIMESTAMP:
        return _timestamp_value(value, user, index)
    return _bounded_text(str(value), path)


def _timestamp_value(value, user, index):
    path = f"conditions[{index}].values"
    if isinstance(value, bool):
        _error(f"{path} requires an ISO date or timestamp.", path=path, code="value")
    if isinstance(value, (int, float)):
        instant = float(value)
        if not isfinite(instant):
            _error(f"{path} requires a finite timestamp.", path=path, code="value")
        return {"instant": instant, "date_only": False}
    text = _bounded_text(value, path)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _error(f"{path} requires an ISO date or datetime.", path=path, code="value")

    date_only = "T" not in text and " " not in text
    user_timezone = dates.user_timezone(user)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=user_timezone)
    parsed = parsed.astimezone(UTC)
    if not date_only:
        return {"instant": parsed.timestamp(), "date_only": False}

    local_date = parsed.astimezone(user_timezone).date()
    start = datetime.combine(local_date, time.min, tzinfo=user_timezone)
    end = datetime.combine(local_date, time.max, tzinfo=user_timezone)
    return {
        "start": start.astimezone(UTC).timestamp(),
        "end": end.astimezone(UTC).timestamp(),
        "date_only": True,
    }


def _timestamp_condition(comparator, values):
    if comparator == Comparator.BETWEEN:
        start = values[0].get("start", values[0].get("instant"))
        end = values[1].get("end", values[1].get("instant"))
        return comparator, [start, end]
    value = values[0]
    if not value["date_only"]:
        return comparator, value["instant"]
    if comparator == Comparator.EQUALS:
        return Comparator.BETWEEN, [value["start"], value["end"]]
    if comparator in {Comparator.LESS_EQUAL, Comparator.GREATER_THAN}:
        return comparator, value["end"]
    return comparator, value["start"]


def _condition_value(entry, comparator, values, user, index, related):
    path = f"conditions[{index}].values"
    if not isinstance(values, list):
        _error(f"{path} must be a list.", path=path, code="shape")
    if len(values) > MAX_VALUES_PER_CONDITION:
        _error(f"{path} has too many values.", path=path, code="limit")
    if comparator in {Comparator.IS_TRUE, Comparator.IS_FALSE}:
        if values:
            _error(f"{path} must be empty for a boolean condition.", path=path)
        return comparator, None

    if comparator == Comparator.BETWEEN and len(values) != 2:
        _error(f"{path} requires exactly two values.", path=path, code="value")
    if comparator != Comparator.BETWEEN and not values:
        _error(f"{path} requires a value.", path=path, code="value")

    if entry.field.is_entity_valued:
        normalized = []
        for value in values:
            normalized_value, entity = _entity_filter_value(entry, value, user, index)
            normalized.append(normalized_value)
            related[entity.hash] = entity
    else:
        normalized = [
            _scalar_filter_value(entry.field, value, user, index) for value in values
        ]

    if _effective_field_type(entry.field) == FieldType.TIMESTAMP:
        return _timestamp_condition(comparator, normalized)
    if comparator in {Comparator.IN, Comparator.CONTAINS_ANY, Comparator.BETWEEN}:
        return comparator, normalized
    if len(normalized) != 1:
        _error(f"{path} requires exactly one value.", path=path, code="value")
    return comparator, normalized[0]


def _canonical_condition(entry: FilterField, comparator: Comparator, value: object) -> FilterCondition:
    values = value if isinstance(value, list) else ([] if value is None else [value])
    return {
        "source_id": entry.source.hash,
        "field": entry.field.filter_key,
        "comparator": comparator.value,
        "values": values,
    }


def compile_filter_contract(parent: FilterParent, contract: object, user: FieldUser, *, allow_default_source: bool = False) -> CompiledFilter:
    """Validate a v1 DTO against the current authorized field catalog."""
    _validate_parent(parent, user)
    if not isinstance(contract, dict):
        _error("Filter contract must be an object.", code="shape", status=400)
    if set(contract) != _CONTRACT_KEYS:
        _error("Filter contract has invalid keys.", code="shape", status=400)
    if contract.get("version") != FILTER_CONTRACT_VERSION:
        _error("Filter contract version is unsupported.", code="version", status=400)
    if _json_bytes(contract) > MAX_CONTRACT_BYTES:
        _error("Filter contract is too large.", code="limit")

    conditions = contract.get("conditions")
    if not isinstance(conditions, list):
        _error(
            "Filter conditions must be a list.",
            path="conditions",
            code="shape",
            status=400,
        )
    if not conditions:
        _error(
            "Please add at least one filter condition.", path="conditions", code="value"
        )

    catalog = field_catalog(parent, user)
    definitions = []
    canonical = []
    related: dict[str, Entity] = {parent.hash: parent}
    form_scopes = set()

    for index, condition in enumerate(conditions):
        path = f"conditions[{index}]"
        if not isinstance(condition, dict):
            _error(f"{path} must be an object.", path=path, code="shape", status=400)
        allowed_keys = _CONDITION_KEYS
        required_keys = allowed_keys - (
            {"source_id"} if allow_default_source else set()
        )
        if not required_keys.issubset(condition) or not set(condition).issubset(
            allowed_keys
        ):
            _error(f"{path} has invalid keys.", path=path, code="shape", status=400)

        source_id = condition.get("source_id") or parent.hash
        source_id = _bounded_text(source_id, f"{path}.source_id")
        field_name = _bounded_text(condition.get("field"), f"{path}.field")
        source = _catalog_source(catalog, source_id)
        entry = catalog.get((source.hash, field_name)) if source else None
        if not entry:
            matching_sources = {
                candidate.source.hash
                for candidate in catalog.values()
                if candidate.field.filter_key == field_name
            }
            hint = ""
            if len(matching_sources) == 1:
                source_hint = f"hash:{next(iter(matching_sources))}"
                hint = f" Use source_id {source_hint!r}."
            _error(
                f"Filter condition {index + 1} uses unavailable field "
                f"{field_name!r}.{hint}",
                path=path,
                code="unavailable",
            )

        if entry.source.kind == "form" and entry.source.hash not in form_scopes:
            selector = catalog.get((parent.hash, "form"))
            if not selector or entry.source.hash not in (selector.allowed_values or {}):
                _error(
                    f"Filter condition {index + 1} form is not attached to this {parent.kind}.",
                    path=path,
                    code="unavailable",
                )
            definitions.append(
                FilterDefinition(
                    parent.hash,
                    selector.field.filter_key,
                    selector.field.field_type,
                    Comparator.EQUALS,
                    entry.source.hash,
                    True,
                )
            )
            related[entry.source.hash] = entry.source
            form_scopes.add(entry.source.hash)

        comparator = _comparator(condition.get("comparator"), entry.field, index)
        comparator, value = _condition_value(
            entry,
            comparator,
            condition.get("values"),
            user,
            index,
            related,
        )
        definition = FilterDefinition(
            entry.source.hash,
            entry.field.filter_key,
            _effective_field_type(entry.field),
            comparator,
            value,
            entry.field.is_entity_valued,
        )
        definitions.append(definition)
        related[entry.source.hash] = entry.source
        canonical.append(_canonical_condition(entry, comparator, value))

        if entry.source.hash == parent.hash and entry.field.filter_key == "form":
            selected = value if isinstance(value, list) else [value]
            form_scopes.update(selected)

    deduplicated = []
    descriptions = set()
    for definition in definitions:
        description = json.dumps(definition.description, sort_keys=True)
        if description not in descriptions:
            deduplicated.append(definition)
            descriptions.add(description)
    if len(deduplicated) > MAX_EFFECTIVE_CONDITIONS:
        _error(
            f"A filter may contain at most {MAX_EFFECTIVE_CONDITIONS} effective conditions.",
            path="conditions",
            code="limit",
        )

    canonical_contract: FilterContract = {
        "version": FILTER_CONTRACT_VERSION,
        "conditions": canonical,
    }
    if _json_bytes(canonical_contract) > MAX_CONTRACT_BYTES:
        _error("Filter contract is too large after normalization.", code="limit")
    return CompiledFilter(
        definitions=tuple(deduplicated),
        contract=canonical_contract,
        related=tuple(related.values()),
    )


def compile_saved_filter(parent: FilterParent, stored_value: object, user: FieldUser) -> CompiledFilter:
    """Compile either stored v1 data or a legacy v0 list."""
    contract = load_filter_contract(stored_value)
    return compile_filter_contract(parent, contract, user)


def _entity_reference(entity):
    return {
        "kind": entity.kind,
        "hash": f"hash:{entity.hash}",
        "name": entity.name,
    }


def _field_choices(field):
    choices = getattr(field, "choices", None)
    if not isinstance(choices, dict):
        return []
    return [{"value": value, "label": label} for value, label in choices.items()]


def describe_filter_contract(parent: FilterParent, user: FieldUser) -> dict[str, object]:
    """Describe the same authorized contract surface used for compilation."""
    catalog = field_catalog(parent, user)
    fields = []
    for entry in catalog.values():
        field = entry.field
        description = {
            "source": _entity_reference(entry.source),
            "field": field.filter_key,
            "label": field.filter_label or field.filter_key,
            "type": _effective_field_type(field).value,
            "comparators": [item.value for item in field_comparators(field)],
            "entity_valued": bool(field.is_entity_valued),
        }
        choices = _field_choices(field)
        if choices:
            description["choices"] = choices
        if entry.allowed_values:
            description["allowed_values"] = [
                _entity_reference(entity)
                for entity in sorted(
                    entry.allowed_values.values(),
                    key=lambda value: (value.name or "").casefold(),
                )
            ]
        fields.append(description)
    fields.sort(
        key=lambda item: (
            item["source"]["kind"] != parent.kind,
            (item["source"]["name"] or "").casefold(),
            item["label"].casefold(),
        )
    )
    return {
        "parent": _entity_reference(parent),
        "result_kind": "task" if parent.kind == "project" else "page",
        "condition_logic": "all",
        "contract_version": FILTER_CONTRACT_VERSION,
        "fields": fields,
    }
