
import traceback
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from flask import g, has_request_context, request

from lagniappe import CONFIG

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _entity_load_tracing_enabled():
    return bool(getattr(CONFIG, "DEBUG_TRACING", False)) and has_request_context()


def _trace_label(item):
    if not item:
        return "None"

    kind = getattr(item, "kind", None)
    item_name = getattr(item, "name", None) or getattr(item, "id", None)
    if kind and item_name:
        return f"{kind}:{item_name}"
    if kind:
        return str(kind)

    key = getattr(item, "key", None)
    if key:
        return _trace_label(key)

    return str(item)


def _trace_summary(items, limit=6):
    if not items:
        return "-"

    shown = items[:limit]
    suffix = f", +{len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(shown) + suffix


def _trace_labels(items):
    if isinstance(items, dict):
        items = items.values()

    return [_trace_label(item) for item in items if item]


def _trace_frame_location(frame):
    path = Path(frame.filename).resolve()
    with suppress(ValueError):
        path = path.relative_to(PROJECT_ROOT)
    return f"{path}:{frame.lineno} {frame.name}"


def _trace_caller():
    for frame in reversed(traceback.extract_stack()[:-1]):
        location = _trace_frame_location(frame)
        if location.startswith("lagniappe/core/entities/__init__.py:"):
            continue
        return location
    return "-"


def record_entity_load_trace(
    *,
    primary: Iterable[object] | None,
    secondary: Iterable[object] | None,
    related: Iterable[object] | None,
    first_batch_key_count: int,
    related_key_count: int,
    fetch_depth: str | None = None,
    fetch_reason: str | None = None,
    fetch_stage: str | None = None,
) -> None:
    """Record one request-local entity-fetch diagnostic entry."""
    if not _entity_load_tracing_enabled():
        return
    if not first_batch_key_count and not related_key_count:
        return

    if not hasattr(g, "entity_loads"):
        g.entity_loads = []

    first_batch_calls = 1 if first_batch_key_count else 0
    related_batch_calls = 1 if related_key_count else 0

    trace = {
        "operation": "load",
        "caller": _trace_caller(),
        "primary": _trace_labels(primary),
        "secondary": _trace_labels(secondary),
        "related": _trace_labels(related),
        "first_batch_keys": first_batch_key_count,
        "related_batch_keys": related_key_count,
        "first_batch_calls": first_batch_calls,
        "related_batch_calls": related_batch_calls,
        "db_reads": first_batch_calls + related_batch_calls,
    }
    if fetch_depth is not None:
        trace["fetch_depth"] = fetch_depth
    if fetch_reason is not None:
        trace["fetch_reason"] = fetch_reason
    if fetch_stage is not None:
        trace["fetch_stage"] = fetch_stage
    g.entity_loads.append(trace)


def print_entity_load_trace(response: object | None = None) -> None:
    """Print request-local entity-fetch diagnostics."""
    if not _entity_load_tracing_enabled():
        return

    loads = [load for load in getattr(g, "entity_loads", []) if _trace_db_reads(load)]
    if not loads or getattr(g, "entity_load_trace_printed", False):
        return

    g.entity_load_trace_printed = True
    first_batch_keys = sum(load["first_batch_keys"] for load in loads)
    related_batch_keys = sum(load["related_batch_keys"] for load in loads)
    db_reads = sum(_trace_db_reads(load) for load in loads)
    print(
        f"[entity-loads] {_request_trace_label(response)}: "
        f"{len(loads)} entity calls, "
        f"{db_reads} db reads, "
        f"{first_batch_keys} first-batch keys, "
        f"{related_batch_keys} related keys"
    )
    for index, load in enumerate(loads, start=1):
        fetch_details = ""
        if load.get("fetch_depth"):
            fetch_details = f" fetch={load['fetch_depth']}"
        if load.get("fetch_reason"):
            fetch_details += f" reason={load['fetch_reason']}"
        if load.get("fetch_stage"):
            fetch_details += f" stage={load['fetch_stage']}"
        print(
            f"[entity-loads]   #{index} {load.get('operation', 'load')} "
            f"caller={load.get('caller', '-')}"
            f"{fetch_details} "
            f"primary={_trace_summary(load['primary'])} "
            f"secondary={_trace_summary(load['secondary'])} "
            f"related={_trace_summary(load['related'])}"
        )


def _trace_db_reads(load):
    return load.get(
        "db_reads",
        load.get("first_batch_calls", 0) + load.get("related_batch_calls", 0),
    )


def _request_trace_label(response=None):
    path = request.full_path.rstrip("?")
    status = getattr(response, "status_code", None) or "-"
    endpoint = request.endpoint or "-"
    rule = getattr(request.url_rule, "rule", None) or "-"
    return f"{request.method} {path} status={status} endpoint={endpoint} rule={rule}"
