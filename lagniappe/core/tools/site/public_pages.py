"""Public-page discovery, document-image, and social metadata services."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from config.public_pages import normalize_public_page_settings
from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import capture
from lagniappe.core.properties.page_public import normalize_public_settings
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import site as site_database
from lagniappe.core.tools.email.notifications.links import absolute_url
from lagniappe.core.tools.files.html import strip_tags
from lagniappe.core.tools.mentions.content import sanitize_mentions


SITEMAP_URL_LIMIT = 50_000


class SitemapLimitError(RuntimeError):
    """A single sitemap cannot safely represent all discoverable pages."""


@dataclass(frozen=True)
class DocumentImage:
    """One page-owned image that is actually embedded in its document."""

    name: str
    url: str
    alt: str
    content_type: str
    fingerprint: str | None
    extension: str | None


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_public_page_runtime_settings_prefer_live_datastore_and_fail_closed
# @matrix public-pages : config-fallback live-settings
def runtime_settings(config=CONFIG):
    """Read live site discovery settings, falling back to deployed config."""
    fallback = {
        "PUBLIC_PAGE_INDEXING": getattr(config, "PUBLIC_PAGE_INDEXING", False)
    }
    try:
        stored = site_database.public_pages()
        return normalize_public_page_settings(stored, current_settings=fallback)
    except Exception as error:
        capture(error, context={"operation": "public-page-settings-read"})
        return normalize_public_page_settings(fallback)


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_public_page_resolution_prefers_strong_reference_and_falls_back_for_existing_pages
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_public_document_images_are_anonymous_and_revocable
# @matrix public-pages : immediate-lookup legacy-fallback public-route
def resolve_page(public_id):
    """Resolve a public page immediately, with a query fallback for older links."""
    reference = site_database.public_page_reference(public_id)
    if reference and reference.get("page"):
        page = Entities.fetch_one(reference["page"], request=Fetch.root())
        if (
            page
            and page.db.get("public_id") == public_id
            and page.is_public
        ):
            return page

    candidates = Entities.fetch(
        *database_get.public_pages(public_id),
        request=Fetch.root(),
    )
    return next(
        (
            page
            for page in candidates
            if page.db.get("public_id") == public_id and page.is_public
        ),
        None,
    )


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_public_page_resolution_prefers_strong_reference_and_falls_back_for_existing_pages
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_public_document_images_are_anonymous_and_revocable
# @matrix public-pages : immediate-lookup public-route
def save_reference(page):
    """Record the strongly consistent page-key lookup for a public link."""
    site_database.save_public_page_reference(page.db["public_id"], page.key)


# @testable false
# @covered-by lagniappe/core/tools/site/public_pages.py::document_images
# @reason URL equivalence is exercised through document-image extraction
def _same_asset_url(source, asset_url):
    source = urlsplit(str(source or ""))
    target = urlsplit(str(asset_url or ""))
    if not source.path or source.path != target.path:
        return False
    return not target.netloc or source.netloc == target.netloc


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_public_document_images_only_include_embedded_page_assets
# @matrix public-pages : document-image privacy preview
def document_images(page):
    """Return unique page-owned document images in their document order."""
    soup = BeautifulSoup(page.properties.document.html or "", "html.parser")
    assets = {}
    for name, definition in page.assets.items():
        if not name.startswith("image_") or definition.get("type") != "image":
            continue
        asset = page.get_asset(name)
        if asset:
            assets[name] = asset

    candidates = []
    seen = set()
    for node in soup.find_all("img"):
        source = node.get("src")
        match = next(
            (
                (name, asset)
                for name, asset in assets.items()
                if _same_asset_url(source, asset.url)
            ),
            None,
        )
        if not match or match[0] in seen:
            continue
        name, asset = match
        seen.add(name)
        candidates.append(
            DocumentImage(
                name=name,
                url=asset.url,
                alt=str(node.get("alt") or "").strip(),
                content_type=asset.content_type,
                fingerprint=asset.fingerprint,
                extension=asset.extension,
            )
        )
    return candidates


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_public_document_rewrites_only_embedded_page_images
# @matrix public-pages : document-image public-rendering
def public_document_html(page, image_url):
    """Sanitize mentions and rewrite embedded private images to public URLs."""
    soup = BeautifulSoup(
        sanitize_mentions(page.properties.document.html or ""),
        "html.parser",
    )
    candidates = document_images(page)
    for node in soup.find_all("img"):
        candidate = next(
            (
                item
                for item in candidates
                if _same_asset_url(node.get("src"), item.url)
            ),
            None,
        )
        if candidate:
            node["src"] = image_url(candidate)
    return str(soup), candidates


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_public_metadata_uses_safe_fallbacks_and_selected_document_image
# @matrix public-pages : metadata privacy social-preview
def metadata(page, *, canonical_url, site_image_url, public_image_url, indexing):
    """Build privacy-safe canonical, robots, Open Graph, and Twitter metadata."""
    settings = normalize_public_settings(page.public_settings)
    document, candidates = public_document_html(page, public_image_url)
    title = settings["title"] or page.name
    description = settings["description"] or strip_tags(document)[:300].strip()
    description = description or f"Public page: {title}"
    selected = next(
        (
            candidate
            for candidate in candidates
            if candidate.name == settings["preview_image_asset"]
        ),
        None,
    )
    image = public_image_url(selected) if selected else site_image_url
    image_alt = (selected.alt if selected else "") or (
        f"Preview for {title}" if selected else f"{CONFIG.APP_NAME} site image"
    )
    return {
        "canonical_url": canonical_url,
        "title": title,
        "description": description,
        "robots": (
            "index, follow"
            if indexing and settings["allow_indexing"]
            else "noindex, follow"
        ),
        "site_name": CONFIG.APP_NAME,
        "image": image,
        "image_alt": image_alt,
        "image_type": selected.content_type if selected else "image/png",
        "image_width": None if selected else 512,
        "image_height": None if selected else 512,
        "twitter_card": "summary_large_image" if selected else "summary",
        "document": document,
    }


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_robots_text_allows_public_surface_and_advertises_enabled_sitemap
# @matrix public-pages robots : disabled enabled public-assets
def robots_text(indexing, *, sitemap_url):
    """Return crawler rules that block the app while allowing public surfaces."""
    lines = [
        "User-agent: *",
        "Disallow: /",
        "Allow: /pages/public/",
        "Allow: /style.css",
        "Allow: /script.js",
        "Allow: /chunks/",
        "Allow: /fonts/",
        "Allow: /images/",
        "Allow: /favicon.ico",
    ]
    if indexing:
        lines.extend(("Allow: /sitemap.xml", f"Sitemap: {sitemap_url}"))
    return "\n".join(lines) + "\n"


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_sitemap_xml_is_sorted_deduped_and_fails_closed_at_limit
# @matrix public-pages sitemap : dedupe limit sorted xml
def sitemap_xml(urls):
    """Build one deterministic URL-only sitemap, failing rather than truncating."""
    urls = sorted(set(urls))
    if len(urls) > SITEMAP_URL_LIMIT:
        raise SitemapLimitError(
            f"Public sitemap contains more than {SITEMAP_URL_LIMIT} URLs."
        )
    root = ElementTree.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for url in urls:
        entry = ElementTree.SubElement(root, "url")
        ElementTree.SubElement(entry, "loc").text = url
    return ElementTree.tostring(root, encoding="unicode", xml_declaration=True)


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_discoverable_page_urls_filter_nonpage_inactive_and_opted_out_rows
# @matrix public-pages sitemap : active opt-out public-url
def discoverable_page_urls():
    """Return trusted absolute URLs for currently indexable public pages."""
    pages = Entities.fetch(
        *database_get.discoverable_page_rows(),
        request=Fetch.root(),
    )
    urls = []
    for page in pages:
        if (
            getattr(page, "entity_kind", None) != "page"
            or not getattr(page, "active", False)
            or not page.is_public
            or not normalize_public_settings(page.public_settings)["allow_indexing"]
        ):
            continue
        public_id = page.db.get("public_id")
        if public_id:
            urls.append(absolute_url(f"/pages/public/{public_id}"))
    return urls
