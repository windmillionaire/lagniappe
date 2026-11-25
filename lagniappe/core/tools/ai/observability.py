"""Privacy-bounded observability for application-visible text generations."""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextvars import Token
from typing import TYPE_CHECKING, Literal, cast, overload

if TYPE_CHECKING:
    from google.genai import types
    from lagniappe import Config
    from .prompt import Prompt

from collections import Counter
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, UTC
import hashlib
import json
import logging
import time
import uuid

if TYPE_CHECKING:
    from lagniappe.core.tools.deferred_jobs.control import DeferredExecutionControl

from .constants import THINKING_LEVELS
from lagniappe import CONFIG
from lagniappe.core.tools.database import analytics as analytics_database


LOGGER = logging.getLogger(__name__)
TELEMETRY_SCHEMA_VERSION = 1
RETENTION_DAYS = 30
PRUNE_LIMIT = 500
QUERY_LIMIT = 1000
MAX_TIMED_ROUNDS = 128

type TimingComponent = Literal["provider", "tool", "progress_write", "claim_check", "telemetry_write"]
_TIMING_COUNTS = {
    "progress_write": "progress_writes",
    "claim_check": "claim_checks",
    "telemetry_write": "telemetry_writes",
}

KNOWN_TRAFFIC_TYPES = {
    "ON_DEMAND": "on_demand",
    "PROVISIONED_THROUGHPUT": "provisioned_throughput",
    "PAYGO": "paygo",
}
OUTCOME_LABELS = {
    "not_validated": "Not validated",
    "validated": "Validated",
    "normalized": "Formatted / normalized",
    # Older records also used local_repair for ordinary normalization.
    "local_repair": "Locally adjusted",
    "model_repair": "Model repair",
    "review_fallback": "Needs review",
    "validation_failed": "Validation failed",
}
KNOWN_OUTCOMES = set(OUTCOME_LABELS)
OUTCOME_PRIORITY = {
    "not_validated": 0,
    "validated": 1,
    "normalized": 2,
    "local_repair": 3,
    "model_repair": 4,
    "review_fallback": 5,
    "validation_failed": 6,
}
KNOWN_PROVIDER_STAGES = {"initial", "tool", "structured_final", "validation_repair"}
KNOWN_TOOL_NAMES = {
    "get_help",
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
    "preview_form_schema_update",
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
    "provider_duration_ms",
    "tool_duration_ms",
    "progress_write_duration_ms",
    "claim_check_duration_ms",
    "telemetry_write_duration_ms",
    "progress_writes",
    "claim_checks",
    "telemetry_writes",
    "round_timings",
)


@dataclass(frozen=True)
class AIExecutionContext:
    """Allowlisted deferred-job metadata available during one preparation pass."""

    job_type: str | None = None
    attempt: int | None = None
    contract_version: int | None = None
    telemetry_id: str | None = field(default=None, repr=False, compare=False)
    execution_control: DeferredExecutionControl | None = field(default=None, repr=False, compare=False)


_EMPTY_CONTEXT = AIExecutionContext()
_EXECUTION_CONTEXT = ContextVar("ai_execution_context", default=_EMPTY_CONTEXT)
_CURRENT_OBSERVER: ContextVar[GenerationObserver | None] = ContextVar("ai_generation_observer", default=None)


@contextmanager
def ai_execution_context(
    *,
    job_type: str | None = None,
    attempt: int | None = None,
    contract_version: int | None = None,
    telemetry_id: str | None = None,
    execution_control: DeferredExecutionControl | None = None,
) -> Iterator[None]:
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


def current_execution_control() -> DeferredExecutionControl | None:
    """Return the ephemeral deferred execution controller, when present."""
    return _EXECUTION_CONTEXT.get().execution_control


@dataclass(kw_only=True)
class GenerationTimings:
    """Exclusive foreground elapsed time; counts include attempted operations."""

    provider_duration_ms: int = 0
    tool_duration_ms: int = 0
    progress_write_duration_ms: int = 0
    claim_check_duration_ms: int = 0
    telemetry_write_duration_ms: int = 0
    progress_writes: int = 0
    claim_checks: int = 0
    telemetry_writes: int = 0


