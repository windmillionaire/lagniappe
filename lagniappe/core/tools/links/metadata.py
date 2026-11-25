"""External URL metadata extraction (title, description, image)."""

from collections.abc import Mapping
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


def extract_link_metadata(content: str | bytes, *, base_url: str | None = None) -> dict[str, str | None]:
    """Extract page metadata (title, description, image) from HTML content."""
    soup = BeautifulSoup(content, "html.parser")
    tags = {
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

    name, description, image = tags["name"], tags["description"], tags["image"]
    title = name.get("content") if name and "content" in name.attrs else (name.string if name else None)
    summary = description.get("content") if description else None
    image_url = image.get("content") if image else None
    return {
        "name": title if isinstance(title, str) else None,
        "description": summary if isinstance(summary, str) else None,
        "image": (urljoin(base_url, image_url) if image_url and base_url else image_url)
        if isinstance(image_url, str) else None,
    }


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


def get_link_attributes(url: str) -> dict[str, str | None]:
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


def get_bookmark_metadata(data: Mapping[str, str]) -> dict[str, str | None]:
    """Fetch bookmark metadata, falling back to user-provided title."""
    if not data.get("url"):
        return {}

    metadata = get_link_attributes(data["url"])
    return {
        "name": metadata["name"] if metadata["name"] else data.get("title"),
        "description": metadata["description"],
        "image": metadata["image"],
    }
