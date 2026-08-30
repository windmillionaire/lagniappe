import re
from pathlib import Path

import pytest
from playwright.sync_api import expect
import yaml

from config import recovery
from lagniappe import CONFIG
from lagniappe.core.tools.database import site as site_database
from lagniappe.core.tools.email.notifications.links import absolute_url
from testing.definitions import Users
from testing.elements import FormElements, Modal
from testing.utility.network import browser_fetch
from testing.utility.site_settings import (
    open_owner_site_settings,
    open_site_settings_section,
    site_settings_section,
)

pytestmark = pytest.mark.e2e


def _open_help_and_expect(user, trigger, text):
    modal = Modal(user.page).open(trigger)
    expect(modal.element).to_contain_text(text)
    modal.close()


def _select_deployment_option(user, form, field_name, option_name):
    select = form.locator(
        f"[data-role='deployment-select']:has(select[name='{field_name}'])"
    )
    select.locator("input[role='combobox']").click()
    user.page.get_by_role("option", name=option_name, exact=True).click()


def _select_ai_option(user, form, field_name, option_value):
    select = form.locator(f"[data-role='ai-select']:has(select[name='{field_name}'])")
    option_name = select.locator(
        f"select option[value='{option_value}']"
    ).text_content()
    select.locator("input[role='combobox']").click()
    user.page.get_by_role("option", name=option_name, exact=True).click()


def _assert_site_image_links(site_image, image_data):
    required_filenames = {
        "favicon-16x16.png",
        "favicon-32x32.png",
        "favicon.ico",
        "apple-touch-icon.png",
        "logo-192x192.png",
        "logo-512x512.png",
    }
    assert required_filenames.issubset(image_data)
    displayed_images = {
        filename: url
        for filename, url in image_data.items()
        if not filename.startswith("splash-")
    }

    preview = site_image.locator("img[alt='Site image']")
    expect(preview).to_be_visible()
    expect(preview).to_have_attribute("src", re.compile(r"/images/"))
    expect(preview).to_have_js_property("complete", True)
    assert preview.evaluate("(image) => image.naturalWidth") > 0
    expect(site_image.locator("a")).to_have_count(len(displayed_images))
    for filename, url in displayed_images.items():
        link = site_image.locator("a", has_text=filename)
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", url)


