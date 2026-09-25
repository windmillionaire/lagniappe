"""Bounded experiments measurements; never retain provider arguments or content."""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Mapping
from functools import wraps
import json
import re
import time
import uuid


CURRENT = ContextVar("experiments_measurement", default=None)
TRACE_LIMIT = 128


# @testable true
# @tests tests_unit/test_034_experiments.py::test_measurements_are_bounded_private_and_context_local
# @matrix experiments : request-measurements
class Measurement:
    def __init__(self, mode):
        self.request_id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self.mode = mode
        self.operations = {}
        self.trace = []
        self.dropped = 0
        self.jobs = []

    # @testable false
    # @covered-by lagniappe/core/tools/measurements.py::Measurement
    # @reason aggregate and trace storage belong to the request measurement contract
    def record(self, component, operation, started, *, failed=False, count=1, **counts):
        duration = (time.perf_counter() - started) * 1000
        label = f"{component}.{operation}"
        item = self.operations.setdefault(
            label, {"calls": 0, "count": 0, "ms": 0, "errors": 0}
        )
        item["calls"] += 1
        item["count"] += count
        item["ms"] += duration
        item["errors"] += int(failed)
        for key, value in counts.items():
            item[key] = item.get(key, 0) + value
        if self.mode == "trace":
            if len(self.trace) < TRACE_LIMIT:
                self.trace.append(
                    {
                        "operation": label,
                        "start_ms": round((started - self.started) * 1000, 3),
                        "ms": round(duration, 3),
                        "failed": failed,
                    }
                )
            else:
                self.dropped += 1

    # @testable false
    # @covered-by lagniappe/core/tools/measurements.py::Measurement
    # @reason serialization belongs to the request measurement contract
    def summary(self):
        return {
            "event": "lagniappe.experiments.request",
            "schema": 1,
            "request_id": self.request_id,
            "mode": self.mode,
            "app_ms": round((time.perf_counter() - self.started) * 1000, 3),
            "operations": {
                key: {**value, "ms": round(value["ms"], 3)}
                for key, value in self.operations.items()
            },
            "jobs": self.jobs,
            **(
                {"trace": self.trace, "trace_dropped": self.dropped}
                if self.mode == "trace"
                else {}
            ),
        }


# @testable true
# @tests tests_unit/test_034_experiments.py::test_measurements_are_bounded_private_and_context_local
# @matrix experiments : request-measurements
@contextmanager
def span(component, operation, *, count=1):
    measurement = CURRENT.get()
    if measurement is None:
        yield {}
        return
    started = time.perf_counter()
    counts = {}
    failed = True
    try:
        yield counts
        failed = False
    finally:
        measurement.record(
            component, operation, started, failed=failed, count=count, **counts
        )


# @testable false
# @covered-by lagniappe/core/tools/measurements.py::span
# @reason decorator only enters the shared timing context
def timed(component, operation):
    # @testable false
    # @covered-by lagniappe/core/tools/measurements.py::span
    # @reason decorator factory for the shared timing context
    def decorate(function):
        # @testable false
        # @covered-by lagniappe/core/tools/measurements.py::span
        # @reason transparent argument forwarding to the measured function
        @wraps(function)
        def measured(*args, **kwargs):
            with span(component, operation):
                return function(*args, **kwargs)

        return measured

    return decorate


# @testable true
# @tests tests_unit/test_034_experiments.py::test_measurements_count_provider_calls_without_arguments
# @matrix experiments : provider-measurements
def instrument_datastore(client):
    """Count SDK RPC invocations, including each query page, not internal retries."""
    api = client._datastore_api
    for name in (
        "lookup",
        "run_query",
        "run_aggregation_query",
        "commit",
        "allocate_ids",
        "begin_transaction",
        "rollback",
    ):
        original = getattr(api, name, None)
        if original is None:
            continue

        # @testable false
        # @covered-by lagniappe/core/tools/measurements.py::instrument_datastore
        # @reason binds each SDK method without recording its arguments
        @wraps(original)
        def measured(*args, _method=original, _name=name, **kwargs):
            with span("datastore", _name) as counts:
                request = kwargs.get("request", args[0] if args else kwargs)
                if _name in {"lookup", "allocate_ids"}:
                    counts["keys"] = len(_field(request, "keys", []))
                if _name == "commit":
                    mutations = _field(request, "mutations", [])
                    counts.update(writes=0, deletes=0)
                    for mutation in mutations:
                        operation = (
                            next(
                                (
                                    key
                                    for key in ("insert", "update", "upsert", "delete")
                                    if key in mutation
                                ),
                                None,
                            )
                            if isinstance(mutation, Mapping)
                            else getattr(mutation, "_pb", mutation).WhichOneof(
                                "operation"
                            )
                        )
                        if operation == "delete":
                            counts["deletes"] += 1
                        elif operation in {"insert", "update", "upsert"}:
                            counts["writes"] += 1
                result = _method(*args, **kwargs)
                if _name == "lookup":
                    counts.update(
                        found=len(result.found),
                        missing=len(result.missing),
                        deferred=len(result.deferred),
                    )
                elif _name == "run_query":
                    counts["entities"] = len(result.batch.entity_results)
                return result

        setattr(api, name, measured)


