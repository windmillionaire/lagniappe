"""Debug logging helpers for AI workflows."""

import json
from pathlib import Path

from lagniappe import CONFIG

MAX_STRING = 1000
MAX_ITEMS = 20
MAX_DEPTH = 4


# @testable false
# @covered-by lagniappe/core/tools/ai/debug.py::ai_debug
# @reason debug flag lookup is exercised only through guarded logging callers
def enabled():
    """Return whether AI debug logging is enabled for this process."""
    return bool(getattr(CONFIG, "AI_DEBUG", False))


# @testable false
# @covered-by lagniappe/core/tools/ai/debug.py::ai_debug
# @reason debug output routing is a local observability helper
def debug_log(message):
    """Write one AI debug line to the configured sink."""
    path = getattr(CONFIG, "AI_DEBUG_LOG", None)
    if path:
        log_path = Path(path).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{message}\n")
        return

    print(message, flush=True)


# @testable infrastructure
# @reason debug breadcrumb logging is intentionally behavior-neutral
def ai_debug(event, **fields):
    """Print a compact AI_DEBUG line when debug logging is enabled."""
    if not enabled():
        return

    payload = _compact(fields)
    if payload:
        debug_log(
            f"AI_DEBUG {event} "
            f"{json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)}"
        )
    else:
        debug_log(f"AI_DEBUG {event}")


# @testable false
# @covered-by lagniappe/core/tools/ai/debug.py::ai_debug
# @reason compact debug serialization is a logging detail
def _compact(value, depth=0):
    if depth >= MAX_DEPTH:
        return f"<{type(value).__name__}>"

    if isinstance(value, str):
        if len(value) > MAX_STRING:
            return f"{value[:MAX_STRING]}...<truncated {len(value)} chars>"
        return value

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    if isinstance(value, dict):
        items = list(value.items())
        compacted = {
            str(key): _compact(child, depth + 1)
            for key, child in items[:MAX_ITEMS]
        }
        if len(items) > MAX_ITEMS:
            compacted["..."] = f"<{len(items) - MAX_ITEMS} more>"
        return compacted

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        compacted = [_compact(child, depth + 1) for child in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            compacted.append(f"...<{len(items) - MAX_ITEMS} more>")
        return compacted

    return str(value)
