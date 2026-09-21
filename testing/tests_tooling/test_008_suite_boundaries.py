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
E2E_BROWSER_INTERACTION_ROOTS = (
    TESTING_ROOT / "tests_e2e",
    TESTING_ROOT / "resources",
    TESTING_ROOT / "elements",
    TESTING_ROOT / "utility",
)
E2E_PROCESS_STATE_SUFFIXES = ("_READY", "_SEEDED", "_CREATED", "_INITIALIZED")
E2E_NATIVE_FETCH_ASSIGNMENT = re.compile(
    r"""\b(?:window|globalThis)\s*
        (?:\.\s*fetch|\[\s*['"]fetch['"]\s*\])\s*=
    """,
    re.VERBOSE,
)
E2E_SYNTHETIC_POINTER_DISPATCH = re.compile(
    r"""dispatchEvent\s*\(\s*new\s+(?:Event|PointerEvent|TouchEvent)\s*\(
        \s*['"](?:pointer(?:down|move|up|cancel)|touch(?:start|move|end|cancel))['"]
    """,
    re.VERBOSE,
)
E2E_INLINE_LAYOUT_ASSIGNMENT = re.compile(
    r"""\.style\s*(?:
        (?:\.\s*(?:width|minWidth|maxWidth)|
           \[\s*['"](?:width|minWidth|maxWidth)['"]\s*\])\s*=|
        \.\s*setProperty\s*\(\s*['"](?:width|min-width|max-width)['"]
    )""",
    re.VERBOSE,
)
E2E_BROWSER_STORAGE_ACCESS = re.compile(r"\b(?:localStorage|sessionStorage)\b")
E2E_SYNTHETIC_LIFECYCLE_DISPATCH = re.compile(
    r"""dispatchEvent\s*\(\s*new\s+(?:Event|CustomEvent)\s*\(
        \s*['"](?:focus|online|offline)['"]
    """,
    re.VERBOSE,
)
E2E_SYNTHETIC_INPUT_EVENTS = {
    "pointercancel",
    "pointerdown",
    "pointermove",
    "pointerup",
    "touchcancel",
    "touchend",
    "touchmove",
    "touchstart",
}
E2E_SYNTHETIC_LIFECYCLE_EVENTS = {"focus", "offline", "online"}
E2E_NONRETRYING_BROWSER_GETTERS = {"get_attribute", "inner_text"}
E2E_LOCATOR_FACTORIES = {
    "get_by_alt_text",
    "get_by_label",
    "get_by_placeholder",
    "get_by_role",
    "get_by_test_id",
    "get_by_text",
    "get_by_title",
    "locate",
    "locator",
}
E2E_DIRECT_AI_HELPERS = {
    "complete_ask_report",
    "complete_organize_submissions",
}


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


def _attribute_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def _e2e_cache_invalidation_violations(path):
    """Return out-of-band invalidation clearing from one E2E support module."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "clear_cache_invalidation"
        ):
            violations.append(f"{path}:{node.lineno} defines clear_cache_invalidation")
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
                f"{path}:{node.lineno} clears invalidate_cache with setattr"
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
                f"{path}:{node.lineno} clears invalidate_cache directly"
            )

    return violations


def _e2e_process_state_violations(path):
    """Return module booleans that cache durable E2E setup state."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue

        if not (isinstance(value, ast.Constant) and isinstance(value.value, bool)):
            continue

        for target in targets:
            if isinstance(target, ast.Name) and target.id.endswith(
                E2E_PROCESS_STATE_SUFFIXES
            ):
                violations.append(f"{path}:{node.lineno} defines {target.id}")

    return violations


