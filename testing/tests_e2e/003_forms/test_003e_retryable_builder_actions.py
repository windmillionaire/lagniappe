"""Browser checks for retryable Form Builder actions."""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from testing.definitions import Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaFields
from testing.definitions.user_definitions import UserDefinition
from testing.resources.form import Builder, Form

pytestmark = pytest.mark.e2e


def _set_forms_permission(user, action):
    entity = Entities.USER.load(user.email)
    entity.permissions = {**entity.permissions, "forms": action.name}
    entity.save()
    user.entity = entity


# @matrix forms : builder-save focus-recovery persistent-error retryable-action
# @template forms/builder.html::header
def test_builder_save_failure_releases_control_for_retry(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    form = Form(
        user=owner,
        definition=FormDefinition(
            name="Builder Retryable Save",
            form_type="page",
        ),
    ).create()
    user = get_user(
        UserDefinition(
            name="Builder Retryable Save Editor",
            email=f"builder-retry-{uuid4().hex}@example.test",
        ),
        creator=owner,
    )
    _set_forms_permission(user, Action.EDIT)
    form.user = user
    builder = form.builder
    field = SchemaFields.TEXT_INPUT.get(title="Retryable Save Field")
    builder.add_field(field)

    save_button = user.locate(builder.SAVE_BUTTON)
    notification = user.locate("#notification")
    route = user.locate("#schema-form").get_attribute("data-route")
    expect(user.locate(builder.UNSAVED)).to_be_visible()

    _set_forms_permission(user, Action.VIEW)
    with browser_failures.expect_http_error(user, status=403, path=route):
        with user.page.context.expect_event(
            "response",
            predicate=lambda response: response.url.endswith(route)
            and response.request.method == "PUT"
            and response.status == 403,
        ):
            save_button.click()

        expect(notification).to_be_visible()
        expect(notification).to_have_text("Error 403")
        expect(save_button).to_be_enabled()
        expect(save_button).not_to_have_attribute("aria-busy", "true")
        expect(save_button).to_be_focused()
        expect(user.locate(builder.UNSAVED)).to_be_visible()

    _set_forms_permission(user, Action.EDIT)
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: response.url.endswith(route)
        and response.request.method == "PUT"
        and response.status == 200,
    ):
        save_button.click()
    expect(user.locate(builder.SAVED)).to_be_visible()
    expect(notification).not_to_be_visible()

    user.page.reload()
    assert Builder(user).schema_field(title=field.title) is not None
