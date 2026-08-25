"""Unit coverage for privacy-bounded AI generation observability."""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import uuid

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import core as ai_core
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.database import analytics as analytics_database


pytestmark = pytest.mark.unit


def _response(text=None, *, calls=(), usage=None):
    parts = [SimpleNamespace(text=text)] if text is not None else []
    return SimpleNamespace(
        function_calls=list(calls),
        candidates=[
            SimpleNamespace(
                finish_reason=None,
                content=SimpleNamespace(parts=parts),
            )
        ],
        usage_metadata=usage,
    )


def _usage(multiplier=1, traffic="ON_DEMAND"):
    return SimpleNamespace(
        prompt_token_count=10 * multiplier,
        cached_content_token_count=2 * multiplier,
        candidates_token_count=5 * multiplier,
        thoughts_token_count=1 * multiplier,
        total_token_count=16 * multiplier,
        traffic_type=traffic,
    )


def _capture(monkeypatch):
    persisted = []
    pruned = []
    monkeypatch.setattr(observability.CONFIG, "AI_OBSERVABILITY", True, raising=False)
    monkeypatch.setattr(
        observability,
        "_write_summary",
        lambda summary: persisted.append(summary.payload()),
    )
    monkeypatch.setattr(
        observability,
        "prune_old_records",
        lambda: pruned.append(True),
    )
    monkeypatch.setattr(
        ai_core,
        "runtime_ai_settings",
        lambda: {
            "AI_MODEL": "runtime-primary",
            "AI_UTILITY_MODEL": "runtime-utility",
            "AI_IMAGE_MODEL": "runtime-image",
            "AI_LOCATION": "us-central1",
        },
    )
    return persisted, pruned


# @matrix observability : cache deferred-context privacy provider-calls tokens tools validation
@pytest.mark.unit
def test_generation_summary_aggregates_visible_calls_and_redacts_payload(
    monkeypatch,
):
    persisted, pruned = _capture(monkeypatch)
    sentinel = "PRIVATE-SENTINEL-DO-NOT-STORE"
    function_call = SimpleNamespace(
        name="get_file",
        args={"id": sentinel},
    )
    unknown_call = SimpleNamespace(name=sentinel, args={"private": sentinel})
    responses = iter(
        (
            _response(calls=[function_call, unknown_call], usage=_usage()),
            _response(calls=[function_call, unknown_call], usage=_usage()),
            _response(text="intermediate", usage=_usage()),
            _response(
                text=json.dumps({"summary": sentinel}),
                usage=_usage(),
            ),
        )
    )

    class Models:
        def generate_content(self, *, model, contents, config):
            return next(responses)

    monkeypatch.setitem(
        ai_functions.HANDLERS,
        "get_file",
        lambda args, user: (
            {"content": sentinel},
            [{"uri": f"gs://private/{sentinel}", "mime_type": "text/plain"}],
        ),
    )
    prompt = Prompt(sentinel, user=SimpleNamespace(), type="ask report")
    prompt.enable_tools("get_file")
    prompt.set_model_tier("utility")
    prompt.set_service_tier("priority")
    prompt.set_output_format("JSON")
    prompt.set_response_schema(
        {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
        }
    )
    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=Models())

    with observability.ai_execution_context(
        job_type="report-ask",
        attempt=3,
        contract_version=1,
    ):
        result = generator.generate_content(
            prompt,
            validator=lambda value: {**value, "validated": True},
        )

    assert result == {"summary": sentinel, "validated": True}
    assert len(persisted) == 1
    assert pruned == [True]
    summary = persisted[0]
    assert set(summary) == set(observability.GenerationSummaryV1.__dataclass_fields__)
    assert sentinel not in json.dumps(summary, default=str)
    uuid.UUID(summary["correlation_id"])
    assert summary["workflow"] == "ask"
    assert summary["stage"] == "answer"
    assert summary["prompt_contract_id"] == "ask-report"
    assert summary["resolved_model"] == "runtime-utility"
    assert summary["location"] == "us-central1"
    assert summary["model_tier"] == "utility"
    assert summary["service_tier"] == "priority"
    assert summary["deferred_job_type"] == "report-ask"
    assert summary["deferred_job_attempt"] == 3
    assert summary["deferred_contract_version"] == 1
    assert summary["provider_requests"] == 4
    assert summary["provider_responses"] == 4
    assert summary["structured_final_used"] is True
    assert summary["tool_rounds"] == 2
    assert summary["calls_per_round"] == [2, 2]
    assert summary["tool_calls"] == 4
    assert summary["tool_names"] == ["get_file", "get_file"]
    assert summary["exact_call_cache_hits"] == 2
    assert summary["tool_result_chars"] > 0
    assert summary["original_file_count"] == 2
    assert summary["prompt_tokens"] == 40
    assert summary["cached_tokens"] == 8
    assert summary["output_tokens"] == 20
    assert summary["thought_tokens"] == 4
    assert summary["total_tokens"] == 64
    assert summary["traffic_types"] == ["on_demand"]
    assert summary["provider_result_chars"] > 0
    assert summary["validated_result_chars"] > summary["provider_result_chars"]
    assert summary["outcome"] == "local_repair"
    assert summary["success"] is True