def _e2e_native_fetch_violations(path):
    """Return browser scripts that replace the native fetch implementation."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for match in E2E_NATIVE_FETCH_ASSIGNMENT.finditer(node.value):
            line = node.lineno + node.value[: match.start()].count("\n")
            violations.append(f"{path}:{line} assigns native fetch")

    return violations


def _e2e_route_bypass_violations(path):
    """Return direct route calls and decorator bypasses in one E2E module."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    route_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "lagniappe.web.routes" or alias.name.startswith(
                    "lagniappe.web.routes."
                ):
                    route_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "lagniappe.web.routes" or module.startswith(
                "lagniappe.web.routes."
            ):
                route_names.update(alias.asname or alias.name for alias in node.names)
            elif module == "lagniappe.web" and any(
                alias.name == "routes" for alias in node.names
            ):
                route_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "routes"
                )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _attribute_name(node.func)
            if target and any(
                target == name or target.startswith(f"{name}.")
                for name in route_names
            ):
                violations.append(
                    f"{path}:{node.lineno} calls imported route {target}"
                )
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "__wrapped__"
            and (target := _attribute_name(node.value))
            and any(
                target == name or target.startswith(f"{name}.")
                for name in route_names
            )
        ):
            violations.append(f"{path}:{node.lineno} accesses route __wrapped__")
    return violations


def _e2e_ai_worker_bypass_violations(path):
    """Return direct provider/helper calls that bypass durable AI workers."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    ai_model_names = {"ai_model"}
    helper_names = {name: name for name in E2E_DIRECT_AI_HELPERS}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            local_name = alias.asname or alias.name
            if alias.name == "ai_model":
                ai_model_names.add(local_name)
            elif alias.name in E2E_DIRECT_AI_HELPERS:
                helper_names[local_name] = alias.name

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id in helper_names:
            violations.append(
                f"{path}:{node.lineno} calls {helper_names[target.id]}"
            )
            continue
        if not isinstance(target, ast.Attribute):
            continue
        if target.attr in E2E_DIRECT_AI_HELPERS:
            violations.append(f"{path}:{node.lineno} calls {target.attr}")
        elif (
            target.attr == "generate_content"
            and (
                (
                    isinstance(target.value, ast.Name)
                    and target.value.id in ai_model_names
                )
                or (
                    isinstance(target.value, ast.Attribute)
                    and target.value.attr == "ai_model"
                )
            )
        ):
            violations.append(f"{path}:{node.lineno} calls ai_model.generate_content")
    return violations


def _e2e_interaction_shortcut_violations(path):
    """Return fabricated pointer/touch input and inline layout overrides."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dispatch_event"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.lower() in E2E_SYNTHETIC_INPUT_EVENTS
        ):
            violations.append(
                f"{path}:{node.lineno} dispatches {node.args[0].value.lower()}"
            )

        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for pattern, description in (
            (E2E_SYNTHETIC_POINTER_DISPATCH, "dispatches synthetic pointer/touch input"),
            (E2E_INLINE_LAYOUT_ASSIGNMENT, "assigns inline layout width"),
        ):
            for match in pattern.finditer(node.value):
                line = node.lineno + node.value[: match.start()].count("\n")
                violations.append(f"{path}:{line} {description}")

    return violations


def _e2e_browser_storage_violations(path):
    """Return direct Web Storage references from E2E browser scripts."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for match in E2E_BROWSER_STORAGE_ACCESS.finditer(node.value):
            line = node.lineno + node.value[: match.start()].count("\n")
            violations.append(
                f"{path}:{line} references {match.group(0)} directly"
            )

    return violations


def _e2e_wait_shortcut_violations(path):
    """Return fixed Python polling and fabricated lifecycle events."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                target = child.func
                name = (
                    target.id
                    if isinstance(target, ast.Name)
                    else target.attr
                    if isinstance(target, ast.Attribute)
                    else None
                )
                if name in {"sleep", "wait_for_timeout"}:
                    violations.append(
                        f"{path}:{child.lineno} polls in Python with {name}"
                    )

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dispatch_event"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.lower() in E2E_SYNTHETIC_LIFECYCLE_EVENTS
        ):
            violations.append(
                f"{path}:{node.lineno} dispatches synthetic "
                f"{node.args[0].value.lower()} lifecycle event"
            )

        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for match in E2E_SYNTHETIC_LIFECYCLE_DISPATCH.finditer(node.value):
            line = node.lineno + node.value[: match.start()].count("\n")
            violations.append(
                f"{path}:{line} dispatches synthetic browser lifecycle event"
            )

    return violations