# @matrix admin : configuration-display configuration-modal environment-variables external-links recovery-export secrets sections service-providers site-settings web-headers
# @template home/admin.html::main
# @template home/site_settings.html::site_settings
def test_site_settings_sections_expand_help_and_configuration(get_user):
    owner = get_user(Users.OWNER)
    _, settings_panel = open_owner_site_settings(owner)

    maintenance = site_settings_section(settings_panel, "maintenance")
    installation_access = site_settings_section(settings_panel, "installation-access")
    deployment = site_settings_section(settings_panel, "deployment")
    ai_models = site_settings_section(settings_panel, "ai-models")
    providers = site_settings_section(settings_panel, "service-providers")
    site_image = site_settings_section(settings_panel, "site-image")

    expect(maintenance).to_have_attribute("data-open", "true")
    expect(installation_access).to_have_attribute("data-open", "false")
    expect(deployment).to_have_attribute("data-open", "false")
    expect(ai_models).to_have_attribute("data-open", "false")
    expect(providers).to_have_attribute("data-open", "false")
    expect(site_image).to_have_attribute("data-open", "false")
    _open_help_and_expect(
        owner,
        maintenance.locator("button[lp-help='site_maintenance']"),
        "Refresh Cache",
    )

    open_site_settings_section(settings_panel, "installation-access")
    _open_help_and_expect(
        owner,
        installation_access.locator("button[lp-help='site_installation_access']"),
        "Why there is no Remove IAM button",
    )

    open_site_settings_section(settings_panel, "deployment")
    _open_help_and_expect(
        owner,
        deployment.locator("button[lp-help='site_deployment']"),
        "Scaling",
    )

    open_site_settings_section(settings_panel, "ai-models")
    expect(deployment).to_have_attribute("data-open", "false")
    expect(ai_models).to_have_attribute("data-open", "true")
    expect(ai_models.locator("input[role='combobox']")).to_have_count(3)
    expect(ai_models.locator("[data-role='section-summary']")).to_contain_text(
        "utility"
    )
    _open_help_and_expect(
        owner,
        ai_models.locator("button[lp-help='site_ai_models']"),
        "Primary",
    )

    open_site_settings_section(settings_panel, "service-providers")
    expect(ai_models).to_have_attribute("data-open", "false")
    expect(providers).to_have_attribute("data-open", "true")
    expect(providers).to_contain_text("Google Cloud Console")
    _open_help_and_expect(
        owner,
        providers.locator("button[lp-help='site_service_providers']"),
        "outside services",
    )

    open_site_settings_section(settings_panel, "site-image")
    _open_help_and_expect(
        owner,
        site_image.locator("button[lp-help='site_image']"),
        "browser tabs",
    )

    open_site_settings_section(settings_panel, "maintenance")
    modal = Modal(owner.page).open(
        settings_panel.locator("[data-role='configuration']")
    )
    expect(modal.element).to_contain_text("Warning")
    expect(modal.element).to_contain_text("APP_NAME")
    expect(
        modal.element.get_by_role("link", name="Download Settings File")
    ).to_be_visible()
    expect(modal.element).to_contain_text(recovery.REDACTED_VALUE)
    download_link = modal.element.get_by_role("link", name="Download Settings File")
    with owner.page.expect_response("**/reference/download-settings") as response_info:
        with owner.page.expect_download() as download_info:
            download_link.click()
    response = response_info.value
    download = download_info.value
    downloaded = yaml.safe_load(Path(download.path()).read_text())
    assert response.status == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["content-type"].startswith("application/yaml")
    assert downloaded["CONFIG_KIND"] == recovery.CONFIG_KIND
    assert downloaded["CONFIG_SCHEMA_VERSION"] == recovery.CONFIG_SCHEMA_VERSION
    live_deployment = site_database.deployment()
    if live_deployment:
        assert (
            downloaded["DEPLOY_MAX_INSTANCES"]
            == dict(live_deployment)["DEPLOY_MAX_INSTANCES"]
        )
    live_ai = site_database.ai()
    if live_ai:
        assert downloaded["AI_MODEL"] == dict(live_ai)["AI_MODEL"]
    modal.close()


# @matrix admin : deployment-settings metadata scaling-controls validation
# @template home/site_settings.html::site_settings
def test_site_settings_deployment_form_saves_and_updates_summary(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    _, settings_panel = open_owner_site_settings(owner)

    deployment = open_site_settings_section(settings_panel, "deployment")
    form = deployment.locator("[data-role='deployment-settings']")

    expect(
        form.locator("[data-role='deployment-select'] input[role='combobox']")
    ).to_have_count(2)
    _select_deployment_option(owner, form, "DEPLOY_SCALING_TYPE", "Basic")
    _select_deployment_option(owner, form, "DEPLOY_SCALING_TYPE", "Automatic")
    expect(form.locator("select[name='DEPLOY_INSTANCE_CLASS']")).to_have_value("F2")
    expect(form.locator("[data-role='automatic-instance-counts']")).to_be_visible()
    form.locator("input[name='DEPLOY_WORKER_COUNT']").fill("3")
    form.locator("input[name='DEPLOY_MIN_IDLE_INSTANCES']").fill("1")
    form.locator(
        "[data-role='automatic-instance-counts'] input[name='DEPLOY_MAX_INSTANCES']"
    ).fill("2")

    with owner.page.expect_response("**/l/set-deployment-settings") as response_info:
        form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.ok, response.text()
    deployment_data = response.json()["deployment"]
    assert deployment_data == {
        "DEPLOY_SCALING_TYPE": "automatic",
        "DEPLOY_WORKER_COUNT": "3",
        "DEPLOY_INSTANCE_CLASS": "F2",
        "DEPLOY_MAX_INSTANCES": "2",
        "DEPLOY_MIN_IDLE_INSTANCES": "1",
        "DEPLOY_IDLE_TIMEOUT": "15m",
    }

    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "Automatic"
    )
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "3 workers"
    )
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text("F2")
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "1 min idle"
    )
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "2 max instances"
    )

    with browser_failures.expect_http_error(
        owner,
        status=422,
        path="/l/set-deployment-settings",
    ):
        rejected = browser_fetch(
            owner,
            "/l/set-deployment-settings",
            data={**deployment_data, "DEPLOY_WORKER_COUNT": "0"},
        )
    assert rejected["status"] == 422
    assert "Worker count" in rejected["text"]


