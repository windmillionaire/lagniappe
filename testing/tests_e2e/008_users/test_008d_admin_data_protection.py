"""Focused browser contracts for Admin data-protection status."""

import pytest
from playwright.sync_api import expect

from testing.definitions import SitePages, Users


pytestmark = pytest.mark.e2e


# @matrix admin cache disaster-recovery : no-store status
# @template home/admin.html::backups_tab
def test_backups_tab_reveals_static_status_panel(get_user):
    owner = get_user(Users.OWNER)
    with owner.page.expect_response(
        lambda response: response.request.method == "GET"
        and response.url.split("?", 1)[0].rstrip("/").endswith("/admin")
    ) as response_info:
        owner.go(SitePages.ADMIN)
    assert response_info.value.headers["cache-control"] == "no-store"

    backups = owner.locate("#backups")
    owner.locate("#tabs button[lp-show='backups:active']").click()

    expect(backups).to_have_attribute("data-visible", "true")
    expect(backups).to_have_attribute("data-open", "true")
    expect(backups).to_contain_text("Data protection")
    expect(backups).to_contain_text("Automatic backups")
    expect(backups).to_contain_text("Manual backups")
    create_command = backups.locator("[data-role='manual-command']").filter(
        has_text="./setup.sh backup create"
    )
    expect(create_command).to_have_count(1)
    copy_button = create_command.locator(
        "xpath=ancestor::*[@data-role='manual-command-shell']"
    ).locator("[data-role='manual-command-copy']")
    copy_button.click()
    expect(copy_button).to_have_text("Copied!")
