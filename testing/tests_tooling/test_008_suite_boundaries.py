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


def _e2e_route_bypass_violations(path):
    """Return route imports and decorator bypasses in one E2E module."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "lagniappe.web.routes" or alias.name.startswith(
                    "lagniappe.web.routes."
                ):
                    violations.append(f"{path}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "lagniappe.web.routes" or module.startswith(
                "lagniappe.web.routes."
            ):
                violations.append(f"{path}:{node.lineno} imports {module}")
            elif module == "lagniappe.web" and any(
                alias.name == "routes" for alias in node.names
            ):
                violations.append(f"{path}:{node.lineno} imports lagniappe.web.routes")
        elif isinstance(node, ast.Attribute) and node.attr == "__wrapped__":
            violations.append(f"{path}:{node.lineno} accesses __wrapped__")
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


def _browser_snapshot_method(node):
    """Return the raw locator getter name represented by one call, if any."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr in E2E_NONRETRYING_BROWSER_GETTERS:
        return node.func.attr
    if node.func.attr == "count" and not node.args and not node.keywords:
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

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for child in ast.walk(node.test):
                if method := _browser_snapshot_method(child):
                    violations.append(
                        f"{path}:{child.lineno} asserts raw {method}() snapshot"
                    )

        if (
            isinstance(node, (ast.For, ast.AsyncFor))
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr == "all"
        ):
            violations.append(f"{path}:{node.iter.lineno} iterates locator.all()")

        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "range"
        ):
            continue
        for child in ast.walk(node):
            if _browser_snapshot_method(child) == "count":
                violations.append(
                    f"{path}:{child.lineno} enumerates range(locator.count())"
                )

    for scope in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
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
            method = _browser_snapshot_method(value)
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
            and node.func.attr
            in {
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

            if not (isinstance(value, ast.Constant) and isinstance(value.value, bool)):
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
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            for offset, line in enumerate(node.value.splitlines()):
                if E2E_NATIVE_FETCH_ASSIGNMENT.search(line):
                    violations.append(
                        f"{relative}:{node.lineno + offset} assigns native fetch"
                    )

    assert violations == []


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
        "    expect(item).to_have_attribute('data-key', NONEMPTY)\n"
        "    key = item.get_attribute('data-key')\n"
        "    entity = fetch(key)\n"
        "    assert entity is not None\n"
    )

    assert _e2e_nonretrying_assertion_violations(allowed) == []


def test_e2e_modules_do_not_import_or_bypass_route_functions():
    """E2E route claims must traverse the managed server and decorator stack."""
    violations = []
    for path in _python_files(TESTING_ROOT / "tests_e2e"):
        violations.extend(_e2e_route_bypass_violations(path))

    assert violations == []


def test_e2e_route_bypass_guard_rejects_synthetic_white_box_test(tmp_path):
    path = tmp_path / "test_route_bypass.py"
    path.write_text(
        "from lagniappe.web.routes.home import site\nsite.site_update.__wrapped__()\n"
    )

    violations = _e2e_route_bypass_violations(path)

    assert any("imports lagniappe.web.routes.home" in item for item in violations)
    assert any("accesses __wrapped__" in item for item in violations)


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
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(REPOSITORY_ROOT)
        for node in ast.walk(tree):
            if _entities_call(node, "load"):
                violations.append(f"{relative}:{node.lineno} uses Entities.load")
            elif (
                _entities_call(node, "fetch") or _entities_call(node, "fetch_one")
            ) and not any(keyword.arg == "request" for keyword in node.keywords):
                violations.append(
                    f"{relative}:{node.lineno} uses {node.func.attr} without request=Fetch..."
                )
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
