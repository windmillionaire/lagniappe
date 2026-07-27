import re
from urllib.parse import quote
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.entities.category import UNCATEGORIZED_PAGES_NAME
from testing.definitions import Categories, Pages, Projects, SitePages, Users
from testing.elements import (
    FormElements,
    FormSelect,
    ProjectSelect,
    Select,
    SpinnerButtons,
)

pytestmark = pytest.mark.e2e


def _unique(label):
    return f"test-quick-create-{label}-{uuid4().hex[:8]}"


def _fetch_json(user, path, method="GET", data=None):
    return user.page.evaluate(
        """async ({ path, method, data }) => {
            const csrfMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
            const bodyMethods = new Set(["POST", "PUT", "PATCH"]);
            const formBody = () => {
                const body = new FormData();
                for (const [key, value] of Object.entries(data || {})) {
                    body.append(key, value);
                }
                return body;
            };
            const send = async () => {
                const headers = { "X-Lagniappe-Request": "true" };
                if (csrfMethods.has(method)) {
                    headers["X-CSRFToken"] =
                        document.getElementById("token")?.value || "";
                }
                return fetch(path, {
                    method,
                    credentials: "include",
                    headers,
                    body: bodyMethods.has(method) ? formBody() : undefined,
                });
            };

            let response = await send();
            if (response.status === 400 && csrfMethods.has(method)) {
                const tokenResponse = await fetch("/token");
                const token = await tokenResponse.text();
                const tokenElt = document.getElementById("token");
                if (tokenElt) tokenElt.value = token;
                response = await send();
            }

            const text = await response.text();
            return {
                status: response.status,
                json: text ? JSON.parse(text) : null,
                text,
            };
        }""",
        {"path": path, "method": method, "data": data or {}},
    )


def _quick_create_option(user, panel, label, name, response_glob):
    option = panel.get_by_role(
        "option",
        name=f"Add New {label}: {name}",
        exact=True,
    )
    expect(option).to_be_visible()

    with user.page.expect_response(response_glob):
        option.click()


def _quick_create_from_select_button(user, select_button, label, name, response_glob):
    panel = select_button.panel(fill=name)
    _quick_create_option(user, panel, label, name, response_glob)
    expect(select_button.button).to_contain_text(name)


def _quick_create_from_combobox(user, combobox, label, name, response_glob):
    panel = combobox.open()
    combobox.input.fill(name)
    _quick_create_option(user, panel, label, name, response_glob)
    expect(combobox.input).to_have_attribute("placeholder", re.compile(re.escape(name)))


# @features search facets quick-create
# @dimensions command-row opt-in permissions search-results
def test_quick_create_command_requires_opt_in_and_create_permission(get_user):
    owner = get_user(Users.OWNER)
    owner.go(SitePages.HOME)
    query = _unique("project-command")

    opted_in = _fetch_json(
        owner,
        f"/search-index/project?q={quote(query)}&creatable=true",
    )
    assert opted_in["status"] == 200
    assert f"Add New Project: {query}" in opted_in["json"]["results"]

    lookup_only = _fetch_json(owner, f"/search-index/project?q={quote(query)}")
    assert lookup_only["status"] == 200
    assert "Add New Project" not in lookup_only["json"]["results"]
    assert "No Results" in lookup_only["json"]["results"]

    viewer = get_user(Users.general_models_view_only, creator=owner)
    viewer.go(SitePages.HOME)
    denied = _fetch_json(
        viewer,
        f"/search-index/project?q={quote(query)}&creatable=true",
    )
    assert denied["status"] == 200
    assert "Add New Project" not in denied["json"]["results"]
    assert "No Results" in denied["json"]["results"]


# @features search permissions
# @dimensions permission-filter category-edit
def test_category_search_permission_filter_returns_editable_categories(get_user):
    owner = get_user(Users.OWNER)
    allowed = Categories.acl_create_allowed.get(owner)
    denied = Categories.acl_create_denied.get(owner)

    user = get_user(Users.single_category_create)
    user.go(SitePages.HOME)

    response = _fetch_json(
        user,
        f"/search-index/category?q={quote('acl')}&permission=edit",
    )

    assert response["status"] == 200
    html = response["json"]["results"]
    assert allowed.name in html
    assert denied.name not in html


# @features search permissions
# @dimensions permission-filter assign
def test_user_assign_search_permission_filter_returns_assignable_users(get_user):
    owner = get_user(Users.OWNER)
    assignable = get_user(Users.assignable_user, creator=owner)
    denied = get_user(Users.create_user, creator=owner)

    assigner = get_user(Users.specific_user_assigner, creator=owner)
    assigner.go(SitePages.HOME)

    response = _fetch_json(
        assigner,
        f"/search-index/user?q={quote('User')}&permission=assign",
    )

    assert response["status"] == 200
    html = response["json"]["results"]
    assert assignable.definition.name in html
    assert denied.definition.name not in html


