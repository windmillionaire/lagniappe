"""Typed, authorized filter-contract behavior."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from google.cloud.datastore import Key

from config.datastore import encode_urlsafe_key

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
        self.key = Key(kind, hash_value, project="offline-filter-tests")
        self.urlsafe_key = encode_urlsafe_key(self.key)
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

    parent, _ = _fixture()
    unsupported = contract.parse_filter_request('{"version":2,"conditions":[]}', [])
    with pytest.raises(contract.FilterContractError) as version:
        contract.compile_filter_contract(parent, unsupported, object())
    assert version.value.status == 400
    assert version.value.code == "version"


@pytest.mark.unit
def test_legacy_definitions_discard_client_type_flags():
    parent, _category = _fixture()
    payload = contract.legacy_definitions_to_contract(
        [[parent.hash, "total", "string", "gt", "2.5", True]]
    )

    original = deepcopy(payload)
    compiled = contract.compile_filter_contract(parent, payload, object())
    assert payload == original

    assert compiled.definitions[0].field_type == FieldType.NUMBER
    assert compiled.definitions[0].is_entity_valued is False
    assert compiled.definitions[0].value == 2.5
    assert compiled.contract["conditions"][0]["values"] == [2.5]


@pytest.mark.unit
def test_compile_filter_contract_rederives_types_authorizes_entities_and_bounds_input(
    monkeypatch,
):
    parent, category = _fixture()
    monkeypatch.setattr(
        contract.Entities,
        "fetch",
        lambda *keys, request: [category] if category.key in keys else [],
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


@pytest.mark.unit
def test_filter_batches_hash_and_key_references_and_reuses_them_across_conditions(monkeypatch):
    parent, first = _fixture()
    second = _Entity("category", "category-two")
    batches = []
    hash_batches = []

    def details(hashes):
        hash_batches.append(list(hashes))
        return {second.hash: {"id": second.urlsafe_key}}

    def fetch(*keys, request):
        batches.append(set(keys))
        return [second, first]  # The backend need not preserve submitted order.

    monkeypatch.setattr(contract.cache, "get_details_by_hash", details)
    monkeypatch.setattr(contract.Entities, "fetch", fetch)
    condition = {"source_id": parent.hash, "field": "categories", "comparator": "contains_any"}
    compiled = contract.compile_filter_contract(parent, {
        "version": 1,
        "conditions": [
            {**condition, "values": [first.urlsafe_key, f"hash:{second.hash}", first.urlsafe_key]},
            {**condition, "values": [second.urlsafe_key, first.hash]},
        ],
    }, object())
    assert [item.value for item in compiled.definitions] == [
        [first.hash, second.hash, first.hash], [second.hash, first.hash],
    ]
    assert batches == [{first.key, second.key}]
    assert hash_batches == [[second.hash]]


@pytest.mark.unit
def test_filter_validates_entity_references_in_submitted_order(monkeypatch):
    parent, denied = _fixture()
    denied._allowed = False
    monkeypatch.setattr(contract.Entities, "fetch", lambda *keys, request: [denied])
    condition = {"source_id": parent.hash, "field": "categories", "comparator": "contains_any"}
    for values, expected_code in (([denied.urlsafe_key, 23], "unavailable"), ([23, denied.urlsafe_key], "shape")):
        with pytest.raises(contract.FilterContractError) as rejected:
            contract.compile_filter_contract(parent, {
                "version": 1, "conditions": [{**condition, "values": values}],
            }, object())
        assert (rejected.value.code, rejected.value.path) == (expected_code, "conditions[0].values")


@pytest.mark.unit
def test_filter_assignee_batch_uses_the_visible_account_page(monkeypatch):
    class Account(_Entity):
        pass

    parent, _ = _fixture()
    parent.filters.fields["assigned_to"] = _Field(
        "assigned_to", FieldType.STRING, FilterOptions.STRING.value,
        entity_valued=True, index="user",
    )
    account = Account("user", "account")
    page = _Entity("page", "account-page")
    account.page = page
    monkeypatch.setattr(contract.Entities, "USER", Account)
    monkeypatch.setattr(contract.Entities, "fetch", lambda *keys, request: [account])
    payload = {"version": 1, "conditions": [{
        "source_id": parent.hash, "field": "assigned_to",
        "comparator": "in", "values": [account.urlsafe_key],
    }]}
    assert contract.compile_filter_contract(parent, payload, object()).definitions[0].value == [page.hash]
    page._allowed = False
    with pytest.raises(contract.FilterContractError, match="assignee is unavailable"):
        contract.compile_filter_contract(parent, payload, object())


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

    with pytest.raises(contract.FilterContractError) as denied:
        filter_entity.compile(object())
    assert denied.value.code == "unavailable"
    assert filter_entity.compile(viewer) is compiled
