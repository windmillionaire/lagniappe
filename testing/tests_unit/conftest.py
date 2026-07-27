"""
Unit test configuration for lagniappe/core testing.

Initializes the Entities registry and cleans up test data on teardown.
No server, no browser, no Playwright.

Fixtures:
    setup_unit_tests (session, autouse): Initializes Entities registry
    get_test_entities (function): Loads test entities from JSON files
"""

import json
import os
from pathlib import Path
import socket
import traceback

os.environ["FLASK_ENV"] = "testing"

import pytest

from lagniappe import CONFIG
from testing.utility.test_entities import TestEntities, TestUser

TEST_ENTITIES_DIR = Path(__file__).parent.parent / "files" / "test_entities"
TEST_SCHEMAS_DIR = Path(__file__).parent.parent / "files" / "test_schemas"


def _forbid_live_resource(resource):
    """Raise with the application caller when a unit test reaches live I/O."""

    def fail(*args, **kwargs):
        frames = [
            frame
            for frame in traceback.extract_stack()
            if "/lagniappe/" in frame.filename
            and "/testing/" not in frame.filename
            and not frame.filename.endswith("tools/cache/core.py")
            and not frame.filename.endswith("tools/database/core.py")
        ]
        caller = frames[-1] if frames else traceback.extract_stack()[-2]
        raise AssertionError(
            "Unit tests may not initialize or contact live "
            f"{resource}; attempted by {caller.filename}:{caller.lineno} "
            f"in {caller.name}"
        )

    return fail


class _ImportProcessStub:
    """Minimal ``import_process`` for ``SubmitterMixin.import_submission`` in unit tests."""

    def __init__(self, test_spec):
        self._fuzzy = {
            field_id
            for field_id, exp in test_spec.get("expected", {}).items()
            if exp.get("field_attrs", {}).get("fuzzy_match")
        }
        seps = [
            exp["field_attrs"]["separator"]
            for exp in test_spec.get("expected", {}).values()
            if "separator" in exp.get("field_attrs", {})
        ]
        self.separator = seps[0] if seps else ","

    def fuzzy_match(self, field_id):
        return field_id in self._fuzzy


@pytest.fixture(scope="session", autouse=True)
def setup_unit_tests(request):
    """Initialize Entities and cleanup test data after all tests."""
    if request.config.option.markexpr == "setup_drift":
        yield
        return

    from lagniappe.core.entities import Entities

    Entities.initialize()
    TestEntities.initialize(Entities)

    yield


@pytest.fixture(autouse=True)
def setup_current_test_user():
    CONFIG.TEST_CURRENT_USER = TestUser()
    yield
    CONFIG.TEST_CURRENT_USER = None


@pytest.fixture(autouse=True)
def forbid_live_network(monkeypatch):
    """Prevent unit tests from initializing clients or issuing network requests."""
    from lagniappe.core.tools.cache import core as cache_core
    from lagniappe.core.tools.database import core as database_core

    monkeypatch.setattr(
        database_core.DataServices,
        "initialize",
        _forbid_live_resource("Datastore or Storage"),
    )
    monkeypatch.setattr(
        cache_core.Cache,
        "initialize",
        _forbid_live_resource("Redis"),
    )
    monkeypatch.setattr(
        cache_core.CacheJSON,
        "initialize",
        _forbid_live_resource("Redis JSON"),
    )

    blocked = _forbid_live_resource("network resources")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)

    try:
        import requests
    except ImportError:
        return
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)


