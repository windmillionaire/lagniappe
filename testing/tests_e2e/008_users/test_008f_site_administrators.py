import json
import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from testing.definitions import SitePages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.utility.network import browser_fetch
from testing.utility.site_settings import (
    open_owner_site_settings,
    open_site_settings_section,
    site_settings_section,
)
from testing.utility.user_cache import acknowledge_user_cache_invalidation

pytestmark = pytest.mark.e2e


# @matrix admin : admin-only page-load route site-settings
# @pair cache:invalidation-acknowledgement
# @template home/admin.html::main
def test_site_settings_requires_administrator(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    user = get_user(
        UserDefinition(
            name=f"Temporary Administrator {suffix[:8]}",
            email=f"temporary-administrator-{suffix}@example.test",
        ),
        creator=owner,
    )

    admin = owner.go(SitePages.ADMIN)
    expect(owner.locate(admin.SITE_SETTINGS_FORM)).to_be_visible()

    admin_url = f"{SETTINGS.test_config['BASE_URL'].rstrip('/')}/admin"
    with browser_failures.expect_http_error(user, status=403, path=admin_url):
        user.navigate(admin_url)
    expect(user.locate(admin.SITE_SETTINGS_FORM)).to_have_count(0)

    user.entity.is_admin = True
    user.entity.save()
    try:
        acknowledge_user_cache_invalidation(user)
        admin = user.go(SitePages.ADMIN)
        expect(user.locate(admin.SITE_SETTINGS_FORM)).to_be_visible()
    finally:
        user.entity = Entities.USER.load(user.email)
        user.entity.is_admin = False
        user.entity.save()
        acknowledge_user_cache_invalidation(user)


# @matrix admin : account-preservation confirmation-modal demotion failure-state managed-user-search managed-users owner-only privileged-account promotion read-only responsive roster
# @matrix cache : cache-invalidation invalidation-acknowledgement
# @matrix owner : awaiting-first-sign-in owner-only role-controls
# @template home/site_settings.html::site_settings
def test_site_administrator_roster_and_owner_controls(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    managed = get_user(
        UserDefinition(
            name=f"Administrator Roster User {suffix[:8]}",
            email=f"administrator-roster-{suffix}@example.test",
        ),
        creator=owner,
    )
    _, settings_panel = open_owner_site_settings(owner)
    section = open_site_settings_section(settings_panel, "administrators")
    form = section.locator("[data-role='administrator-form']")
    roster = section.locator("[data-role='administrator-list']")

    expect(form).to_have_attribute("data-visible", "true")
    expect(roster.locator("[data-owner='true']")).to_contain_text("Primary Owner")
    expect(roster.locator("[data-owner='true']")).to_contain_text(owner.email)

    selector = form.locator("[data-role='managed-user-selector']")
    expect(selector).to_have_attribute("role", "combobox")
    expect(selector).to_have_attribute("aria-haspopup", "listbox")
    submit = form.locator("button[type='submit']")
    selector_box = selector.bounding_box()
    submit_box = submit.bounding_box()
    assert selector_box and submit_box
    assert abs(selector_box["width"] - submit_box["width"]) <= 2
    assert abs(selector_box["height"] - submit_box["height"]) <= 2
    selector.fill(managed.entity.name)
    option = owner.page.locator(
        f"[role='option'][data-id='{managed.entity.page.urlsafe_key}']"
    )
    expect(option).to_contain_text(managed.entity.name)
    option.click()
    expect(form.locator("select[name='user_key']")).to_have_value(
        managed.entity.page.urlsafe_key
    )
    with owner.page.expect_response(
        lambda response: (
            response.url.endswith("/l/site-administrators")
            and response.request.method == "POST"
        )
    ) as promotion:
        submit.click()
    assert promotion.value.status == 200
    expect(roster).to_contain_text(managed.email)
    promoted = Entities.USER(database_get.user(managed.email))
    assert promoted.is_admin
    assert promoted.invalidate_cache
    assert not promoted.is_owner

    admin_url = f"{SETTINGS.test_config['BASE_URL'].rstrip('/')}/admin"
    managed.entity = promoted
    response = acknowledge_user_cache_invalidation(managed, admin_url)
    assert response.status == 200
    expect(managed.locate("button[data-role='configuration']")).to_have_count(0)
    admin_section = open_site_settings_section(
        managed.locate("[data-widget='SiteSettings']"), "administrators"
    )
    expect(admin_section.locator("[data-role='administrator-form']")).to_have_attribute(
        "data-visible", "false"
    )
    expect(admin_section.locator("[data-role='demote-administrator']")).to_have_count(
        0
    )

    protected_path = f"/users/{owner.entity.urlsafe_key}/delete"
    with browser_failures.expect_http_error(managed, status=403, path=protected_path):
        protected_delete = browser_fetch(managed, protected_path, "DELETE")
    assert protected_delete["status"] == 403
    self_demote_path = f"/l/site-administrators/{managed.entity.urlsafe_key}"
    with browser_failures.expect_http_error(managed, status=403, path=self_demote_path):
        self_demote = browser_fetch(managed, self_demote_path, "DELETE")
    assert self_demote["status"] == 403

    administrator_row = roster.locator(
        f"[data-role='administrator']:has(button[data-key='{managed.entity.urlsafe_key}'])"
    )
    expect(administrator_row).to_have_class(re.compile(r".*\bsm:flex-row\b.*"))
    demote_button = administrator_row.locator("[data-role='demote-administrator']")
    demote_button.click()
    modal = owner.locate("#modal")
    expect(modal).to_be_visible()
    expect(
        modal.get_by_role("heading", name="Remove Administrator", exact=True)
    ).to_be_visible()
    expect(modal).to_contain_text(
        f"Remove Administrator access from {managed.entity.name}?"
    )
    expect(modal).to_contain_text("Their account and content will be kept.")
    modal.get_by_role("button", name="Cancel").click()
    expect(modal).not_to_be_attached()
    expect(administrator_row).to_contain_text(managed.email)
    assert Entities.USER(database_get.user(managed.email)).is_admin

    demote_button.click()
    modal = owner.locate("#modal")
    expect(modal).to_be_visible()
    with owner.page.expect_response(
        lambda response: (
            response.url.endswith(
                f"/l/site-administrators/{managed.entity.urlsafe_key}"
            )
            and response.request.method == "DELETE"
        )
    ) as demotion:
        modal.get_by_role("button", name="Remove Administrator").click()
    assert demotion.value.status == 200
    expect(modal).not_to_be_attached()
    expect(roster).not_to_contain_text(managed.email)
    demoted = Entities.USER(database_get.user(managed.email))
    assert not demoted.is_admin
    assert demoted.invalidate_cache
    managed.entity = demoted

    with browser_failures.expect_http_error(managed, status=403, path=admin_url):
        response = acknowledge_user_cache_invalidation(managed, admin_url)
    assert response.status == 403


# @matrix owner : configuration recovery-export route-gate sensitive-configuration
# @pair admin:site-settings
def test_additional_admin_cannot_access_owner_configuration(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    administrator = get_user(
        UserDefinition(
            name=f"Restricted Administrator {suffix[:8]}",
            email=f"restricted-administrator-{suffix}@example.test",
        ),
        creator=owner,
    )
    owner.go(SitePages.HOME)
    administrator.go(SitePages.HOME)
    promotion = browser_fetch(
        owner,
        "/l/site-administrators",
        "POST",
        {"user_key": administrator.entity.urlsafe_key},
    )
    assert promotion["status"] == 200

    try:
        persisted_administrator = Entities.USER(database_get.user(administrator.email))
        assert persisted_administrator.is_admin
        administrator.entity = persisted_administrator
        acknowledge_user_cache_invalidation(administrator)
        admin = administrator.go(SitePages.ADMIN)
        settings_panel = administrator.locate(admin.SITE_SETTINGS_FORM)
        expect(settings_panel).to_be_visible()
        expect(
            settings_panel.locator("button[data-role='configuration']")
        ).to_have_count(0)

        site_settings = browser_fetch(administrator, "/l/site-settings", "GET")
        assert site_settings["status"] == 200
        assert site_settings["data"]["can_manage_administrators"] is False
        assert site_settings["data"]["can_view_sensitive_configuration"] is False
        assert "installation_access" not in site_settings["data"]
        expect(
            settings_panel.locator(
                "[data-role='site-settings-section'][data-section='installation-access']"
            )
        ).to_have_count(0)
        assert (
            browser_fetch(
                administrator, "/reference/environment-variables", "GET"
            )["status"]
            == 200
        )
        with browser_failures.expect_http_error(
            administrator, status=403, path="/l/site-configuration"
        ):
            configuration = browser_fetch(
                administrator, "/l/site-configuration", "GET"
            )
        assert configuration["status"] == 403
        with browser_failures.expect_http_error(
            administrator, status=403, path="/reference/download-settings"
        ):
            recovery = browser_fetch(
                administrator, "/reference/download-settings", "GET"
            )
        assert recovery["status"] == 403
    finally:
        demotion = browser_fetch(
            owner,
            f"/l/site-administrators/{administrator.entity.urlsafe_key}",
            "DELETE",
        )
        assert demotion["status"] == 200
        administrator.entity = Entities.USER.load(administrator.email)
        assert not administrator.entity.is_admin
        acknowledge_user_cache_invalidation(administrator)


# @matrix owner : authentication-email delegated-handoff identity-metadata provider-cleanup
# @template home/site_settings.html::site_settings
def test_owner_installation_access_distinguishes_handoff_from_provider_cleanup(
    get_user,
):
    owner = get_user(Users.OWNER)
    owner_email = str(getattr(CONFIG, "ADMIN_EMAIL", "") or "").strip().casefold()
    installer_email = str(
        getattr(CONFIG, "INSTALLER_EMAIL", "") or ""
    ).strip().casefold()
    deployer_email = str(
        getattr(CONFIG, "DEPLOYER_EMAIL", "") or ""
    ).strip().casefold()
    bootstrap_email = str(
        getattr(CONFIG, "BOOTSTRAP_ADMIN_EMAIL", "") or ""
    ).strip().casefold()
    delegated = bool(owner_email and installer_email and owner_email != installer_email)
    _, settings_panel = open_owner_site_settings(owner)
    response = browser_fetch(owner, "/l/site-settings", "GET")["data"]
    section = site_settings_section(settings_panel, "installation-access")
    if not delegated:
        expect(section).to_have_count(0)
        assert "installation_access" not in response
        return

    expect(section).to_have_count(1)
    access = open_site_settings_section(settings_panel, "installation-access")
    target = access.locator(
        "[data-role='section-body'][data-widget='SiteInstallationAccess']"
    )
    application_complete = bool(deployer_email == owner_email and not bootstrap_email)
    state = "application-complete" if application_complete else "pending"
    title = (
        "Application handoff configured"
        if application_complete
        else "Delegated handoff pending"
    )
    project_id = str(getattr(CONFIG, "GOOGLE_CLOUD_PROJECT", "") or "").strip()
    runtime_email = str(
        getattr(CONFIG, "RUNTIME_SERVICE_ACCOUNT_EMAIL", "") or ""
    ).strip().casefold()
    auth_email = getattr(CONFIG, "AUTH_EMAIL_CONFIG", None) or {}
    if not isinstance(auth_email, dict):
        auth_email = {}
    auth_service = str(auth_email.get("service") or "").strip()
    auth_sender = str(auth_email.get("senderEmail") or "").strip().casefold()
    auth_login = str(auth_email.get("username") or "").strip().casefold()
    installer_controls_email = bool(
        installer_email and installer_email in {auth_sender, auth_login}
    )

    expect(target).to_have_attribute("data-state", state)
    expect(access.locator("[data-role='status-title']")).to_have_text(title)
    expect(access.locator("[data-field='owner']")).to_have_text(owner_email)
    expect(access.locator("[data-field='installer']")).to_have_text(installer_email)
    expect(access.locator("[data-field='deployer']")).to_have_text(
        deployer_email or "None"
    )
    expect(access.locator("[data-field='bootstrap']")).to_have_text(
        bootstrap_email or "None"
    )
    expect(access.locator("[data-field='runtime']")).to_have_text(
        runtime_email or "None"
    )
    expect(access.locator("[data-field='email-service']")).to_have_text(
        auth_service or "None"
    )
    expect(access.locator("[data-field='email-sender']")).to_have_text(
        auth_sender or "None"
    )
    expect(access.locator("[data-field='email-login']")).to_have_text(
        auth_login or "None"
    )
    handoff = access.locator("[data-role='handoff-instructions']")
    if state == "pending":
        expect(handoff).to_be_visible()
        expect(handoff).to_contain_text("the installer normally runs")
        expect(handoff.locator("code")).to_have_text("./setup.sh handoff")
    else:
        expect(handoff).to_be_hidden()
    expect(access.locator("code[data-field]")).to_have_count(8)
    email_warning = access.locator("[data-role='installer-email-warning']")
    if installer_controls_email:
        expect(email_warning).to_be_visible()
    else:
        expect(email_warning).to_be_hidden()
    expect(access.locator("[data-role='project-iam-link']")).to_have_attribute(
        "href",
        f"https://console.cloud.google.com/iam-admin/iam?project={project_id}",
    )

    payload = response["installation_access"]
    assert payload["state"] == state
    assert payload["application_handoff_complete"] is application_complete
    assert payload["owner_email"] == owner_email
    assert payload["installer_email"] == installer_email
    assert payload["deployer_email"] == deployer_email
    assert payload["bootstrap_admin_email"] == bootstrap_email
    assert payload["runtime_service_account"] == runtime_email
    assert payload["authentication_email"] == {
        "configured": bool(auth_email),
        "service": auth_service,
        "sender_email": auth_sender,
        "login": auth_login,
        "uses_installer": installer_controls_email,
    }
    assert "password" not in json.dumps(payload).casefold()