def _is_locator_expression(node, locator_names):
    if _attribute_name(node) in locator_names:
        return True
    if isinstance(node, ast.Attribute):
        return node.attr in {"first", "last"} and _is_locator_expression(
            node.value, locator_names
        )
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    return node.func.attr in E2E_LOCATOR_FACTORIES or (
        node.func.attr in {"filter", "nth"}
        and _is_locator_expression(node.func.value, locator_names)
    )


def _locator_names(scope):
    names = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(scope):
            if isinstance(node, (ast.For, ast.AsyncFor)):
                is_locator = (
                    isinstance(node.iter, ast.Call)
                    and isinstance(node.iter.func, ast.Attribute)
                    and node.iter.func.attr == "all"
                    and _is_locator_expression(node.iter.func.value, names)
                )
                targets = [node.target]
            elif isinstance(node, ast.Assign):
                is_locator = _is_locator_expression(node.value, names)
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                is_locator = _is_locator_expression(node.value, names)
                targets = [node.target]
            else:
                continue
            if not is_locator:
                continue
            for target in targets:
                name = _attribute_name(target)
                if name is not None and name not in names:
                    names.add(name)
                    changed = True
    return names


def _browser_snapshot_method(node, locator_names):
    """Return the raw locator getter name represented by one call, if any."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if (
        node.func.attr in E2E_NONRETRYING_BROWSER_GETTERS | {"count"}
        and _is_locator_expression(node.func.value, locator_names)
        and (node.func.attr != "count" or (not node.args and not node.keywords))
    ):
        return node.func.attr
    return None


def _asserts_snapshot_name(node, names):
    """Whether an assertion directly checks a value read from a locator."""
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.BoolOp):
        return any(_asserts_snapshot_name(value, names) for value in node.values)
    if isinstance(node, ast.Compare):
        # A raw attribute on the left is the assertion subject. A raw value on
        # the right is commonly a settled identifier expected in a response.
        return _asserts_snapshot_name(node.left, names)
    if isinstance(node, ast.UnaryOp):
        return _asserts_snapshot_name(node.operand, names)
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        return _asserts_snapshot_name(node.value, names)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return _asserts_snapshot_name(node.func.value, names)
        if isinstance(node.func, ast.Name) and node.func.id in {"bool", "len"}:
            return any(_asserts_snapshot_name(arg, names) for arg in node.args)
    return False


def _e2e_nonretrying_assertion_violations(path):
    """Return assertion-shaped locator snapshots that should use expect()."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []

    for scope in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        locator_names = _locator_names(scope)
        for node in ast.walk(scope):
            if isinstance(node, ast.Assert):
                for child in ast.walk(node.test):
                    if method := _browser_snapshot_method(child, locator_names):
                        violations.append(
                            f"{path}:{child.lineno} asserts raw {method}() snapshot"
                        )

            if (
                isinstance(node, (ast.For, ast.AsyncFor))
                and isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Attribute)
                and node.iter.func.attr == "all"
                and _is_locator_expression(node.iter.func.value, locator_names)
            ):
                violations.append(f"{path}:{node.iter.lineno} iterates locator.all()")

            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "range"
            ):
                continue
            for child in ast.walk(node):
                if _browser_snapshot_method(child, locator_names) == "count":
                    violations.append(
                        f"{path}:{child.lineno} enumerates range(locator.count())"
                    )

        snapshot_assignments = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            method = _browser_snapshot_method(value, locator_names)
            if method is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    snapshot_assignments[target.id] = (method, value.lineno)

        if not snapshot_assignments:
            continue
        for assertion in (
            node for node in ast.walk(scope) if isinstance(node, ast.Assert)
        ):
            checked_names = {
                name
                for name in snapshot_assignments
                if _asserts_snapshot_name(assertion.test, {name})
            }
            for name in sorted(checked_names):
                method, assignment_line = snapshot_assignments[name]
                violations.append(
                    f"{path}:{assertion.lineno} asserts {name} from raw "
                    f"{method}() on line {assignment_line}"
                )

    return violations


