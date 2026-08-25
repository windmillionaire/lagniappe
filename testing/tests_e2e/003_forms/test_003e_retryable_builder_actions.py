"""Browser checks for retryable Form Builder actions."""

import pytest
from playwright.sync_api import expect

from testing.definitions import Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaFields
from testing.resources.form import Builder, Form

pytestmark = pytest.mark.e2e


def _fail_next_browser_fetch(page, *, method, path_prefix, error):
    page.evaluate(
        """([method, pathPrefix, error]) => {
            const originalFetch = window.fetch.bind(window);
            let pending = true;
            window.fetch = (input, options = {}) => {
                const url = typeof input === "string" ? input : input.url;
                const requestMethod = (
                    options.method || (typeof input === "string" ? "GET" : input.method)
                ).toUpperCase();
                const pathname = new URL(url, window.location.href).pathname;
                if (pending && requestMethod === method && pathname.startsWith(pathPrefix)) {
                    pending = false;
                    return Promise.resolve(new Response(
                        JSON.stringify({ error }),
                        {
                            status: 503,
                            headers: { "Content-Type": "application/json" },
                        },
                    ));
                }
                return originalFetch(input, options);
            };
        }""",
        [method, path_prefix, error],
    )


# @features forms
# @dimensions builder-save retryable-action persistent-error focus-recovery
# @template forms/builder.html::header
def test_builder_save_failure_releases_control_for_retry(get_user):
    user = get_user(Users.OWNER)
    form = Form(
        user=user,
        definition=FormDefinition(
            name="Builder Retryable Save",
            form_type="page",
        ),
    ).create()
    builder = form.builder
    field = SchemaFields.TEXT_INPUT.get(title="Retryable Save Field")
    builder.add_field(field)

    save_button = user.locate(builder.SAVE_BUTTON)
    notification = user.locate("#notification")
    route = user.locate("#schema-form").get_attribute("data-route")
    expect(user.locate(builder.UNSAVED)).to_be_visible()

    _fail_next_browser_fetch(
        user.page,
        method="PUT",
        path_prefix=route,
        error="Temporary save failure",
    )
    save_button.click()

    expect(notification).to_be_visible()
    expect(notification).to_have_text("Temporary save failure")
    expect(save_button).to_be_enabled()
    expect(save_button).not_to_have_attribute("aria-busy", "true")
    expect(save_button).to_be_focused()
    expect(user.locate(builder.UNSAVED)).to_be_visible()

    with user.page.expect_response(f"**{route}"):
        save_button.click()
    expect(user.locate(builder.SAVED)).to_be_visible()
    expect(notification).not_to_be_visible()

    user.page.reload()
    assert Builder(user).schema_field(title=field.title) is not None
