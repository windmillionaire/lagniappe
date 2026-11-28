"""Canonical, portable reference topics shared by contextual help, search and AI."""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import NotRequired, TypedDict

from bs4 import BeautifulSoup, Tag
import yaml

from lagniappe.core.definitions.manual import VALID_MANUAL_SECTIONS
from lagniappe.core.tools.files.html import SafeHTML, render_markdown, sanitize_html, strip_tags

TOPIC_DIRECTORY = Path(__file__).parent
PROJECTION_VERSION = "2"
TOPIC_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")

HELP_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "getting_started",
        "Getting Started & Workspace",
        "Moving around the workspace, personal pages, notes, and finding what you need.",
    ),
    (
        "pages_and_forms",
        "Pages, Forms & Projects",
        "Organizing information with categories, projects, forms, tables, documents, and files.",
    ),
    (
        "tasks_and_collaboration",
        "Tasks & Activity",
        "Managing repeatable work, schedules, submission history, and direct messages.",
    ),
    (
        "permissions_and_users",
        "Users, Permissions & Settings",
        "Accounts, passwords and security, groups, restrictions, and public access.",
    ),
    (
        "ai_and_automation",
        "AI Assistant & Connections",
        "On-site planning and answers, email submissions, and external AI integrations.",
    ),
    (
        "site_administration",
        "Site Administration",
        "Owner configuration for site access, AI models, analytics, public discovery, backups, and operations.",
    ),
)
VALID_HELP_CATEGORIES = frozenset(category_id for category_id, _, _ in HELP_CATEGORIES)


class TopicRecord(TypedDict):
    id: str
    title: str
    url: str
    markdown: str
    summary: str
    related: list[str]
    context: NotRequired[dict[str, str]]


class TopicCatalogEntry(TypedDict):
    id: str
    title: str
    category: str
    url: str
    summary: str


@dataclass(frozen=True)
class Topic:
    """One immutable article; installation-specific context is kept separate."""

    id: str
    title: str
    markdown: str
    summary: str
    text: str
    related: tuple[str, ...]
    category: str = "getting_started"
    keywords: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"/help/{self.id}"

    def as_dict(self) -> TopicRecord:
        return {
            "id": self.id, "title": self.title, "url": self.url,
            "markdown": self.markdown, "summary": self.summary,
            "related": list(self.related),
        }


@lru_cache(maxsize=1)
def _sources() -> tuple[tuple[str, bytes], ...]:
    return tuple((path.stem, path.read_bytes()) for path in sorted(TOPIC_DIRECTORY.glob("*.md")))