# @matrix observability : empty-response error-normalization quota
@pytest.mark.unit
def test_generation_summary_records_empty_retry_and_bounded_quota_error(monkeypatch):
    persisted, _ = _capture(monkeypatch)

    class EmptyThenText:
        def __init__(self):
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            if self.calls == 1:
                return _response()
            return _response(text="Recovered")

    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=EmptyThenText())
    prompt = Prompt("private", type="document text").set_output_format("TEXT")
    assert generator.generate_content(prompt) == "Recovered"
    assert persisted[-1]["empty_response_retries"] == 1
    assert persisted[-1]["provider_requests"] == 2
    assert persisted[-1]["service_tier"] == "standard"

    class UnknownProviderExplosion(Exception):
        code = 429
        status = "RESOURCE_EXHAUSTED"

    class QuotaModels:
        def generate_content(self, *, model, contents, config):
            raise UnknownProviderExplosion("private provider message")

    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=QuotaModels())
    with pytest.raises(exceptions.AIQuotaError):
        generator.generate_content(prompt)

    quota = persisted[-1]
    assert quota["surfaced_quota_stages"] == ["initial"]
    assert quota["terminal_error_category"] == "quota"
    assert quota["terminal_error_class"] == "quota"
    assert "private provider message" not in json.dumps(quota, default=str)

    resolution_error = RuntimeError("private model resolution failure")
    monkeypatch.setattr(
        ai_core,
        "runtime_ai_settings",
        lambda: (_ for _ in ()).throw(resolution_error),
    )
    with pytest.raises(RuntimeError) as caught:
        generator.generate_content(prompt)
    assert caught.value is resolution_error
    resolution = persisted[-1]
    assert resolution["resolved_model"] == "unknown"
    assert resolution["provider_requests"] == 0
    assert "private model resolution failure" not in json.dumps(
        resolution,
        default=str,
    )


# @matrix observability : correlation in-flight privacy provider-stage
def test_deferred_generation_overwrites_correlated_live_snapshots(monkeypatch):
    persisted, pruned = _capture(monkeypatch)

    class Models:
        def generate_content(self, *, model, contents, config):
            return _response(text="PRIVATE-GENERATED-RESULT", usage=_usage())

    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=Models())
    prompt = Prompt(
        "PRIVATE-PROMPT-CONTENT",
        type="ask report",
    ).set_output_format("TEXT")

    with observability.ai_execution_context(
        job_type="report-ask",
        attempt=2,
        contract_version=2,
        telemetry_id="opaque-telemetry-id",
    ):
        assert generator.generate_content(prompt) == "PRIVATE-GENERATED-RESULT"

    assert len(persisted) >= 4
    assert len({record["correlation_id"] for record in persisted}) == 1
    assert all(record["telemetry_id"] == "opaque-telemetry-id" for record in persisted)
    assert persisted[0]["state"] == "running"
    assert any(
        record["active_provider_stage"] == "initial" for record in persisted[:-1]
    )
    assert persisted[-1]["state"] == "complete"
    assert persisted[-1]["active_provider_stage"] == "complete"
    assert persisted[-1]["success"] is True
    assert pruned == [True]
    assert "PRIVATE-PROMPT-CONTENT" not in json.dumps(persisted, default=str)
    assert "PRIVATE-GENERATED-RESULT" not in json.dumps(persisted, default=str)


