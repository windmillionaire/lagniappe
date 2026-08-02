"""
Tests for project info tab functionality.

Tests project info editing and attribute management.
Verified against:
- lagniappe/web/templates/projects/info.html
- src/script/widgets/projectInfo.mjs (ProjectInfo)
- lagniappe/web/routes/projects/main.py
"""

import re
from urllib.parse import urljoin
from uuid import uuid4

import requests
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, SubmissionFields, Users
from testing.elements import SpinnerButtons, Attributes, Tabs
from testing.utility import expect_poll_result, expect_successful_response


# @features projects
# @dimensions info-form update metadata-sync
# @template projects/project.html::view_header
# @template projects/info.html::info_tab
def test_project_info_form(get_user):
    """Test that project info form can be edited."""
    user = get_user(Users.OWNER)
    project = Projects.test_project_info_form.get(user)
    user.go(project)
    expect(user.page.get_by_role("button", name="Project actions")).to_be_visible()

    new_name = "Apples"
    new_description = "Apples are mad tasty."

    info_form = project.info_form

    name = SubmissionFields.INPUT.get("name", submission_value=project.definition.name)
    assert name.verify_submission_value(info_form)

    description = SubmissionFields.TEXTAREA.get(
        "description", submission_value=project.definition.description
    )
    assert description.verify_submission_value(info_form)

    name.value = new_name
    description.value = new_description

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(info_form)

    new_info_form = project.info_form
    new_name_field = SubmissionFields.INPUT.get("name", submission_value=new_name)
    assert new_name_field.verify_submission_value(new_info_form)

    new_description_field = SubmissionFields.TEXTAREA.get(
        "description", submission_value=new_description
    )
    assert new_description_field.verify_submission_value(new_info_form)

    title = user.locate(project.PROJECT_TITLE)
    expect(title).to_contain_text(new_name)

    description = user.locate(project.PROJECT_DESCRIPTION)
    expect(description).to_contain_text(new_description)


# @pairs edited-entity-notice:timestamp-only edited-entity-notice:replacement
# @pairs edited-entity-notice:info-form edited-entity-notice:side-effect-free
# @pairs projects:timestamp-only projects:replacement projects:info-form
# @pair projects:side-effect-free
# @template projects/info.html::info_form
def test_project_info_replacement_is_side_effect_free_for_timestamp_only_revision(
    get_user,
):
    owner = get_user(Users.OWNER)
    project = Projects.test_project_info_form.get(owner)
    owner.go(project)

    timestamp_only = Entities.fetch_one(project.key, request=Fetch.direct())
    timestamp_only.properties.modified.update()
    timestamp_only.save()
    modified_before_probe = timestamp_only.modified
    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in owner.page.context.cookies()
    }
    replacement = requests.get(
        urljoin(owner.page.url, f"/projects/{project.key}/info/replace"),
        cookies=cookies,
        timeout=10,
    )

    assert replacement.ok
    replacement_headers = replacement.headers
    assert "x-lagniappe-entity-revisions" in replacement_headers
    assert "x-lagniappe-entity-key" not in replacement_headers
    assert "x-lagniappe-entity-fingerprint" not in replacement_headers
    after_probe = Entities.fetch_one(project.key, request=Fetch.direct())
    assert after_probe.modified == modified_before_probe


