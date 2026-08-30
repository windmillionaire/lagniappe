"""Anonymous directory and crawler discovery endpoints."""

from flask import Response, abort, make_response, render_template, url_for

from lagniappe import CONFIG
from lagniappe.core.exceptions import capture
from lagniappe.core.tools import cache
from lagniappe.core.tools.email.notifications.links import absolute_url
from lagniappe.core.tools.site import public_pages

from . import home


# @testable true
# @tests tests_e2e/002_home/test_002h_home_permissions.py::test_public_directory_renders_cached_page_groups
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_directory_lists_manual_in_collapsed_group
# @matrix public-directory : anonymous-access collapsible empty-state login manual metadata page-cards redis-cache
@home.route("/public/", methods=["GET"])
def public_directory():
    snapshot = cache.cached_public_directory(
        public_pages.public_directory_snapshot
    )
    groups = list(snapshot["groups"])
    if CONFIG.PUBLIC_MANUAL:
        groups.append(public_pages.manual_directory_group())
    groups.sort(key=lambda group: group["name"].casefold())

    has_content = any(group["pages"] for group in groups)
    indexing = snapshot["site_indexing"] and has_content
    title = f"Public — {CONFIG.APP_NAME}"
    description = f"Browse public pages from {CONFIG.APP_NAME}."
    metadata = {
        "canonical_url": absolute_url("/public/"),
        "title": title,
        "description": description,
        "robots": "index, follow" if indexing else "noindex, follow",
        "site_name": CONFIG.APP_NAME,
        "image": absolute_url(
            f"/images/logo-512x512.png?v={CONFIG.BUILD_ID}"
        ),
    }
    response = make_response(
        render_template(
            "public/index.html",
            groups=groups,
            has_content=has_content,
            metadata=metadata,
            login_url=url_for("users.login"),
        )
    )
    response.headers["X-Robots-Tag"] = metadata["robots"]
    return response


# @testable true
# @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_public_page_indexing_saves_live_setting
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_discovery_follows_live_setting
# @matrix public-pages robots : disabled enabled
# @matrix manual robots : disabled enabled fragment
@home.route("/robots.txt", methods=["GET"])
def robots():
    indexing = public_pages.runtime_settings()["PUBLIC_PAGE_INDEXING"]
    content = public_pages.robots_text(
        indexing,
        sitemap_url=absolute_url("/sitemap.xml"),
        public_manual=bool(CONFIG.PUBLIC_MANUAL),
    )
    return Response(content, mimetype="text/plain")


# @testable true
# @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_public_page_indexing_saves_live_setting
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_discovery_follows_live_setting
# @matrix public-pages sitemap : disabled enabled redis-cache
# @matrix manual sitemap : disabled enabled public-url
@home.route("/sitemap.xml", methods=["GET"])
def sitemap():
    snapshot = cache.cached_public_directory(
        public_pages.public_directory_snapshot
    )
    if not snapshot["site_indexing"]:
        abort(404)
    try:
        content = cache.cached_sitemap(
            lambda: public_pages.sitemap_xml(
                public_pages.discoverable_page_urls(snapshot)
                + (
                    public_pages.discoverable_manual_urls()
                    if CONFIG.PUBLIC_MANUAL
                    else []
                )
                + (
                    [absolute_url("/public/")]
                    if snapshot["groups"] or CONFIG.PUBLIC_MANUAL
                    else []
                )
            ),
            public_manual=bool(CONFIG.PUBLIC_MANUAL),
        )
    except public_pages.SitemapLimitError as error:
        capture(error, context={"operation": "public-sitemap-generate"})
        abort(503)
    return Response(content, mimetype="application/xml")
