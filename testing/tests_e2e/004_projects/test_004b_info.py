"""
Tests for project info tab functionality.

Tests project info editing.
Verified against:
- lagniappe/web/templates/projects/info.html
- src/script/widgets/projectInfo.mjs (ProjectInfo)
- lagniappe/web/routes/projects/main.py
"""

from dataclasses import replace
from uuid import uuid4

from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, SubmissionFields, Users
from testing.elements import SpinnerButtons
from testing.resources import Project
from testing.utility.network import expect_successful_response
from testing.utility.polling import expect_poll_result


def _wait_for_services_ready(user):
    user.page.evaluate(
        """
        async () => {
            const view = document.querySelector("[lp-view]")?._lp_view;
            if (!view) throw new Error("The current view was not published.");
            await view.servicesReady;
        }
        """
    )


# @matrix projects : info-form metadata-sync update
# @template projects/project.html::view_header
# @template projects/info.html::info_tab
def test_project_info_form(get_user):
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


# @matrix edited-entity-notice projects : info-form replacement side-effect-free timestamp-only
# @template projects/info.html::info_form
def test_project_info_replacement_is_side_effect_free_for_timestamp_only_revision(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    project = Project(
        user=owner,
        definition=replace(
            Projects.test_project_info_form.value.definition,
            name=f"Timestamp-only Project {uuid4().hex}",
        ),
    ).create()
    owner.go(project)
    info_form = project.info_form
    expect(info_form.locator("input[name='name']")).to_have_value(
        project.definition.name
    )
    expect(info_form.locator("textarea[name='description']")).to_have_value(
        project.definition.description
    )
    _wait_for_services_ready(owner)

    with browser_failures.expect_http_error(
        owner,
        status=503,
        path="/l/poll",
        count=0,
        max_count=1,
    ):
        with browser_failures.expect_offline(owner):
            owner.offline = True
            expect(owner.locate("[data-role='offline']")).to_be_visible()

    timestamp_only = Entities.fetch_one(project.key, request=Fetch.direct())
    timestamp_only.properties.modified.update()
    timestamp_only.save()
    modified_before_probe = timestamp_only.modified

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

    expect(owner.locate("[data-role='offline']")).to_be_hidden()
    refreshed_form = project.info_form
    expect(refreshed_form.locator("input[name='name']")).to_have_value(
        project.definition.name
    )
    expect(refreshed_form.locator("textarea[name='description']")).to_have_value(
        project.definition.description
    )
    after_probe = Entities.fetch_one(project.key, request=Fetch.direct())
    assert after_probe.modified == modified_before_probe


# @matrix edited-entity-notice : dirty-state no-reload replacement staged-reset
# @matrix projects : dirty-state info-form no-reload replacement staged-reset
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
    _wait_for_services_ready(owner)
    with browser_failures.expect_http_error(
        owner,
        status=503,
        path="/l/poll",
        count=0,
        max_count=1,
    ):
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