def _runs_node(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    subprocess_modules = {"subprocess"}
    subprocess_calls = set()
    shutil_modules = {"shutil"}
    shutil_which_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    subprocess_modules.add(alias.asname or alias.name)
                elif alias.name == "shutil":
                    shutil_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                subprocess_calls.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name
                    in {"call", "check_call", "check_output", "Popen", "run"}
                )
            elif node.module == "shutil":
                shutil_which_calls.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "which"
                )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in shutil_modules
            and node.func.attr == "which"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "node"
        ):
            return True
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in shutil_which_calls
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "node"
        ):
            return True

        is_subprocess_call = (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in subprocess_modules
            and node.func.attr
            in {"call", "check_call", "check_output", "Popen", "run"}
        ) or (
            isinstance(node.func, ast.Name) and node.func.id in subprocess_calls
        )
        if not is_subprocess_call:
            continue
        command = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "args"),
            None,
        )
        if not isinstance(command, (ast.List, ast.Tuple)) or not command.elts:
            continue
        executable = command.elts[0]
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


def _route_entity_fetch_violations(path):
    """Return route access that bypasses an explicit entity fetch request."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if _entities_call(node, "load"):
            violations.append(f"{path}:{node.lineno} uses Entities.load")
        elif (
            _entities_call(node, "fetch") or _entities_call(node, "fetch_one")
        ) and not any(keyword.arg == "request" for keyword in node.keywords):
            violations.append(
                f"{path}:{node.lineno} uses {node.func.attr} without request=Fetch..."
            )
        elif _entities_call(node, "get") and any(
            keyword.arg == "load"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        ):
            violations.append(f"{path}:{node.lineno} uses Entities.get(load=True)")
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _uses_injected_entity(node)
            and not _has_permission_decorator(node)
        ):
            violations.append(
                f"{path}:{node.lineno} uses kwargs['entity'] without @permission"
            )
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and (keyword := _permission_decorator_fetch_keyword(node)) is not None
        ):
            violations.append(
                f"{path}:{keyword.value.lineno} passes fetch to @permission"
            )

    return violations


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


def test_suite_import_and_node_guards_recognize_real_syntax(tmp_path):
    imports = tmp_path / "test_imports.py"
    imports.write_text(
        "import lagniappe.web.routes as routes\n"
        "from lagniappe import web as application_web\n"
        "import lagniappe\n"
        "WEB_PACKAGE = 'lagniappe.web'\n"
    )

    assert _package_imports(imports, "lagniappe.web") == [
        "lagniappe.web.routes",
        "lagniappe.web",
    ]

    direct_node = tmp_path / "test_direct_node.py"
    for source in (
        "import subprocess as process\nprocess.run(args=['node', 'case.mjs'])\n",
        "from subprocess import run as execute\nexecute(['node', 'case.mjs'])\n",
        "import shutil as files\nfiles.which('node')\n",
        "from shutil import which as find_executable\nfind_executable('node')\n",
    ):
        direct_node.write_text(source)
        assert _runs_node(direct_node) is True, source
    harmless = tmp_path / "test_harmless_commands.py"
    harmless.write_text(
        "import subprocess\n"
        "import shutil\n"
        "subprocess.run(['npm', 'run', 'build'])\n"
        "shutil.which('python')\n"
    )

    assert _runs_node(harmless) is False


def test_e2e_support_does_not_clear_user_cache_invalidation_out_of_band():
    """Only the browser acknowledgement route may clear persisted invalidation."""
    violations = []
    for path in _python_files(*E2E_CACHE_CONTRACT_ROOTS):
        relative = path.relative_to(REPOSITORY_ROOT)
        violations.extend(
            violation.replace(str(path), str(relative), 1)
            for violation in _e2e_cache_invalidation_violations(path)
        )

    assert violations == []


def test_e2e_modules_do_not_cache_durable_setup_in_process_booleans():
    """Durable E2E preconditions must be checked against the living datastore."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        relative = path.relative_to(REPOSITORY_ROOT)
        violations.extend(
            violation.replace(str(path), str(relative), 1)
            for violation in _e2e_process_state_violations(path)
        )

    assert violations == []


