"""Tests for the generated full-suite structural evidence helpers."""

import json

import pytest

from testing.utility import structural_evidence


pytestmark = pytest.mark.tooling


class FakeKey:
    def __init__(self, value):
        self.value = value

    def to_legacy_urlsafe(self):
        return self.value.encode("utf-8")

    def __hash__(self):
        return hash(self.value)


class FakeRow(dict):
    def __init__(self, key, **values):
        super().__init__(values)
        self.key = FakeKey(key)


class FakePrompt:
    prompt_type = "evidence"
    intro = "System text that must not be persisted"
    context_blocks = [
        {"label": "Context", "value": "Private context that must not be persisted"}
    ]
    instruction_blocks = [
        {"content": "Private instruction that must not be persisted"}
    ]
    bytes = [{"bytes": b"private bytes", "mime_type": "text/plain"}]
    files = [{"uri": "gs://test/reference"}]
    tools = ["get_entity"]
    response_schema = {"type": "object"}
    output_format = {"type": "JSON"}
    model_tier = "primary"

    def build(self):
        return "Built prompt that must not be persisted"


def test_canonical_json_bytes_are_stable_and_compact():
    first = structural_evidence.canonical_json_bytes({"b": 2, "a": 1})
    second = structural_evidence.canonical_json_bytes({"a": 1, "b": 2})

    assert first == second == b'{"a":1,"b":2}'


def test_dataset_inventory_summarizes_accumulated_shapes():
    inventory = structural_evidence.dataset_inventory(
        {
            "test-models": [
                FakeRow("project-a", type="project", name="Project A"),
                FakeRow("project-b", type="project", name="Project B"),
            ],
            "test-instances": [
                FakeRow(
                    "task-a",
                    type="task",
                    project=FakeKey("project-a"),
                    page=FakeKey("page-a"),
                    completed=True,
                ),
                FakeRow(
                    "page-a",
                    type="page",
                    model=FakeKey("category-a"),
                    categories=[FakeKey("category-b")],
                ),
            ],
        }
    )

    assert inventory["total_rows"] == 4
    assert inventory["entity_types"] == {"page": 1, "project": 2, "task": 1}
    assert inventory["project_task_distribution"]["total_projects"] == 2
    assert inventory["project_task_distribution"]["projects_without_tasks"] == 1
    assert inventory["project_task_distribution"]["maximum"] == 1
    assert inventory["task_shape"] == {
        "completed": 1,
        "with_page": 1,
        "with_project": 1,
    }


def test_entity_load_summary_retains_callers_and_repeated_signatures():
    load = {
        "caller": "workflow.py:10",
        "operation": "load",
        "primary": ["task:a"],
        "secondary": ["project:b"],
        "related": [],
        "first_batch_keys": 1,
        "related_batch_keys": 0,
        "first_batch_calls": 1,
        "related_batch_calls": 0,
        "db_reads": 1,
    }

    summary = structural_evidence.entity_load_summary([load, load])

    assert summary["calls"] == 2
    assert summary["datastore_requests"] == 2
    assert summary["callers"]["workflow.py:10"]["calls"] == 2
    assert summary["repeated_load_signatures"][0]["occurrences"] == 2


def test_prompt_evidence_fingerprints_without_storing_prompt_text():
    evidence = structural_evidence.prompt_evidence(FakePrompt(), provider_tokens=123)
    serialized = json.dumps(evidence)

    assert evidence["provider_token_count"] == 123
    assert evidence["content_bytes"] > 0
    assert evidence["inline_bytes"] == len(b"private bytes")
    assert evidence["request_sha256"]
    assert "must not be persisted" not in serialized
    assert "private bytes" not in serialized


def test_full_e2e_collection_state_rejects_partial_or_filtered_runs():
    full = structural_evidence.full_e2e_collection_state(
        expected_files={"a.py", "b.py"},
        selected_files={"a.py", "b.py"},
    )
    partial = structural_evidence.full_e2e_collection_state(
        expected_files={"a.py", "b.py"},
        selected_files={"a.py"},
    )
    filtered = structural_evidence.full_e2e_collection_state(
        expected_files={"a.py", "b.py"},
        selected_files={"a.py", "b.py"},
        keyword="cache",
    )

    assert full["full_e2e_run"] is True
    assert partial["full_e2e_run"] is False
    assert filtered["full_e2e_run"] is False


def test_write_evidence_writes_both_formats_and_rejects_speed_fields(tmp_path):
    json_path = tmp_path / "evidence.json"
    markdown_path = tmp_path / "evidence.md"
    record = {
        "generated_at": "2026-07-15T00:00:00+00:00",
        "suite_clean": True,
        "dataset": {"total_rows": 4},
        "workflows": {"cache": {"datastore_requests": 2}},
    }

    structural_evidence.write_evidence(
        record,
        json_path=json_path,
        markdown_path=markdown_path,
    )

    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == structural_evidence.SCHEMA_VERSION
    assert payload["kind"] == "structural-evidence-baseline"
    assert "Timing metrics: deliberately excluded" in markdown_path.read_text()

    with pytest.raises(ValueError, match="Timing metrics are not allowed"):
        structural_evidence.write_evidence(
            {"workflows": {"cache": {"elapsed_seconds": 1}}},
            json_path=json_path,
            markdown_path=markdown_path,
        )
