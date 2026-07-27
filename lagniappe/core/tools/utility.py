"""General-purpose utility functions (hashing, HTML, dates, sorting)."""

import cProfile
from functools import wraps
import hashlib
from io import BytesIO
import os
from pathlib import Path
import pstats
import re
import time
import uuid

from bs4 import BeautifulSoup
from flask import has_request_context, request
import requests

from lagniappe import CONFIG

from .. import exceptions

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


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_short_hash_and_uuid
# @features utility
# @dimensions hashing
def short_hash(value):
    """Return the first 12 characters of a SHA-256 hex digest."""
    hash_object = hashlib.sha256(value.encode())
    hex_digest = hash_object.hexdigest()
    return hex_digest[:12]


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::Hash
# @reason collision fallback when generating entity hashes
def random_hash(length=12):
    """Return a random alphanumeric string (0-9, a-z)."""
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(alphabet[b % len(alphabet)] for b in os.urandom(length))


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_short_hash_and_uuid
# @features utility
# @dimensions hashing
def short_uuid():
    """Return the first segment of a UUID4 (8 hex chars)."""
    return str(uuid.uuid4()).split("-")[0]


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_strip_tags
# @features utility
# @dimensions html-stripping
def strip_tags(html_content):
    """Strip HTML tags and return plain text; whitespace is collapsed to single spaces."""
    if isinstance(html_content, str):
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=" ")
        return re.sub(r"\s+", " ", text).strip()
    else:
        return html_content


# @testable false
# @covered-by lagniappe/core/properties/user_entity.py::ProfilePhoto
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.validate_submission
# @reason external image fetch is owned by profile/bookmark image workflows
def download_image(url):
    """Download an image URL and return {success, file} or {success, error}."""
    from time import sleep

    sleep(0.3)
    try:
        response = requests.get(url, timeout=2)
        response.raise_for_status()

        if not response.content or len(response.content) < 500:
            return {"success": False, "error": "no image file found"}

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return {"success": False, "error": "not an image file"}

        file = BytesIO(response.content)
        file.seek(0)
        file.content_type = content_type
        return {"success": True, "file": file}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        exceptions.capture(e, {"function": "download_image", "url": url})
        return {"success": False, "error": str(e)}


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_config_disabled
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_config_enabled
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_parameterized_preserves_metadata
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_profiles_project_calls
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_profile_omits_raw_profile_table
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_project_filter_excludes_local_dependency_paths
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_profile_rows_use_total_calls
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_prints_when_wrapped_function_raises
# @tests tests_unit/test_001_test_general_and_utilities.py::test_timed_prints_request_label_without_entity_trace
# @features utility
# @dimensions timing
def timed(
    func=None,
    *,
    profile=False,
    limit=12,
    min_ms=0.0,
    project_only=True,
    enabled=None,
    label=None,
):
    """Print elapsed time for a function, optionally with top profile rows.

    By default, output is controlled by ``CONFIG.DEBUG_TRACING``. Use
    ``@timed(enabled=True)`` for a temporary always-on measurement. With Flask
    routes, put ``@timed`` closest to the function to time the route body after
    other decorators; put it above auth/load decorators to include their work.
    Profile output shows project-source cumulative rows by default; set
    ``project_only=False`` to include dependency frames in the same table.
    """

    # @testable false
    # @covered-by lagniappe/core/tools/utility.py::timed
    # @reason nested decorator factory is exercised through timed
    def decorator(wrapped_func):
        # @testable false
        # @covered-by lagniappe/core/tools/utility.py::timed
        # @reason wrapper behavior is exercised through timed
        @wraps(wrapped_func)
        def wrapper(*args, **kwargs):
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


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason timing toggle resolution is part of timed decorator behavior
def _timing_enabled(enabled):
    if enabled is not None:
        return bool(enabled)

    return bool(getattr(CONFIG, "DEBUG_TRACING", False))


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason diagnostic label formatting is part of timed decorator output
def _function_label(func):
    module = getattr(func, "__module__", "")
    qualname = getattr(func, "__qualname__", getattr(func, "__name__", "function"))
    return f"{module}.{qualname}" if module else qualname


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason stdout formatting is part of timed decorator output
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


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason request label formatting is part of timed decorator output
def _timing_label(label):
    if not has_request_context():
        return label

    path = request.full_path.rstrip("?")
    return f"{request.method} {path} {label}"


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason profiler table formatting is part of timed decorator output
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


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason cProfile row shaping is part of timed decorator output
def _profile_rows(profiler, *, limit, min_ms, project_only):
    stats = pstats.Stats(profiler)
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


# @testable false
# @covered-by lagniappe/core/tools/utility.py::timed
# @reason profiler file labels are part of timed decorator output
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


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_clean_html
# @features utility
# @dimensions html-cleaning
def clean_html(html):
    """Strip markdown code fences, empty tags, and inter-tag whitespace."""
    if not html or not isinstance(html, str):
        return html or ""

    # First, remove markdown code blocks (regex needed since this isn't HTML)
    html = re.sub(r"```html\s*(.*?)\s*```", r"\1", html, flags=re.DOTALL)
    html = re.sub(r"```\s*(.*?)\s*```", r"\1", html, flags=re.DOTALL)

    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Remove empty elements (paragraphs, list items, etc.)
    for tag in soup.find_all(["p", "li", "div", "span"]):
        if not tag.get_text(strip=True) and not tag.find_all(["img", "br", "hr"]):
            tag.decompose()

    # Get the cleaned HTML
    cleaned = str(soup)

    # Remove any remaining whitespace between tags
    cleaned = re.sub(r">\s+<", "><", cleaned)

    return cleaned.strip()


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_sort_tasks
# @features utility
# @dimensions task-sorting
def sort_tasks(tasks):
    """Sort tasks: due-date ascending first, then no-due-date by modified descending."""
    with_due_date = [t for t in tasks if t.due_date]
    without_due_date = [t for t in tasks if not t.due_date]
    return sorted(with_due_date, key=lambda t: t.due_date) + sorted(
        without_due_date, key=lambda t: t.modified, reverse=True
    )
