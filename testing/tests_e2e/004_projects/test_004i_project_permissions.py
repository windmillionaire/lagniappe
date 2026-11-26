"""
Project permission tests for view, edit affordances, and model task creation.

Verified against:
- lagniappe/web/templates/projects/project.html
- lagniappe/web/templates/projects/info.html
- lagniappe/web/templates/projects/model_tasks.html
- lagniappe/web/routes/projects/main.py
"""

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import ModelTasks, Projects, Users
from testing.elements import (
    Filters,
    FormElements,
    ProjectFilterConditions,
    Tabs,
)
from testing.utility.network import manual_mutation_headers

pytestmark = pytest.mark.e2e


def test_project_url_rejects_model_task_key(get_admin, browser_failures):
    owner = get_admin()
    model = ModelTasks.test_create_model_task.get(owner)
    url = f"{SETTINGS.test_config['BASE_URL']}/projects/{model.key}"
    with browser_failures.expect_http_error(owner, status=404, path=url):
        response = owner.page.goto(url)
        assert response.status == 404
        expect(owner.page).to_have_title("Error 404")


def test_project_is_forbidden_without_model_permission(get_admin, get_user, browser_failures):
    owner = get_admin()
    project = Projects.test_create_project_manual_mode.get(owner)

    blocked = get_user(Users.user_no_access)
    with browser_failures.expect_http_error(blocked, status=403, path=project.url):
        blocked.navigate(project.url)
        expect(blocked.page).to_have_title("Error 403")


def test_project_viewer_reads_project_without_editing_controls(get_admin, get_user):
    owner = get_admin()
    model_task = ModelTasks.test_create_model_task.get(owner)
    project = model_task.project

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)
    model_task.user = viewer

    expect(viewer.locate("[lp-view]")).to_have_attribute("data-can-edit", "false")
    expect(viewer.locate(project.PROJECT_TITLE)).to_contain_text(
        project.definition.name
    )
    description_el = viewer.locate(project.PROJECT_DESCRIPTION)
    expect(description_el).to_have_attribute("data-editable", "false")
    expect(description_el).to_contain_text(project.definition.description)
    expect(viewer.locate(project.CREATE_MODEL_BUTTON)).not_to_be_attached()

    project.user = viewer
    menu = project.open_actions_menu()
    expect(menu.locator("[data-project-action='rename']")).not_to_be_attached()
    expect(menu.locator("[data-project-action='description']")).not_to_be_attached()
    viewer.page.keyboard.press("Escape")

    model_info = model_task.open_info()
    expect(model_info.locator("#name")).to_contain_text("Name")
    expect(model_info.locator("#name")).to_contain_text(model_task.definition.name)
    expect(model_info.locator(FormElements.NAME)).not_to_be_attached()
    expect(model_task.element.locator(model_task.TITLE)).to_contain_text(
        model_task.definition.name
    )
    expect(model_task.element.locator(model_task.TITLE)).not_to_contain_text(
        "undefined"
    )

    filters = Filters(viewer, project)
    expect(filters.form).to_have_attribute("data-can-edit", "false")
    expect(filters.save_button).not_to_be_attached()
    expect(filters.add_trigger).to_be_visible()
    filters.open_add_popover()
    expect(filters.field_option(ProjectFilterConditions.NAME.value)).to_be_visible()


# @template projects/project.html::main
def test_project_viewer_can_read_document_content(get_admin, get_user):
    owner = get_admin()
    empty_project = Projects.test_readonly_document_visibility.get(owner)
    content_project = Projects.test_readonly_document_content.get(owner)

    viewer = get_user(Users.general_models_view_only)
    viewer.go(empty_project)

    expect(viewer.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).not_to_be_attached()
    expect(viewer.locate(Tabs.DOCUMENT_TAB)).not_to_be_attached()

    marker = "Readonly project document content marker"
    if marker not in (content_project.entity.properties.document.html or ""):
        content_project.entity.properties.document.save(
            html=f"<p>{marker}</p>",
            ydoc=None,
        )
        content_project.entity.save()

    viewer.go(content_project)

    expect(viewer.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).to_be_visible()
    document = Tabs(viewer).document
    expect(document).to_be_visible()
    expect(document).to_contain_text(marker)


def test_project_editor_can_open_model_task_creation(get_admin, get_user):
    owner = get_admin()
    project = Projects.test_create_project_manual_mode.get(owner)

    editor = get_user(Users.admin)
    editor.go(project)

    create_form = project.create_model_task_form()
    expect(create_form).to_be_visible()
    expect(create_form.locator(FormElements.NAME)).to_be_visible()
    expect(create_form.locator("[data-role='form-select']")).to_be_visible()


def test_model_task_mutations_require_route_project_membership(get_admin):
    owner = get_admin()
    route_project = Projects.test_create_project_manual_mode.get(owner)
    foreign_model = ModelTasks.test_multi_model_alpha.get(owner)
    assert foreign_model.entity.project.key != route_project.entity.key

    owner.go(route_project)
    cookies = {
        cookie["name"]: cookie["value"] for cookie in owner.page.context.cookies()
    }
    headers = manual_mutation_headers(
        owner.page.url,
        owner.locate("#token").input_value(),
    )
    original_name = foreign_model.entity.name
    base_url = SETTINGS.test_config["BASE_URL"]

    update_response = requests.put(
        f"{base_url}/projects/{route_project.key}/update-model/{foreign_model.key}",
        data={"name": "Forged cross-project update"},
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert update_response.status_code == 404
    assert update_response.text == "Model task not found"

    delete_response = requests.delete(
        f"{base_url}/projects/{route_project.key}/delete-model/{foreign_model.key}",
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert delete_response.status_code == 404
    assert delete_response.text == "Model task not found"

    persisted = Entities.fetch_one(foreign_model.key, request=Fetch.direct())
    assert persisted is not None
    assert persisted.name == original_name
    assert persisted.project.key == foreign_model.entity.project.key
