"""Focused browser contracts for Admin data-protection status."""

import pytest
from playwright.sync_api import expect

from testing.definitions import SitePages, Users


pytestmark = pytest.mark.e2e


# @template home/admin.html::backups_tab
def test_backups_tab_reveals_static_status_panel(get_user):
    owner = get_user(Users.OWNER)
    owner.go(SitePages.ADMIN)

    backups = owner.locate("#backups")
    owner.locate("#tabs button[lp-show='backups:active']").click()

    expect(backups).to_have_attribute("data-visible", "true")
    expect(backups).to_have_attribute("data-open", "true")
    expect(backups).to_contain_text("Data protection")
