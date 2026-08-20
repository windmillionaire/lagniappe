#!/usr/bin/env python3
"""Style ownership manifest and advisory traceability report."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

import yaml
from yaml.nodes import MappingNode, ScalarNode

from testing.utility import icon_traceability, style_candidates, style_registry
from testing.utility.artifacts import write_markdown_report
from testing.utility.traceability_common import (
    git_changed_paths,
    load_json,
    provenance,
    stable_finding_id,
    structured_report_payload,
    write_json,
)


STYLE_MANIFEST_SCHEMA_VERSION = 3
DEFAULT_MANIFEST_PATH = Path("reports/style-manifest.json")
DEFAULT_REPORT_PATH = Path("reports/style-traceability.md")
PIPELINE_INPUT_PATHS = (
    Path("build/rollup.config.mjs"),
    Path("build/rollup.dev.config.mjs"),
    Path("build/utility.mjs"),
    Path("testing/utility/style_compile.mjs"),
    Path("package.json"),
    Path("package-lock.json"),
)
SELECTOR_INVENTORY_EXCLUSIONS: set[str] = set()
CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\()?\s*(['\"])(?P<path>[^'\"]+)\1")
CSS_SOURCE_RE = re.compile(r"@source\s+(['\"])(?P<path>[^'\"]+)\1")
CSS_ENTRY_IMPORT_RE = re.compile(r"\bimport\s+(['\"])(?P<path>[^'\"]+\.css)\1")
CSS_STYLE_OWNER_RE = re.compile(r"@style\s+(?P<ids>[A-Za-z0-9_.\s]+)")
CSS_OWNERSHIP_KINDS = {
    "pipeline",
    "structural",
    "semantic",
    "theme",
    "editor",
    "asset",
    "vendor",
}


@dataclass(frozen=True)
class StyleInput:
    path: str
    role: str
    fingerprint: str


@dataclass(frozen=True)
class StyleConsumer:
    path: str
    line: int
    surface: str
    context: str
    reference: str
    resolution: str


@dataclass(frozen=True)
class StyleEvidence:
    nodeid: str
    kind: str
    source: str
    test_path: str
    outcome: str
    current: bool


@dataclass(frozen=True)
class StyleEntry:
    id: str
    classes: str
    tokens: list[str]
    source: dict[str, object]
    alias: str
    canonical: str
    intent: str
    declared_surfaces: list[str]
    markers: list[str]
    hooks: list[str]
    css: list[str]
    exceptions: list[dict[str, str]]
    observed_surfaces: list[str]
    consumers: list[StyleConsumer]
    fingerprint: str = ""
    evidence: list[StyleEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class RawClassUse:
    classes: str
    tokens: list[str]
    style_refs: list[str]
    path: str
    line: int
    surface: str
    context: str


@dataclass(frozen=True)
class CssSelector:
    selector: str
    path: str
    line: int
    at_rules: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    ownership: str = "structural"
    fingerprint: str = ""


@dataclass(frozen=True)
class CssStylesheet:
    path: str
    ownership: str


@dataclass(frozen=True)
class CssImport:
    source: str
    target: str
    line: int
    order: int
    external: bool


@dataclass
class StylePipeline:
    configured: bool
    contract_path: str
    frontend_entry: str
    registry: str
    registry_schema: str
    icons: str
    icons_schema: str
    virtual_module: str
    python_output: str
    python_icons_output: str
    icon_count: int
    used_icon_count: int
    css_entry: str
    css_output: str
    tailwind_sources: list[str]
    candidate_validator: str
    compiled_candidate_count: int
    invalid_candidates: list[str]
    authored_stylesheets: list[CssStylesheet]
    css_imports: list[CssImport]
    reachable_stylesheets: list[str]
    unreachable_stylesheets: list[str]
    duplicate_stylesheets: list[str]
    transforms: dict[str, list[str]]
    python_registry_parity: bool | None
    python_icons_parity: bool | None
    issues: list[dict[str, str]]


@dataclass
class StyleManifest:
    summary: dict[str, object]
    inputs: list[StyleInput]
    styles: dict[str, StyleEntry]
    families: dict[str, list[str]]
    raw_class_uses: list[RawClassUse]
    css_selectors: list[CssSelector]
    pipeline: StylePipeline
    issues: list[dict[str, str]]
    provenance: dict[str, object] = field(default_factory=dict)


@dataclass
class Report:
    summary: dict[str, object]
    manifest_fingerprint: str
    audit: style_candidates.Report
    pipeline: StylePipeline
    registry_issues: list[dict[str, str]]
    query: dict[str, object] = field(default_factory=dict)
    provenance: dict[str, object] = field(default_factory=dict)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _surface_name(surface: str) -> str:
    return {"template": "server", "javascript": "frontend"}.get(
        surface, surface
    )


def _definition_lines(styles_path: Path) -> dict[str, int]:
    root = yaml.compose(styles_path.read_text(encoding="utf-8"))
    lines: dict[str, int] = {}

    def walk(node: object, prefix: str = "") -> None:
        if not isinstance(node, MappingNode):
            return
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            name = f"{prefix}.{key_node.value}" if prefix else key_node.value
            if isinstance(value_node, MappingNode):
                field_names = {
                    child_key.value
                    for child_key, _child_value in value_node.value
                    if isinstance(child_key, ScalarNode)
                }
                if {"classes", "alias"} & field_names:
                    lines[name] = key_node.start_mark.line + 1
                else:
                    walk(value_node, name)
            else:
                lines[name] = key_node.start_mark.line + 1

    if root is not None:
        walk(root)
    return lines


def _input_role(relative: str) -> str:
    if relative == style_candidates.DEFAULT_STYLES_PATH.as_posix():
        return "semantic-registry"
    if relative == style_registry.DEFAULT_ICONS_PATH.as_posix():
        return "icon-registry"
    if relative == style_registry.DEFAULT_ICONS_SCHEMA_PATH.as_posix():
        return "icon-registry-schema"
    if relative == style_registry.DEFAULT_SCHEMA_PATH.as_posix():
        return "semantic-registry-schema"
    if relative == "src/style/pipeline.json":
        return "style-pipeline"
    if relative.startswith("src/style/") and relative.endswith(".css"):
        return "stylesheet"
    if relative.startswith("build/"):
        return "build-pipeline"
    if relative == "testing/utility/style_compile.mjs":
        return "style-build-validator"
    if relative in {"package.json", "package-lock.json"}:
        return "build-dependencies"
    return "consumer-source"


def _manifest_inputs(
    repo_root: Path,
    styles_path: Path,
    source_roots: Iterable[Path],
) -> list[StyleInput]:
    paths = {
        path.resolve()
        for path, _surface in style_candidates.iter_source_files(repo_root, source_roots)
    }
    resolved_styles = (
        styles_path.resolve()
        if styles_path.is_absolute()
        else (repo_root / styles_path).resolve()
    )
    paths.add(resolved_styles)
    style_root = repo_root / "src/style"
    if style_root.exists():
        paths.update(path.resolve() for path in style_root.iterdir() if path.is_file())
    paths.update(
        (repo_root / relative).resolve()
        for relative in PIPELINE_INPUT_PATHS
        if (repo_root / relative).is_file()
    )

    inputs = []
    for path in sorted(paths):
        try:
            relative = _relative(path, repo_root)
        except ValueError:
            relative = str(path)
        inputs.append(
            StyleInput(
                path=relative,
                role=_input_role(relative),
                fingerprint=_sha256(path),
            )
        )
    return inputs


def _without_css_comments(text: str) -> str:
    return re.sub(
        r"/\*.*?\*/",
        lambda match: re.sub(r"[^\n]", " ", match.group(0)),
        text,
        flags=re.DOTALL,
    )


def _split_selectors(prelude: str) -> list[str]:
    selectors: list[str] = []
    start = 0
    round_depth = 0
    square_depth = 0
    quote = ""
    escaped = False
    for index, char in enumerate(prelude):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "(":
            round_depth += 1
        elif char == ")":
            round_depth = max(0, round_depth - 1)
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        elif char == "," and not round_depth and not square_depth:
            selectors.append(prelude[start:index])
            start = index + 1
    selectors.append(prelude[start:])
    return [" ".join(selector.split()) for selector in selectors if selector.strip()]


def inventory_css_selectors(
    path: Path,
    repo_root: Path,
    *,
    ownership: str = "structural",
) -> list[CssSelector]:
    """Inventory authored selectors and source-local semantic owners."""
    text = path.read_text(encoding="utf-8")
    relative = _relative(path, repo_root)
    selectors: list[CssSelector] = []
    stack: list[dict[str, object]] = []
    segment_start = 0
    quote = ""
    escaped = False

    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "{":
            raw_prelude = text[segment_start:index]
            clean_prelude = _without_css_comments(raw_prelude)
            prelude = " ".join(clean_prelude.split())
            owner_matches = list(CSS_STYLE_OWNER_RE.finditer(raw_prelude))
            owners = []
            for match in owner_matches:
                owners.extend(match.group("ids").split())
            if not owners and stack:
                owners = list(stack[-1]["owners"])
            keyframe_context = any(
                str(value["prelude"]).startswith(
                    ("@keyframes ", "@-webkit-keyframes ")
                )
                for value in stack
            )
            is_rule = bool(
                prelude and not prelude.startswith("@") and not keyframe_context
            )
            offset = len(clean_prelude) - len(clean_prelude.lstrip())
            stack.append(
                {
                    "prelude": prelude,
                    "owners": sorted(set(owners)),
                    "is_rule": is_rule,
                    "line": text.count("\n", 0, segment_start + offset) + 1,
                    "start": segment_start,
                    "at_rules": [
                        str(value["prelude"])
                        for value in stack
                        if str(value["prelude"]).startswith("@")
                    ],
                }
            )
            segment_start = index + 1
        elif char == ";":
            segment_start = index + 1
        elif char == "}":
            if stack:
                entry = stack.pop()
                if entry["is_rule"]:
                    rule_text = text[int(entry["start"]): index + 1]
                    fingerprint = hashlib.sha256(rule_text.encode()).hexdigest()
                    selectors.extend(
                        CssSelector(
                            selector=selector,
                            path=relative,
                            line=int(entry["line"]),
                            at_rules=list(entry["at_rules"]),
                            owners=list(entry["owners"]),
                            ownership="semantic" if entry["owners"] else ownership,
                            fingerprint=fingerprint,
                        )
                        for selector in _split_selectors(str(entry["prelude"]))
                    )
            segment_start = index + 1
    return selectors


def _selector_inventory(
    repo_root: Path,
    authored_stylesheets: list[CssStylesheet],
) -> list[CssSelector]:
    selectors: list[CssSelector] = []
    ownership_by_path = {
        stylesheet.path: stylesheet.ownership
        for stylesheet in authored_stylesheets
    }
    style_root = repo_root / "src/style"
    if not style_root.exists():
        return selectors
    for path in sorted(style_root.glob("*.css")):
        relative = _relative(path, repo_root)
        if relative not in SELECTOR_INVENTORY_EXCLUSIONS:
            selectors.extend(
                inventory_css_selectors(
                    path,
                    repo_root,
                    ownership=ownership_by_path.get(relative, "structural"),
                )
            )
    return sorted(selectors, key=lambda item: (item.path, item.line, item.selector))


def _resolve_css_path(source: Path, value: str) -> Path | None:
    if not value.startswith("."):
        return None
    return (source.parent / value).resolve()


def _css_import_graph(
    repo_root: Path, css_entry: str
) -> tuple[list[CssImport], list[str], list[str], list[str], list[dict[str, str]]]:
    entry = repo_root / css_entry
    if not entry.is_file():
        return [], [], [], [], [
            {
                "kind": "missing-css-entry",
                "severity": "error",
                "location": css_entry,
                "message": "declared CSS entry does not exist",
            }
        ]

    imports: list[CssImport] = []
    reachable: set[str] = set()
    visiting: list[str] = []
    issues: list[dict[str, str]] = []

    def walk(path: Path) -> None:
        relative = _relative(path, repo_root)
        if relative in visiting:
            cycle = " -> ".join([*visiting, relative])
            issues.append(
                {
                    "kind": "css-import-cycle",
                    "severity": "error",
                    "location": relative,
                    "message": f"CSS import cycle: {cycle}",
                }
            )
            return
        if relative in reachable:
            return
        reachable.add(relative)
        visiting.append(relative)
        text = path.read_text(encoding="utf-8")
        for order, match in enumerate(CSS_IMPORT_RE.finditer(text), start=1):
            value = match.group("path")
            target_path = _resolve_css_path(path, value)
            external = target_path is None
            target = value
            if target_path is not None:
                try:
                    target = _relative(target_path, repo_root)
                except ValueError:
                    target = str(target_path)
            imports.append(
                CssImport(
                    source=relative,
                    target=target,
                    line=text.count("\n", 0, match.start()) + 1,
                    order=order,
                    external=external,
                )
            )
            if target_path is not None:
                if not target_path.is_file():
                    issues.append(
                        {
                            "kind": "missing-css-import",
                            "severity": "error",
                            "location": f"{relative}:{text.count(chr(10), 0, match.start()) + 1}",
                            "message": f"CSS import target does not exist: {target}",
                        }
                    )
                else:
                    walk(target_path)
        visiting.pop()

    walk(entry)
    target_counts: dict[str, int] = defaultdict(int)
    for item in imports:
        if not item.external:
            target_counts[item.target] += 1
    duplicate = sorted(path for path, count in target_counts.items() if count > 1)
    authored = {
        _relative(path, repo_root)
        for path in (repo_root / "src/style").glob("*.css")
        if path.is_file()
    }
    unreachable = sorted(authored - reachable)
    return imports, sorted(reachable), unreachable, duplicate, issues


def _load_generated_registry(path: Path, constant: str) -> object:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id == constant:
            return ast.literal_eval(statement.value)
    raise ValueError(f"{path} does not assign {constant}")


def _pipeline_inventory(
    repo_root: Path,
    styles_path: Path,
) -> StylePipeline:
    contract_path = repo_root / "src/style/pipeline.json"
    if not contract_path.is_file():
        return StylePipeline(
            configured=False,
            contract_path="src/style/pipeline.json",
            frontend_entry="",
            registry=styles_path.as_posix(),
            registry_schema="",
            icons="",
            icons_schema="",
            virtual_module="",
            python_output="",
            python_icons_output="",
            icon_count=0,
            used_icon_count=0,
            css_entry="",
            css_output="",
            tailwind_sources=[],
            candidate_validator="",
            compiled_candidate_count=0,
            invalid_candidates=[],
            authored_stylesheets=[],
            css_imports=[],
            reachable_stylesheets=[],
            unreachable_stylesheets=[],
            duplicate_stylesheets=[],
            transforms={},
            python_registry_parity=None,
            python_icons_parity=None,
            issues=[],
        )

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    registry = contract.get("registry", {})
    css = contract.get("css", {})
    frontend_entry = str(contract.get("frontend_entry", ""))
    registry_path = str(registry.get("styles", ""))
    registry_schema = str(registry.get("schema", ""))
    icons_path = str(registry.get("icons", ""))
    icons_schema = str(registry.get("icons_schema", ""))
    python_output = str(registry.get("python_styles", ""))
    python_icons_output = str(registry.get("python_icons", ""))
    css_entry = str(css.get("entry", ""))
    candidate_validator = str(css.get("candidate_validator", ""))
    issues: list[dict[str, str]] = []
    if contract.get("schema_version") != 3:
        issues.append(
            {
                "kind": "unsupported-style-pipeline-schema",
                "severity": "error",
                "location": "src/style/pipeline.json",
                "message": "style pipeline schema_version must be 3",
            }
        )
    imports, reachable, unreachable, duplicate, import_issues = _css_import_graph(
        repo_root, css_entry
    )
    issues.extend(import_issues)

    if registry_path != _relative(
        styles_path if styles_path.is_absolute() else repo_root / styles_path,
        repo_root,
    ):
        issues.append(
            {
                "kind": "style-registry-contract-drift",
                "severity": "error",
                "location": "src/style/pipeline.json",
                "message": f"contract names {registry_path}, reporter loaded {styles_path}",
            }
        )

    expected_schema = style_registry.DEFAULT_SCHEMA_PATH.as_posix()
    if registry_schema != expected_schema:
        issues.append(
            {
                "kind": "style-registry-schema-contract-drift",
                "severity": "error",
                "location": "src/style/pipeline.json",
                "message": f"contract must name shared schema {expected_schema}",
            }
        )
    elif not (repo_root / registry_schema).is_file():
        issues.append(
            {
                "kind": "missing-style-registry-schema",
                "severity": "error",
                "location": registry_schema,
                "message": "declared style registry schema does not exist",
            }
        )

    expected_icons = style_registry.DEFAULT_ICONS_PATH.as_posix()
    expected_icons_schema = style_registry.DEFAULT_ICONS_SCHEMA_PATH.as_posix()
    if icons_path != expected_icons:
        issues.append(
            {
                "kind": "icon-registry-contract-drift",
                "severity": "error",
                "location": "src/style/pipeline.json",
                "message": f"contract must name shared icon registry {expected_icons}",
            }
        )
    elif not (repo_root / icons_path).is_file():
        issues.append(
            {
                "kind": "missing-icon-registry",
                "severity": "error",
                "location": icons_path,
                "message": "declared icon registry does not exist",
            }
        )
    if icons_schema != expected_icons_schema:
        issues.append(
            {
                "kind": "icon-registry-schema-contract-drift",
                "severity": "error",
                "location": "src/style/pipeline.json",
                "message": f"contract must name shared icon schema {expected_icons_schema}",
            }
        )
    elif not (repo_root / icons_schema).is_file():
        issues.append(
            {
                "kind": "missing-icon-registry-schema",
                "severity": "error",
                "location": icons_schema,
                "message": "declared icon registry schema does not exist",
            }
        )

    frontend_path = repo_root / frontend_entry
    if not frontend_path.is_file():
        issues.append(
            {
                "kind": "missing-style-frontend-entry",
                "severity": "error",
                "location": frontend_entry,
                "message": "declared frontend entry does not exist",
            }
        )
    else:
        frontend_css = {
            _relative((frontend_path.parent / match.group("path")).resolve(), repo_root)
            for match in CSS_ENTRY_IMPORT_RE.finditer(
                frontend_path.read_text(encoding="utf-8")
            )
        }
        if css_entry not in frontend_css:
            issues.append(
                {
                    "kind": "unreachable-css-entry",
                    "severity": "error",
                    "location": frontend_entry,
                    "message": f"frontend entry does not import {css_entry}",
                }
            )

    declared_sources = [str(value) for value in css.get("tailwind_sources", [])]
    authored_stylesheets: list[CssStylesheet] = []
    authored_paths: set[str] = set()
    raw_authored = css.get("authored_stylesheets", [])
    if not isinstance(raw_authored, list):
        raw_authored = []
        issues.append(
            {
                "kind": "invalid-authored-stylesheet-contract",
                "severity": "error",
                "location": "src/style/pipeline.json",
                "message": "css.authored_stylesheets must be a list",
            }
        )
    for row in raw_authored:
        if not isinstance(row, dict) or set(row) != {"path", "ownership"}:
            issues.append(
                {
                    "kind": "invalid-authored-stylesheet-contract",
                    "severity": "error",
                    "location": "src/style/pipeline.json",
                    "message": "authored stylesheet rows need path and ownership",
                }
            )
            continue
        path = str(row["path"])
        ownership = str(row["ownership"])
        if ownership not in CSS_OWNERSHIP_KINDS:
            issues.append(
                {
                    "kind": "invalid-stylesheet-ownership",
                    "severity": "error",
                    "location": "src/style/pipeline.json",
                    "message": f"{path} has unknown ownership kind {ownership}",
                }
            )
            continue
        if path in authored_paths:
            issues.append(
                {
                    "kind": "duplicate-authored-stylesheet-contract",
                    "severity": "error",
                    "location": "src/style/pipeline.json",
                    "message": f"{path} is classified more than once",
                }
            )
            continue
        authored_paths.add(path)
        authored_stylesheets.append(CssStylesheet(path, ownership))
        if not (repo_root / path).is_file():
            issues.append(
                {
                    "kind": "missing-authored-stylesheet",
                    "severity": "error",
                    "location": path,
                    "message": "classified stylesheet does not exist",
                }
            )
    discovered_stylesheets = {
        _relative(path, repo_root)
        for path in (repo_root / "src/style").glob("*.css")
        if path.is_file()
    }
    for path in sorted(discovered_stylesheets - authored_paths):
        issues.append(
            {
                "kind": "unclassified-authored-stylesheet",
                "severity": "error",
                "location": path,
                "message": "authored stylesheet has no ownership classification",
            }
        )
    css_entry_path = repo_root / css_entry
    observed_sources: set[str] = set()
    if css_entry_path.is_file():
        for match in CSS_SOURCE_RE.finditer(
            css_entry_path.read_text(encoding="utf-8")
        ):
            resolved = _resolve_css_path(css_entry_path, match.group("path"))
            if resolved is not None:
                observed_sources.add(_relative(resolved, repo_root))
    for source in declared_sources:
        if source not in observed_sources:
            issues.append(
                {
                    "kind": "missing-tailwind-source",
                    "severity": "error",
                    "location": css_entry,
                    "message": f"Tailwind does not explicitly scan {source}",
                }
            )

    for path in unreachable:
        issues.append(
            {
                "kind": "unreachable-stylesheet",
                "severity": "warning",
                "location": path,
                "message": f"authored stylesheet is not reachable from {css_entry}",
            }
        )
    for path in duplicate:
        issues.append(
            {
                "kind": "multiply-imported-stylesheet",
                "severity": "warning",
                "location": path,
                "message": "stylesheet is reachable through more than one import edge",
            }
        )

    transforms: dict[str, list[str]] = {}
    dependency_names = {
        "tailwindcss": "@tailwindcss/postcss",
        "cssnano": "cssnano",
    }
    package_path = repo_root / "package.json"
    dependencies: dict[str, object] = {}
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        dependencies = {
            **package.get("dependencies", {}),
            **package.get("devDependencies", {}),
        }
    for build_name, build in contract.get("builds", {}).items():
        build_transforms = [str(value) for value in build.get("transforms", [])]
        transforms[str(build_name)] = build_transforms
        config = str(build.get("config", ""))
        config_path = repo_root / config
        config_text = (
            config_path.read_text(encoding="utf-8")
            if config_path.is_file()
            else ""
        )
        for transform in build_transforms:
            dependency = dependency_names.get(transform)
            if dependency and dependency not in dependencies:
                issues.append(
                    {
                        "kind": "missing-style-build-dependency",
                        "severity": "error",
                        "location": "package.json",
                        "message": f"{build_name} declares {transform} without {dependency}",
                    }
                )
            if not re.search(rf"\b{re.escape(transform)}\s*\(", config_text):
                issues.append(
                    {
                        "kind": "missing-style-transform",
                        "severity": "error",
                        "location": config,
                        "message": f"declared transform {transform} is not configured",
                    }
                )

    parity: bool | None = None
    generated_path = repo_root / python_output
    source_registry = repo_root / registry_path
    if generated_path.is_file() and source_registry.is_file():
        try:
            generated = _load_generated_registry(generated_path, "STYLES")
            authored = style_candidates.normalize_style_registry(
                yaml.safe_load(source_registry.read_text(encoding="utf-8")) or {},
                schema=style_registry.load_registry_schema(
                    repo_root, Path(registry_schema)
                ),
            )
            parity = generated == authored
        except (OSError, SyntaxError, TypeError, ValueError) as exc:
            parity = False
            issues.append(
                {
                    "kind": "invalid-generated-style-registry",
                    "severity": "error",
                    "location": python_output,
                    "message": str(exc),
                }
            )
        if parity is False and not any(
            item["kind"] == "invalid-generated-style-registry" for item in issues
        ):
            issues.append(
                {
                    "kind": "generated-style-registry-drift",
                    "severity": "error",
                    "location": python_output,
                    "message": f"generated STYLES differs from {registry_path}",
                }
            )
    else:
        issues.append(
            {
                "kind": "missing-generated-style-registry",
                "severity": "error",
                "location": python_output,
                "message": "generated Python style registry is missing",
            }
        )

    icon_count = 0
    used_icon_count = 0
    normalized_icons: dict[str, object] | None = None
    icon_definitions: dict[str, object] | None = None
    source_icons = repo_root / icons_path
    if source_icons.is_file() and (repo_root / icons_schema).is_file():
        try:
            raw_icons = (
                yaml.safe_load(source_icons.read_text(encoding="utf-8")) or {}
            )
            icon_contract = style_registry.load_icons_schema(
                repo_root, Path(icons_schema)
            )
            icon_definitions = style_registry.flatten_icon_definitions(
                raw_icons, schema=icon_contract
            )
            icon_count = len(icon_definitions)
            normalized_icons = style_registry.normalize_icon_registry(
                raw_icons, schema=icon_contract
            )
        except (OSError, TypeError, ValueError) as exc:
            issues.append(
                {
                    "kind": "invalid-icon-registry",
                    "severity": "error",
                    "location": icons_path,
                    "message": str(exc),
                }
            )

    if icon_definitions is not None:
        icon_report = icon_traceability.build_report(
            repo_root, definitions=icon_definitions
        )
        used_icon_count = len(icon_report.used)
        for reference in icon_report.unknown:
            issues.append(
                {
                    "kind": "unknown-icon-reference",
                    "severity": "error",
                    "location": f"{reference.path}:{reference.line}",
                    "message": f"unknown icon ID {reference.icon_id}",
                }
            )
        for icon_id in icon_report.unused:
            issues.append(
                {
                    "kind": "unused-icon-definition",
                    "severity": "warning",
                    "location": icons_path,
                    "message": f"{icon_id} has no observed consumer",
                }
            )

    icons_parity: bool | None = None
    generated_icons_path = repo_root / python_icons_output
    if normalized_icons is None:
        icons_parity = False
    elif generated_icons_path.is_file():
        try:
            generated_icons = _load_generated_registry(
                generated_icons_path, "ICONS"
            )
            icons_parity = generated_icons == normalized_icons
        except (OSError, SyntaxError, TypeError, ValueError) as exc:
            icons_parity = False
            issues.append(
                {
                    "kind": "invalid-generated-icon-registry",
                    "severity": "error",
                    "location": python_icons_output,
                    "message": str(exc),
                }
            )
        if icons_parity is False and not any(
            item["kind"] == "invalid-generated-icon-registry" for item in issues
        ):
            issues.append(
                {
                    "kind": "generated-icon-registry-drift",
                    "severity": "error",
                    "location": python_icons_output,
                    "message": f"generated ICONS differs from {icons_path}",
                }
            )
    else:
        issues.append(
            {
                "kind": "missing-generated-icon-registry",
                "severity": "error",
                "location": python_icons_output,
                "message": "generated Python icon registry is missing",
            }
        )

    return StylePipeline(
        configured=True,
        contract_path="src/style/pipeline.json",
        frontend_entry=frontend_entry,
        registry=registry_path,
        registry_schema=registry_schema,
        icons=icons_path,
        icons_schema=icons_schema,
        virtual_module=str(registry.get("virtual_module", "")),
        python_output=python_output,
        python_icons_output=python_icons_output,
        icon_count=icon_count,
        used_icon_count=used_icon_count,
        css_entry=css_entry,
        css_output=str(css.get("output", "")),
        tailwind_sources=declared_sources,
        candidate_validator=candidate_validator,
        compiled_candidate_count=0,
        invalid_candidates=[],
        authored_stylesheets=authored_stylesheets,
        css_imports=imports,
        reachable_stylesheets=reachable,
        unreachable_stylesheets=unreachable,
        duplicate_stylesheets=duplicate,
        transforms=transforms,
        python_registry_parity=parity,
        python_icons_parity=icons_parity,
        issues=issues,
    )


def _validate_compiled_candidates(
    repo_root: Path,
    pipeline: StylePipeline,
    definitions: dict[str, style_registry.StyleDefinition],
) -> None:
    """Ask Tailwind whether every registry utility token is compilable."""
    if not pipeline.configured or not pipeline.candidate_validator:
        return
    validator = repo_root / pipeline.candidate_validator
    if not validator.is_file():
        pipeline.issues.append(
            {
                "kind": "missing-style-candidate-validator",
                "severity": "error",
                "location": pipeline.candidate_validator,
                "message": "declared Tailwind candidate validator does not exist",
            }
        )
        return
    candidates = sorted(
        {token for definition in definitions.values() for token in definition.tokens}
    )
    hooks = {hook for definition in definitions.values() for hook in definition.hooks}
    markers = {
        token
        for token in candidates
        if token in {"group", "peer"}
        or token.startswith(("group/", "peer/"))
    }
    markers.update(
        marker for definition in definitions.values() for marker in definition.markers
    )
    request = {
        "repoRoot": str(repo_root),
        "cssEntry": pipeline.css_entry,
        "candidates": candidates,
        "ignored": sorted(hooks | markers),
    }
    try:
        result = subprocess.run(
            ["node", str(validator)],
            cwd=repo_root,
            check=False,
            capture_output=True,
            input=json.dumps(request),
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pipeline.issues.append(
            {
                "kind": "style-candidate-validation-failed",
                "severity": "error",
                "location": pipeline.candidate_validator,
                "message": str(exc),
            }
        )
        return
    if result.returncode != 0:
        pipeline.issues.append(
            {
                "kind": "style-candidate-validation-failed",
                "severity": "error",
                "location": pipeline.candidate_validator,
                "message": result.stderr.strip() or result.stdout.strip(),
            }
        )
        return
    try:
        payload = json.loads(result.stdout)
        checked = int(payload["checked"])
        invalid = sorted(str(value) for value in payload["invalid"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        pipeline.issues.append(
            {
                "kind": "style-candidate-validation-failed",
                "severity": "error",
                "location": pipeline.candidate_validator,
                "message": f"invalid validator response: {exc}",
            }
        )
        return
    pipeline.compiled_candidate_count = checked
    pipeline.invalid_candidates = invalid
    for candidate in invalid:
        pipeline.issues.append(
            {
                "kind": "unavailable-tailwind-candidate",
                "severity": "error",
                "location": style_registry.DEFAULT_STYLES_PATH.as_posix(),
                "message": f"registry token is not emitted by Tailwind or declared as a CSS hook/marker: {candidate}",
            }
        )


def _style_consumers(
    references: list[style_candidates.StyleReference],
    families: dict[str, list[str]],
) -> dict[str, list[StyleConsumer]]:
    consumers: dict[str, list[StyleConsumer]] = defaultdict(list)
    for reference in references:
        names = (
            [reference.name]
            if reference.resolved == "leaf"
            else families.get(reference.name, [])
        )
        for name in names:
            consumers[name].append(
                StyleConsumer(
                    path=reference.path,
                    line=reference.line,
                    surface=_surface_name(reference.surface),
                    context=reference.context,
                    reference=reference.name,
                    resolution=reference.resolved,
                )
            )
    for items in consumers.values():
        items.sort(
            key=lambda item: (
                item.path,
                item.line,
                item.surface,
                item.reference,
            )
        )
    return consumers


def _registry_issues(
    styles: dict[str, StyleEntry], selectors: list[CssSelector]
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    selectors_by_path: dict[str, list[CssSelector]] = defaultdict(list)
    for item in selectors:
        selectors_by_path[item.path].append(item)

    def selector_has_hook(selector: str, hook: str) -> bool:
        pattern = rf"\.{re.escape(hook)}(?![A-Za-z0-9_-])"
        return re.search(pattern, selector) is not None

    for style in styles.values():
        location = f"{style.source['path']}:{style.source['line']}"
        missing_surfaces = sorted(
            set(style.declared_surfaces) - set(style.observed_surfaces)
        )
        for surface in missing_surfaces:
            issues.append(
                {
                    "kind": "style-surface-without-consumer",
                    "severity": "error",
                    "location": location,
                    "message": f"{style.id} declares {surface} but has no observed consumer",
                }
            )
        undeclared_surfaces = sorted(
            set(style.observed_surfaces) - set(style.declared_surfaces)
        )
        for surface in undeclared_surfaces:
            issues.append(
                {
                    "kind": "style-consumer-on-undeclared-surface",
                    "severity": "error",
                    "location": location,
                    "message": f"{style.id} is consumed on undeclared {surface} surface",
                }
            )
        for hook in style.hooks:
            if hook not in style.tokens:
                issues.append(
                    {
                        "kind": "style-hook-not-emitted",
                        "severity": "error",
                        "location": location,
                        "message": f"{style.id} declares hook {hook} but does not emit it",
                    }
                )
            if not any(
                style.id in selector.owners
                and selector_has_hook(selector.selector, hook)
                for selector in selectors
            ):
                issues.append(
                    {
                        "kind": "style-hook-without-rule",
                        "severity": "error",
                        "location": location,
                        "message": f"{style.id} hook {hook} has no authored CSS selector",
                    }
                )
        for marker in style.markers:
            if marker not in style.tokens:
                issues.append(
                    {
                        "kind": "style-marker-not-emitted",
                        "severity": "error",
                        "location": location,
                        "message": f"{style.id} declares marker {marker} but does not emit it",
                    }
                )
        for owner in style.css:
            if owner not in selectors_by_path:
                issues.append(
                    {
                        "kind": "style-css-owner-without-stylesheet",
                        "severity": "error",
                        "location": location,
                        "message": f"{style.id} CSS owner is missing: {owner}",
                    }
                )
                continue
            if not any(style.id in selector.owners for selector in selectors_by_path[owner]):
                issues.append(
                    {
                        "kind": "style-css-owner-without-rule",
                        "severity": "error",
                        "location": location,
                        "message": f"{style.id} has no @style-owned rule in {owner}",
                    }
                )
    for selector in selectors:
        selector_location = f"{selector.path}:{selector.line}"
        if selector.ownership == "semantic" and not selector.owners:
            issues.append(
                {
                    "kind": "unowned-semantic-selector",
                    "severity": "error",
                    "location": selector_location,
                    "message": f"semantic selector has no @style owner: {selector.selector}",
                }
            )
        for owner in selector.owners:
            style = styles.get(owner)
            if style is None:
                issues.append(
                    {
                        "kind": "unknown-css-style-owner",
                        "severity": "error",
                        "location": selector_location,
                        "message": f"selector names unknown style owner {owner}",
                    }
                )
            elif selector.path not in style.css:
                issues.append(
                    {
                        "kind": "css-style-owner-without-backlink",
                        "severity": "error",
                        "location": selector_location,
                        "message": f"{owner} does not declare CSS source {selector.path}",
                    }
                )
    return issues


def _fingerprint_styles(
    repo_root: Path,
    styles: dict[str, StyleEntry],
    selectors: list[CssSelector],
) -> dict[str, StyleEntry]:
    record_fingerprints = style_registry.style_record_fingerprints(repo_root)
    selector_fingerprints: dict[str, set[str]] = defaultdict(set)
    for selector in selectors:
        for owner in selector.owners:
            selector_fingerprints[owner].add(selector.fingerprint)
    result: dict[str, StyleEntry] = {}
    for name, style in styles.items():
        payload = {
            "record": record_fingerprints.get(name, ""),
            "css_rules": sorted(selector_fingerprints.get(name, set())),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result[name] = replace(style, fingerprint=fingerprint)
    return result


def _attach_style_evidence(
    repo_root: Path,
    styles: dict[str, StyleEntry],
) -> tuple[dict[str, StyleEntry], list[dict[str, str]]]:
    """Connect explicit/test-template evidence and apply result freshness."""
    config_path = repo_root / "testing/utility/traceability.yaml"
    if not config_path.is_file():
        return styles, []

    from testing.utility import template_contracts, traceability

    config = traceability.load_config(
        Path("testing/utility/traceability.yaml"), repo_root
    )
    tests = traceability.collect_tests(repo_root, config["test_roots"])
    dependencies: dict[str, set[str]] = defaultdict(set)
    pending: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    issues: list[dict[str, str]] = []

    def add(style_id: str, nodeid: str, kind: str, source: str) -> None:
        pending[style_id].add((nodeid, kind, source))

    for test in tests.values():
        for style_id in test.metadata.styles:
            if style_id not in styles:
                issues.append(
                    {
                        "kind": "unknown-test-style-evidence",
                        "severity": "error",
                        "location": test.location,
                        "message": f"test names unknown semantic style {style_id}",
                    }
                )
                continue
            add(style_id, test.nodeid, "explicit", test.location)

    template_report = template_contracts.build_report(repo_root)
    styles_by_template_ref: dict[str, set[str]] = defaultdict(set)
    parsed_templates: dict[str, template_contracts.TemplateFile] = {}
    for style in styles.values():
        for consumer in style.consumers:
            prefix = "lagniappe/web/templates/"
            if consumer.path.startswith(prefix):
                template_path = consumer.path.removeprefix(prefix)
                parsed = parsed_templates.get(template_path)
                if parsed is None:
                    path = repo_root / consumer.path
                    if not path.is_file():
                        continue
                    parsed = template_contracts.parse_template_file(path, repo_root)
                    parsed_templates[template_path] = parsed
                owning_macro = next(
                    (
                        macro.name
                        for macro in parsed.macros.values()
                        if macro.lineno
                        <= consumer.line
                        <= macro.lineno + macro.body.count("\n") + 1
                    ),
                    "",
                )
                if owning_macro:
                    styles_by_template_ref[
                        f"{template_path}::{owning_macro}"
                    ].add(style.id)

    for entry in template_report.entries:
        owned_refs = {entry.reference.template_ref, *entry.included_macros}
        for template_ref in owned_refs:
            template_path = template_ref.split("::", 1)[0]
            for style_id in styles_by_template_ref.get(template_ref, set()):
                add(
                    style_id,
                    entry.reference.nodeid,
                    "template-contract",
                    template_ref,
                )
    for style_id, rows in list(pending.items()):
        explicit = {row for row in rows if row[1] == "explicit"}
        by_template: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for row in rows - explicit:
            by_template[row[2]].append(row)
        representatives = {
            sorted(
                candidates,
                key=lambda row: (
                    tests[row[0]].execution != "passed",
                    not tests[row[0]].execution_current,
                    row[0],
                ),
            )[0]
            for candidates in by_template.values()
        }
        pending[style_id] = explicit | representatives

    dependencies.clear()
    for style_id, rows in pending.items():
        for nodeid, kind, source in rows:
            dependencies[nodeid].add(f"@style/{style_id}")
            dependencies[nodeid].update(styles[style_id].css)
            if kind == "template-contract":
                dependencies[nodeid].add(
                    f"lagniappe/web/templates/{source.split('::', 1)[0]}"
                )

    traceability.apply_test_dependency_fingerprints(
        tests, dict(dependencies), repo_root
    )
    result: dict[str, StyleEntry] = {}
    for style_id, style in styles.items():
        evidence = []
        for nodeid, kind, source in sorted(pending.get(style_id, set())):
            test = tests.get(nodeid)
            if test is None:
                continue
            evidence.append(
                StyleEvidence(
                    nodeid=nodeid,
                    kind=kind,
                    source=source,
                    test_path=f"testing/{test.path}",
                    outcome=test.execution,
                    current=test.execution_current,
                )
            )
        result[style_id] = replace(style, evidence=evidence)
    return result, issues


def build_manifest(
    repo_root: Path,
    *,
    styles_path: Path = style_candidates.DEFAULT_STYLES_PATH,
    source_roots: Iterable[Path] = style_candidates.DEFAULT_SOURCE_ROOTS,
    command: Iterable[str] = (),
) -> StyleManifest:
    source_roots = tuple(source_roots)
    definitions = style_candidates.load_style_definitions(repo_root, styles_path)
    families = style_candidates.style_families(definitions)
    references, class_uses, files_by_surface = style_candidates.collect_usage(
        repo_root, source_roots, definitions, families
    )
    consumers = _style_consumers(references, families)
    resolved_styles_path = (
        styles_path if styles_path.is_absolute() else repo_root / styles_path
    )
    style_source = _relative(resolved_styles_path, repo_root)
    definition_lines = _definition_lines(resolved_styles_path)
    styles = {
        name: StyleEntry(
            id=name,
            classes=definition.classes,
            tokens=definition.tokens,
            source={"path": style_source, "line": definition_lines.get(name, 1)},
            alias=definition.alias,
            canonical=definition.canonical,
            intent=definition.intent,
            declared_surfaces=definition.surfaces,
            markers=definition.markers,
            hooks=definition.hooks,
            css=definition.css,
            exceptions=definition.exceptions,
            observed_surfaces=sorted(
                {consumer.surface for consumer in consumers.get(name, [])}
            ),
            consumers=consumers.get(name, []),
        )
        for name, definition in sorted(definitions.items())
    }
    raw_class_uses = [
        RawClassUse(
            classes=" ".join(use.literal_tokens),
            tokens=use.literal_tokens,
            style_refs=use.style_refs,
            path=use.path,
            line=use.line,
            surface=_surface_name(use.surface),
            context=use.context,
        )
        for use in sorted(
            class_uses,
            key=lambda item: (
                item.path,
                item.line,
                item.context,
                item.literal_tokens,
            ),
        )
    ]
    inputs = _manifest_inputs(repo_root, styles_path, source_roots)
    pipeline = _pipeline_inventory(repo_root, styles_path)
    _validate_compiled_candidates(repo_root, pipeline, definitions)
    selectors = _selector_inventory(repo_root, pipeline.authored_stylesheets)
    issues = _registry_issues(styles, selectors)
    styles = _fingerprint_styles(repo_root, styles, selectors)
    styles, evidence_issues = _attach_style_evidence(repo_root, styles)
    issues.extend(evidence_issues)
    return StyleManifest(
        summary={
            "style_definitions": len(styles),
            "style_families": len(families),
            "style_references": len(references),
            "raw_class_uses": len(raw_class_uses),
            "css_selectors": len(selectors),
            "inputs": len(inputs),
            "pipeline_issues": len(pipeline.issues),
            "icon_definitions": pipeline.icon_count,
            "used_icon_definitions": pipeline.used_icon_count,
            "registry_issues": len(issues),
            "style_evidence": sum(len(style.evidence) for style in styles.values()),
            "styles_with_evidence": sum(bool(style.evidence) for style in styles.values()),
            "source_files_by_surface": files_by_surface,
        },
        inputs=inputs,
        styles=styles,
        families=families,
        raw_class_uses=raw_class_uses,
        css_selectors=selectors,
        pipeline=pipeline,
        issues=issues,
        provenance=provenance(repo_root, command=command),
    )


def _manifest_body(manifest: StyleManifest) -> dict[str, object]:
    body = asdict(manifest)
    body.pop("provenance", None)
    return body


def manifest_fingerprint(manifest: StyleManifest) -> str:
    body = json.dumps(
        _manifest_body(manifest), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(body).hexdigest()


def manifest_payload(manifest: StyleManifest) -> dict[str, object]:
    return {
        "schema_version": STYLE_MANIFEST_SCHEMA_VERSION,
        "kind": "style-manifest",
        "provenance": manifest.provenance,
        "manifest_fingerprint": manifest_fingerprint(manifest),
        **_manifest_body(manifest),
    }


def query_manifest(
    manifest: StyleManifest,
    *,
    style_id: str | None = None,
    source: str | None = None,
    consumer: str | None = None,
    changed_paths: Iterable[str] = (),
) -> dict[str, object]:
    selected: set[str] = set()
    query: dict[str, object] = {}
    if style_id:
        selected.update(
            name
            for name in manifest.styles
            if name == style_id or name.startswith(f"{style_id}.")
        )
        query.update({"mode": "style", "value": style_id})
    elif source:
        selected.update(
            style.id
            for style in manifest.styles.values()
            if style.source["path"] == source
            or source in style.css
        )
        query.update({"mode": "source", "value": source})
    elif consumer:
        selected.update(
            style.id
            for style in manifest.styles.values()
            if any(item.path == consumer for item in style.consumers)
        )
        query.update({"mode": "consumer", "value": consumer})
    else:
        changed = set(changed_paths)
        if changed:
            if manifest.pipeline.registry in changed:
                selected.update(manifest.styles)
            selected.update(
                style.id
                for style in manifest.styles.values()
                if any(item.path in changed for item in style.consumers)
                or any(owner in changed for owner in style.css)
            )
            pipeline_paths = {
                manifest.pipeline.contract_path,
                manifest.pipeline.frontend_entry,
                manifest.pipeline.css_entry,
                *(
                    item.path
                    for item in manifest.inputs
                    if item.role in {"build-pipeline", "build-dependencies"}
                ),
            }
            query.update(
                {
                    "mode": "changed",
                    "value": sorted(changed),
                    "pipeline_affected": bool(changed & pipeline_paths),
                }
            )
    if not query:
        return {}
    query["styles"] = [asdict(manifest.styles[name]) for name in sorted(selected)]
    if source:
        query["css_selectors"] = [
            asdict(item) for item in manifest.css_selectors if item.path == source
        ]
        query["inputs"] = [
            asdict(item) for item in manifest.inputs if item.path == source
        ]
    return query


def build_report(
    repo_root: Path,
    *,
    styles_path: Path = style_candidates.DEFAULT_STYLES_PATH,
    source_roots: Iterable[Path] = style_candidates.DEFAULT_SOURCE_ROOTS,
    long_class_limit: int = style_candidates.DEFAULT_LONG_CLASS_LIMIT,
    repeat_limit: int = style_candidates.DEFAULT_REPEAT_LIMIT,
    command: Iterable[str] = (),
) -> tuple[Report, StyleManifest]:
    source_roots = tuple(source_roots)
    manifest = build_manifest(
        repo_root,
        styles_path=styles_path,
        source_roots=source_roots,
        command=command,
    )
    audit = style_candidates.build_report(
        repo_root,
        styles_path=styles_path,
        source_roots=source_roots,
        long_class_limit=long_class_limit,
        repeat_limit=repeat_limit,
    )
    summary = {
        **audit.summary,
        "manifest_inputs": manifest.summary["inputs"],
        "css_selectors": manifest.summary["css_selectors"],
        "pipeline_issues": len(manifest.pipeline.issues),
        "python_registry_parity": manifest.pipeline.python_registry_parity,
        "python_icons_parity": manifest.pipeline.python_icons_parity,
        "icon_definitions": manifest.pipeline.icon_count,
        "used_icon_definitions": manifest.pipeline.used_icon_count,
        "registry_issues": len(manifest.issues),
        "style_evidence": manifest.summary["style_evidence"],
        "styles_with_evidence": manifest.summary["styles_with_evidence"],
    }
    return (
        Report(
            summary=summary,
            manifest_fingerprint=manifest_fingerprint(manifest),
            audit=audit,
            pipeline=manifest.pipeline,
            registry_issues=manifest.issues,
            provenance=manifest.provenance,
        ),
        manifest,
    )


def _finding(
    kind: str, severity: str, location: str, message: str
) -> dict[str, str]:
    return {
        "id": stable_finding_id(kind, location, message),
        "kind": kind,
        "severity": severity,
        "location": location,
        "message": message,
    }


def report_findings(report: Report) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    audit = report.audit
    for item in audit.unknown_style_references:
        location = f"{item.path}:{item.line}"
        findings.append(
            _finding(
                "unknown-style-reference",
                "error",
                location,
                f"unknown style ID {item.name}",
            )
        )
    for name in audit.unused_style_definitions:
        findings.append(
            _finding(
                "unused-style-definition",
                "warning",
                style_candidates.DEFAULT_STYLES_PATH.as_posix(),
                f"{name} has no observed consumer",
            )
        )
    for item in audit.cross_surface_style_extensions:
        findings.append(
            _finding(
                "cross-surface-style-extension",
                "review",
                item.locations[0].path if item.locations else "repository",
                f"{item.style} is extended with "
                f"{' '.join(item.extra_classes)} on multiple surfaces",
            )
        )
    for item in audit.repeated_style_extensions:
        findings.append(
            _finding(
                "repeated-style-extension",
                "review",
                item.locations[0].path if item.locations else "repository",
                f"{item.style} is extended with {' '.join(item.extra_classes)} {item.count} times",
            )
        )
    for item in audit.raw_class_matches_yaml:
        findings.append(
            _finding(
                "raw-class-matches-style",
                "review",
                item.locations[0].path if item.locations else "repository",
                f"raw classes match {', '.join(item.matching_styles)}",
            )
        )
    for item in audit.duplicate_style_definitions:
        findings.append(
            _finding(
                "duplicate-style-value",
                "review",
                style_candidates.DEFAULT_STYLES_PATH.as_posix(),
                f"equal class values: {', '.join(item.styles)}",
            )
        )
    for item in report.pipeline.issues:
        findings.append(
            _finding(
                item["kind"],
                item["severity"],
                item["location"],
                item["message"],
            )
        )
    for item in report.registry_issues:
        findings.append(
            _finding(
                item["kind"],
                item["severity"],
                item["location"],
                item["message"],
            )
        )
    if report.query.get("mode") == "changed":
        for style in report.query.get("styles", []):
            evidence = style.get("evidence", [])
            location = f"{style['source']['path']}:{style['source']['line']}"
            if not evidence:
                findings.append(
                    _finding(
                        "changed-style-without-evidence",
                        "review",
                        location,
                        f"{style['id']} has no explicit or template-contract evidence",
                    )
                )
            elif not any(
                item.get("current") and item.get("outcome") == "passed"
                for item in evidence
            ):
                findings.append(
                    _finding(
                        "style-evidence-not-current",
                        "error",
                        location,
                        f"{style['id']} has no passing evidence for its current style/CSS dependencies",
                    )
                )
    return sorted(
        findings,
        key=lambda item: (
            {"error": 0, "warning": 1, "review": 2}.get(item["severity"], 3),
            item["kind"],
            item["location"],
            item["message"],
        ),
    )


def report_payload(report: Report) -> dict[str, object]:
    body = asdict(report)
    body.pop("provenance", None)
    return structured_report_payload(
        kind="style-traceability-report",
        report=body,
        report_provenance=report.provenance,
        findings=report_findings(report),
    )


def report_to_json(report: Report) -> str:
    return json.dumps(report_payload(report), indent=2, sort_keys=True)


def report_to_markdown(report: Report) -> str:
    pipeline = report.pipeline
    stylesheet_rows = "\n".join(
        f"| `{item.path}` | {item.ownership} |"
        for item in pipeline.authored_stylesheets
    )
    preamble = (
        "# Style Traceability Report\n\n"
        "Hard findings cover registry, ownership, compiled candidates, and build "
        "parity. Repeated strings remain review evidence, not rewrite instructions.\n\n"
        f"Manifest fingerprint: `{report.manifest_fingerprint}`\n\n"
        "## Semantic graph\n\n"
        f"- Styles: {report.summary['style_definitions']} "
        f"({report.summary['used_style_definitions']} observed)\n"
        f"- Icons: {pipeline.icon_count} ({pipeline.used_icon_count} observed)\n"
        f"- Evidence links: {report.summary['style_evidence']} across "
        f"{report.summary['styles_with_evidence']} styles\n"
        f"- Authored selectors: {report.summary['css_selectors']}\n"
        f"- Compiled candidates checked: {pipeline.compiled_candidate_count}\n\n"
        "## Build and CSS ownership\n\n"
        f"Registry: `{pipeline.registry}` via `{pipeline.registry_schema}`. "
        f"Icons: `{pipeline.icons}` via `{pipeline.icons_schema}`. "
        f"CSS entry: `{pipeline.css_entry}`. Candidate validator: "
        f"`{pipeline.candidate_validator}`.\n\n"
        "| Stylesheet | Ownership |\n"
        "| --- | --- |\n"
        f"{stylesheet_rows}\n\n"
        "## Advisory candidates\n\n"
    )
    audit = style_candidates.report_to_markdown(report.audit)
    audit = audit.removeprefix("# Style Candidate Inventory\n\n").removeprefix(
        "## Summary\n\n"
    )
    return preamble + audit


def save_manifest(
    manifest: StyleManifest,
    repo_root: Path,
    path: Path = DEFAULT_MANIFEST_PATH,
) -> Path:
    output = path if path.is_absolute() else repo_root / path
    write_json(output, manifest_payload(manifest))
    return output


def save_report(
    report: Report,
    repo_root: Path,
    path: Path = DEFAULT_REPORT_PATH,
) -> Path:
    output = path if path.is_absolute() else repo_root / path
    write_markdown_report(output, report_to_markdown(report))
    return output


def baseline_finding_ids(path: Path | None, repo_root: Path) -> set[str]:
    if path is None:
        return set()
    resolved = path if path.is_absolute() else repo_root / path
    payload = load_json(resolved)
    if not payload:
        raise ValueError(f"baseline report not found or invalid: {path}")
    values = payload.get("finding_ids")
    if not isinstance(values, list):
        raise ValueError(f"baseline contains no finding IDs: {path}")
    return {str(value) for value in values}


def run_from_traceability(args: object, argv: list[str] | None = None) -> int:
    repo_root = args.repo_root.resolve()
    command = ["traceability", *(argv or [])]
    try:
        report, manifest = build_report(repo_root, command=command)
        changed = []
        if args.changed is not None:
            style_inputs = {item.path for item in manifest.inputs}
            changed = [
                path
                for path in git_changed_paths(repo_root, args.changed)
                if path in style_inputs
            ]
        report.query = query_manifest(
            manifest,
            style_id=args.style,
            source=args.style_source,
            consumer=args.style_consumer,
            changed_paths=changed,
        )
        baseline_ids = baseline_finding_ids(args.baseline, repo_root)
    except Exception as exc:
        print(f"traceability styles: {exc}", file=sys.stderr)
        return 2

    if not args.no_manifest:
        save_manifest(manifest, repo_root, args.manifest_path)
    if args.write_baseline:
        baseline_path = (
            args.write_baseline
            if args.write_baseline.is_absolute()
            else repo_root / args.write_baseline
        )
        payload = report_payload(report)
        payload["kind"] = "style-traceability-baseline"
        write_json(baseline_path, payload)

    if args.json:
        print(report_to_json(report))
    else:
        if not args.no_report:
            save_report(report, repo_root, args.report_path or DEFAULT_REPORT_PATH)
        findings = report_findings(report)
        counts = {
            severity: sum(item["severity"] == severity for item in findings)
            for severity in ("error", "warning", "review")
        }
        print("Style Traceability Report")
        print(
            "\nInventory: "
            f"styles={report.summary['style_definitions']}, "
            f"used={report.summary['used_style_definitions']}, "
            f"icons={manifest.pipeline.icon_count}, "
            f"icons-used={manifest.pipeline.used_icon_count}, "
            f"raw-uses={manifest.summary['raw_class_uses']}, "
            f"css-selectors={manifest.summary['css_selectors']}, "
            f"inputs={manifest.summary['inputs']}"
        )
        print(
            "Findings: "
            f"errors={counts['error']}, warnings={counts['warning']}, "
            f"advisory-review={counts['review']}"
        )
        for finding in [
            item for item in findings if item["severity"] in {"error", "warning"}
        ][:20]:
            print(
                f"  [{finding['severity'].upper()}] {finding['location']}: "
                f"{finding['message']} ({finding['id']})"
            )
        print(f"Manifest fingerprint: {report.manifest_fingerprint}")
        if not args.no_manifest:
            print(f"Style manifest: {args.manifest_path}")
        if report.query:
            styles = report.query.get("styles", [])
            print(
                f"\nQuery: {report.query['mode']}={report.query['value']} "
                f"({len(styles)} styles)"
            )
            for style in styles[:30]:
                print(
                    f"  {style['id']} -> {style['classes']} "
                    f"[{', '.join(style['observed_surfaces']) or 'unused'}] "
                    f"fingerprint={style['fingerprint'][:12]}"
                )
                for consumer in style["consumers"][:5]:
                    print(f"    {consumer['path']}:{consumer['line']}")
                for evidence in style["evidence"][:5]:
                    state = (
                        evidence["outcome"]
                        if evidence["current"]
                        else f"stale-{evidence['outcome']}"
                    )
                    print(
                        f"    evidence {evidence['nodeid']} "
                        f"({evidence['kind']}, {state})"
                    )

    if args.check:
        severities = {"error"} if args.fail_on == "error" else {"error", "warning"}
        actionable = [
            finding
            for finding in report_findings(report)
            if finding["severity"] in severities and finding["id"] not in baseline_ids
        ]
        if actionable:
            print(
                f"\nStyle traceability check failed: {len(actionable)} new "
                f"{args.fail_on}-level finding(s).",
                file=sys.stderr,
            )
            return 1
    return 0


__all__ = [
    "CssSelector",
    "RawClassUse",
    "Report",
    "STYLE_MANIFEST_SCHEMA_VERSION",
    "StyleConsumer",
    "StyleEvidence",
    "StyleEntry",
    "StyleInput",
    "StyleManifest",
    "build_manifest",
    "build_report",
    "inventory_css_selectors",
    "manifest_fingerprint",
    "manifest_payload",
    "query_manifest",
    "report_findings",
    "report_payload",
    "report_to_json",
    "run_from_traceability",
]
