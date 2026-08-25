"""External URL metadata extraction (title, description, image)."""

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import HTML_METADATA_POLICY, fetch_user_content


METADATA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# @testable false
# @covered-by lagniappe/core/tools/links/metadata.py::get_link_attributes
# @reason metadata parsing is owned by the external link metadata fetch workflow
def extract_link_metadata(content, *, base_url=None):
    """Extract page metadata (title, description, image) from HTML content."""
    soup = BeautifulSoup(content, "html.parser")
    meta = {
        "name": (
            soup.find("meta", {"name": "title"})
            or soup.find("meta", property="og:title")
            or soup.find("meta", {"name": "twitter:title"})
            or soup.find("title")
        ),
        "description": (
            soup.find("meta", {"name": "description"})
            or soup.find("meta", property="og:description")
            or soup.find("meta", {"name": "twitter:description"})
        ),
        "image": (
            soup.find("meta", {"name": "image"})
            or soup.find("meta", property="og:image")
            or soup.find("meta", {"name": "twitter:image"})
        ),
    }

    if meta["name"] and "content" in meta["name"].attrs:
        meta["name"] = meta["name"].get("content")
    elif meta["name"]:
        meta["name"] = meta["name"].string

    if meta["description"]:
        meta["description"] = meta["description"].get("content")

    if meta["image"]:
        meta["image"] = meta["image"].get("content")
        if meta["image"] and base_url:
            meta["image"] = urljoin(base_url, meta["image"])

    return meta


# @testable false
# @covered-by lagniappe/core/tools/links/metadata.py::get_link_attributes
# @reason broken-link labeling is part of external link metadata fallback
def _broken_link_label(url: str) -> str:
    """Short display label when the URL cannot be fetched (HTTP error, timeout, etc.)."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return "Broken link"
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "Broken link"
    return f"Broken link - {host}"


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_link_metadata_uses_typed_fetch_and_resolves_relative_images
# @pairs link:metadata bookmark:metadata link:relative-image link:fallback outbound-http:privacy
def get_link_attributes(url):
    """Fetch page metadata (title, description, image) from a URL via meta tags.

    If the request fails (404, other HTTP errors, timeout, network errors), returns
    metadata with a synthetic ``name`` from :func:`_broken_link_label` so callers
    can still show that a URL was stored.
    """
    result = fetch_user_content(url, HTML_METADATA_POLICY, headers=METADATA_HEADERS)
    if result.ok:
        try:
            return extract_link_metadata(result.body, base_url=result.final_url)
        except Exception:
            pass
    return {
        "name": _broken_link_label(url),
        "description": None,
        "image": None,
    }


# @testable false
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.validate_submission
# @reason external bookmark metadata fetch is owned by bookmark submission workflows
def get_bookmark_metadata(data):
    """Fetch bookmark metadata, falling back to user-provided title."""
    if not data.get("url"):
        return {}

    metadata = get_link_attributes(data["url"])
    return {
        "name": metadata["name"] if metadata["name"] else data.get("title"),
        "description": metadata["description"],
        "image": metadata["image"],
    }
