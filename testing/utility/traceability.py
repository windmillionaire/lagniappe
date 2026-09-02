#!/usr/bin/env python3
"""Declared source/test traceability reporter.

This is intentionally not a runtime coverage tool. It inventories source
symbols, reads lightweight ``@testable`` metadata, compares referenced pytest
nodeids against pytest collection, and reports drift.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import asdict, dataclass, field
import difflib
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from testing.utility.artifacts import (
    limited as limited_items,
    markdown_code,
    markdown_escape,
    markdown_list,
    markdown_more_line,
    markdown_section_count,
    slugify,
    write_markdown_report,
)
from testing.utility.traceability_common import (
    LATEST_TEST_RUN,
    behavior_path_fingerprints,
    decode_test_run_snapshots,
    git_changed_line_ranges,
    git_changed_paths,
    load_json,
    provenance,
    stable_finding_id,
    structured_report_payload,
    write_json,
)


DEFAULT_CONFIG = Path("testing/utility/traceability.yaml")
PYTEST_CONFIG = Path("testing/pytest.ini")
DEFAULT_REPORT_DIR = Path("reports")
TEXT_SECTION_LIMIT = 10
BROAD_OWNER_TEST_LIMIT = 5
BROAD_OWNER_DIMENSION_LIMIT = 6
TAG_RE = re.compile(r"^\s*@(?P<tag>[\w-]+)(?:\s*[:=]\s*|\s+)?(?P<value>.*)$")
NODEID_LINE_RE = re.compile(r"^[^\s].+\.py::.+")
SOURCE_PATH_MENTION_RE = re.compile(
    r"\b(?:config|installer|lagniappe|runner|src)/"
    r"[A-Za-z0-9_./-]+\.(?:py|mjs)\b"
)
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
CONTEXT_TOKEN_STOPWORDS = {
    "and",
    "args",
    "async",
    "await",
    "bool",
    "class",
    "const",
    "def",
    "e2e",
    "else",
    "false",
    "for",
    "from",
    "get",
    "html",
    "if",
    "import",
    "in",
    "is",
    "lagniappe",
    "let",
    "main",
    "mjs",
    "none",
    "not",
    "or",
    "pass",
    "py",
    "return",
    "routes",
    "self",
    "script",
    "src",
    "template",
    "templates",
    "test",
    "tests",
    "testing",
    "unit",
    "utility",
    "web",
    "widgets",
}
TESTABLE_INFRASTRUCTURE = "infrastructure"
TESTABLE_ARCHITECTURE_ALIASES = {"architecture", "infra", "infrastructure"}
SUPPRESSIVE_TESTABLE_VALUES = {True, False, TESTABLE_INFRASTRUCTURE}
TEST_FUNCTION_SOURCE_CACHE: dict[str, str] = {}


@dataclass(frozen=True)
class MatrixClause:
    """One declared Cartesian feature/dimension rectangle."""

    features: tuple[str, ...]
    dimensions: tuple[str, ...]


@dataclass
class Metadata:
    testable: bool | str | None = None
    tests: list[str] = field(default_factory=list)
    test_scaffolds: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    matrices: list[MatrixClause] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    pairs: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    reason: str | None = None
    covered_by: list[str] = field(default_factory=list)
    manual: bool = False
    raw: str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def has_tags(self) -> bool:
        return bool(
            self.testable is not None
            or self.tests
            or self.test_scaffolds
            or self.templates
            or self.styles
            or self.matrices
            or self.features
            or self.dimensions
            or self.pairs
            or self.sources
            or self.todos
            or self.reason
            or self.covered_by
            or self.manual
        )


@dataclass
class SourceSymbol:
    path: str
    language: str
    kind: str
    qualname: str
    lineno: int
    end_lineno: int
    metadata: Metadata
    start_lineno: int = 0
    subkind: str | None = None
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    data_only: bool = False

    @property
    def source_id(self) -> str:
        return f"{self.path}::{self.qualname}"


@dataclass
class TestCase:
    nodeid: str
    runnable: bool
    unfinished: bool
    metadata: Metadata
    path: str = ""
    qualname: str = ""
    lineno: int = 0
    start_lineno: int = 0
    end_lineno: int = 0
    collection_verified: bool = False
    _collected_nodeids: list[str] = field(default_factory=list, repr=False)
    execution: str = "not_run"
    execution_current: bool = False
    _execution_snapshots: list[dict[str, str]] = field(
        default_factory=list, repr=False
    )

    @property
    def location(self) -> str:
        if self.path and self.qualname and self.lineno:
            return f"{self.path}::{self.qualname}:{self.lineno}"
        return self.nodeid


@dataclass
class TestSymbolInfo:
    metadata: Metadata
    lineno: int
    start_lineno: int = 0
    end_lineno: int = 0
    unfinished: bool = False


@dataclass
class Report:
    summary: dict[str, object]
    missing_testable: list[SourceSymbol]
    testable_without_tests: list[SourceSymbol]
    unfinished_coverage: list[SourceSymbol]
    stale_test_references: list[dict[str, object]]
    invalid_false: list[dict[str, object]]
    manual_validation: list[SourceSymbol]
    covered_by_missing: list[dict[str, object]]
    feature_dimension_gaps: list[dict[str, object]]
    broad_source_owners: list[dict[str, object]]
    test_todos: list[dict[str, object]]
    orphan_runnable_tests: list[str]
    source_test_suggestions: list[dict[str, object]] = field(default_factory=list)
    focused_tests: list[TestCase] = field(default_factory=list)
    focused_source_references: list[dict[str, object]] = field(default_factory=list)
    focused_test_mappings: list[dict[str, object]] = field(default_factory=list)
    focused_source_tag_gaps: list[dict[str, object]] = field(default_factory=list)
    focused_source_suggestions: list[dict[str, object]] = field(default_factory=list)
    feature_dimension_sources: list[SourceSymbol] = field(default_factory=list)
    feature_dimension_tests: list[TestCase] = field(default_factory=list)
    feature_dimension_templates: list[dict[str, object]] = field(default_factory=list)
    feature_dimension_links: list[dict[str, object]] = field(default_factory=list)
    provenance: dict[str, object] = field(default_factory=dict)
    annotation_scope_issues: list[dict[str, object]] = field(default_factory=list)
    source_link_issues: list[dict[str, object]] = field(default_factory=list)
    metadata_issues: list[dict[str, object]] = field(default_factory=list)
    taxonomy: dict[str, object] = field(default_factory=dict)
    source_explanations: list[dict[str, object]] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    changed_tests: list[TestCase] = field(default_factory=list)
    template_contract_summary: dict[str, object] = field(default_factory=dict)
    template_contract_findings: list[dict[str, str]] = field(default_factory=list)
    template_contract_tests: list[TestCase] = field(default_factory=list)
    style_traceability_summary: dict[str, object] = field(default_factory=dict)
    style_traceability_findings: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TestReferenceExpansion:
    links: list[tuple[str, str]]
    stale_by_source: dict[str, list[str]]
    candidates: list[dict[str, object]] = field(default_factory=list)
    realized_pairs: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    fallback_links: set[tuple[str, str]] = field(default_factory=set)
    issues: list[dict[str, object]] = field(default_factory=list)


def repo_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_config(config_path: Path, repo_root: Path) -> dict[str, object]:
    with (repo_root / config_path).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    config.setdefault("source_roots", [])
    config.setdefault("test_roots", [])
    config.setdefault("annotated_source_roots", [])
    config.setdefault("test_scaffold_roots", [])
    config.setdefault("exclude", [])
    config.setdefault("python_extensions", [".py"])
    config.setdefault("javascript_extensions", [".js", ".mjs"])
    config.setdefault("ignore_symbols", {})
    config.setdefault("suggestions", {})
    config["ignore_symbols"].setdefault("names", [])
    config["ignore_symbols"].setdefault("python_decorators", [])
    config["ignore_symbols"].setdefault("python_class_bases", [])
    config["ignore_symbols"].setdefault("python_data_classes", False)
    config["ignore_symbols"].setdefault("javascript_method_kinds", [])
    config["suggestions"].setdefault("javascript_generic_symbols", [])
    config["suggestions"].setdefault("javascript_generic_tokens", [])
    config["suggestions"].setdefault(
        "strong_match_kinds", ["pair", "feature", "dimension", "path", "template"]
    )
    return config


def resolve_source_path(path: Path, repo_root: Path) -> Path:
    source = path if path.is_absolute() else repo_root / path
    source = source.resolve()
    resolved_root = repo_root.resolve()

    if not source.exists():
        raise FileNotFoundError(f"--source not found: {path}")
    if not source.is_file() and not source.is_dir():
        raise ValueError(f"--source must be a file or directory: {path}")
    try:
        source.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"--source must be inside repo root: {source}") from exc

    return source


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        unique.append(path)
        seen.add(resolved)
    return unique


def resolve_source_paths(paths: Iterable[Path], repo_root: Path) -> list[Path]:
    return unique_paths(resolve_source_path(path, repo_root) for path in paths)


def supported_source_files_for_path(
    config: dict[str, object], repo_root: Path, source: Path
) -> tuple[list[Path], list[Path]]:
    if source.is_dir():
        return discover_files_in_roots([relpath(source, repo_root)], config, repo_root)

    py_exts = set(config["python_extensions"])
    js_exts = set(config["javascript_extensions"])
    if source.suffix in py_exts:
        return [source], []
    if source.suffix in js_exts:
        return [], [source]

    extensions = sorted(py_exts | js_exts)
    raise ValueError(
        f"--source must use a supported extension or directory: {', '.join(extensions)}"
    )


def is_excluded(path: Path, repo_root: Path, patterns: Iterable[str]) -> bool:
    relative = relpath(path, repo_root)
    for pattern in patterns:
        if fnmatch.fnmatch(relative, pattern):
            return True
        if pattern.endswith("/**") and relative.startswith(pattern[:-3]):
            return True
    return False


def discover_files_in_roots(
    root_names: Iterable[object],
    config: dict[str, object],
    repo_root: Path,
    *,
    respect_excludes: bool = True,
) -> tuple[list[Path], list[Path]]:
    excludes = list(config["exclude"])
    py_exts = set(config["python_extensions"])
    js_exts = set(config["javascript_extensions"])
    python_files: list[Path] = []
    javascript_files: list[Path] = []

    for root_name in root_names:
        root = repo_root / str(root_name)
        if not root.exists():
            continue
        paths = (
            [root]
            if root.is_file()
            else sorted(p for p in root.rglob("*") if p.is_file())
        )
        for path in paths:
            if respect_excludes and is_excluded(path, repo_root, excludes):
                continue
            if path.suffix in py_exts:
                python_files.append(path)
            elif path.suffix in js_exts:
                javascript_files.append(path)

    return python_files, javascript_files


def discover_source_files(
    config: dict[str, object], repo_root: Path
) -> tuple[list[Path], list[Path]]:
    return discover_files_in_roots(config["source_roots"], config, repo_root)


def discover_annotated_source_files(
    config: dict[str, object],
    repo_root: Path,
    symbols: Iterable[SourceSymbol],
) -> tuple[list[Path], list[Path]]:
    """Return optional source files where only tagged symbols should count."""
    python_files, javascript_files = discover_files_in_roots(
        config["annotated_source_roots"],
        config,
        repo_root,
        respect_excludes=False,
    )
    py_exts = set(config["python_extensions"])
    js_exts = set(config["javascript_extensions"])
    excludes = list(config["exclude"])
    seen = {path.resolve() for path in [*python_files, *javascript_files]}

    for symbol in symbols:
        for reference in symbol.metadata.covered_by:
            path_text = reference.split("::", 1)[0]
            if not path_text:
                continue
            path = repo_root / path_text
            if not path.exists() or not path.is_file():
                continue
            if path.suffix not in py_exts and path.suffix not in js_exts:
                continue
            if is_excluded(path, repo_root, excludes):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.suffix in py_exts:
                python_files.append(path)
            else:
                javascript_files.append(path)

    return sorted(python_files), sorted(javascript_files)


def discover_test_scaffold_files(
    config: dict[str, object], repo_root: Path
) -> tuple[list[Path], list[Path]]:
    return discover_files_in_roots(config["test_scaffold_roots"], config, repo_root)


def clean_metadata_line(line: str) -> str:
    line = line.strip()
    if line.startswith("#"):
        line = line[1:].strip()
    if line.startswith("*"):
        line = line[1:].strip()
    return line.rstrip()


def split_values(value: str, *, preserve_brackets: bool = False) -> list[str]:
    value = value.strip()
    if not preserve_brackets:
        value = value.strip("[]")
    if not value:
        return []
    return [part for part in re.split(r"[\s,]+", value) if part]


def add_unique(items: list[str], values: Iterable[str]) -> None:
    existing = set(items)
    for value in values:
        if value and value not in existing:
            items.append(value)
            existing.add(value)


def unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    add_unique(result, values)
    return result


def parse_matrix_clause(value: str) -> MatrixClause:
    if value.count(":") != 1:
        raise ValueError("@matrix must use FEATURES : DIMENSIONS")
    raw_features, raw_dimensions = value.split(":", 1)
    features = tuple(unique(split_values(raw_features)))
    dimensions = tuple(unique(split_values(raw_dimensions)))
    if not features or not dimensions:
        raise ValueError("@matrix must use FEATURES : DIMENSIONS")
    return MatrixClause(features=features, dimensions=dimensions)


def parse_metadata(text: str) -> Metadata:
    metadata = Metadata(raw=text.strip())
    recognized_tags = {
        "testable",
        "test",
        "tests",
        "scaffolding",
        "scaffoldings",
        "scaffold",
        "template",
        "templates",
        "template-partial",
        "template-partials",
        "style",
        "styles",
        "matrix",
        "feature",
        "features",
        "dimension",
        "dimensions",
        "pair",
        "pairs",
        "source",
        "sources",
        "todo",
        "todos",
        "reason",
        "covered-by",
        "coveredby",
        "manual",
        "manual-test",
        "manual-testing",
    }
    for raw_line in text.splitlines():
        line = clean_metadata_line(raw_line)
        match = TAG_RE.match(line)
        if not match:
            continue

        tag = match.group("tag").lower().replace("_", "-")
        value = match.group("value").strip()

        if tag not in recognized_tags:
            if tag == "suggestion":
                metadata.issues.append(
                    "@suggestion is not tracked; use @todo for a concrete coverage gap"
                )
                continue
            close = difflib.get_close_matches(tag, recognized_tags, n=1, cutoff=0.82)
            if close:
                metadata.issues.append(
                    f"unknown traceability tag @{tag}; did you mean @{close[0]}?"
                )
            continue

        if tag == "testable":
            normalized = value.lower()
            if normalized in {"true", "yes", "1"}:
                metadata.testable = True
            elif normalized in {"false", "no", "0"}:
                metadata.testable = False
            elif normalized in TESTABLE_ARCHITECTURE_ALIASES:
                metadata.testable = TESTABLE_INFRASTRUCTURE
            else:
                metadata.issues.append(
                    "@testable must be true, false, or infrastructure"
                )
        elif tag in {"test", "tests"}:
            add_unique(metadata.tests, split_values(value, preserve_brackets=True))
        elif tag in {"scaffolding", "scaffoldings", "scaffold"}:
            add_unique(
                metadata.test_scaffolds, split_values(value, preserve_brackets=True)
            )
        elif tag in {"template", "templates", "template-partial", "template-partials"}:
            add_unique(metadata.templates, split_values(value, preserve_brackets=True))
        elif tag in {"style", "styles"}:
            add_unique(metadata.styles, split_values(value, preserve_brackets=True))
        elif tag == "matrix":
            try:
                clause = parse_matrix_clause(value)
            except ValueError as exc:
                metadata.issues.append(str(exc))
            else:
                if clause in metadata.matrices:
                    metadata.issues.append(f"duplicate @matrix clause: {value}")
                else:
                    metadata.matrices.append(clause)
                    add_unique(metadata.features, clause.features)
                    add_unique(metadata.dimensions, clause.dimensions)
        elif tag in {"feature", "features"}:
            metadata.issues.append(
                f"@{tag} is no longer supported; use @matrix FEATURES : DIMENSIONS"
            )
        elif tag in {"dimension", "dimensions"}:
            metadata.issues.append(
                f"@{tag} is no longer supported; use @matrix FEATURES : DIMENSIONS"
            )
        elif tag in {"pair", "pairs"}:
            for pair in split_values(value):
                try:
                    feature, dimension = parse_feature_dimension_pair(
                        pair, option="@pair"
                    )
                except ValueError as exc:
                    metadata.issues.append(str(exc))
                    continue
                add_unique(metadata.pairs, [f"{feature}:{dimension}"])
                add_unique(metadata.features, [feature])
                add_unique(metadata.dimensions, [dimension])
        elif tag in {"source", "sources"}:
            add_unique(metadata.sources, split_values(value, preserve_brackets=True))
        elif tag in {"todo", "todos"}:
            if value:
                add_unique(metadata.todos, [value])
        elif tag == "reason":
            metadata.reason = value or metadata.reason
        elif tag in {"covered-by", "coveredby"}:
            add_unique(metadata.covered_by, split_values(value, preserve_brackets=True))
        elif tag in {"manual", "manual-test", "manual-testing"}:
            metadata.manual = value.lower() not in {"false", "no", "0"}

        if tag in {
            "test",
            "tests",
            "scaffolding",
            "scaffoldings",
            "scaffold",
            "covered-by",
            "coveredby",
            "feature",
            "features",
            "dimension",
            "dimensions",
            "matrix",
            "pair",
            "pairs",
            "source",
            "sources",
            "template",
            "templates",
            "style",
            "styles",
        } and not value:
            metadata.issues.append(f"@{tag} requires a value")

    return metadata


def decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Subscript):
        return decorator_name(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = decorator_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def base_names(node: ast.ClassDef) -> list[str]:
    return [name for base in node.bases if (name := decorator_name(base))]


def is_data_only_class(node: ast.ClassDef) -> bool:
    for stmt in node.body:
        if isinstance(stmt, ast.Expr) and isinstance(
            getattr(stmt, "value", None), ast.Constant
        ):
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Pass)):
            continue
        return False
    return True


def decorator_names(node: ast.AST) -> list[str]:
    return [
        name
        for decorator in getattr(node, "decorator_list", [])
        if (name := decorator_name(decorator))
    ]


def decorator_matches(name: str, patterns: Iterable[str]) -> bool:
    return any(
        name == pattern
        or name.split(".")[-1] == pattern
        or fnmatch.fnmatch(name, pattern)
        for pattern in patterns
    )


def is_python_property(
    decorators: list[str], ignored_decorators: Iterable[str]
) -> bool:
    return any(
        decorator.endswith(".setter")
        or decorator.endswith(".deleter")
        or decorator_matches(decorator, ignored_decorators)
        for decorator in decorators
    )


def leading_comment_block(lines: list[str], start_lineno: int) -> str:
    index = start_lineno - 2
    block: list[str] = []
    while index >= 0 and lines[index].lstrip().startswith("#"):
        block.append(clean_metadata_line(lines[index]))
        index -= 1
    return "\n".join(reversed(block))


def symbol_start_lineno(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        return min(decorator.lineno for decorator in decorators)
    return node.lineno


def metadata_text_for_python_node(node: ast.AST, lines: list[str]) -> str:
    parts = []
    comments = leading_comment_block(lines, symbol_start_lineno(node))
    if comments:
        parts.append(comments)
    docstring = ast.get_docstring(node)
    if docstring:
        parts.append(docstring)
    return "\n".join(parts)


def metadata_start_lineno_for_python_node(node: ast.AST, lines: list[str]) -> int:
    """Return the first decorator or immediately preceding metadata-comment line."""
    start = symbol_start_lineno(node)
    index = start - 2
    while index >= 0 and lines[index].lstrip().startswith("#"):
        index -= 1
    return index + 2 if index < start - 2 else start


def inventory_python_file(path: Path, repo_root: Path) -> list[SourceSymbol]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    symbols: list[SourceSymbol] = []

    def visit_body(body: list[ast.stmt], stack: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                qualname = ".".join([*stack, node.name])
                decorators = decorator_names(node)
                metadata = parse_metadata(metadata_text_for_python_node(node, lines))
                symbols.append(
                    SourceSymbol(
                        path=relpath(path, repo_root),
                        language="python",
                        kind="class",
                        subkind=None,
                        qualname=qualname,
                        lineno=node.lineno,
                        end_lineno=getattr(node, "end_lineno", node.lineno),
                        metadata=metadata,
                        start_lineno=metadata_start_lineno_for_python_node(node, lines),
                        decorators=decorators,
                        bases=base_names(node),
                        data_only=is_data_only_class(node),
                    )
                )
                visit_body(node.body, [*stack, node.name])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = ".".join([*stack, node.name])
                decorators = decorator_names(node)
                metadata = parse_metadata(metadata_text_for_python_node(node, lines))
                symbols.append(
                    SourceSymbol(
                        path=relpath(path, repo_root),
                        language="python",
                        kind="function" if not stack else "method",
                        subkind="property"
                        if is_python_property(
                            decorators, {"property", "cached_property"}
                        )
                        else None,
                        qualname=qualname,
                        lineno=node.lineno,
                        end_lineno=getattr(node, "end_lineno", node.lineno),
                        metadata=metadata,
                        start_lineno=metadata_start_lineno_for_python_node(node, lines),
                        decorators=decorators,
                    )
                )
                visit_body(node.body, [*stack, node.name])

    visit_body(tree.body, [])
    return symbols


def inventory_javascript_files(
    paths: list[Path], repo_root: Path
) -> list[SourceSymbol]:
    if not paths:
        return []

    helper = Path(__file__).with_name("traceability_js.mjs")
    command = ["node", str(helper), *[str(path) for path in paths]]
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "JavaScript inventory failed")

    symbols: list[SourceSymbol] = []
    for item in json.loads(result.stdout or "[]"):
        metadata = parse_metadata(item.get("metadata_text", ""))
        symbols.append(
            SourceSymbol(
                path=relpath(Path(item["path"]), repo_root),
                language=item["language"],
                kind=item["kind"],
                subkind=item.get("subkind"),
                qualname=item["qualname"],
                lineno=item["lineno"],
                end_lineno=item["end_lineno"],
                metadata=metadata,
            )
        )
    return symbols


def inventory_raw_sources(
    config: dict[str, object],
    repo_root: Path,
    *,
    include_untagged_annotated: bool = False,
) -> list[SourceSymbol]:
    python_files, javascript_files = discover_source_files(config, repo_root)
    symbols: list[SourceSymbol] = []
    for path in python_files:
        symbols.extend(inventory_python_file(path, repo_root))
    symbols.extend(inventory_javascript_files(javascript_files, repo_root))

    annotated_python_files, annotated_javascript_files = (
        discover_annotated_source_files(config, repo_root, symbols)
    )
    annotated_symbols: list[SourceSymbol] = []
    for path in annotated_python_files:
        annotated_symbols.extend(inventory_python_file(path, repo_root))
    annotated_symbols.extend(
        inventory_javascript_files(annotated_javascript_files, repo_root)
    )
    source_ids = {symbol.source_id for symbol in symbols}
    for symbol in annotated_symbols:
        if not include_untagged_annotated and not symbol.metadata.has_tags:
            continue
        if symbol.source_id not in source_ids:
            symbols.append(symbol)
            source_ids.add(symbol.source_id)

    return sorted(symbols, key=lambda s: (s.path, s.lineno, s.qualname))


def inventory_sources(config: dict[str, object], repo_root: Path) -> list[SourceSymbol]:
    return sorted(
        filter_symbols(inventory_raw_sources(config, repo_root), config),
        key=lambda s: (s.path, s.lineno, s.qualname),
    )


def inventory_referenceable_source_symbols(
    config: dict[str, object],
    repo_root: Path,
    extra_symbols: Iterable[SourceSymbol] = (),
) -> list[SourceSymbol]:
    symbols = inventory_raw_sources(config, repo_root, include_untagged_annotated=True)
    source_ids = {symbol.source_id for symbol in symbols}
    for symbol in extra_symbols:
        if symbol.source_id in source_ids:
            continue
        symbols.append(symbol)
        source_ids.add(symbol.source_id)

    return sorted(symbols, key=lambda s: (s.path, s.lineno, s.qualname))


def inventory_test_scaffolds(
    config: dict[str, object], repo_root: Path
) -> list[SourceSymbol]:
    python_files, javascript_files = discover_test_scaffold_files(config, repo_root)
    symbols: list[SourceSymbol] = []
    for path in python_files:
        symbols.extend(inventory_python_file(path, repo_root))
    symbols.extend(inventory_javascript_files(javascript_files, repo_root))
    return sorted(
        filter_symbols(symbols, config), key=lambda s: (s.path, s.lineno, s.qualname)
    )


def inventory_source_path(
    config: dict[str, object], repo_root: Path, source_path: Path
) -> tuple[list[SourceSymbol], list[SourceSymbol], str]:
    symbols, raw_symbols, source_scope, _ = inventory_source_paths(
        config, repo_root, [source_path]
    )
    return symbols, raw_symbols, source_scope


def inventory_source_paths(
    config: dict[str, object], repo_root: Path, source_paths: Iterable[Path]
) -> tuple[list[SourceSymbol], list[SourceSymbol], str, list[str]]:
    sources = resolve_source_paths(source_paths, repo_root)
    if not sources:
        raise ValueError("--source requires at least one path")

    python_files: list[Path] = []
    javascript_files: list[Path] = []
    for source in sources:
        source_python_files, source_javascript_files = supported_source_files_for_path(
            config, repo_root, source
        )
        python_files.extend(source_python_files)
        javascript_files.extend(source_javascript_files)

    python_files = unique_paths(python_files)
    javascript_files = unique_paths(javascript_files)
    raw_symbols: list[SourceSymbol] = []
    for path in python_files:
        raw_symbols.extend(inventory_python_file(path, repo_root))
    raw_symbols.extend(inventory_javascript_files(javascript_files, repo_root))

    source_scopes = [relpath(source, repo_root) for source in sources]
    source_scope = (
        source_scopes[0] if len(source_scopes) == 1 else ", ".join(source_scopes)
    )
    return (
        sorted(
            filter_symbols(raw_symbols, config),
            key=lambda s: (s.path, s.lineno, s.qualname),
        ),
        raw_symbols,
        source_scope,
        source_scopes,
    )


def inventory_source_file(
    config: dict[str, object], repo_root: Path, source_path: Path
) -> list[SourceSymbol]:
    symbols, _, _ = inventory_source_path(config, repo_root, source_path)
    return symbols


def filter_symbols(
    symbols: Iterable[SourceSymbol], config: dict[str, object]
) -> list[SourceSymbol]:
    filtered = []
    for symbol in symbols:
        ignored = should_ignore_symbol(symbol, config.get("ignore_symbols", {}))
        if ignored and not symbol.metadata.has_tags:
            continue
        filtered.append(symbol)
    return apply_inherited_testable_suppression(filtered)


def apply_inherited_testable_suppression(
    symbols: Iterable[SourceSymbol],
) -> list[SourceSymbol]:
    symbol_list = list(symbols)
    class_decisions = {
        (symbol.path, symbol.qualname): symbol.metadata.testable
        for symbol in symbol_list
        if symbol.kind == "class" and symbol.metadata.testable is not None
    }

    return [
        symbol
        for symbol in symbol_list
        if not should_suppress_from_parent(symbol, class_decisions)
    ]


def should_suppress_from_parent(
    symbol: SourceSymbol, class_decisions: dict[tuple[str, str], bool | str]
) -> bool:
    if symbol.metadata.testable is not None:
        return False

    inherited = nearest_class_testable_decision(symbol, class_decisions)
    return inherited in SUPPRESSIVE_TESTABLE_VALUES


def nearest_class_testable_decision(
    symbol: SourceSymbol, class_decisions: dict[tuple[str, str], bool | str]
) -> bool | str | None:
    inherited = None
    parts = symbol.qualname.split(".")
    for index in range(1, len(parts)):
        ancestor = ".".join(parts[:index])
        decision = class_decisions.get((symbol.path, ancestor))
        if decision is not None:
            inherited = decision
    return inherited


def should_ignore_symbol(
    symbol: SourceSymbol, ignore_config: dict[str, object]
) -> bool:
    ignored_names = set(ignore_config.get("names", []))
    ignored_js_kinds = set(ignore_config.get("javascript_method_kinds", []))
    ignored_python_decorators = set(ignore_config.get("python_decorators", []))
    ignored_python_class_bases = ignore_config.get("python_class_bases", [])
    ignore_python_data_classes = bool(ignore_config.get("python_data_classes", False))
    name = symbol.qualname.split(".")[-1]

    if name in ignored_names:
        return True

    if symbol.language == "javascript" and symbol.subkind in ignored_js_kinds:
        return True

    if symbol.language == "python" and symbol.kind == "class":
        if ignore_python_data_classes and symbol.data_only:
            return True
        if any(
            decorator_matches(base, ignored_python_class_bases) for base in symbol.bases
        ):
            return True

    if symbol.language == "python" and symbol.kind == "method":
        if is_python_property(symbol.decorators, ignored_python_decorators):
            return True

    return False


def normalized_test_root(root: object) -> str:
    text = str(root).strip().strip("/")
    if text.startswith("testing/"):
        return text.removeprefix("testing/")
    return text


def pytest_collect_root_args(roots: Iterable[object]) -> list[str]:
    normalized_roots = [
        root for root in (normalized_test_root(r) for r in roots) if root
    ]
    return [f"testing/{root}" for root in normalized_roots]


def collect_pytest_nodeids(
    repo_root: Path,
    *,
    include_all: bool = False,
    roots: Iterable[object] = (),
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(PYTEST_CONFIG),
        "--collect-only",
        "-qq",
    ]
    if include_all:
        command.extend(["-m", ""])
    command.extend(pytest_collect_root_args(roots))

    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        env=pytest_collect_env(repo_root),
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    return [
        line.strip()
        for line in result.stdout.splitlines()
        if NODEID_LINE_RE.match(line.strip())
    ]


def pytest_collect_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("FLASK_ENV", "testing")
    return env


def base_nodeid(nodeid: str) -> str:
    parts = nodeid.split("::")
    if parts:
        parts[-1] = re.sub(r"\[.*\]$", "", parts[-1])
    return "::".join(parts)


def test_path_from_nodeid(nodeid: str, repo_root: Path) -> Path:
    return repo_root / "testing" / nodeid.split("::", 1)[0]


def collect_python_test_symbol_info(path: Path) -> dict[str, TestSymbolInfo]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    info_by_qualname: dict[str, TestSymbolInfo] = {}

    def visit_body(body: list[ast.stmt], stack: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit_body(node.body, [*stack, node.name])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    qualname = "::".join([*stack, node.name])
                    info_by_qualname[qualname] = TestSymbolInfo(
                        metadata=parse_metadata(
                            metadata_text_for_python_node(node, lines)
                        ),
                        lineno=node.lineno,
                        start_lineno=metadata_start_lineno_for_python_node(node, lines),
                        end_lineno=getattr(node, "end_lineno", node.lineno),
                        unfinished=any(
                            decorator_name(decorator).split(".")[-1] == "unfinished"
                            for decorator in node.decorator_list
                        ),
                    )
                visit_body(node.body, [*stack, node.name])

    visit_body(tree.body, [])
    return info_by_qualname


def collect_python_test_symbol_metadata(path: Path) -> dict[str, Metadata]:
    return {
        qualname: info.metadata
        for qualname, info in collect_python_test_symbol_info(path).items()
    }


def collect_test_symbol_info(
    nodeids: Iterable[str], repo_root: Path
) -> dict[str, TestSymbolInfo]:
    by_path: dict[Path, dict[str, TestSymbolInfo]] = {}
    info_by_nodeid: dict[str, TestSymbolInfo] = {}

    for nodeid in nodeids:
        normalized = base_nodeid(nodeid)
        path_part, *qualname_parts = normalized.split("::")
        if not qualname_parts:
            info_by_nodeid[nodeid] = TestSymbolInfo(Metadata(), 0)
            continue

        path = repo_root / "testing" / path_part
        if path not in by_path:
            by_path[path] = collect_python_test_symbol_info(path)

        info_by_nodeid[nodeid] = by_path[path].get(
            "::".join(qualname_parts), TestSymbolInfo(Metadata(), 0)
        )

    return info_by_nodeid


def collect_test_metadata(
    nodeids: Iterable[str], repo_root: Path
) -> dict[str, Metadata]:
    return {
        nodeid: info.metadata
        for nodeid, info in collect_test_symbol_info(nodeids, repo_root).items()
    }


def test_files_in_roots(repo_root: Path, roots: Iterable[object]) -> list[Path]:
    files: set[Path] = set()
    testing_root = repo_root / "testing"
    for value in roots:
        relative = normalized_test_root(value)
        if not relative:
            continue
        root = testing_root / relative
        if root.is_file() and root.name.startswith("test_") and root.suffix == ".py":
            files.add(root)
        elif root.is_dir():
            files.update(root.rglob("test_*.py"))
    return sorted(files)


def discover_tests(repo_root: Path, roots: Iterable[object] = ()) -> dict[str, TestCase]:
    """Discover test functions statically without importing application modules."""
    tests: dict[str, TestCase] = {}
    testing_root = repo_root / "testing"
    for path in test_files_in_roots(repo_root, roots):
        test_path = relpath(path, testing_root)
        for qualname, info in collect_python_test_symbol_info(path).items():
            nodeid = f"{test_path}::{qualname}"
            tests[nodeid] = TestCase(
                nodeid=nodeid,
                runnable=not info.unfinished,
                unfinished=info.unfinished,
                metadata=info.metadata,
                path=test_path,
                qualname=qualname,
                lineno=info.lineno,
                start_lineno=info.start_lineno,
                end_lineno=info.end_lineno,
            )
    return tests


def changed_tests_for_paths(
    tests: dict[str, TestCase],
    changed_paths: Iterable[str],
    changed_line_ranges: dict[str, list[tuple[int, int]] | None] | None = None,
) -> list[TestCase]:
    """Select tests in changed files, narrowed to edited symbol ranges when known."""
    changed_test_paths = {
        path.removeprefix("testing/")
        for path in changed_paths
        if path.startswith("testing/")
    }
    candidates = [test for test in tests.values() if test.path in changed_test_paths]
    if changed_line_ranges is None:
        return sorted(candidates, key=lambda test: test.nodeid)

    focused = []
    for test in candidates:
        ranges = changed_line_ranges.get(f"testing/{test.path}")
        if ranges is None:
            focused.append(test)
            continue
        start = test.start_lineno or test.lineno
        end = test.end_lineno or test.lineno
        if any(
            range_end >= start and range_start <= end
            for range_start, range_end in ranges
        ):
            focused.append(test)
    return sorted(focused, key=lambda test: test.nodeid)


def changed_sources_for_paths(
    symbols: Iterable[SourceSymbol],
    changed_paths: Iterable[str],
    changed_line_ranges: dict[str, list[tuple[int, int]] | None] | None = None,
) -> list[SourceSymbol]:
    """Select source symbols in changed files, narrowed to edited ranges when known."""
    changed_set = set(changed_paths)
    candidates = [symbol for symbol in symbols if symbol.path in changed_set]
    if changed_line_ranges is None:
        return candidates

    focused = []
    for symbol in candidates:
        ranges = changed_line_ranges.get(symbol.path)
        if ranges is None:
            focused.append(symbol)
            continue
        start = symbol.start_lineno or symbol.lineno
        if any(
            range_end >= start and range_start <= symbol.end_lineno
            for range_start, range_end in ranges
        ):
            focused.append(symbol)
    return focused


def verify_test_collection(
    tests: dict[str, TestCase], repo_root: Path, roots: Iterable[object]
) -> dict[str, TestCase]:
    """Optionally enrich static discovery with real pytest collection results."""
    runnable = set(collect_pytest_nodeids(repo_root, include_all=False, roots=roots))
    all_collected = set(collect_pytest_nodeids(repo_root, include_all=True, roots=roots))
    runnable_bases = {base_nodeid(nodeid) for nodeid in runnable}
    collected_by_base: dict[str, list[str]] = {}
    for nodeid in all_collected:
        collected_by_base.setdefault(base_nodeid(nodeid), []).append(nodeid)
    for test in tests.values():
        test._collected_nodeids = sorted(collected_by_base.get(test.nodeid, []))
        test.collection_verified = bool(test._collected_nodeids)
        if test.collection_verified:
            test.runnable = test.nodeid in runnable_bases
            test.unfinished = not test.runnable
    return tests


def aggregate_test_outcomes(outcomes: list[str]) -> str:
    if not outcomes:
        return "not_run"
    if "failed" in outcomes:
        return "failed"
    if all(outcome == "passed" for outcome in outcomes):
        return "passed"
    if all(outcome == "skipped" for outcome in outcomes):
        return "skipped"
    if "passed" in outcomes:
        return "passed"
    return outcomes[0]


def attach_test_results(
    tests: dict[str, TestCase], repo_root: Path, results_path: Path | None = None
) -> dict[str, object]:
    path = results_path or (repo_root / LATEST_TEST_RUN)
    if not path.is_absolute():
        path = repo_root / path
    manifest = load_json(path)
    summary: dict[str, object] = {
        "path": display_path(path, repo_root),
        "available": manifest is not None,
        "current": False,
        "exit_status": None,
    }
    if not manifest:
        return summary

    manifest_provenance = manifest.get("provenance", {})
    snapshots = decode_test_run_snapshots(manifest)
    current_paths = behavior_path_fingerprints(repo_root)
    summary.update(
        {
            "exit_status": manifest.get("exit_status"),
            "provenance": manifest_provenance,
        }
    )
    raw_results = manifest.get("tests", {})
    if not isinstance(raw_results, dict):
        return summary

    by_base: dict[str, list[tuple[str, dict[str, object]]]] = {}
    for nodeid, row in raw_results.items():
        if not isinstance(row, dict):
            continue
        normalized_nodeid = str(nodeid)
        by_base.setdefault(base_nodeid(normalized_nodeid), []).append(
            (normalized_nodeid, row)
        )

    for test in tests.values():
        entries = by_base.get(test.nodeid, [])
        if test.collection_verified:
            collected_nodeids = set(test._collected_nodeids)
            entries = [
                entry for entry in entries if entry[0] in collected_nodeids
            ]
        rows = [row for _, row in entries]
        test.execution = aggregate_test_outcomes(
            [str(row.get("outcome", "not_run")) for row in rows]
        )
        test._execution_snapshots = []
        for row in rows:
            paths = snapshots.get(row.get("snapshot"))
            if isinstance(paths, dict):
                test._execution_snapshots.append(
                    {
                        str(key): str(value)
                        for key, value in paths.items()
                        if isinstance(key, str) and isinstance(value, str)
                    }
                )
        own_path = f"testing/{test.path}" if test.path else ""
        test.execution_current = bool(
            test.execution != "not_run"
            and test._execution_snapshots
            and own_path
            and all(
                snapshot.get(own_path) == current_paths.get(own_path)
                for snapshot in test._execution_snapshots
            )
        )
    summary["current"] = any(test.execution_current for test in tests.values())
    return summary


def apply_test_dependency_fingerprints(
    tests: dict[str, TestCase],
    dependencies: dict[str, set[str]],
    repo_root: Path,
) -> None:
    """Invalidate results whose declared source/template dependencies changed."""
    current_paths = behavior_path_fingerprints(repo_root)
    for nodeid, paths in dependencies.items():
        test = tests.get(nodeid)
        if not test or not test.execution_current:
            continue
        test.execution_current = all(
            snapshot.get(path) == current_paths.get(path)
            for snapshot in test._execution_snapshots
            for path in paths
        )


def source_test_dependency_paths(
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    scaffold_symbols: list[SourceSymbol] | None,
    repo_root: Path,
) -> dict[str, set[str]]:
    dependencies: dict[str, set[str]] = {}
    expansion = expand_test_references(symbols, tests, scaffold_symbols, repo_root)
    source_by_id = {symbol.source_id: symbol for symbol in symbols}
    for source_id, nodeid in expansion.links:
        source = source_by_id.get(source_id)
        if source and nodeid in tests:
            dependencies.setdefault(nodeid, set()).add(source.path)
    return dependencies


def collect_tests(
    repo_root: Path,
    roots: Iterable[object] = (),
    *,
    verify_collection: bool = False,
    results_path: Path | None = None,
) -> dict[str, TestCase]:
    normalized_roots = tuple(
        root for root in (normalized_test_root(r) for r in roots) if root
    )
    tests = discover_tests(repo_root, normalized_roots)
    if verify_collection:
        verify_test_collection(tests, repo_root, normalized_roots)
    attach_test_results(tests, repo_root, results_path)
    return tests


def test_execution_summary(tests: dict[str, TestCase]) -> dict[str, object]:
    counts = Counter(test.execution for test in tests.values())
    return {
        "tests_discovered": len(tests),
        "tests_runnable": sum(test.runnable for test in tests.values()),
        "tests_unfinished": sum(test.unfinished for test in tests.values()),
        "tests_collection_verified": sum(
            test.collection_verified for test in tests.values()
        ),
        "test_results_current": any(
            test.execution_current for test in tests.values()
        ),
        "tests_passed": counts.get("passed", 0),
        "tests_failed": counts.get("failed", 0),
        "tests_skipped": counts.get("skipped", 0),
        "tests_not_run": counts.get("not_run", 0),
    }


def test_in_roots(test: TestCase, roots: Iterable[object]) -> bool:
    normalized_roots = [
        root for root in (normalized_test_root(r) for r in roots) if root
    ]
    if not normalized_roots:
        return True
    return any(
        test.path == root or test.path.startswith(f"{root}/")
        for root in normalized_roots
    )


def filter_tests_by_roots(
    tests: dict[str, TestCase], roots: Iterable[object]
) -> dict[str, TestCase]:
    return {
        nodeid: test for nodeid, test in tests.items() if test_in_roots(test, roots)
    }


def is_test_pattern(reference: str) -> bool:
    return "*" in reference or "?" in reference


def test_function_source(test: TestCase, repo_root: Path, cache: dict[str, str]) -> str:
    if not test.path or not test.lineno:
        return ""

    path = repo_root / "testing" / test.path
    cache_key = f"{path}:{test.lineno}"
    if cache_key in cache:
        return cache[cache_key]

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        cache[cache_key] = ""
        return ""

    target_name = test.qualname.split("::")[-1]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == target_name and node.lineno == test.lineno:
            cache[cache_key] = ast.get_source_segment(source, node) or ""
            return cache[cache_key]

    cache[cache_key] = ""
    return ""


def test_uses_scaffold(test: TestCase, scaffold: SourceSymbol, repo_root: Path) -> bool:
    source = test_function_source(test, repo_root, TEST_FUNCTION_SOURCE_CACHE)
    if not source:
        return False

    name = scaffold.qualname.split(".")[-1]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == name:
            return True
        if isinstance(func, ast.Name) and func.id == name:
            return True
    return False


def scaffold_symbols_by_reference(
    scaffold_symbols: Iterable[SourceSymbol] | None,
) -> dict[str, list[SourceSymbol]]:
    by_reference: dict[str, list[SourceSymbol]] = {}
    for symbol in scaffold_symbols or []:
        by_reference.setdefault(symbol.source_id, []).append(symbol)
        by_reference.setdefault(symbol.path, []).append(symbol)
    return by_reference


def add_expanded_test_reference(
    expansion: TestReferenceExpansion,
    source_id: str,
    reference: str,
    all_test_ids: set[str],
    *,
    location: str,
) -> None:
    if is_test_pattern(reference):
        normalized_pattern = re.sub(r"\[[^]]*\]$", "", reference)
        matches = sorted(
            nodeid
            for nodeid in all_test_ids
            if fnmatch.fnmatch(nodeid, reference)
            or fnmatch.fnmatch(nodeid, normalized_pattern)
        )
        if not matches:
            expansion.stale_by_source.setdefault(source_id, []).append(reference)
            return
        for nodeid in matches:
            add_test_candidate(
                expansion,
                source_id,
                nodeid,
                origin="@tests",
                reference=reference,
                broad=True,
                location=location,
            )
    elif reference in all_test_ids or base_nodeid(reference) in all_test_ids:
        add_test_candidate(
            expansion,
            source_id,
            base_nodeid(reference),
            origin="@tests",
            reference=reference,
            broad=False,
            location=location,
        )
    else:
        expansion.stale_by_source.setdefault(source_id, []).append(reference)


def add_test_candidate(
    expansion: TestReferenceExpansion,
    source_id: str,
    nodeid: str,
    *,
    origin: str,
    reference: str,
    broad: bool,
    location: str,
) -> None:
    candidate = {
        "source_id": source_id,
        "nodeid": nodeid,
        "origin": origin,
        "reference": reference,
        "broad": broad,
        "location": location,
    }
    if candidate not in expansion.candidates:
        expansion.candidates.append(candidate)


def qualify_test_candidates(
    expansion: TestReferenceExpansion,
    symbols: Iterable[SourceSymbol],
    tests: dict[str, TestCase],
) -> None:
    source_by_id = {symbol.source_id: symbol for symbol in symbols}
    candidates_by_link: dict[tuple[str, str], list[dict[str, object]]] = {}
    broad_declarations: dict[tuple[str, str, str], dict[str, object]] = {}
    qualified_broad: set[tuple[str, str, str]] = set()
    for candidate in expansion.candidates:
        source_id = str(candidate["source_id"])
        nodeid = str(candidate["nodeid"])
        candidates_by_link.setdefault((source_id, nodeid), []).append(candidate)
        if candidate["broad"]:
            key = (
                source_id,
                str(candidate["origin"]),
                str(candidate["reference"]),
            )
            broad_declarations[key] = candidate

    for link, candidates in sorted(candidates_by_link.items()):
        source_id, nodeid = link
        source = source_by_id.get(source_id)
        test = tests.get(nodeid)
        if source is None or test is None:
            continue

        origins = {str(candidate["origin"]) for candidate in candidates}
        if "@tests" in origins and "@source" in origins:
            expansion.issues.append(
                {
                    "kind": "duplicate-direct-link",
                    "severity": "warning",
                    "location": test.location,
                    "message": f"{source_id} and {nodeid} declare the same edge twice",
                }
            )

        source_pairs = feature_dimension_pairs(source.metadata)
        test_pairs = feature_dimension_pairs(test.metadata)
        realized = source_pairs & test_pairs
        if realized:
            expansion.links.append(link)
            expansion.realized_pairs[link] = realized
            for candidate in candidates:
                if candidate["broad"]:
                    qualified_broad.add(
                        (
                            source_id,
                            str(candidate["origin"]),
                            str(candidate["reference"]),
                        )
                    )
            continue

        exact_candidates = [candidate for candidate in candidates if not candidate["broad"]]
        if not exact_candidates:
            continue

        expansion.links.append(link)
        expansion.fallback_links.add(link)
        missing = []
        if not source_pairs:
            missing.append("source")
        if not test_pairs:
            missing.append("test")
        if missing:
            message = (
                f"{source_id} and {nodeid} have no qualifying behavior claims "
                f"on: {', '.join(missing)}"
            )
            kind = "unqualified-direct-link"
        else:
            message = f"{source_id} and {nodeid} declare disjoint behavior cells"
            kind = "disjoint-direct-link"
        expansion.issues.append(
            {
                "kind": kind,
                "severity": "error",
                "location": str(exact_candidates[0]["location"]),
                "message": message,
            }
        )

    for key, candidate in sorted(broad_declarations.items()):
        if key in qualified_broad:
            continue
        expansion.issues.append(
            {
                "kind": "unqualified-test-pattern",
                "severity": "error",
                "location": str(candidate["location"]),
                "message": (
                    f"{candidate['origin']} {candidate['reference']} matched tests "
                    "but none shared a declared behavior cell"
                ),
            }
        )


def expand_test_references(
    symbols: Iterable[SourceSymbol],
    tests: dict[str, TestCase],
    scaffold_symbols: Iterable[SourceSymbol] | None = None,
    repo_root: Path | None = None,
    known_source_ids: set[str] | None = None,
) -> TestReferenceExpansion:
    symbol_list = list(symbols)
    source_by_id = {symbol.source_id: symbol for symbol in symbol_list}
    all_test_ids = set(tests)
    expansion = TestReferenceExpansion(
        links=[],
        stale_by_source={},
    )
    scaffolds_by_ref = scaffold_symbols_by_reference(scaffold_symbols)

    for symbol in symbol_list:
        if symbol.metadata.testable is not True:
            continue

        for reference in symbol.metadata.tests:
            add_expanded_test_reference(
                expansion,
                symbol.source_id,
                reference,
                all_test_ids,
                location=symbol_line(symbol),
            )

        for scaffold_ref in symbol.metadata.test_scaffolds:
            scaffolds = scaffolds_by_ref.get(scaffold_ref, [])
            if not scaffolds:
                expansion.stale_by_source.setdefault(symbol.source_id, []).append(
                    f"@scaffolding {scaffold_ref}"
                )
                continue

            if repo_root is None:
                continue

            for scaffold in scaffolds:
                for test in tests.values():
                    if test_uses_scaffold(test, scaffold, repo_root):
                        add_test_candidate(
                            expansion,
                            symbol.source_id,
                            test.nodeid,
                            origin="@scaffolding",
                            reference=scaffold_ref,
                            broad=True,
                            location=symbol_line(symbol),
                        )

    for test in tests.values():
        for source_id in test.metadata.sources:
            if "::" not in source_id:
                expansion.issues.append(
                    {
                        "kind": "invalid-source-reference",
                        "severity": "error",
                        "location": test.location,
                        "message": f"@source must use PATH::QUALNAME: {source_id}",
                    }
                )
                continue
            source = source_by_id.get(source_id)
            if source is None:
                if known_source_ids is not None and source_id not in known_source_ids:
                    expansion.issues.append(
                        {
                            "kind": "stale-source-reference",
                            "severity": "error",
                            "location": test.location,
                            "message": source_id,
                        }
                    )
                continue
            if source.metadata.testable is not True:
                expansion.issues.append(
                    {
                        "kind": "source-reference-not-testable",
                        "severity": "error",
                        "location": test.location,
                        "message": f"@source target is not @testable true: {source_id}",
                    }
                )
            add_test_candidate(
                expansion,
                source_id,
                test.nodeid,
                origin="@source",
                reference=source_id,
                broad=False,
                location=test.location,
            )

    qualify_test_candidates(expansion, symbol_list, tests)

    return expansion


def metadata_matrix_clauses(metadata: Metadata) -> list[MatrixClause]:
    """Return declared matrices, including programmatic legacy test fixtures."""
    if metadata.matrices:
        return list(metadata.matrices)
    if metadata.pairs or not metadata.features or not metadata.dimensions:
        return []
    return [
        MatrixClause(
            features=tuple(metadata.features),
            dimensions=tuple(metadata.dimensions),
        )
    ]


def matrix_clause_pairs(clause: MatrixClause) -> set[str]:
    return {
        f"{feature}:{dimension}"
        for feature in clause.features
        for dimension in clause.dimensions
    }


def feature_dimension_coverage_gaps(
    metadata: Metadata, known_refs: Iterable[str], tests: dict[str, TestCase]
) -> list[dict[str, str]]:
    refs = list(known_refs)
    gaps: list[dict[str, str]] = []

    claimed_by_tests = {
        test: feature_dimension_pairs(tests[test].metadata)
        for test in refs
        if test in tests
    }
    for pair in sorted(set(metadata.pairs)):
        feature, dimension = pair.split(":", 1)
        if not any(pair in claims for claims in claimed_by_tests.values()):
            gaps.append(
                {
                    "kind": "pair",
                    "feature": feature,
                    "dimension": dimension,
                    "name": pair,
                }
            )

    for clause in metadata_matrix_clauses(metadata):
        allowed = matrix_clause_pairs(clause)
        realized = set().union(
            *(allowed & claims for claims in claimed_by_tests.values())
        ) if claimed_by_tests else set()
        realized_features = {pair.split(":", 1)[0] for pair in realized}
        realized_dimensions = {pair.split(":", 1)[1] for pair in realized}
        for feature in clause.features:
            if feature not in realized_features:
                gaps.append({"kind": "feature", "name": feature})
        for dimension in clause.dimensions:
            if dimension not in realized_dimensions:
                gaps.append({"kind": "dimension", "name": dimension})
    return gaps


def traceability_metadata_issues(
    symbols: Iterable[SourceSymbol], tests: Iterable[TestCase]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for issue in symbol.metadata.issues:
            rows.append(
                {
                    "kind": "source-metadata",
                    "severity": "error",
                    "location": symbol_line(symbol),
                    "message": issue,
                }
            )
    for test in tests:
        for issue in test.metadata.issues:
            rows.append(
                {
                    "kind": "test-metadata",
                    "severity": "error",
                    "location": test.location,
                    "message": issue,
                }
            )
    return rows


def annotation_scope_issues(
    config: dict[str, object],
    repo_root: Path,
    included_symbols: Iterable[SourceSymbol],
) -> list[dict[str, object]]:
    """Find annotations that silently sit outside configured report scopes."""
    included_paths = {symbol.path for symbol in included_symbols}
    issues: list[dict[str, object]] = []
    scan_roots = config.get(
        "annotation_scan_roots",
        ["installer", "lagniappe", "runner", "src", "config"],
    )
    extensions = set(config["python_extensions"]) | set(
        config["javascript_extensions"]
    )
    for root_name in scan_roots:
        root = repo_root / str(root_name)
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix not in extensions:
                continue
            relative = relpath(path, repo_root)
            if relative in included_paths or relative.startswith("lagniappe/web/static/"):
                continue
            try:
                tagged = "@testable" in path.read_text(encoding="utf-8")
            except OSError:
                continue
            if tagged:
                issues.append(
                    {
                        "kind": "annotated-source-outside-scope",
                        "severity": "error",
                        "path": relative,
                        "message": "source contains @testable metadata but is not inventoried",
                    }
                )

    allowed_test_roots = list(config["test_roots"])
    configured_test_paths = {
        relpath(path, repo_root / "testing")
        for path in test_files_in_roots(repo_root, allowed_test_roots)
    }
    for path in sorted((repo_root / "testing").rglob("test_*.py")):
        test_path = relpath(path, repo_root / "testing")
        if test_path in configured_test_paths:
            continue
        for qualname, info in collect_python_test_symbol_info(path).items():
            if not info.metadata.has_tags:
                continue
            issues.append(
                {
                    "kind": "annotated-test-outside-scope",
                    "severity": "error",
                    "path": test_path,
                    "location": f"{test_path}::{qualname}:{info.lineno}",
                    "message": "test contains traceability metadata but is not inventoried",
                }
            )
    return issues


def source_link_issues(
    symbols: Iterable[SourceSymbol],
) -> list[dict[str, object]]:
    """Validate that @covered-by links form useful, acyclic ownership paths."""
    symbol_list = list(symbols)
    by_id: dict[str, list[SourceSymbol]] = {}
    by_path: dict[str, list[SourceSymbol]] = {}
    for symbol in symbol_list:
        by_id.setdefault(symbol.source_id, []).append(symbol)
        by_path.setdefault(symbol.path, []).append(symbol)

    def targets(reference: str) -> list[SourceSymbol]:
        if reference in by_id:
            # Python property getters and setters intentionally share a
            # qualname. Preserve every candidate so an unannotated setter
            # cannot hide the tested getter that owns the behavior.
            return by_id[reference]
        return by_path.get(reference, [])

    issues: list[dict[str, object]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def reaches_owner(source: SourceSymbol, path: list[str]) -> bool:
        if source.metadata.testable is True:
            return bool(source.metadata.tests or source.metadata.test_scaffolds)
        if source.metadata.testable == TESTABLE_INFRASTRUCTURE:
            return True
        if source.source_id in path:
            cycle = path[path.index(source.source_id) :] + [source.source_id]
            body = cycle[:-1]
            rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
            canonical = min(rotations) if rotations else (source.source_id,)
            if canonical not in seen_cycles:
                seen_cycles.add(canonical)
                issues.append(
                    {
                        "kind": "covered-by-cycle",
                        "severity": "error",
                        "source": source,
                        "targets": cycle,
                        "message": "@covered-by ownership cycle: " + " -> ".join(cycle),
                    }
                )
            return False

        next_path = [*path, source.source_id]
        linked = [
            target
            for ref in source.metadata.covered_by
            for target in targets(ref)
            if target.source_id != source.source_id
        ]
        outcomes = [reaches_owner(target, next_path) for target in linked]
        return any(outcomes)

    for symbol in symbol_list:
        for reference in symbol.metadata.covered_by:
            if not targets(reference):
                issues.append(
                    {
                        "kind": "covered-by-missing",
                        "severity": "error",
                        "source": symbol,
                        "targets": [reference],
                        "message": f"@covered-by target does not exist: {reference}",
                    }
                )
            if reference == symbol.source_id:
                issues.append(
                    {
                        "kind": "covered-by-self",
                        "severity": "error",
                        "source": symbol,
                        "targets": [reference],
                        "message": "@covered-by cannot reference the same source symbol",
                    }
                )
        if symbol.metadata.covered_by and not reaches_owner(symbol, []):
            issues.append(
                {
                    "kind": "covered-by-no-tested-owner",
                    "severity": "warning",
                    "source": symbol,
                    "targets": list(symbol.metadata.covered_by),
                    "message": "ownership chain does not reach a tested or infrastructure owner",
                }
            )

    unique_rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        source = issue.get("source")
        source_id = source.source_id if isinstance(source, SourceSymbol) else ""
        key = (str(issue["kind"]), source_id, str(issue["message"]))
        if key not in seen:
            unique_rows.append(issue)
            seen.add(key)
    return unique_rows


def normalized_taxonomy_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]", "", value.lower())
    if token.endswith("s") and len(token) > 3:
        token = token[:-1]
    return token


def taxonomy_summary(
    symbols: Iterable[SourceSymbol], tests: Iterable[TestCase]
) -> dict[str, object]:
    source_list = list(symbols)
    test_list = list(tests)

    def values(attribute: str) -> Counter:
        return Counter(
            value
            for item in [*source_list, *test_list]
            for value in getattr(item.metadata, attribute)
        )

    feature_counts = values("features")
    dimension_counts = values("dimensions")

    def collisions(counts: Counter) -> list[list[str]]:
        grouped: dict[str, set[str]] = {}
        for value in counts:
            grouped.setdefault(normalized_taxonomy_token(value), set()).add(value)
        return sorted(
            (sorted(group) for group in grouped.values() if len(group) > 1),
            key=lambda group: group[0],
        )

    large_cross_products = [
        {
            "source": symbol,
            "features": len(symbol.metadata.features),
            "dimensions": len(symbol.metadata.dimensions),
            "pairs": len(feature_dimension_pairs(symbol.metadata)),
        }
        for symbol in source_list
        if len(feature_dimension_pairs(symbol.metadata)) >= 12
        and len(symbol.metadata.features) > 1
        and not symbol.metadata.pairs
    ]
    return {
        "features": len(feature_counts),
        "dimensions": len(dimension_counts),
        "single_use_features": sum(count == 1 for count in feature_counts.values()),
        "single_use_dimensions": sum(
            count == 1 for count in dimension_counts.values()
        ),
        "feature_alias_candidates": collisions(feature_counts),
        "dimension_alias_candidates": collisions(dimension_counts),
        "large_cross_products": large_cross_products,
    }


def source_explanation_rows(
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    scaffold_symbols: list[SourceSymbol] | None,
    repo_root: Path,
) -> list[dict[str, object]]:
    expansion = expand_test_references(symbols, tests, scaffold_symbols, repo_root)
    by_source: dict[str, list[TestCase]] = {}
    realized_by_source: dict[str, set[str]] = {}
    for source_id, nodeid in expansion.links:
        if nodeid in tests:
            by_source.setdefault(source_id, []).append(tests[nodeid])
            realized_by_source.setdefault(source_id, set()).update(
                expansion.realized_pairs.get((source_id, nodeid), set())
            )

    def related_tests(source_id: str) -> list[dict[str, object]]:
        direct_ids = {test.nodeid for test in by_source.get(source_id, [])}
        realized = realized_by_source.get(source_id, set())
        rows = []
        for test in tests.values():
            if test.nodeid in direct_ids:
                continue
            shared = realized & feature_dimension_pairs(test.metadata)
            if shared:
                rows.append({"test": test, "pairs": sorted(shared)})
        return sorted(rows, key=lambda row: row["test"].nodeid)

    return [
        {
            "source": symbol,
            "decision": symbol.metadata.testable,
            "reason": symbol.metadata.reason,
            "covered_by": list(symbol.metadata.covered_by),
            "tests": sorted(
                unique_tests_by_nodeid(by_source.get(symbol.source_id, [])),
                key=lambda test: test.nodeid,
            ),
            "features": list(symbol.metadata.features),
            "dimensions": list(symbol.metadata.dimensions),
            "pairs": list(symbol.metadata.pairs),
            "matrices": list(symbol.metadata.matrices),
            "realized_pairs": sorted(realized_by_source.get(symbol.source_id, set())),
            "related_tests": related_tests(symbol.source_id),
            "templates": list(symbol.metadata.templates),
        }
        for symbol in symbols
    ]


def attach_source_explanations(
    report: Report,
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    scaffold_symbols: list[SourceSymbol] | None,
    repo_root: Path,
) -> None:
    report.source_explanations = source_explanation_rows(
        symbols, tests, scaffold_symbols, repo_root
    )
    required_tests = {
        test.nodeid
        for item in report.source_explanations
        for test in item["tests"]
    }
    related_tests = {
        item["test"].nodeid
        for source in report.source_explanations
        for item in source["related_tests"]
    }
    report.summary.update(
        {
            "source_required_tests": len(required_tests),
            "source_realized_pair_links": sum(
                len(item["realized_pairs"])
                for item in report.source_explanations
            ),
            "source_related_tests": len(related_tests),
            "source_related_test_links": sum(
                len(item["related_tests"])
                for item in report.source_explanations
            ),
            "source_related_pair_links": sum(
                len(related["pairs"])
                for item in report.source_explanations
                for related in item["related_tests"]
            ),
        }
    )


def normalize_test_target(target: str | None) -> str | None:
    if not target:
        return None
    normalized = base_nodeid(target).replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("testing/"):
        normalized = normalized[len("testing/") :]
    return normalized.rstrip("/")


def path_matches_test_target(test_path: str, target_path: str) -> bool:
    clean = target_path.strip("/")
    if not clean:
        return True
    path = Path(test_path)
    if clean.endswith(".py"):
        return (
            test_path == clean or path.name == clean or test_path.endswith(f"/{clean}")
        )
    return (
        test_path == clean
        or test_path.startswith(f"{clean}/")
        or clean in path.parts
        or path.name == clean
    )


def test_matches_target(test: TestCase, target: str | None) -> bool:
    if not target:
        return True

    if "::" in target:
        target_path, target_qualname = target.split("::", 1)
        if target_qualname and not (
            test.qualname == target_qualname
            or test.qualname.endswith(f"::{target_qualname}")
        ):
            return False
        if not target_path:
            return True
        return path_matches_test_target(test.path, target_path)

    if test.nodeid == target:
        return True
    return path_matches_test_target(test.path, target)


def matching_tests_for_target(
    tests: dict[str, TestCase], target: str
) -> list[TestCase]:
    normalized = normalize_test_target(target)
    return sorted(
        (test for test in tests.values() if test_matches_target(test, normalized)),
        key=lambda test: test.nodeid,
    )


def source_reference_matches_for_tests(
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    focused_tests: list[TestCase],
    scaffold_symbols: list[SourceSymbol] | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, object]]:
    focus_ids = {test.nodeid for test in focused_tests}
    source_by_id = {symbol.source_id: symbol for symbol in symbols}
    expansion = expand_test_references(symbols, tests, scaffold_symbols, repo_root)
    matches_by_source: dict[str, list[str]] = {}
    for source_id, nodeid in expansion.links:
        if nodeid in focus_ids and source_id in source_by_id:
            matches_by_source.setdefault(source_id, []).append(nodeid)

    return [
        {
            "source": source_by_id[source_id],
            "tests": unique(sorted(nodeids)),
        }
        for source_id, nodeids in sorted(matches_by_source.items())
    ]


def feature_dimension_pairs(metadata: Metadata) -> set[str]:
    declared = set(metadata.pairs)
    clauses = metadata_matrix_clauses(metadata)
    for clause in clauses:
        declared.update(matrix_clause_pairs(clause))
    if declared:
        return declared
    if not metadata.features or not metadata.dimensions:
        return set()
    return {
        f"{feature}:{dimension}"
        for feature in metadata.features
        for dimension in metadata.dimensions
    }


def parse_feature_dimension_pair(
    value: str, *, option: str = "--feature-dimension"
) -> tuple[str, str]:
    pair = value.strip()
    if pair.count(":") != 1:
        raise ValueError(f"{option} must use FEATURE:DIMENSION")

    feature, dimension = [part.strip() for part in pair.split(":", 1)]
    if not feature or not dimension:
        raise ValueError(f"{option} must use FEATURE:DIMENSION")
    if any(re.search(r"[\s,]", part) for part in (feature, dimension)):
        raise ValueError(
            f"{option} feature and dimension must be single tokens"
        )
    return feature, dimension


def metadata_has_feature_dimension_pair(
    metadata: Metadata, feature: str, dimension: str
) -> bool:
    return f"{feature}:{dimension}" in feature_dimension_pairs(metadata)


def unique_tag_matches(matches: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in matches:
        key = (match["kind"], match["name"])
        if key in seen:
            continue
        result.append(match)
        seen.add(key)
    return result


def metadata_tag_matches(
    source_metadata: Metadata, test_metadata: Metadata
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    source_pairs = feature_dimension_pairs(source_metadata)
    test_pairs = feature_dimension_pairs(test_metadata)

    for pair in sorted(source_pairs & test_pairs):
        matches.append({"kind": "pair", "name": pair})
    for feature in sorted(set(source_metadata.features) & set(test_metadata.features)):
        matches.append({"kind": "feature", "name": feature})
    for dimension in sorted(
        set(source_metadata.dimensions) & set(test_metadata.dimensions)
    ):
        matches.append({"kind": "dimension", "name": dimension})

    return matches


def shared_templates(source_metadata: Metadata, test_metadata: Metadata) -> list[str]:
    return sorted(set(source_metadata.templates) & set(test_metadata.templates))


def format_tag_matches(matches: list[dict[str, str]]) -> str:
    groups = [
        ("pair", "pairs"),
        ("feature", "features"),
        ("dimension", "dimensions"),
        ("path", "paths"),
        ("symbol", "symbols"),
        ("context", "context"),
    ]
    parts = []
    for kind, label in groups:
        values = [match["name"] for match in matches if match["kind"] == kind]
        if values:
            parts.append(f"{label}={', '.join(values)}")
    return "; ".join(parts) if parts else "none"


def source_owner_kind(symbol: SourceSymbol) -> str:
    return symbol.subkind or symbol.kind


def focused_sources_by_test(
    focused_tests: list[TestCase], references: list[dict[str, object]]
) -> dict[str, list[SourceSymbol]]:
    by_test = {test.nodeid: [] for test in focused_tests}
    seen: set[tuple[str, str]] = set()
    for item in references:
        source = item.get("source")
        if not isinstance(source, SourceSymbol):
            continue
        for nodeid in item.get("tests", []):
            key = (nodeid, source.source_id)
            if nodeid not in by_test or key in seen:
                continue
            by_test[nodeid].append(source)
            seen.add(key)

    for sources in by_test.values():
        sources.sort(key=lambda source: source.source_id)
    return by_test


def focused_test_feature_dimension_mappings(
    focused_tests: list[TestCase], references: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sources_by_test = focused_sources_by_test(focused_tests, references)
    mappings: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []

    for test in focused_tests:
        pair_rows = []
        missing_pairs = []
        sources = sources_by_test.get(test.nodeid, [])
        source_pairs = {
            source.source_id: feature_dimension_pairs(source.metadata)
            for source in sources
        }

        for pair in sorted(feature_dimension_pairs(test.metadata)):
            mapped_sources = [
                source for source in sources if pair in source_pairs[source.source_id]
            ]
            template_sources = [
                {
                    "source": source,
                    "templates": shared_templates(source.metadata, test.metadata),
                }
                for source in sources
                if source not in mapped_sources
                and shared_templates(source.metadata, test.metadata)
            ]
            pair_rows.append(
                {
                    "name": pair,
                    "sources": mapped_sources,
                    "template_sources": template_sources,
                }
            )
            if test.metadata.has_tags and not mapped_sources and not template_sources:
                missing_pairs.append(pair)

        mappings.append({"test": test, "pairs": pair_rows})
        if missing_pairs:
            gaps.append({"test": test, "missing": missing_pairs})

    return mappings, gaps


def broad_source_owner_rows(
    symbols: list[SourceSymbol], known_tests_by_source: dict[str, list[str]]
) -> list[dict[str, object]]:
    rows = []
    for symbol in symbols:
        if symbol.metadata.testable is not True:
            continue
        tests = unique(known_tests_by_source.get(symbol.source_id, []))
        dimensions = len(symbol.metadata.dimensions)
        if (
            len(tests) < BROAD_OWNER_TEST_LIMIT
            and dimensions < BROAD_OWNER_DIMENSION_LIMIT
        ):
            continue
        rows.append(
            {
                "source": symbol,
                "owner_kind": source_owner_kind(symbol),
                "tests": tests,
                "test_count": len(tests),
                "feature_count": len(symbol.metadata.features),
                "dimension_count": dimensions,
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            -item["dimension_count"],
            -item["test_count"],
            item["source"].source_id,
        ),
    )


def line_distance_to_references(
    symbol: SourceSymbol, references: list[dict[str, object]]
) -> int | None:
    distances = [
        abs(symbol.lineno - source.lineno)
        for item in references
        if isinstance((source := item.get("source")), SourceSymbol)
        and source.path == symbol.path
    ]
    return min(distances) if distances else None


def context_token_variants(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(value):
        token = raw.lower()
        if token in CONTEXT_TOKEN_STOPWORDS or token.isdigit():
            continue
        tokens.add(token)
        if token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens


def identifier_token_variants(value: str) -> set[str]:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return context_token_variants(value) | context_token_variants(camel_split)


def source_suggestion_config(config: dict[str, object]) -> dict[str, object]:
    return dict(config.get("suggestions", {}))


def configured_token_set(config: dict[str, object], key: str) -> set[str]:
    return {str(item).lower() for item in config.get(key, [])}


def generic_javascript_source_symbol(
    symbol: SourceSymbol, suggestion_config: dict[str, object]
) -> bool:
    if symbol.language != "javascript":
        return False

    leaf = symbol.qualname.split(".")[-1]
    leaf_name = leaf.lower()
    generic_names = configured_token_set(
        suggestion_config, "javascript_generic_symbols"
    )
    if leaf_name in generic_names:
        return True

    generic_tokens = configured_token_set(
        suggestion_config, "javascript_generic_tokens"
    )
    leaf_tokens = identifier_token_variants(leaf)
    return bool(leaf_tokens) and leaf_tokens <= generic_tokens


def generic_javascript_suggestion_without_strong_evidence(
    symbol: SourceSymbol,
    matches: list[dict[str, str]],
    suggestion_config: dict[str, object],
) -> bool:
    if not generic_javascript_source_symbol(symbol, suggestion_config):
        return False

    strong_kinds = configured_token_set(suggestion_config, "strong_match_kinds")
    match_kinds = {match["kind"] for match in matches}
    return not bool(match_kinds & strong_kinds)


def focused_test_context_paths(
    focused_tests: list[TestCase],
    symbols: list[SourceSymbol],
    repo_root: Path,
    existing_paths: set[str],
) -> set[str]:
    symbol_paths = {symbol.path for symbol in symbols}
    source_paths = set(existing_paths)
    context_tokens: set[str] = set()

    for test in focused_tests:
        context_tokens.update(context_token_variants(test.path))
        context_tokens.update(context_token_variants(test.qualname))
        for template in test.metadata.templates:
            template_path = template.split("::", 1)[0]
            context_tokens.update(context_token_variants(template_path))

        if not test.path:
            continue
        test_path = repo_root / "testing" / test.path
        if not test_path.exists():
            continue
        try:
            text = test_path.read_text(encoding="utf-8")
        except OSError:
            continue
        context_tokens.update(context_token_variants(text))
        for mention in SOURCE_PATH_MENTION_RE.findall(text):
            if mention in symbol_paths:
                source_paths.add(mention)

    if not context_tokens:
        return source_paths

    for path in symbol_paths:
        if context_token_variants(path) & context_tokens:
            source_paths.add(path)

    return source_paths


def source_suggestions_for_tests(
    symbols: list[SourceSymbol],
    focused_tests: list[TestCase],
    references: list[dict[str, object]],
    source_tag_gaps: list[dict[str, object]],
    repo_root: Path,
) -> list[dict[str, object]]:
    referenced_sources = [
        item["source"]
        for item in references
        if isinstance(item.get("source"), SourceSymbol)
    ]
    referenced_source_ids = {source.source_id for source in referenced_sources}
    context_paths = focused_test_context_paths(
        focused_tests,
        symbols,
        repo_root,
        {source.path for source in referenced_sources},
    )
    if not context_paths:
        return []

    missing_pairs_by_test = {
        item["test"].nodeid: set(item["missing"])
        for item in source_tag_gaps
        if isinstance(item.get("test"), TestCase)
    }
    suggestions: list[dict[str, object]] = []
    for symbol in symbols:
        if symbol.path not in context_paths:
            continue
        if symbol.metadata.testable is not True:
            continue

        matches: list[dict[str, str]] = []
        matched_tests: list[str] = []
        missing_pairs: list[str] = []
        for test in focused_tests:
            test_matches = metadata_tag_matches(symbol.metadata, test.metadata)
            pair_matches = [
                match["name"] for match in test_matches if match["kind"] == "pair"
            ]
            if not pair_matches:
                continue
            matches.extend(test_matches)
            matched_tests.append(test.nodeid)
            add_unique(
                missing_pairs,
                [
                    pair
                    for pair in pair_matches
                    if pair in missing_pairs_by_test.get(test.nodeid, set())
                ],
            )

        if matches and (missing_pairs or symbol.source_id not in referenced_source_ids):
            suggestions.append(
                {
                    "source": symbol,
                    "category": "likely_missing" if missing_pairs else "additional",
                    "missing_pairs": missing_pairs,
                    "matches": unique_tag_matches(matches),
                    "tests": unique(matched_tests),
                    "line_distance": line_distance_to_references(symbol, references),
                }
            )

    return sorted(
        suggestions,
        key=lambda item: (
            item["category"] != "likely_missing",
            -len(item["missing_pairs"]),
            -sum(1 for match in item["matches"] if match["kind"] == "pair"),
            -len(item["matches"]),
            item["line_distance"] if item["line_distance"] is not None else 10**9,
            item["source"].source_id,
        ),
    )


def source_code_segment(symbol: SourceSymbol, repo_root: Path) -> str:
    path = repo_root / symbol.path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    start = max(symbol.lineno - 1, 0)
    end = max(symbol.end_lineno, symbol.lineno)
    return "\n".join(lines[start:end])


def source_context_tokens(symbol: SourceSymbol, repo_root: Path) -> set[str]:
    parts = [
        symbol.path,
        symbol.qualname,
        symbol.metadata.raw,
        " ".join(symbol.metadata.features),
        " ".join(symbol.metadata.dimensions),
        source_code_segment(symbol, repo_root),
    ]
    return set().union(*(context_token_variants(part) for part in parts if part))


def test_context_tokens(test: TestCase, repo_root: Path) -> set[str]:
    parts = [
        test.path,
        test.qualname,
        test.metadata.raw,
        " ".join(test.metadata.features),
        " ".join(test.metadata.dimensions),
        " ".join(test.metadata.todos),
        " ".join(test.metadata.templates),
        test_function_source(test, repo_root, TEST_FUNCTION_SOURCE_CACHE),
    ]
    return set().union(*(context_token_variants(part) for part in parts if part))


def source_symbol_needs_test_suggestion(symbol: SourceSymbol) -> bool:
    metadata = symbol.metadata
    if metadata.testable is None:
        return True
    return (
        metadata.testable is True and not metadata.tests and not metadata.test_scaffolds
    )


def test_mentions_source_path(
    test: TestCase, symbol: SourceSymbol, repo_root: Path
) -> bool:
    if not test.path:
        return False

    path = repo_root / "testing" / test.path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return symbol.path in text


def source_test_candidate_matches(
    symbol: SourceSymbol,
    test: TestCase,
    repo_root: Path,
) -> list[dict[str, str]]:
    matches = metadata_tag_matches(symbol.metadata, test.metadata)
    test_source = test_function_source(
        test, repo_root, TEST_FUNCTION_SOURCE_CACHE
    ).lower()
    source_tokens = source_context_tokens(symbol, repo_root)
    test_tokens = test_context_tokens(test, repo_root)

    if test_mentions_source_path(test, symbol, repo_root):
        matches.append({"kind": "path", "name": symbol.path})

    template_matches = sorted(
        set(symbol.metadata.templates) & set(test.metadata.templates)
    )
    if template_matches:
        matches.append({"kind": "template", "name": ", ".join(template_matches[:5])})

    name_tokens = identifier_token_variants(symbol.qualname.split(".")[-1])
    name_matches = sorted(name_tokens & test_tokens)
    if name_matches and (
        len(name_matches) > 1 or any(len(t) > 4 for t in name_matches)
    ):
        matches.append({"kind": "symbol", "name": ", ".join(name_matches[:5])})

    if symbol.qualname.lower() in test_source:
        matches.append({"kind": "symbol", "name": symbol.qualname})

    context_matches = sorted(source_tokens & test_tokens)
    if context_matches:
        matches.append({"kind": "context", "name": ", ".join(context_matches[:8])})

    return unique_tag_matches(matches)


def source_test_suggestions_for_sources(
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    repo_root: Path,
    suggestion_config: dict[str, object],
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    for symbol in symbols:
        if not source_symbol_needs_test_suggestion(symbol):
            continue

        candidates: list[dict[str, object]] = []
        for test in tests.values():
            matches = source_test_candidate_matches(symbol, test, repo_root)
            if not matches:
                continue
            if generic_javascript_suggestion_without_strong_evidence(
                symbol, matches, suggestion_config
            ):
                continue

            kinds = {match["kind"] for match in matches}
            context_match = next(
                (match for match in matches if match["kind"] == "context"), None
            )
            context_count = (
                len(context_match["name"].split(", ")) if context_match else 0
            )
            strong = bool(
                kinds & {"pair", "path", "template", "feature", "dimension"}
            ) or ("symbol" in kinds and context_count >= 1)
            if not strong and context_count < 3:
                continue

            score = (
                10 * sum(1 for match in matches if match["kind"] == "pair")
                + 8 * sum(1 for match in matches if match["kind"] == "path")
                + 8 * sum(1 for match in matches if match["kind"] == "template")
                + 5 * sum(1 for match in matches if match["kind"] == "symbol")
                + 2 * sum(1 for match in matches if match["kind"] == "feature")
                + 2 * sum(1 for match in matches if match["kind"] == "dimension")
                + context_count
            )
            candidates.append(
                {
                    "test": test,
                    "matches": matches,
                    "score": score,
                    "category": "likely_existing" if strong else "contextual",
                }
            )

        if not candidates:
            continue

        candidates = sorted(
            candidates,
            key=lambda item: (
                item["category"] != "likely_existing",
                -int(item["score"]),
                item["test"].nodeid,
            ),
        )
        suggestions.append(
            {
                "source": symbol,
                "category": candidates[0]["category"],
                "matches": unique_tag_matches(
                    match
                    for candidate in candidates[:3]
                    for match in candidate["matches"]
                ),
                "tests": [candidate["test"] for candidate in candidates[:3]],
                "score": candidates[0]["score"],
            }
        )

    return sorted(
        suggestions,
        key=lambda item: (
            item["category"] != "likely_existing",
            -int(item["score"]),
            item["source"].path,
            item["source"].lineno,
            item["source"].qualname,
        ),
    )


def feature_dimension_template_rows(
    sources: list[SourceSymbol], tests: list[TestCase]
) -> list[dict[str, object]]:
    templates: dict[str, dict[str, object]] = {}
    for source in sources:
        for template in source.metadata.templates:
            row = templates.setdefault(
                template, {"template": template, "sources": [], "tests": []}
            )
            row["sources"].append(source)
    for test in tests:
        for template in test.metadata.templates:
            row = templates.setdefault(
                template, {"template": template, "sources": [], "tests": []}
            )
            row["tests"].append(test)

    rows = list(templates.values())
    for row in rows:
        row["sources"].sort(key=lambda source: source.source_id)
        row["tests"].sort(key=lambda test: test.nodeid)
    return sorted(rows, key=lambda row: str(row["template"]))


def unique_tests_by_nodeid(tests: Iterable[TestCase]) -> list[TestCase]:
    result: list[TestCase] = []
    seen: set[str] = set()
    for test in tests:
        if test.nodeid in seen:
            continue
        result.append(test)
        seen.add(test.nodeid)
    return result


def feature_dimension_link_rows(
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    sources: list[SourceSymbol],
    focused_tests: list[TestCase],
    scaffold_symbols: list[SourceSymbol] | None,
    repo_root: Path | None,
) -> list[dict[str, object]]:
    source_by_id = {source.source_id: source for source in sources}
    focused_test_ids = {test.nodeid for test in focused_tests}
    expansion = expand_test_references(symbols, tests, scaffold_symbols, repo_root)
    tests_by_source: dict[str, list[TestCase]] = {}
    for source_id, nodeid in expansion.links:
        if source_id not in source_by_id or nodeid not in focused_test_ids:
            continue
        tests_by_source.setdefault(source_id, []).append(tests[nodeid])

    return [
        {
            "source": source_by_id[source_id],
            "tests": sorted(unique_tests, key=lambda test: test.nodeid),
        }
        for source_id, unique_tests in sorted(
            (
                (source_id, unique_tests_by_nodeid(tests_for_source))
                for source_id, tests_for_source in tests_by_source.items()
            ),
            key=lambda item: item[0],
        )
    ]


def suppress_global_findings(report: Report) -> None:
    report.missing_testable = []
    report.testable_without_tests = []
    report.unfinished_coverage = []
    report.stale_test_references = []
    report.invalid_false = []
    report.manual_validation = []
    report.covered_by_missing = []
    report.feature_dimension_gaps = []
    report.broad_source_owners = []
    report.test_todos = []
    report.orphan_runnable_tests = []
    report.summary["global_findings_suppressed"] = True


def attach_feature_dimension_focus(
    report: Report,
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    target: str,
    repo_root: Path,
    *,
    scaffold_symbols: list[SourceSymbol] | None = None,
) -> None:
    feature, dimension = parse_feature_dimension_pair(target)
    matching_sources = sorted(
        (
            symbol
            for symbol in symbols
            if metadata_has_feature_dimension_pair(
                symbol.metadata, feature, dimension
            )
        ),
        key=lambda source: (source.path, source.lineno, source.qualname),
    )
    matching_tests = sorted(
        (
            test
            for test in tests.values()
            if metadata_has_feature_dimension_pair(test.metadata, feature, dimension)
        ),
        key=lambda test: test.nodeid,
    )
    template_rows = feature_dimension_template_rows(matching_sources, matching_tests)
    link_rows = feature_dimension_link_rows(
        symbols,
        tests,
        matching_sources,
        matching_tests,
        scaffold_symbols,
        repo_root,
    )

    suppress_global_findings(report)
    report.feature_dimension_sources = matching_sources
    report.feature_dimension_tests = matching_tests
    report.feature_dimension_templates = template_rows
    report.feature_dimension_links = link_rows
    report.summary.update(
        {
            "feature_dimension_scope": f"{feature}:{dimension}",
            "feature_dimension_feature": feature,
            "feature_dimension_dimension": dimension,
            "feature_dimension_sources": len(matching_sources),
            "feature_dimension_tests": len(matching_tests),
            "feature_dimension_tests_runnable": sum(
                test.runnable for test in matching_tests
            ),
            "feature_dimension_tests_unfinished": sum(
                test.unfinished for test in matching_tests
            ),
            "feature_dimension_templates": len(template_rows),
            "feature_dimension_source_test_links": sum(
                len(item["tests"]) for item in link_rows
            ),
        }
    )


def attach_test_focus(
    report: Report,
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    focused_tests: list[TestCase],
    target: str,
    repo_root: Path,
    *,
    suggest_sources: bool = False,
    scaffold_symbols: list[SourceSymbol] | None = None,
) -> None:
    references = source_reference_matches_for_tests(
        symbols, tests, focused_tests, scaffold_symbols, repo_root
    )
    mappings, source_tag_gaps = focused_test_feature_dimension_mappings(
        focused_tests, references
    )
    focused_source_ids = {
        item["source"].source_id
        for item in references
        if isinstance(item.get("source"), SourceSymbol)
    }
    report.focused_tests = focused_tests
    report.focused_source_references = references
    report.focused_test_mappings = mappings
    report.focused_source_tag_gaps = source_tag_gaps
    report.focused_source_suggestions = (
        source_suggestions_for_tests(
            symbols, focused_tests, references, source_tag_gaps, repo_root
        )
        if suggest_sources
        else []
    )
    report.broad_source_owners = [
        item
        for item in report.broad_source_owners
        if item["source"].source_id in focused_source_ids
    ]
    broad_owner_kinds = Counter(
        item["owner_kind"] for item in report.broad_source_owners
    )
    likely_suggestions = [
        item
        for item in report.focused_source_suggestions
        if item["category"] == "likely_missing"
    ]
    additional_suggestions = [
        item
        for item in report.focused_source_suggestions
        if item["category"] == "additional"
    ]
    report.missing_testable = []
    report.testable_without_tests = []
    report.unfinished_coverage = []
    report.stale_test_references = []
    report.invalid_false = []
    report.manual_validation = []
    report.covered_by_missing = []
    report.feature_dimension_gaps = []
    report.test_todos = []
    report.orphan_runnable_tests = []
    annotated_tests = [test for test in focused_tests if test.metadata.has_tags]
    report.summary.update(
        {
            "test_scope": target,
            "global_findings_suppressed": True,
            "focused_tests": len(focused_tests),
            "focused_tests_runnable": sum(test.runnable for test in focused_tests),
            "focused_tests_unfinished": sum(test.unfinished for test in focused_tests),
            "focused_tests_annotated": len(annotated_tests),
            "focused_source_references": len(references),
            "focused_source_tag_gap_tests": len(source_tag_gaps),
            "focused_source_tag_gaps": sum(
                len(item["missing"]) for item in source_tag_gaps
            ),
            "focused_broad_source_owners": len(report.broad_source_owners),
            "focused_broad_source_owner_kinds": dict(sorted(broad_owner_kinds.items())),
            "focused_source_suggestions": len(report.focused_source_suggestions),
            "focused_source_suggestions_likely_missing": len(likely_suggestions),
            "focused_source_suggestions_additional": len(additional_suggestions),
            "focused_source_suggestions_enabled": suggest_sources,
        }
    )


def classify(
    symbols: list[SourceSymbol],
    tests: dict[str, TestCase],
    *,
    scaffold_symbols: list[SourceSymbol] | None = None,
    repo_root: Path | None = None,
    suppress_orphan_tests: bool = False,
    known_source_ids: set[str] | None = None,
    known_source_paths: set[str] | None = None,
) -> Report:
    all_test_ids = set(tests)
    runnable_test_ids = {nodeid for nodeid, test in tests.items() if test.runnable}
    source_ids = {symbol.source_id for symbol in symbols}
    source_paths = {symbol.path for symbol in symbols}
    covered_by_source_ids = (
        source_ids if known_source_ids is None else source_ids | known_source_ids
    )
    covered_by_source_refs = (
        covered_by_source_ids
        | source_paths
        | (known_source_paths if known_source_paths is not None else set())
    )
    source_source_links = [
        (symbol.source_id, source_id)
        for symbol in symbols
        for source_id in symbol.metadata.covered_by
    ]
    known_source_source_links = [
        (source_id, covered_by)
        for source_id, covered_by in source_source_links
        if covered_by in covered_by_source_refs
    ]
    stale_source_source_links = [
        (source_id, covered_by)
        for source_id, covered_by in source_source_links
        if covered_by not in covered_by_source_refs
    ]
    annotated_sources = [
        symbol for symbol in symbols if symbol.metadata.testable is not None
    ]
    testable_true = [symbol for symbol in symbols if symbol.metadata.testable is True]
    testable_false = [symbol for symbol in symbols if symbol.metadata.testable is False]
    testable_infrastructure = [
        symbol
        for symbol in symbols
        if symbol.metadata.testable == TESTABLE_INFRASTRUCTURE
    ]
    expansion = expand_test_references(
        symbols,
        tests,
        scaffold_symbols,
        repo_root,
        known_source_ids=covered_by_source_ids,
    )
    source_test_links = expansion.links
    stale_by_source = expansion.stale_by_source
    referenced = {test for _, test in source_test_links}
    known_source_test_links = [
        (source_id, test)
        for source_id, test in source_test_links
        if test in all_test_ids
    ]
    runnable_source_test_links = [
        (source_id, test)
        for source_id, test in source_test_links
        if test in runnable_test_ids
    ]
    unfinished_source_test_links = [
        (source_id, test)
        for source_id, test in source_test_links
        if test in all_test_ids and test not in runnable_test_ids
    ]
    stale_source_test_links = [
        (source_id, test)
        for source_id, stale_tests in stale_by_source.items()
        for test in stale_tests
    ]
    sources_with_known_tests = {source_id for source_id, _ in known_source_test_links}
    sources_with_runnable_tests = {
        source_id for source_id, _ in runnable_source_test_links
    }
    known_tests_by_source: dict[str, list[str]] = {}
    for source_id, test in known_source_test_links:
        known_tests_by_source.setdefault(source_id, []).append(test)
    known_referenced_tests = referenced & all_test_ids
    runnable_referenced_tests = referenced & runnable_test_ids
    unfinished_referenced_tests = known_referenced_tests - runnable_test_ids
    todo_scope_test_ids = (
        known_referenced_tests if suppress_orphan_tests else all_test_ids
    )

    missing_testable = [
        symbol for symbol in symbols if symbol.metadata.testable is None
    ]
    testable_without_tests = [
        symbol
        for symbol in symbols
        if symbol.metadata.testable is True
        and not symbol.metadata.tests
        and not symbol.metadata.test_scaffolds
        and symbol.source_id not in sources_with_known_tests
    ]
    stale_test_references = []
    unfinished_coverage = []
    invalid_false = []
    manual_validation = []
    covered_by_missing = []
    feature_dimension_gaps = []
    test_todos = [
        {
            "test": test.nodeid,
            "todos": test.metadata.todos,
            "runnable": test.runnable,
            "unfinished": test.unfinished,
        }
        for test in sorted(tests.values(), key=lambda item: item.nodeid)
        if test.nodeid in todo_scope_test_ids and test.metadata.todos
    ]
    test_todo_count = sum(len(item["todos"]) for item in test_todos)
    runnable_test_todo_count = sum(
        len(item["todos"]) for item in test_todos if item["runnable"]
    )
    unfinished_test_todo_count = test_todo_count - runnable_test_todo_count
    broad_source_owners = broad_source_owner_rows(symbols, known_tests_by_source)
    broad_source_owner_kinds = Counter(
        item["owner_kind"] for item in broad_source_owners
    )

    for symbol in symbols:
        metadata = symbol.metadata
        if metadata.testable is True:
            stale = stale_by_source.get(symbol.source_id, [])
            if stale:
                stale_test_references.append({"source": symbol, "tests": stale})

            known_refs = [
                test
                for source_id, test in source_test_links
                if source_id == symbol.source_id
            ]
            if known_refs and not any(tests[test].runnable for test in known_refs):
                unfinished_coverage.append(symbol)

            gaps = feature_dimension_coverage_gaps(metadata, known_refs, tests)
            if gaps:
                feature_dimension_gaps.append({"source": symbol, "missing": gaps})

        elif metadata.testable is False:
            if metadata.manual:
                manual_validation.append(symbol)
            if not metadata.reason and not metadata.covered_by:
                invalid_false.append(
                    {
                        "source": symbol,
                        "message": "@testable false requires @reason or @covered-by",
                    }
                )
            missing_covered_by = [
                source_id
                for source_id in metadata.covered_by
                if source_id not in covered_by_source_refs
            ]
            if missing_covered_by:
                covered_by_missing.append(
                    {"source": symbol, "covered_by": missing_covered_by}
                )
        elif metadata.testable == TESTABLE_INFRASTRUCTURE:
            missing_covered_by = [
                source_id
                for source_id in metadata.covered_by
                if source_id not in covered_by_source_refs
            ]
            if missing_covered_by:
                covered_by_missing.append(
                    {"source": symbol, "covered_by": missing_covered_by}
                )

    orphan_runnable_tests = (
        [] if suppress_orphan_tests else sorted(runnable_test_ids - referenced)
    )
    summary = {
        "sources": len(symbols),
        "source_kinds": dict(
            sorted(Counter(symbol.kind for symbol in symbols).items())
        ),
        "source_languages": dict(
            sorted(Counter(symbol.language for symbol in symbols).items())
        ),
        "annotated_sources": len(annotated_sources),
        "testable_true": len(testable_true),
        "testable_false": len(testable_false),
        "testable_infrastructure": len(testable_infrastructure),
        "sources_with_known_tests": len(sources_with_known_tests),
        "sources_with_runnable_tests": len(sources_with_runnable_tests),
        "source_test_links": len(source_test_links) + len(stale_source_test_links),
        "source_test_links_known": len(known_source_test_links),
        "source_test_links_runnable": len(runnable_source_test_links),
        "source_test_links_unfinished": len(unfinished_source_test_links),
        "source_test_links_stale": len(stale_source_test_links),
        "source_source_links": len(source_source_links),
        "source_source_links_known": len(known_source_source_links),
        "source_source_links_stale": len(stale_source_source_links),
        "referenced_tests": len(known_referenced_tests),
        "referenced_runnable_tests": len(runnable_referenced_tests),
        "referenced_unfinished_tests": len(unfinished_referenced_tests),
        "missing_testable": len(missing_testable),
        "testable_without_tests": len(testable_without_tests),
        "unfinished_coverage": len(unfinished_coverage),
        "stale_test_references": len(stale_test_references),
        "invalid_false": len(invalid_false),
        "manual_validation": len(manual_validation),
        "covered_by_missing": len(covered_by_missing),
        "feature_dimension_gaps": len(feature_dimension_gaps),
        "broad_source_owners": len(broad_source_owners),
        "broad_source_owner_kinds": dict(sorted(broad_source_owner_kinds.items())),
        "test_todos": test_todo_count,
        "test_todo_groups": len(test_todos),
        "test_todos_runnable": runnable_test_todo_count,
        "test_todos_unfinished": unfinished_test_todo_count,
        "orphan_runnable_tests": len(orphan_runnable_tests),
        "orphan_tests_suppressed": suppress_orphan_tests,
        "source_test_suggestions_enabled": False,
        "source_test_suggestions": 0,
        "source_test_suggestions_likely_existing": 0,
        "source_test_suggestions_contextual": 0,
    }
    summary.update(test_execution_summary(tests))

    return Report(
        summary=summary,
        missing_testable=missing_testable,
        testable_without_tests=testable_without_tests,
        unfinished_coverage=unfinished_coverage,
        stale_test_references=stale_test_references,
        invalid_false=invalid_false,
        manual_validation=manual_validation,
        covered_by_missing=covered_by_missing,
        feature_dimension_gaps=feature_dimension_gaps,
        broad_source_owners=broad_source_owners,
        test_todos=test_todos,
        orphan_runnable_tests=orphan_runnable_tests,
        source_link_issues=expansion.issues,
    )


def attach_contract_traceability(
    report: Report,
    tests: dict[str, TestCase],
    repo_root: Path,
    *,
    changed_paths: Iterable[str] | None = None,
) -> None:
    """Attach template and style contracts to changed or full inventory runs."""
    from testing.utility import template_contracts

    changed_path_list = sorted(set(changed_paths or []))
    template_report = template_contracts.build_report(
        repo_root,
        changed_paths=changed_path_list if changed_paths is not None else None,
    )
    report.template_contract_summary = template_report.summary
    report.template_contract_findings = template_contracts.report_findings(
        template_report
    )
    template_test_ids = {
        entry.reference.nodeid for entry in template_report.entries
    }
    report.template_contract_tests = sorted(
        (tests[nodeid] for nodeid in template_test_ids if nodeid in tests),
        key=lambda test: test.nodeid,
    )
    template_dependencies: dict[str, set[str]] = {}
    for entry in template_report.entries:
        paths = template_dependencies.setdefault(entry.reference.nodeid, set())
        paths.add(f"lagniappe/web/templates/{entry.reference.template_path}")
        paths.update(
            f"lagniappe/web/templates/{label.split('::', 1)[0]}"
            for label in entry.included_macros
        )
    apply_test_dependency_fingerprints(tests, template_dependencies, repo_root)
    report.summary.update(test_execution_summary(tests))
    report.summary.update(
        {
            "template_contracts": template_report.summary["template_partials"],
            "template_contract_errors": sum(
                finding["severity"] == "error"
                for finding in report.template_contract_findings
            ),
            "template_contract_warnings": sum(
                finding["severity"] == "warning"
                for finding in report.template_contract_findings
            ),
            "template_contract_reviews": sum(
                finding["severity"] == "review"
                for finding in report.template_contract_findings
            ),
            "template_contract_tests": len(report.template_contract_tests),
        }
    )

    style_relevant = (repo_root / "src/style/styles.yaml").is_file() and (
        changed_paths is None
        or any(
            path.startswith(
                (
                    "src/style/",
                    "src/script/",
                    "lagniappe/web/templates/",
                    "build/",
                )
            )
            or path in {"package.json", "package-lock.json"}
            for path in changed_path_list
        )
    )
    if not style_relevant:
        return

    from testing.utility import style_traceability

    style_report, style_manifest = style_traceability.build_report(repo_root)
    if changed_paths is not None:
        style_report.query = style_traceability.query_manifest(
            style_manifest, changed_paths=changed_path_list
        )
    report.style_traceability_summary = style_report.summary
    report.style_traceability_findings = style_traceability.report_findings(
        style_report
    )
    report.summary.update(
        {
            "style_traceability": True,
            "style_traceability_errors": sum(
                item["severity"] == "error"
                for item in report.style_traceability_findings
            ),
            "style_traceability_warnings": sum(
                item["severity"] == "warning"
                for item in report.style_traceability_findings
            ),
            "style_traceability_reviews": sum(
                item["severity"] == "review"
                for item in report.style_traceability_findings
            ),
        }
    )


def build_report(
    repo_root: Path,
    config_path: Path,
    source_path: Path | None = None,
    test_target: str | None = None,
    feature_dimension: str | None = None,
    suggest_sources: bool = False,
    verify_collection: bool = False,
    results_path: Path | None = None,
    changed_paths: Iterable[str] | None = None,
    changed_line_ranges: dict[str, list[tuple[int, int]] | None] | None = None,
    *,
    source_paths: Iterable[Path] | None = None,
) -> Report:
    if source_path is not None and source_paths is not None:
        raise ValueError("pass source_path or source_paths, not both")
    selected_source_paths = list(source_paths or [])
    if source_path is not None:
        selected_source_paths = [source_path]

    changed_mode = changed_paths is not None
    changed_path_list = sorted(set(changed_paths or []))
    focused_modes = [
        bool(selected_source_paths),
        test_target is not None,
        feature_dimension is not None,
        changed_mode,
    ]
    if sum(focused_modes) > 1:
        raise ValueError(
            "pass only one of --source, --test, --feature-dimension, or --changed"
        )
    if (
        suggest_sources
        and not selected_source_paths
        and test_target is None
        and not changed_mode
    ):
        raise ValueError("--suggest-sources requires --test, --source, or --changed")

    TEST_FUNCTION_SOURCE_CACHE.clear()
    config = load_config(config_path, repo_root)
    scaffold_symbols = inventory_test_scaffolds(config, repo_root)
    source_scope_paths: list[str] = []
    all_symbols: list[SourceSymbol] | None = None
    if changed_mode:
        all_symbols = inventory_sources(config, repo_root)
        scan_prefixes = tuple(
            f"{str(value).strip('/')}/" for value in config["annotation_scan_roots"]
        )
        explicit_paths = [
            repo_root / path
            for path in changed_path_list
            if path.startswith(scan_prefixes)
            and (repo_root / path).is_file()
            and not is_excluded(repo_root / path, repo_root, config["exclude"])
            and (repo_root / path).suffix
            in set(config["python_extensions"]) | set(config["javascript_extensions"])
        ]
        if explicit_paths:
            explicit_symbols, _, _, _ = inventory_source_paths(
                config, repo_root, explicit_paths
            )
            known_ids = {symbol.source_id for symbol in all_symbols}
            all_symbols.extend(
                symbol for symbol in explicit_symbols if symbol.source_id not in known_ids
            )
        symbols = changed_sources_for_paths(
            all_symbols,
            changed_path_list,
            changed_line_ranges,
        )
        source_scope = "changed paths"
        source_scope_paths = [
            path for path in changed_path_list if any(s.path == path for s in symbols)
        ]
        source_file_symbols = list(symbols)
    elif not selected_source_paths:
        symbols = inventory_sources(config, repo_root)
        all_symbols = symbols
        source_scope = "configured source roots"
        source_file_symbols: list[SourceSymbol] = []
    else:
        symbols, source_file_symbols, source_scope, source_scope_paths = (
            inventory_source_paths(config, repo_root, selected_source_paths)
        )
        all_symbols = symbols
    referenceable_symbols = inventory_referenceable_source_symbols(
        config, repo_root, source_file_symbols
    )
    known_source_ids = {symbol.source_id for symbol in referenceable_symbols}
    known_source_paths = {symbol.path for symbol in referenceable_symbols}

    if verify_collection or results_path is not None:
        collected_tests = collect_tests(
            repo_root,
            config["test_roots"],
            verify_collection=verify_collection,
            results_path=results_path,
        )
    else:
        collected_tests = collect_tests(repo_root, config["test_roots"])
    tests = filter_tests_by_roots(collected_tests, config["test_roots"])
    focused_tests: list[TestCase] = []
    if test_target is not None:
        focused_tests = matching_tests_for_target(tests, test_target)
        if not focused_tests:
            raise ValueError(f"--test matched no discovered tests: {test_target}")
    elif changed_mode:
        focused_tests = changed_tests_for_paths(
            tests,
            changed_path_list,
            changed_line_ranges,
        )

    report = classify(
        symbols,
        tests,
        scaffold_symbols=scaffold_symbols,
        repo_root=repo_root,
        suppress_orphan_tests=(
            bool(selected_source_paths)
            or test_target is not None
            or feature_dimension is not None
            or changed_mode
        ),
        known_source_ids=known_source_ids,
        known_source_paths=known_source_paths,
    )
    apply_test_dependency_fingerprints(
        tests,
        source_test_dependency_paths(
            symbols, tests, scaffold_symbols, repo_root
        ),
        repo_root,
    )
    report.provenance = provenance(repo_root)
    report.summary.update(test_execution_summary(tests))
    report.summary["collection_mode"] = (
        "pytest-verified" if verify_collection else "static"
    )
    report.annotation_scope_issues = annotation_scope_issues(
        config, repo_root, referenceable_symbols
    )
    if changed_mode:
        changed_set = set(changed_path_list)
        report.annotation_scope_issues = [
            issue
            for issue in report.annotation_scope_issues
            if str(issue.get("path", "")) in changed_set
        ]
    all_source_link_issues = [
        *source_link_issues(referenceable_symbols),
        *report.source_link_issues,
    ]
    scoped_source_ids = {symbol.source_id for symbol in symbols}
    report.source_link_issues = [
        issue
        for issue in all_source_link_issues
        if not isinstance(issue.get("source"), SourceSymbol)
        or issue["source"].source_id in scoped_source_ids
        or (
            changed_mode
            and any(
                str(target).split("::", 1)[0] in set(changed_path_list)
                for target in issue.get("targets", [])
            )
        )
    ]
    metadata_tests = focused_tests if changed_mode else list(tests.values())
    report.metadata_issues = traceability_metadata_issues(symbols, metadata_tests)
    report.taxonomy = taxonomy_summary(symbols, metadata_tests)
    report.summary.update(
        {
            "annotation_scope_issues": len(report.annotation_scope_issues),
            "source_link_issues": len(report.source_link_issues),
            "metadata_issues": len(report.metadata_issues),
            "taxonomy_feature_alias_candidates": len(
                report.taxonomy["feature_alias_candidates"]
            ),
            "taxonomy_dimension_alias_candidates": len(
                report.taxonomy["dimension_alias_candidates"]
            ),
            "taxonomy_large_cross_products": len(
                report.taxonomy["large_cross_products"]
            ),
        }
    )
    report.summary["source_scope"] = source_scope
    if source_scope_paths:
        report.summary["source_paths"] = source_scope_paths
    if changed_mode:
        report.changed_paths = changed_path_list
        report.changed_tests = focused_tests
        attach_source_explanations(
            report, symbols, tests, scaffold_symbols, repo_root
        )
        references = source_reference_matches_for_tests(
            all_symbols or symbols,
            tests,
            focused_tests,
            scaffold_symbols,
            repo_root,
        )
        mappings, gaps = focused_test_feature_dimension_mappings(
            focused_tests, references
        )
        report.focused_tests = focused_tests
        report.focused_source_references = references
        report.focused_test_mappings = mappings
        report.focused_source_tag_gaps = gaps
        report.summary.update(
            {
                "changed_scope": True,
                "changed_paths": len(changed_path_list),
                "changed_source_files": len({symbol.path for symbol in symbols}),
                "changed_source_symbols": len(symbols),
                "changed_test_files": len({test.path for test in focused_tests}),
                "changed_tests": len(focused_tests),
                "changed_source_tag_gaps": sum(len(item["missing"]) for item in gaps),
            }
        )
        attach_contract_traceability(
            report,
            tests,
            repo_root,
            changed_paths=changed_path_list,
        )
    elif feature_dimension is not None:
        attach_feature_dimension_focus(
            report,
            symbols,
            tests,
            feature_dimension,
            repo_root,
            scaffold_symbols=scaffold_symbols,
        )
    elif test_target is not None:
        attach_test_focus(
            report,
            symbols,
            tests,
            focused_tests,
            test_target,
            repo_root,
            suggest_sources=suggest_sources,
            scaffold_symbols=scaffold_symbols,
        )
    elif selected_source_paths:
        attach_source_explanations(
            report, symbols, tests, scaffold_symbols, repo_root
        )
        report.summary["source_test_suggestions_enabled"] = suggest_sources
        report.source_test_suggestions = (
            source_test_suggestions_for_sources(
                symbols,
                tests,
                repo_root,
                source_suggestion_config(config),
            )
            if suggest_sources
            else []
        )
        likely = [
            item
            for item in report.source_test_suggestions
            if item["category"] == "likely_existing"
        ]
        contextual = [
            item
            for item in report.source_test_suggestions
            if item["category"] == "contextual"
        ]
        report.summary.update(
            {
                "source_test_suggestions": len(report.source_test_suggestions),
                "source_test_suggestions_likely_existing": len(likely),
                "source_test_suggestions_contextual": len(contextual),
            }
        )
    if not any(focused_modes):
        attach_contract_traceability(report, tests, repo_root)
    return report


def symbol_line(symbol: SourceSymbol) -> str:
    return f"{symbol.source_id}:{symbol.lineno}"


def limited(items: list[object]) -> tuple[list[object], int]:
    return list(items), 0


def format_symbol_section(title: str, symbols: list[SourceSymbol]) -> list[str]:
    if not symbols:
        return []
    lines = [f"\n{title}: {len(symbols)}"]
    shown, remaining = limited(symbols)
    for symbol in shown:
        lines.append(f"  - {symbol_line(symbol)}")
    if remaining:
        lines.append(f"  ... {remaining} more")
    return lines


def nearest_missing_class(
    symbol: SourceSymbol, classes: dict[tuple[str, str], SourceSymbol]
) -> SourceSymbol | None:
    parts = symbol.qualname.split(".")
    for index in range(len(parts) - 1, 0, -1):
        parent = ".".join(parts[:index])
        if found := classes.get((symbol.path, parent)):
            return found
    return None


def grouped_missing_metadata_rows(
    symbols: list[SourceSymbol],
) -> list[tuple[SourceSymbol, int]]:
    classes = {
        (symbol.path, symbol.qualname): symbol
        for symbol in symbols
        if symbol.kind == "class"
    }
    child_counts: dict[str, int] = {}
    rows: list[tuple[SourceSymbol, int]] = []

    for symbol in symbols:
        if symbol.kind == "class":
            rows.append((symbol, 0))
            continue

        parent = nearest_missing_class(symbol, classes)
        if parent:
            child_counts[parent.source_id] = child_counts.get(parent.source_id, 0) + 1
        else:
            rows.append((symbol, 0))

    return [
        (symbol, child_counts.get(symbol.source_id, child_count))
        for symbol, child_count in rows
    ]


def format_missing_metadata_section(symbols: list[SourceSymbol]) -> list[str]:
    if not symbols:
        return []

    lines = [f"\nMissing @testable metadata: {len(symbols)}"]
    for symbol, child_count in grouped_missing_metadata_rows(symbols):
        suffix = f" (unannotated children: {child_count})" if child_count else ""
        lines.append(f"  - {symbol_line(symbol)}{suffix}")
    return lines


def format_feature_dimension_gap(gap: dict[str, object]) -> str:
    if gap.get("kind") == "pair":
        return f"missing pair: {gap['name']}"
    return f"missing {gap['kind']}: {gap['name']}"


def format_metadata_tags(metadata: Metadata) -> str:
    parts = []
    if metadata.matrices:
        parts.append(
            "matrices="
            + "; ".join(
                f"{' '.join(clause.features)} : {' '.join(clause.dimensions)}"
                for clause in metadata.matrices
            )
        )
    if metadata.pairs:
        parts.append(f"pairs={', '.join(metadata.pairs)}")
    if metadata.features and not metadata.matrices:
        parts.append(f"features={', '.join(metadata.features)}")
    if metadata.dimensions and not metadata.matrices:
        parts.append(f"dimensions={', '.join(metadata.dimensions)}")
    if metadata.sources:
        parts.append(f"sources={', '.join(metadata.sources)}")
    if metadata.templates:
        parts.append(f"templates={', '.join(metadata.templates)}")
    if metadata.todos:
        parts.append(f"todos={len(metadata.todos)}")
    return "; ".join(parts) if parts else "no parsed test metadata"


def format_focused_pair_sources(
    sources: list[SourceSymbol], template_sources: list[dict[str, object]] | None = None
) -> list[str]:
    template_sources = template_sources or []
    if not sources and not template_sources:
        return ["      source: none"]
    lines = [f"      source: {symbol_line(source)}" for source in sources]
    for item in template_sources:
        source = item["source"]
        templates = ", ".join(item["templates"])
        lines.append(
            f"      template-backed source: {symbol_line(source)} "
            f"(templates={templates})"
        )
    return lines


def format_broad_owner_line(item: dict[str, object]) -> str:
    source = item["source"]
    return (
        f"{symbol_line(source)} "
        f"(kind={item['owner_kind']}, tests={item['test_count']}, "
        f"features={item['feature_count']}, "
        f"dimensions={item['dimension_count']})"
    )


def format_broad_source_owners(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return []
    lines = [f"\nBroad source owners: {len(items)}"]
    shown, remaining = limited(items)
    for item in shown:
        lines.append(f"  - {format_broad_owner_line(item)}")
    if remaining:
        lines.append(f"  ... {remaining} more")
    return lines


def format_source_suggestion_item(item: dict[str, object]) -> list[str]:
    source = item["source"]
    distance = item["line_distance"]
    suffix = f", nearest focus line distance={distance}" if distance is not None else ""
    lines = [f"  - {symbol_line(source)}"]
    if item["missing_pairs"]:
        lines.append(f"    fills missing pairs: {', '.join(item['missing_pairs'])}")
    lines.append(f"    matches: {format_tag_matches(item['matches'])}{suffix}")
    for nodeid in item["tests"]:
        lines.append(f"    matched test: {nodeid}")
    return lines


def format_source_suggestion_group(
    title: str, items: list[dict[str, object]]
) -> list[str]:
    if not items:
        return []
    lines = [f"\n{title}: {len(items)}"]
    shown, remaining = limited(items)
    for item in shown:
        lines.extend(format_source_suggestion_item(item))
    if remaining:
        lines.append(f"  ... {remaining} more")
    return lines


def format_source_suggestions(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return []
    likely = [item for item in items if item["category"] == "likely_missing"]
    additional = [item for item in items if item["category"] == "additional"]
    lines = [f"\nSuggested source candidates: {len(items)}"]
    lines.extend(format_source_suggestion_group("Likely missing sources", likely))
    lines.extend(
        format_source_suggestion_group("Additional source candidates", additional)
    )
    return lines


def format_source_test_suggestion_item(item: dict[str, object]) -> list[str]:
    source = item["source"]
    lines = [f"  - {symbol_line(source)}"]
    lines.append(f"    matches: {format_tag_matches(item['matches'])}")
    for test in item["tests"]:
        status = test_status(test)
        lines.append(f"    candidate test: {test.nodeid} ({status})")
    return lines


def format_source_test_suggestion_group(
    title: str, items: list[dict[str, object]]
) -> list[str]:
    if not items:
        return []
    lines = [f"\n{title}: {len(items)}"]
    for item in items:
        lines.extend(format_source_test_suggestion_item(item))
    return lines


def format_source_test_suggestions(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return []
    likely = [item for item in items if item["category"] == "likely_existing"]
    contextual = [item for item in items if item["category"] == "contextual"]
    lines = [f"\nSuggested test candidates: {len(items)}"]
    lines.extend(format_source_test_suggestion_group("Likely matching tests", likely))
    lines.extend(
        format_source_test_suggestion_group("Contextual test candidates", contextual)
    )
    return lines


def test_status(test: TestCase) -> str:
    if test.unfinished:
        return "unfinished"
    if test.execution_current:
        return test.execution
    if test.collection_verified:
        return "collectable"
    return "discovered; not run"


def decision_label(value: bool | str | None) -> str:
    if value is True:
        return "testable"
    if value is False:
        return "delegated/not directly tested"
    if value == TESTABLE_INFRASTRUCTURE:
        return "infrastructure"
    return "missing"


def format_source_explanations(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return []
    lines = [f"\nSource traceability map: {len(items)}"]
    for item in items:
        source = item["source"]
        lines.append(
            f"  - {symbol_line(source)} ({decision_label(item['decision'])})"
        )
        if item["reason"]:
            lines.append(f"    reason: {item['reason']}")
        for owner in item["covered_by"]:
            lines.append(f"    owner: {owner}")
        for test in item["tests"]:
            lines.append(f"    required test: {test.nodeid} ({test_status(test)})")
        for related in item["related_tests"]:
            test = related["test"]
            lines.append(
                f"    related test: {test.nodeid} "
                f"(pairs={', '.join(related['pairs'])}; {test_status(test)})"
            )
        if item["features"]:
            lines.append(f"    features: {', '.join(item['features'])}")
        if item["dimensions"]:
            lines.append(f"    dimensions: {', '.join(item['dimensions'])}")
        if item["pairs"]:
            lines.append(f"    exact pairs: {', '.join(item['pairs'])}")
        if item["matrices"]:
            for matrix in item["matrices"]:
                lines.append(
                    f"    matrix: {' '.join(matrix.features)} : "
                    f"{' '.join(matrix.dimensions)}"
                )
        if item["realized_pairs"]:
            lines.append(f"    realized pairs: {', '.join(item['realized_pairs'])}")
        if item["templates"]:
            lines.append(f"    templates: {', '.join(item['templates'])}")
    return lines


def format_changed_test_evidence(report: Report) -> list[str]:
    if not report.summary.get("changed_scope"):
        return []
    lines = [f"\nChanged test evidence: {len(report.changed_tests)}"]
    mappings = {
        item["test"].nodeid: item for item in report.focused_test_mappings
    }
    references_by_test: dict[str, list[SourceSymbol]] = {}
    for item in report.focused_source_references:
        for nodeid in item["tests"]:
            references_by_test.setdefault(nodeid, []).append(item["source"])
    for test in report.changed_tests:
        lines.append(f"  - {test.location} ({test_status(test)})")
        for source in references_by_test.get(test.nodeid, []):
            lines.append(f"    source: {symbol_line(source)}")
        mapping = mappings.get(test.nodeid, {})
        for pair in mapping.get("pairs", []):
            mapped = len(pair["sources"]) + len(pair.get("template_sources", []))
            lines.append(f"    pair: {pair['name']} (owners={mapped})")
    if not report.changed_tests:
        lines.append("  none")
    return lines


def format_traceability_diagnostics(report: Report) -> list[str]:
    lines: list[str] = []
    if report.annotation_scope_issues:
        lines.append(
            f"\nAnnotations outside configured scope: {len(report.annotation_scope_issues)}"
        )
        for issue in report.annotation_scope_issues:
            lines.append(
                f"  - {issue.get('location') or issue.get('path')}: {issue['message']}"
            )
    if report.source_link_issues:
        lines.append(f"\nSource ownership link issues: {len(report.source_link_issues)}")
        for issue in report.source_link_issues:
            source = issue.get("source")
            location = str(issue.get("location") or "source")
            if isinstance(source, SourceSymbol):
                location = symbol_line(source)
            lines.append(
                f"  - [{str(issue['severity']).upper()}] {location}: {issue['message']}"
            )
    if report.metadata_issues:
        lines.append(f"\nMalformed traceability metadata: {len(report.metadata_issues)}")
        for issue in report.metadata_issues:
            lines.append(f"  - {issue['location']}: {issue['message']}")

    aliases = [
        *report.taxonomy.get("feature_alias_candidates", []),
        *report.taxonomy.get("dimension_alias_candidates", []),
    ]
    cross_products = report.taxonomy.get("large_cross_products", [])
    if aliases or cross_products:
        lines.append(
            "\nTaxonomy review: "
            f"alias candidates={len(aliases)}, large cross-products={len(cross_products)}"
        )
        for group in aliases:
            lines.append(f"  - possible aliases: {', '.join(group)}")
        for item in cross_products:
            lines.append(
                f"  - {symbol_line(item['source'])}: "
                f"{item['features']} features x {item['dimensions']} dimensions "
                f"= {item['pairs']} implied pairs"
            )
    return lines


def format_unfinished_coverage(report: Report) -> list[str]:
    return format_symbol_section(
        "Coverage references unfinished tests", report.unfinished_coverage
    )


def format_test_todos(report: Report) -> list[str]:
    if not report.test_todos:
        return []
    lines = [f"\nTest TODOs: {report.summary['test_todos']}"]
    shown, remaining = limited(report.test_todos)
    for item in shown:
        status = "unfinished" if item["unfinished"] else "runnable"
        lines.append(f"  - {item['test']} ({status})")
        for todo in item["todos"]:
            lines.append(f"    todo: {todo}")
    if remaining:
        lines.append(f"  ... {remaining} more")
    return lines


def format_feature_dimension_report(report: Report) -> str:
    scope = report.summary["feature_dimension_scope"]
    link_tests_by_source = {
        item["source"].source_id: item["tests"]
        for item in report.feature_dimension_links
    }
    lines = [
        "Traceability Feature:Dimension Report",
        "",
        "Summary:",
        f"  pair: {scope}",
        f"  source symbols tagged: {report.summary['feature_dimension_sources']}",
        f"  tests tagged: {report.summary['feature_dimension_tests']}",
        "  tests runnable/unfinished: "
        f"{report.summary['feature_dimension_tests_runnable']}/"
        f"{report.summary['feature_dimension_tests_unfinished']}",
        f"  templates tagged: {report.summary['feature_dimension_templates']}",
        "  source/test reference links tagged with pair: "
        f"{report.summary['feature_dimension_source_test_links']}",
    ]

    lines.append(
        f"\nSource symbols tagged {scope}: {len(report.feature_dimension_sources)}"
    )
    if not report.feature_dimension_sources:
        lines.append("  none")
    for source in report.feature_dimension_sources:
        lines.append(f"  - {symbol_line(source)}")
        if source.metadata.templates:
            lines.append(f"    templates: {', '.join(source.metadata.templates)}")
        linked_tests = link_tests_by_source.get(source.source_id, [])
        if linked_tests:
            lines.append("    referenced tests tagged with pair:")
            for test in linked_tests:
                lines.append(f"      - {test.nodeid} ({test_status(test)})")

    lines.append(f"\nTests tagged {scope}: {len(report.feature_dimension_tests)}")
    if not report.feature_dimension_tests:
        lines.append("  none")
    for test in report.feature_dimension_tests:
        lines.append(f"  - {test.location} ({test_status(test)})")
        if test.metadata.templates:
            lines.append(f"    templates: {', '.join(test.metadata.templates)}")
        for todo in test.metadata.todos:
            lines.append(f"    todo: {todo}")

    lines.append(
        f"\nTemplates tagged {scope}: {len(report.feature_dimension_templates)}"
    )
    if not report.feature_dimension_templates:
        lines.append("  none")
    for item in report.feature_dimension_templates:
        lines.append(f"  - {item['template']}")
        for source in item["sources"]:
            lines.append(f"    source: {symbol_line(source)}")
        for test in item["tests"]:
            lines.append(f"    test: {test.nodeid} ({test_status(test)})")

    return "\n".join(lines)


def format_test_focus_report(report: Report) -> str:
    suggestions = (
        (
            f"{report.summary['focused_source_suggestions']} "
            f"(likely={report.summary['focused_source_suggestions_likely_missing']}, "
            f"additional={report.summary['focused_source_suggestions_additional']})"
        )
        if report.summary.get("focused_source_suggestions_enabled")
        else "not requested"
    )
    broad_kinds = format_breakdown(
        report.summary.get("focused_broad_source_owner_kinds", {})
    )
    lines = [
        "Traceability Test Focus Report",
        "",
        "Summary:",
        f"  test scope: {report.summary['test_scope']}",
        f"  tests matched: {report.summary['focused_tests']}",
        "  tests runnable/unfinished: "
        f"{report.summary['focused_tests_runnable']}/"
        f"{report.summary['focused_tests_unfinished']}",
        f"  tests with parsed annotations: {report.summary['focused_tests_annotated']}",
        f"  source symbols referencing these tests: {report.summary['focused_source_references']}",
        "  missing feature:dimension source tags: "
        f"{report.summary['focused_source_tag_gaps']} "
        f"in {report.summary['focused_source_tag_gap_tests']} tests",
        "  broad source owners among focused references: "
        f"{report.summary['focused_broad_source_owners']} ({broad_kinds})",
        f"  suggested source candidates: {suggestions}",
    ]

    lines.append(
        f"\nFocused test feature:dimension mappings: "
        f"{len(report.focused_test_mappings)}"
    )
    for item in report.focused_test_mappings:
        test = item["test"]
        status = test_status(test)
        lines.append(f"  - {test.location} ({status})")
        lines.append(f"    {format_metadata_tags(test.metadata)}")
        for todo in test.metadata.todos:
            lines.append(f"    todo: {todo}")
        pairs = item["pairs"]
        if not pairs:
            lines.append("    feature:dimension pairs: none")
        for pair in pairs:
            lines.append(f"    {pair['name']}")
            lines.extend(
                format_focused_pair_sources(
                    pair["sources"], pair.get("template_sources")
                )
            )

    if report.focused_source_tag_gaps:
        lines.append(
            "\nAnnotated tests missing feature:dimension source tags: "
            f"{len(report.focused_source_tag_gaps)}"
        )
        for item in report.focused_source_tag_gaps:
            test = item["test"]
            status = test_status(test)
            lines.append(f"  - {test.location} ({status})")
            for pair in item["missing"]:
                lines.append(f"    missing source tag: {pair}")

    lines.extend(format_broad_source_owners(report.broad_source_owners))
    if report.summary.get("focused_source_suggestions_enabled"):
        lines.extend(format_source_suggestions(report.focused_source_suggestions))

    return "\n".join(lines)


def format_detailed_report(report: Report, *, verbose: bool = False) -> str:
    if report.summary.get("feature_dimension_scope"):
        return format_feature_dimension_report(report)
    if report.summary.get("test_scope"):
        return format_test_focus_report(report)

    lines = [
        "Traceability Report",
        "",
        "Summary:",
        f"  source scope: {report.summary.get('source_scope', 'configured source roots')}",
        f"  source symbols: {report.summary['sources']}",
        f"  source symbols by kind: {format_breakdown(report.summary['source_kinds'])}",
        "  source symbols by language: "
        f"{format_breakdown(report.summary['source_languages'])}",
        f"  tests runnable/discovered: {report.summary['tests_runnable']}/{report.summary['tests_discovered']}",
        "  latest test results: "
        f"passed={report.summary['tests_passed']}, "
        f"failed={report.summary['tests_failed']}, "
        f"skipped={report.summary['tests_skipped']}, "
        f"not-run={report.summary['tests_not_run']} "
        f"(current={report.summary['test_results_current']})",
        "  annotated source symbols: "
        f"{report.summary['annotated_sources']} "
        f"(true={report.summary['testable_true']}, "
        f"false={report.summary['testable_false']}, "
        f"infrastructure={report.summary['testable_infrastructure']})",
        "  sources matched to tests: "
        f"{report.summary['sources_with_known_tests']} "
        f"(runnable={report.summary['sources_with_runnable_tests']})",
        "  source/test reference links: "
        f"total={report.summary['source_test_links']}, "
        f"collected={report.summary['source_test_links_known']}, "
        f"runnable={report.summary['source_test_links_runnable']}, "
        f"unfinished={report.summary['source_test_links_unfinished']}, "
        f"stale={report.summary['source_test_links_stale']}",
        "  collected tests referenced: "
        f"{report.summary['referenced_tests']} "
        f"(runnable={report.summary['referenced_runnable_tests']}, "
        f"unfinished={report.summary['referenced_unfinished_tests']})",
    ]

    optional_summary_lines = [
        (
            report.summary["source_source_links"],
            "  source/source @covered-by links: "
            f"total={report.summary['source_source_links']}, "
            f"resolved={report.summary['source_source_links_known']}, "
            f"stale={report.summary['source_source_links_stale']}",
        ),
        (
            report.summary["missing_testable"],
            f"  missing @testable metadata: {report.summary['missing_testable']}",
        ),
        (
            report.summary["testable_without_tests"],
            f"  testable without tests: {report.summary['testable_without_tests']}",
        ),
        (
            report.summary["unfinished_coverage"],
            f"  unfinished coverage: {report.summary['unfinished_coverage']}",
        ),
        (
            report.summary["stale_test_references"],
            f"  stale test reference groups: {report.summary['stale_test_references']}",
        ),
        (
            report.summary["invalid_false"],
            f"  invalid @testable false blocks: {report.summary['invalid_false']}",
        ),
        (
            report.summary["manual_validation"],
            f"  manual validation required: {report.summary['manual_validation']}",
        ),
        (
            report.summary["covered_by_missing"],
            f"  missing @covered-by sources: {report.summary['covered_by_missing']}",
        ),
        (
            report.summary["feature_dimension_gaps"],
            f"  feature/dimension gaps: {report.summary['feature_dimension_gaps']}",
        ),
        (
            report.summary["broad_source_owners"],
            f"  broad source owners: {report.summary['broad_source_owners']}",
        ),
        (
            report.summary["test_todos"],
            "  test TODOs: "
            f"{report.summary['test_todos']} "
            f"in {report.summary['test_todo_groups']} tests "
            f"(runnable={report.summary['test_todos_runnable']}, "
            f"unfinished={report.summary['test_todos_unfinished']})",
        ),
    ]
    if report.summary["broad_source_owners"]:
        optional_summary_lines.append(
            (
                report.summary["broad_source_owners"],
                "  broad source owners by kind: "
                f"{format_breakdown(report.summary['broad_source_owner_kinds'])}",
            )
        )
    if (
        not report.summary.get("orphan_tests_suppressed")
        and report.summary["orphan_runnable_tests"]
    ):
        optional_summary_lines.append(
            (
                report.summary["orphan_runnable_tests"],
                "  runnable tests not referenced: "
                f"{report.summary['orphan_runnable_tests']}",
            )
        )
    if report.summary.get("source_test_suggestions_enabled"):
        optional_summary_lines.append(
            (
                report.summary["source_test_suggestions"],
                "  suggested test candidates: "
                f"{report.summary['source_test_suggestions']} "
                f"(likely={report.summary['source_test_suggestions_likely_existing']}, "
                f"contextual={report.summary['source_test_suggestions_contextual']})",
            )
        )
    lines.extend(line for count, line in optional_summary_lines if count)

    lines.extend(format_source_explanations(report.source_explanations))
    lines.extend(format_changed_test_evidence(report))
    lines.extend(format_traceability_diagnostics(report))

    lines.extend(format_missing_metadata_section(report.missing_testable))
    lines.extend(
        format_symbol_section(
            "@testable true without @tests/@scaffolding",
            report.testable_without_tests,
        )
    )
    lines.extend(format_unfinished_coverage(report))

    if report.stale_test_references:
        lines.append(f"\nStale test references: {len(report.stale_test_references)}")
        shown, remaining = limited(report.stale_test_references)
        for item in shown:
            source = item["source"]
            lines.append(f"  - {symbol_line(source)}")
            for test in item["tests"]:
                lines.append(f"    missing: {test}")
        if remaining:
            lines.append(f"  ... {remaining} more")

    if report.invalid_false:
        lines.append(f"\nInvalid @testable false blocks: {len(report.invalid_false)}")
        shown, remaining = limited(report.invalid_false)
        for item in shown:
            lines.append(f"  - {symbol_line(item['source'])}: {item['message']}")
        if remaining:
            lines.append(f"  ... {remaining} more")

    lines.extend(
        format_symbol_section("Manual validation required", report.manual_validation)
    )
    if report.covered_by_missing:
        lines.append(f"\nMissing @covered-by sources: {len(report.covered_by_missing)}")
        shown, remaining = limited(report.covered_by_missing)
        for item in shown:
            lines.append(f"  - {symbol_line(item['source'])}")
            for source_id in item["covered_by"]:
                lines.append(f"    missing: {source_id}")
        if remaining:
            lines.append(f"  ... {remaining} more")

    if report.feature_dimension_gaps:
        lines.append(f"\nFeature/dimension gaps: {len(report.feature_dimension_gaps)}")
        shown, remaining = limited(report.feature_dimension_gaps)
        for item in shown:
            lines.append(f"  - {symbol_line(item['source'])}")
            for gap in item["missing"]:
                lines.append(f"    {format_feature_dimension_gap(gap)}")
        if remaining:
            lines.append(f"  ... {remaining} more")

    lines.extend(format_broad_source_owners(report.broad_source_owners))

    lines.extend(format_test_todos(report))

    lines.extend(format_source_test_suggestions(report.source_test_suggestions))

    if (
        not report.summary.get("orphan_tests_suppressed")
        and report.orphan_runnable_tests
    ):
        lines.append(
            f"\nRunnable tests not referenced by source: {len(report.orphan_runnable_tests)}"
        )
        shown, remaining = limited(report.orphan_runnable_tests)
        for nodeid in shown:
            lines.append(f"  - {nodeid}")
        if remaining:
            lines.append(f"  ... {remaining} more")

    return "\n".join(lines)


def format_report(report: Report, *, verbose: bool = False) -> str:
    if (
        verbose
        or report.summary.get("feature_dimension_scope")
        or report.summary.get("test_scope")
    ):
        return format_detailed_report(report, verbose=verbose)

    findings = report_findings(report)
    actionable = [
        finding for finding in findings if finding["severity"] in {"error", "warning"}
    ]
    counts = Counter(finding["severity"] for finding in findings)
    lines = [
        "Traceability Report",
        "",
        "Summary:",
        f"  source scope: {report.summary.get('source_scope', 'configured source roots')}",
        f"  source decisions: {report.summary['annotated_sources']}/{report.summary['sources']}",
        f"  sources matched to tests: {report.summary['sources_with_known_tests']}",
        f"  tests runnable/discovered: {report.summary['tests_runnable']}/{report.summary['tests_discovered']}",
        "  latest current test results: "
        f"passed={report.summary['tests_passed']}, "
        f"failed={report.summary['tests_failed']}, "
        f"not-run={report.summary['tests_not_run']} "
        f"(current={report.summary['test_results_current']})",
        "  findings: "
        f"errors={counts['error']}, warnings={counts['warning']}, "
        f"review={counts['review']}",
    ]
    if report.summary.get("changed_scope"):
        lines.append(
            "  affected template contracts: "
            f"{report.summary.get('template_contracts', 0)} "
            f"across {report.summary.get('template_contract_tests', 0)} tests "
            f"(errors={report.summary.get('template_contract_errors', 0)}, "
            f"warnings={report.summary.get('template_contract_warnings', 0)}, "
            f"review={report.summary.get('template_contract_reviews', 0)})"
        )
        if report.summary.get("style_traceability"):
            lines.append(
                "  affected style graph: "
                f"errors={report.summary.get('style_traceability_errors', 0)}, "
                f"warnings={report.summary.get('style_traceability_warnings', 0)}, "
                f"review={report.summary.get('style_traceability_reviews', 0)}"
            )
    if actionable:
        lines.append("\nFindings:")
        shown, remaining = limited_items(actionable, TEXT_SECTION_LIMIT)
        for finding in shown:
            lines.append(
                f"  [{finding['severity'].upper()}] {finding['location']}: "
                f"{finding['message']} ({finding['id']})"
            )
        if remaining:
            lines.append(
                f"  ... {remaining} more; use --verbose for the full inventory"
            )
    else:
        lines.append("\nNo error/warning traceability findings.")
    return "\n".join(lines)


def format_breakdown(values: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items()) or "none"


def markdown_feature_dimension_gap(gap: dict[str, object]) -> str:
    if gap.get("kind") == "pair":
        return f"missing pair: {markdown_code(gap['name'])}"
    return f"missing {markdown_escape(gap['kind'])}: {markdown_code(gap['name'])}"


def markdown_symbol_section(title: str, symbols: list[SourceSymbol]) -> list[str]:
    if not symbols:
        return []
    lines = [markdown_section_count(title, len(symbols)), ""]
    shown, remaining = limited(symbols)
    lines.extend(f"- {markdown_code(symbol_line(symbol))}" for symbol in shown)
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_missing_metadata_section(symbols: list[SourceSymbol]) -> list[str]:
    if not symbols:
        return []

    lines = [markdown_section_count("Missing @testable metadata", len(symbols)), ""]
    for symbol, child_count in grouped_missing_metadata_rows(symbols):
        suffix = f" (unannotated children: {child_count})" if child_count else ""
        lines.append(f"- {markdown_code(symbol_line(symbol))}{suffix}")
    lines.append("")
    return lines


def markdown_metadata_tags(metadata: Metadata) -> str:
    parts = []
    if metadata.pairs:
        parts.append(f"pairs={markdown_list(metadata.pairs)}")
    if metadata.features:
        parts.append(f"features={markdown_list(metadata.features)}")
    if metadata.dimensions:
        parts.append(f"dimensions={markdown_list(metadata.dimensions)}")
    if metadata.templates:
        parts.append(f"templates={markdown_list(metadata.templates)}")
    if metadata.todos:
        parts.append(f"todos={len(metadata.todos)}")
    return "; ".join(parts) if parts else "_No parsed test metadata._"


def markdown_focused_pair_sources(
    sources: list[SourceSymbol], template_sources: list[dict[str, object]] | None = None
) -> list[str]:
    template_sources = template_sources or []
    if not sources and not template_sources:
        return ["    - source: _None._"]
    lines = [
        f"    - source: {markdown_code(symbol_line(source))}" for source in sources
    ]
    for item in template_sources:
        source = item["source"]
        templates = markdown_list(item["templates"])
        lines.append(
            f"    - template-backed source: {markdown_code(symbol_line(source))} "
            f"(templates={templates})"
        )
    return lines


def markdown_tag_matches(matches: list[dict[str, str]]) -> str:
    groups = [
        ("pair", "pairs"),
        ("feature", "features"),
        ("dimension", "dimensions"),
        ("path", "paths"),
        ("symbol", "symbols"),
        ("context", "context"),
    ]
    parts = []
    for kind, label in groups:
        values = [match["name"] for match in matches if match["kind"] == kind]
        if values:
            parts.append(f"{label}={markdown_list(values)}")
    return "; ".join(parts) if parts else "_None._"


def markdown_broad_source_owners(report: Report) -> list[str]:
    if not report.broad_source_owners:
        return []
    lines = [
        markdown_section_count("Broad source owners", len(report.broad_source_owners)),
        "",
    ]
    shown, remaining = limited(report.broad_source_owners)
    for item in shown:
        source = item["source"]
        lines.append(
            f"- {markdown_code(symbol_line(source))} "
            f"(kind={markdown_escape(item['owner_kind'])}, "
            f"tests={item['test_count']}, "
            f"features={item['feature_count']}, "
            f"dimensions={item['dimension_count']})"
        )
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_source_suggestion_item(item: dict[str, object]) -> list[str]:
    source = item["source"]
    distance = item["line_distance"]
    suffix = f", nearest focus line distance={distance}" if distance is not None else ""
    lines = [f"- {markdown_code(symbol_line(source))}"]
    if item["missing_pairs"]:
        lines.append(f"  - fills missing pairs: {markdown_list(item['missing_pairs'])}")
    lines.append(f"  - matches: {markdown_tag_matches(item['matches'])}{suffix}")
    for nodeid in item["tests"]:
        lines.append(f"  - matched test: {markdown_code(nodeid)}")
    return lines


def markdown_source_suggestion_group(
    title: str, items: list[dict[str, object]]
) -> list[str]:
    if not items:
        return []
    lines = [markdown_section_count(title, len(items)), ""]
    shown, remaining = limited(items)
    for item in shown:
        lines.extend(markdown_source_suggestion_item(item))
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_source_suggestions(report: Report) -> list[str]:
    if not report.focused_source_suggestions:
        return []
    likely = [
        item
        for item in report.focused_source_suggestions
        if item["category"] == "likely_missing"
    ]
    additional = [
        item
        for item in report.focused_source_suggestions
        if item["category"] == "additional"
    ]
    lines = [
        markdown_section_count(
            "Suggested source candidates", len(report.focused_source_suggestions)
        ),
        "",
    ]
    lines.extend(markdown_source_suggestion_group("Likely Missing Sources", likely))
    lines.extend(
        markdown_source_suggestion_group("Additional Source Candidates", additional)
    )
    return lines


def markdown_source_test_suggestion_item(item: dict[str, object]) -> list[str]:
    source = item["source"]
    lines = [f"- {markdown_code(symbol_line(source))}"]
    lines.append(f"  - matches: {markdown_tag_matches(item['matches'])}")
    for test in item["tests"]:
        status = test_status(test)
        lines.append(f"  - candidate test: {markdown_code(test.nodeid)} _{status}_")
    return lines


def markdown_source_test_suggestion_group(
    title: str, items: list[dict[str, object]]
) -> list[str]:
    if not items:
        return []
    lines = [markdown_section_count(title, len(items)), ""]
    for item in items:
        lines.extend(markdown_source_test_suggestion_item(item))
    lines.append("")
    return lines


def markdown_source_test_suggestions(report: Report) -> list[str]:
    if not report.source_test_suggestions:
        return []
    likely = [
        item
        for item in report.source_test_suggestions
        if item["category"] == "likely_existing"
    ]
    contextual = [
        item
        for item in report.source_test_suggestions
        if item["category"] == "contextual"
    ]
    lines = [
        markdown_section_count(
            "Suggested test candidates", len(report.source_test_suggestions)
        ),
        "",
    ]
    lines.extend(markdown_source_test_suggestion_group("Likely Matching Tests", likely))
    lines.extend(
        markdown_source_test_suggestion_group("Contextual Test Candidates", contextual)
    )
    return lines


def markdown_unfinished_coverage(report: Report) -> list[str]:
    return markdown_symbol_section(
        "Coverage references unfinished tests", report.unfinished_coverage
    )


def markdown_test_todos(report: Report) -> list[str]:
    if not report.test_todos:
        return []
    lines = [
        markdown_section_count("Test TODOs", int(report.summary["test_todos"])),
        "",
    ]
    shown, remaining = limited(report.test_todos)
    for item in shown:
        status = "unfinished" if item["unfinished"] else "runnable"
        lines.append(f"- {markdown_code(item['test'])} _{status}_")
        for todo in item["todos"]:
            lines.append(f"  - todo: {markdown_escape(todo)}")
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def test_focus_report_to_markdown(report: Report) -> str:
    suggestions = (
        (
            f"{report.summary['focused_source_suggestions']} "
            f"(likely={report.summary['focused_source_suggestions_likely_missing']}, "
            f"additional={report.summary['focused_source_suggestions_additional']})"
        )
        if report.summary.get("focused_source_suggestions_enabled")
        else "not requested"
    )
    lines = [
        "# Traceability Test Focus Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    rows = [
        ("Test scope", markdown_code(report.summary["test_scope"])),
        ("Tests matched", report.summary["focused_tests"]),
        (
            "Tests runnable/unfinished",
            f"{report.summary['focused_tests_runnable']}/"
            f"{report.summary['focused_tests_unfinished']}",
        ),
        ("Tests with parsed annotations", report.summary["focused_tests_annotated"]),
        (
            "Source symbols referencing these tests",
            report.summary["focused_source_references"],
        ),
        (
            "Missing feature:dimension source tags",
            f"{report.summary['focused_source_tag_gaps']} "
            f"in {report.summary['focused_source_tag_gap_tests']} tests",
        ),
        (
            "Broad source owners among focused references",
            (
                f"{report.summary['focused_broad_source_owners']} "
                f"({format_breakdown(report.summary['focused_broad_source_owner_kinds'])})"
            ),
        ),
        ("Suggested source candidates", suggestions),
    ]
    for metric, value in rows:
        lines.append(f"| {markdown_escape(metric)} | {markdown_escape(value)} |")

    lines.extend(["", "## Focused Test Feature:Dimension Mappings", ""])
    if not report.focused_test_mappings:
        lines.append("_None._")
    for item in report.focused_test_mappings:
        test = item["test"]
        status = test_status(test)
        lines.append(f"- {markdown_code(test.location)} _{status}_")
        lines.append(f"  - {markdown_metadata_tags(test.metadata)}")
        for todo in test.metadata.todos:
            lines.append(f"  - todo: {markdown_escape(todo)}")
        pairs = item["pairs"]
        if not pairs:
            lines.append("  - feature:dimension pairs: _None._")
        for pair in pairs:
            lines.append(f"  - {markdown_code(pair['name'])}")
            lines.extend(
                markdown_focused_pair_sources(
                    pair["sources"], pair.get("template_sources")
                )
            )

    if report.focused_source_tag_gaps:
        lines.extend(
            ["", "## Annotated Tests Missing Feature:Dimension Source Tags", ""]
        )
        for item in report.focused_source_tag_gaps:
            test = item["test"]
            status = test_status(test)
            lines.append(f"- {markdown_code(test.location)} _{status}_")
            for pair in item["missing"]:
                lines.append(f"  - missing source tag: {markdown_code(pair)}")

    if report.broad_source_owners:
        lines.extend(["", "## Broad Source Owners", ""])
        for item in report.broad_source_owners:
            source = item["source"]
            lines.append(
                f"- {markdown_code(symbol_line(source))} "
                f"(kind={markdown_escape(item['owner_kind'])}, "
                f"tests={item['test_count']}, "
                f"features={item['feature_count']}, "
                f"dimensions={item['dimension_count']})"
            )

    if report.summary.get("focused_source_suggestions_enabled"):
        lines.extend([""])
        lines.extend(markdown_source_suggestions(report))

    return "\n".join(lines).rstrip()


def feature_dimension_report_to_markdown(report: Report) -> str:
    scope = report.summary["feature_dimension_scope"]
    link_tests_by_source = {
        item["source"].source_id: item["tests"]
        for item in report.feature_dimension_links
    }
    lines = [
        "# Traceability Feature:Dimension Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    rows = [
        ("Pair", markdown_code(scope)),
        ("Source symbols tagged", report.summary["feature_dimension_sources"]),
        ("Tests tagged", report.summary["feature_dimension_tests"]),
        (
            "Tests runnable/unfinished",
            f"{report.summary['feature_dimension_tests_runnable']}/"
            f"{report.summary['feature_dimension_tests_unfinished']}",
        ),
        ("Templates tagged", report.summary["feature_dimension_templates"]),
        (
            "Source/test reference links tagged with pair",
            report.summary["feature_dimension_source_test_links"],
        ),
    ]
    for metric, value in rows:
        lines.append(f"| {markdown_escape(metric)} | {markdown_escape(value)} |")

    lines.extend(
        [
            "",
            f"## Source Symbols Tagged {markdown_code(scope)}",
            "",
        ]
    )
    if not report.feature_dimension_sources:
        lines.append("_None._")
    for source in report.feature_dimension_sources:
        lines.append(f"- {markdown_code(symbol_line(source))}")
        if source.metadata.templates:
            lines.append(f"  - templates: {markdown_list(source.metadata.templates)}")
        linked_tests = link_tests_by_source.get(source.source_id, [])
        if linked_tests:
            lines.append("  - referenced tests tagged with pair:")
            for test in linked_tests:
                lines.append(
                    f"    - {markdown_code(test.nodeid)} _{test_status(test)}_"
                )

    lines.extend(["", f"## Tests Tagged {markdown_code(scope)}", ""])
    if not report.feature_dimension_tests:
        lines.append("_None._")
    for test in report.feature_dimension_tests:
        lines.append(f"- {markdown_code(test.location)} _{test_status(test)}_")
        if test.metadata.templates:
            lines.append(f"  - templates: {markdown_list(test.metadata.templates)}")
        for todo in test.metadata.todos:
            lines.append(f"  - todo: {markdown_escape(todo)}")

    lines.extend(["", f"## Templates Tagged {markdown_code(scope)}", ""])
    if not report.feature_dimension_templates:
        lines.append("_None._")
    for item in report.feature_dimension_templates:
        lines.append(f"- {markdown_code(item['template'])}")
        for source in item["sources"]:
            lines.append(f"  - source: {markdown_code(symbol_line(source))}")
        for test in item["tests"]:
            lines.append(
                f"  - test: {markdown_code(test.nodeid)} _{test_status(test)}_"
            )

    return "\n".join(lines).rstrip()


def markdown_source_explanations(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return []
    lines = ["## Source Traceability Map", ""]
    for item in items:
        source = item["source"]
        lines.append(
            f"- {markdown_code(symbol_line(source))} "
            f"_{markdown_escape(decision_label(item['decision']))}_"
        )
        if item["reason"]:
            lines.append(f"  - reason: {markdown_escape(item['reason'])}")
        for owner in item["covered_by"]:
            lines.append(f"  - owner: {markdown_code(owner)}")
        for test in item["tests"]:
            lines.append(
                f"  - required test: {markdown_code(test.nodeid)} _{test_status(test)}_"
            )
        for related in item["related_tests"]:
            test = related["test"]
            lines.append(
                f"  - related test: {markdown_code(test.nodeid)} "
                f"(pairs={markdown_list(related['pairs'])}) _{test_status(test)}_"
            )
        if item["features"]:
            lines.append(f"  - features: {markdown_list(item['features'])}")
        if item["dimensions"]:
            lines.append(f"  - dimensions: {markdown_list(item['dimensions'])}")
        if item["pairs"]:
            lines.append(f"  - exact pairs: {markdown_list(item['pairs'])}")
        for matrix in item["matrices"]:
            lines.append(
                f"  - matrix: {markdown_list(matrix.features)} : "
                f"{markdown_list(matrix.dimensions)}"
            )
        if item["realized_pairs"]:
            lines.append(
                f"  - realized pairs: {markdown_list(item['realized_pairs'])}"
            )
        if item["templates"]:
            lines.append(f"  - templates: {markdown_list(item['templates'])}")
    lines.append("")
    return lines


def markdown_traceability_diagnostics(report: Report) -> list[str]:
    text_sections = format_traceability_diagnostics(report)
    if not text_sections:
        return []
    lines = ["### Traceability Diagnostics", "", "```text"]
    lines.extend(line.lstrip("\n") for line in text_sections)
    lines.extend(["```", ""])
    return lines


def detailed_report_to_markdown(report: Report, *, verbose: bool = False) -> str:
    if report.summary.get("feature_dimension_scope"):
        return feature_dimension_report_to_markdown(report)
    if report.summary.get("test_scope"):
        return test_focus_report_to_markdown(report)

    source_scope = report.summary.get("source_scope", "configured source roots")
    orphan_value = (
        "skipped for source-file report"
        if report.summary.get("orphan_tests_suppressed")
        else str(report.summary["orphan_runnable_tests"])
    )
    summary_rows = [
        ("Source scope", markdown_code(source_scope)),
        ("Source symbols", report.summary["sources"]),
        ("Source symbols by kind", format_breakdown(report.summary["source_kinds"])),
        (
            "Source symbols by language",
            format_breakdown(report.summary["source_languages"]),
        ),
        (
            "Tests runnable/discovered",
            f"{report.summary['tests_runnable']}/{report.summary['tests_discovered']}",
        ),
        (
            "Latest test results",
            f"passed={report.summary['tests_passed']}, "
            f"failed={report.summary['tests_failed']}, "
            f"skipped={report.summary['tests_skipped']}, "
            f"not-run={report.summary['tests_not_run']} "
            f"(current={report.summary['test_results_current']})",
        ),
        (
            "Annotated source symbols",
            f"{report.summary['annotated_sources']} "
            f"(true={report.summary['testable_true']}, "
            f"false={report.summary['testable_false']}, "
            f"infrastructure={report.summary['testable_infrastructure']})",
        ),
        (
            "Sources matched to tests",
            f"{report.summary['sources_with_known_tests']} "
            f"(runnable={report.summary['sources_with_runnable_tests']})",
        ),
        (
            "Source/test reference links",
            f"total={report.summary['source_test_links']}, "
            f"collected={report.summary['source_test_links_known']}, "
            f"runnable={report.summary['source_test_links_runnable']}, "
            f"unfinished={report.summary['source_test_links_unfinished']}, "
            f"stale={report.summary['source_test_links_stale']}",
        ),
        (
            "Collected tests referenced",
            f"{report.summary['referenced_tests']} "
            f"(runnable={report.summary['referenced_runnable_tests']}, "
            f"unfinished={report.summary['referenced_unfinished_tests']})",
        ),
    ]
    optional_summary_rows = [
        (
            report.summary["source_source_links"],
            (
                "Source/source @covered-by links",
                f"total={report.summary['source_source_links']}, "
                f"resolved={report.summary['source_source_links_known']}, "
                f"stale={report.summary['source_source_links_stale']}",
            ),
        ),
        (
            report.summary["missing_testable"],
            ("Missing @testable metadata", report.summary["missing_testable"]),
        ),
        (
            report.summary["testable_without_tests"],
            ("Testable without tests", report.summary["testable_without_tests"]),
        ),
        (
            report.summary["unfinished_coverage"],
            ("Unfinished coverage", report.summary["unfinished_coverage"]),
        ),
        (
            report.summary["stale_test_references"],
            ("Stale test reference groups", report.summary["stale_test_references"]),
        ),
        (
            report.summary["invalid_false"],
            ("Invalid @testable false blocks", report.summary["invalid_false"]),
        ),
        (
            report.summary["manual_validation"],
            ("Manual validation required", report.summary["manual_validation"]),
        ),
        (
            report.summary["covered_by_missing"],
            ("Missing @covered-by sources", report.summary["covered_by_missing"]),
        ),
        (
            report.summary["feature_dimension_gaps"],
            ("Feature/dimension gaps", report.summary["feature_dimension_gaps"]),
        ),
        (
            report.summary["broad_source_owners"],
            ("Broad source owners", report.summary["broad_source_owners"]),
        ),
        (
            report.summary["test_todos"],
            (
                "Test TODOs",
                f"{report.summary['test_todos']} "
                f"in {report.summary['test_todo_groups']} tests "
                f"(runnable={report.summary['test_todos_runnable']}, "
                f"unfinished={report.summary['test_todos_unfinished']})",
            ),
        ),
    ]
    if report.summary["broad_source_owners"]:
        optional_summary_rows.append(
            (
                report.summary["broad_source_owners"],
                (
                    "Broad source owners by kind",
                    format_breakdown(report.summary["broad_source_owner_kinds"]),
                ),
            )
        )
    if (
        not report.summary.get("orphan_tests_suppressed")
        and report.summary["orphan_runnable_tests"]
    ):
        optional_summary_rows.append(
            (
                report.summary["orphan_runnable_tests"],
                ("Runnable tests not referenced", orphan_value),
            )
        )
    if report.summary.get("source_test_suggestions_enabled"):
        optional_summary_rows.append(
            (
                report.summary["source_test_suggestions"],
                (
                    "Suggested test candidates",
                    f"{report.summary['source_test_suggestions']} "
                    f"(likely={report.summary['source_test_suggestions_likely_existing']}, "
                    f"contextual={report.summary['source_test_suggestions_contextual']})",
                ),
            )
        )
    summary_rows.extend(row for count, row in optional_summary_rows if count)

    lines = [
        "# Traceability Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for metric, value in summary_rows:
        lines.append(f"| {markdown_escape(metric)} | {markdown_escape(value)} |")

    lines.extend([""])
    lines.extend(markdown_source_explanations(report.source_explanations))

    finding_lines: list[str] = []
    finding_lines.extend(markdown_traceability_diagnostics(report))
    finding_lines.extend(markdown_missing_metadata_section(report.missing_testable))
    finding_lines.extend(
        markdown_symbol_section(
            "@testable true without @tests/@scaffolding",
            report.testable_without_tests,
        )
    )
    finding_lines.extend(markdown_unfinished_coverage(report))
    finding_lines.extend(markdown_stale_test_references(report))
    finding_lines.extend(markdown_invalid_false(report))
    finding_lines.extend(
        markdown_symbol_section("Manual validation required", report.manual_validation)
    )
    finding_lines.extend(markdown_missing_covered_by(report))
    finding_lines.extend(markdown_feature_dimension_gaps(report))
    finding_lines.extend(markdown_broad_source_owners(report))
    finding_lines.extend(markdown_test_todos(report))
    finding_lines.extend(markdown_source_test_suggestions(report))
    finding_lines.extend(markdown_orphan_tests(report))
    if finding_lines:
        lines.extend(["", "## Findings", ""])
        lines.extend(finding_lines)
    return "\n".join(lines).rstrip()


def report_to_markdown(report: Report, *, verbose: bool = False) -> str:
    if (
        verbose
        or report.summary.get("feature_dimension_scope")
        or report.summary.get("test_scope")
    ):
        return detailed_report_to_markdown(report, verbose=verbose)

    findings = report_findings(report)
    actionable = [
        finding for finding in findings if finding["severity"] in {"error", "warning"}
    ]
    counts = Counter(finding["severity"] for finding in findings)
    lines = [
        "# Traceability Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Source scope | {markdown_escape(report.summary.get('source_scope', 'configured source roots'))} |",
        f"| Source decisions | {report.summary['annotated_sources']}/{report.summary['sources']} |",
        f"| Sources matched to tests | {report.summary['sources_with_known_tests']} |",
        f"| Tests runnable/discovered | {report.summary['tests_runnable']}/{report.summary['tests_discovered']} |",
        f"| Current test results | passed={report.summary['tests_passed']}, failed={report.summary['tests_failed']}, not-run={report.summary['tests_not_run']}, current={report.summary['test_results_current']} |",
        f"| Finding errors | {counts['error']} |",
        f"| Finding warnings | {counts['warning']} |",
        f"| Finding review | {counts['review']} |",
        "",
        "## Findings",
        "",
    ]
    if report.summary.get("changed_scope"):
        lines.insert(
            12,
            "| Affected template contracts | "
            f"{report.summary.get('template_contracts', 0)} "
            f"across {report.summary.get('template_contract_tests', 0)} tests "
            f"(errors={report.summary.get('template_contract_errors', 0)}, "
            f"warnings={report.summary.get('template_contract_warnings', 0)}, "
            f"review={report.summary.get('template_contract_reviews', 0)}) |",
        )
        if report.summary.get("style_traceability"):
            lines.insert(
                13,
                "| Affected style graph | "
                f"errors={report.summary.get('style_traceability_errors', 0)}, "
                f"warnings={report.summary.get('style_traceability_warnings', 0)}, "
                f"review={report.summary.get('style_traceability_reviews', 0)} |",
            )
    if actionable:
        shown, remaining = limited_items(actionable, TEXT_SECTION_LIMIT)
        lines.extend(
            f"- **{markdown_escape(finding['severity'].upper())}** "
            f"{markdown_code(finding['location'])}: "
            f"{markdown_escape(finding['message'])} "
            f"({markdown_code(finding['id'])})"
            for finding in shown
        )
        if remaining:
            lines.append(f"- _... {remaining} more; use `--verbose` for the full inventory_")
    else:
        lines.append("_No error/warning traceability findings._")
    return "\n".join(lines).rstrip()


def markdown_stale_test_references(report: Report) -> list[str]:
    if not report.stale_test_references:
        return []
    lines = [
        markdown_section_count(
            "Stale test references", len(report.stale_test_references)
        ),
        "",
    ]
    shown, remaining = limited(report.stale_test_references)
    for item in shown:
        lines.append(f"- {markdown_code(symbol_line(item['source']))}")
        for test in item["tests"]:
            lines.append(f"  - missing: {markdown_code(test)}")
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_invalid_false(report: Report) -> list[str]:
    if not report.invalid_false:
        return []
    lines = [
        markdown_section_count(
            "Invalid @testable false blocks", len(report.invalid_false)
        ),
        "",
    ]
    shown, remaining = limited(report.invalid_false)
    for item in shown:
        lines.append(
            f"- {markdown_code(symbol_line(item['source']))}: "
            f"{markdown_escape(item['message'])}"
        )
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_missing_covered_by(report: Report) -> list[str]:
    if not report.covered_by_missing:
        return []
    lines = [
        markdown_section_count(
            "Missing @covered-by sources", len(report.covered_by_missing)
        ),
        "",
    ]
    shown, remaining = limited(report.covered_by_missing)
    for item in shown:
        lines.append(f"- {markdown_code(symbol_line(item['source']))}")
        for source_id in item["covered_by"]:
            lines.append(f"  - missing: {markdown_code(source_id)}")
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_feature_dimension_gaps(report: Report) -> list[str]:
    if not report.feature_dimension_gaps:
        return []
    lines = [
        markdown_section_count(
            "Feature/dimension gaps", len(report.feature_dimension_gaps)
        ),
        "",
    ]
    shown, remaining = limited(report.feature_dimension_gaps)
    for item in shown:
        lines.append(f"- {markdown_code(symbol_line(item['source']))}")
        for gap in item["missing"]:
            lines.append(f"  - {markdown_feature_dimension_gap(gap)}")
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def markdown_orphan_tests(report: Report) -> list[str]:
    title = "Runnable tests not referenced by source"
    if report.summary.get("orphan_tests_suppressed"):
        return []
    if not report.orphan_runnable_tests:
        return []

    lines = [markdown_section_count(title, len(report.orphan_runnable_tests)), ""]
    shown, remaining = limited(report.orphan_runnable_tests)
    lines.extend(f"- {markdown_code(nodeid)}" for nodeid in shown)
    if remaining:
        lines.append(markdown_more_line(remaining))
    lines.append("")
    return lines


def default_markdown_report_path(report: Report) -> Path:
    feature_dimension_scope = report.summary.get("feature_dimension_scope")
    if feature_dimension_scope:
        return (
            DEFAULT_REPORT_DIR
            / (
                "traceability-feature-dimension-"
                f"{slugify(feature_dimension_scope, 'pair')}.md"
            )
        )

    test_scope = report.summary.get("test_scope")
    if test_scope:
        return DEFAULT_REPORT_DIR / f"traceability-test-{slugify(test_scope, 'test')}.md"

    source_scope = str(report.summary.get("source_scope", "configured source roots"))
    if source_scope == "configured source roots":
        return DEFAULT_REPORT_DIR / "traceability.md"

    source_paths = report.summary.get("source_paths")
    if isinstance(source_paths, list) and len(source_paths) > 1:
        first_path = source_paths[0]
        remaining = len(source_paths) - 1
        source_scope = f"{first_path} plus {remaining} more"

    return DEFAULT_REPORT_DIR / f"traceability-{slugify(source_scope, 'source')}.md"


def save_markdown_report(
    report: Report,
    repo_root: Path,
    report_path: Path | None = None,
    *,
    verbose: bool = False,
) -> Path:
    path = report_path or default_markdown_report_path(report)
    output_path = path if path.is_absolute() else repo_root / path
    write_markdown_report(output_path, report_to_markdown(report, verbose=verbose))
    return output_path


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return relpath(path, repo_root)
    except ValueError:
        return str(path)


def report_findings(report: Report) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(kind: str, severity: str, location: str, message: str) -> None:
        findings.append(
            {
                "id": stable_finding_id(kind, location, message),
                "kind": kind,
                "severity": severity,
                "location": location,
                "message": message,
            }
        )

    for symbol in report.missing_testable:
        add("missing-testable", "error", symbol_line(symbol), "missing @testable decision")
    for symbol in report.testable_without_tests:
        add(
            "testable-without-tests",
            "error",
            symbol_line(symbol),
            "@testable true has no @tests, @source, or @scaffolding evidence",
        )
    for item in report.stale_test_references:
        for test in item["tests"]:
            add("stale-test-reference", "error", symbol_line(item["source"]), str(test))
    for item in report.invalid_false:
        add(
            "invalid-testable-false",
            "error",
            symbol_line(item["source"]),
            str(item["message"]),
        )
    for item in report.covered_by_missing:
        for owner in item["covered_by"]:
            add("missing-covered-by", "error", symbol_line(item["source"]), str(owner))
    for item in report.feature_dimension_gaps:
        for gap in item["missing"]:
            add(
                "feature-dimension-gap",
                "error",
                symbol_line(item["source"]),
                format_feature_dimension_gap(gap),
            )
    for item in report.annotation_scope_issues:
        add(
            str(item["kind"]),
            str(item["severity"]),
            str(item.get("location") or item.get("path") or "repository"),
            str(item["message"]),
        )
    for item in report.source_link_issues:
        source = item.get("source")
        location = str(item.get("location") or "repository")
        if isinstance(source, SourceSymbol):
            location = symbol_line(source)
        add(str(item["kind"]), str(item["severity"]), location, str(item["message"]))
    for item in report.metadata_issues:
        add(
            str(item["kind"]),
            str(item["severity"]),
            str(item["location"]),
            str(item["message"]),
        )
    for finding in report.template_contract_findings:
        add(
            f"template-{finding['kind']}",
            finding["severity"],
            finding["location"],
            finding["message"],
        )
    for finding in report.style_traceability_findings:
        add(
            f"style-{finding['kind']}",
            finding["severity"],
            finding["location"],
            finding["message"],
        )
    for item in report.focused_source_tag_gaps:
        test = item["test"]
        for pair in item["missing"]:
            add(
                "test-pair-without-source-owner",
                "error",
                test.location,
                f"no source owner declares {pair}",
            )
    if report.summary.get("changed_scope"):
        required_tests: dict[str, TestCase] = {
            test.nodeid: test
            for item in report.source_explanations
            for test in item["tests"]
        }
        required_tests.update({test.nodeid: test for test in report.changed_tests})
        required_tests.update(
            {test.nodeid: test for test in report.template_contract_tests}
        )
        for test in required_tests.values():
            if not test.execution_current:
                add(
                    "referenced-test-not-run",
                    "error",
                    test.location,
                    "test has no result for its current declared code dependencies",
                )
            elif test.execution != "passed":
                add(
                    "referenced-test-not-passed",
                    "error",
                    test.location,
                    f"latest current result is {test.execution}",
                )
    for item in report.broad_source_owners:
        add(
            "broad-source-owner",
            "review",
            symbol_line(item["source"]),
            f"owns {item['test_count']} tests and {item['dimension_count']} dimensions",
        )
    for group in report.taxonomy.get("feature_alias_candidates", []):
        add("feature-alias", "review", "taxonomy", ", ".join(group))
    for group in report.taxonomy.get("dimension_alias_candidates", []):
        add("dimension-alias", "review", "taxonomy", ", ".join(group))
    for item in report.taxonomy.get("large_cross_products", []):
        add(
            "large-tag-cross-product",
            "review",
            symbol_line(item["source"]),
            f"{item['pairs']} implied feature:dimension pairs",
        )
    return findings


def baseline_finding_ids(path: Path | None, repo_root: Path) -> set[str]:
    if path is None:
        return set()
    resolved = path if path.is_absolute() else repo_root / path
    payload = load_json(resolved)
    if not payload:
        raise ValueError(f"baseline report not found or invalid: {path}")
    ids = payload.get("finding_ids")
    if isinstance(ids, list):
        return {str(value) for value in ids}
    findings = payload.get("findings")
    if isinstance(findings, list):
        return {
            str(item["id"])
            for item in findings
            if isinstance(item, dict) and "id" in item
        }
    raise ValueError(f"baseline contains no finding IDs: {path}")


def actionable_findings(
    report: Report, *, fail_on: str = "error", baseline_ids: set[str] | None = None
) -> list[dict[str, str]]:
    baseline_ids = baseline_ids or set()
    severities = {"error"} if fail_on == "error" else {"error", "warning"}
    return [
        finding
        for finding in report_findings(report)
        if finding["severity"] in severities and finding["id"] not in baseline_ids
    ]


def json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: json_ready(item)
            for key, item in value.items()
            if key != "raw" and not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def report_payload(report: Report) -> dict[str, object]:
    body = asdict(report)
    body.pop("provenance", None)
    findings = report_findings(report)
    return structured_report_payload(
        kind="traceability-report",
        report=json_ready(body),
        report_provenance=report.provenance,
        findings=findings,
    )


def report_to_json(report: Report) -> str:
    return json.dumps(report_payload(report), indent=2, sort_keys=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_file())
    parser.add_argument(
        "--styles",
        action="store_true",
        help="Inventory semantic styles, their consumers, and authored CSS selectors.",
    )
    parser.add_argument(
        "--style",
        metavar="STYLE_ID",
        help="Query one semantic style ID or family.",
    )
    parser.add_argument(
        "--style-source",
        metavar="PATH",
        help="Query styles and selectors owned by one authored style source.",
    )
    parser.add_argument(
        "--style-consumer",
        metavar="PATH",
        help="Query semantic styles consumed by one template or frontend module.",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=Path("reports/style-manifest.json"),
        help="With --styles, write the machine-readable style manifest here.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="With --styles, do not write the default style manifest.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        nargs="+",
        metavar="PATH",
        help=(
            "Inventory one or more source files or directories instead of the "
            "configured source roots. Can be repeated."
        ),
    )
    parser.add_argument(
        "--changed",
        nargs="?",
        const="HEAD",
        metavar="BASE",
        help=(
            "Trace source and tests changed from BASE, including staged and "
            "untracked files. Defaults to HEAD."
        ),
    )
    parser.add_argument(
        "--test",
        help=(
            "Report backward from one pytest nodeid, test_file.py::test_name, "
            "test file, or test folder."
        ),
    )
    parser.add_argument(
        "--feature-dimension",
        "--pair",
        dest="feature_dimension",
        metavar="FEATURE:DIMENSION",
        help=(
            "Report source symbols, tests, and @template tags declaring one "
            "feature:dimension pair."
        ),
    )
    parser.add_argument(
        "--suggest-sources",
        action="store_true",
        help=(
            "With --test, suggest related source symbols; with --source, "
            "suggest candidate tests for source symbols that need a decision."
        ),
    )
    parser.add_argument(
        "--verify-collection",
        action="store_true",
        help=(
            "Verify static test discovery with pytest collection. This can import "
            "application modules and is intentionally opt-in."
        ),
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=LATEST_TEST_RUN,
        help=f"Test-result manifest to correlate. Defaults to {LATEST_TEST_RUN}.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return a non-zero status when actionable findings remain.",
    )
    parser.add_argument(
        "--fail-on",
        choices=["error", "warning"],
        default="error",
        help="With --check, fail on errors only or on errors and warnings.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Ignore finding IDs recorded in an earlier traceability JSON report.",
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help="Write the current structured findings as a baseline JSON file.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Markdown report path. Defaults to reports/traceability*.md.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write the default Markdown report file.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed unfinished coverage and TODO entries.",
    )
    return parser.parse_args(argv)


def parsed_source_paths(args: argparse.Namespace) -> list[Path]:
    return [path for group in args.source or [] for path in group]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    style_modes = [args.style, args.style_source, args.style_consumer]
    if args.styles or any(style_modes):
        if sum(value is not None for value in style_modes) > 1:
            print(
                "traceability: use only one of --style, --style-source, or "
                "--style-consumer",
                file=sys.stderr,
            )
            return 2
        incompatible = [
            name
            for name, enabled in (
                ("--source", bool(args.source)),
                ("--test", bool(args.test)),
                ("--feature-dimension", bool(args.feature_dimension)),
                ("--suggest-sources", args.suggest_sources),
                ("--verify-collection", args.verify_collection),
            )
            if enabled
        ]
        if incompatible:
            print(
                "traceability: --styles cannot yet be combined with "
                + ", ".join(incompatible),
                file=sys.stderr,
            )
            return 2
        from testing.utility import style_traceability

        return style_traceability.run_from_traceability(args, argv)
    try:
        changed = (
            git_changed_paths(args.repo_root.resolve(), args.changed)
            if args.changed is not None
            else None
        )
        changed_lines = (
            git_changed_line_ranges(
                args.repo_root.resolve(), changed, args.changed
            )
            if changed is not None
            else None
        )
        report = build_report(
            args.repo_root.resolve(),
            args.config,
            test_target=args.test,
            feature_dimension=args.feature_dimension,
            suggest_sources=args.suggest_sources,
            source_paths=parsed_source_paths(args),
            verify_collection=args.verify_collection,
            results_path=args.results,
            changed_paths=changed,
            changed_line_ranges=changed_lines,
        )
        report.provenance = provenance(
            args.repo_root.resolve(), command=["traceability", *(argv or sys.argv[1:])]
        )
        baseline_ids = baseline_finding_ids(args.baseline, args.repo_root.resolve())
    except Exception as exc:
        print(f"traceability: {exc}", file=sys.stderr)
        return 2

    if args.write_baseline:
        baseline_path = (
            args.write_baseline
            if args.write_baseline.is_absolute()
            else args.repo_root.resolve() / args.write_baseline
        )
        payload = report_payload(report)
        payload["kind"] = "traceability-baseline"
        write_json(baseline_path, payload)

    if args.json:
        print(report_to_json(report))
    else:
        saved_path = None
        if not args.no_report:
            saved_path = save_markdown_report(
                report,
                args.repo_root.resolve(),
                args.report_path,
                verbose=args.verbose,
            )
        print(format_report(report, verbose=args.verbose))
        if saved_path:
            print(
                "\nMarkdown report saved: "
                f"{display_path(saved_path, args.repo_root.resolve())}"
            )
    if args.check:
        findings = actionable_findings(
            report, fail_on=args.fail_on, baseline_ids=baseline_ids
        )
        if findings:
            print(
                f"\nTraceability check failed: {len(findings)} new "
                f"{args.fail_on}-level finding(s).",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
