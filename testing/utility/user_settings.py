"""Shared user-settings navigation and selector helpers for E2E tests."""

from playwright.sync_api import expect

from testing.resources import HomePage


# @testable false
# @reason Reusable E2E selectors; consuming tests assert the opened panel.
def open_user_settings(user, user_page):
    toggle = user.locate(user_page.USER_SETTINGS_TOGGLE).first
    expect(toggle).to_be_visible()
    toggle.click()
    settings_panel = user.locate(user_page.USER_SETTINGS_FORM)
    expect(settings_panel).to_have_attribute("initialized", "")
    expect(settings_panel).to_be_visible()
    return settings_panel


# @testable false
# @reason Reusable E2E DOM projection; consuming tests assert the resulting order.
def user_settings_field_order(settings_panel):
    return settings_panel.locator("[data-role='user-fields'] > *").evaluate_all(
        """(elements) => elements.map((element) => {
            if (element.dataset.role && element.dataset.role !== "label") {
                return element.dataset.role;
            }
            const input = element.matches("[name]")
                ? element
                : element.querySelector("[name]");
            return input?.name || element.id;
        })"""
    )


# @testable false
# @reason Reusable E2E navigation; destination behavior belongs to callers.
def go_to_my_page(user):
    home = HomePage(user=user)
    with user.page.expect_navigation():
        home.user_page_button.click()
