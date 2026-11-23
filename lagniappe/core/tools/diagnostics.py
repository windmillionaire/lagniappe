"""Optional timing and profiling diagnostics."""

from collections.abc import Callable, Mapping
from typing import Protocol, cast, overload

import cProfile
from functools import wraps
from pathlib import Path
import pstats
import time
from flask import has_request_context, request
from lagniappe import CONFIG

class _ProfileStats(Protocol):
    stats: Mapping[tuple[str, int, str], tuple[int, int, float, float, object]]


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROFILE_SOURCE_ROOTS = {
    "config",
    "installer",
    "lagniappe",
    "runner",
    "src",
    "testing",
}
PROFILE_SOURCE_FILES = {"main.py", "run.py"}


@overload
def timed[**P, T](func: Callable[P, T], *, profile: bool = False, limit: int = 12, min_ms: float = 0.0, project_only: bool = True, enabled: bool | None = None, label: str | None = None) -> Callable[P, T]: ...

@overload
def timed[**P, T](func: None = None, *, profile: bool = False, limit: int = 12, min_ms: float = 0.0, project_only: bool = True, enabled: bool | None = None, label: str | None = None) -> Callable[[Callable[P, T]], Callable[P, T]]: ...

def timed[**P, T](
    func: Callable[P, T] | None = None,
    *,
    profile: bool = False,
    limit: int = 12,
    min_ms: float = 0.0,
    project_only: bool = True,
    enabled: bool | None = None,
    label: str | None = None,
) -> Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]:
    """Print elapsed time for a function, optionally with top profile rows.

    By default, output is controlled by ``CONFIG.DEBUG_TRACING``. Use
    ``@timed(enabled=True)`` for a temporary always-on measurement. With Flask
    routes, put ``@timed`` closest to the function to time the route body after
    other decorators; put it above auth/load decorators to include their work.
    Profile output shows project-source cumulative rows by default; set
    ``project_only=False`` to include dependency frames in the same table.
    """

    def decorator(wrapped_func: Callable[P, T]) -> Callable[P, T]:
        @wraps(wrapped_func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if not _timing_enabled(enabled):
                return wrapped_func(*args, **kwargs)

            timer_label = label or _function_label(wrapped_func)
            profiler = cProfile.Profile() if profile else None
            start_time = time.perf_counter()
            try:
                if profiler:
                    return profiler.runcall(wrapped_func, *args, **kwargs)
                return wrapped_func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                _print_timing(
                    timer_label,
                    elapsed_ms,
                    profiler=profiler,
                    limit=limit,
                    min_ms=min_ms,
                    project_only=project_only,
                )

        return wrapper

    if func is not None:
        return decorator(func)

    return decorator


def _timing_enabled(enabled):
    if enabled is not None:
        return bool(enabled)

    return bool(getattr(CONFIG, "DEBUG_TRACING", False))


def _function_label(func):
    module = getattr(func, "__module__", "")
    qualname = getattr(func, "__qualname__", getattr(func, "__name__", "function"))
    return f"{module}.{qualname}" if module else qualname


def _print_timing(label, elapsed_ms, *, profiler, limit, min_ms, project_only):
    print(f"[timing] {_timing_label(label)}: {elapsed_ms:.2f} ms")

    if not profiler:
        return

    rows = _profile_rows(
        profiler,
        limit=limit,
        min_ms=min_ms,
        project_only=project_only,
    )
    title = (
        "project calls by cumulative time (includes child/dependency calls)"
        if project_only
        else "all calls by cumulative time"
    )
    _print_profile_rows(
        title,
        rows,
        limit,
    )


def _timing_label(label):
    if not has_request_context():
        return label

    path = request.full_path.rstrip("?")
    return f"{request.method} {path} {label}"


def _print_profile_rows(title, rows, limit):
    if not rows:
        print(f"[timing] no {title} rows matched filters")
        return

    print(f"[timing] {title} (limit={limit})")
    print("[timing] cum_ms  self_ms  calls  function")
    for row in rows:
        print(
            f"[timing] {row['cum_ms']:7.2f} {row['self_ms']:8.2f} "
            f"{row['calls']:>6}  {row['location']}"
        )


def _profile_rows(profiler, *, limit, min_ms, project_only):
    # CPython publishes the per-location counters on Stats.stats (omitted from typeshed).
    stats = cast(_ProfileStats, pstats.Stats(profiler))
    rows = []
    for (filename, line, function), stat in stats.stats.items():
        _primitive_calls, total_calls, total_time, cumulative_time, _callers = stat
        cum_ms = cumulative_time * 1000
        if cum_ms < min_ms:
            continue

        location = _profile_location(filename, line, function, project_only)
        if not location:
            continue

        rows.append(
            {
                "cum_ms": cum_ms,
                "self_ms": total_time * 1000,
                "calls": str(total_calls),
                "location": location,
            }
        )

    rows.sort(key=lambda row: row["cum_ms"], reverse=True)
    return rows[:limit]


def _profile_location(filename, line, function, project_only):
    if filename.startswith("<"):
        return None if project_only else f"{filename}:{line} {function}"

    path = Path(filename).resolve()
    if project_only:
        try:
            path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            return None
        if path.parts and (
            path.parts[0] not in PROFILE_SOURCE_ROOTS
            and path.name not in PROFILE_SOURCE_FILES
        ):
            return None

    return f"{path}:{line} {function}"

