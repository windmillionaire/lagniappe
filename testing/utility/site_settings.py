"""Shared Site Settings navigation and section helpers for E2E tests."""

from playwright.sync_api import expect

from testing.definitions import SitePages


# @testable false
# @reason Reusable E2E navigation and selectors; callers assert page behavior.
def open_owner_site_settings(owner):
    owner.go(SitePages.HOME)
    admin = owner.go(SitePages.ADMIN)
    settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(settings_panel).to_have_attribute("initialized", "")
    expect(settings_panel).to_be_visible()
    return admin, settings_panel


# @testable false
# @reason Reusable E2E selector composition; callers assert section behavior.
def site_settings_section(settings_panel, section):
    return settings_panel.locator(
        f"[data-role='site-settings-section'][data-section='{section}']"
    )


# @testable false
# @reason Reusable E2E interaction composition; callers assert section outcomes.
def open_site_settings_section(settings_panel, section):
    section_panel = site_settings_section(settings_panel, section)
    if section_panel.get_attribute("data-open") != "true":
        section_panel.locator("[data-role='expand']").click()
    expect(section_panel).to_have_attribute("data-open", "true")
    expect(section_panel.locator("[data-role='section-body']")).to_be_visible()
    return section_panel
