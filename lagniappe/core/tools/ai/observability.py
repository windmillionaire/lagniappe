"""Privacy-bounded observability for application-visible text generations."""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time
import uuid

from lagniappe import CONFIG
from lagniappe.core.tools.database import analytics as analytics_database


LOGGER = logging.getLogger(__name__)
TELEMETRY_SCHEMA_VERSION = 1
RETENTION_DAYS = 30
PRUNE_LIMIT = 500
QUERY_LIMIT = 1000

KNOWN_TRAFFIC_TYPES = {
    "ON_DEMAND": "on_demand",
    "PROVISIONED_THROUGHPUT": "provisioned_throughput",
    "PAYGO": "paygo",
}
KNOWN_OUTCOMES = {
    "not_validated",
    "validated",
    "local_repair",
    "model_repair",
    "review_fallback",
    "validation_failed",
}
OUTCOME_PRIORITY = {
    "not_validated": 0,
    "validated": 1,
    "local_repair": 2,
    "model_repair": 3,
    "review_fallback": 4,
    "validation_failed": 5,
}
KNOWN_PROVIDER_STAGES = {"initial", "tool", "structured_final"}
KNOWN_TOOL_NAMES = {
    "search_entities",
    "get_entity",
    "get_file",
    "get_category_pages",
    "get_category_forms",
    "get_page_details",
    "get_page_file_list",
    "get_page_tasks",
    "get_task_history",
    "get_category_details",
    "get_guidelines",
    "get_schema",
    "get_form_instances",
    "list_workspace_resources",
    "get_filter_schema",
    "query_workspace_filter",
}

# Only timestamps and bounded, low-cardinality dashboard dimensions remain indexed.
EXCLUDE_FROM_INDEXES = (
    "correlation_id",
    "telemetry_id",
    "deferred_job_attempt",
    "provider_requests",
    "provider_responses",
    "empty_response_retries",
    "surfaced_quota_stages",
    "tool_rounds",
    "calls_per_round",
    "tool_calls",
    "tool_names",
    "exact_call_cache_hits",
    "tool_result_chars",
    "original_file_count",
    "prompt_tokens",
    "cached_tokens",
    "output_tokens",
    "thought_tokens",
    "total_tokens",
    "traffic_types",
    "provider_result_chars",
    "validated_result_chars",
    "duration_ms",
)


# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_supplies_bounded_ai_observability_context_during_prepare
# @matrix observability : attempt contract-version job-type no-job-key
@dataclass(frozen=True)
class AIExecutionContext:
    """Allowlisted deferred-job metadata available during one preparation pass."""

    job_type: str | None = None
    attempt: int | None = None
    contract_version: int | None = None
    telemetry_id: str | None = field(default=None, repr=False, compare=False)
    execution_control: object | None = field(default=None, repr=False, compare=False)


_EXECUTION_CONTEXT = ContextVar("ai_execution_context", default=AIExecutionContext())
_CURRENT_OBSERVER = ContextVar("ai_generation_observer", default=None)


# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_supplies_bounded_ai_observability_context_during_prepare
# @pair deferred-jobs:preparation-context
@contextmanager
def ai_execution_context(
    *,
    job_type=None,
    attempt=None,
    contract_version=None,
    telemetry_id=None,
    execution_control=None,
):
    """Supply controlled deferred metadata without exposing a durable job key."""
    value = getattr(job_type, "value", job_type)
    token = _EXECUTION_CONTEXT.set(
        AIExecutionContext(
            job_type=str(value) if value else None,
            attempt=max(int(attempt or 0), 0) or None,
            contract_version=max(int(contract_version or 0), 0) or None,
            telemetry_id=str(telemetry_id) if telemetry_id else None,
            execution_control=execution_control,
        )
    )
    try:
        yield
    finally:
        _EXECUTION_CONTEXT.reset(token)


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::ai_execution_context
# @reason context lookup is exercised through deferred provider/tool boundaries
def current_execution_control():
    """Return the ephemeral deferred execution controller, when present."""
    return _EXECUTION_CONTEXT.get().execution_control


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_summary_persistence_uses_uuid_key_and_bounded_pruning
# @tests tests_unit/test_015c_ai_observability.py::test_generation_summary_aggregates_visible_calls_and_redacts_payload
# @matrix datastore : index-exclusions uuid-key
# @pair observability:privacy
@dataclass
class GenerationSummaryV1:
    """Exact allowlist for the version-1 persisted summary contract."""

    correlation_id: str
    created: datetime
    workflow: str
    stage: str
    prompt_contract_id: str
    prompt_contract_version: int
    updated: datetime | None = None
    telemetry_schema_version: int = TELEMETRY_SCHEMA_VERSION
    deferred_job_type: str | None = None
    deferred_job_attempt: int | None = None
    deferred_contract_version: int | None = None
    telemetry_id: str | None = None
    state: str = "running"
    active_provider_stage: str = "not_started"
    resolved_model: str = "unknown"
    location: str = "unknown"
    model_tier: str = "primary"
    service_tier: str = "standard"
    provider_requests: int = 0
    provider_responses: int = 0
    empty_response_retries: int = 0
    structured_final_used: bool = False
    surfaced_quota_stages: list[str] = field(default_factory=list)
    terminal_error_category: str = "none"
    terminal_error_class: str = "none"
    success: bool = False
    tool_rounds: int = 0
    calls_per_round: list[int] = field(default_factory=list)
    tool_calls: int = 0
    tool_names: list[str] = field(default_factory=list)
    exact_call_cache_hits: int = 0
    tool_result_chars: int = 0
    original_file_count: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    total_tokens: int = 0
    traffic_types: list[str] = field(default_factory=list)
    provider_result_chars: int = 0
    validated_result_chars: int = 0
    duration_ms: int = 0
    outcome: str = "not_validated"

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationSummaryV1
    # @reason dataclass serialization is exercised through the typed summary contract
    def payload(self):
        """Return only fields declared by this typed contract."""
        return asdict(self)


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::operation_diagnostic_payload
# @reason the public correlation helper owns the typed serialization allowlist
def diagnostic_record(record):
    """Serialize only fields declared by the persisted summary contract."""
    result = {}
    for name in GenerationSummaryV1.__dataclass_fields__:
        value = record.get(name)
        if value is None:
            continue
        if isinstance(value, datetime):
            value = value.isoformat()
        result[name] = value
    return result


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_operation_diagnostic_payload_is_correlated_and_privacy_bounded
# @matrix ai-observability : job-correlation privacy
def operation_diagnostic_payload(operation, records, *, query_limit=QUERY_LIMIT):
    """Build a transferable, privacy-bounded job/provider snapshot."""
    telemetry_id = operation.get("telemetry_id")
    matching = [
        diagnostic_record(record)
        for record in records
        if telemetry_id and record.get("telemetry_id") == telemetry_id
    ]
    return {
        "schema_version": 1,
        "job_id": operation.get("key"),
        "telemetry_id": telemetry_id,
        "operation": operation,
        "ai_generations": matching,
        "ai_record_query_limit": query_limit,
        "ai_records_may_be_truncated": len(records) >= query_limit,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason enablement is exercised through observer construction and disabled-mode tests
def enabled(config=CONFIG):
    return bool(getattr(config, "AI_OBSERVABILITY", False))


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason bounded dimensions are exercised through persisted generation summaries
def _bounded_contract(value, fallback="unknown"):
    value = str(value or "").strip().lower().replace("_", "-")
    if not value or len(value) > 80:
        return fallback
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in value
    ):
        return fallback
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason aggregate-only result sizing is exercised through generation summaries
def _size(value):
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, separators=(",", ":"), default=str))
    except Exception:
        return 0


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason ephemeral validation comparison is exercised through local-repair outcomes
def _fingerprint(value):
    try:
        serialized = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        )
    except Exception:
        serialized = f"<{type(value).__name__}>"
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason error normalization is exercised through bounded terminal summaries
def _error_class(error):
    name = type(error).__name__.lower()
    if "quota" in name:
        return "quota"
    if "timeout" in name or "deadline" in name:
        return "timeout"
    if "connect" in name or "connection" in name:
        return "connection"
    if name in {"clienterror", "servererror"}:
        return "provider"
    if name in {"aiexception", "validationerror"}:
        return "application"
    return "other"


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason error normalization is exercised through bounded terminal summaries
def _error_category(error):
    if _error_class(error) == "quota":
        return "quota"
    message = str(error or "").lower()
    if message == "model returned no text content.":
        return "empty_response"
    if "blocked" in message or "safety" in message:
        return "safety"
    context = getattr(error, "context", None) or {}
    if isinstance(context, dict) and context.get("ai_tool_loop"):
        return "tool"
    if _error_class(error) in {"provider", "timeout", "connection"}:
        return "provider"
    if _error_class(error) == "application":
        return "validation"
    return "internal"


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_generation_summary_aggregates_visible_calls_and_redacts_payload
# @tests tests_unit/test_015c_ai_observability.py::test_generation_summary_records_empty_retry_and_bounded_quota_error
# @tests tests_unit/test_015c_ai_observability.py::test_nested_model_repair_gets_its_own_summary
# @tests tests_unit/test_015c_ai_observability.py::test_observability_failures_never_change_generation_result_or_error
# @tests tests_unit/test_015c_ai_observability.py::test_deferred_generation_overwrites_correlated_live_snapshots
# @matrix observability : cache correlation deferred-context disabled empty-response error-normalization exception-transparency in-flight nested-generation persistence-failure privacy provider-calls provider-stage pruning-failure quota review-fallback tokens tools validation
class GenerationObserver:
    """Mutable in-memory reducer for one public ``generate_content`` call."""

    def __init__(self, prompt):
        self.active = enabled()
        self.started = time.monotonic()
        self.validation_started = False
        self.validation_fingerprint = None
        correlation_id = str(uuid.uuid4())
        contract = getattr(prompt, "observability_contract", None) or {}
        execution = _EXECUTION_CONTEXT.get()
        created = datetime.now(timezone.utc)
        self.live = bool(self.active and execution.telemetry_id)
        self.summary = GenerationSummaryV1(
            correlation_id=correlation_id,
            created=created,
            updated=created,
            workflow=_bounded_contract(contract.get("workflow")),
            stage=_bounded_contract(contract.get("stage")),
            prompt_contract_id=_bounded_contract(contract.get("id")),
            prompt_contract_version=max(int(contract.get("version") or 1), 1),
            deferred_job_type=_bounded_contract(execution.job_type, None),
            deferred_job_attempt=execution.attempt,
            deferred_contract_version=execution.contract_version,
            telemetry_id=(
                str(execution.telemetry_id) if execution.telemetry_id else None
            ),
            model_tier=(
                getattr(prompt, "model_tier", None)
                if getattr(prompt, "model_tier", None) in {"primary", "utility"}
                else "primary"
            ),
            service_tier=(
                getattr(prompt, "service_tier", None)
                if getattr(prompt, "service_tier", None)
                in {"standard", "priority", "flex"}
                else "standard"
            ),
            original_file_count=(
                len(getattr(prompt, "files", ()) or ())
                + len(getattr(prompt, "bytes", ()) or ())
            ),
        )

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason runtime routing is exercised through the public generation boundary
    def resolution(self, *, model, location):
        if not self.active:
            return
        self.summary.resolved_model = _bounded_contract(model)
        self.summary.location = _bounded_contract(location)
        self._persist_live()

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason context lifecycle is exercised through nested public generations
    def install(self):
        return _CURRENT_OBSERVER.set(self)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason context lifecycle is exercised through nested public generations
    @staticmethod
    def reset(token):
        _CURRENT_OBSERVER.reset(token)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def request(self, stage):
        if self.active:
            self.summary.provider_requests += 1
            self.summary.active_provider_stage = (
                stage if stage in KNOWN_PROVIDER_STAGES else "initial"
            )
            if stage == "structured_final":
                self.summary.structured_final_used = True
            self._persist_live()

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def response(self, response):
        if not self.active:
            return
        self.summary.provider_responses += 1
        self.summary.active_provider_stage = "between_requests"
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            self._persist_live()
            return
        for field_name, provider_name in (
            ("prompt_tokens", "prompt_token_count"),
            ("cached_tokens", "cached_content_token_count"),
            ("output_tokens", "candidates_token_count"),
            ("thought_tokens", "thoughts_token_count"),
            ("total_tokens", "total_token_count"),
        ):
            value = getattr(usage, provider_name, 0) or 0
            setattr(
                self.summary, field_name, getattr(self.summary, field_name) + int(value)
            )
        traffic = str(getattr(usage, "traffic_type", "") or "")
        traffic = traffic.rsplit(".", 1)[-1].upper()
        normalized = KNOWN_TRAFFIC_TYPES.get(traffic, "other")
        if normalized not in self.summary.traffic_types:
            self.summary.traffic_types.append(normalized)
        self._persist_live()

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def provider_error(self, error, stage, *, quota=False):
        if not self.active or not quota:
            return
        stage = stage if stage in KNOWN_PROVIDER_STAGES else "initial"
        if stage not in self.summary.surfaced_quota_stages:
            self.summary.surfaced_quota_stages.append(stage)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def empty_retry(self):
        if self.active:
            self.summary.empty_response_retries += 1

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def tool_round(self, function_calls, trace):
        if not self.active:
            return
        function_calls = list(function_calls or ())
        calls = list(trace or ())
        self.summary.tool_rounds += 1
        self.summary.calls_per_round.append(len(function_calls))
        self.summary.tool_calls += len(function_calls)
        for call in function_calls:
            name = getattr(call, "name", None)
            if name in KNOWN_TOOL_NAMES:
                self.summary.tool_names.append(name)
        for call in calls:
            if isinstance(call, dict):
                self.summary.exact_call_cache_hits += int(bool(call.get("cached")))
                self.summary.tool_result_chars += max(
                    int(call.get("result_chars") or 0), 0
                )
                self.summary.original_file_count += max(
                    int(call.get("file_parts") or 0), 0
                )
        self.summary.tool_names.sort()
        self._persist_live()

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def provider_result(self, value):
        if self.active:
            self.summary.provider_result_chars = _size(value)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def validated_result(self, after):
        if not self.active:
            return
        self.summary.validated_result_chars = _size(after)
        changed = self.validation_fingerprint != _fingerprint(after)
        self.outcome("local_repair" if changed else "validated")

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def begin_validation(self, value):
        if self.active:
            self.validation_started = True
            self.validation_fingerprint = _fingerprint(value)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def outcome(self, value):
        if not self.active or value not in KNOWN_OUTCOMES:
            return
        current = self.summary.outcome
        if OUTCOME_PRIORITY[value] >= OUTCOME_PRIORITY[current]:
            self.summary.outcome = value

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason reducer method is exercised through the public generation boundary
    def finish(self, *, error=None):
        if not self.active:
            return
        self.summary.duration_ms = max(int((time.monotonic() - self.started) * 1000), 0)
        self.summary.updated = datetime.now(timezone.utc)
        self.summary.state = "complete"
        self.summary.active_provider_stage = "complete"
        self.summary.success = error is None
        if error is not None:
            self.summary.terminal_error_category = _error_category(error)
            self.summary.terminal_error_class = _error_class(error)
            if self.validation_started and self.summary.outcome not in {
                "model_repair",
                "review_fallback",
            }:
                self.outcome("validation_failed")

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
    # @reason best-effort persistence is exercised through public generation results
    def _persist_live(self):
        if not self.live:
            return
        self.summary.updated = datetime.now(timezone.utc)
        self.summary.duration_ms = max(
            int((time.monotonic() - self.started) * 1000),
            0,
        )
        self.persist(prune=False)

    def persist(self, *, prune=True):
        if not self.active:
            return
        try:
            _write_summary(self.summary)
        except Exception:
            LOGGER.warning("Unable to persist AI observability summary.", exc_info=True)
            return
        if prune:
            try:
                prune_old_records()
            except Exception:
                LOGGER.warning(
                    "Unable to prune AI observability summaries.", exc_info=True
                )


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::GenerationObserver
# @reason context lookup is exercised through provider and nested generation paths
def current_observer():
    return _CURRENT_OBSERVER.get()


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_nested_model_repair_gets_its_own_summary
# @matrix observability : model-repair review-fallback
def mark_outcome(value):
    observer = current_observer()
    if observer is not None:
        observer.outcome(value)


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_summary_persistence_uses_uuid_key_and_bounded_pruning
# @matrix datastore : index-exclusions uuid-key
def _write_summary(summary):
    return analytics_database.create_ai_observability(
        summary.correlation_id,
        summary.payload(),
        exclude_from_indexes=EXCLUDE_FROM_INDEXES,
    )


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_summary_persistence_uses_uuid_key_and_bounded_pruning
# @pair datastore:retention-bound
def prune_old_records(*, now=None, limit=PRUNE_LIMIT):
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
    return analytics_database.delete_ai_observability(
        before=cutoff,
        batch_size=min(int(limit), PRUNE_LIMIT),
        once=True,
    )