@dataclass
class RoundTiming(GenerationTimings):
    provider_stage: str
    requested_tool_calls: int = 0


@dataclass
class GenerationSummaryV1(GenerationTimings):
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
    requested_thinking_level: str = "unset"
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
    round_timings: list[RoundTiming] = field(default_factory=list)
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

    def payload(self) -> dict[str, object]:
        """Return only fields declared by this typed contract."""
        return asdict(self)


def diagnostic_record(record: Mapping[str, object]) -> dict[str, object]:
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


def operation_diagnostic_payload(operation: Mapping[str, object], records: Sequence[Mapping[str, object]], *, query_limit: int = QUERY_LIMIT) -> dict[str, object]:
    """Build a transferable, privacy-bounded job/provider snapshot."""
    records = reconcile_generation_records(records, [operation])
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


def enabled(config: Config = CONFIG) -> bool:
    return bool(getattr(config, "AI_OBSERVABILITY", False))


@overload
def _bounded_contract(value: object, fallback: str = "unknown") -> str: ...
@overload
def _bounded_contract(value: object, fallback: None) -> str | None: ...


def _bounded_contract(value: object, fallback: str | None = "unknown") -> str | None:
    value = str(value or "").strip().lower().replace("_", "-")
    if not value or len(value) > 80:
        return fallback
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in value
    ):
        return fallback
    return value


def _counter(value: object) -> int:
    """Decode a counter from a current or historical telemetry row."""
    return int(cast("int | str | None", value) or 0)


def _size(value):
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, separators=(",", ":"), default=str))
    except Exception:
        return 0


def _fingerprint(value):
    try:
        serialized = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        )
    except Exception:
        serialized = f"<{type(value).__name__}>"
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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