@pytest.fixture
def get_test_entities(request):
    """
    Load test entities from a JSON file matching the test file and function.

    Looks for testing/files/test_entities/{test_file}.json with test function
    names as keys, and creates TestEntity instances via TestEntities enum.

    JSON format (file: 005a_test_project_basic_properties.json):
        {
            "test_project_active": {
                "entities": [
                    ["PROJECT", {"name": "Test Project"}],
                    ["PROJECT", {"name": "Inactive", "active": false}]
                ]
            },
            "test_project_document": {
                "entities": [
                    ["PROJECT", {
                        "name": "Doc Test",
                        "assets": {"document": {"type": "html", "path": "test.html"}},
                        "text_cache": {"document": "Test document content"}
                    }]
                ]
            }
        }

    Auto-added fields (via TestEntityMixin.initialize):
        - hash: random 7-char string if not provided
        - active: True if not provided
        - type: entity_kind (e.g., "project" for PROJECT)
        - requires: from entity.required if not provided
        - created/modified: current UTC datetime if not provided

    Test-specific fields:
        - assets: dict for testing asset-related properties
        - text_cache: dict for testing text_for_cache() output

    Returns:
        Callable returning list[TestEntity]: Initialized test entities

    Example:
        def test_project_document(get_test_entities):
            for project in get_test_entities():
                assert project.text_for_cache("document") == "Test document content"
    """

    def _load_entities():
        filename = Path(request.fspath).stem[5:]
        function_name = request.node.name

        filepath = TEST_ENTITIES_DIR / f"{filename}.json"

        if not filepath.exists():
            raise FileNotFoundError(
                f"Test entities file not found: {filepath}\n"
                f"Create it with test function names as keys containing 'entities' arrays."
            )

        with open(filepath) as f:
            data = json.load(f)

        if function_name not in data:
            raise KeyError(
                f"Test function '{function_name}' not found in {filepath}\n"
                f"Available keys: {list(data.keys())}"
            )

        entities = []
        for entity_type, test_data in data[function_name].get("entities", []):
            test_entity = TestEntities.get(entity_type, test_data)
            entities.append(test_entity)

        return entities

    return _load_entities


@pytest.fixture
def get_permissions_test_data(request):
    """
    Load permission test data from JSON for data-driven permission tests.

    JSON format:
        {
            "test_function_name": {
                "entities": [
                    ["USER", {
                        "name": "Owner User",
                        "hash": "owner01",
                        "page": {...},
                        "owner": true,
                        "expected": [true, true, true, ...]
                    }]
                ],
                "resources": ["SITE", "MODELS", ["PAGE", {"hash": "page01"}], ...]
            }
        }

    Sets on each entity (USER, USER_GROUP, PUBLIC_GROUP, …):
        - is_owner from test_spec["owner"] (users)
        - permissions from test_spec["permissions"] when not owner
        - expected from test_spec["expected"]

    Users with ``groups`` in JSON get permissions only from
    ``UserPermissions.create()`` (combined group grants), not from merging
    pre-seeded ``permissions`` with groups.

    For ``Restrictions`` facet tests, use :class:`testing.utility.mock_restrictions.MockRestrictions`
    to patch ``cache.get_details_by_hash`` (see ``test_009d_user_restrictions``).
    """
    from lagniappe.core.definitions import Action, Resource

    def _load_permissions_test_data():
        filename = Path(request.fspath).stem[5:]
        function_name = request.node.name
        filepath = TEST_ENTITIES_DIR / f"{filename}.json"
        with open(filepath) as f:
            data = json.load(f)

        entities, resources = [], []
        for entity_type, test_data in data[function_name].get("entities", []):
            test_entity = TestEntities.get(entity_type, test_data)
            entities.append(test_entity)

        for resource_spec in data[function_name].get("resources", []):
            resource_name, action_name = resource_spec
            if isinstance(resource_name, str):
                # [Resource, Action] pair
                resource = Resource[resource_name.upper()]
                action = Action[action_name.upper()]
                resources.append((resource, action))
            else:
                # [EntitySpec, Action] pair
                entity_type, entity_spec = resource_name
                entity = TestEntities.get(entity_type, entity_spec)
                action = Action[action_name.upper()]
                resources.append((entity, action))

        return entities, resources

    return _load_permissions_test_data


@pytest.fixture
def get_schema():
    """
    Load a test schema from testing/files/test_schemas/{name}.json.

    Returns:
        Callable[[str], list]: Function that takes schema name and returns parsed schema

    Example:
        def test_form_schema(get_schema):
            schema = get_schema("basic_inputs")
            # schema is a list of field definitions
    """

    def _load_schema(name):
        filepath = TEST_SCHEMAS_DIR / f"{name}.json"
        if not filepath.exists():
            raise FileNotFoundError(f"Test schema file not found: {filepath}")
        with open(filepath) as f:
            return json.load(f)

    return _load_schema