# @features quick-create
# @dimensions create-route created-option create-entity default-category
def test_page_quick_create_uses_visible_uncategorized_pages_category(get_user):
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    first = _fetch_json(
        user,
        "/search-index/page/create",
        method="POST",
        data={"name": _unique("page-one")},
    )
    second = _fetch_json(
        user,
        "/search-index/page/create",
        method="POST",
        data={"name": _unique("page-two")},
    )

    assert first["status"] == 200
    assert second["status"] == 200

    first_page = Entities.fetch_one(
        first["json"]["option"]["id"], request=Fetch.direct()
    )
    second_page = Entities.fetch_one(
        second["json"]["option"]["id"], request=Fetch.direct()
    )

    assert first_page.model.name == UNCATEGORIZED_PAGES_NAME
    assert first_page.model.reserved is False
    assert second_page.model.key == first_page.model.key


# @features quick-create
# @dimensions create-route created-option create-entity
# @template pages/tasks.html::action_buttons
def test_project_combobox_quick_create_selects_new_project(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_create_page_task.get(user)
    user.go(page)
    project_name = _unique("project-combobox")

    create_form = page.create_task_form
    project_select = ProjectSelect(create_form)
    _quick_create_from_select_button(
        user,
        project_select,
        "Project",
        project_name,
        "**/search-index/project/create",
    )

    expect(project_select.button).to_contain_text(project_name)


# @features quick-create
# @dimensions create-route created-option create-entity form-type
# @template projects/model_tasks.html::create_model_task
def test_model_task_form_selector_quick_creates_form(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_create_model_task.get(user)
    user.go(project)

    model_task_name = _unique("model-task")
    form_name = _unique("model-task-form")

    create_form = project.create_model_task_form()
    create_form.locator(FormElements.NAME).fill(model_task_name)
    _quick_create_from_select_button(
        user,
        FormSelect(create_form),
        "Form",
        form_name,
        "**/search-index/form/create",
    )

    with user.page.expect_response("**/create-model"):
        SpinnerButtons.CREATE.click(create_form)

    saved_project = Entities.fetch_one(project.key, request=Fetch.direct())
    model_task = next(t for t in saved_project.model_tasks if t.name == model_task_name)
    assert model_task.form.name == form_name
    assert model_task.form.form_type == "task"


# @features quick-create
# @dimensions create-route created-option create-entity form-type
# @template home/categories.html::create
def test_home_create_category_form_selector_quick_creates_form(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    category_name = _unique("category")
    form_name = _unique("category-form")

    create_form = home.create_category_form()
    create_form.locator(FormElements.NAME).fill(category_name)
    _quick_create_from_select_button(
        user,
        FormSelect(create_form),
        "Form",
        form_name,
        "**/search-index/form/create",
    )

    with user.page.expect_response("**/categories/create") as response_info:
        SpinnerButtons.CREATE.click(create_form)

    category_key = home.entity_key_from_response(response_info.value)
    category = Entities.fetch_one(category_key, request=Fetch.direct())
    assert category.form.name == form_name
    assert category.form.form_type == "page"


# @features quick-create
# @dimensions create-route created-option create-entity
# @template pages/info.html::info_form
def test_page_info_category_multiselect_quick_creates_category(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_category_edit_page)
    category_name = _unique("page-info-category")
    original_page = Entities.fetch_one(page.key, request=Fetch.direct())
    original_categories = original_page.categories
    original_category_ids = {category.details["id"] for category in original_categories}
    original_category_names = {category.name for category in original_categories}

    info_form = page.info_form
    category_select = Select(info_form.locator("[data-role='categories']"))
    _quick_create_from_combobox(
        user,
        category_select,
        "Category",
        category_name,
        "**/search-index/category/create",
    )
    placeholder = category_select.placeholder
    assert category_name in placeholder
    assert original_category_names <= set(placeholder.split(", "))

    selected_ids = info_form.locator("select[name='category']").evaluate(
        "(select) => Array.from(select.selectedOptions).map((option) => option.value)"
    )
    assert original_category_ids <= set(selected_ids)
    category_select.input.press("Escape")

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(info_form)

    saved_page = Entities.fetch_one(page.key, request=Fetch.direct())
    saved_category_names = {category.name for category in saved_page.categories}
    assert original_category_names <= saved_category_names
    assert category_name in saved_category_names
