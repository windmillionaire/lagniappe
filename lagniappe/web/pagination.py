"""Parse the browser controls accepted by collection indexes."""

from flask import request

from lagniappe.core.entities.index import CollectionOptions


def pagination_options() -> CollectionOptions:
    return {
        "cursor": request.values.get("cursor"),
        "limit": request.values.get("limit", 25, type=int),
    }
