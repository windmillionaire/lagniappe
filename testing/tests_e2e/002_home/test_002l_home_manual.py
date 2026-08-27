"""Browser coverage for public manual pages linked from the home page."""

import pytest
from playwright.sync_api import expect

from config import SETTINGS
from testing.definitions import Users


@pytest.mark.e2e
def test_manual_delegated_installation_separates_owner_and_installer_checklists(
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
    expect(
        delegated.get_by_role("heading", name="Delegated Installation")
    ).to_be_visible()
    owner = delegated.locator("[data-role='delegated-owner-checklist']")
    installer = delegated.locator("[data-role='delegated-installer-checklist']")
    expect(owner).not_to_have_attribute("open", "")
    expect(installer).not_to_have_attribute("open", "")
    expect(owner.locator("summary")).to_contain_text("Business / permanent Owner")
    expect(owner.locator("summary")).to_contain_text(
        "Create and fund the project, create the installer account, grant "
        "temporary access, and close the handoff."
    )
    expect(installer.locator("summary")).to_contain_text("Installer")
    expect(installer.locator("summary")).to_contain_text(
        "Activate the temporary account, run setup, verify the deployment, "
        "and return access."
    )
    expect(owner.locator("ol")).not_to_be_visible()
    expect(installer.locator("ol")).not_to_be_visible()

    owner.locator("summary").click()
    expect(owner).to_have_attribute("open", "")
    expect(owner.locator("ol")).to_be_visible()
    expect(installer.locator("ol")).not_to_be_visible()
    expect(owner).to_contain_text(
        "Apps / Additional Google services / Google Cloud Platform / "
        "Service status"
    )
    expect(owner).to_contain_text("ON for everyone")
    expect(owner).to_contain_text("Inherited: On")
    expect(owner).to_contain_text("Override")
    expect(owner).to_contain_text(
        "does not need permission to create projects"
    )
    expect(owner).to_contain_text("Project info")
    expect(owner).to_contain_text(
        "record the exact Project ID for the installer"
    )
    expect(owner).to_contain_text(
        "confirm on the Billing page that billing is enabled"
    )
    expect(owner).to_contain_text(
        "use the search box at the top of Google Cloud console to search for "
        "IAM"
    )
    expect(owner).to_contain_text("View by principals")
    expect(owner).to_contain_text(
        "directly, with no inherited source or condition"
    )
    expect(owner).to_contain_text(
        "the Owner line itself must have no entry in Inheritance"
    )
    expect(owner).to_contain_text(
        "Never give the installer the Owner’s Google password"
    )
    owner_terms = owner.locator(
        "a[href='https://console.developers.google.com/terms/cloud']"
    )
    expect(owner_terms).to_have_count(1)
    expect(owner_terms).to_have_text("Google Cloud service-terms page")
    owner_maps_terms = owner.locator(
        "a[href='https://console.developers.google.com/terms/maps']"
    )
    expect(owner_maps_terms).to_have_count(1)
    expect(owner_maps_terms).to_have_text("Google Maps Platform terms page")
    expect(owner).to_contain_text("setup will enable Places API itself")
    owner_places_api = owner.locator(
        "a[href='https://console.cloud.google.com/apis/library/places.googleapis.com']"
    )
    expect(owner_places_api).to_have_count(0)

    owner.locator("summary").click()
    installer.locator("summary").click()
    expect(owner.locator("ol")).not_to_be_visible()
    expect(installer).to_have_attribute("open", "")
    expect(installer.locator("ol")).to_be_visible()
    expect(installer).to_contain_text("separate browser profile")
    expect(installer).to_contain_text("Agree and continue")
    expect(installer).to_contain_text("You do not need to select Start free")
    expect(installer).to_contain_text(
        "Do not create a project or manually enable any APIs"
    )
    expect(installer).to_contain_text(
        "it displays the active gcloud CLI email"
    )
    expect(installer).to_contain_text(
        "verifies that account’s CLI token before showing any project choices"
    )
    expect(installer).to_contain_text(
        "Are you installing Lagniappe for a different permanent Owner?"
    )
    expect(installer).to_contain_text(
        "lists only active projects where the authenticated installer has a "
        "direct, unconditional Project Owner role"
    )
    expect(installer).to_contain_text(
        "never offers project creation in delegated mode"
    )
    expect(installer).to_contain_text(
        "automatically enables Google Sign-In, and gives the confirmed "
        "installer temporary Lagniappe Administrator access"
    )
    expect(installer).to_contain_text(
        "does not ask additional yes-or-no questions for them"
    )
    expect(installer).to_contain_text("./setup.sh handoff")
    installer_terms = installer.locator(
        "a[href='https://console.developers.google.com/terms/cloud']"
    )
    expect(installer_terms).to_have_count(0)
    installer_maps_terms = installer.locator(
        "a[href='https://console.developers.google.com/terms/maps']"
    )
    expect(installer_maps_terms).to_have_count(0)
    expect(installer).to_contain_text(
        "only after the permanent Owner has reviewed the agreement and "
        "explicitly authorized you to do so"
    )
    cloud_console_links = delegated.locator(
        "a[href='https://console.cloud.google.com/']"
    )
    expect(cloud_console_links).to_have_count(2)
    expect(cloud_console_links.first).to_have_text("Google Cloud console")
    expect(delegated.locator("summary [data-icon]")).to_have_count(0)
