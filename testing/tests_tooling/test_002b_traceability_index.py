"""One-report source snapshots retain traceability semantics and freshness."""

import ast
from collections import Counter
from pathlib import Path
import sys

import pytest

from testing.utility import traceability

pytestmark = pytest.mark.tooling


@pytest.fixture
def indexed_repo(tmp_path):
    files = {
        "traceability.yaml": """source_roots: [pkg]
test_roots: [testing/tests_unit]
test_scaffold_roots: [testing/resources]
annotation_scan_roots: [pkg]
exclude: []
""",
        "pkg/example.py": """# @testable true
# @scaffolding testing/resources/helper.py::Helper.exercise
# @pair example:save
def save():
    pass
""",
        "testing/resources/helper.py": """class Helper:
    def exercise(self):
        pass
""",
        "testing/tests_unit/test_example.py": """# @pair example:save
def test_first():
    helper.exercise()

class TestGroup:
    # @pair example:save
    async def test_second(self):
        helper.exercise()
""",
    }
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return tmp_path


@pytest.mark.parametrize("changed", [False, True])
def test_reporter_shares_one_read_and_parse_per_python_file(indexed_repo, monkeypatch, changed):
    reads, parses = Counter(), Counter()
    real_read, real_parse = Path.read_text, ast.parse
    paths = {str(path) for path in indexed_repo.rglob("*.py")}

    def read(path, *args, **kwargs):
        if str(path) in paths and sys._getframe(1).f_code.co_filename == traceability.__file__:
            reads[str(path)] += 1
        return real_read(path, *args, **kwargs)

    def parse(source, filename="<unknown>", *args, **kwargs):
        if str(filename) in paths and sys._getframe(1).f_code.co_filename == traceability.__file__:
            parses[str(filename)] += 1
        return real_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(ast, "parse", parse)
    options = {"changed_paths": ["pkg/example.py"]} if changed else {}
    report = traceability.build_report(indexed_repo, Path("traceability.yaml"), **options)

    assert report.summary["sources_with_known_tests"] == 1
    assert report.summary["source_test_links_known"] == 2
    assert report.feature_dimension_gaps == []
    assert report.stale_test_references == []
    assert reads == {path: 1 for path in paths}
    assert parses == {path: 1 for path in paths}
    assert traceability.FILE_INDEX.get() is None


def test_function_index_preserves_nested_async_and_decorator_call_boundaries(tmp_path):
    path = tmp_path / "testing/tests_unit/test_nested.py"
    path.parent.mkdir(parents=True)
    source = '''@outer_only()
async def test_same(value=default_call()):
    """Unicode café stays in the source segment."""
    @nested_decorator()
    def helper():
        nested_call()
    await client.exercise()
    text = "string_only()"
    callback = referenced_only

class TestGroup:
    @method_decorator()
    def test_same(self):
        other_call()

def enclosing():
    async def test_nested():
        nested_test_call()
'''
    path.write_text(source)
    tests = traceability.discover_tests(tmp_path, ["testing/tests_unit"])

    def calls(test, name):
        scaffold = traceability.SourceSymbol("helper.py", "python", "method", f"Helper.{name}", 1, 1, traceability.Metadata())
        return traceability.test_uses_scaffold(test, scaffold, tmp_path)

    with traceability.file_index_scope():
        outer = tests["tests_unit/test_nested.py::test_same"]
        method = tests["tests_unit/test_nested.py::TestGroup::test_same"]
        nested = tests["tests_unit/test_nested.py::enclosing::test_nested"]
        assert traceability.test_function_source(outer, tmp_path) == source[source.index("async def"):source.index("\n\nclass")]
        assert traceability.test_function_source(method, tmp_path) == "def test_same(self):\n        other_call()"
        assert traceability.test_function_source(nested, tmp_path) == "async def test_nested():\n        nested_test_call()"
        assert all(calls(outer, name) for name in ["default_call", "nested_decorator", "nested_call", "exercise"])
        assert not any(calls(outer, name) for name in ["outer_only", "string_only", "referenced_only", "other_call"])
        assert calls(method, "other_call") and not calls(method, "method_decorator")
        assert calls(nested, "nested_test_call") and not calls(nested, "exercise")
        unknown = traceability.TestCase("unknown", True, False, traceability.Metadata(), path=outer.path, qualname="test_missing", lineno=outer.lineno)
        assert traceability.test_function_source(unknown, tmp_path) == ""
        assert not calls(unknown, "exercise")