# @matrix observability : correlation model-repair nested-generation review-fallback
@pytest.mark.unit
def test_nested_model_repair_gets_its_own_summary(monkeypatch):
    persisted, _ = _capture(monkeypatch)
    responses = iter(
        (
            _response(text='{"value":"invalid"}', usage=_usage()),
            _response(text='{"value":"repaired"}', usage=_usage()),
        )
    )

    class Models:
        def generate_content(self, *, model, contents, config):
            return next(responses)

    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=Models())
    source_prompt = Prompt("private", type="organize report").set_output_format("JSON")
    repair_prompt = Prompt(
        "private repair",
        type="organize report repair",
    ).set_output_format("JSON")

    def repair(_value):
        observability.mark_outcome("model_repair")
        return generator.generate_content(repair_prompt)

    assert generator.generate_content(source_prompt, validator=repair) == {
        "value": "repaired"
    }
    assert len(persisted) == 2
    nested, initiating = persisted
    assert nested["stage"] == "model-repair"
    assert nested["outcome"] == "not_validated"
    assert initiating["stage"] == "planning"
    assert initiating["outcome"] == "model_repair"
    assert nested["correlation_id"] != initiating["correlation_id"]

    class FallbackModels:
        def generate_content(self, *, model, contents, config):
            return _response(text='{"value":"review"}', usage=_usage())

    fallback_generator = ai_core.GenAI()
    fallback_generator._client = SimpleNamespace(models=FallbackModels())

    def review_fallback(value):
        observability.mark_outcome("model_repair")
        observability.mark_outcome("review_fallback")
        return value

    assert fallback_generator.generate_content(
        source_prompt,
        validator=review_fallback,
    ) == {"value": "review"}
    assert persisted[-1]["outcome"] == "review_fallback"


# @matrix observability : disabled exception-transparency persistence-failure pruning-failure
@pytest.mark.unit
def test_observability_failures_never_change_generation_result_or_error(monkeypatch):
    monkeypatch.setattr(
        ai_core,
        "runtime_ai_settings",
        lambda: {
            "AI_MODEL": "model",
            "AI_UTILITY_MODEL": "utility",
            "AI_LOCATION": "global",
        },
    )
    prompt = Prompt("private", type="document text").set_output_format("TEXT")

    class SuccessModels:
        def generate_content(self, *, model, contents, config):
            return _response(text="Success")

    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=SuccessModels())
    monkeypatch.setattr(observability.CONFIG, "AI_OBSERVABILITY", False, raising=False)
    monkeypatch.setattr(
        observability,
        "_write_summary",
        lambda summary: pytest.fail("disabled collection wrote a record"),
    )
    assert generator.generate_content(prompt) == "Success"

    monkeypatch.setattr(observability.CONFIG, "AI_OBSERVABILITY", True, raising=False)
    monkeypatch.setattr(
        observability,
        "_write_summary",
        lambda summary: (_ for _ in ()).throw(RuntimeError("write failed")),
    )
    assert generator.generate_content(prompt) == "Success"

    monkeypatch.setattr(observability, "_write_summary", lambda summary: None)
    monkeypatch.setattr(
        observability,
        "prune_old_records",
        lambda: (_ for _ in ()).throw(RuntimeError("prune failed")),
    )
    assert generator.generate_content(prompt) == "Success"

    original = RuntimeError("original provider failure")

    class ErrorModels:
        def generate_content(self, *, model, contents, config):
            raise original

    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=ErrorModels())
    with pytest.raises(RuntimeError) as caught:
        generator.generate_content(prompt)
    assert caught.value is original


class _Entity(dict):
    def __init__(self, *, key, exclude_from_indexes=()):
        super().__init__()
        self.key = key
        self.exclude_from_indexes = tuple(exclude_from_indexes)


class _Key:
    def __init__(self, kind, name):
        self.kind = kind
        self.name = name


class _Query:
    def __init__(self, records):
        self.records = records
        self.filters = []
        self.order = []
        self.keys_only_called = False
        self.limit = None

    def add_filter(self, *, filter):
        self.filters.append(filter)

    def keys_only(self):
        self.keys_only_called = True

    def fetch(self, *, limit):
        self.limit = limit
        return self.records[:limit]