def test_e2e_modules_do_not_replace_native_browser_fetch():
    """Endpoint failures and stubs belong at Playwright's routing boundary."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        relative = path.relative_to(REPOSITORY_ROOT)
        violations.extend(
            violation.replace(str(path), str(relative), 1)
            for violation in _e2e_native_fetch_violations(path)
        )

    assert violations == []


def test_e2e_state_and_fetch_guards_reject_bypasses_and_accept_live_checks(tmp_path):
    invalidation = tmp_path / "invalidation.py"
    invalidation.write_text(
        "def clear_cache_invalidation():\n"
        "    user.invalidate_cache = False\n"
        "    setattr(user, 'invalidate_cache', False)\n"
    )
    assert len(_e2e_cache_invalidation_violations(invalidation)) == 3

    durable_state = tmp_path / "durable_state.py"
    durable_state.write_text(
        "WORKSPACE_READY = False\n"
        "def check_live_state():\n"
        "    request_ready = False\n"
        "    return request_ready\n"
    )
    assert len(_e2e_process_state_violations(durable_state)) == 1

    native_fetch = tmp_path / "native_fetch.py"
    native_fetch.write_text(
        "page.evaluate(\"\"\"window\n"
        ".fetch = replacement\"\"\")\n"
        "page.evaluate(\"const original = window.fetch\")\n"
    )
    assert len(_e2e_native_fetch_violations(native_fetch)) == 1


def test_e2e_support_does_not_fabricate_pointer_input_or_layout_widths():
    """Touch gestures and responsive layout must use browser capabilities."""
    violations = []
    for path in _python_files(*E2E_BROWSER_INTERACTION_ROOTS):
        violations.extend(_e2e_interaction_shortcut_violations(path))

    assert violations == []


def test_e2e_support_does_not_access_browser_storage_directly():
    """Preference setup and persistence checks must use visible product behavior."""
    violations = []
    for path in _python_files(*E2E_BROWSER_INTERACTION_ROOTS):
        violations.extend(_e2e_browser_storage_violations(path))

    assert violations == []


def test_e2e_support_does_not_poll_in_python_or_dispatch_lifecycle_events():
    """Automated waits use browser conditions and native lifecycle triggers."""
    violations = []
    for path in _python_files(*E2E_BROWSER_INTERACTION_ROOTS):
        violations.extend(_e2e_wait_shortcut_violations(path))

    assert violations == []


def test_e2e_support_does_not_use_nonretrying_browser_assertions():
    """Browser outcomes use retrying locator expectations, not DOM snapshots."""
    violations = []
    for path in _python_files(*E2E_BROWSER_INTERACTION_ROOTS):
        violations.extend(_e2e_nonretrying_assertion_violations(path))

    assert violations == []


def test_e2e_browser_storage_guard_rejects_white_box_access(tmp_path):
    path = tmp_path / "test_browser_storage.py"
    path.write_text(
        'page.evaluate("localStorage.removeItem(\'columns-tasks\')")\n'
        'page.wait_for_function("sessionStorage.getItem(\'sorts-tasks\')")\n'
    )

    violations = _e2e_browser_storage_violations(path)

    assert any("references localStorage directly" in item for item in violations)
    assert any("references sessionStorage directly" in item for item in violations)


def test_e2e_interaction_guard_rejects_synthetic_shortcuts(tmp_path):
    path = tmp_path / "test_interaction_shortcuts.py"
    path.write_text(
        'row.dispatch_event("pointerdown", {"pointerType": "touch"})\n'
        'page.evaluate("node => { node.style.maxWidth = \'8rem\'; }")\n'
        'page.evaluate("node => node.dispatchEvent('
        'new TouchEvent(\'touchstart\'))")\n'
    )

    violations = _e2e_interaction_shortcut_violations(path)

    assert any("dispatches pointerdown" in item for item in violations)
    assert any("assigns inline layout width" in item for item in violations)
    assert any(
        "dispatches synthetic pointer/touch input" in item for item in violations
    )


def test_e2e_wait_guard_rejects_python_polling_and_lifecycle_dispatch(tmp_path):
    path = tmp_path / "test_wait_shortcuts.py"
    path.write_text(
        "while not ready():\n"
        "    page.wait_for_timeout(100)\n"
        "    sleep(0.1)\n"
        'page.dispatch_event("focus")\n'
        'page.evaluate("window.dispatchEvent(new Event(\'online\'))")\n'
    )

    violations = _e2e_wait_shortcut_violations(path)

    assert any("polls in Python with wait_for_timeout" in item for item in violations)
    assert any("polls in Python with sleep" in item for item in violations)
    assert any("dispatches synthetic focus" in item for item in violations)
    assert any("synthetic browser lifecycle event" in item for item in violations)


def test_e2e_assertion_guard_rejects_locator_snapshots(tmp_path):
    path = tmp_path / "test_nonretrying_assertions.py"
    path.write_text(
        "def test_example():\n"
        "    links = modal.locator('a')\n"
        "    assert links.count() >= 4\n"
        "    for link in links.all():\n"
        "        assert link.inner_text()\n"
        "    href = links.first.get_attribute('href')\n"
        "    assert href and href.startswith('/pages/')\n"
        "    for index in range(links.count()):\n"
        "        visit(links.nth(index))\n"
    )

    violations = _e2e_nonretrying_assertion_violations(path)

    assert any("asserts raw count() snapshot" in item for item in violations)
    assert any("iterates locator.all()" in item for item in violations)
    assert any("asserts raw inner_text() snapshot" in item for item in violations)
    assert any("asserts href from raw get_attribute()" in item for item in violations)
    assert any("enumerates range(locator.count())" in item for item in violations)

    allowed = tmp_path / "test_identifier_extraction.py"
    allowed.write_text(
        "def test_example():\n"
        "    item = page.locator('[data-key]')\n"
        "    expect(item).to_have_attribute('data-key', NONEMPTY)\n"
        "    key = item.get_attribute('data-key')\n"
        "    entity = fetch(key)\n"
        "    assert entity is not None\n"
        "    assert records.count() == 2\n"
    )

    assert _e2e_nonretrying_assertion_violations(allowed) == []


def test_e2e_assertion_guard_tracks_locator_attributes(tmp_path):
    path = tmp_path / "test_locator_attribute.py"
    path.write_text(
        "def test_example(self):\n"
        "    self.links = page.locator('a')\n"
        "    links = self.links\n"
        "    assert links.count() == 2\n"
        "    assert self.links.first.inner_text() == 'Home'\n"
    )

    violations = _e2e_nonretrying_assertion_violations(path)

    assert any("asserts raw count() snapshot" in item for item in violations)
    assert any("asserts raw inner_text() snapshot" in item for item in violations)


def test_e2e_modules_do_not_import_or_bypass_route_functions():
    """E2E route claims must traverse the managed server and decorator stack."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        violations.extend(_e2e_route_bypass_violations(path))

    assert violations == []


