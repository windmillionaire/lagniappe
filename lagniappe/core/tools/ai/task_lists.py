"""Bounded task discovery shared by page task and page detail reads."""

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json

from lagniappe.core.definitions import Action
from lagniappe.core.tools.dates import user_timezone

from .references import hash_reference


DEFAULT_TASK_LIMIT = 25
MAX_TASK_LIMIT = 100
DESCRIPTION_LIMIT = 500
TASK_LIMIT_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": MAX_TASK_LIMIT,
    "description": "Maximum compact tasks per response (default 25, maximum 100).",
}


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_page_tasks.py::execute_get_page_tasks
# @covered-by lagniappe/core/tools/ai/function_definitions/get_page_details.py::execute_get_page_details
# @reason shared compact projection and continuation are exercised through both read tools
def compact_task_list(
    page, user, *, include_completed, limit=DEFAULT_TASK_LIMIT, cursor=None
):
    """Page an authorized list without serializing task forms or submissions.

    Page loads and filters its task relations once. Pagination bounds projection
    and response size, not the underlying Page relation fetch. A cursor identifies
    one viewer/page/scope and ordered task revision snapshot, never authorization.
    """
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_TASK_LIMIT
    ):
        return {"error": "limit must be an integer from 1 to 100"}
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor or len(cursor) > 512
    ):
        return {
            "error": "Invalid task cursor. Restart this task list without a cursor."
        }

    scope = "active_and_completed" if include_completed else "active"
    tasks = [*page.tasks, *(page.completed if include_completed else [])]
    tasks = [task for task in tasks if task.allowed(Action.VIEW, user=user)]
    tasks.sort(
        key=lambda task: (bool(task.completed), (task.name or "").casefold(), task.hash)
    )
    snapshot = hashlib.sha256(
        json.dumps(
            [
                hash_reference(page),
                hash_reference(user),
                scope,
                [
                    (task.hash, bool(task.completed), str(task.modified))
                    for task in tasks
                ],
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    offset = 0
    if cursor:
        try:
            decoded = json.loads(
                base64.b64decode(cursor, altchars=b"-_", validate=True)
            )
            if (
                not isinstance(decoded, dict)
                or set(decoded) != {"snapshot", "offset"}
                or type(decoded["offset"]) is not int
                or not 0 < decoded["offset"] < len(tasks)
                or decoded["snapshot"] != snapshot
            ):
                raise ValueError("stale cursor")
            offset = decoded["offset"]
        except (ValueError, TypeError, binascii.Error):
            return {
                "error": "Invalid or stale task cursor. Restart this task list without a cursor."
            }

    selected = tasks[offset : offset + limit]
    active, completed, errors = [], [], []
    tz = user_timezone(user)
    for task in selected:
        try:
            row = _compact_task(task, user, tz)
        except Exception:
            # Do not expose exception text, related records, or submission data.
            errors.append(
                {
                    "hash": hash_reference(task),
                    "message": "Task details could not be read. Use get_entity for this task.",
                }
            )
            continue
        (completed if row["completed"] else active).append(row)
    next_offset = offset + len(selected)
    has_more = next_offset < len(tasks)
    return {
        "tasks": active,
        **({"completed_tasks": completed} if include_completed else {}),
        "task_list": {
            "scope": scope,
            "limit": limit,
            "total_count": len(tasks),
            "active_count": sum(not task.completed for task in tasks),
            "completed_count": sum(bool(task.completed) for task in tasks),
            "returned_count": len(active) + len(completed),
            "has_more": has_more,
            "next_cursor": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "snapshot": snapshot,
                        "offset": next_offset,
                    },
                    separators=(",", ":"),
                ).encode()
            ).decode()
            if has_more
            else None,
            "incomplete": bool(errors),
            **({"serialization_errors": errors} if errors else {}),
        },
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/task_lists.py::compact_task_list
# @reason compact fields are exercised through page task discovery
def _compact_task(task, user, tz):
    description = task.description or ""
    result = {
        "kind": "task",
        "hash": hash_reference(task),
        "name": task.name,
        "url": task._ai_url(),
        "completed": bool(task.completed),
        "description": description[:DESCRIPTION_LIMIT],
        "description_truncated": len(description) > DESCRIPTION_LIMIT,
        "permissions": {
            "can_view": True,
            "can_edit": task.allowed(Action.EDIT, user=user),
        },
    }
    for field in ("project", "model", "form"):
        entity = getattr(task, field)
        if entity and entity.allowed(Action.VIEW, user=user):
            result[field] = {
                "kind": entity.entity_kind,
                "hash": hash_reference(entity),
                "name": entity.name,
            }
    for field in ("due_date", "completed_on"):
        value = getattr(task, field)
        if value:
            if isinstance(value, datetime):
                value = (
                    (value if value.tzinfo else value.replace(tzinfo=timezone.utc))
                    .astimezone(tz)
                    .date()
                )
            result[field] = value.isoformat()
    return result
