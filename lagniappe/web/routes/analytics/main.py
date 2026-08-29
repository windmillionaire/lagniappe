from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone

from flask import abort, g, render_template, request
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    Action,
    DEFERRED_JOB_HEARTBEAT_SECONDS,
    Resource,
)
from lagniappe.core.tools.database import analytics as analytics_database
from lagniappe.core.tools.ai.observability import (
    aggregate_records,
    operation_diagnostic_payload,
)
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import analytics


PERIODS = {
    "today": "Today",
    "7d": "Last 7 Days",
    "30d": "Last 30 Days",
    "all": "All Time",
}
QUERY_LIMIT = 1000
DETAIL_LIMIT = 50
DELETE_BATCH_SIZE = 500
ACTION_LABELS = {
    "view": "View",
    "public_view": "Public View",
    "login": "Login",
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
}
ROUTE_ICON_KEYS = {
    "assets": "files",
    "categories": "category",
    "files": "files",
    "filters": ("filter", "list"),
    "forms": "form",
    "manual": "manual",
    "pages": "page",
    "process": "status",
    "projects": "project",
    "reference": "overview",
    "tasks": "tasks",
    "users": "group",
}
ROUTE_KINDS = {
    "assets": "file",
    "categories": "category",
    "files": "file",
    "filters": "page",
    "forms": "form",
    "home": "page",
    "manual": "page",
    "pages": "page",
    "process": "file",
    "projects": "project",
    "reference": "page",
    "tasks": "task",
    "users": "user",
}
CLEAR_RETENTION_OPTIONS = {
    "7d": {
        "label": "Delete Records Older Than 7 Days",
        "days": 7,
    },
    "30d": {
        "label": "Delete Records Older Than 30 Days",
        "days": 30,
    },
    "90d": {
        "label": "Delete Records Older Than 90 Days",
        "days": 90,
    },
    "all": {
        "label": "Delete All Records",
        "days": None,
    },
}


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason analytics records change outside normal entity fingerprinting
@analytics.before_request
def _no_cache():
    g.NO_CACHE = True


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::track
# @reason analytics is intentionally route-local and covered through the owner dashboard workflow
def enabled():
    return bool(getattr(CONFIG, "ANALYTICS", False))


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason AI observability enablement is exercised through independent dashboard gates
def ai_enabled():
    return bool(getattr(CONFIG, "AI_OBSERVABILITY", False))


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason period parsing is dashboard-owned display behavior
def _period(value):
    return value if value in PERIODS else "7d"


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason route-local analytics window helper
def _period_start(period):
    now = datetime.now(timezone.utc)
    if period == "today":
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    return None


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_save_event
# @reason route-local event classification
def _route_prefix(path):
    parts = [p for p in (path or "/").split("/") if p]
    return parts[0] if parts else "home"


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_activity_details
# @reason action label presentation is route-local analytics view-model plumbing
def _action_label(action):
    return ACTION_LABELS.get(action, action.replace("_", " ").title())


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_dashboard
# @reason route icon lookup is dashboard-owned analytics view-model plumbing
def _route_icon(prefix):
    key = ROUTE_ICON_KEYS.get(prefix, prefix)
    return ".".join(key) if isinstance(key, tuple) else key or "analytics"


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_activity_details
# @reason analytics detail rows aggregate noisy event records by activity target
def _activity_key(event):
    action = event.get("action") or "view"
    identity = (
        event.get("entity_key")
        or event.get("entity_hash")
        or event.get("public_id")
        or event.get("path")
        or "/"
    )
    return (action, identity)


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_activity_details
# @reason analytics detail titles favor entity names but fall back to routes
def _activity_title(event):
    return event.get("page_title") or event.get("path") or "Untitled"


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_activity_details
# @reason analytics detail visitor labels compact user identity for grouped rows
def _visitor_label(event):
    return event.get("user_name") or event.get("user_email") or "Public visitor"


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::events
# @reason owner activity detail view intentionally summarizes event records instead of listing every hit
def _activity_details(events, limit=DETAIL_LIMIT):
    grouped = {}
    for event in events:
        key = _activity_key(event)
        if key not in grouped:
            action = event.get("action") or "view"
            grouped[key] = {
                "action": action,
                "action_label": _action_label(action),
                "title": _activity_title(event),
                "path": event.get("path") or "",
                "count": 0,
                "visitors": Counter(),
            }

        detail = grouped[key]
        detail["count"] += 1
        detail["visitors"][_visitor_label(event)] += 1

    details = []
    for detail in grouped.values():
        visitors = detail.pop("visitors")
        top_visitors = [
            {
                "name": name,
                "count": count,
                "label": f"{name} ({count})" if count > 1 else name,
            }
            for name, count in visitors.most_common(4)
        ]
        remaining = max(len(visitors) - len(top_visitors), 0)
        detail["visitors"] = top_visitors
        detail["remaining_visitors"] = remaining
        details.append(detail)

    details.sort(key=lambda detail: (-detail["count"], detail["title"].lower()))
    return details[:limit]


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::track
# @reason event write shape is covered by dashboard readback
def _save_event(data):
    if not enabled():
        return None

    path = data.get("path") or request.path
    if path.startswith("/analytics"):
        return None

    return analytics_database.create_event(
        {
            "created": datetime.now(timezone.utc),
            "action": data.get("action") or "view",
            "route_prefix": data.get("route_prefix") or _route_prefix(path),
            "path": path,
            "query": data.get("query") or "",
            "page_title": data.get("page_title") or "",
            "view_kind": data.get("view_kind") or "",
            "entity_key": data.get("entity_key") or "",
            "entity_hash": data.get("entity_hash") or "",
            "index": data.get("index") or "",
            "user_key": data.get("user_key") or "",
            "user_hash": data.get("user_hash") or "",
            "user_name": data.get("user_name") or "",
            "user_email": data.get("user_email") or "",
            "public_id": data.get("public_id") or "",
            "referrer": data.get("referrer") or "",
            "navigation_type": data.get("navigation_type") or "",
        }
    )


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_save_event
# @reason login events are a dashboard analytics signal and intentionally share route-local persistence
def record_login(user, provider=None):
    if not enabled() or not user:
        return

    _save_event(
        {
            "action": "login",
            "route_prefix": "users",
            "path": request.path,
            "page_title": "Login",
            "user_key": getattr(user, "urlsafe_key", ""),
            "user_hash": getattr(user, "hash", ""),
            "user_name": getattr(user, "name", ""),
            "user_email": getattr(user, "email", ""),
            "navigation_type": provider or "",
        }
    )


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason analytics queries intentionally live with the analytics route
def _events(period, prefix=None, limit=QUERY_LIMIT):
    events = analytics_database.events(start=_period_start(period), limit=limit)
    if prefix:
        events = [event for event in events if event.get("route_prefix") == prefix]
    return events


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason AI summary queries are dashboard-owned period-window plumbing
def _ai_records(period, limit=QUERY_LIMIT):
    return analytics_database.ai_observability_records(
        start=_period_start(period),
        limit=limit,
    )


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason owner-dashboard presentation projection for privacy-bounded live rows
def _inflight_ai_records(records, job_keys_by_telemetry=None):
    """Project privacy-bounded live generations without payload content."""
    rows = []
    now = datetime.now(timezone.utc)
    job_keys_by_telemetry = job_keys_by_telemetry or {}
    for record in records:
        if record.get("state") != "running":
            continue
        updated = record.get("updated") or record.get("created")
        if updated and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = max(int((now - updated).total_seconds()), 0) if updated else 0
        rows.append(
            {
                "workflow": record.get("workflow") or "unknown",
                "stage": record.get("stage") or "unknown",
                "provider_stage": record.get("active_provider_stage") or "unknown",
                "model": record.get("resolved_model") or "unknown",
                "requests": int(record.get("provider_requests") or 0),
                "age_seconds": age,
                "duration_seconds": max(
                    int(record.get("duration_ms") or 0) // 1000,
                    0,
                ),
                "job_type": record.get("deferred_job_type"),
                "attempt": record.get("deferred_job_attempt"),
                "telemetry_id": record.get("telemetry_id"),
                "job_key": job_keys_by_telemetry.get(record.get("telemetry_id")),
                "stale": age >= DEFERRED_JOB_HEARTBEAT_SECONDS * 2,
            }
        )
    rows.sort(key=lambda row: -row["age_seconds"])
    return rows[:50]


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::operation_diagnostic
# @reason displayed operation lookup is bounded by the dashboard cohort
def _recent_operation(key):
    for operation in DeferredJobs.recent(limit=250):
        if operation.get("key") == key:
            return operation
    abort(404)


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::clear_records
# @reason retention cutoff parsing is route-local analytics cleanup behavior
def _clear_cutoff(retention):
    option = CLEAR_RETENTION_OPTIONS.get(retention)
    if option is None:
        abort(400)

    days = option["days"]
    if days is None:
        return None

    return datetime.now(timezone.utc) - timedelta(days=days)


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::clear_records
# @reason key-only datastore cleanup is owned by the analytics retention route
def _delete_events(retention, batch_size=DELETE_BATCH_SIZE):
    return analytics_database.delete_events(
        before=_clear_cutoff(retention),
        batch_size=batch_size,
    )


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::clear_ai_records
# @reason key-only AI cleanup is owned by its dataset-specific retention route
def _delete_ai_records(retention, batch_size=DELETE_BATCH_SIZE):
    return analytics_database.delete_ai_observability(
        before=_clear_cutoff(retention),
        batch_size=batch_size,
    )


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::index
# @reason dashboard view model is route-local presentation logic
def _dashboard(events):
    action_counts = Counter(event.get("action") or "view" for event in events)
    known_users = {
        event.get("user_hash") or event.get("user_email")
        for event in events
        if event.get("user_hash") or event.get("user_email")
    }

    top_pages = Counter()
    for event in events:
        if event.get("action") == "login":
            continue
        label = event.get("page_title") or event.get("path") or "Untitled"
        top_pages[(event.get("path") or "/", label)] += 1

    grouped = defaultdict(list)
    for event in events:
        grouped[event.get("route_prefix") or "home"].append(event)

    groups = [
        {
            "prefix": prefix,
            "label": prefix.replace("-", " ").replace("_", " ").title(),
            "icon": _route_icon(prefix),
            "kind": ROUTE_KINDS.get(prefix, "page"),
            "count": len(prefix_events),
        }
        for prefix, prefix_events in grouped.items()
    ]
    groups.sort(key=lambda group: (-group["count"], group["prefix"]))

    return {
        "total": len(events),
        "page_views": action_counts.get("view", 0),
        "public_views": action_counts.get("public_view", 0),
        "logins": action_counts.get("login", 0),
        "known_users": len(known_users),
        "top_pages": [
            {"path": path, "title": title, "count": count}
            for (path, title), count in top_pages.most_common(8)
        ],
        "groups": groups,
    }


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_ai_dashboard_diagnostics_and_clear_use_real_routes
# @matrix ai-observability : ai-only independent-flags job-correlation
# @matrix analytics : dashboard page-tracking period-controls
# @pair deferred-jobs:diagnostics
@analytics.route("/", methods=["GET"])
@permission(Resource.SITE, Action.EDIT)
def index():
    analytics_enabled = enabled()
    ai_observability_enabled = ai_enabled()
    if not analytics_enabled and not ai_observability_enabled:
        abort(404)

    period = _period(request.args.get("period"))
    events = _events(period) if analytics_enabled else []
    ai_records = _ai_records(period) if ai_observability_enabled else []
    deferred_operations = (
        DeferredJobs.recent(limit=100) if ai_observability_enabled else []
    )
    job_keys_by_telemetry = {
        operation.get("telemetry_id"): operation.get("key")
        for operation in deferred_operations
        if operation.get("telemetry_id") and operation.get("key")
    }
    completed_ai_records = [
        record for record in ai_records if record.get("state") != "running"
    ]
    return (
        render_template(
            "analytics/index.html",
            analytics_enabled=analytics_enabled,
            ai_observability_enabled=ai_observability_enabled,
            dashboard=_dashboard(events) if analytics_enabled else None,
            ai_dashboard=(
                aggregate_records(completed_ai_records, query_limit=QUERY_LIMIT)
                if ai_observability_enabled
                else None
            ),
            ai_inflight=(
                _inflight_ai_records(
                    ai_records,
                    job_keys_by_telemetry=job_keys_by_telemetry,
                )
                if ai_observability_enabled
                else []
            ),
            deferred_operations=deferred_operations,
            period=period,
            periods=PERIODS,
            retention_options=CLEAR_RETENTION_OPTIONS,
            query_limit=QUERY_LIMIT,
        ),
        200,
    )


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_ai_dashboard_diagnostics_and_clear_use_real_routes
# @pairs ai-observability:job-correlation deferred-jobs:diagnostics
@analytics.route("/ai/operations/<job_id>.json", methods=["GET"])
@permission(Resource.SITE, Action.EDIT)
def operation_diagnostic(job_id):
    """Return one transferable, privacy-bounded job/provider snapshot."""
    if not ai_enabled():
        abort(404)

    operation = _recent_operation(job_id)
    records = _ai_records("all")
    return responses.json_response(
        operation_diagnostic_payload(operation, records, query_limit=QUERY_LIMIT)
    )


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
# @matrix analytics : accordion dashboard
@analytics.route("/events/<prefix>", methods=["GET"])
@permission(Resource.SITE, Action.EDIT)
def events(prefix):
    if not enabled():
        abort(404)

    period = _period(request.args.get("period"))
    return (
        render_template(
            "analytics/events.html",
            activities=_activity_details(_events(period, prefix=prefix)),
        ),
        200,
    )


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
# @matrix analytics : owner-filter retention-clear
@analytics.route("/clear/<retention>", methods=["DELETE"])
@permission(Resource.SITE, Action.EDIT)
def clear_records(retention):
    if not enabled():
        abort(404)

    deleted = _delete_events(retention)
    return responses.json_response(
        {
            "deleted": deleted,
            "retention": retention,
            "label": CLEAR_RETENTION_OPTIONS[retention]["label"],
        }
    )


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_ai_dashboard_diagnostics_and_clear_use_real_routes
# @pair ai-observability:independent-clear
@analytics.route("/ai/clear/<retention>", methods=["DELETE"])
@permission(Resource.SITE, Action.EDIT)
def clear_ai_records(retention):
    if not ai_enabled():
        abort(404)

    deleted = _delete_ai_records(retention)
    jobs_deleted = DeferredJobs.delete_terminal(before=_clear_cutoff(retention))
    return responses.json_response(
        {
            "dataset": "ai",
            "deleted": deleted,
            "jobs_deleted": jobs_deleted,
            "retention": retention,
            "label": CLEAR_RETENTION_OPTIONS[retention]["label"],
        }
    )


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
# @matrix analytics : owner-filter page-load
@analytics.route("/track", methods=["POST"])
def track():
    if not enabled():
        abort(404)

    data = request.get_json(silent=True) or {}
    action = data.get("action") or "view"
    if action in ("view", "public_view") and getattr(
        current_user, "is_admin", getattr(current_user, "is_owner", False)
    ):
        return responses.ok()

    if getattr(current_user, "is_authenticated", False):
        data.update(
            {
                "user_key": getattr(current_user, "urlsafe_key", ""),
                "user_hash": getattr(current_user, "hash", ""),
                "user_name": getattr(current_user, "name", ""),
                "user_email": getattr(current_user, "email", ""),
            }
        )

    _save_event(data)
    return responses.ok()