# @pairs edited-entity-notice:staged-reset edited-entity-notice:no-reload
# @pairs edited-entity-notice:dirty-state edited-entity-notice:replacement
# @pairs projects:staged-reset projects:no-reload projects:dirty-state
# @pairs projects:replacement projects:info-form
# @template projects/info.html::info_form
def test_project_revision_notice_only_resets_changed_form(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_project_info_form.get(owner)

    owner.go(project)
    project.user = owner
    owner_form = project.info_form
    owner_name = owner_form.locator("input[name='name']")
    owner_description = owner_form.locator("textarea[name='description']")
    initial_name = owner_name.input_value()
    initial_description = owner_description.input_value()
    local_description = f"Local draft {uuid4().hex[:8]}"
    local_description_field = SubmissionFields.TEXTAREA.get(
        "description", submission_value=local_description
    )
    local_description_field.set_submission_value(owner_form)
    owner.page.evaluate("window.__revisionResetSentinel = 'mounted'")
    owner.page.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
    with browser_failures.expect_offline(owner):
        owner.offline = True
        expect(owner.locate("[data-role='offline']")).to_be_visible()

    remote_name = f"Remote revision {uuid4().hex[:8]}"
    collaborator.go(project)
    project.user = collaborator
    collaborator_form = project.info_form
    remote_name_field = SubmissionFields.INPUT.get(
        "name", submission_value=remote_name
    )
    remote_name_field.set_submission_value(collaborator_form)
    with expect_successful_response(
        collaborator.page,
        method="PUT",
        path=f"/projects/{project.key}/update",
        entity_key=project.key,
    ):
        collaborator_form.locator(
            "button[type='submit']:not([data-role])"
        ).click()

    replacement_requests = []

    def record_replacement(request):
        if (
            request.method == "GET"
            and request.url.endswith(f"/projects/{project.key}/info/replace")
        ):
            replacement_requests.append(request)

    owner.page.on("request", record_replacement)
    try:
        with expect_poll_result(
            owner.page,
            subscription_id=f"view:entity:{project.key}",
        ):
            with expect_successful_response(
                owner.page,
                method="GET",
                path=f"/projects/{project.key}/info/replace",
                entity_key=project.key,
            ):
                owner.offline = False
    finally:
        owner.page.remove_listener("request", record_replacement)

    assert len(replacement_requests) == 1
    expect(owner.locate("[data-role='offline']")).to_be_hidden()

    project.user = owner
    owner_form = project.info_form
    owner_name = owner_form.locator("input[name='name']")
    owner_description = owner_form.locator("textarea[name='description']")
    marker = owner_form.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.get_by_role("button", name="Reset form")).to_be_visible()
    expect(owner_name).to_have_value(initial_name)
    expect(owner_description).to_have_value(local_description)

    marker.get_by_role("button", name="Reset form").click()
    expect(owner_form.locator("input[name='name']")).to_have_value(remote_name)
    expect(owner_form.locator("textarea[name='description']")).to_have_value(
        initial_description
    )
    expect(owner_form.locator("[lp-edited-marker]")).to_be_hidden()
    assert owner.page.evaluate("window.__revisionResetSentinel") == "mounted"


# @features projects
# @dimensions attributes-live-toggle attribute-model-tasks no-reload
# @template projects/info.html::info_form
def test_toggle_tasks_attribute(get_user):
    """Project tasks attribute hides and restores model tasks without a reload."""
    user = get_user(Users.OWNER)
    project = Projects.test_project_info_form.get(user)
    user.go(project)
    info_form = project.info_form
    user.page.evaluate("window.__projectAttributeNoReload = true")

    attributes = Attributes(info_form)
    with user.page.expect_response("**/attributes/tasks"):
        attributes.set_selected("tasks", False)

    model_tasks = user.locate(project.MODEL_TASKS_CARD)
    expect(model_tasks).not_to_be_visible()
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-5xl.*"))
    assert user.page.evaluate("window.__projectAttributeNoReload") is True

    with user.page.expect_response("**/attributes/tasks"):
        attributes.set_selected("tasks", True)

    expect(model_tasks).to_be_visible()
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-7xl.*"))
    assert user.page.evaluate("window.__projectAttributeNoReload") is True


# @features projects
# @dimensions attributes-live-toggle attribute-document no-reload
# @template projects/info.html::info_form
def test_toggle_document_attribute(get_user):
    """Project document attribute hides and restores the document tab."""
    user = get_user(Users.OWNER)
    project = Projects.test_project_info_form.get(user)
    user.go(project)
    info_form = project.info_form
    user.page.evaluate("window.__projectDocumentNoReload = true")

    attributes = Attributes(info_form)
    with user.page.expect_response("**/attributes/document"):
        attributes.set_selected("document", False)

    document_tab = user.locate(Tabs.DOCUMENT_TAB)
    expect(document_tab).not_to_be_visible()
    assert user.page.evaluate("window.__projectDocumentNoReload") is True

    with user.page.expect_response("**/attributes/document"):
        attributes.set_selected("document", True)

    expect(user.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).to_be_visible()
    assert user.page.evaluate("window.__projectDocumentNoReload") is True
