"""Crawler discovery coverage for the optional public manual."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from lagniappe.core.definitions.manual import MANUAL_SECTIONS
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import site as site_database
from lagniappe.core.tools.email.notifications.links import absolute_url
from testing.definitions import Users


pytestmark = pytest.mark.e2e


# @template manual/index.html::main
# @template manual/index.html::mobile_nav
# @template manual/index.html::nav_column
# @matrix manual : ajax-section anonymous-access canonical-url direct-section metadata noindex page-load popstate section-navigation
def test_public_manual_search_metadata_and_navigation(get_user):
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")

    response = anonymous.page.goto(
        f"{base_url}/manual/security",
        wait_until="load",
    )

    assert response.ok
    expect(anonymous.page).to_have_title(f"Security — {CONFIG.APP_NAME} Manual")
    expect(anonymous.locate("meta[name='description']")).to_have_attribute(
        "content",
        f"Read the Security section of the {CONFIG.APP_NAME} manual.",
    )
    canonical = anonymous.locate("link[rel='canonical']").get_attribute("href")
    assert urlparse(canonical).path == "/manual/security"
    robots = anonymous.locate("meta[name='robots']").get_attribute("content")
    assert robots in {"index, follow", "noindex, follow"}
    assert response.headers["x-robots-tag"] == robots

    with anonymous.page.expect_response("**/manual/section/forms") as response_info:
        anonymous.page.locator("button[data-section='forms']").first.click()
    fragment = response_info.value

    assert fragment.status == 200
    assert fragment.headers["x-robots-tag"] == "noindex, nofollow"
    expect(anonymous.page).to_have_url(f"{base_url}/manual/forms")
    expect(anonymous.page).to_have_title(f"Forms — {CONFIG.APP_NAME} Manual")
    expect(anonymous.locate("meta[name='description']")).to_have_attribute(
        "content",
        f"Read the Forms section of the {CONFIG.APP_NAME} manual.",
    )
    canonical = anonymous.locate("link[rel='canonical']").get_attribute("href")
    assert urlparse(canonical).path == "/manual/forms"

    with anonymous.page.expect_response("**/manual/section/tasks"):
        anonymous.page.locator("button[data-section='tasks']").first.click()
    expect(anonymous.page).to_have_url(f"{base_url}/manual/tasks")
    expect(anonymous.page).to_have_title(f"Tasks — {CONFIG.APP_NAME} Manual")

    with anonymous.page.expect_response("**/manual/section/forms"):
        anonymous.page.go_back()
    expect(anonymous.page).to_have_url(f"{base_url}/manual/forms")
    expect(anonymous.page).to_have_title(f"Forms — {CONFIG.APP_NAME} Manual")
    expect(anonymous.locate("meta[name='description']")).to_have_attribute(
        "content",
        f"Read the Forms section of the {CONFIG.APP_NAME} manual.",
    )
    canonical = anonymous.locate("link[rel='canonical']").get_attribute("href")
    assert urlparse(canonical).path == "/manual/forms"


# @matrix manual robots : disabled enabled fragment
# @matrix manual sitemap : disabled enabled public-url
# @matrix public-pages robots : disabled enabled
# @matrix public-pages sitemap : disabled enabled redis-cache
# @pair manual:search-discovery
def test_public_manual_discovery_follows_live_setting(get_user):
    assert CONFIG.PUBLIC_MANUAL is True
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")
    request = anonymous.page.context.request
    stored = site_database.public_pages()
    original = (
        bool(stored.get("PUBLIC_PAGE_INDEXING"))
        if stored
        else bool(getattr(CONFIG, "PUBLIC_PAGE_INDEXING", False))
    )

    def set_indexing(enabled):
        site_database.save_public_pages({"PUBLIC_PAGE_INDEXING": enabled})
        cache.invalidate_sitemap()

    try:
        set_indexing(True)
        robots = request.get(f"{base_url}/robots.txt")
        assert robots.status == 200
        assert "Allow: /manual/" in robots.text()
        assert "Disallow: /manual/section/" in robots.text()
        assert f"Sitemap: {absolute_url('/sitemap.xml')}" in robots.text()

        sitemap = request.get(f"{base_url}/sitemap.xml")
        assert sitemap.status == 200
        cached_sitemap = request.get(f"{base_url}/sitemap.xml")
        assert cached_sitemap.status == 200
        assert cached_sitemap.text() == sitemap.text()
        for section in MANUAL_SECTIONS:
            path = (
                "/manual/"
                if section["key"] == "overview"
                else f"/manual/{section['key']}"
            )
            assert f"<loc>{absolute_url(path)}</loc>" in sitemap.text()
        assert "/manual/overview" not in sitemap.text()
        assert "/manual/section/" not in sitemap.text()

        enabled_manual = request.get(f"{base_url}/manual/security")
        assert enabled_manual.status == 200
        assert enabled_manual.headers["x-robots-tag"] == "index, follow"

        set_indexing(False)
        robots = request.get(f"{base_url}/robots.txt")
        assert "Allow: /manual/" in robots.text()
        assert "Disallow: /manual/section/" in robots.text()
        assert "Sitemap:" not in robots.text()
        assert request.get(f"{base_url}/sitemap.xml").status == 404

        disabled_manual = request.get(f"{base_url}/manual/security")
        assert disabled_manual.status == 200
        assert disabled_manual.headers["x-robots-tag"] == "noindex, follow"
    finally:
        set_indexing(original)
