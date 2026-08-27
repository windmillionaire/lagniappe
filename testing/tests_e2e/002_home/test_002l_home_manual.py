"""Browser coverage for public manual pages linked from the home page."""

import pytest
from playwright.sync_api import expect

from config import SETTINGS
from testing.definitions import Users


@pytest.mark.e2e
def test_manual_delegated_installation_explains_workspace_cloud_access(
    get_user,
):
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")

    response = anonymous.page.goto(
        f"{base_url}/manual/installation",
        wait_until="domcontentloaded",
    )

    assert response.ok
    delegated = anonymous.locate("[data-role='delegated-installation']")
    expect(delegated).to_contain_text(
        "Apps / Additional Google services / Google Cloud Platform / "
        "Service status"
    )
    expect(delegated).to_contain_text("ON for everyone")
    expect(delegated).to_contain_text("Inherited: On")
    expect(delegated).to_contain_text("Override")
    expect(delegated).to_contain_text(
        "does not need permission to create projects"
    )
    expect(delegated).to_contain_text("separate browser profile")
    expect(delegated).to_contain_text("Project info")
    expect(delegated).to_contain_text(
        "record the exact Project ID for the installer"
    )
    expect(delegated).to_contain_text(
        "confirm on the Billing page that billing is enabled"
    )
    expect(delegated).to_contain_text(
        "use the search box at the top of Google Cloud console to search for "
        "IAM"
    )
    expect(delegated).to_contain_text("View by principals")
    expect(delegated).to_contain_text(
        "directly, with no inherited source or condition"
    )
    expect(delegated).to_contain_text(
        "the Owner line itself must have no entry in Inheritance"
    )
    expect(delegated).to_contain_text(
        "setup displays the active gcloud CLI account's exact email"
    )
    expect(delegated).to_contain_text(
        "confirmed account's CLI token before showing any project choices"
    )
    expect(delegated).to_contain_text(
        "Are you installing Lagniappe for a different permanent Owner?"
    )
    expect(delegated).to_contain_text(
        "lists only active projects where that authenticated installer has a "
        "direct, unconditional Project Owner role"
    )
    expect(delegated).to_contain_text(
        "does not offer to create a project in delegated mode"
    )
    cloud_console_links = delegated.locator(
        "a[href='https://console.cloud.google.com/']"
    )
    expect(cloud_console_links).to_have_count(2)
    expect(cloud_console_links.first).to_have_text("Google Cloud console")
    expect(
        delegated.locator("summary [data-icon='installation']")
    ).to_have_count(0)
    summary = delegated.locator("summary")
    expect(
        summary.get_by_text("Delegated installation", exact=True)
    ).to_have_css("display", "inline")
    expect(
        summary.get_by_text(
            "Open this checklist only when someone outside the business "
            "will perform the installation.",
            exact=True,
        )
    ).to_have_css("display", "block")
