from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

import math

from flask import abort, g, request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, collaboration
from lagniappe.core.tools.services import places as location
from lagniappe.web.auth import authenticated_user, logged_in
from lagniappe.web import responses

from . import internal


CREATABLES = {
    "category": {
        "resource": Resource.MODELS,
        "title": "Category",
    },
    "form": {
        "resource": Resource.FORMS,
        "title": "Form",
    },
    "page": {
        "resource": Resource.MODELS,
        "title": "Page",
    },
    "project": {
        "resource": Resource.PROJECTS,
        "title": "Project",
    },
}
FORM_TYPES = {"page", "task"}


def _can_quick_create(kind):
    creatable = CREATABLES.get(kind)
    if not creatable:
        return False
    return current_user.has_permission(creatable["resource"], Action.CREATE)


def _quick_create_command(kind, query):
    name = query.strip()
    if request.values.get("creatable") != "true" or not name:
        return None
    if not _can_quick_create(kind):
        return None
    if kind == "form" and request.values.get("form-type") not in FORM_TYPES:
        return None

    creatable = CREATABLES[kind]
    return {
        "kind": kind,
        "name": name,
        "title": creatable["title"],
    }


def _index_result(entity):
    details = entity.details
    return {
        "id": details["id"],
        "kind": details["kind"],
        "name": details["name"],
        "details": details,
    }


def _search_restrictions(kind):
    permission = request.values.get("permission")
    if not permission:
        return current_user.properties.restrictions.search
    if kind == "administrator" and permission == "administrator":
        if not current_user.is_owner:
            abort(403)
        return current_user.properties.restrictions.search
    if kind == "category" and permission == "edit":
        return current_user.properties.restrictions.category_edit_restrictions
    if kind == "user" and permission == "assign":
        return current_user.properties.restrictions.user_assign_restrictions
    if kind == "user" and permission in {"message", "mention"}:
        if not collaboration.managed_user(current_user):
            abort(403)
        if permission == "mention":
            document = Entities.fetch_one(
                request.values.get("document"), request=Fetch.root()
            )
            if not document or not document.allowed(Action.VIEW, user=current_user):
                abort(403)
        return current_user.properties.restrictions.user_message_restrictions
    abort(400)


def _administrator_results(results):
    """Keep the role selector limited to ordinary managed-user pages."""
    pages = {
        page.urlsafe_key: page
        for page in Entities.fetch(
            *[result.get("id") for result in results if result.get("id")],
            request=Fetch.direct(),
        )
        if isinstance(page, Entities.PAGE) and page.user
    }
    return [
        result
        for result in results
        if (page := pages.get(result.get("id")))
        and page.user is not None
        and not page.user.is_public
        and not page.user.is_admin
    ]


def _quick_create_entity(kind, form):
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    if kind == "category":
        entity = Entities.CATEGORY.create({"name": name})
    elif kind == "form":
        form_type = form.get("form-type")
        if form_type not in FORM_TYPES:
            raise ValueError("form-type must be page or task")
        entity = Entities.FORM.create({"name": name, "form-type": form_type})
    elif kind == "page":
        category = Entities.CATEGORY.get_uncategorized_pages()
        entity = Entities.PAGE.create({"name": name, "model": category})
    elif kind == "project":
        entity = Entities.PROJECT.create({"name": name})
    else:
        raise ValueError("kind is not quick-creatable")

    entity.save()
    return entity


@internal.route("/search-index/<kind>")
@logged_in
def index(kind: str) -> ResponseReturnValue:
    g.NO_CACHE = True
    preloaded_hashes = set(request.values.getlist("preload"))
    query = request.values.get("q", "")
    if len(query) < 1:
        return responses.index_results([])

    search_kind = "user" if kind == "administrator" else kind
    if kind != "internal":
        search_results = cache.kind_search(
            query,
            search_kind,
            _search_restrictions(kind),
            current_user.properties.restrictions.belongs_to,
            form_type=request.values.get("form-type"),
            models=request.values.get("models") != "false",
            include_users=request.values.get("include-users") != "false",
        )
    else:
        search_results = cache.entity_search(
            query,
            _search_restrictions(kind),
            current_user.properties.restrictions.belongs_to,
        )

    search_results = collaboration.collaboration_user_results(
        search_results,
        query,
        request.values.get("permission", ""),
        authenticated_user(),
        document_identifier=request.values.get("document"),
    )
    if kind == "administrator":
        search_results = _administrator_results(search_results)

    if preloaded_hashes:
        results = [
            {"id": r["id"], "name": r["name"], "kind": r["kind"], "details": r}
            for r in cache.get_details_by_hash(preloaded_hashes).values()
            if "id" in r and "kind" in r and "name" in r
        ]
    else:
        results = []

    real_result_count = len(search_results)

    for r in search_results:
        if r["details"].get("hash") not in preloaded_hashes:
            results.append(r)

    create_command = (
        _quick_create_command(kind, query) if real_result_count == 0 else None
    )

    return responses.index_results(results, create_command=create_command)


@internal.route("/search-index/<kind>/create", methods=["POST"])
@logged_in
def create_index(kind: str) -> ResponseReturnValue:
    if not _can_quick_create(kind):
        abort(403)

    try:
        entity = _quick_create_entity(kind, request.form)
    except ValueError as e:
        return responses.error(str(e))

    return responses.created_index_result(_index_result(entity))


@internal.route("/search-bar")
@logged_in
def search_bar() -> ResponseReturnValue:
    g.NO_CACHE = True
    q = request.values.get("q", "")
    if len(q) < 2:
        return responses.search_results(q, [], 0)

    results, total = cache.search(
        q,
        current_user.properties.restrictions.search,
        current_user.properties.restrictions.belongs_to,
        include_help=True,
    )

    return responses.search_results(q, results, total)


@internal.route("/search-page")
@logged_in
def search_page() -> ResponseReturnValue:
    g.NO_CACHE = True
    q = request.values.get("q", "")

    page = int(request.args.get("page", 0))
    results, total = _search_page_results(q, page, request.values.getlist("kind"))
    pagination = _search_page_pagination(page, results, total)

    return responses.search_page(q, results, pagination)


def _search_page_results(q, page, kinds):
    return cache.search(
        q,
        current_user.properties.restrictions.search,
        current_user.properties.restrictions.belongs_to,
        kinds=kinds,
        page=page + 1,
        include_help=True,
    )


def _search_page_pagination(page, results, total, per_page=10):
    previous_page = None if page == 0 else page - 1
    next_page = page + 1 if math.floor(total / per_page) >= page + 1 else None
    last_result = page * per_page + len(results)

    return {
        "showing": page * per_page + 1,
        "to": last_result,
        "total": total,
        "previous": previous_page if isinstance(previous_page, int) else None,
        "next": (
            next_page if isinstance(next_page, int) and last_result < total else None
        ),
    }


@internal.route("/search-location")
@logged_in
def location_search() -> ResponseReturnValue:
    g.NO_CACHE = True
    query = request.values.get("q")

    results = location.search_places(query)

    return responses.location_results(results, len(results))
