"""E2E coverage for the owner-only site export tab."""

import pytest
from playwright.sync_api import expect

from lagniappe.core.tools import database
from testing.definitions import SitePages, Users

pytestmark = pytest.mark.e2e


# @features export
# @dimensions owner-only start-export storage-objects notification archive-build users-category
def test_owner_can_start_html_export(get_user):
    owner = get_user(Users.OWNER)
    admin = owner.go(SitePages.ADMIN)

    owner.locate(admin.SITE_EXPORT_TOGGLE).click()
    export_panel = owner.locate(admin.SITE_EXPORT_FORM)
    expect(export_panel).to_have_attribute("initialized", "")
    expect(export_panel).to_be_visible()

    export_panel.locator(admin.SITE_EXPORT_START).click()

    completed_item = owner.locate(
        f"{admin.SITE_EXPORT_ITEM}:has-text('Complete')"
    ).first
    expect(completed_item).to_be_visible(timeout=30000)
    expect(completed_item).to_contain_text("gcloud storage cp --recursive")

    notifications = owner.locate("[data-role='notifications']")
    expect(notifications).to_be_visible(timeout=15000)

    latest = database.site_exports(limit=1)[0]
    assert latest["status"] == "complete"
    prefix = latest["prefix"]
    object_names = {
        blob.name for blob in database.assets.list_files(prefix, "export")
    }

    assert f"{prefix}index.html" in object_names
    assert f"{prefix}manifest.json" in object_names
    assert f"{prefix}README.txt" in object_names
    assert f"{prefix}assets/archive.css" in object_names
    assert f"{prefix}categories/users/index.html" in object_names
