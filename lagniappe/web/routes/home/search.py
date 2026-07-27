import math

from flask import abort, g, request
from flask_login import current_user

from lagniappe.core.definitions import Action, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, location
from lagniappe.web.auth import logged_in
from lagniappe.web import responses

from . import home


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


# @testable true
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_quick_create_command_requires_opt_in_and_create_permission
# @features search facets quick-create
# @dimensions permissions
def _can_quick_create(kind):
    creatable = CREATABLES.get(kind)
    if not creatable:
        return False
    return current_user.has_permission(creatable["resource"], Action.CREATE)


# @testable true
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_quick_create_command_requires_opt_in_and_create_permission
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_model_task_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_home_create_category_form_selector_quick_creates_form
# @pairs quick-create:command-row quick-create:opt-in quick-create:form-type
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


# @testable true
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_quick_create_uses_visible_uncategorized_pages_category
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_model_task_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_home_create_category_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_info_category_multiselect_quick_creates_category
# @pairs quick-create:created-option
def _index_result(entity):
    details = entity.details
    return {
        "id": details["id"],
        "kind": details["kind"],
        "name": details["name"],
        "details": details,
    }


# @testable true
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_category_search_permission_filter_returns_editable_categories
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_user_assign_search_permission_filter_returns_assignable_users
# @features search permissions
# @dimensions permission-filter category-edit assign
def _search_restrictions(kind):
    permission = request.values.get("permission")
    if not permission:
        return current_user.properties.restrictions.search
    if kind == "category" and permission == "edit":
        return current_user.properties.restrictions.category_edit_restrictions
    if kind == "user" and permission == "assign":
        return current_user.properties.restrictions.user_assign_restrictions
    abort(400)


# @testable true
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_quick_create_uses_visible_uncategorized_pages_category
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_project_combobox_quick_create_selects_new_project
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_model_task_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_home_create_category_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_info_category_multiselect_quick_creates_category
# @pairs quick-create:create-entity quick-create:default-category
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


# @testable true
# @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_page_acl_user_sees_one_page_on_category_index_home_and_search
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_quick_create_command_requires_opt_in_and_create_permission
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_project_combobox_quick_create_selects_new_project
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_model_task_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_home_create_category_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_info_category_multiselect_quick_creates_category
# @features search facets quick-create
# @dimensions search-results command-row
@home.route("/search-index/<kind>")
@logged_in
def index(kind):
    g.NO_CACHE = True
    preloaded_hashes = set(request.values.getlist("preload"))
    query = request.values.get("q", "")
    if len(query) < 1:
        return responses.index_results([])

    if kind != "internal":
        search_results = cache.kind_search(
            query,
            kind,
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

    if preloaded_hashes:
        results = [
            {"id": r["id"], "name": r["name"], "kind": r["kind"], "details": r}
            for r in cache.get_details_by_hash(preloaded_hashes).values()
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


# @testable true
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_quick_create_uses_visible_uncategorized_pages_category
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_project_combobox_quick_create_selects_new_project
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_model_task_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_home_create_category_form_selector_quick_creates_form
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_page_info_category_multiselect_quick_creates_category
# @pairs quick-create:create-route quick-create:created-option
@home.route("/search-index/<kind>/create", methods=["POST"])
@logged_in
def create_index(kind):
    if not _can_quick_create(kind):
        abort(403)

    try:
        entity = _quick_create_entity(kind, request.form)
    except ValueError as e:
        return responses.error(str(e))

    return responses.created_index_result(_index_result(entity))


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_manual_mode
# @tests tests_e2e/009_search/test_009a_search_page.py::test_navbar_task_results_handle_legacy_completed_values
# @pair projects:search
# @pair search:navbar-results
# @pair search:task-model
@home.route("/search-bar")
@logged_in
def search_bar():
    g.NO_CACHE = True
    q = request.values.get("q", "")
    if len(q) < 2:
        return responses.search_results(q, [], 0)

    results, total = cache.search(
        q,
        current_user.properties.restrictions.search,
        current_user.properties.restrictions.belongs_to,
    )

    return responses.search_results(q, results, total)


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_page_shows_query
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_no_results
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_result_titles
# @features search
# @dimensions query-display no-results result-title
@home.route("/search-page")
@logged_in
def search_page():
    g.NO_CACHE = True
    q = request.values.get("q", "")

    page = int(request.args.get("page", 0))
    results, total = _search_page_results(q, page, request.values.getlist("kind"))
    pagination = _search_page_pagination(page, results, total)

    return responses.search_page(q, results, pagination)


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_from_navbar
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_returns_results
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_no_results
# @features search
# @dimensions results no-results
def _search_page_results(q, page, kinds):
    return cache.search(
        q,
        current_user.properties.restrictions.search,
        current_user.properties.restrictions.belongs_to,
        kinds=kinds,
        page=page + 1,
    )


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_pagination_controls_visible
# @tests tests_e2e/009_search/test_009a_search_page.py::test_next_page
# @tests tests_e2e/009_search/test_009a_search_page.py::test_previous_page
# @features search
# @dimensions pagination pagination-next pagination-previous
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


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_resolve_location_query_first_hit_wins
# @tests tests_unit/test_003d_submission_location.py::test_resolve_location_query_retries_after_simplify
@home.route("/search-location")
@logged_in
def location_search():
    g.NO_CACHE = True
    query = request.values.get("q")

    results = location.search_places(query)

    return responses.location_results(results, len(results))
