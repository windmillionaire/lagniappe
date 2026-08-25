"""Typed, authorized filter-contract behavior."""

import json
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import Comparator, FieldType, FilterOptions
from lagniappe.core.entities.filter import Filter as FilterEntity
from lagniappe.core.tools.filters import contract
from testing.utility.test_entities import TestEntities


class _Field:
    def __init__(
        self,
        key,
        field_type,
        options,
        *,
        entity_valued=False,
        index=None,
        choices=None,
    ):
        self.filter_key = key
        self.filter_label = key
        self.field_type = field_type
        self.field_options = options
        self.is_entity_valued = entity_valued
        self.index = index
        self.choices = choices


class _Entity:
    def __init__(self, kind, hash_value, *, fields=None, allowed=True):
        self.kind = kind
        self.hash = hash_value
        self.name = hash_value
        self.urlsafe_key = f"key-{hash_value}"
        self.key = self.urlsafe_key
        self.filters = SimpleNamespace(fields=fields or {}, entity_fields={})
        self._allowed = allowed

    def allowed(self, _action, user=None):
        return self._allowed


def _fixture():
    name = _Field("name", FieldType.STRING, FilterOptions.STRING.value)
    total = _Field("total", FieldType.NUMBER, FilterOptions.NUMBER.value)
    categories = _Field(
        "categories",
        FieldType.LIST,
        FilterOptions.LIST.value,
        entity_valued=True,
        index="category",
    )
    parent = _Entity(
        "project",
        "parent",
        fields={"name": name, "total": total, "categories": categories},
    )
    category = _Entity("category", "category-one")
    return parent, category


# @matrix filters : legacy limits malformed request-contract versioning
@pytest.mark.unit
def test_parse_filter_request_distinguishes_malformed_and_semantic_errors():
    with pytest.raises(contract.FilterContractError) as malformed:
        contract.parse_filter_request("{not-json", [])
    assert malformed.value.status == 400
    assert malformed.value.code == "malformed"

    with pytest.raises(contract.FilterContractError) as mixed:
        contract.parse_filter_request(
            '{"version":1,"conditions":[]}',
            ['["source","name","string","eq","value"]'],
        )
    assert mixed.value.status == 400

    oversized = "x" * (contract.MAX_CONTRACT_BYTES + 1)
    with pytest.raises(contract.FilterContractError) as limited:
        contract.parse_filter_request(oversized, [])
    assert limited.value.status == 422
    assert limited.value.code == "limit"


# @matrix filters : compatibility legacy saved-filter
@pytest.mark.unit
def test_legacy_definitions_discard_client_type_flags(monkeypatch):
    parent, _category = _fixture()
    payload = contract.legacy_definitions_to_contract(
        [[parent.hash, "total", "string", "gt", "2.5", True]]
    )

    compiled = contract.compile_filter_contract(parent, payload, object())

    assert compiled.definitions[0].field_type == FieldType.NUMBER
    assert compiled.definitions[0].is_entity_valued is False
    assert compiled.definitions[0].value == 2.5
    assert compiled.contract["conditions"][0]["values"] == [2.5]


# @matrix filters : authorization compilation limits normalization validation
@pytest.mark.unit
def test_compile_filter_contract_rederives_types_authorizes_entities_and_bounds_input(
    monkeypatch,
):
    parent, category = _fixture()
    monkeypatch.setattr(
        contract.Entities,
        "fetch_one",
        lambda value, request: (
            category if value in {category.hash, category.urlsafe_key} else None
        ),
    )
    payload = {
        "version": 1,
        "conditions": [
            {
                "source_id": parent.hash,
                "field": "categories",
                "comparator": "contains",
                "values": [category.urlsafe_key],
            }
        ],
    }

    compiled = contract.compile_filter_contract(parent, payload, object())

    definition = compiled.definitions[0]
    assert definition.field_type == FieldType.LIST
    assert definition.comparator == Comparator.CONTAINS
    assert definition.value == category.hash
    assert category in compiled.related

    category._allowed = False
    with pytest.raises(contract.FilterContractError, match="unavailable entity"):
        contract.compile_filter_contract(parent, payload, object())

    too_many = dict(payload)
    too_many["conditions"] = [
        {
            "source_id": parent.hash,
            "field": "name",
            "comparator": "in",
            "values": [
                str(index) for index in range(contract.MAX_VALUES_PER_CONDITION + 1)
            ],
        }
    ]
    with pytest.raises(contract.FilterContractError, match="too many values"):
        contract.compile_filter_contract(parent, too_many, object())


# @matrix filters permissions : authorization legacy saved-filter validation
@pytest.mark.unit
def test_saved_filter_compiles_legacy_data_per_viewer():
    viewer = object()
    project = TestEntities.get(
        "PROJECT",
        {"name": "Contract Project", "hash": "contract-project"},
    )
    project.allowed = lambda _action, user=None: user is viewer
    filter_entity = FilterEntity(testing=True)
    filter_entity.parent = project
    filter_entity.db["definitions"] = json.dumps(
        [[project.hash, "name", "number", "substring", "A-B", True]]
    )

    compiled = filter_entity.compile(viewer)

    assert compiled.definitions[0].field_type == FieldType.STRING
    assert compiled.definitions[0].is_entity_valued is False
    assert compiled.definitions[0].value == "A-B"
    assert compiled.contract == {
        "version": 1,
        "conditions": [
            {
                "source_id": project.hash,
                "field": "name",
                "comparator": "substring",
                "values": ["A-B"],
            }
        ],
    }

    filter_entity._conditions = ["stale-viewer-projection"]
    filter_entity._definitions = []
    assert filter_entity.compile(viewer) is compiled
    assert filter_entity._conditions is None
    assert filter_entity.definitions == list(compiled.definitions)
