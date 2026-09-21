"""Canonical, portable reference topics shared by contextual help, search and AI."""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from types import MappingProxyType

from bs4 import BeautifulSoup
import yaml

from lagniappe.core.definitions.manual import VALID_MANUAL_SECTIONS
from lagniappe.core.tools.files.html import render_markdown, sanitize_html, strip_tags

TOPIC_DIRECTORY = Path(__file__).parent
PROJECTION_VERSION = "1"
TOPIC_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")


# @testable false
# @covered-by lagniappe/reference/__init__.py::topics
# @reason immutable data record populated by the validated corpus loader
@dataclass(frozen=True)
class Topic:
    """One immutable article; installation-specific context is kept separate."""

    id: str
    title: str
    markdown: str
    summary: str
    text: str
    related: tuple[str, ...]

    # @testable false
    # @covered-by lagniappe/reference/__init__.py::get_topic
    # @reason canonical address is part of the topic lookup contract
    @property
    def url(self):
        return f"/help/{self.id}"

    # @testable true
    # @tests tests_unit/test_035_help.py::test_topics_are_canonical_and_portable
    # @pair help:canonical-source
    def as_dict(self):
        return {
            "id": self.id, "title": self.title, "url": self.url,
            "markdown": self.markdown, "summary": self.summary,
            "related": list(self.related),
        }


# @testable false
# @covered-by lagniappe/reference/__init__.py::help_version
# @covered-by lagniappe/reference/__init__.py::topics
# @reason deployed source snapshot is immutable for the life of a process
@lru_cache(maxsize=1)
def _sources():
    return tuple((path.stem, path.read_bytes()) for path in sorted(TOPIC_DIRECTORY.glob("*.md")))


# @testable true
# @tests tests_unit/test_035_help.py::test_help_version_changes_with_source_without_rendering
# @pair help:version
@lru_cache(maxsize=1)
def help_version():
    """Fingerprint source bytes without parsing Markdown on a warm startup."""
    digest = hashlib.sha256(PROJECTION_VERSION.encode())
    for topic_id, source in _sources():
        digest.update(topic_id.encode() + b"\0" + source + b"\0")
    return digest.hexdigest()


# @testable true
# @tests tests_unit/test_035_help.py::test_topics_are_canonical_and_portable
# @tests tests_unit/test_035_help.py::test_invalid_topic_sources_fail_validation
# @matrix help : canonical-source validation
@lru_cache(maxsize=1)
def topics():
    """Load and validate the complete corpus once, without Flask or Redis."""
    loaded = {}
    for topic_id, source in _sources():
        if not TOPIC_ID.fullmatch(topic_id):
            raise ValueError(f"Invalid help topic ID: {topic_id}")
        parts = source.decode("utf-8").split("---\n", 2)
        if len(parts) != 3 or parts[0]:
            raise ValueError(f"Missing help metadata: {topic_id}")
        metadata = yaml.safe_load(parts[1])
        if not isinstance(metadata, dict) or set(metadata) - {"title", "related"}:
            raise ValueError(f"Invalid help metadata: {topic_id}")
        title = metadata.get("title")
        related = metadata.get("related", [])
        body = parts[2].strip()
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Missing help title: {topic_id}")
        if not isinstance(related, list) or any(not isinstance(item, str) for item in related):
            raise ValueError(f"Invalid related topics: {topic_id}")
        if len(set(related)) != len(related) or topic_id in related:
            raise ValueError(f"Duplicate or self-related help topic: {topic_id}")
        if not body or "{{" in body or "{%" in body:
            raise ValueError(f"Help must be static Markdown: {topic_id}")
        html = render_markdown(body)
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("h1") or not soup.contents or soup.contents[0].name != "p":
            raise ValueError(f"Help must start with a summary paragraph and use level-two headings: {topic_id}")
        loaded[topic_id] = Topic(
            topic_id, title.strip(), body, strip_tags(str(soup.contents[0])),
            strip_tags(html), tuple(related),
        )
    if not loaded:
        raise ValueError("No help topics were packaged.")
    for topic in loaded.values():
        for related_id in topic.related:
            if related_id not in loaded:
                raise ValueError(f"Unknown related topic {related_id} in {topic.id}")
        for link in BeautifulSoup(render_markdown(topic.markdown), "html.parser").find_all("a", href=True):
            href = link["href"]
            if href.startswith("/help/") and href.removeprefix("/help/") not in loaded:
                raise ValueError(f"Unknown help link {href} in {topic.id}")
            if href.startswith("/manual/") and href.removeprefix("/manual/").split("#")[0] not in VALID_MANUAL_SECTIONS:
                raise ValueError(f"Unknown manual link {href} in {topic.id}")
    return MappingProxyType(loaded)


# @testable true
# @tests tests_unit/test_035_help.py::test_topics_are_canonical_and_portable
# @tests tests_unit/test_035_help.py::test_topic_lookup_rejects_aliases_and_paths
# @pair help:canonical-source
def get_topic(topic_id):
    """Resolve exactly one canonical ID, never a filename, alias or path."""
    if not isinstance(topic_id, str) or not TOPIC_ID.fullmatch(topic_id):
        raise KeyError(topic_id)
    return topics()[topic_id]


# @testable true
# @tests tests_unit/test_035_help.py::test_topic_rendering_preserves_safety_and_links
# @pair help:rendering
@lru_cache(maxsize=256)
def topic_html(topic_id, *, embedded=False):
    """Render the reference body with headings appropriate to its wrapper."""
    soup = BeautifulSoup(render_markdown(get_topic(topic_id).markdown), "html.parser")
    if embedded:
        for heading in soup.find_all(re.compile(r"h[2-5]")):
            heading.name = f"h{int(heading.name[1]) + 1}"
    return sanitize_html(str(soup))


# @testable true
# @tests tests_unit/test_035_help.py::test_topic_rendering_preserves_safety_and_links
# @pair help:rendering
@lru_cache(maxsize=256)
def topic_sections(topic_id, *, embedded=False):
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


# @testable true
# @tests tests_unit/test_035_help.py::test_context_is_separate_and_requires_authenticated_user
# @pair help:context-permissions
def topic_context(topic_id, user=None):
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