def test_report_cache_is_fresh_after_edits_and_failed_reports(indexed_repo):
    test_path = indexed_repo / "testing/tests_unit/test_example.py"
    first = traceability.build_report(indexed_repo, Path("traceability.yaml"))
    assert first.summary["source_test_links_known"] == 2

    original = test_path.read_text()
    test_path.write_text("def broken(:\n")
    with pytest.raises(SyntaxError):
        traceability.build_report(indexed_repo, Path("traceability.yaml"))
    assert traceability.FILE_INDEX.get() is None

    test_path.write_text(original.replace("helper.exercise()", "helper.different()"))
    second = traceability.build_report(indexed_repo, Path("traceability.yaml"))
    assert second.summary["source_test_links_known"] == 0
    assert second.summary["sources_with_known_tests"] == 0
    assert first.summary["source_test_links_known"] == 2
    assert traceability.FILE_INDEX.get() is None


@pytest.mark.parametrize("contents", [None, "def broken(:\n"])
def test_unreadable_and_invalid_functions_keep_empty_fallbacks(tmp_path, monkeypatch, contents):
    path = tmp_path / "testing/tests_unit/test_invalid.py"
    path.parent.mkdir(parents=True)
    if contents is not None:
        path.write_text(contents)
    test = traceability.TestCase("invalid", True, False, traceability.Metadata(), path="tests_unit/test_invalid.py", qualname="test_invalid", lineno=1)
    scaffold = traceability.SourceSymbol("helper.py", "python", "method", "exercise", 1, 1, traceability.Metadata())
    real_read, real_parse = Path.read_text, ast.parse
    reads, parses = [], []

    def read(target, *args, **kwargs):
        reads.append(target)
        return real_read(target, *args, **kwargs)

    def parse(source, *args, **kwargs):
        parses.append(source)
        return real_parse(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(ast, "parse", parse)
    with traceability.file_index_scope():
        for _ in range(2):
            assert traceability.test_function_source(test, tmp_path) == ""
            assert not traceability.test_uses_scaffold(test, scaffold, tmp_path)
        if contents is not None:
            with pytest.raises(SyntaxError):
                traceability.inventory_python_file(path, tmp_path)
    assert reads == [path]
    assert parses == ([] if contents is None else [contents])


def test_file_index_keeps_roots_and_nested_report_scopes_separate(tmp_path):
    first = tmp_path / "first/example.py"
    second = tmp_path / "second/example.py"
    for path, value in [(first, "first"), (second, "second")]:
        path.parent.mkdir()
        path.write_text(value)
    with traceability.file_index_scope():
        assert traceability.indexed_file(first).source == "first"
        assert traceability.indexed_file(second).source == "second"
        first.write_text("edited")
        with traceability.file_index_scope():
            assert traceability.indexed_file(first).source == "edited"
        assert traceability.indexed_file(first).source == "first"
    assert traceability.indexed_file(first).source == "edited"


def test_javascript_source_slicing_keeps_existing_line_boundaries(tmp_path):
    path = tmp_path / "testing/tests_js/test_example.mjs"
    path.parent.mkdir(parents=True)
    path.write_text("// header\ntest('one', () => {\n  exercise();\n});\n// footer\n")
    test = traceability.TestCase("one", True, False, traceability.Metadata(), path="tests_js/test_example.mjs", qualname="one", lineno=2, end_lineno=4)
    with traceability.file_index_scope():
        assert traceability.test_function_source(test, tmp_path) == "test('one', () => {\n  exercise();\n});"