# @matrix datastore : index-exclusions retention-bound uuid-key
@pytest.mark.unit
def test_summary_persistence_uses_uuid_key_and_bounded_pruning(monkeypatch):
    old_records = [SimpleNamespace(key=f"old-{index}") for index in range(700)]
    query = _Query(old_records)

    class Datastore:
        def __init__(self):
            self.put_record = None
            self.deleted = []

        def key(self, kind, name):
            return _Key(kind, name)

        def entity(self, *, key, exclude_from_indexes=()):
            return _Entity(key=key, exclude_from_indexes=exclude_from_indexes)

        def put(self, record):
            self.put_record = record

        def query(self, *, kind):
            assert kind == analytics_database.KINDS.ai_observability.value
            return query

        def delete_multi(self, keys):
            self.deleted.extend(keys)

    datastore = Datastore()
    monkeypatch.setattr(
        analytics_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    identifier = str(uuid.uuid4())
    summary = observability.GenerationSummaryV1(
        correlation_id=identifier,
        created=datetime.now(timezone.utc),
        workflow="ask",
        stage="answer",
        prompt_contract_id="ask-report",
        prompt_contract_version=1,
    )

    record = observability._write_summary(summary)
    assert record.key.name == identifier
    assert record["correlation_id"] == identifier
    assert record.exclude_from_indexes == observability.EXCLUDE_FROM_INDEXES

    now = datetime.now(timezone.utc)
    assert observability.prune_old_records(now=now, limit=900) == 500
    assert len(datastore.deleted) == 500
    assert query.keys_only_called is True
    assert query.limit == 500
    assert query.filters[0].property_name == "created"
    assert query.filters[0].operator == "<"
    assert query.filters[0].value == now - timedelta(days=30)


# @matrix analytics : groups outcomes query-limit
# @pair observability:aggregation
@pytest.mark.unit
def test_ai_observability_dashboard_aggregation():
    records = [
        {
            "workflow": "ask",
            "stage": "answer",
            "prompt_contract_id": "ask-report",
            "prompt_contract_version": 1,
            "resolved_model": "model-a",
            "model_tier": "primary",
            "service_tier": "standard",
            "success": True,
            "provider_requests": 3,
            "tool_rounds": 2,
            "tool_calls": 3,
            "total_tokens": 120,
            "surfaced_quota_stages": [],
            "exact_call_cache_hits": 1,
            "duration_ms": 100,
            "provider_result_chars": 20,
            "validated_result_chars": 25,
            "original_file_count": 2,
            "outcome": "model_repair",
            "tool_names": ["get_file", "get_file", "search_entities"],
        },
        {
            "workflow": "ask",
            "stage": "answer",
            "prompt_contract_id": "ask-report",
            "prompt_contract_version": 1,
            "resolved_model": "model-a",
            "model_tier": "primary",
            "service_tier": "priority",
            "success": False,
            "provider_requests": 1,
            "tool_rounds": 0,
            "tool_calls": 0,
            "total_tokens": 30,
            "surfaced_quota_stages": ["initial"],
            "duration_ms": 300,
            "outcome": "validation_failed",
        },
    ]

    dashboard = observability.aggregate_records(records, query_limit=2)
    assert dashboard["generation_count"] == 2
    assert dashboard["success_rate"] == 50.0
    assert dashboard["provider_requests"] == 4
    assert dashboard["requests_per_generation"] == 2.0
    assert dashboard["calls_per_round"] == 1.5
    assert dashboard["sequential_round_rate"] == 100.0
    assert dashboard["token_total"] == 150
    assert dashboard["quota_errors"] == 1
    assert dashboard["cache_hits"] == 1
    assert dashboard["average_duration_ms"] == 200
    assert dashboard["provider_result_chars"] == 20
    assert dashboard["validated_result_chars"] == 25
    assert dashboard["original_file_count"] == 2
    assert dashboard["limited"] is True
    assert dashboard["tools"] == [
        {"name": "get_file", "count": 2},
        {"name": "search_entities", "count": 1},
    ]
    workflow = next(
        group for group in dashboard["groups"] if group["field"] == "workflow"
    )
    assert {group["field"] for group in dashboard["groups"]} == {
        "workflow",
        "stage",
        "resolved_model",
        "model_tier",
        "service_tier",
        "prompt_contract",
    }
    assert workflow["rows"][0]["value"] == "ask"
    assert workflow["rows"][0]["count"] == 2
    assert workflow["rows"][0]["outcomes"] == [
        {"name": "Model Repair", "count": 1},
        {"name": "Validation Failed", "count": 1},
    ]


# @matrix ai-observability : job-correlation privacy
def test_operation_diagnostic_payload_is_correlated_and_privacy_bounded():
    created = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
    operation = {
        "key": "job-key",
        "telemetry_id": "telemetry-match",
        "state": "complete",
    }
    records = [
        {
            "telemetry_id": "telemetry-match",
            "correlation_id": "correlation",
            "created": created,
            "workflow": "ask",
            "stage": "answer",
            "prompt_contract_id": "ask-report",
            "prompt_contract_version": 1,
            "private_prompt": "must not leave core",
        },
        {
            "telemetry_id": "telemetry-other",
            "workflow": "organize",
            "private_prompt": "unrelated",
        },
    ]

    payload = observability.operation_diagnostic_payload(
        operation,
        records,
        query_limit=2,
    )

    assert payload["job_id"] == "job-key"
    assert payload["telemetry_id"] == "telemetry-match"
    assert payload["ai_records_may_be_truncated"] is True
    assert payload["ai_generations"] == [
        {
            "correlation_id": "correlation",
            "created": created.isoformat(),
            "workflow": "ask",
            "stage": "answer",
            "prompt_contract_id": "ask-report",
            "prompt_contract_version": 1,
            "telemetry_id": "telemetry-match",
        }
    ]
    assert "private_prompt" not in str(payload)