# @testable false
# @covered-by lagniappe/core/tools/measurements.py::instrument_datastore
# @reason SDK requests accept both mapping and protobuf representations
def _field(value, name, default):
    return (
        value.get(name, default)
        if isinstance(value, Mapping)
        else getattr(value, name, default)
    )


# @testable true
# @tests tests_unit/test_034_experiments.py::test_measurements_count_provider_calls_without_arguments
# @matrix experiments : provider-measurements
def instrument_storage(client):
    """Count Storage HTTP calls without materializing streaming response bodies."""
    original = client._http.request

    # @testable false
    # @covered-by lagniappe/core/tools/measurements.py::instrument_storage
    # @reason transport wrapper deliberately ignores URLs, headers and bodies
    @wraps(original)
    def measured(method, *args, **kwargs):
        verb = str(method).upper()
        with span(
            "storage",
            verb
            if verb in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
            else "OTHER",
        ) as counts:
            response = original(method, *args, **kwargs)
            counts["http_errors"] = int(response.status_code >= 400)
            length = getattr(response, "headers", {}).get("Content-Length", "")
            if isinstance(length, str) and length.isascii() and length.isdigit():
                counts["declared_response_bytes"] = int(length)
            data = kwargs.get("data")
            if isinstance(data, (bytes, bytearray)):
                counts["body_bytes"] = len(data)
            return response

    client._http.request = measured


# @testable false
# @covered-by lagniappe/core/tools/measurements.py::instrument_redis
# @reason exposes only a bounded command name, never keys or values
def _redis_command(args):
    name = args[0] if args else "OTHER"
    if isinstance(name, bytes):
        name = name.decode("ascii", errors="replace")
    name = str(name).upper()
    return name if re.fullmatch(r"[A-Z.]{1,32}", name) else "OTHER"


# @testable true
# @tests tests_unit/test_034_experiments.py::test_measurements_count_provider_calls_without_arguments
# @matrix experiments : provider-measurements
def instrument_redis(client):
    """Measure executed commands and pipeline batches, never pipeline enqueueing."""
    original = client.execute_command
    original_pipeline = client.pipeline

    # @testable false
    # @covered-by lagniappe/core/tools/measurements.py::instrument_redis
    # @reason single-command adapter for the shared provider span
    @wraps(original)
    def execute(*args, **kwargs):
        with span("redis", _redis_command(args)) as counts:
            result = original(*args, **kwargs)
            if _redis_command(args) in {"GET", "HGET", "JSON.GET"}:
                counts.update(hits=int(result is not None), misses=int(result is None))
            if isinstance(result, bytes):
                counts["value_bytes"] = len(result)
            return result

    # @testable false
    # @covered-by lagniappe/core/tools/measurements.py::instrument_redis
    # @reason measures actual pipeline execution and immediate WATCH commands
    @wraps(original_pipeline)
    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        run = pipe.execute
        immediate = pipe.immediate_execute_command

        # @testable false
        # @covered-by lagniappe/core/tools/measurements.py::instrument_redis
        # @reason observes the batch before Redis clears its command stack
        @wraps(run)
        def execute_batch(*args, **kwargs):
            commands = [
                _redis_command(command) for command, _options in pipe.command_stack
            ]
            with span("redis", "pipeline", count=len(commands)) as counts:
                result = run(*args, **kwargs)
                for command, value in zip(commands, result):
                    if command in {"GET", "HGET", "JSON.GET"} and not isinstance(
                        value, Exception
                    ):
                        counts["hits"] = counts.get("hits", 0) + int(value is not None)
                        counts["misses"] = counts.get("misses", 0) + int(value is None)
                    if isinstance(value, bytes):
                        counts["value_bytes"] = counts.get("value_bytes", 0) + len(
                            value
                        )
                    counts["command_errors"] = counts.get("command_errors", 0) + int(
                        isinstance(value, Exception)
                    )
                return result

        # @testable false
        # @covered-by lagniappe/core/tools/measurements.py::instrument_redis
        # @reason WATCH-mode commands execute outside the queued batch
        @wraps(immediate)
        def execute_immediate(*args, **kwargs):
            with span("redis", _redis_command(args)):
                return immediate(*args, **kwargs)

        pipe.execute = execute_batch
        pipe.immediate_execute_command = execute_immediate
        return pipe

    client.execute_command = execute
    client.pipeline = pipeline


# @testable false
# @covered-by lagniappe/core/tools/measurements.py::Measurement
# @reason links existing opaque job telemetry IDs without retaining job parameters
def link_job(job):
    measurement = CURRENT.get()
    telemetry = getattr(job, "telemetry_id", None)
    if (
        measurement
        and telemetry
        and telemetry not in measurement.jobs
        and len(measurement.jobs) < 32
    ):
        measurement.jobs.append(telemetry)


# @testable false
# @covered-by lagniappe/core/tools/measurements.py::Measurement
# @reason one JSON line is collected by the existing cloud stdout logging pipeline
def emit(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)
