"""Static traceability for the shared semantic icon registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import yaml

from testing.utility import style_registry


SOURCE_ROOTS = (
    Path("src/script"),
    Path("lagniappe/core"),
    Path("lagniappe/web"),
    Path("config"),
    Path("installer"),
    Path("runner"),
)
SOURCE_SUFFIXES = {".html", ".mjs", ".py"}
DIRECT_DOTTED_RE = re.compile(
    r"(?<![A-Za-z0-9_/])(?:ICONS|icons)"
    r"(?P<path>(?:\.[A-Za-z][A-Za-z0-9]*)+)"
)
DIRECT_BRACKET_RE = re.compile(
    r"\b(?:ICONS|icons)\[\s*['\"](?P<path>[A-Za-z][A-Za-z0-9.]*)['\"]\s*\]"
)
CONTEXT_LITERAL_RE = re.compile(
    r"(?:\b(?:processingIcon|completedIcon)|\b_?icon|['\"]icon['\"])"
    r"\s*[:=]\s*['\"](?P<path>[A-Za-z][A-Za-z0-9.-]*)['\"]"
)
CONTEXT_ALTERNATIVES_RE = re.compile(
    r"(?:\b(?:processingIcon|completedIcon)|\bthis\.icon|\b_icon)\s*[:=]"
    r"|(?:\bicon|['\"]icon['\"])\s*:"
)
DATA_ICON_RE = re.compile(
    r"\bdata-(?:[A-Za-z0-9-]*-)?icon\s*=\s*['\"]"
    r"(?P<path>[A-Za-z][A-Za-z0-9.-]*)['\"]"
)
QUOTED_LITERAL_RE = re.compile(
    r"(['\"])(?P<path>[A-Za-z][A-Za-z0-9.-]*)\1"
)


@dataclass(frozen=True)
class IconReference:
    icon_id: str
    path: str
    line: int
    kind: str


@dataclass
class IconReport:
    definitions: dict[str, object]
    references: list[IconReference]
    used: list[str]
    unused: list[str]
    unknown: list[IconReference]


def _source_files(repo_root: Path):
    for source_root in SOURCE_ROOTS:
        root = repo_root / source_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(repo_root).as_posix()
            if relative.startswith(
                ("lagniappe/web/static/", "lagniappe/web/start/styles/")
            ):
                continue
            yield path, relative


def _line_references(
    line: str,
    path: str,
    line_number: int,
    definitions: set[str],
):
    seen: set[tuple[str, str]] = set()
    for pattern, kind in (
        (DIRECT_DOTTED_RE, "direct"),
        (DIRECT_BRACKET_RE, "direct"),
        (CONTEXT_LITERAL_RE, "context"),
        (DATA_ICON_RE, "context"),
    ):
        for match in pattern.finditer(line):
            icon_id = match.group("path").lstrip(".")
            if icon_id in {"get", "items", "keys", "values"}:
                continue
            key = (icon_id, kind)
            if key in seen:
                continue
            seen.add(key)
            yield IconReference(icon_id, path, line_number, kind)
    for match in QUOTED_LITERAL_RE.finditer(line):
        icon_id = match.group("path")
        key = (icon_id, "literal")
        if icon_id not in definitions or key in seen:
            continue
        seen.add(key)
        yield IconReference(icon_id, path, line_number, "literal")
    for context_match in CONTEXT_ALTERNATIVES_RE.finditer(line):
        value_start = context_match.end()
        value_text = line[value_start:].lstrip()
        if value_text.startswith(("{", "[")):
            continue
        value_end = line.find(",", value_start)
        if value_end < 0:
            value_end = len(line)
        for match in QUOTED_LITERAL_RE.finditer(line, value_start, value_end):
            icon_id = match.group("path")
            if icon_id == "icon":
                continue
            key = (icon_id, "context")
            if key in seen:
                continue
            seen.add(key)
            yield IconReference(icon_id, path, line_number, "context")


def build_report(
    repo_root: Path,
    *,
    definitions: dict[str, object] | None = None,
) -> IconReport:
    """Inventory direct icon access and literals feeding dynamic icon lookups."""
    if definitions is None:
        icons_path = repo_root / style_registry.DEFAULT_ICONS_PATH
        raw_icons = yaml.safe_load(icons_path.read_text(encoding="utf-8")) or {}
        definitions = style_registry.flatten_icon_definitions(
            raw_icons,
            schema=style_registry.load_icons_schema(repo_root),
        )

    references: list[IconReference] = []
    known = set(definitions)
    for source_path, relative in _source_files(repo_root):
        for line_number, line in enumerate(
            source_path.read_text(encoding="utf-8").splitlines(),
            1,
        ):
            references.extend(
                _line_references(line, relative, line_number, known)
            )

    references.sort(
        key=lambda item: (item.path, item.line, item.icon_id, item.kind)
    )
    used = sorted({item.icon_id for item in references} & known)
    unknown = [item for item in references if item.icon_id not in known]
    return IconReport(
        definitions=definitions,
        references=references,
        used=used,
        unused=sorted(known - set(used)),
        unknown=unknown,
    )


__all__ = ["IconReference", "IconReport", "build_report"]
