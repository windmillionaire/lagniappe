"""Managed deployment waits for its own composite index definitions."""

import json
from types import SimpleNamespace

import pytest

from runner import datastore_indexes as indexes


pytestmark = pytest.mark.tooling

MANIFEST = {"indexes": [{
    "kind": "tasks", "ancestor": True,
    "properties": [{"name": "page"}, {"name": "due", "direction": "desc"}],
}]}
REQUIRED = {
    "kind": "tasks", "ancestor": "ALL_ANCESTORS",
    "properties": [{"name": "page", "direction": "ASCENDING"}, {"name": "due", "direction": "DESCENDING"}],
}


def test_waits_for_exact_index_even_when_other_indexes_are_ready(monkeypatch):
    others = [
        {**REQUIRED, "ancestor": "NONE", "state": "READY"},
        {**REQUIRED, "properties": REQUIRED["properties"][::-1], "state": "READY"},
        {**REQUIRED, "properties": [{"name": "page", "direction": "DESCENDING"}, REQUIRED["properties"][1]], "state": "READY"},
        {**REQUIRED, "kind": "retired", "state": "ERROR"},
    ]
    responses = iter([others, [*others, {**REQUIRED, "state": "CREATING"}], [*others, {**REQUIRED, "state": "READY"}]])
    monkeypatch.setattr(indexes, "run_command", lambda _: SimpleNamespace(stdout=json.dumps(next(responses))))
    waits = []
    monkeypatch.setattr(indexes.time, "sleep", waits.append)

    indexes.wait_for_indexes(MANIFEST, ["--project", "target"])
    assert len(waits) == 2
    assert next(responses, None) is None


@pytest.mark.parametrize("state", ["ERROR", "DELETING", None])
def test_unusable_index_stops_deployment_with_its_definition_and_target(monkeypatch, state):
    row = {**REQUIRED, "state": state}
    monkeypatch.setattr(indexes, "run_command", lambda _: SimpleNamespace(stdout=json.dumps([row])))
    with pytest.raises(RuntimeError, match=r"tasks .*due DESCENDING.*--project target"):
        indexes.wait_for_indexes(MANIFEST, ["--project", "target"])


def test_missing_index_build_times_out_with_retry_instructions(monkeypatch):
    monkeypatch.setattr(indexes, "run_command", lambda _: SimpleNamespace(stdout="[]"))
    monkeypatch.setattr(indexes, "INDEX_BUILD_TIMEOUT", 0)
    with pytest.raises(RuntimeError, match=r"Timed out.*tasks .*retry deployment"):
        indexes.wait_for_indexes(MANIFEST, ["--project", "target"])
