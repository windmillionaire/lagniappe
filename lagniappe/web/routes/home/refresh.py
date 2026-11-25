"""Batched collection refresh with cached-fingerprint comparisons."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import get_template_attribute, request

from lagniappe.core import exceptions
from lagniappe.core.tools.polling.refresh import (
    MAX_REFRESH_ROWS,
    RefreshFallback,
    load_refresh_collection,
    load_refresh_view,
    resolve_refresh_delta,
)
from lagniappe.web import responses
from lagniappe.web.auth import authenticated_user, logged_in

from . import internal


MAX_REFRESH_TARGETS = 32


def _fallback(target):
    target_id = target.get("id") if isinstance(target, dict) else None
    return {"id": target_id, "fallback": True}


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


def _refresh_target(view, target, refresh_view):
    collection = load_refresh_collection(view, target, authenticated_user(), refresh_view)
    delta = resolve_refresh_delta(
        collection, target.get("rows"), authenticated_user(),
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


@internal.route("/refresh", methods=["POST"])
@logged_in
def refresh() -> ResponseReturnValue:
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
        refresh_view = load_refresh_view(view, authenticated_user())
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