@pytest.mark.parametrize(
    "import_statement, route",
    [
        ("from lagniappe.web.routes.home import site", "site.site_update"),
        ("from lagniappe.web.routes.home.site import site_update as handler", "handler"),
        ("from lagniappe.web import routes", "routes.home.site.site_update"),
        ("import lagniappe.web.routes.home.site", "lagniappe.web.routes.home.site.site_update"),
        ("import lagniappe.web.routes.home.site as site", "site.site_update"),
    ],
    ids=["from-module", "from-function-alias", "from-package", "qualified", "module-alias"],
)
def test_e2e_route_bypass_guard_rejects_synthetic_white_box_test(
    tmp_path, import_statement, route
):
    path = tmp_path / "test_route_bypass.py"
    path.write_text(
        f"{import_statement}\n"
        f"{route}()\n"
    )

    violations = _e2e_route_bypass_violations(path)

    assert any("calls imported route" in item for item in violations)

    path.write_text(f"{import_statement}\n{route}.__wrapped__()\n")
    violations = _e2e_route_bypass_violations(path)
    assert any("accesses route __wrapped__" in item for item in violations)

    patch_only = tmp_path / "test_route_boundary_patch.py"
    patch_only.write_text(
        "from lagniappe.web.routes.process import main as process_routes\n"
        "import lagniappe.web.routes.home.site\n"
        "monkeypatch.setattr(process_routes, 'Entities', fake_entities)\n"
        "client.post('/process/example')\n"
        "lagniappe.unrelated_helper()\n"
        "lagniappe.unrelated_helper.__wrapped__()\n"
    )

    assert _e2e_route_bypass_violations(patch_only) == []


