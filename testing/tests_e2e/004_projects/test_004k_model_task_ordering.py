"""Project model-order controls save without replacing open editor state."""

from uuid import uuid4

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Forms, SubmissionFields, Users
from testing.definitions.project_definitions import ProjectDefinition
from testing.resources.project import Project
from testing.utility.network import expect_successful_response, manual_mutation_headers

pytestmark = pytest.mark.e2e


def _ordered_project(owner):
    project = Project(definition=ProjectDefinition(
        name=f"Model ordering {uuid4().hex[:8]}", description="Preserve Project description",
    ))
    project.user = owner
    project.create()
    form = Forms.test_alternate_task_form.get(owner)
    models = [Entities.MODEL_TASK.create(project.entity, {
        "name": name, "form": form.entity if name == "Beta" else None,
    }) for name in ("Alpha", "Beta", "Gamma")]
    Entities.save(*models)
    return project, models, form


# @matrix model-tasks : ordering persistence
# @template projects/model_tasks.html::model_task_list
# @template projects/model_tasks.html::model_task
def test_model_task_arrows_preserve_open_edits_and_saved_order(get_user):
    owner = get_user(Users.OWNER)
    project, models, form = _ordered_project(owner)
    owner.go(project)
    expect(owner.locate("[data-widget='ModelTaskList']")).to_have_attribute("loaded", "")
    rows = owner.locate("[data-widget='ModelTaskList'] > li[lp-entity]")
    titles = rows.locator("[data-role='header'] > [data-role='title']")
    expect(titles).to_have_text(["Alpha", "Beta", "Gamma"])
    expect(rows.get_by_role("button", name="Move Alpha up", exact=True)).to_be_disabled()
    expect(rows.get_by_role("button", name="Move Gamma down", exact=True)).to_be_disabled()

    beta = owner.locate(f"li[data-key='{models[1].urlsafe_key}']")
    beta.locator("[data-role='header'] > [data-role='title']").click()
    expect(beta.locator("[data-widget='ModelTaskInfo']")).to_be_visible()
    name = SubmissionFields.INPUT.get("name", submission_value="Beta")
    assert name.verify_submission_value(beta.locator("[data-widget='ModelTaskInfo']"))
    name.value = "Unsaved Beta name"
    draft = beta.locator("[data-widget='ModelTaskInfo'] input[name='name']")
    with expect_successful_response(owner.page, method="PUT", path=f"/projects/{project.key}/reorder-models"):
        rows.get_by_role("button", name="Move Alpha down", exact=True).click()
    expect(titles).to_have_text(["Beta", "Alpha", "Gamma"])
    expect(draft).to_have_value("Unsaved Beta name")
    expect(beta.get_by_role("button", name="Move Beta up", exact=True, include_hidden=True)).to_be_disabled()
    with expect_successful_response(owner.page, method="PUT", path=f"/projects/{project.key}/reorder-models"):
        rows.get_by_role("button", name="Move Alpha down", exact=True).click()
    expect(titles).to_have_text(["Beta", "Gamma", "Alpha"])
    expect(draft).to_have_value("Unsaved Beta name")

    owner.go(project)
    expect(titles).to_have_text(["Beta", "Gamma", "Alpha"])
    expect(rows.get_by_role("button", name="Move Alpha down", exact=True)).to_be_disabled()
    saved = Entities.fetch_one(models[1].key, request=Fetch.direct())
    assert saved.name == "Beta"
    assert saved.form.key == form.entity.key
    assert Entities.fetch_one(project.entity.key, request=Fetch.root()).description == "Preserve Project description"


# @matrix model-tasks : permission-gates parent-membership ordering
# @template projects/model_tasks.html::model_task
def test_model_order_rejects_invalid_membership_and_readonly_users(get_user):
    owner = get_user(Users.OWNER)
    project, models, _form = _ordered_project(owner)
    foreign_project = Project(definition=ProjectDefinition(name=f"Other project {uuid4().hex[:8]}"))
    foreign_project.user = owner
    foreign_project.create()
    foreign = Entities.MODEL_TASK.create(foreign_project.entity, {"name": "Foreign model"})
    foreign.save()
    owner.go(project)
    url = f"{SETTINGS.test_config['BASE_URL']}/projects/{project.key}/reorder-models"
    cookies = {cookie["name"]: cookie["value"] for cookie in owner.page.context.cookies()}
    headers = manual_mutation_headers(owner.page.url, owner.locate("#token").input_value())
    keys = [model.urlsafe_key for model in models]
    for ordering in (keys[:-1], [keys[0], keys[0], keys[2]], [*keys[:-1], foreign.urlsafe_key]):
        response = requests.put(url, json={"model_tasks": ordering}, cookies=cookies, headers=headers, timeout=10)
        assert response.status_code == 422
    assert [Entities.fetch_one(model.key, request=Fetch.root()).order for model in models] == [1, 2, 3]

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)
    expect(viewer.locate("[data-widget='ModelTaskList'] [data-role='move-model']")).to_have_count(0)
    cookies = {cookie["name"]: cookie["value"] for cookie in viewer.page.context.cookies()}
    headers = manual_mutation_headers(viewer.page.url, viewer.locate("#token").input_value())
    response = requests.put(url, json={"model_tasks": list(reversed(keys))}, cookies=cookies, headers=headers, timeout=10)
    assert response.status_code == 403
    assert [Entities.fetch_one(model.key, request=Fetch.root()).order for model in models] == [1, 2, 3]