@pytest.fixture
def test_submission_values():
    """
    Test fixture that validates form field submission values.

    Applies submission (form, ai, or import), then verifies:
    - field.value matches expected
    - field.form_value matches expected
    - ColumnMixin: column_value matches (Table fields use ``{"num_rows": n}`` or null)
    - SearchMixin: search values appear in to_cache
    - AIMixin: ai_value appears in to_ai (Table: key is the table's title, value is a list
      of per-row dicts keyed by column titles)
    - FilterMixin: filter_value appears in to_filter_index (Table columns merge by column id)

    Test spec format:
        {
            "form": {"schema": "schema_name", ...},
            "form_submission": {...},  # OR "ai_submission" OR "import_submission"
            "expected": {
                "field_id": {
                    "value": ...,           # or "value_date" for DateMixin fields
                    "form_value": ...,
                    "filter_value": ...,    # if FilterMixin (not needed for DateMixin)
                    "ai_value": ...,        # if AIMixin
                    "search_value": {...}   # if SearchMixin
                }
            }
        }
    """
    from unittest.mock import patch
    from zoneinfo import ZoneInfo
    from lagniappe.core import mixins
    from testing.utility.mock_submission import WebFormSubmission

    # Default test timezone
    DEFAULT_USER_TZ = ZoneInfo("America/Chicago")

    def _check_value(entity, field, field_id, expected):
        """Check field.value - DateMixin verifies UTC timezone, others check exact or form_value."""
        from datetime import datetime, timezone

        if isinstance(field, mixins.DateMixin):
            # DateMixin stores as UTC - just verify timezone
            assert field.value is not None, (
                f"{entity.name}: {field_id}.value should not be None"
            )
            assert field.value.tzinfo == timezone.utc, (
                f"{entity.name}: {field_id}.value should be UTC, "
                f"got {field.value.tzinfo}"
            )
        elif isinstance(field.value, datetime):
            # Non-DateMixin datetime (e.g., TimeInput) - compare via form_value
            assert field.form_value == expected["value"], (
                f"{entity.name}: {field_id}.form_value = {field.form_value!r}, "
                f"expected {expected['value']!r}"
            )
        else:
            assert field.value == expected["value"], (
                f"{entity.name}: {field_id}.value = {field.value!r}, "
                f"expected {expected['value']!r}"
            )

    def _check_column_value(entity, field, field_id, expected, user_tz):
        """Check column_value - uses expected['column_value'] if present, else expected['value']."""
        from datetime import datetime

        column = entity.column(field_id)
        expected_col = expected.get("column_value", expected.get("value"))

        if isinstance(field, mixins.DateMixin):
            # DateMixin column_value should be in user timezone
            assert column.column_value.tzinfo == user_tz, (
                f"{entity.name}: {field_id}.column_value should be in user timezone "
                f"{user_tz}, got {column.column_value.tzinfo}"
            )
        elif isinstance(column.column_value, datetime):
            # Non-DateMixin datetime (e.g., TimeInput) - compare via strftime
            actual = column.column_value.strftime("%H:%M")
            assert actual == expected_col, (
                f"{entity.name}: {field_id}.column_value = "
                f"{actual!r}, expected {expected_col!r}"
            )
        else:
            assert column.column_value == expected_col, (
                f"{entity.name}: {field_id}.column_value = "
                f"{column.column_value!r}, expected {expected_col!r}"
            )

    def _check_form_value(entity, submission, field_id, expected):
        """Check submission.form_value matches expected. Uses .get() since form_value filters out None."""
        actual = submission.form_value.get(field_id)
        assert actual == expected["form_value"], (
            f"{entity.name}: {field_id}.form_value = "
            f"{actual!r}, expected {expected['form_value']!r}"
        )

    def _check_search_value(entity, field, expected, to_cache):
        """Check SearchMixin fields appear in to_cache."""
        if isinstance(field, mixins.SearchMixin):
            for key, value in expected.get("search_value", {}).items():
                assert key in to_cache.get("keys", []), (
                    f"{entity.name}: search key '{key}' not in to_cache keys"
                )
                assert value in to_cache.get("values", []), (
                    f"{entity.name}: search value '{value}' not in to_cache values"
                )
        else:
            assert field.label not in to_cache.get("keys", []), (
                f"{entity.name}: non-SearchMixin field '{field.label}' in to_cache"
            )

    def _check_ai_value(entity, field, expected, to_ai):
        """Check AIMixin fields appear in to_ai."""
        from lagniappe.core.properties.form_table import Table

        if isinstance(field, mixins.AIMixin) and "ai_value" in expected:
            if isinstance(field, Table):
                # Table row values keep human column labels, but the outer field
                # key follows AIMixin like every other submission field.
                table_values = next(iter(expected["ai_value"].values()), None)
                assert to_ai.get(field.ai_key) == table_values, (
                    f"{entity.name}: {field.ai_key} = {to_ai.get(field.ai_key)!r}, "
                    f"expected {table_values!r}"
                )
            else:
                assert to_ai[field.ai_key] == expected["ai_value"], (
                    f"{entity.name}: {field.ai_key} = {to_ai.get(field.ai_key)!r}, "
                    f"expected {expected['ai_value']!r}"
                )

    def _check_filter_value(entity, field, expected, to_filter_index):
        """Check FilterMixin fields appear in to_filter_index."""
        from datetime import datetime
        from lagniappe.core.properties.form_table import Table

        if isinstance(field, mixins.FilterMixin):
            if isinstance(field, Table):
                # Table filter_value is dict of column_id -> list, merged into to_filter_index
                if "filter_value" in expected:
                    for col_id, col_values in expected["filter_value"].items():
                        assert to_filter_index.get(col_id) == col_values, (
                            f"{entity.name}: {col_id} = {to_filter_index.get(col_id)!r}, "
                            f"expected {col_values!r}"
                        )
            elif isinstance(field, mixins.DateMixin) or isinstance(
                field.value, datetime
            ):
                # DateMixin and datetime fields (e.g., TimeInput) return timestamps
                filter_val = to_filter_index[field.filter_key]
                assert isinstance(filter_val, float), (
                    f"{entity.name}: {field.filter_key} should be timestamp, "
                    f"got {type(filter_val).__name__}"
                )
            else:
                filter_val = to_filter_index[field.filter_key]
                assert filter_val == expected["filter_value"], (
                    f"{entity.name}: {field.filter_key} = {filter_val!r}, "
                    f"expected {expected['filter_value']!r}"
                )
        else:
            field_filter_key = getattr(field, "filter_key", field.id)
            assert field_filter_key not in to_filter_index.keys(), (
                f"{entity.name}: non-FilterMixin field '{field_filter_key}' "
                f"in to_filter_index"
            )

    def _test_submission_values(entity, user_tz=None):
        user_tz = user_tz or DEFAULT_USER_TZ

        with patch("lagniappe.core.tools.dates.user_timezone", return_value=user_tz):
            submission = entity.properties.submission

            # Set field_attrs before import (needed for fuzzy_match, separator)
            for field_id, expected in entity.test_spec["expected"].items():
                field = submission.fields[field_id]
                for attr, value in expected.get("field_attrs", {}).items():
                    setattr(field, attr, value)

            # Apply submission based on test_spec
            if "form_submission" in entity.test_spec:
                entity.form_submission(
                    WebFormSubmission(entity.test_spec["form_submission"])
                )
            elif "ai_submission" in entity.test_spec:
                entity.ai_submission(entity.test_spec["ai_submission"])
            elif "import_submission" in entity.test_spec:
                entity.import_submission(
                    entity.test_spec["import_submission"],
                    _ImportProcessStub(entity.test_spec),
                )

            to_cache = entity.to_cache
            to_ai = entity.to_ai()
            to_filter_index = entity.to_filter_index()

            for field_id, expected in entity.test_spec["expected"].items():
                field = submission.fields[field_id]

                _check_value(entity, field, field_id, expected)
                _check_form_value(entity, submission, field_id, expected)

                if isinstance(field, mixins.ColumnMixin):
                    _check_column_value(entity, field, field_id, expected, user_tz)

                _check_search_value(entity, field, expected, to_cache)
                _check_ai_value(entity, field, expected, to_ai)
                _check_filter_value(entity, field, expected, to_filter_index)

    return _test_submission_values


