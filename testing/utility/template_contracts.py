#!/usr/bin/env python3
"""Template contract reporter for tests annotated with ``@template``.

This is a lightweight discoverability tool. It scans tests for template macro
references, extracts stable ``lp-*`` and ``data-*`` contract attributes from the
template macro and obvious imported macro calls, then reports what can be checked
against JavaScript classes/handlers and test selector usage.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable

from jinja2 import Environment, TemplateSyntaxError, nodes

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from testing.utility.artifacts import (
    limited as limited_items,
    markdown_code,
    markdown_escape,
    markdown_list,
    slugify,
    write_markdown_report,
)
from testing.utility import traceability
from testing.utility.traceability_common import (
    TRACEABILITY_SCHEMA_VERSION,
    git_changed_paths,
    load_json,
    provenance,
    write_json,
)


DEFAULT_REPORT_DIR = Path("reports")
DEFAULT_REPORT_PATH = DEFAULT_REPORT_DIR / "template-contracts.md"
TEMPLATE_ROOT = Path("lagniappe/web/templates")
TEXT_SECTION_LIMIT = 12
MAX_MACRO_DEPTH = 3

TAG_RE = re.compile(r"^\s*@(?P<tag>[\w-]+)(?:\s*[:=]\s*|\s+)?(?P<value>.*)$")
MACRO_START_RE = re.compile(
    r"{%-?\s*macro\s+(?P<name>\w+)\((?P<params>[^)]*)\)\s*-?%}"
)
MACRO_END_RE = re.compile(r"{%-?\s*endmacro\s*-?%}")
IMPORT_RE = re.compile(
    r"{%-?\s*import\s+['\"](?P<path>[^'\"]+)['\"]\s+as\s+(?P<alias>\w+)\s*-?%}"
)
FROM_IMPORT_RE = re.compile(
    r"{%-?\s*from\s+['\"](?P<path>[^'\"]+)['\"]\s+import\s+(?P<names>.*?)\s*-?%}",
    re.DOTALL,
)
CONTRACT_ATTR_RE = re.compile(
    r"(?P<name>(?:lp|data)-[\w-]+)(?:\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote))?",
    re.DOTALL,
)
CONTRACT_TAG_RE = re.compile(r"<[^>]*?(?:lp|data)-[\w-]+[^>]*>", re.DOTALL)
CLASS_RE = re.compile(r"(?:export\s+default\s+|export\s+)?class\s+(?P<name>\w+)")
DATA_ROLE_SELECTOR_RE = re.compile(r"\[data-role=(?P<quote>['\"])(?P<role>.*?)(?P=quote)\]")
DATASET_RE = re.compile(r"dataset(?:\?\.)?\.([A-Za-z][A-Za-z0-9_]*)")
CONTROL_EQUALS_RE = re.compile(r"control\s*===\s*['\"](?P<control>[^'\"]+)['\"]")
CONTROL_LIST_RE = re.compile(r"\[(?P<items>(?:\s*['\"][^'\"]+['\"]\s*,?)+)\]\.includes\(control\)")
STRING_ITEM_RE = re.compile(r"['\"](?P<value>[^'\"]+)['\"]")
ID_RE = re.compile(r"\bid=(?P<quote>['\"])(?P<id>.*?)(?P=quote)")
HAS_ATTRIBUTE_RE = re.compile(
    r"\.hasAttribute\(\s*(?P<quote>['\"])(?P<attr>lp-(?:create|update))(?P=quote)\s*\)"
)
SUBMIT_BUTTON_CONTRACTS = {
    "CREATE": "lp-create",
    "UPDATE": "lp-update",
}
STRUCTURAL_LP_ATTRIBUTES = {
    "lp-component",
    "lp-entity",
    "lp-nav",
    "lp-view",
}
STATEFUL_DATA_ATTRIBUTES = {
    "data-flipped",
}
ALLOWED_LP_ATTRIBUTES = {
    "lp-close",
    "lp-component",
    "lp-control",
    "lp-create",
    "lp-deferred",
    "lp-delete",
    "lp-edited-marker",
    "lp-entity",
    "lp-fingerprint",
    "lp-help",
    "lp-link",
    "lp-load",
    "lp-menu",
    "lp-nav",
    "lp-offline",
    "lp-prefetch",
    "lp-search",
    "lp-select",
    "lp-show",
    "lp-sync",
    "lp-update",
    "lp-view",
}
SUPERSEDED_LP_ATTRIBUTES = {
    "lp-expand": 'use data-role="expandable-cell" on the wrapper and data-role="expand" on the button',
    "lp-filters": 'use lp-control="filters"',
    "lp-form": 'use lp-control="form"',
    "lp-get": "removed modal lazy-load hook; add a new documented data-role/widget hook if needed",
    "lp-reset": 'use lp-control="reset"',
    "lp-star": 'use lp-control="star"',
    "lp-task": 'use lp-control="task"',
    "lp-version": (
        "removed with live form sync; forms use entity fingerprints and focused "
        "replacement routes"
    ),
}
ALLOWED_LP_CONTROLS = {
    "close",
    "delete",
    "filters",
    "form",
    "help",
    "history",
    "menu",
    "next",
    "previous",
    "reset",
    "star",
    "task",
}
ROUTED_LP_CONTROL_CONTRACTS = {
    "close": ("close", "lp-close", "data-close"),
    "filters": ("show", "lp-show", "data-filters"),
    "form": ("show", "lp-show", "data-form"),
    "help": ("help", "lp-help", "data-help"),
    "history": ("show", "lp-show", "data-history"),
    "reset": ("show", "lp-show", "data-reset"),
    "task": ("show", "lp-show", "data-task"),
}
RESOURCE_COLLECTION_CLASSES = {
    "Categories": "Category",
    "Forms": "Form",
    "ModelTasks": "ModelTask",
    "Pages": "Page",
    "Projects": "Project",
    "SitePages": "HomePage",
    "Tasks": "Task",
}


@dataclass(frozen=True)
class ArgValue:
    text: str
    literal: bool = True
    boolean: bool | None = None


@dataclass
class MacroInfo:
    path: Path
    name: str
    params: list[str]
    defaults: dict[str, ArgValue]
    body: str
    lineno: int


@dataclass
class TemplateFile:
    path: Path
    imports: dict[str, Path]
    from_imports: dict[str, tuple[Path, str]]
    macros: dict[str, MacroInfo]


@dataclass
class ContractAttribute:
    name: str
    value: str | None
    source: str
    dynamic: bool = False
    element: int | None = None

    @property
    def label(self) -> str:
        if self.value is None:
            return self.name
        return f"{self.name}={self.value}"


@dataclass
class TemplateReference:
    nodeid: str
    test_path: str
    qualname: str
    template_ref: str
    template_path: str
    macro: str
    lineno: int
    todos: list[str] = field(default_factory=list)


@dataclass
class SelectorEvidence:
    symbol: str
    selector: str
    matches: list[str]


@dataclass
class Check:
    status: str
    kind: str
    name: str
    detail: str


@dataclass
class ContractEntry:
    reference: TemplateReference
    included_macros: list[str]
    macro_calls: list[str]
    attributes: list[ContractAttribute]
    checks: list[Check]
    selector_evidence: list[SelectorEvidence]
    touched_attributes: list[str]
    touched_attribute_names: list[str]
    not_directly_selected: list[str]
    review: list[str]
    issues: list[str]


@dataclass
class ContractGroup:
    template_ref: str
    entries: list[ContractEntry]
    included_macros: list[str]
    attributes: list[ContractAttribute]
    checks: list[Check]
    touched_by_attribute: dict[str, list[str]]
    covered_by_template: dict[str, list[str]]
    not_directly_selected: list[str]
    review: list[str]
    issues: list[str]


@dataclass
class Report:
    summary: dict[str, object]
    entries: list[ContractEntry]
    groups: list[ContractGroup] = field(default_factory=list)
    provenance: dict[str, object] = field(default_factory=dict)
    changed_paths: list[str] = field(default_factory=list)


def repo_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return relpath(path, repo_root)
    except ValueError:
        return str(path)


def unique(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def limited(values: list[object], limit: int = TEXT_SECTION_LIMIT) -> tuple[list[object], int]:
    return limited_items(values, limit)


def parse_tag_values(text: str, tag_names: set[str], *, preserve: bool = False) -> list[str]:
    values: list[str] = []
    for raw_line in text.splitlines():
        line = traceability.clean_metadata_line(raw_line)
        match = TAG_RE.match(line)
        if not match:
            continue
        tag = match.group("tag").lower().replace("_", "-")
        if tag not in tag_names:
            continue
        value = match.group("value").strip()
        if preserve:
            if value:
                values.append(value)
        else:
            values.extend(traceability.split_values(value, preserve_brackets=True))
    return unique(values)


def parse_template_tags(text: str) -> list[str]:
    return parse_tag_values(
        text,
        {"template", "templates", "template-partial", "template-partials"},
    )


def parse_todo_tags(text: str) -> list[str]:
    return parse_tag_values(text, {"todo", "todos"}, preserve=True)


def normalize_target(target: str | None) -> str | None:
    if not target:
        return None
    normalized = traceability.base_nodeid(target).replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("testing/"):
        normalized = normalized[len("testing/") :]
    normalized = normalized.rstrip("/")
    return normalized


def normalize_template_target(target: str | None, repo_root: Path) -> str | None:
    if not target:
        return None
    clean = target.replace("\\", "/").strip()
    if ".html" not in clean:
        return None

    macro = ""
    if "::" in clean:
        clean, macro = clean.split("::", 1)

    if clean.startswith("./"):
        clean = clean[2:]
    if clean.startswith("/"):
        try:
            clean = relpath(Path(clean), repo_root)
        except ValueError:
            pass

    template_root = TEMPLATE_ROOT.as_posix()
    prefixes = [
        f"{template_root}/",
        "templates/",
    ]
    for prefix in prefixes:
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
            break

    clean = clean.strip("/")
    if macro:
        return f"{clean}::{macro}"
    return clean


def target_matches_test(target: str | None, test_path: str, qualname: str) -> bool:
    if not target:
        return True

    nodeid = f"{test_path}::{qualname}"
    path = Path(test_path)

    if "::" in target:
        target_path, target_qualname = target.split("::", 1)
        if target_qualname and not (
            qualname == target_qualname or qualname.endswith(f"::{target_qualname}")
        ):
            return False
        if not target_path:
            return True
        return path_matches_target(test_path, path, target_path)

    if target == nodeid:
        return True
    return path_matches_target(test_path, path, target)


def path_matches_target(test_path: str, path: Path, target_path: str) -> bool:
    clean = target_path.strip("/")
    if not clean:
        return True
    if clean.endswith(".py"):
        return test_path == clean or path.name == clean or test_path.endswith(f"/{clean}")
    return (
        test_path == clean
        or test_path.startswith(f"{clean}/")
        or clean in path.parts
        or path.name == clean
    )


def target_matches_template(
    target: str | None, template_path: str, macro: str
) -> bool:
    if not target:
        return True

    target_path = target
    target_macro = ""
    if "::" in target:
        target_path, target_macro = target.split("::", 1)
        if target_macro and macro != target_macro:
            return False

    path = Path(template_path)
    return (
        template_path == target_path
        or template_path.endswith(f"/{target_path}")
        or path.name == target_path
    )


def collect_template_references(
    repo_root: Path, target: str | None = None
) -> list[TemplateReference]:
    references: list[TemplateReference] = []
    tests_root = repo_root / "testing"
    normalized_target = normalize_target(target)
    template_target = normalize_template_target(target, repo_root)

    for path in sorted(tests_root.rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        test_path = relpath(path, tests_root)

        def visit_body(body: list[ast.stmt], stack: list[str]) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    visit_body(node.body, [*stack, node.name])
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = "::".join([*stack, node.name])
                    if node.name.startswith("test_"):
                        nodeid = f"{test_path}::{qualname}"
                        if template_target or target_matches_test(normalized_target, test_path, qualname):
                            metadata_text = traceability.metadata_text_for_python_node(
                                node, lines
                            )
                            for template_ref in parse_template_tags(metadata_text):
                                template_path, macro = split_template_ref(template_ref)
                                if not target_matches_template(
                                    template_target, template_path, macro
                                ):
                                    continue
                                references.append(
                                    TemplateReference(
                                        nodeid=nodeid,
                                        test_path=test_path,
                                        qualname=qualname,
                                        template_ref=template_ref,
                                        template_path=template_path,
                                        macro=macro,
                                        lineno=node.lineno,
                                        todos=parse_todo_tags(metadata_text),
                                    )
                                )
                    visit_body(node.body, [*stack, node.name])

        visit_body(tree.body, [])

    return references


def split_template_ref(template_ref: str) -> tuple[str, str]:
    if "::" not in template_ref:
        return template_ref, ""
    template_path, macro = template_ref.split("::", 1)
    return template_path, macro


def resolve_template_path(path_text: str, repo_root: Path, current: Path | None = None) -> Path:
    clean = path_text.strip().strip("'\"")
    # Jinja import paths are loader-root relative. A sibling path is only a
    # useful fallback for the few standalone fixtures that are not loader based.
    candidates = [repo_root / TEMPLATE_ROOT / clean]
    if current is not None:
        candidates.append(current.parent / clean)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (repo_root / TEMPLATE_ROOT / clean).resolve()


def split_args(text: str) -> list[str]:
    args: list[str] = []
    current = []
    quote: str | None = None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ",":
            value = "".join(current).strip()
            if value:
                args.append(value)
            current = []
        else:
            current.append(char)
    value = "".join(current).strip()
    if value:
        args.append(value)
    return args


def parse_arg_value(raw: str) -> ArgValue:
    value = raw.strip()
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return ArgValue(value[1:-1], literal=True)
    lowered = value.lower()
    if lowered == "true":
        return ArgValue("true", literal=True, boolean=True)
    if lowered == "false":
        return ArgValue("false", literal=True, boolean=False)
    if lowered in {"none", "null"}:
        return ArgValue("", literal=True)
    return ArgValue(f"{{{{ {value} }}}}", literal=False)


def parse_macro_params(text: str) -> tuple[list[str], dict[str, ArgValue]]:
    params: list[str] = []
    defaults: dict[str, ArgValue] = {}
    for part in split_args(text):
        if "=" in part:
            name, default = part.split("=", 1)
            clean = name.strip()
            params.append(clean)
            defaults[clean] = parse_arg_value(default)
        else:
            params.append(part.strip())
    return params, defaults


def parse_template_file(path: Path, repo_root: Path) -> TemplateFile:
    text = path.read_text(encoding="utf-8")
    imports = {
        match.group("alias"): resolve_template_path(match.group("path"), repo_root, path)
        for match in IMPORT_RE.finditer(text)
    }
    from_imports: dict[str, tuple[Path, str]] = {}
    for match in FROM_IMPORT_RE.finditer(text):
        imported_path = resolve_template_path(match.group("path"), repo_root, path)
        for item in split_args(match.group("names")):
            parts = item.split()
            if len(parts) == 3 and parts[1] == "as":
                original, alias = parts[0], parts[2]
            else:
                original = alias = item.strip()
            if alias:
                from_imports[alias] = (imported_path, original)

    macros: dict[str, MacroInfo] = {}
    for start in MACRO_START_RE.finditer(text):
        end = MACRO_END_RE.search(text, start.end())
        if not end:
            continue
        name = start.group("name")
        params, defaults = parse_macro_params(start.group("params"))
        macros[name] = MacroInfo(
            path=path,
            name=name,
            params=params,
            defaults=defaults,
            body=text[start.end() : end.start()],
            lineno=text[: start.start()].count("\n") + 1,
        )

    return TemplateFile(path=path, imports=imports, from_imports=from_imports, macros=macros)


def yesno(value: ArgValue) -> str:
    if value.boolean is not None:
        return "true" if value.boolean else "false"
    return "true" if value.text else "false"


def substitute_macro_args(
    macro: MacroInfo,
    args: list[ArgValue],
    kwargs: dict[str, ArgValue] | None = None,
) -> str:
    values = dict(macro.defaults)
    for name, value in zip(macro.params, args):
        values[name] = value
    values.update(kwargs or {})

    body = macro.body
    for name, value in values.items():
        escaped = re.escape(name)
        body = re.sub(
            r"{{-?\s*" + escaped + r"\s*\|\s*yesno\s*-?}}",
            yesno(value),
            body,
        )
        body = re.sub(
            r"{{-?\s*" + escaped + r"\s+or\s+(['\"])(.*?)\1\s*-?}}",
            lambda match: value.text or match.group(2),
            body,
        )
        body = re.sub(
            r"{{-?\s*" + escaped + r"\s*-?}}",
            value.text,
            body,
        )
    return body


def source_label(
    path: Path,
    macro: str,
    repo_root: Path,
    args: list[ArgValue] | None = None,
    kwargs: dict[str, ArgValue] | None = None,
) -> str:
    label = f"{relpath(path, repo_root / TEMPLATE_ROOT)}::{macro}"
    if args or kwargs:
        rendered_args = [arg.text for arg in args or []]
        rendered_args.extend(
            f"{name}={value.text}" for name, value in (kwargs or {}).items()
        )
        rendered = ", ".join(rendered_args)
        label = f"{label}({rendered})"
    return label


def jinja_arg_value(value: nodes.Expr) -> ArgValue:
    if isinstance(value, nodes.Const):
        if isinstance(value.value, bool):
            return ArgValue(
                "true" if value.value else "false",
                literal=True,
                boolean=value.value,
            )
        if value.value is None:
            return ArgValue("", literal=True)
        return ArgValue(str(value.value), literal=True)
    if isinstance(value, nodes.Name):
        return ArgValue(f"{{{{ {value.name} }}}}", literal=False)
    if isinstance(value, nodes.Getattr):
        parts = [value.attr]
        parent = value.node
        while isinstance(parent, nodes.Getattr):
            parts.append(parent.attr)
            parent = parent.node
        if isinstance(parent, nodes.Name):
            parts.append(parent.name)
            return ArgValue(f"{{{{ {'.'.join(reversed(parts))} }}}}", literal=False)
    return ArgValue("{{ expression }}", literal=False)


def jinja_macro_calls(
    text: str,
) -> list[tuple[str | None, str, list[ArgValue], dict[str, ArgValue]]]:
    """Return macro-shaped calls from every Jinja expression and call block."""
    try:
        tree = Environment().parse(text)
    except TemplateSyntaxError:
        return []

    result = []
    for call in tree.find_all(nodes.Call):
        alias: str | None = None
        name: str | None = None
        if isinstance(call.node, nodes.Getattr) and isinstance(call.node.node, nodes.Name):
            alias = call.node.node.name
            name = call.node.attr
        elif isinstance(call.node, nodes.Name):
            name = call.node.name
        if not name:
            continue
        result.append(
            (
                alias,
                name,
                [jinja_arg_value(arg) for arg in call.args],
                {keyword.key: jinja_arg_value(keyword.value) for keyword in call.kwargs},
            )
        )
    return result


def extract_contract_attributes(text: str, source: str) -> list[ContractAttribute]:
    attributes: list[ContractAttribute] = []

    tag_matches = list(CONTRACT_TAG_RE.finditer(text))
    contract_chunks = (
        (match.group(0), index) for index, match in enumerate(tag_matches)
    ) if tag_matches else ((text, None),)

    for chunk, element in contract_chunks:
        for match in CONTRACT_ATTR_RE.finditer(chunk):
            name = match.group("name")
            value = match.group("value")
            if value is not None:
                value = " ".join(value.split())
            dynamic = value is not None and ("{{" in value or "{%" in value)
            attributes.append(
                ContractAttribute(
                    name=name,
                    value=value,
                    source=source,
                    dynamic=dynamic,
                    element=element,
                )
            )
    return attributes


def resolve_macro_call(
    call_alias: str | None,
    call_name: str,
    template_file: TemplateFile,
) -> tuple[Path, str] | None:
    if call_alias:
        if call_alias not in template_file.imports:
            return None
        return template_file.imports[call_alias], call_name
    if call_name in template_file.from_imports:
        return template_file.from_imports[call_name]
    if call_name in template_file.macros:
        return template_file.path, call_name
    return None


def expand_template_contract(
    reference: TemplateReference, repo_root: Path
) -> tuple[list[str], list[str], list[ContractAttribute], list[str], list[str]]:
    cache: dict[Path, TemplateFile] = {}
    included_macros: list[str] = []
    macro_calls: list[str] = []
    attributes: list[ContractAttribute] = []
    review: list[str] = []
    issues: list[str] = []
    seen: set[tuple[Path, str, tuple[str, ...], tuple[tuple[str, str], ...]]] = set()

    def load(path: Path) -> TemplateFile:
        if path not in cache:
            cache[path] = parse_template_file(path, repo_root)
        return cache[path]

    def expand(
        path: Path,
        macro_name: str,
        args: list[ArgValue],
        kwargs: dict[str, ArgValue],
        depth: int,
    ) -> None:
        key = (
            path,
            macro_name,
            tuple(arg.text for arg in args),
            tuple((name, value.text) for name, value in sorted(kwargs.items())),
        )
        if key in seen:
            return
        seen.add(key)

        if depth > MAX_MACRO_DEPTH:
            review.append(f"macro expansion depth limit reached at {display_path(path, repo_root)}::{macro_name}")
            return
        if not path.exists():
            issues.append(f"template file not found: {display_path(path, repo_root)}")
            return

        template_file = load(path)
        macro = template_file.macros.get(macro_name)
        if not macro:
            issues.append(f"macro not found: {display_path(path, repo_root)}::{macro_name}")
            return

        label = source_label(
            path,
            macro_name,
            repo_root,
            args if depth else None,
            kwargs if depth else None,
        )
        included_macros.append(label)
        rendered = substitute_macro_args(macro, args, kwargs)
        attributes.extend(extract_contract_attributes(rendered, label))

        if "{% for " in rendered:
            review.append(f"{label} contains a Jinja loop; repeated contract elements need human review")
        if "{% if " in rendered:
            review.append(f"{label} contains a Jinja conditional; branch-specific contract elements need human review")

        for call_alias, call_name, call_args, call_kwargs in jinja_macro_calls(rendered):
            resolved = resolve_macro_call(call_alias, call_name, template_file)
            if not resolved:
                continue
            target_path, target_macro = resolved
            macro_calls.append(
                f"{source_label(path, macro_name, repo_root)} -> "
                f"{source_label(target_path, target_macro, repo_root, call_args, call_kwargs)}"
            )
            expand(target_path, target_macro, call_args, call_kwargs, depth + 1)

    template_path = resolve_template_path(reference.template_path, repo_root)
    if not reference.macro:
        issues.append(f"template reference needs ::macro: {reference.template_ref}")
    else:
        expand(template_path, reference.macro, [], {}, 0)

    return (
        unique(included_macros),
        unique(macro_calls),
        attributes,
        unique(review),
        unique(issues),
    )


def camel_to_kebab(value: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"-\1", value).lower()


@dataclass
class JsIndex:
    classes: dict[str, list[str]]
    role_consumers: dict[str, list[str]]
    dataset_names: dict[str, list[str]]
    direct_controls: dict[str, list[str]]
    submit_contracts: dict[str, list[str]]
    generic_control_handler: bool


@dataclass
class TemplateIndex:
    widgets: dict[str, list[str]]
    lp_show_by_widget: dict[str, list[str]]
    ids: dict[str, list[str]]


def collect_js_index(repo_root: Path) -> JsIndex:
    classes: dict[str, list[str]] = defaultdict(list)
    role_consumers: dict[str, list[str]] = defaultdict(list)
    dataset_names: dict[str, list[str]] = defaultdict(list)
    direct_controls: dict[str, list[str]] = defaultdict(list)
    submit_contracts: dict[str, list[str]] = defaultdict(list)
    generic_control_handler = False

    for path in sorted((repo_root / "src/script").rglob("*.mjs")):
        text = path.read_text(encoding="utf-8")
        rel = display_path(path, repo_root)
        for match in CLASS_RE.finditer(text):
            classes[match.group("name")].append(rel)
        for match in DATA_ROLE_SELECTOR_RE.finditer(text):
            role_consumers[match.group("role")].append(rel)
        for match in DATASET_RE.finditer(text):
            dataset_names[camel_to_kebab(match.group(1))].append(rel)
        for match in CONTROL_EQUALS_RE.finditer(text):
            direct_controls[match.group("control")].append(rel)
        for match in CONTROL_LIST_RE.finditer(text):
            for item in STRING_ITEM_RE.finditer(match.group("items")):
                direct_controls[item.group("value")].append(rel)
        for match in HAS_ATTRIBUTE_RE.finditer(text):
            submit_contracts[match.group("attr")].append(rel)
        if "control || button?.hasAttribute" in text:
            generic_control_handler = True

    return JsIndex(
        classes={key: unique(values) for key, values in classes.items()},
        role_consumers={key: unique(values) for key, values in role_consumers.items()},
        dataset_names={key: unique(values) for key, values in dataset_names.items()},
        direct_controls={key: unique(values) for key, values in direct_controls.items()},
        submit_contracts={key: unique(values) for key, values in submit_contracts.items()},
        generic_control_handler=generic_control_handler,
    )


def collect_template_index(repo_root: Path) -> TemplateIndex:
    widgets: dict[str, list[str]] = defaultdict(list)
    lp_show_by_widget: dict[str, list[str]] = defaultdict(list)
    ids: dict[str, list[str]] = defaultdict(list)

    for path in sorted((repo_root / TEMPLATE_ROOT).rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        rel = display_path(path, repo_root)
        for attr in extract_contract_attributes(text, rel):
            if attr.value is None or attr.dynamic:
                continue
            if attr.name == "data-widget":
                widgets[attr.value].append(rel)
            elif attr.name == "lp-show":
                parts = attr.value.split(":", 1)
                if len(parts) == 2:
                    lp_show_by_widget[parts[1]].append(f"{rel}: {attr.value}")
        for match in ID_RE.finditer(text):
            ids[match.group("id")].append(rel)

    return TemplateIndex(
        widgets={key: unique(values) for key, values in widgets.items()},
        lp_show_by_widget={key: unique(values) for key, values in lp_show_by_widget.items()},
        ids={key: unique(values) for key, values in ids.items()},
    )


@dataclass
class SelectorIndex:
    by_symbol: dict[str, str]
    by_attr: dict[str, list[tuple[str, str]]]


@dataclass
class HelperSelectorIndex:
    property_selectors: dict[tuple[str, str], list[tuple[str, str]]]
    method_selectors: dict[tuple[str, str], list[tuple[str, str]]]
    classes_by_alias: dict[str, list[str]]


@dataclass
class SubmitContractIndex:
    helpers_by_name: dict[str, list[tuple[str, list[str]]]]


def string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def snake_case_name(value: str) -> str:
    with_word_boundaries = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", with_word_boundaries).lower()


def class_aliases(class_name: str) -> set[str]:
    snake = snake_case_name(class_name)
    aliases = {class_name, class_name.lower(), snake}
    if class_name.endswith("Page"):
        stem = class_name[: -len("Page")]
        aliases.update({stem.lower(), snake.removesuffix("_page")})
    return {alias for alias in aliases if alias}


def decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    return None


def is_property_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(decorator_name(decorator) == "property" for decorator in node.decorator_list)


def selector_has_contract_attributes(selector: str) -> bool:
    return bool(extract_contract_attributes(selector, "helper"))


def joined_string_value(node: ast.JoinedStr) -> str:
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            prefix = "".join(parts).rstrip()
            if prefix.endswith(("'", '"', "=")):
                parts.append("{{ value }}")
    return "".join(parts)


def docstring_constant_ids(node: ast.AST) -> set[int]:
    ids = set()
    for child in ast.walk(node):
        if not isinstance(
            child, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        if not child.body:
            continue
        first = child.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def collect_helper_selector_index(repo_root: Path) -> HelperSelectorIndex:
    property_selectors: dict[tuple[str, str], list[tuple[str, str]]] = {}
    method_selectors: dict[tuple[str, str], list[tuple[str, str]]] = {}
    classes_by_alias: dict[str, list[str]] = defaultdict(list)
    roots = [repo_root / "testing/resources", repo_root / "testing/elements"]
    parsed_files: list[tuple[Path, ast.Module]] = []
    module_constants: dict[Path, dict[str, str]] = {}
    class_constants: dict[str, dict[str, str]] = {}

    for root in roots:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            parsed_files.append((path, tree))

            constants: dict[str, str] = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    value = string_value(node.value)
                    if value is None:
                        continue
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = value
                    continue
                if isinstance(node, ast.AnnAssign):
                    value = string_value(node.value) if node.value else None
                    if value is not None and isinstance(node.target, ast.Name):
                        constants[node.target.id] = value
                    continue
                if not isinstance(node, ast.ClassDef):
                    continue

                for alias in class_aliases(node.name):
                    classes_by_alias[alias].append(node.name)

                class_body_constants: dict[str, str] = {}
                for child in node.body:
                    if isinstance(child, ast.Assign):
                        value = string_value(child.value)
                        if value is None:
                            continue
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                class_body_constants[target.id] = value
                    elif isinstance(child, ast.AnnAssign):
                        value = string_value(child.value) if child.value else None
                        if value is not None and isinstance(child.target, ast.Name):
                            class_body_constants[child.target.id] = value

                class_constants[node.name] = class_body_constants

            module_constants[path] = constants

    class_constant_selectors = {
        f"{class_name}.{name}": value
        for class_name, constants in class_constants.items()
        for name, value in constants.items()
        if selector_has_contract_attributes(value)
    }

    def member_selectors(
        class_name: str,
        member: ast.FunctionDef | ast.AsyncFunctionDef,
        constants: dict[str, str],
    ) -> list[tuple[str, str]]:
        selectors: list[tuple[str, str]] = []
        symbol = f"{class_name}.{member.name}"
        docstrings = docstring_constant_ids(member)
        joined_string_fragments = {
            id(value)
            for node in ast.walk(member)
            if isinstance(node, ast.JoinedStr)
            for value in node.values
            if isinstance(value, ast.Constant)
        }

        for descendent in ast.walk(member):
            if isinstance(descendent, ast.Attribute) and isinstance(
                descendent.value, ast.Name
            ):
                if descendent.value.id in {"self", "cls"}:
                    selector = class_constants[class_name].get(descendent.attr)
                else:
                    selector = class_constant_selectors.get(
                        f"{descendent.value.id}.{descendent.attr}"
                    )
                if selector and selector_has_contract_attributes(selector):
                    selectors.append((symbol, selector))
            elif isinstance(descendent, ast.Name):
                selector = constants.get(descendent.id)
                if selector and selector_has_contract_attributes(selector):
                    selectors.append((symbol, selector))
            elif isinstance(descendent, ast.JoinedStr):
                selector = joined_string_value(descendent)
                if selector_has_contract_attributes(selector):
                    selectors.append((symbol, selector))
            elif (
                isinstance(descendent, ast.Constant)
                and id(descendent) not in joined_string_fragments
                and id(descendent) not in docstrings
                and isinstance(descendent.value, str)
                and selector_has_contract_attributes(descendent.value)
            ):
                selectors.append((symbol, descendent.value))

        return unique_selector_pairs(selectors)

    for path, tree in parsed_files:
        constants = module_constants[path]
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                selectors = member_selectors(node.name, child, constants)
                if not selectors:
                    continue
                if is_property_method(child):
                    property_selectors[(node.name, child.name)] = selectors
                else:
                    method_selectors[(node.name, child.name)] = selectors

    return HelperSelectorIndex(
        property_selectors=property_selectors,
        method_selectors=method_selectors,
        classes_by_alias={
            alias: sorted(set(classes)) for alias, classes in classes_by_alias.items()
        },
    )


def collect_selector_index(repo_root: Path) -> SelectorIndex:
    by_symbol: dict[str, str] = {}
    by_attr: dict[str, list[tuple[str, str]]] = defaultdict(list)
    roots = [repo_root / "testing/resources", repo_root / "testing/elements"]

    for root in roots:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))

            def visit_body(body: list[ast.stmt], stack: list[str]) -> None:
                for node in body:
                    if isinstance(node, ast.ClassDef):
                        visit_body(node.body, [*stack, node.name])
                    elif isinstance(node, ast.Assign):
                        value = string_value(node.value)
                        if value is None:
                            continue
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                symbol = ".".join([*stack, target.id]) if stack else target.id
                                by_symbol[symbol] = value
                                by_attr[target.id].append((symbol, value))
                    elif isinstance(node, ast.AnnAssign):
                        value = string_value(node.value) if node.value else None
                        if value is None or not isinstance(node.target, ast.Name):
                            continue
                        symbol = ".".join([*stack, node.target.id]) if stack else node.target.id
                        by_symbol[symbol] = value
                        by_attr[node.target.id].append((symbol, value))

            visit_body(tree.body, [])

    return SelectorIndex(by_symbol=by_symbol, by_attr=dict(by_attr))


def spinner_click_contract(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "click":
        return None
    button = func.value
    if (
        isinstance(button, ast.Attribute)
        and isinstance(button.value, ast.Name)
        and button.value.id == "SpinnerButtons"
    ):
        return SUBMIT_BUTTON_CONTRACTS.get(button.attr)
    return None


def collect_submit_contract_index(repo_root: Path) -> SubmitContractIndex:
    helpers_by_name: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    testing_root = repo_root / "testing"
    if not testing_root.exists():
        return SubmitContractIndex(helpers_by_name={})

    for path in sorted(testing_root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        def visit_body(body: list[ast.stmt], stack: list[str]) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    visit_body(node.body, [*stack, node.name])
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    contracts = unique(
                        contract
                        for child in ast.walk(node)
                        if (contract := spinner_click_contract(child))
                    )
                    if contracts:
                        qualname = ".".join([*stack, node.name])
                        helpers_by_name[node.name].append((qualname, contracts))
                    visit_body(node.body, [*stack, node.name])

        visit_body(tree.body, [])

    return SubmitContractIndex(
        helpers_by_name={
            name: helpers
            for name, helpers in helpers_by_name.items()
            if len(helpers) == 1
        }
    )


def called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def root_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return root_name(node.func)
    if isinstance(node, ast.Attribute):
        return root_name(node.value)
    if isinstance(node, ast.Subscript):
        return root_name(node.value)
    if isinstance(node, ast.Name):
        return node.id
    return None


def resource_class_from_value(
    value: ast.AST, helper_selector_index: HelperSelectorIndex
) -> str | None:
    root = root_name(value)
    if root in RESOURCE_COLLECTION_CLASSES:
        class_name = RESOURCE_COLLECTION_CLASSES[root]
        if class_name in helper_selector_index.classes_by_alias.get(class_name, []):
            return class_name
        return class_name

    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "go"
    ):
        for arg in value.args:
            if root_name(arg) == "SitePages":
                return RESOURCE_COLLECTION_CLASSES["SitePages"]

    return None


def helper_property_selectors(
    helper_selector_index: HelperSelectorIndex,
    receiver_name: str,
    property_name: str,
    resource_vars: dict[str, str],
) -> list[tuple[str, str]]:
    if receiver_name in resource_vars:
        class_names = [resource_vars[receiver_name]]
        require_unambiguous_alias = False
    else:
        class_names = helper_selector_index.classes_by_alias.get(receiver_name, [])
        require_unambiguous_alias = True

    matches = [
        (class_name, helper_selector_index.property_selectors[(class_name, property_name)])
        for class_name in class_names
        if (class_name, property_name) in helper_selector_index.property_selectors
    ]
    if require_unambiguous_alias and len(matches) != 1:
        return []

    selectors: list[tuple[str, str]] = []
    for _class_name, class_selectors in matches:
        selectors.extend(class_selectors)
    return selectors


def helper_method_selectors(
    helper_selector_index: HelperSelectorIndex,
    receiver_name: str,
    method_name: str,
    resource_vars: dict[str, str],
) -> list[tuple[str, str]]:
    if receiver_name in resource_vars:
        class_names = [resource_vars[receiver_name]]
        require_unambiguous_alias = False
    else:
        class_names = helper_selector_index.classes_by_alias.get(receiver_name, [])
        require_unambiguous_alias = True

    matches = [
        (class_name, helper_selector_index.method_selectors[(class_name, method_name)])
        for class_name in class_names
        if (class_name, method_name) in helper_selector_index.method_selectors
    ]
    if require_unambiguous_alias and len(matches) != 1:
        return []

    selectors: list[tuple[str, str]] = []
    for _class_name, class_selectors in matches:
        selectors.extend(class_selectors)
    return selectors


def find_test_node(path: Path, qualname: str) -> ast.AST | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parts = qualname.split("::")

    def visit_body(body: list[ast.stmt], stack: list[str]) -> ast.AST | None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                found = visit_body(node.body, [*stack, node.name])
                if found:
                    return found
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                current = [*stack, node.name]
                if current == parts:
                    return node
                found = visit_body(node.body, current)
                if found:
                    return found
        return None

    return visit_body(tree.body, [])


def selector_attributes(selector: str, source: str) -> list[ContractAttribute]:
    return extract_contract_attributes(selector, source)


def collect_test_selector_evidence(
    reference: TemplateReference,
    contract_attrs: list[ContractAttribute],
    selector_index: SelectorIndex,
    helper_selector_index: HelperSelectorIndex,
    submit_contract_index: SubmitContractIndex,
    repo_root: Path,
) -> tuple[list[SelectorEvidence], set[str], set[str]]:
    path = repo_root / "testing" / reference.test_path
    node = find_test_node(path, reference.qualname)
    if node is None:
        return [], set(), set()

    selectors: list[tuple[str, str]] = []
    helper_vars: dict[str, str] = {}
    resource_vars: dict[str, str] = {}
    docstrings = docstring_constant_ids(node)
    joined_string_fragments = {
        id(value)
        for child in ast.walk(node)
        if isinstance(child, ast.JoinedStr)
        for value in child.values
        if isinstance(value, ast.Constant)
    }

    def call_name(call: ast.AST) -> str | None:
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Name):
                return call.func.id
            if isinstance(call.func, ast.Attribute):
                return call.func.attr
        return None

    def helper_name(value: ast.AST) -> str | None:
        if isinstance(value, ast.Name):
            return helper_vars.get(value.id)
        return call_name(value)

    def receiver_name(value: ast.AST) -> str | None:
        if isinstance(value, ast.Name):
            return helper_vars.get(value.id) or value.id
        return helper_name(value) or root_name(value)

    def helper_class_from_value(value: ast.AST) -> str | None:
        root = root_name(value)
        if not root:
            return None
        class_names = helper_selector_index.classes_by_alias.get(root, [])
        if len(class_names) == 1:
            return class_names[0]
        return None

    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            value = child.value if isinstance(child, ast.Assign) else child.value
            name = call_name(value) if value else None
            resource_class = (
                resource_class_from_value(value, helper_selector_index)
                if value
                else None
            )
            if name in {"Attributes", "Link", "List"}:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        helper_vars[target.id] = name
            helper_class = helper_class_from_value(value) if value else None
            if helper_class:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        helper_vars[target.id] = helper_class
            if resource_class:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        resource_vars[target.id] = resource_class

        if isinstance(child, ast.Attribute):
            if isinstance(child.value, ast.Name):
                symbol = f"{child.value.id}.{child.attr}"
                if symbol in selector_index.by_symbol:
                    selectors.append((symbol, selector_index.by_symbol[symbol]))
                    continue
                selectors.extend(
                    helper_property_selectors(
                        helper_selector_index,
                        child.value.id,
                        child.attr,
                        resource_vars,
                    )
                )
            matches = selector_index.by_attr.get(child.attr, [])
            if len(matches) == 1:
                selectors.append(matches[0])
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            if (
                id(child) not in joined_string_fragments
                and id(child) not in docstrings
                and ("data-" in child.value or "lp-" in child.value)
            ):
                selectors.append(("literal", child.value))
        elif isinstance(child, ast.JoinedStr):
            selector = joined_string_value(child)
            if "data-" in selector or "lp-" in selector:
                selectors.append(("literal", selector))
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            owner = helper_name(child.func.value)
            if owner == "Link" and child.func.attr == "click":
                selectors.append(("Link.click", "a[data-role='title']"))
            elif owner == "Attributes" and child.func.attr == "select":
                selectors.extend(
                    [
                        ("Attributes.select", "[data-role='attributes']"),
                        ("Attributes.select", "[data-role='attribute']"),
                        ("Attributes.select", "[data-attribute]"),
                        ("Attributes.select", "[data-role='remove']"),
                    ]
                )
            elif owner == "Attributes" and child.func.attr == "set_selected":
                selectors.extend(
                    [
                        ("Attributes.set_selected", "[data-role='attributes']"),
                        ("Attributes.set_selected", "[data-role='attribute']"),
                        ("Attributes.set_selected", "[data-attribute]"),
                        ("Attributes.set_selected", "[data-selected]"),
                        ("Attributes.set_selected", "[data-role='add']"),
                        ("Attributes.set_selected", "[data-role='remove']"),
                    ]
                )
            elif owner == "Attributes" and child.func.attr == "expect_selected":
                selectors.extend(
                    [
                        ("Attributes.expect_selected", "[data-role='attribute']"),
                        ("Attributes.expect_selected", "[data-attribute]"),
                        ("Attributes.expect_selected", "[data-selected]"),
                    ]
                )
            elif child.func.attr in {"new_item", "new_ai_generated_item", "get_item"}:
                selectors.append(
                    (f"List.{child.func.attr}", "li[lp-entity][data-key]")
                )
            name = receiver_name(child.func.value)
            if name:
                selectors.extend(
                    helper_method_selectors(
                        helper_selector_index,
                        name,
                        child.func.attr,
                        resource_vars,
                    )
                )

    contract_by_exact = {attr.label: attr for attr in contract_attrs}
    contract_by_name: dict[str, list[ContractAttribute]] = defaultdict(list)
    for attr in contract_attrs:
        contract_by_name[attr.name].append(attr)

    evidence: list[SelectorEvidence] = []
    touched_exact: set[str] = set()
    touched_names: set[str] = set()

    def add_submit_evidence(symbol: str, detail: str, contracts: list[str]) -> None:
        matches = []
        for contract in contracts:
            if contract in contract_by_exact:
                touched_exact.add(contract)
                touched_names.add(contract)
                matches.append(contract)
        if matches:
            evidence.append(
                SelectorEvidence(symbol=symbol, selector=detail, matches=unique(matches))
            )

    for symbol, selector in unique_selector_pairs(selectors):
        matches: list[str] = []
        for attr in selector_attributes(selector, symbol):
            if attr.value is not None:
                touched_exact.add(attr.label)
            else:
                touched_names.add(attr.name)

            if attr.value is not None and attr.label in contract_by_exact:
                matches.append(attr.label)
            elif attr.value is not None and attr.name in contract_by_name:
                dynamic_matches = [
                    item.label for item in contract_by_name[attr.name] if item.dynamic
                ]
                if dynamic_matches:
                    touched_names.add(attr.name)
                    matches.extend(dynamic_matches)
            elif attr.value is None and attr.name in contract_by_name:
                matches.extend(item.label for item in contract_by_name[attr.name])
        if matches:
            evidence.append(
                SelectorEvidence(symbol=symbol, selector=selector, matches=unique(matches))
            )

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        contract = spinner_click_contract(child)
        if contract:
            symbol = next(
                name
                for name, value in SUBMIT_BUTTON_CONTRACTS.items()
                if value == contract
            )
            add_submit_evidence(
                f"SpinnerButtons.{symbol}",
                f"clicks submit button for {contract}",
                [contract],
            )
            continue
        name = called_name(child.func)
        if not name:
            continue
        helpers = submit_contract_index.helpers_by_name.get(name, [])
        if len(helpers) == 1:
            helper_symbol, contracts = helpers[0]
            add_submit_evidence(
                helper_symbol,
                "calls " + ", ".join(
                    f"SpinnerButtons.{button}"
                    for button, submit_attr in SUBMIT_BUTTON_CONTRACTS.items()
                    if submit_attr in contracts
                ),
                contracts,
            )

    return evidence, touched_exact, touched_names


def unique_selector_pairs(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen = set()
    result = []
    for symbol, selector in values:
        key = (symbol, selector)
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def static_values(attrs: list[ContractAttribute], name: str) -> list[str]:
    return unique(
        attr.value
        for attr in attrs
        if attr.name == name and attr.value is not None and not attr.dynamic
    )


def has_static_attr_value(
    attrs: Iterable[ContractAttribute], name: str, value: str
) -> bool:
    return any(
        attr.name == name
        and attr.value == value
        and not attr.dynamic
        for attr in attrs
    )


def has_attr_name(attrs: Iterable[ContractAttribute], name: str) -> bool:
    return any(attr.name == name for attr in attrs)


def routed_control_issues(attrs: list[ContractAttribute]) -> list[str]:
    issues: list[str] = []
    attrs_by_element: dict[tuple[str, int | None], list[ContractAttribute]] = (
        defaultdict(list)
    )
    for attr in attrs:
        attrs_by_element[(attr.source, attr.element)].append(attr)

    for attr in attrs:
        if (
            attr.name != "lp-control"
            or attr.value is None
            or attr.dynamic
            or attr.value not in ROUTED_LP_CONTROL_CONTRACTS
        ):
            continue

        controls, own_target, widget_target = ROUTED_LP_CONTROL_CONTRACTS[attr.value]
        element_attrs = attrs_by_element[(attr.source, attr.element)]

        if not has_static_attr_value(element_attrs, "data-controls", controls):
            issues.append(
                f"lp-control value {attr.value!r} from {attr.source} needs "
                f'data-controls="{controls}" for NavElement routing'
            )

        if not (
            has_attr_name(element_attrs, own_target)
            or has_attr_name(attrs, widget_target)
        ):
            issues.append(
                f"lp-control value {attr.value!r} from {attr.source} cannot resolve "
                f"a routed target; expected {own_target} on the control or "
                f"{widget_target} on an expanded widget/nav context"
            )

    return issues


def contract_attribute_issues(attrs: list[ContractAttribute]) -> list[str]:
    issues: list[str] = []
    for attr in attrs:
        if not attr.name.startswith("lp-"):
            continue

        if attr.name in SUPERSEDED_LP_ATTRIBUTES:
            issues.append(
                f"unsupported lp-* attribute {attr.name} from {attr.source}: "
                f"{SUPERSEDED_LP_ATTRIBUTES[attr.name]}"
            )
        elif attr.name not in ALLOWED_LP_ATTRIBUTES:
            issues.append(
                f"unsupported lp-* attribute {attr.name} from {attr.source}"
            )

        if attr.name != "lp-control":
            continue
        if attr.value is None:
            issues.append(f"lp-control missing value from {attr.source}")
        elif attr.dynamic:
            continue
        elif attr.value not in ALLOWED_LP_CONTROLS:
            issues.append(
                f"unsupported lp-control value {attr.value!r} from {attr.source}"
            )

    return unique([*issues, *routed_control_issues(attrs)])


def check_contract(
    attrs: list[ContractAttribute],
    js_index: JsIndex,
    template_index: TemplateIndex,
) -> list[Check]:
    checks: list[Check] = []

    for widget in static_values(attrs, "data-widget"):
        if widget in js_index.classes:
            checks.append(
                Check("ok", "widget", widget, ", ".join(js_index.classes[widget]))
            )
        else:
            checks.append(Check("warn", "widget", widget, "no matching JS class found"))

        triggers = template_index.lp_show_by_widget.get(widget, [])
        if triggers:
            checks.append(
                Check("info", "trigger", widget, "; ".join(triggers[:3]))
            )

    for destination in static_values(attrs, "data-destination"):
        parts = destination.split(":", 1)
        if len(parts) != 2:
            checks.append(Check("review", "destination", destination, "not component:widget shaped"))
            continue
        component, widget = parts
        widget_known = widget in js_index.classes or widget in template_index.widgets
        component_known = component in template_index.ids
        if widget_known and component_known:
            checks.append(Check("ok", "destination", destination, "component and widget found"))
        elif widget_known:
            checks.append(Check("review", "destination", destination, "widget found; component id not found in templates"))
        else:
            checks.append(Check("warn", "destination", destination, "destination widget not found"))

    for control in static_values(attrs, "lp-control"):
        if control not in ALLOWED_LP_CONTROLS:
            checks.append(Check("warn", "lp-control", control, "unsupported value"))
        elif control in js_index.direct_controls:
            checks.append(
                Check("ok", "lp-control", control, "direct Core._click handler")
            )
        elif js_index.generic_control_handler:
            checks.append(
                Check("ok", "lp-control", control, "generic renderComponent path")
            )
        else:
            checks.append(Check("warn", "lp-control", control, "no handler found"))

    for submit_attr in SUBMIT_BUTTON_CONTRACTS.values():
        if not any(attr.name == submit_attr for attr in attrs):
            continue
        handlers = js_index.submit_contracts.get(submit_attr, [])
        if handlers:
            checks.append(
                Check(
                    "ok",
                    "submit-contract",
                    submit_attr,
                    "handled by submit listener in " + ", ".join(handlers[:3]),
                )
            )
        else:
            checks.append(
                Check("warn", "submit-contract", submit_attr, "no submit handler found")
            )

    for show in static_values(attrs, "lp-show"):
        parts = show.split(":", 1)
        if len(parts) == 2 and (parts[1] in js_index.classes or parts[1] in template_index.widgets):
            checks.append(Check("ok", "lp-show", show, "target widget found"))
        elif len(parts) == 2 and parts[1] in {"active", "default", "nav"}:
            checks.append(Check("info", "lp-show", show, "reserved view component target"))
        else:
            checks.append(Check("review", "lp-show", show, "target needs human review"))

    consumed_roles = [
        role for role in static_values(attrs, "data-role") if role in js_index.role_consumers
    ]
    if consumed_roles:
        checks.append(
            Check(
                "info",
                "data-role consumers",
                ", ".join(consumed_roles[:8]),
                "roles consumed by frontend selectors",
            )
        )

    return checks


def important_attr_labels(
    attrs: list[ContractAttribute], js_index: JsIndex
) -> list[str]:
    labels = []
    for attr in attrs:
        if attr.dynamic:
            continue
        if attr.name in STRUCTURAL_LP_ATTRIBUTES:
            continue
        if attr.name.startswith("lp-"):
            labels.append(attr.label)
        elif attr.name in {"data-widget", "data-mode"}:
            labels.append(attr.label)
        elif attr.name in STATEFUL_DATA_ATTRIBUTES:
            labels.append(attr.label)
        elif attr.name == "data-role" and attr.value in js_index.role_consumers:
            labels.append(attr.label)
    return unique(labels)


def not_directly_selected(
    attrs: list[ContractAttribute],
    touched_exact: set[str],
    touched_names: set[str],
    js_index: JsIndex,
) -> list[str]:
    missing = []
    for attr in attrs:
        if attr.label not in important_attr_labels(attrs, js_index):
            continue
        if attr.name == "lp-control" and attr.value and f"lp-{attr.value}" in touched_names:
            continue
        if attr.label in touched_exact or attr.name in touched_names:
            continue
        missing.append(attr.label)
    return unique(missing)


def review_notes(
    attrs: list[ContractAttribute],
    existing: list[str],
    touched_exact: set[str],
    touched_names: set[str],
) -> list[str]:
    notes = list(existing)
    dynamic_by_name: dict[str, list[str]] = defaultdict(list)
    for attr in attrs:
        if attr.dynamic:
            if attr.label in touched_exact or attr.name in touched_names:
                continue
            dynamic_by_name[attr.name].append(f"{attr.label} from {attr.source}")
        elif attr.name == "data-route":
            notes.append(f"route behavior needs request/response assertions: {attr.label}")
        elif attr.name == "data-destination":
            notes.append(f"destination update needs behavior assertions: {attr.label}")
    for name, values in sorted(dynamic_by_name.items()):
        notes.append(
            f"dynamic {name} values need manual review ({len(values)}): "
            f"{format_values(unique(values))}"
        )
    return unique(notes)


def group_checks(checks: list[Check], touched_by_attribute: dict[str, list[str]]) -> list[Check]:
    result = []
    for check in checks:
        if (
            check.status == "warn"
            and check.kind == "widget"
            and f"data-widget={check.name}" in touched_by_attribute
        ):
            result.append(
                Check(
                    "info",
                    check.kind,
                    check.name,
                    "selector-only widget touched by tests; no matching JS class found",
                )
            )
        else:
            result.append(check)
    return result


def base_template_ref(label: str) -> str:
    return label.split("(", 1)[0]


def apply_included_template_coverage(groups: list[ContractGroup]) -> list[ContractGroup]:
    groups_by_ref = {group.template_ref: group for group in groups}

    for group in groups:
        included_refs = unique(
            ref
            for label in group.included_macros
            if (ref := base_template_ref(label)) != group.template_ref
        )
        covered: dict[str, list[str]] = {}
        still_missing: list[str] = []

        for attr in group.not_directly_selected:
            evidence = []
            for included_ref in included_refs:
                included = groups_by_ref.get(included_ref)
                if not included:
                    continue
                for item in included.touched_by_attribute.get(attr, []):
                    evidence.append(f"{included_ref}: {item}")

            if evidence:
                covered[attr] = unique(evidence)
            else:
                still_missing.append(attr)

        group.covered_by_template = covered
        group.not_directly_selected = still_missing

    return groups


def build_contract_groups(
    entries: list[ContractEntry], js_index: JsIndex
) -> list[ContractGroup]:
    grouped: dict[str, list[ContractEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.reference.template_ref].append(entry)

    groups: list[ContractGroup] = []
    for template_ref, group_entries in grouped.items():
        first = group_entries[0]
        touched_attributes = unique(
            attribute
            for entry in group_entries
            for attribute in entry.touched_attributes
        )
        touched_names = unique(
            name for entry in group_entries for name in entry.touched_attribute_names
        )
        touched_by_attribute: dict[str, list[str]] = defaultdict(list)
        for entry in group_entries:
            for evidence in entry.selector_evidence:
                for match in evidence.matches:
                    touched_by_attribute[match].append(
                        f"{entry.reference.nodeid} via {evidence.symbol}"
                    )

        existing_review = unique(
            note
            for entry in group_entries
            for note in entry.review
            if not note.startswith("dynamic ")
        )
        touched_by_attribute = {
            key: unique(values) for key, values in touched_by_attribute.items()
        }
        groups.append(
            ContractGroup(
                template_ref=template_ref,
                entries=group_entries,
                included_macros=first.included_macros,
                attributes=first.attributes,
                checks=group_checks(first.checks, touched_by_attribute),
                touched_by_attribute=touched_by_attribute,
                covered_by_template={},
                not_directly_selected=not_directly_selected(
                    first.attributes, set(touched_attributes), set(touched_names), js_index
                ),
                review=review_notes(
                    first.attributes,
                    existing_review,
                    set(touched_attributes),
                    set(touched_names),
                ),
                issues=unique(issue for entry in group_entries for issue in entry.issues),
            )
        )

    return apply_included_template_coverage(
        sorted(groups, key=lambda group: group.template_ref)
    )


def build_report(
    repo_root: Path,
    target: str | None = None,
    *,
    changed_paths: Iterable[str] | None = None,
) -> Report:
    references = collect_template_references(repo_root, target)
    changed_path_list = sorted(set(changed_paths or []))
    js_index = collect_js_index(repo_root)
    template_index = collect_template_index(repo_root)
    selector_index = collect_selector_index(repo_root)
    helper_selector_index = collect_helper_selector_index(repo_root)
    submit_contract_index = collect_submit_contract_index(repo_root)

    entries: list[ContractEntry] = []
    for reference in references:
        macros, calls, attrs, review, issues = expand_template_contract(
            reference, repo_root
        )
        issues = unique([*issues, *contract_attribute_issues(attrs)])
        checks = check_contract(attrs, js_index, template_index)
        evidence, touched_exact, touched_names = collect_test_selector_evidence(
            reference,
            attrs,
            selector_index,
            helper_selector_index,
            submit_contract_index,
            repo_root,
        )
        entries.append(
            ContractEntry(
                reference=reference,
                included_macros=macros,
                macro_calls=calls,
                attributes=attrs,
                checks=checks,
                selector_evidence=evidence,
                touched_attributes=unique(touched_exact),
                touched_attribute_names=unique(touched_names),
                not_directly_selected=not_directly_selected(
                    attrs, touched_exact, touched_names, js_index
                ),
                review=review_notes(attrs, review, touched_exact, touched_names),
                issues=issues,
            )
        )

    if changed_paths is not None and not any(
        path.startswith("src/script/") for path in changed_path_list
    ):
        changed_set = set(changed_path_list)

        def entry_is_changed(entry: ContractEntry) -> bool:
            if f"testing/{entry.reference.test_path}" in changed_set:
                return True
            referenced = f"{TEMPLATE_ROOT.as_posix()}/{entry.reference.template_path}"
            if referenced in changed_set:
                return True
            return any(
                f"{TEMPLATE_ROOT.as_posix()}/{label.split('::', 1)[0]}" in changed_set
                for label in entry.included_macros
            )

        entries = [entry for entry in entries if entry_is_changed(entry)]

    groups = build_contract_groups(entries, js_index)
    check_counts = Counter(check.status for group in groups for check in group.checks)
    summary = {
        "template_references": len(references),
        "tests": len({reference.nodeid for reference in references}),
        "template_partials": len({reference.template_ref for reference in references}),
        "included_macros": sum(len(group.included_macros) for group in groups),
        "contract_attributes": sum(len(group.attributes) for group in groups),
        "checks_ok": check_counts.get("ok", 0),
        "checks_warn": check_counts.get("warn", 0),
        "checks_review": check_counts.get("review", 0),
        "checks_info": check_counts.get("info", 0),
        "selector_evidence": sum(len(entry.selector_evidence) for entry in entries),
        "not_directly_selected": sum(
            len(group.not_directly_selected) for group in groups
        ),
        "review_notes": sum(len(group.review) for group in groups),
        "issues": sum(len(group.issues) for group in groups),
        "target": target,
        "changed_scope": changed_paths is not None,
        "changed_paths": len(changed_path_list),
    }
    return Report(
        summary=summary,
        entries=entries,
        groups=groups,
        provenance=provenance(repo_root),
        changed_paths=changed_path_list,
    )


def grouped_attr_values(attrs: list[ContractAttribute], names: set[str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name in names:
        labels = []
        for attr in attrs:
            if attr.name == name:
                labels.append(attr.value if attr.value is not None else "(present)")
        if labels:
            values[name] = unique(labels)
    return values


def stable_finding_id(kind: str, location: str, message: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{location}\0{message}".encode()).hexdigest()[:16]
    return f"{kind}:{digest}"


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

    for group in report.groups:
        for issue in group.issues:
            add("template-contract", "error", group.template_ref, issue)
        for check in group.checks:
            if check.status == "warn":
                add(
                    "template-check",
                    "warning",
                    group.template_ref,
                    f"{check.kind} {check.name}: {check.detail}",
                )
            elif check.status == "review":
                add(
                    "template-check-review",
                    "review",
                    group.template_ref,
                    f"{check.kind} {check.name}: {check.detail}",
                )
        for note in group.review:
            add("template-review", "review", group.template_ref, note)
    return findings


def finding_counts(report: Report) -> Counter:
    return Counter(finding["severity"] for finding in report_findings(report))


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
    raise ValueError(f"baseline contains no finding IDs: {path}")


def actionable_findings(
    report: Report,
    *,
    fail_on: str = "error",
    baseline_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    severities = {"error"} if fail_on == "error" else {"error", "warning"}
    ignored = baseline_ids or set()
    return [
        finding
        for finding in report_findings(report)
        if finding["severity"] in severities and finding["id"] not in ignored
    ]


def format_values(values: list[str]) -> str:
    shown, remaining = limited(values)
    text = ", ".join(shown) if shown else "none"
    if remaining:
        text += f", ... {remaining} more"
    return text


def format_grouped(
    title: str, values: dict[str, list[str]], indent: str = ""
) -> list[str]:
    if not values:
        return [f"{indent}{title}: none"]
    lines = [f"{indent}{title}:"]
    for name, items in sorted(values.items()):
        lines.append(f"{indent}  {name}: {format_values(items)}")
    return lines


def format_contract_details(attrs: list[ContractAttribute], indent: str = "  ") -> list[str]:
    widgets = static_values(attrs, "data-widget")
    roles = static_values(attrs, "data-role")
    lp_attrs = [
        attr.label for attr in attrs if attr.name.startswith("lp-")
    ]
    data_attrs = grouped_attr_values(
        attrs,
        {
            "data-destination",
            "data-route",
            "data-mode",
            "data-visible",
            "data-if-empty",
            "data-entity",
            "data-toggle",
            "data-explain",
        },
    )
    lines = [f"{indent}contract:"]
    lines.append(f"{indent}  widgets: {format_values(widgets)}")
    lines.append(f"{indent}  lp attrs: {format_values(unique(lp_attrs))}")
    lines.append(f"{indent}  data roles: {format_values(roles)}")
    lines.extend(format_grouped("data attrs", data_attrs, f"{indent}  "))
    return lines


def format_checks(checks: list[Check], indent: str = "  ") -> list[str]:
    lines = [f"{indent}automated checks:"]
    if checks:
        for check in checks:
            lines.append(
                f"{indent}  [{check.status.upper()}] "
                f"{check.kind} {check.name}: {check.detail}"
            )
    else:
        lines.append(f"{indent}  none")
    return lines


def format_selector_evidence(
    evidence_items: list[SelectorEvidence], indent: str = "  "
) -> list[str]:
    lines = [f"{indent}test evidence:"]
    if evidence_items:
        shown, remaining = limited(evidence_items)
        for evidence in shown:
            lines.append(
                f"{indent}  - {evidence.symbol}: {evidence.selector} -> "
                f"{format_values(evidence.matches)}"
            )
        if remaining:
            lines.append(f"{indent}  ... {remaining} more")
    else:
        lines.append(f"{indent}  none found")
    return lines


def format_entry(entry: ContractEntry, *, include_missing: bool = False) -> list[str]:
    lines = [f"    {entry.reference.nodeid}"]
    if entry.reference.todos:
        lines.append(f"      test todos: {format_values(entry.reference.todos)}")
    lines.extend(format_selector_evidence(entry.selector_evidence, "      "))
    if include_missing and entry.not_directly_selected:
        lines.append(
            "      not directly selected by this test: "
            f"{format_values(entry.not_directly_selected)}"
        )
    return lines


def format_group(group: ContractGroup) -> list[str]:
    lines = [
        f"\n{group.template_ref}",
        f"  tests: {len(group.entries)}",
        f"  included macros: {format_values(group.included_macros)}",
    ]
    lines.extend(format_contract_details(group.attributes, "  "))
    lines.extend(format_checks(group.checks, "  "))

    lines.append("  touched by tests:")
    if group.touched_by_attribute:
        shown, remaining = limited(sorted(group.touched_by_attribute))
        for attr in shown:
            lines.append(f"    - {attr}:")
            for test in group.touched_by_attribute[attr]:
                lines.append(f"      - {test}")
        if remaining:
            lines.append(f"    ... {remaining} more attributes")
    else:
        lines.append("    none found")

    if group.covered_by_template:
        lines.append("  covered by included template tags:")
        for attr in sorted(group.covered_by_template):
            lines.append(f"    - {attr}:")
            for test in group.covered_by_template[attr]:
                lines.append(f"      - {test}")

    lines.append("  per-test evidence:")
    for entry in group.entries:
        lines.extend(format_entry(entry, include_missing=len(group.entries) == 1))

    if group.not_directly_selected:
        lines.append(
            "  not directly selected by any tagged test: "
            f"{format_values(group.not_directly_selected)}"
        )
    if group.review:
        lines.append("  review manually:")
        shown, remaining = limited(group.review)
        for note in shown:
            lines.append(f"    - {note}")
        if remaining:
            lines.append(f"    ... {remaining} more")
    if group.issues:
        lines.append("  issues:")
        for issue in group.issues:
            lines.append(f"    - {issue}")
    return lines


def format_report(report: Report, *, verbose: bool = False) -> str:
    counts = finding_counts(report)
    lines = [
        "Template Contract Report",
        "",
        "Summary:",
        f"  template references: {report.summary['template_references']}",
        f"  tests with template tags: {report.summary['tests']}",
        f"  template partials: {report.summary['template_partials']}",
        f"  included macros: {report.summary['included_macros']}",
        f"  contract attributes: {report.summary['contract_attributes']}",
        "  automated checks: "
        f"ok={report.summary['checks_ok']}, "
        f"warn={report.summary['checks_warn']}, "
        f"review={report.summary['checks_review']}, "
        f"info={report.summary['checks_info']}",
        f"  test evidence groups: {report.summary['selector_evidence']}",
        f"  not directly selected: {report.summary['not_directly_selected']}",
        f"  review notes: {report.summary['review_notes']}",
        f"  issues: {report.summary['issues']}",
        "  findings: "
        f"errors={counts['error']}, warnings={counts['warning']}, "
        f"review={counts['review']}",
    ]
    if report.summary.get("target"):
        lines.append(f"  target filter: {report.summary['target']}")

    findings = report_findings(report)
    actionable = [
        finding for finding in findings if finding["severity"] in {"error", "warning"}
    ]
    if actionable:
        lines.append("\nFindings:")
        shown, remaining = limited(actionable)
        for finding in shown:
            lines.append(
                f"  [{finding['severity'].upper()}] {finding['location']}: "
                f"{finding['message']} ({finding['id']})"
            )
        if remaining:
            lines.append(f"  ... {remaining} more; use --verbose for full contract detail")
    else:
        lines.append("\nNo error/warning contract findings.")

    if not report.groups:
        lines.append("\nNo @template references found.")
    elif verbose:
        lines.append("\nTemplate partials:")
        for group in report.groups:
            lines.extend(format_group(group))
    return "\n".join(lines)


def markdown_contract_details(attrs: list[ContractAttribute]) -> list[str]:
    lines = [
        f"- widgets: {markdown_list(static_values(attrs, 'data-widget'))}",
        "- lp attrs: "
        f"{markdown_list(unique(attr.label for attr in attrs if attr.name.startswith('lp-')))}",
        f"- data roles: {markdown_list(static_values(attrs, 'data-role'))}",
    ]
    data_attrs = grouped_attr_values(
        attrs,
        {
            "data-destination",
            "data-route",
            "data-mode",
            "data-visible",
            "data-if-empty",
            "data-entity",
            "data-toggle",
            "data-explain",
        },
    )
    if data_attrs:
        lines.append("- data attrs:")
        for name, values in sorted(data_attrs.items()):
            lines.append(f"  - {markdown_code(name)}: {markdown_list(values)}")
    return lines


def markdown_checks(checks: list[Check]) -> list[str]:
    if not checks:
        return ["_None._"]
    return [
        f"- **{markdown_escape(check.status.upper())}** "
        f"{markdown_escape(check.kind)} {markdown_code(check.name)}: "
        f"{markdown_escape(check.detail)}"
        for check in checks
    ]


def markdown_selector_evidence(evidence_items: list[SelectorEvidence]) -> list[str]:
    if not evidence_items:
        return ["_None found._"]
    return [
        f"- {markdown_code(evidence.symbol)} "
        f"{markdown_code(evidence.selector)} -> "
        f"{markdown_list(evidence.matches)}"
        for evidence in evidence_items
    ]


def report_to_markdown(report: Report, *, verbose: bool = False) -> str:
    counts = finding_counts(report)
    lines = [
        "# Template Contract Report",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    metrics = [
        ("Template references", report.summary["template_references"]),
        ("Tests with template tags", report.summary["tests"]),
        ("Template partials", report.summary["template_partials"]),
        ("Included macros", report.summary["included_macros"]),
        ("Contract attributes", report.summary["contract_attributes"]),
        ("Checks ok", report.summary["checks_ok"]),
        ("Checks warn", report.summary["checks_warn"]),
        ("Checks review", report.summary["checks_review"]),
        ("Checks info", report.summary["checks_info"]),
        ("Test evidence groups", report.summary["selector_evidence"]),
        ("Not directly selected", report.summary["not_directly_selected"]),
        ("Review notes", report.summary["review_notes"]),
        ("Issues", report.summary["issues"]),
        ("Finding errors", counts["error"]),
        ("Finding warnings", counts["warning"]),
        ("Finding review", counts["review"]),
    ]
    for name, value in metrics:
        lines.append(f"| {markdown_escape(name)} | {markdown_escape(value)} |")
    lines.append("")
    if report.summary.get("target"):
        lines.extend([f"Target filter: {markdown_code(report.summary['target'])}", ""])

    findings = report_findings(report)
    actionable = [
        finding for finding in findings if finding["severity"] in {"error", "warning"}
    ]
    lines.extend(["## Findings", ""])
    if actionable:
        for finding in actionable:
            lines.append(
                f"- **{markdown_escape(finding['severity'].upper())}** "
                f"{markdown_code(finding['location'])}: "
                f"{markdown_escape(finding['message'])} "
                f"({markdown_code(finding['id'])})"
            )
    else:
        lines.append("_No error/warning contract findings._")
    lines.append("")

    if not verbose:
        return "\n".join(lines).rstrip()

    if not report.groups:
        lines.extend(["_No @template references found._", ""])
        return "\n".join(lines)

    for group in report.groups:
        lines.extend(
            [
                f"## {markdown_code(group.template_ref)}",
                "",
                f"- tests: {len(group.entries)}",
                f"- included macros: {markdown_list(group.included_macros)}",
            ]
        )
        lines.append("")

        lines.extend(["### Contract", ""])
        lines.extend(markdown_contract_details(group.attributes))
        lines.append("")

        lines.extend(["### Automated Checks", ""])
        lines.extend(markdown_checks(group.checks))
        lines.append("")

        lines.extend(["### Touched By Tests", ""])
        if group.touched_by_attribute:
            for attr in sorted(group.touched_by_attribute):
                lines.append(f"- {markdown_code(attr)}")
                for test in group.touched_by_attribute[attr]:
                    lines.append(f"  - {markdown_escape(test)}")
        else:
            lines.append("_None found._")
        lines.append("")

        if group.covered_by_template:
            lines.extend(["### Covered By Included Template Tags", ""])
            for attr in sorted(group.covered_by_template):
                lines.append(f"- {markdown_code(attr)}")
                for test in group.covered_by_template[attr]:
                    lines.append(f"  - {markdown_escape(test)}")
            lines.append("")

        lines.extend(["### Per-Test Evidence", ""])
        for entry in group.entries:
            lines.append(f"#### {markdown_code(entry.reference.nodeid)}")
            lines.append("")
            if entry.reference.todos:
                lines.append(f"- test todos: {markdown_list(entry.reference.todos)}")
                lines.append("")
            lines.extend(markdown_selector_evidence(entry.selector_evidence))
            if len(group.entries) == 1 and entry.not_directly_selected:
                lines.append("")
                lines.append(
                    "- not directly selected by this test: "
                    f"{markdown_list(entry.not_directly_selected)}"
                )
            lines.append("")

        if group.not_directly_selected:
            lines.extend(["### Not Directly Selected By Any Tagged Test", ""])
            lines.extend(f"- {markdown_code(item)}" for item in group.not_directly_selected)
            lines.append("")
        if group.review:
            lines.extend(["### Review Manually", ""])
            lines.extend(f"- {markdown_escape(item)}" for item in group.review)
            lines.append("")
        if group.issues:
            lines.extend(["### Issues", ""])
            lines.extend(f"- {markdown_escape(item)}" for item in group.issues)
        lines.append("")

    return "\n".join(lines).rstrip()


def default_markdown_report_path(report: Report) -> Path:
    if len(report.groups) == 1:
        slug = slugify(report.groups[0].template_ref, "template")
        return DEFAULT_REPORT_DIR / f"template-contracts-{slug}.md"
    target = report.summary.get("target")
    if not target:
        return DEFAULT_REPORT_PATH
    return DEFAULT_REPORT_DIR / f"template-contracts-{slugify(target, 'target')}.md"


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


def report_payload(report: Report) -> dict[str, object]:
    body = asdict(report)
    body.pop("provenance", None)
    findings = report_findings(report)
    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        "kind": "template-contract-report",
        "provenance": report.provenance,
        "findings": findings,
        "finding_ids": [finding["id"] for finding in findings],
        "report": body,
    }


def report_to_json(report: Report) -> str:
    return json.dumps(report_payload(report), indent=2, sort_keys=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        help=(
            "Optional test nodeid, test_file.py::test_name, test file, test "
            "folder, template path, or template.html::macro to report."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_file())
    parser.add_argument(
        "--changed",
        nargs="?",
        const="HEAD",
        metavar="BASE",
        help=(
            "Report contracts affected by tests, templates, or frontend code "
            "changed from BASE. Defaults to HEAD."
        ),
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
        help="Ignore finding IDs recorded in an earlier template-contract JSON report.",
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help="Write the current structured findings as a baseline JSON file.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Markdown report path. Defaults to reports/template-contracts*.md.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write the default Markdown report file.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include exhaustive per-template contracts and selector evidence.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root = args.repo_root.resolve()
        if args.target and args.changed is not None:
            raise ValueError("pass either target or --changed, not both")
        changed = (
            git_changed_paths(repo_root, args.changed)
            if args.changed is not None
            else None
        )
        report = build_report(repo_root, args.target, changed_paths=changed)
        report.provenance = provenance(
            repo_root, command=["template-contracts", *(argv or sys.argv[1:])]
        )
        if args.target and not report.entries:
            raise ValueError(
                f"no @template references found for target: {args.target}"
            )
        baseline_ids = baseline_finding_ids(args.baseline, repo_root)
    except Exception as exc:  # pragma: no cover - command-line guard
        print(f"template-contracts: {exc}", file=sys.stderr)
        return 2

    if args.write_baseline:
        baseline_path = (
            args.write_baseline
            if args.write_baseline.is_absolute()
            else repo_root / args.write_baseline
        )
        payload = report_payload(report)
        payload["kind"] = "template-contract-baseline"
        write_json(baseline_path, payload)

    if args.json:
        print(report_to_json(report))
    else:
        print(format_report(report, verbose=args.verbose))
        if not args.no_report:
            saved_path = save_markdown_report(
                report,
                repo_root,
                args.report_path,
                verbose=args.verbose,
            )
            print(f"\nMarkdown report saved: {display_path(saved_path, repo_root)}")
    if args.check:
        findings = actionable_findings(
            report, fail_on=args.fail_on, baseline_ids=baseline_ids
        )
        if findings:
            print(
                f"\nTemplate-contract check failed: {len(findings)} new "
                f"{args.fail_on}-level finding(s).",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
