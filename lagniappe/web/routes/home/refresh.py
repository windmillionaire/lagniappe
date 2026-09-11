"""Batched collection refresh with cached-fingerprint comparisons."""

from flask import get_template_attribute, request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.tools.polling.refresh import (
    MAX_REFRESH_ROWS,
    RefreshFallback,
    load_refresh_collection,
    load_refresh_view,
    resolve_refresh_delta,
)
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import internal


MAX_REFRESH_TARGETS = 32


# @testable false
# @covered-by lagniappe/web/routes/home/refresh.py::refresh
# @reason per-target fallback envelopes are owned by the public refresh route
def _fallback(target):
    target_id = target.get("id") if isinstance(target, dict) else None
    return {"id": target_id, "fallback": True}


# @testable false
# @covered-by lagniappe/web/routes/home/refresh.py::refresh
# @reason target-specific template rendering is exercised through the refresh route
def _render_upserts(collection, entities):
    if collection.kind == "page-tasks":
        render = get_template_attribute("pages/tasks.html", "task")
        return [
            {
                "key": entity.urlsafe_key,
                "html": render(entity, collection.parent).strip(),
            }
            for entity in entities
        ]

    render = get_template_attribute("table.html", "row")
    return [
        {
            "key": entity.urlsafe_key,
            "html": render(
                entity.user if collection.kind == "user-index" else entity,
                collection.parent,
            ).strip(),
        }
        for entity in entities
    ]


# @testable false
# @covered-by lagniappe/web/routes/home/refresh.py::refresh
# @reason empty-state rendering is exercised through the refresh route
def _render_empty(collection, order):
    if order:
        return None
    if collection.kind == "page-tasks":
        render = get_template_attribute("pages/tasks.html", "task_empty")
        return render(collection.parent).strip()
    empty_macro = (
        "empty_row_filter"
        if collection.kind.startswith("filtered-")
        else "empty_row_index"
    )
    render = get_template_attribute("table.html", empty_macro)
    return render(collection.parent).strip()


# @testable false
# @covered-by lagniappe/web/routes/home/refresh.py::refresh
# @reason target orchestration is owned by the public batched route
def _refresh_target(view, target, refresh_view):
    collection = load_refresh_collection(view, target, current_user, refresh_view)
    delta = resolve_refresh_delta(
        collection, target.get("rows"), current_user,
        reauthorize=refresh_view.reauthorize,
    )
    return {
        "id": target["id"],
        "fallback": False,
        "upsert": _render_upserts(collection, delta.upsert),
        "remove": list(delta.remove),
        "order": list(delta.order),
        "empty": _render_empty(collection, delta.order),
    }


# @testable true
# @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_reconnect_refreshes_external_page
# @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_project_filter_results_respect_task_permissions
# @matrix reconnect-refresh : batched-request category-index component-identity fallback page-tasks root-fingerprint
# @pairs category-index:refresh permissions:authorization
@internal.route("/refresh", methods=["POST"])
@logged_in
def refresh():
    """Return permission-checked row deltas for supported mounted collections."""
    payload = request.get_json(silent=True) or {}
    view = payload.get("view")
    targets = payload.get("targets")
    if (
        not isinstance(view, dict)
        or not isinstance(targets, list)
        or len(targets) > MAX_REFRESH_TARGETS
    ):
        return responses.error("Invalid refresh targets.")

    try:
        refresh_view = load_refresh_view(view, current_user)
    except RefreshFallback:
        return responses.json_response(
            {"targets": [_fallback(target) for target in targets]}
        )
    except Exception as error:
        exceptions.capture(error, context={"operation": "refresh-view"})
        return responses.json_response(
            {"targets": [_fallback(target) for target in targets]}
        )

    # Form tables use full fragments; their rows cannot change independently
    # of the Forms collection revision.
    if view.get("index") == "forms" and refresh_view.matches(view):
        return responses.json_response(
            {"fingerprint": refresh_view.fingerprint,
             "authorization": refresh_view.authorization,
             "collection_revision": refresh_view.collection_revision, "targets": []}
        )

    refreshed = []
    for target in targets:
        try:
            if not isinstance(target, dict) or not isinstance(target.get("id"), str):
                raise RefreshFallback("Invalid refresh target identity")
            rows = target.get("rows")
            if isinstance(rows, list) and len(rows) > MAX_REFRESH_ROWS:
                raise RefreshFallback("Refresh row limit exceeded")
            refreshed.append(_refresh_target(view, target, refresh_view))
        except RefreshFallback:
            refreshed.append(_fallback(target))
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "operation": "refresh-target",
                    "component": (
                        target.get("id") if isinstance(target, dict) else None
                    ),
                },
            )
            refreshed.append(_fallback(target))

    return responses.json_response(
        {"fingerprint": refresh_view.fingerprint,
         "authorization": refresh_view.authorization,
         "collection_revision": refresh_view.collection_revision, "targets": refreshed}
    )
