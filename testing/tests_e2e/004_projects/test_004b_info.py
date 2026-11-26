"""
Tests for project header inline editing and project model-task revision handling.

Verified against:
- lagniappe/web/templates/projects/project.html
- lagniappe/web/templates/projects/model_tasks.html
- src/script/widgets/projectHeader.ts
- lagniappe/web/routes/projects/main.py
"""

from dataclasses import replace
from uuid import uuid4

from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, SubmissionFields, Users
from testing.definitions.model_task_definitions import ModelTaskDefinition
from testing.resources import ModelTask, Project
from testing.utility.network import browser_fetch, expect_successful_response
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


# @template projects/project.html::view_header
# @template projects/project.html::main
# @style entity.description
def test_project_info_form(get_admin, get_user):
    user = get_admin()
    project = Projects.test_project_info_form.get(user)
    user.go(project)
    expect(user.page.get_by_role("button", name="Project actions")).to_be_visible()

    new_name = "Apples"
    new_description = "Apples are mad tasty.\n\n  Keep this line indented."

    menu = project.open_actions_menu()
    menu.locator("[data-project-action='rename']").click()
    rename_input = user.locate("[data-role='rename-form'] input[name='name']")
    expect(rename_input).to_be_visible()
    expect(rename_input).to_have_value(project.definition.name)
    rename_input.fill(new_name)
    with expect_successful_response(
        user.page, method="PATCH", path=f"/projects/{project.key}/patch"
    ):
        rename_input.press("Enter")

    title = user.locate(project.PROJECT_TITLE)
    expect(title).to_contain_text(new_name)

    menu = project.open_actions_menu()
    menu.locator("[data-project-action='description']").click()
    desc_editor = user.locate("[data-role='description-editor']")
    expect(desc_editor).to_be_visible()
    desc_textarea = desc_editor.locator("textarea[name='description']")
    expect(desc_textarea).to_have_value(project.definition.description)
    desc_textarea.fill(new_description)
    with expect_successful_response(
        user.page, method="PATCH", path=f"/projects/{project.key}/patch"
    ):
        desc_editor.get_by_role("button", name="Save", exact=True).click()

    description = user.locate(project.PROJECT_DESCRIPTION)
    expect(description).to_contain_text(new_description)
    expect(description).to_have_css("white-space", "pre-wrap")
    assert description.text_content() == new_description

    user.reload()
    expect(user.locate(project.PROJECT_TITLE)).to_contain_text(new_name)
    description = user.locate(project.PROJECT_DESCRIPTION)
    expect(description).to_contain_text(new_description)
    expect(description).to_have_css("white-space", "pre-wrap")
    assert description.text_content() == new_description


# @template projects/project.html::main
def test_project_info_replacement_is_side_effect_free_for_timestamp_only_revision(
    get_admin,
    browser_failures,
):
    owner = get_admin()
    project = Project(
        user=owner,
        definition=replace(
            Projects.test_project_info_form.value.definition,
            name=f"Timestamp-only Project {uuid4().hex}",
        ),
    ).create()
    owner.go(project)
    expect(owner.locate(project.PROJECT_TITLE)).to_have_text(project.definition.name)
    expect(owner.locate(project.PROJECT_DESCRIPTION)).to_have_text(
        project.definition.description
    )
    _wait_for_services_ready(owner)

    with browser_failures.expect_http_error(
        owner,
        status=503,
        path="/l/poll",
        count=0,
        max_count=1,
    ), browser_failures.expect_offline(owner):
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
        owner.offline = False

    expect(owner.locate("[data-role='offline']")).to_be_hidden()
    probe = browser_fetch(
        owner,
        f"/projects/{project.key}/info/replace",
        method="GET",
    )
    assert probe["status"] == 200
    after_probe = Entities.fetch_one(project.key, request=Fetch.direct())
    assert after_probe.modified == modified_before_probe


# @template projects/model_tasks.html::model_task
def test_project_revision_notice_only_resets_changed_form(
    get_admin, get_user,
    browser_failures,
):
    owner = get_admin()
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_project_revision_notice.get(owner)
    initial_name = f"Revision Model {uuid4().hex[:8]}"
    model_task = ModelTask(
        user=owner,
        definition=ModelTaskDefinition(name=initial_name, project=None),
    )
    model_task.entity = Entities.MODEL_TASK.create(
        project.entity, {"name": initial_name}
    )
    model_task.entity.save()

    try:
        owner.go(project)
        model_task.user = owner
        owner_form = model_task.open_info()
        owner_name = owner_form.locator("input[name='name']")
        expect(owner_name).to_have_value(initial_name)

        local_draft = f"Local draft {uuid4().hex[:8]}"
        local_name_field = SubmissionFields.INPUT.get(
            "name", submission_value=local_draft
        )
        local_name_field.set_submission_value(owner_form)
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
        ), browser_failures.expect_offline(owner):
            owner.offline = True
            expect(owner.locate("[data-role='offline']")).to_be_visible()

        remote_name = f"Remote revision {uuid4().hex[:8]}"
        collaborator.go(project)
        model_task.user = collaborator
        collaborator_form = model_task.open_info()
        remote_name_field = SubmissionFields.INPUT.get(
            "name", submission_value=remote_name
        )
        remote_name_field.set_submission_value(collaborator_form)
        with expect_successful_response(
            collaborator.page,
            method="PUT",
            path=f"/projects/{project.key}/update-model/{model_task.key}",
            entity_key=model_task.key,
        ):
            collaborator_form.locator(
                "button[type='submit']:not([data-role])"
            ).click()

        with expect_poll_result(
            owner.page,
            subscription_id=f"edit:{model_task.key}",
        ), expect_successful_response(
            owner.page,
            method="GET",
            path=f"/projects/{project.key}/models/{model_task.key}/replace",
            entity_key=model_task.key,
        ):
            owner.offline = False

        expect(owner.locate("[data-role='offline']")).to_be_hidden()

        model_task.user = owner
        owner_form = model_task.info_form
        owner_name = owner_form.locator("input[name='name']")
        marker = owner_form.locator("[lp-edited-marker]")
        expect(marker).to_be_visible()
        expect(marker.get_by_role("button", name="Reset form")).to_be_visible()
        expect(owner_name).to_have_value(local_draft)

        marker.get_by_role("button", name="Reset form").click()
        expect(model_task.info_form.locator("input[name='name']")).to_have_value(
            remote_name
        )
        expect(model_task.info_form.locator("[lp-edited-marker]")).to_be_hidden()
        assert owner.page.evaluate("window.__revisionResetSentinel") == "mounted"
    finally:
        Entities.delete(model_task.entity)