def test_e2e_modules_do_not_bypass_durable_ai_workers():
    """Provider-backed E2E must enter through UI-created durable jobs."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        violations.extend(_e2e_ai_worker_bypass_violations(path))

    assert violations == []


def test_e2e_ai_worker_guard_rejects_synthetic_white_box_test(tmp_path):
    path = tmp_path / "test_ai_worker_bypass.py"
    path.write_text(
        "from lagniappe.core.tools.ai.core import ai_model as provider\n"
        "from lagniappe.core.tools.ai.organize import "
        "complete_organize_submissions as complete\n"
        "provider.generate_content(prompt)\n"
        "ask.complete_ask_report(report, owner)\n"
        "complete(proposal, report, owner)\n"
    )

    violations = _e2e_ai_worker_bypass_violations(path)

    assert any("calls ai_model.generate_content" in item for item in violations)
    assert any("calls complete_ask_report" in item for item in violations)
    assert any("calls complete_organize_submissions" in item for item in violations)


def test_web_routes_use_explicit_entity_fetch_boundaries():
    """Route code must not reintroduce identifier-dependent relation expansion."""
    violations = []
    for path in _python_files(ROUTES_ROOT):
        relative = path.relative_to(REPOSITORY_ROOT)
        violations.extend(
            violation.replace(str(path), str(relative), 1)
            for violation in _route_entity_fetch_violations(path)
        )

    assert violations == []


def test_route_fetch_guard_rejects_implicit_expansion_and_accepts_requests(tmp_path):
    prohibited = tmp_path / "prohibited.py"
    prohibited.write_text(
        "Entities.load(key)\n"
        "Entities.fetch(key)\n"
        "Entities.fetch_one(key)\n"
        "Entities.get(key, load=True)\n"
        "@permission(fetch=Fetch.ALL)\n"
        "def decorated(**kwargs):\n"
        "    return kwargs['entity']\n"
        "def undecorated(**kwargs):\n"
        "    return kwargs['entity']\n"
    )
    allowed = tmp_path / "allowed.py"
    allowed.write_text(
        "Entities.fetch(key, request=Fetch.RELATED)\n"
        "Entities.fetch_one(key, request=Fetch.RELATED)\n"
        "Entities.get(key, load=False)\n"
        "@permission\n"
        "def decorated(**kwargs):\n"
        "    return kwargs['entity']\n"
    )

    assert len(_route_entity_fetch_violations(prohibited)) == 6
    assert _route_entity_fetch_violations(allowed) == []