@lru_cache(maxsize=1)
def help_version() -> str:
    """Fingerprint source bytes without parsing Markdown on a warm startup."""
    digest = hashlib.sha256(PROJECTION_VERSION.encode())
    for topic_id, source in _sources():
        digest.update(topic_id.encode() + b"\0" + source + b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def topics() -> MappingProxyType[str, Topic]:
    """Load and validate the complete corpus once, without Flask or Redis."""
    loaded = {}
    for topic_id, source in _sources():
        if not TOPIC_ID.fullmatch(topic_id):
            raise ValueError(f"Invalid help topic ID: {topic_id}")
        parts = source.decode("utf-8").split("---\n", 2)
        if len(parts) != 3 or parts[0]:
            raise ValueError(f"Missing help metadata: {topic_id}")
        metadata = yaml.safe_load(parts[1])
        if not isinstance(metadata, dict) or set(metadata) - {"title", "related", "category", "keywords"}:
            raise ValueError(f"Invalid help metadata: {topic_id}")
        title = metadata.get("title")
        related = metadata.get("related", [])
        category = metadata.get("category", "getting_started")
        keywords = metadata.get("keywords", [])
        body = parts[2].strip()
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Missing help title: {topic_id}")
        if not isinstance(related, list) or any(not isinstance(item, str) for item in related):
            raise ValueError(f"Invalid related topics: {topic_id}")
        if len(set(related)) != len(related) or topic_id in related:
            raise ValueError(f"Duplicate or self-related help topic: {topic_id}")
        if not isinstance(category, str) or category not in VALID_HELP_CATEGORIES:
            raise ValueError(f"Invalid help category: {topic_id}")
        if not isinstance(keywords, list) or any(not isinstance(item, str) or not item.strip() for item in keywords):
            raise ValueError(f"Invalid help keywords: {topic_id}")
        normalized_keywords = tuple(item.strip() for item in keywords)
        if len(set(normalized_keywords)) != len(normalized_keywords):
            raise ValueError(f"Duplicate help keywords: {topic_id}")
        if not body or "{{" in body or "{%" in body:
            raise ValueError(f"Help must be static Markdown: {topic_id}")
        html = render_markdown(body)
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("h1") or not soup.contents or not isinstance(soup.contents[0], Tag) or soup.contents[0].name != "p":
            raise ValueError(f"Help must start with a summary paragraph and use level-two headings: {topic_id}")
        loaded[topic_id] = Topic(
            topic_id,
            title.strip(),
            body,
            strip_tags(str(soup.contents[0])),
            strip_tags(html),
            tuple(related),
            category=category,
            keywords=normalized_keywords,
        )
    if not loaded:
        raise ValueError("No help topics were packaged.")
    for topic in loaded.values():
        for related_id in topic.related:
            if related_id not in loaded:
                raise ValueError(f"Unknown related topic {related_id} in {topic.id}")
        for link in BeautifulSoup(render_markdown(topic.markdown), "html.parser").find_all("a", href=True):
            href = link["href"]
            if not isinstance(href, str):
                raise ValueError(f"Invalid help link in {topic.id}")
            if href.startswith("/help/") and href.removeprefix("/help/") not in loaded:
                raise ValueError(f"Unknown help link {href} in {topic.id}")
            if href.startswith("/manual/") and href.removeprefix("/manual/").split("#")[0] not in VALID_MANUAL_SECTIONS:
                raise ValueError(f"Unknown manual link {href} in {topic.id}")
    return MappingProxyType(loaded)


def get_topic(topic_id: str) -> Topic:
    """Resolve exactly one canonical ID, never a filename, alias or path."""
    if not isinstance(topic_id, str) or not TOPIC_ID.fullmatch(topic_id):
        raise KeyError(topic_id)
    return topics()[topic_id]


def grouped_topics() -> list[tuple[str, str, str, list[Topic]]]:
    """Return help topics grouped by canonical category for the help index."""
    by_category: dict[str, list[Topic]] = {category_id: [] for category_id, _, _ in HELP_CATEGORIES}
    for topic in topics().values():
        by_category[topic.category].append(topic)
    return [
        (category_id, title, description, sorted(items, key=lambda topic: topic.title.casefold()))
        for category_id, title, description in HELP_CATEGORIES
        if (items := by_category[category_id])
    ]


def topic_catalog() -> list[TopicCatalogEntry]:
    """Return a compact, category-ordered directory of help topics for discovery."""
    entries: list[TopicCatalogEntry] = []
    for category_id, _title, _description, items in grouped_topics():
        for topic in items:
            entries.append(
                {
                    "id": topic.id,
                    "title": topic.title,
                    "category": category_id,
                    "url": topic.url,
                    "summary": topic.summary,
                }
            )
    return entries


@lru_cache(maxsize=256)
def topic_html(topic_id: str, *, embedded: bool = False) -> SafeHTML:
    """Render the reference body with headings appropriate to its wrapper."""
    soup = BeautifulSoup(render_markdown(get_topic(topic_id).markdown), "html.parser")
    if embedded:
        for heading in soup.find_all(re.compile(r"h[2-5]")):
            heading.name = f"h{int(heading.name[1]) + 1}"
    return sanitize_html(str(soup))


@lru_cache(maxsize=256)
def topic_sections(topic_id: str, *, embedded: bool = False) -> tuple[SafeHTML, ...]:
    """Split the safe body into introduction and details for template wrappers."""
    clean = BeautifulSoup(topic_html(topic_id, embedded=embedded), "html.parser")
    nodes = list(clean.contents)
    heading_level = "h3" if embedded else "h2"
    has_sections = any(getattr(node, "name", None) == heading_level for node in nodes)
    sections = [[]]
    summary_open = True
    for node in nodes:
        if not str(node).strip():
            continue
        heading = getattr(node, "name", None) == heading_level
        if heading or (summary_open and not has_sections and sections[-1]):
            sections.append([])
            summary_open = False
        sections[-1].append(str(node))
    return tuple(sanitize_html("".join(section)) for section in sections)


def topic_context(topic_id: str, user: object | None = None) -> dict[str, str]:
    """Return safe installation context only for an authenticated reader."""
    if not user or not getattr(user, "is_authenticated", False):
        return {}
    if topic_id == "ai_email":
        from lagniappe import CONFIG

        public = CONFIG.AI_EMAIL_PUBLIC
        if public.get("enabled"):
            return {"email_address": public["addresses"]["ai"]}
    if topic_id == "external_ai" and not getattr(user, "is_public", True):
        from lagniappe import CONFIG

        if CONFIG.AI_ENABLED and CONFIG.EXTERNAL_AI_ENABLED:
            origin = f"https://{CONFIG.CUSTOM_DOMAIN}" if CONFIG.CUSTOM_DOMAIN else CONFIG.APP_URL
            context = {"skill_url": f"{origin.rstrip('/')}/api/v1/client-skill.md"}
            if CONFIG.MCP_RESOURCE:
                context.update(mcp_url=CONFIG.MCP_RESOURCE, connection_name=CONFIG.MCP_NAME)
            return context
    return {}
