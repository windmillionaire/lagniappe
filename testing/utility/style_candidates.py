"""Advisory style candidates for semantic traceability.

This is an informational static audit. It compares the shared ``styles.yaml``
definitions with style references and literal class strings in ``src/`` and
``lagniappe/web/templates/``. It does not inspect generated assets or rendered
DOM; the goal is to point humans and agents at likely style-system cleanup.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable

from testing.utility.artifacts import (
    markdown_code,
    markdown_escape,
    markdown_list,
    markdown_more_line,
    markdown_section_count,
)
from testing.utility.style_registry import (
    DEFAULT_STYLES_PATH,
    StyleDefinition,
    flatten_style_definitions as flatten_style_definitions,
    load_style_definitions,
    normalize_style_registry as normalize_style_registry,
    split_class_tokens,
    style_families,
)


DEFAULT_SOURCE_ROOTS = (Path("src"), Path("lagniappe/web/templates"))
DEFAULT_LONG_CLASS_LIMIT = 6
DEFAULT_REPEAT_LIMIT = 2
MARKDOWN_SECTION_LIMIT = 30
SCRIPT_EXTENSIONS = {".js", ".mjs"}
TEMPLATE_EXTENSIONS = {".html", ".jinja", ".j2"}
STYLE_REF_RE = re.compile(
    r"\b(?P<root>STYLES|styles)"
    r"(?P<tail>(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?:\[['\"][A-Za-z_][A-Za-z0-9_]*['\"]))+)"
)
TAIL_PART_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]")
CLASS_ATTR_RE = re.compile(
    r"(?<![A-Za-z0-9_-])class\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
JINJA_BLOCK_RE = re.compile(r"({{.*?}}|{%.*?%}|{#.*?#})", re.DOTALL)
JINJA_STRING_RE = re.compile(r"(?P<quote>[\"'])(?P<value>(?:\\.|(?!\1).)*?)(?P=quote)")
CLASS_NAME_ASSIGN_RE = re.compile(r"\bclassName\s*=")
CLASS_NAME_PROPERTY_RE = re.compile(r"\bclassName\s*:")
CLASS_PROPERTY_RE = re.compile(r"(?<![A-Za-z0-9_])class\s*:")
CLASS_LIST_RE = re.compile(r"\.classList\.(?P<method>add|remove|toggle)\s*\(")
STYLE_TEMPLATE_RE = re.compile(r"`(?:(?:\\.)|[^`])*?STYLES(?:(?:\\.)|[^`])*?`", re.DOTALL)


@dataclass(frozen=True)
class Location:
    path: str
    line: int
    surface: str
    context: str
    snippet: str = ""


@dataclass
class StyleReference:
    name: str
    path: str
    line: int
    surface: str
    context: str
    resolved: str


@dataclass
class ClassUse:
    path: str
    line: int
    surface: str
    context: str
    literal_tokens: list[str]
    style_refs: list[str] = field(default_factory=list)
    snippet: str = ""

    @property
    def location(self) -> Location:
        return Location(self.path, self.line, self.surface, self.context, self.snippet)


@dataclass
class StyleExtensionFinding:
    style: str
    extra_classes: list[str]
    count: int
    surfaces: list[str]
    locations: list[Location]
    suggested_classes: str


@dataclass
class ClassStringFinding:
    classes: list[str]
    count: int
    surfaces: list[str]
    locations: list[Location]
    matching_styles: list[str] = field(default_factory=list)


@dataclass
class DuplicateStyleFinding:
    classes: list[str]
    styles: list[str]


@dataclass
class Report:
    summary: dict[str, object]
    unused_style_definitions: list[str]
    unknown_style_references: list[StyleReference]
    cross_surface_style_extensions: list[StyleExtensionFinding]
    repeated_style_extensions: list[StyleExtensionFinding]
    long_class_strings: list[ClassStringFinding]
    repeated_class_strings: list[ClassStringFinding]
    raw_class_matches_yaml: list[ClassStringFinding]
    duplicate_style_definitions: list[DuplicateStyleFinding]


def repo_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def compact_snippet(value: str, *, limit: int = 160) -> str:
    snippet = " ".join(value.strip().split())
    return snippet if len(snippet) <= limit else snippet[: limit - 1].rstrip() + "..."


def normalize_style_tail(tail: str) -> str:
    parts = []
    for match in TAIL_PART_RE.finditer(tail):
        parts.append(match.group(1) or match.group(2))
    return ".".join(parts)


def find_style_names(value: str, *, roots: set[str] | None = None) -> list[str]:
    allowed_roots = roots or {"STYLES", "styles"}
    return [
        normalize_style_tail(match.group("tail"))
        for match in STYLE_REF_RE.finditer(value)
        if match.group("root") in allowed_roots
    ]


def resolve_style_reference(
    name: str,
    definitions: dict[str, StyleDefinition],
    families: dict[str, list[str]],
) -> str:
    if name in definitions:
        return "leaf"
    if name in families:
        return "family"
    return "unknown"


def iter_source_files(repo_root: Path, source_roots: Iterable[Path]) -> Iterable[tuple[Path, str]]:
    for root in source_roots:
        source_root = root if root.is_absolute() else repo_root / root
        if source_root.is_file():
            surface = source_surface(source_root)
            if surface:
                yield source_root, surface
            continue
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            surface = source_surface(path)
            if surface:
                yield path, surface


def source_surface(path: Path) -> str | None:
    if path.suffix in TEMPLATE_EXTENSIONS:
        return "template"
    if path.suffix in SCRIPT_EXTENSIONS:
        return "javascript"
    return None


def style_references_from_text(
    text: str,
    path: Path,
    repo_root: Path,
    surface: str,
    context: str,
    definitions: dict[str, StyleDefinition],
    families: dict[str, list[str]],
) -> list[StyleReference]:
    relative = relpath(path, repo_root)
    roots = {"styles"} if surface == "template" else {"STYLES"}
    references = []
    for match in STYLE_REF_RE.finditer(text):
        if match.group("root") not in roots:
            continue
        name = normalize_style_tail(match.group("tail"))
        references.append(
            StyleReference(
                name=name,
                path=relative,
                line=line_number(text, match.start()),
                surface=surface,
                context=context,
                resolved=resolve_style_reference(name, definitions, families),
            )
        )
    return references


def quoted_values_from_jinja(block: str) -> list[str]:
    values = []
    for match in JINJA_STRING_RE.finditer(block):
        values.append(match.group("value"))
    return values


def template_literal_tokens(value: str) -> list[str]:
    parts = []
    position = 0
    for match in JINJA_BLOCK_RE.finditer(value):
        parts.append(value[position : match.start()])
        parts.extend(quoted_values_from_jinja(match.group(0)))
        position = match.end()
    parts.append(value[position:])
    return split_class_tokens(" ".join(parts))


def scan_template_class_uses(
    text: str,
    path: Path,
    repo_root: Path,
) -> list[ClassUse]:
    relative = relpath(path, repo_root)
    uses = []
    for match in CLASS_ATTR_RE.finditer(text):
        value = match.group("value")
        tokens = template_literal_tokens(value)
        style_refs = find_style_names(value, roots={"styles"})
        if not tokens and not style_refs:
            continue
        uses.append(
            ClassUse(
                path=relative,
                line=line_number(text, match.start()),
                surface="template",
                context="class attribute",
                literal_tokens=tokens,
                style_refs=style_refs,
                snippet=compact_snippet(value),
            )
        )
    return uses


def read_js_quoted(text: str, start: int) -> tuple[str, int]:
    quote = text[start]
    index = start + 1
    content = []
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            content.append(text[index + 1])
            index += 2
            continue
        if char == quote:
            return "".join(content), index + 1
        content.append(char)
        index += 1
    return "".join(content), index


def remove_template_substitutions(value: str) -> str:
    parts = []
    index = 0
    while index < len(value):
        start = value.find("${", index)
        if start == -1:
            parts.append(value[index:])
            break
        parts.append(value[index:start])
        index = skip_balanced_js(value, start + 2, "{", "}")
    return " ".join(parts)


def skip_balanced_js(text: str, start: int, opener: str, closer: str) -> int:
    depth = 1
    index = start
    while index < len(text):
        char = text[index]
        if char in {"'", '"', "`"}:
            _, index = read_js_quoted(text, index)
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def extract_js_string_contents(expression: str) -> list[str]:
    values = []
    index = 0
    while index < len(expression):
        char = expression[index]
        if char in {"'", '"'}:
            value, index = read_js_quoted(expression, index)
            values.append(value)
            continue
        if char == "`":
            value, index = read_js_quoted(expression, index)
            values.append(remove_template_substitutions(value))
            continue
        index += 1
    return values


def js_literal_tokens(expression: str) -> list[str]:
    return split_class_tokens(" ".join(extract_js_string_contents(expression)))


def read_js_expression(text: str, start: int, terminators: set[str]) -> str:
    index = start
    depth = 0
    while index < len(text):
        char = text[index]
        if char in {"'", '"', "`"}:
            _, index = read_js_quoted(text, index)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth > 0:
                depth -= 1
        elif depth == 0 and char in terminators:
            return text[start:index]
        index += 1
    return text[start:]


def read_parenthesized_expression(text: str, open_paren: int) -> str:
    depth = 1
    index = open_paren + 1
    while index < len(text):
        char = text[index]
        if char in {"'", '"', "`"}:
            _, index = read_js_quoted(text, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : index]
        index += 1
    return text[open_paren + 1 :]


def js_class_use(
    text: str,
    path: Path,
    repo_root: Path,
    start: int,
    expression: str,
    context: str,
) -> ClassUse | None:
    tokens = js_literal_tokens(expression)
    style_refs = find_style_names(expression, roots={"STYLES"})
    if not tokens and not style_refs:
        return None
    return ClassUse(
        path=relpath(path, repo_root),
        line=line_number(text, start),
        surface="javascript",
        context=context,
        literal_tokens=tokens,
        style_refs=style_refs,
        snippet=compact_snippet(expression),
    )


def scan_js_class_uses(text: str, path: Path, repo_root: Path) -> list[ClassUse]:
    uses = []
    for pattern, terminators, context in (
        (CLASS_NAME_ASSIGN_RE, {";"}, "className assignment"),
        (CLASS_NAME_PROPERTY_RE, {",", "\n"}, "className property"),
        (CLASS_PROPERTY_RE, {",", "\n"}, "class property"),
    ):
        for match in pattern.finditer(text):
            expression = read_js_expression(text, match.end(), terminators)
            use = js_class_use(text, path, repo_root, match.start(), expression, context)
            if use:
                uses.append(use)

    for match in CLASS_LIST_RE.finditer(text):
        expression = read_parenthesized_expression(text, match.end() - 1)
        method = match.group("method")
        use = js_class_use(
            text,
            path,
            repo_root,
            match.start(),
            expression,
            f"classList.{method}",
        )
        if use:
            uses.append(use)

    for match in STYLE_TEMPLATE_RE.finditer(text):
        expression = match.group(0)
        use = js_class_use(
            text,
            path,
            repo_root,
            match.start(),
            expression,
            "STYLES template literal",
        )
        if use and use.literal_tokens:
            uses.append(use)

    return deduplicate_class_uses(uses)


def deduplicate_class_uses(uses: list[ClassUse]) -> list[ClassUse]:
    seen = set()
    unique = []
    for use in uses:
        key = (
            use.path,
            use.line,
            tuple(use.literal_tokens),
            tuple(use.style_refs),
            use.snippet,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(use)
    return unique


def collect_usage(
    repo_root: Path,
    source_roots: Iterable[Path],
    definitions: dict[str, StyleDefinition],
    families: dict[str, list[str]],
) -> tuple[list[StyleReference], list[ClassUse], dict[str, int]]:
    references: list[StyleReference] = []
    class_uses: list[ClassUse] = []
    files_by_surface: Counter[str] = Counter()
    for path, surface in iter_source_files(repo_root, source_roots):
        text = path.read_text(encoding="utf-8")
        files_by_surface[surface] += 1
        references.extend(
            style_references_from_text(
                text, path, repo_root, surface, "source", definitions, families
            )
        )
        if surface == "template":
            class_uses.extend(scan_template_class_uses(text, path, repo_root))
        elif surface == "javascript":
            class_uses.extend(scan_js_class_uses(text, path, repo_root))
    return references, class_uses, dict(files_by_surface)


def referenced_style_leaves(
    references: list[StyleReference],
    families: dict[str, list[str]],
) -> dict[str, set[str]]:
    usage: dict[str, set[str]] = defaultdict(set)
    for reference in references:
        if reference.resolved == "leaf":
            usage[reference.name].add(reference.surface)
        elif reference.resolved == "family":
            for child in families[reference.name]:
                usage[child].add(reference.surface)
    return usage


def locations_for_uses(uses: Iterable[ClassUse], limit: int = 5) -> list[Location]:
    return [use.location for use in list(uses)[:limit]]


def build_style_extension_findings(
    class_uses: list[ClassUse],
    definitions: dict[str, StyleDefinition],
    *,
    repeat_limit: int,
) -> tuple[list[StyleExtensionFinding], list[StyleExtensionFinding]]:
    grouped: dict[tuple[str, tuple[str, ...]], list[ClassUse]] = defaultdict(list)
    for use in class_uses:
        if not use.literal_tokens:
            continue
        for style_ref in use.style_refs:
            if style_ref in definitions:
                grouped[(style_ref, tuple(use.literal_tokens))].append(use)

    findings = []
    for (style_ref, extras), uses in grouped.items():
        surfaces = sorted({use.surface for use in uses})
        definition_tokens = definitions[style_ref].tokens
        findings.append(
            StyleExtensionFinding(
                style=style_ref,
                extra_classes=list(extras),
                count=len(uses),
                surfaces=surfaces,
                locations=locations_for_uses(uses),
                suggested_classes=" ".join(definition_tokens + list(extras)),
            )
        )

    findings.sort(
        key=lambda item: (
            -len(item.surfaces),
            -item.count,
            item.style,
            item.extra_classes,
        )
    )
    cross_surface = [item for item in findings if len(item.surfaces) > 1]
    repeated = [
        item
        for item in findings
        if item.count >= repeat_limit and len(item.surfaces) == 1
    ]
    return cross_surface, repeated


def class_string_groups(class_uses: list[ClassUse]) -> dict[tuple[str, ...], list[ClassUse]]:
    grouped: dict[tuple[str, ...], list[ClassUse]] = defaultdict(list)
    for use in class_uses:
        if use.style_refs or not use.literal_tokens:
            continue
        grouped[tuple(use.literal_tokens)].append(use)
    return grouped


def build_class_string_finding(
    tokens: tuple[str, ...],
    uses: list[ClassUse],
    *,
    matching_styles: list[str] | None = None,
) -> ClassStringFinding:
    return ClassStringFinding(
        classes=list(tokens),
        count=len(uses),
        surfaces=sorted({use.surface for use in uses}),
        locations=locations_for_uses(uses),
        matching_styles=matching_styles or [],
    )


def build_class_string_findings(
    class_uses: list[ClassUse],
    definitions: dict[str, StyleDefinition],
    *,
    long_class_limit: int,
    repeat_limit: int,
) -> tuple[list[ClassStringFinding], list[ClassStringFinding], list[ClassStringFinding]]:
    grouped = class_string_groups(class_uses)
    style_tokens: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name, definition in definitions.items():
        style_tokens[tuple(definition.tokens)].append(name)

    long_class_strings = []
    repeated_class_strings = []
    raw_class_matches_yaml = []
    for tokens, uses in grouped.items():
        matching_styles = sorted(style_tokens.get(tokens, []))
        if len(tokens) >= long_class_limit:
            long_class_strings.append(
                build_class_string_finding(tokens, uses, matching_styles=matching_styles)
            )
        if len(uses) >= repeat_limit and len(tokens) > 1:
            repeated_class_strings.append(
                build_class_string_finding(tokens, uses, matching_styles=matching_styles)
            )
        if matching_styles:
            raw_class_matches_yaml.append(
                build_class_string_finding(tokens, uses, matching_styles=matching_styles)
            )

    def sort_key(item):
        return (-item.count, -len(item.classes), item.classes)

    long_class_strings.sort(key=sort_key)
    repeated_class_strings.sort(key=sort_key)
    raw_class_matches_yaml.sort(key=sort_key)
    return long_class_strings, repeated_class_strings, raw_class_matches_yaml


def build_duplicate_style_findings(
    definitions: dict[str, StyleDefinition],
) -> list[DuplicateStyleFinding]:
    grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name, definition in definitions.items():
        grouped[tuple(definition.tokens)].append(name)
    findings = []
    for tokens, names in grouped.items():
        if len(names) <= 1 or len({definitions[name].canonical for name in names}) <= 1:
            continue
        name_set = set(names)
        edges: dict[str, set[str]] = defaultdict(set)
        for name in names:
            for exception in definitions[name].exceptions:
                if (
                    exception["diagnostic"] == "duplicate-style-value"
                    and exception["target"] in name_set
                ):
                    edges[name].add(exception["target"])
                    edges[exception["target"]].add(name)
        connected = {names[0]}
        pending = [names[0]]
        while pending:
            current = pending.pop()
            for target in edges[current] - connected:
                connected.add(target)
                pending.append(target)
        if connected != name_set:
            findings.append(
                DuplicateStyleFinding(classes=list(tokens), styles=sorted(names))
            )
    findings.sort(key=lambda item: (-len(item.styles), -len(item.classes), item.styles))
    return findings


def build_summary(
    *,
    definitions: dict[str, StyleDefinition],
    references: list[StyleReference],
    usage: dict[str, set[str]],
    files_by_surface: dict[str, int],
    unused: list[str],
    unknown: list[StyleReference],
    cross_surface_extensions: list[StyleExtensionFinding],
    repeated_extensions: list[StyleExtensionFinding],
    long_class_strings: list[ClassStringFinding],
    repeated_class_strings: list[ClassStringFinding],
    raw_matches: list[ClassStringFinding],
    duplicate_styles: list[DuplicateStyleFinding],
) -> dict[str, object]:
    used = {name for name, surfaces in usage.items() if surfaces}
    both = {name for name, surfaces in usage.items() if len(surfaces) > 1}
    template_only = {
        name for name, surfaces in usage.items() if surfaces == {"template"}
    }
    javascript_only = {
        name for name, surfaces in usage.items() if surfaces == {"javascript"}
    }
    return {
        "style_definitions": len(definitions),
        "source_files": sum(files_by_surface.values()),
        "source_files_by_surface": files_by_surface,
        "style_references": len(references),
        "style_references_by_surface": dict(Counter(ref.surface for ref in references)),
        "used_style_definitions": len(used),
        "style_definitions_used_both_surfaces": len(both),
        "style_definitions_template_only": len(template_only),
        "style_definitions_javascript_only": len(javascript_only),
        "unused_style_definitions": len(unused),
        "unknown_style_references": len(unknown),
        "cross_surface_style_extensions": len(cross_surface_extensions),
        "repeated_style_extensions": len(repeated_extensions),
        "long_class_strings": len(long_class_strings),
        "repeated_class_strings": len(repeated_class_strings),
        "raw_class_matches_yaml": len(raw_matches),
        "duplicate_style_definitions": len(duplicate_styles),
    }


def build_report(
    repo_root: Path,
    *,
    styles_path: Path = DEFAULT_STYLES_PATH,
    source_roots: Iterable[Path] = DEFAULT_SOURCE_ROOTS,
    long_class_limit: int = DEFAULT_LONG_CLASS_LIMIT,
    repeat_limit: int = DEFAULT_REPEAT_LIMIT,
) -> Report:
    definitions = load_style_definitions(repo_root, styles_path)
    families = style_families(definitions)
    references, class_uses, files_by_surface = collect_usage(
        repo_root, source_roots, definitions, families
    )
    usage = referenced_style_leaves(references, families)
    unused = sorted(set(definitions) - set(usage))
    unknown = [reference for reference in references if reference.resolved == "unknown"]
    cross_surface_extensions, repeated_extensions = build_style_extension_findings(
        class_uses, definitions, repeat_limit=repeat_limit
    )
    long_class_strings, repeated_class_strings, raw_matches = build_class_string_findings(
        class_uses,
        definitions,
        long_class_limit=long_class_limit,
        repeat_limit=repeat_limit,
    )
    duplicate_styles = build_duplicate_style_findings(definitions)
    summary = build_summary(
        definitions=definitions,
        references=references,
        usage=usage,
        files_by_surface=files_by_surface,
        unused=unused,
        unknown=unknown,
        cross_surface_extensions=cross_surface_extensions,
        repeated_extensions=repeated_extensions,
        long_class_strings=long_class_strings,
        repeated_class_strings=repeated_class_strings,
        raw_matches=raw_matches,
        duplicate_styles=duplicate_styles,
    )
    return Report(
        summary=summary,
        unused_style_definitions=unused,
        unknown_style_references=unknown,
        cross_surface_style_extensions=cross_surface_extensions,
        repeated_style_extensions=repeated_extensions,
        long_class_strings=long_class_strings,
        repeated_class_strings=repeated_class_strings,
        raw_class_matches_yaml=raw_matches,
        duplicate_style_definitions=duplicate_styles,
    )


def format_breakdown(values: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items()) or "none"


def format_location(location: Location) -> str:
    suffix = f": {location.snippet}" if location.snippet else ""
    return f"{location.path}:{location.line} [{location.surface}, {location.context}]{suffix}"


def limited(
    items: list[object], limit: int = MARKDOWN_SECTION_LIMIT
) -> tuple[list[object], int]:
    shown = items[:limit]
    return shown, max(0, len(items) - len(shown))


def markdown_locations(locations: list[Location]) -> str:
    if not locations:
        return "_none_"
    return "<br>".join(markdown_code(format_location(location)) for location in locations)


def markdown_style_extensions(title: str, items: list[StyleExtensionFinding]) -> list[str]:
    if not items:
        return []
    lines = [
        markdown_section_count(title, len(items)),
        "",
        "| Style | Extra classes | Uses | Surfaces | Example locations |",
        "| --- | --- | ---: | --- | --- |",
    ]
    shown, remaining = limited(items, MARKDOWN_SECTION_LIMIT)
    for item in shown:
        lines.append(
            f"| {markdown_code(item.style)} | "
            f"{markdown_code(' '.join(item.extra_classes))} | "
            f"{item.count} | "
            f"{markdown_escape(', '.join(item.surfaces))} | "
            f"{markdown_locations(item.locations[:3])} |"
        )
    if remaining:
        lines.append(f"| _{remaining} more_ |  |  |  |  |")
    lines.append("")
    return lines


def markdown_class_strings(title: str, items: list[ClassStringFinding]) -> list[str]:
    if not items:
        return []
    lines = [
        markdown_section_count(title, len(items)),
        "",
        "| Classes | Uses | Surfaces | Matching styles | Example locations |",
        "| --- | ---: | --- | --- | --- |",
    ]
    shown, remaining = limited(items, MARKDOWN_SECTION_LIMIT)
    for item in shown:
        lines.append(
            f"| {markdown_code(' '.join(item.classes))} | "
            f"{item.count} | "
            f"{markdown_escape(', '.join(item.surfaces))} | "
            f"{markdown_list(item.matching_styles)} | "
            f"{markdown_locations(item.locations[:3])} |"
        )
    if remaining:
        lines.append(f"| _{remaining} more_ |  |  |  |  |")
    lines.append("")
    return lines


def markdown_unknown_references(items: list[StyleReference]) -> list[str]:
    if not items:
        return []
    lines = [markdown_section_count("Unknown Style References", len(items)), ""]
    shown, remaining = limited(items, MARKDOWN_SECTION_LIMIT)
    for item in shown:
        lines.append(
            f"- {markdown_code(item.name)} at "
            f"{markdown_code(f'{item.path}:{item.line}')} "
            f"_{markdown_escape(item.surface)}_"
        )
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_unused_styles(items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [markdown_section_count("Unused Style Definitions", len(items)), ""]
    shown, remaining = limited(items, MARKDOWN_SECTION_LIMIT)
    lines.extend(f"- {markdown_code(item)}" for item in shown)
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_duplicate_styles(items: list[DuplicateStyleFinding]) -> list[str]:
    if not items:
        return []
    lines = [
        markdown_section_count("Duplicate Style Definitions", len(items)),
        "",
        "| Styles | Classes |",
        "| --- | --- |",
    ]
    shown, remaining = limited(items, MARKDOWN_SECTION_LIMIT)
    for item in shown:
        lines.append(
            f"| {markdown_list(item.styles)} | {markdown_code(' '.join(item.classes))} |"
        )
    if remaining:
        lines.append(f"| _{remaining} more_ |  |")
    lines.append("")
    return lines


def report_to_markdown(report: Report) -> str:
    summary = report.summary
    lines = [
        "# Style Candidate Inventory",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    rows = [
        ("Style definitions", summary["style_definitions"]),
        (
            "Source files scanned",
            f"{summary['source_files']} ({format_breakdown(summary['source_files_by_surface'])})",
        ),
        (
            "Style references",
            f"{summary['style_references']} "
            f"({format_breakdown(summary['style_references_by_surface'])})",
        ),
        (
            "Used style definitions",
            f"{summary['used_style_definitions']} "
            f"(both={summary['style_definitions_used_both_surfaces']}, "
            f"template-only={summary['style_definitions_template_only']}, "
            f"javascript-only={summary['style_definitions_javascript_only']})",
        ),
        ("Unused style definitions", summary["unused_style_definitions"]),
        ("Unknown style references", summary["unknown_style_references"]),
        ("Cross-surface style extensions", summary["cross_surface_style_extensions"]),
        ("Repeated style extensions", summary["repeated_style_extensions"]),
        ("Long raw class strings", summary["long_class_strings"]),
        ("Repeated raw class strings", summary["repeated_class_strings"]),
        ("Raw class strings matching styles.yaml", summary["raw_class_matches_yaml"]),
        ("Duplicate style definitions", summary["duplicate_style_definitions"]),
    ]
    for metric, value in rows:
        lines.append(f"| {markdown_escape(metric)} | {markdown_escape(value)} |")

    finding_lines: list[str] = []
    finding_lines.extend(markdown_unknown_references(report.unknown_style_references))
    finding_lines.extend(markdown_unused_styles(report.unused_style_definitions))
    finding_lines.extend(
        markdown_style_extensions(
            "Cross-Surface Style Extensions", report.cross_surface_style_extensions
        )
    )
    finding_lines.extend(
        markdown_style_extensions(
            "Repeated Single-Surface Style Extensions",
            report.repeated_style_extensions,
        )
    )
    finding_lines.extend(
        markdown_class_strings("Long Raw Class Strings", report.long_class_strings)
    )
    finding_lines.extend(
        markdown_class_strings("Repeated Raw Class Strings", report.repeated_class_strings)
    )
    finding_lines.extend(
        markdown_class_strings(
            "Raw Class Strings Matching Styles.yaml", report.raw_class_matches_yaml
        )
    )
    finding_lines.extend(markdown_duplicate_styles(report.duplicate_style_definitions))
    if finding_lines:
        lines.extend(["", "## Findings", ""])
        lines.extend(finding_lines)
    return "\n".join(lines).rstrip()
