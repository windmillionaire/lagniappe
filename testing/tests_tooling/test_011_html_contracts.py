"""Repository-health checks for executable HTML trust boundaries."""

import ast
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "lagniappe" / "web" / "templates"
SAFE_HTML_SINKS = {
    "lagniappe/web/templates/files/text.html": 1,
    "lagniappe/web/templates/public/public.html": 1,
    "lagniappe/web/templates/tools/report.html": 1,
}
MARKUP_EMITTERS = {
    "lagniappe/core/tools/cache/query.py": {"_highlighted_html"},
    "lagniappe/web/start/jinja.py": {"render_icon", "render_safe_html"},
}
STAMPED_PRODUCERS = {
    "htmlize",
    "render_markdown",
    "sanitize_form_content_html",
    "sanitize_html",
    "sanitize_public_document_html",
}
JINJA_BLOCK = re.compile(r"{{.*?}}|{%.*?%}", re.DOTALL)
SAFE_FILTER = re.compile(r"\|\s*safe(?![_A-Za-z0-9])")
SAFE_HTML_FILTER = re.compile(r"\|\s*safe_html(?![_A-Za-z0-9])")


def _template_filter_count(source, pattern):
    return sum(len(pattern.findall(block)) for block in JINJA_BLOCK.findall(source))


@pytest.mark.parametrize(
    "source,unsafe_count,safe_html_count",
    [
        ("{{ value | safe }}", 1, 0),
        ("{{ value|default('')|safe }}", 1, 0),
        ("{% set rendered = value | safe %}", 1, 0),
        ("{{ value | safe_html }}", 0, 1),
        ("Documentation may mention value|safe without executing it.", 0, 0),
        ("{{ safely_named }}", 0, 0),
    ],
)
def test_template_filter_scanner_fixtures(source, unsafe_count, safe_html_count):
    assert _template_filter_count(source, SAFE_FILTER) == unsafe_count
    assert _template_filter_count(source, SAFE_HTML_FILTER) == safe_html_count


def test_application_templates_use_only_allowlisted_strict_html_sinks():
    actual_sinks = {}
    unsafe = []
    for path in TEMPLATES.rglob("*.html"):
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        unsafe_count = _template_filter_count(source, SAFE_FILTER)
        if unsafe_count:
            unsafe.append((relative, unsafe_count))
        safe_html_count = _template_filter_count(source, SAFE_HTML_FILTER)
        if safe_html_count:
            actual_sinks[relative] = safe_html_count

    assert unsafe == []
    assert actual_sinks == SAFE_HTML_SINKS


class _ConstructorVisitor(ast.NodeVisitor):
    def __init__(self):
        self.function = None
        self.safe_html_aliases = {"SafeHTML"}
        self.markup_aliases = {"Markup"}
        self.safe_html_calls = []
        self.stamp_calls = []
        self.markup_calls = []
        self.markup_imported = False
        self.public_stamp_helpers = []

    def visit_Import(self, node):
        for imported in node.names:
            if imported.name == "markupsafe":
                self.markup_imported = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for imported in node.names:
            if imported.name == "SafeHTML":
                self.safe_html_aliases.add(imported.asname or imported.name)
            if imported.name == "Markup":
                self.markup_aliases.add(imported.asname or imported.name)
                self.markup_imported = True
        self.generic_visit(node)

    def _visit_function(self, node):
        previous = self.function
        self.function = node.name
        if node.name in {"mark_safe", "trusted_html", "safe_html"}:
            self.public_stamp_helpers.append((node.name, node.lineno))
        self.generic_visit(node)
        self.function = previous

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
        record = (self.function, node.lineno)
        if name in self.safe_html_aliases or attribute == "SafeHTML":
            self.safe_html_calls.append(record)
        if name == "_stamp_safe_html":
            self.stamp_calls.append(record)
        if name in self.markup_aliases or attribute == "Markup":
            self.markup_calls.append(record)
        self.generic_visit(node)


@pytest.mark.parametrize(
    "source,safe_html_calls,markup_calls,markup_imported",
    [
        (
            "from package import SafeHTML as Trusted\nTrusted('value')",
            1,
            0,
            False,
        ),
        (
            "import package.html as html_tools\nhtml_tools.SafeHTML('value')",
            1,
            0,
            False,
        ),
        (
            "from markupsafe import Markup as TrustedMarkup\nTrustedMarkup('value')",
            0,
            1,
            True,
        ),
        (
            "import markupsafe as markup\nmarkup.Markup('value')",
            0,
            1,
            True,
        ),
        ("message = 'SafeHTML and Markup are prose'", 0, 0, False),
    ],
)
def test_constructor_scanner_fixtures(
    source,
    safe_html_calls,
    markup_calls,
    markup_imported,
):
    visitor = _ConstructorVisitor()
    visitor.visit(ast.parse(source))

    assert len(visitor.safe_html_calls) == safe_html_calls
    assert len(visitor.markup_calls) == markup_calls
    assert visitor.markup_imported is markup_imported


def test_safe_html_and_markup_construction_stays_narrowly_allowlisted():
    python_root = ROOT / "lagniappe"
    safe_html_calls = []
    stamp_calls = []
    public_helpers = []
    markup_calls = []
    markup_imports = set()

    for path in python_root.rglob("*.py"):
        if "web/static" in path.as_posix():
            continue
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _ConstructorVisitor()
        visitor.visit(tree)
        safe_html_calls.extend((relative, *record) for record in visitor.safe_html_calls)
        stamp_calls.extend((relative, *record) for record in visitor.stamp_calls)
        public_helpers.extend((relative, *record) for record in visitor.public_stamp_helpers)
        markup_calls.extend((relative, *record) for record in visitor.markup_calls)
        if visitor.markup_imported:
            markup_imports.add(relative)

    assert [(path, function) for path, function, _line in safe_html_calls] == [
        ("lagniappe/core/tools/files/html.py", "_stamp_safe_html")
    ]
    assert public_helpers == []
    assert {
        (path, function) for path, function, _line in stamp_calls
    } == {
        ("lagniappe/core/tools/files/html.py", function)
        for function in STAMPED_PRODUCERS
    }
    assert markup_imports == set(MARKUP_EMITTERS)
    assert {
        (path, function) for path, function, _line in markup_calls
    } == {
        (path, function)
        for path, functions in MARKUP_EMITTERS.items()
        for function in functions
    }