@pytest.fixture
def test_condition_definition():
    """
    Test fixture that validates Condition.set_value() produces correct FilterDefinition.

    Creates a Condition for each field in test_spec["fields"], sets the value,
    and verifies:
    - condition.definition stores the expected entity, field, type, comparator,
      value, and entity-valued flag
    - condition.description matches expected_description
    - condition.details matches expected_details

    Test spec format:
        {
            "entities": [["CATEGORY", {...}]],
            "fields": [
                {
                    "id": "name",
                    "value": ["test"],
                    "comparator": "SUBSTRING",
                    "expected_description": ["hash", "name", "string", "substring", "test"],
                    "expected_details": {
                        "type": "string",
                        "text": "contains",
                        "value": "test",
                        "field_label": "Page Name"
                    }
                }
            ]
        }
    """
    from unittest.mock import patch
    from zoneinfo import ZoneInfo
    from lagniappe.core.entities.condition import Condition

    DEFAULT_USER_TZ = ZoneInfo("America/Chicago")

    def _test_condition_definition(entity, schema=None, entity_map=None):
        # If schema provided, set it on entity.form
        if schema and hasattr(entity, "form") and entity.form:
            entity.form.schema = schema

        # Build entity_map from provided map or empty
        entity_map = entity_map or {}

        with patch(
            "lagniappe.core.tools.dates.user_timezone", return_value=DEFAULT_USER_TZ
        ):
            for field_case in entity.test_spec.get("fields", []):
                condition = Condition()
                condition.entity = entity
                # Set entity_map before field/set_value to avoid database calls
                condition.entity_map.update(entity_map)
                condition.field = field_case["id"]
                condition.set_value(
                    field_case["value"], default_comparator=field_case.get("comparator")
                )

                field_id = field_case["id"]
                comparator = field_case.get("comparator", "")
                expected = field_case["expected_details"]

                # Check description
                expected_desc = field_case["expected_description"]
                actual_desc = condition.description
                definition = condition.definition

                assert definition.entity_hash == expected_desc[0], (
                    f"{field_id} ({comparator}): entity_hash = "
                    f"{definition.entity_hash!r}, expected {expected_desc[0]!r}"
                )
                assert definition.field == expected_desc[1], (
                    f"{field_id} ({comparator}): field = {definition.field!r}, "
                    f"expected {expected_desc[1]!r}"
                )
                assert definition.field_type.value == expected_desc[2], (
                    f"{field_id} ({comparator}): field_type = "
                    f"{definition.field_type.value!r}, expected {expected_desc[2]!r}"
                )
                assert definition.comparator.value == expected_desc[3], (
                    f"{field_id} ({comparator}): comparator = "
                    f"{definition.comparator.value!r}, expected {expected_desc[3]!r}"
                )
                expected_is_entity_valued = (
                    expected_desc[5] if len(expected_desc) > 5 else False
                )
                assert definition.is_entity_valued == expected_is_entity_valued, (
                    f"{field_id} ({comparator}): is_entity_valued = "
                    f"{definition.is_entity_valued!r}, "
                    f"expected {expected_is_entity_valued!r}"
                )

                # For timestamps, the value is dynamic - just check structure matches
                if expected.get("type") == "timestamp":
                    # Check that description prefix matches (entity, field, type, comparator)
                    assert actual_desc[:4] == expected_desc[:4], (
                        f"{field_id} ({comparator}): description prefix = {actual_desc[:4]!r}, "
                        f"expected {expected_desc[:4]!r}"
                    )
                    # Verify value is numeric (or list of numerics for BETWEEN)
                    if len(actual_desc) > 4:
                        val = actual_desc[4]
                        if isinstance(val, list):
                            assert all(isinstance(v, (int, float)) for v in val), (
                                f"{field_id} ({comparator}): BETWEEN values should be numeric"
                            )
                        else:
                            assert isinstance(val, (int, float)), (
                                f"{field_id} ({comparator}): timestamp value should be numeric, "
                                f"got {type(val).__name__}"
                            )
                    if isinstance(definition.value, list):
                        assert all(
                            isinstance(v, (int, float)) for v in definition.value
                        ), (
                            f"{field_id} ({comparator}): definition timestamp "
                            "values should be numeric"
                        )
                    else:
                        assert isinstance(definition.value, (int, float)), (
                            f"{field_id} ({comparator}): definition timestamp "
                            f"value should be numeric, got {type(definition.value).__name__}"
                        )
                else:
                    expected_value = expected_desc[4] if len(expected_desc) > 4 else None
                    assert definition.value == expected_value, (
                        f"{field_id} ({comparator}): value = {definition.value!r}, "
                        f"expected {expected_value!r}"
                    )
                    assert actual_desc == expected_desc, (
                        f"{field_id} ({comparator}): description = {actual_desc!r}, "
                        f"expected {expected_desc!r}"
                    )

                # Check details
                details = condition.details

                assert details["type"] == expected["type"], (
                    f"{field_id} ({comparator}): type = {details['type']!r}, "
                    f"expected {expected['type']!r}"
                )

                if "text" in expected:
                    assert details["text"] == expected["text"], (
                        f"{field_id} ({comparator}): text = {details['text']!r}, "
                        f"expected {expected['text']!r}"
                    )

                if "value" in expected:
                    assert details["value"] == expected["value"], (
                        f"{field_id} ({comparator}): value = {details['value']!r}, "
                        f"expected {expected['value']!r}"
                    )

                if "status" in expected:
                    assert details["status"] == expected["status"], (
                        f"{field_id} ({comparator}): status = {details['status']!r}, "
                        f"expected {expected['status']!r}"
                    )

                if "field_label" in expected:
                    assert details["field"].filter_label == expected["field_label"], (
                        f"{field_id} ({comparator}): field_label = {details['field'].filter_label!r}, "
                        f"expected {expected['field_label']!r}"
                    )

                # Check fields with 'or' key (multiple values - entity-valued or categorical)
                if "or" in expected:
                    assert "or" in details, (
                        f"{field_id} ({comparator}): expected 'or' key in details"
                    )
                    # Check that or list has correct length
                    assert len(details["or"]) == len(expected["or"]), (
                        f"{field_id} ({comparator}): or length = {len(details['or'])}, "
                        f"expected {len(expected['or'])}"
                    )
                    # Check or list values - could be entity dicts or categorical strings
                    if expected["or"] and isinstance(expected["or"][0], dict):
                        # Entity-valued: compare hashes
                        actual_hashes = [d.get("hash") for d in details["or"]]
                        expected_hashes = [d.get("hash") for d in expected["or"]]
                        assert actual_hashes == expected_hashes, (
                            f"{field_id} ({comparator}): or hashes = {actual_hashes!r}, "
                            f"expected {expected_hashes!r}"
                        )
                    else:
                        # Categorical: compare labels directly
                        assert details["or"] == expected["or"], (
                            f"{field_id} ({comparator}): or = {details['or']!r}, "
                            f"expected {expected['or']!r}"
                        )

                # Check entity-valued fields with 'entity' key (single value)
                if "entity" in expected:
                    assert "entity" in details, (
                        f"{field_id} ({comparator}): expected 'entity' key in details"
                    )
                    # entity can be a dict (single) or list (multi) - normalize both
                    actual_entity = details["entity"]
                    expected_entity = expected["entity"]
                    if isinstance(actual_entity, dict):
                        actual_entity = [actual_entity]
                    if isinstance(expected_entity, dict):
                        expected_entity = [expected_entity]
                    actual_hashes = [e.get("hash") for e in actual_entity]
                    expected_hashes = [e.get("hash") for e in expected_entity]
                    assert actual_hashes == expected_hashes, (
                        f"{field_id} ({comparator}): entity hashes = {actual_hashes!r}, "
                        f"expected {expected_hashes!r}"
                    )

    return _test_condition_definition
