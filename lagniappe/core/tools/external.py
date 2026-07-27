"""External URL metadata extraction (title, description, image)."""

from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests


# @testable false
# @covered-by lagniappe/core/tools/external.py::get_link_attributes
# @reason metadata parsing is owned by the external link metadata fetch workflow
def extract_link_metadata(content):
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

    return meta


# @testable false
# @covered-by lagniappe/core/tools/external.py::get_link_attributes
# @reason broken-link labeling is part of external link metadata fallback
def _broken_link_label(url: str) -> str:
    """Short display label when the URL cannot be fetched (HTTP error, timeout, etc.)."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return "Broken link"
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "Broken link"
    return f"Broken link - {host}"


# @testable false
# @covered-by lagniappe/core/properties/form_links.py::Link.value
# @reason external URL metadata fetch is owned by link field workflows
def get_link_attributes(url):
    """Fetch page metadata (title, description, image) from a URL via meta tags.

    If the request fails (404, other HTTP errors, timeout, network errors), returns
    metadata with a synthetic ``name`` from :func:`_broken_link_label` so callers
    can still show that a URL was stored.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.get(
            url, headers=headers, allow_redirects=True, timeout=0.5, stream=True
        )
        response.raise_for_status()

        return extract_link_metadata(response.text)
    except requests.RequestException:
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
