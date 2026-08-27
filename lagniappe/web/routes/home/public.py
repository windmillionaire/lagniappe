"""Anonymous crawler discovery endpoints."""

from flask import Response, abort

from lagniappe import CONFIG
from lagniappe.core.exceptions import capture
from lagniappe.core.tools import cache
from lagniappe.core.tools.email.notifications.links import absolute_url
from lagniappe.core.tools.site import public_pages

from . import home


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_public_page_indexing_saves_live_setting
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
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_public_page_indexing_saves_live_setting
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_discovery_follows_live_setting
# @matrix public-pages sitemap : disabled enabled redis-cache
# @matrix manual sitemap : disabled enabled public-url
@home.route("/sitemap.xml", methods=["GET"])
def sitemap():
    if not public_pages.runtime_settings()["PUBLIC_PAGE_INDEXING"]:
        abort(404)
    try:
        content = cache.cached_sitemap(
            lambda: public_pages.sitemap_xml(
                public_pages.discoverable_page_urls()
                + (
                    public_pages.discoverable_manual_urls()
                    if CONFIG.PUBLIC_MANUAL
                    else []
                )
            ),
            public_manual=bool(CONFIG.PUBLIC_MANUAL),
        )
    except public_pages.SitemapLimitError as error:
        capture(error, context={"operation": "public-sitemap-generate"})
        abort(503)
    return Response(content, mimetype="application/xml")