# @testable true
# @tests tests_unit/test_015c_ai_observability.py::test_ai_observability_dashboard_aggregation
# @matrix analytics : groups outcomes query-limit
# @pair observability:aggregation
def aggregate_records(records, *, query_limit=QUERY_LIMIT):
    """Build the owner dashboard view model from already-windowed summaries."""
    records = list(records)
    count = len(records)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::aggregate_records
    # @reason local aggregation helper is exercised through the dashboard contract
    def total(name):
        return sum(max(int(record.get(name) or 0), 0) for record in records)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/observability.py::aggregate_records
    # @reason local aggregation helper is exercised through the dashboard contract
    def percent(numerator, denominator):
        return round((100 * numerator / denominator), 1) if denominator else 0.0

    successes = sum(bool(record.get("success")) for record in records)
    tool_generations = sum(
        int(record.get("tool_rounds") or 0) > 0 for record in records
    )
    sequential = sum(int(record.get("tool_rounds") or 0) > 1 for record in records)
    tool_rounds = total("tool_rounds")
    tool_calls = total("tool_calls")
    provider_requests = total("provider_requests")
    quota_errors = sum(bool(record.get("surfaced_quota_stages")) for record in records)

    group_specs = (
        ("workflow", "Workflow"),
        ("stage", "Stage"),
        ("resolved_model", "Resolved Model"),
        ("model_tier", "Model Tier"),
        ("service_tier", "Service Tier"),
        ("prompt_contract", "Contract Version"),
    )
    grouped_tables = []
    for field_name, label in group_specs:
        grouped = {}
        for record in records:
            if field_name == "prompt_contract":
                value = (
                    f"{record.get('prompt_contract_id') or 'unknown'} "
                    f"v{record.get('prompt_contract_version') or 1}"
                )
            else:
                value = record.get(field_name) or "unknown"
            row = grouped.setdefault(
                str(value),
                {
                    "value": str(value),
                    "count": 0,
                    "successes": 0,
                    "requests": 0,
                    "tokens": 0,
                    "outcomes": Counter(),
                },
            )
            row["count"] += 1
            row["successes"] += int(bool(record.get("success")))
            row["requests"] += max(int(record.get("provider_requests") or 0), 0)
            row["tokens"] += max(int(record.get("total_tokens") or 0), 0)
            outcome = record.get("outcome") or "not_validated"
            row["outcomes"][
                outcome if outcome in KNOWN_OUTCOMES else "not_validated"
            ] += 1
        rows = []
        for row in grouped.values():
            row["success_rate"] = percent(row.pop("successes"), row["count"])
            row["outcomes"] = [
                {"name": name.replace("_", " ").title(), "count": value}
                for name, value in sorted(row["outcomes"].items())
            ]
            rows.append(row)
        rows.sort(key=lambda row: (-row["count"], row["value"]))
        grouped_tables.append({"field": field_name, "label": label, "rows": rows})

    tool_names = Counter()
    for record in records:
        for name in record.get("tool_names") or ():
            if name in KNOWN_TOOL_NAMES:
                tool_names[name] += 1

    return {
        "generation_count": count,
        "success_rate": percent(successes, count),
        "provider_requests": provider_requests,
        "tool_rounds": tool_rounds,
        "tool_calls": tool_calls,
        "token_total": total("total_tokens"),
        "quota_errors": quota_errors,
        "requests_per_generation": round(provider_requests / count, 2) if count else 0,
        "calls_per_round": round(tool_calls / tool_rounds, 2) if tool_rounds else 0,
        "sequential_round_rate": percent(sequential, tool_generations),
        "cache_hits": total("exact_call_cache_hits"),
        "average_duration_ms": round(total("duration_ms") / count) if count else 0,
        "provider_result_chars": total("provider_result_chars"),
        "validated_result_chars": total("validated_result_chars"),
        "original_file_count": total("original_file_count"),
        "groups": grouped_tables,
        "tools": [
            {"name": name, "count": value} for name, value in tool_names.most_common()
        ],
        "limited": count >= query_limit,
    }
