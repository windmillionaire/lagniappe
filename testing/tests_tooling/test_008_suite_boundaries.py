"""Repository-health checks for test-suite responsibility boundaries."""

import ast
from pathlib import Path
import re

import pytest


pytestmark = pytest.mark.tooling

TESTING_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TESTING_ROOT.parent
ROUTES_ROOT = REPOSITORY_ROOT / "lagniappe" / "web" / "routes"
LOWER_LEVEL_SUITES = (
    TESTING_ROOT / "tests_unit",
    TESTING_ROOT / "tests_tooling",
    TESTING_ROOT / "tests_js",
)
E2E_CACHE_CONTRACT_ROOTS = (
    TESTING_ROOT / "tests_e2e",
    TESTING_ROOT / "resources",
)
E2E_PROCESS_STATE_SUFFIXES = ("_READY", "_SEEDED", "_CREATED", "_INITIALIZED")
E2E_NATIVE_FETCH_ASSIGNMENT = re.compile(
    r"""\b(?:window|globalThis)\s*
        (?:\.\s*fetch|\[\s*['"]fetch['"]\s*\])\s*=
    """,
    re.VERBOSE,
)


def _python_files(*roots):
    for root in roots:
        yield from root.rglob("*.py")


def _package_imports(path, package):
    imports = []
    root, child = package.split(".", 1)
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.extend(
                alias.name
                for alias in node.names
                if alias.name == package or alias.name.startswith(f"{package}.")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == package or module.startswith(f"{package}."):
                imports.append(module)
            elif module == root and any(alias.name == child for alias in node.names):
                imports.append(package)
    return imports


def _runs_node(path):
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "shutil"
            and node.func.attr == "which"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "node"
        ):
            return True
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr in {
                "call",
                "check_call",
                "check_output",
                "Popen",
                "run",
            }
            and node.args
            and isinstance(node.args[0], (ast.List, ast.Tuple))
            and node.args[0].elts
        ):
            continue
        executable = node.args[0].elts[0]
        if isinstance(executable, ast.Constant) and executable.value == "node":
            return True
    return False


def _entities_call(node, method):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Entities"
        and node.func.attr == method
    )


def _cache_invalidation_target(node):
    return (isinstance(node, ast.Attribute) and node.attr == "invalidate_cache") or (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "invalidate_cache"
    )


def _uses_injected_entity(node):
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Subscript)
            and isinstance(child.value, ast.Name)
            and child.value.id == "kwargs"
            and isinstance(child.slice, ast.Constant)
            and child.slice.value == "entity"
        ):
            continue
        return True
    return False


def _has_permission_decorator(node):
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "permission":
            return True
    return False


def _permission_decorator_fetch_keyword(node):
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "permission"
        ):
            continue
        return next(
            (keyword for keyword in decorator.keywords if keyword.arg == "fetch"),
            None,
        )
    return None


def test_lower_level_suites_do_not_import_web_package():
    violations = {}
    for path in _python_files(*LOWER_LEVEL_SUITES):
        imports = _package_imports(path, "lagniappe.web")
        if imports:
            violations[str(path.relative_to(TESTING_ROOT))] = imports

    assert violations == {}


def test_tooling_suite_does_not_import_core_package():
    violations = {}
    for path in _python_files(TESTING_ROOT / "tests_tooling"):
        imports = _package_imports(path, "lagniappe.core")
        if imports:
            violations[str(path.relative_to(TESTING_ROOT))] = imports

    assert violations == {}


def test_tooling_suite_does_not_execute_node():
    violations = [
        str(path.relative_to(TESTING_ROOT))
        for path in _python_files(TESTING_ROOT / "tests_tooling")
        if _runs_node(path)
    ]

    assert violations == []


def test_e2e_support_does_not_clear_user_cache_invalidation_out_of_band():
    """Only the browser acknowledgement route may clear persisted invalidation."""
    violations = []
    for path in _python_files(*E2E_CACHE_CONTRACT_ROOTS):
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(REPOSITORY_ROOT)
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "clear_cache_invalidation"
            ):
                violations.append(
                    f"{relative}:{node.lineno} defines clear_cache_invalidation"
                )
                continue

            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 3
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "invalidate_cache"
                and isinstance(node.args[2], ast.Constant)
                and node.args[2].value is False
            ):
                violations.append(
                    f"{relative}:{node.lineno} clears invalidate_cache with setattr"
                )
                continue

            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue

            if (
                isinstance(value, ast.Constant)
                and value.value is False
                and any(_cache_invalidation_target(target) for target in targets)
            ):
                violations.append(
                    f"{relative}:{node.lineno} clears invalidate_cache directly"
                )

    assert violations == []


def test_e2e_modules_do_not_cache_durable_setup_in_process_booleans():
    """Durable E2E preconditions must be checked against the living datastore."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(REPOSITORY_ROOT)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue

            if not (
                isinstance(value, ast.Constant)
                and isinstance(value.value, bool)
            ):
                continue

            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith(
                    E2E_PROCESS_STATE_SUFFIXES
                ):
                    violations.append(f"{relative}:{node.lineno} defines {target.id}")

    assert violations == []


def test_e2e_modules_do_not_replace_native_browser_fetch():
    """Endpoint failures and stubs belong at Playwright's routing boundary."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(REPOSITORY_ROOT)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
            ):
                continue
            for offset, line in enumerate(node.value.splitlines()):
                if E2E_NATIVE_FETCH_ASSIGNMENT.search(line):
                    violations.append(
                        f"{relative}:{node.lineno + offset} assigns native fetch"
                    )

    assert violations == []


def test_web_routes_use_explicit_entity_fetch_boundaries():
    """Route code must not reintroduce identifier-dependent relation expansion."""
    violations = []
    for path in _python_files(ROUTES_ROOT):
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(REPOSITORY_ROOT)
        for node in ast.walk(tree):
            if _entities_call(node, "load"):
                violations.append(f"{relative}:{node.lineno} uses Entities.load")
            elif _entities_call(node, "get") and any(
                keyword.arg == "load"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                violations.append(
                    f"{relative}:{node.lineno} uses Entities.get(load=True)"
                )
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _uses_injected_entity(node)
                and not _has_permission_decorator(node)
            ):
                violations.append(
                    f"{relative}:{node.lineno} uses kwargs['entity'] without @permission"
                )
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (keyword := _permission_decorator_fetch_keyword(node)) is not None
            ):
                violations.append(
                    f"{relative}:{keyword.value.lineno} passes fetch to @permission"
                )

    assert violations == []