class GenerationObserver:
    """Mutable in-memory reducer for one public ``generate_content`` call."""

    def __init__(self, prompt: Prompt) -> None:
        self.active = enabled()
        self.started = time.monotonic()
        self._elapsed_ns: Counter[TimingComponent] = Counter()
        self._round_start_ns: Counter[TimingComponent] = Counter()
        self._round: RoundTiming | None = None
        self.validation_started = False
        self.validation_fingerprint = None
        correlation_id = str(uuid.uuid4())
        contract = getattr(prompt, "observability_contract", None) or {}
        execution = _EXECUTION_CONTEXT.get()
        created = datetime.now(UTC)
        self.live = bool(self.active and execution.telemetry_id)
        self.summary = GenerationSummaryV1(
            correlation_id=correlation_id,
            created=created,
            updated=created,
            workflow=_bounded_contract(contract.get("workflow")),
            stage=_bounded_contract(contract.get("stage")),
            prompt_contract_id=_bounded_contract(contract.get("id")),
            prompt_contract_version=max(int(contract.get("version") or 1), 1),
            requested_thinking_level=(
                level if (level := getattr(prompt, "thinking_level", None)) in THINKING_LEVELS else "unset"
            ),
            deferred_job_type=_bounded_contract(execution.job_type, None),
            deferred_job_attempt=execution.attempt,
            deferred_contract_version=execution.contract_version,
            telemetry_id=(
                str(execution.telemetry_id) if execution.telemetry_id else None
            ),
            model_tier=(
                tier if (tier := getattr(prompt, "model_tier", None)) in {"primary", "utility"}
                else "primary"
            ),
            service_tier=(
                tier if (tier := getattr(prompt, "service_tier", None)) in {"standard", "priority", "flex"}
                else "standard"
            ),
            original_file_count=(
                len(getattr(prompt, "files", ()) or ())
                + len(getattr(prompt, "bytes", ()) or ())
            ),
        )

    def resolution(self, *, model: str, location: str) -> None:
        if not self.active:
            return
        self.summary.resolved_model = _bounded_contract(model)
        self.summary.location = _bounded_contract(location)
        self._persist_live()

    def install(self) -> Token[GenerationObserver | None]:
        return _CURRENT_OBSERVER.set(self)

    @staticmethod
    def reset(token: Token[GenerationObserver | None]) -> None:
        _CURRENT_OBSERVER.reset(token)

    def start_round(self, stage: str) -> None:
        """A turn starts before provider progress and includes its returned tool batch."""
        if not self.active:
            return
        self._round = None
        if len(self.summary.round_timings) < MAX_TIMED_ROUNDS:
            self._round = RoundTiming(stage if stage in KNOWN_PROVIDER_STAGES else "initial")
            self._round_start_ns = self._elapsed_ns.copy()
            self.summary.round_timings.append(self._round)

    @contextmanager
    def measure(self, component: TimingComponent) -> Iterator[None]:
        """Charge nested lease reads and progress writes independently of their caller."""
        previous = self._elapsed_ns.total()
        started = time.monotonic_ns()
        try:
            yield
        finally:
            elapsed = time.monotonic_ns() - started
            nested = self._elapsed_ns.total() - previous
            self._elapsed_ns[component] += elapsed - nested
            total = self._elapsed_ns[component]
            duration_field = f"{component}_duration_ms"
            count_field = _TIMING_COUNTS.get(component)
            setattr(self.summary, duration_field, total // 1_000_000)
            if count_field:
                setattr(self.summary, count_field, getattr(self.summary, count_field) + 1)
            if self._round is not None:
                round_ns = total - self._round_start_ns[component]
                setattr(self._round, duration_field, round_ns // 1_000_000)
                if count_field:
                    setattr(self._round, count_field, getattr(self._round, count_field) + 1)

    def request(self, stage: str) -> None:
        if self.active:
            self.summary.provider_requests += 1
            self.summary.active_provider_stage = (
                stage if stage in KNOWN_PROVIDER_STAGES else "initial"
            )
            if stage == "structured_final":
                self.summary.structured_final_used = True
            self._persist_live()

    def response(self, response: types.GenerateContentResponse) -> None:
        if not self.active:
            return
        self.summary.provider_responses += 1
        if self._round is not None:
            self._round.requested_tool_calls = len(response.function_calls or ())
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

    def provider_error(self, error: BaseException, stage: str, *, quota: bool = False) -> None:
        if not self.active or not quota:
            return
        stage = stage if stage in KNOWN_PROVIDER_STAGES else "initial"
        if stage not in self.summary.surfaced_quota_stages:
            self.summary.surfaced_quota_stages.append(stage)

    def empty_retry(self) -> None:
        if self.active:
            self.summary.empty_response_retries += 1

    def tool_round(self, function_calls: Sequence[types.FunctionCall], trace: Sequence[Mapping[str, object]]) -> None:
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
                    _counter(call.get("result_chars")), 0
                )
                self.summary.original_file_count += max(
                    _counter(call.get("file_parts")), 0
                )
        self.summary.tool_names.sort()
        self._persist_live()

    def provider_result(self, value: object) -> None:
        if self.active:
            self.summary.provider_result_chars = _size(value)

    def validated_result(self, after: object) -> None:
        if not self.active:
            return
        self.summary.validated_result_chars = _size(after)
        changed = self.validation_fingerprint != _fingerprint(after)
        self.outcome("normalized" if changed else "validated")

    def begin_validation(self, value: object) -> None:
        if self.active:
            self.validation_started = True
            self.validation_fingerprint = _fingerprint(value)

    def outcome(self, value: str) -> None:
        if not self.active or value not in KNOWN_OUTCOMES:
            return
        current = self.summary.outcome
        if OUTCOME_PRIORITY[value] >= OUTCOME_PRIORITY[current]:
            self.summary.outcome = value

    def finish(self, *, error: BaseException | None = None) -> None:
        if not self.active:
            return
        self.summary.duration_ms = max(int((time.monotonic() - self.started) * 1000), 0)
        self.summary.updated = datetime.now(UTC)
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

    def _persist_live(self):
        if not self.live:
            return
        self.summary.updated = datetime.now(UTC)
        self.summary.duration_ms = max(
            int((time.monotonic() - self.started) * 1000),
            0,
        )
        # The final snapshot includes the cost of all completed live upserts.
        # It cannot include its own write or subsequent retention pruning.
        with self.measure("telemetry_write"):
            self.persist(prune=False)

    def persist(self, *, prune: bool = True) -> None:
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


def current_observer() -> GenerationObserver | None:
    return _CURRENT_OBSERVER.get()


def generation_timing(component: TimingComponent) -> AbstractContextManager[None]:
    observer = current_observer()
    if observer is not None and observer.active:
        return observer.measure(component)
    return nullcontext()


def mark_outcome(value: str) -> None:
    observer = current_observer()
    if observer is not None:
        observer.outcome(value)


def _write_summary(summary):
    return analytics_database.create_ai_observability(
        summary.correlation_id,
        summary.payload(),
        exclude_from_indexes=EXCLUDE_FROM_INDEXES,
    )


def prune_old_records(*, now: datetime | None = None, limit: int = PRUNE_LIMIT) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    return analytics_database.delete_ai_observability(
        before=cutoff,
        batch_size=min(int(limit), PRUNE_LIMIT),
        once=True,
    )


def aggregate_records(records: Iterable[Mapping[str, object]], *, query_limit: int = QUERY_LIMIT) -> dict[str, object]:
    """Build the owner dashboard view model from already-windowed summaries."""
    records = list(records)
    count = len(records)

    def total(name):
        return sum(max(_counter(record.get(name)), 0) for record in records)

    def percent(numerator, denominator):
        return round((100 * numerator / denominator), 1) if denominator else 0.0

    successes = sum(bool(record.get("success")) for record in records)
    tool_generations = sum(
        _counter(record.get("tool_rounds")) > 0 for record in records
    )
    sequential = sum(_counter(record.get("tool_rounds")) > 1 for record in records)
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
            row["requests"] += max(_counter(record.get("provider_requests")), 0)
            row["tokens"] += max(_counter(record.get("total_tokens")), 0)
            outcome = record.get("outcome") or "not_validated"
            row["outcomes"][
                outcome if outcome in KNOWN_OUTCOMES else "not_validated"
            ] += 1
        rows = []
        for row in grouped.values():
            row["success_rate"] = percent(row.pop("successes"), row["count"])
            row["outcomes"] = [
                {"name": OUTCOME_LABELS[name], "count": value}
                for name, value in sorted(row["outcomes"].items())
            ]
            rows.append(row)
        rows.sort(key=lambda row: (-row["count"], row["value"]))
        grouped_tables.append({"field": field_name, "label": label, "rows": rows})

    tool_names = Counter()
    for record in records:
        names = cast("Iterable[str]", record.get("tool_names") or ())
        for name in names:
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


def reconcile_generation_records(records: Iterable[Mapping[str, object]], operations: Iterable[Mapping[str, object]], *, now: datetime | None = None) -> list[dict[str, object]]:
    """Project orphaned report attempts as interrupted using durable job state."""
    now = now or datetime.now(UTC)
    jobs = {item.get("telemetry_id"): item for item in operations if item.get("telemetry_id")}
    result = []
    for record in records:
        item = dict(record)
        if item.get("state") == "running" and item.get("deferred_job_type") == "report-ai":
            job = jobs.get(item.get("telemetry_id"), {})
            created = item.get("created")
            if isinstance(created, datetime) and created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            expired = isinstance(created, datetime) and now - created >= timedelta(minutes=10)
            stopped = job.get("status") in {"complete", "failed", "cancelled", "superseded"}
            replaced = _counter(job.get("attempt")) > _counter(item.get("deferred_job_attempt"))
            if expired or stopped or replaced:
                item.update(state="interrupted", active_provider_stage="interrupted", success=False, terminal_error_category="interrupted", terminal_error_class="interrupted")
        result.append(item)
    return result