# @matrix admin : ai-settings metadata model-selection saved-values validation
# @template home/site_settings.html::site_settings
def test_site_settings_ai_form_saves_current_models_through_route(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    admin, settings_panel = open_owner_site_settings(owner)
    ai_models = open_site_settings_section(settings_panel, "ai-models")
    form = ai_models.locator("[data-role='ai-settings']")

    primary = form.locator("select[name='AI_MODEL']")
    current_primary = primary.input_value()
    primary_options = primary.locator("option").evaluate_all(
        "options => options.map(option => option.value)"
    )
    selected_primary = next(
        (option for option in primary_options if option != current_primary),
        None,
    )
    assert selected_primary, "AI model chooser did not offer an alternate model"
    _select_ai_option(owner, form, "AI_MODEL", selected_primary)
    expect(primary).to_have_value(selected_primary)

    expected = {
        name: form.locator(f"[name='{name}']").input_value()
        for name in (
            "AI_MODEL",
            "AI_UTILITY_MODEL",
            "AI_IMAGE_MODEL",
            "AI_LOCATION",
        )
    }

    with owner.page.expect_response("**/l/set-ai-settings") as response_info:
        form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.status == 200
    assert response.json()["ai_settings"] == expected
    expect(form.locator("button[type='submit']")).to_contain_text(
        "AI Model Settings Saved"
    )
    saved = dict(site_database.ai())
    assert {name: saved[name] for name in expected} == expected

    owner.page.reload(wait_until="domcontentloaded")
    reloaded_settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(reloaded_settings_panel).to_have_attribute("initialized", "")
    reloaded_ai_models = open_site_settings_section(
        reloaded_settings_panel,
        "ai-models",
    )
    reloaded_form = reloaded_ai_models.locator("[data-role='ai-settings']")
    for name, value in expected.items():
        expect(reloaded_form.locator(f"[name='{name}']")).to_have_value(value)

    with browser_failures.expect_http_error(
        owner,
        status=422,
        path="/l/set-ai-settings",
    ):
        rejected = browser_fetch(
            owner,
            "/l/set-ai-settings",
            data={**expected, "AI_LOCATION": "not-global"},
        )
    assert rejected["status"] == 422
    assert "global" in rejected["text"]


# @matrix admin public-pages : live-settings sitemap-invalidation validation
# @matrix public-pages sitemap : disabled enabled redis-cache
# @matrix robots : disabled enabled
# @template home/site_settings.html::site_settings
def test_site_settings_public_page_indexing_saves_live_setting(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    _, settings_panel = open_owner_site_settings(owner)
    section = open_site_settings_section(settings_panel, "public-pages")
    form = section.locator("[data-role='public-page-settings']")
    field = form.locator("[name='PUBLIC_PAGE_INDEXING']")
    stored = site_database.public_pages()
    original = (
        bool(stored.get("PUBLIC_PAGE_INDEXING"))
        if stored
        else bool(getattr(CONFIG, "PUBLIC_PAGE_INDEXING", False))
    )
    loaded = browser_fetch(owner, "/l/site-settings/public-pages", "GET")
    assert loaded["status"] == 200
    assert loaded["data"]["public_pages"]["PUBLIC_PAGE_INDEXING"] is original

    def save(enabled):
        field.set_checked(enabled)
        with owner.page.expect_response(
            "**/l/site-settings/public-pages"
        ) as response_info:
            form.locator("button[type='submit']").click()
        response = response_info.value
        assert response.status == 200
        assert response.json()["public_pages"]["PUBLIC_PAGE_INDEXING"] is enabled
        expect(section.locator("[data-role='section-summary']")).to_have_text(
            f"Search discovery is {'on' if enabled else 'off'}"
        )

    try:
        save(True)
        assert site_database.public_pages()["PUBLIC_PAGE_INDEXING"] is True
        origin = owner.page.evaluate("location.origin")

        robots = owner.page.context.request.get(f"{origin}/robots.txt")
        assert robots.status == 200
        assert "Allow: /pages/public/" in robots.text()
        assert f"Sitemap: {absolute_url('/sitemap.xml')}" in robots.text()

        first_sitemap = owner.page.context.request.get(f"{origin}/sitemap.xml")
        second_sitemap = owner.page.context.request.get(f"{origin}/sitemap.xml")
        assert first_sitemap.status == second_sitemap.status == 200
        assert first_sitemap.text() == second_sitemap.text()
        assert "<urlset" in first_sitemap.text()

        with browser_failures.expect_http_error(
            owner,
            status=422,
            path="/l/site-settings/public-pages",
        ):
            rejected = browser_fetch(
                owner,
                "/l/site-settings/public-pages",
                data={"PUBLIC_PAGE_INDEXING": "sometimes"},
            )
        assert rejected["status"] == 422

        save(False)
        disabled_robots = owner.page.context.request.get(f"{origin}/robots.txt")
        assert "Sitemap:" not in disabled_robots.text()
        disabled_sitemap = owner.page.context.request.get(f"{origin}/sitemap.xml")
        assert disabled_sitemap.status == 404
    finally:
        if field.is_checked() is not original:
            save(original)


# @matrix admin : site-update success
# @pair cache:current
# @template home/site_settings.html::site_settings
def test_site_maintenance_update_and_cache_refresh_use_real_routes(get_user):
    owner = get_user(Users.OWNER)
    _, settings_panel = open_owner_site_settings(owner)
    maintenance = open_site_settings_section(settings_panel, "maintenance")

    update = browser_fetch(owner, "/l/site-update", method="POST")
    assert update["status"] == 200
    assert update["data"]["migration_status"]["status"] == "current"

    cache_button = maintenance.locator("[data-role='rebuild-cache']")
    expect(cache_button).to_be_enabled()
    with owner.page.expect_response("**/l/rebuild-cache") as response_info:
        cache_button.click()
    assert response_info.value.status == 200
    expect(cache_button).to_contain_text("Cache Refreshed")


# @matrix admin : generated-images lazy-initialization metadata public-preview site-image-upload
# @template home/site_settings.html::site_settings
def test_site_settings_image_upload_generates_and_persists_site_images(get_user):
    owner = get_user(Users.OWNER)
    admin, settings_panel = open_owner_site_settings(owner)

    upload_form = settings_panel.locator("[data-role='upload-site-image']")
    expect(upload_form).not_to_have_attribute("rendered", "")

    open_site_settings_section(settings_panel, "site-image")
    expect(upload_form).to_have_attribute("rendered", "")

    image_path = Path("testing/files/site_image_test_image.jpeg").resolve()
    upload_form.locator(FormElements.FILE_INPUT).set_input_files(str(image_path))
    expect(upload_form.locator("[data-role='dropzone']")).to_contain_text(
        "site_image_test_image"
    )

    with owner.page.expect_response("**/l/set-site-image") as response_info:
        upload_form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.ok, response.text()
    image_data = response.json()["site_image"]
    assert "favicon-32x32.png" in image_data
    assert "apple-touch-icon.png" in image_data
    assert "logo-192x192.png" in image_data

    site_image = settings_panel.locator("[data-role='site-image']")
    _assert_site_image_links(site_image, image_data)

    owner.reload(admin)
    settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(settings_panel).to_be_visible()
    open_site_settings_section(settings_panel, "site-image")

    persisted_site_image = settings_panel.locator("[data-role='site-image']")
    _assert_site_image_links(persisted_site_image, image_data)
