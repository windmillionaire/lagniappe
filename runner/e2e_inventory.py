"""Discover named resources and group collected E2E stories without app imports."""

import ast
import inspect
import json
import math
import os
from pathlib import Path
from statistics import median

from runner.e2e_parallel import Batch


ENUMS = frozenset({"Pages", "Tasks", "Projects", "Categories", "Forms", "Files",
                   "ModelTasks", "Users", "Groups"})


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_collection_preserves_group_and_serial_markers
# @matrix testing : parallel-e2e
def pytest_collection_finish(session):
    destination = os.environ.get("LAGNIAPPE_E2E_COLLECTION")
    if not destination:
        return
    root = Path(__file__).resolve().parents[1]
    records = []
    for item in session.items:
        fixtures = []
        for name in item.fixturenames:
            definitions = item._fixtureinfo.name2fixturedefs.get(name, ())
            if definitions:
                function = inspect.unwrap(definitions[-1].func)
                path = inspect.getsourcefile(function)
                if path and Path(path).is_relative_to(root):
                    fixtures.append([str(Path(path).relative_to(root)), function.__name__])
        marker = item.get_closest_marker("e2e_serial")
        phase = marker.kwargs.get("phase", "after") if marker else None
        if marker and phase not in {"before", "after"}:
            raise ValueError(f"Invalid e2e_serial phase for {item.nodeid}: {phase}")
        group_marker = item.get_closest_marker("e2e_group")
        group = None
        if group_marker:
            if (len(group_marker.args) != 1 or group_marker.kwargs
                    or not isinstance(group_marker.args[0], str) or not group_marker.args[0].strip()):
                raise ValueError(f"e2e_group requires one nonempty name for {item.nodeid}")
            group = group_marker.args[0]
        records.append({"nodeid": item.nodeid, "serial": bool(marker),
                        "serial_phase": phase, "group": group, "fixtures": fixtures})
    Path(destination).write_text(json.dumps(records), encoding="utf-8")


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_inventory_follows_helpers_constants_and_fixtures
# @matrix testing : parallel-e2e
def discover_resources(root, path, name, fixtures=(), *, modules=None):
    """Follow test helpers/constants and fixtures; no transitive entity graph."""
    visited, resources = set(), set()
    modules = {} if modules is None else modules

    def scan(relative, symbol):
        identity = (relative, symbol)
        if identity in visited:
            return
        visited.add(identity)
        if relative not in modules:
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                functions.update({f"{cls.name}::{n.name}": n for n in cls.body
                                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))})
            constants = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                         for t in n.targets if isinstance(t, ast.Name)}
            modules[relative] = tree, functions, constants
        tree, functions, constants = modules[relative]
        aliases, imports = {}, {}
        node = functions.get(symbol, constants.get(symbol))
        imports_to_scan = [*tree.body, *ast.walk(node)] if node is not None else tree.body
        for n in imports_to_scan:
            if isinstance(n, ast.ImportFrom) and n.module:
                if n.module.startswith("testing.definitions"):
                    aliases.update({a.asname or a.name: a.name for a in n.names if a.name in ENUMS})
                if n.module.startswith("testing."):
                    target = n.module.replace(".", "/") + ".py"
                    if (root / target).is_file():
                        imports.update({a.asname or a.name: (target, a.name) for a in n.names})
        node = functions.get(symbol, constants.get(symbol))
        if node is None:
            return
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                enum = aliases.get(child.value.id, child.value.id)
                if enum in ENUMS:
                    resources.add(f"{enum}.{child.attr}")
            elif isinstance(child, ast.Name) and child.id in constants:
                scan(relative, child.id)
            elif isinstance(child, ast.Name) and child.id in imports:
                scan(*imports[child.id])
            elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in functions:
                scan(relative, child.func.id)

    scan(path, name)
    for fixture_path, fixture_name in fixtures:
        scan(fixture_path, fixture_name)
    # Anonymous contexts have no shared user row or persisted settings.
    resources.discard("Users.ANONYMOUS")
    return frozenset(resources)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_inventory_balances_cases_without_transitive_resource_groups
# @tests tests_tooling/test_015_e2e_parallel.py::test_marked_groups_stay_on_one_worker_without_becoming_exclusive
# @matrix testing : parallel-e2e
def story_batches(root, records, *, workers=3, durations=None):
    """Place marked groups first, then balance cases; reserve resources per test."""
    if type(workers) is not int or workers < 1:
        raise ValueError("E2E workers must be a positive integer")
    durations = durations or {}
    fallback = median(durations.values()) if durations else 5.0
    ordinary, serial, before, inventory = [], [], [], []
    groups = {}
    modules = {}
    for record in records:
        nodeid = record["nodeid"].removeprefix("testing/")
        path, name = nodeid.split("::", 1)
        resources = discover_resources(root, "testing/" + path, name.split("[")[0], record["fixtures"], modules=modules)
        estimate = durations.get(nodeid, fallback)
        inventory.append({**record, "resources": sorted(resources), "estimated_seconds": estimate})
        if record["serial"]:
            (before if record.get("serial_phase") == "before" else serial).append((nodeid, resources))
            continue
        if record.get("group"):
            groups.setdefault(record["group"], []).append((nodeid, estimate))
        else:
            ordinary.append((nodeid, estimate))
    order = {record["nodeid"].removeprefix("testing/"): i for i, record in enumerate(records)}
    bins = [[] for _ in range(workers)]
    totals = [0.0] * workers
    units = sorted(groups.values(), key=lambda rows: -sum(estimate for _, estimate in rows))
    units.extend([(nodeid, estimate)] for nodeid, estimate in sorted(ordinary, key=lambda row: -row[1]))
    for unit in units:
        worker = min(range(workers), key=lambda i: (totals[i], len(bins[i]), i))
        bins[worker].append([nodeid for nodeid, _ in unit])
        totals[worker] += sum(estimate for _, estimate in unit)
    batches = []
    for i, units in enumerate(bins):
        if units:
            units.sort(key=lambda nodes: min(order[node] for node in nodes))
            selected = ["testing/" + node for nodes in units for node in nodes]
            batches.append(Batch(f"stories-{i + 1}", selected[0],
                                 additional_nodeids=tuple(selected[1:])))
    for name, group in (("stories-before", before), ("stories-serial", serial)):
        if group:
            selected = ["testing/" + node for node, _ in group]
            batch = Batch(name, selected[0], frozenset().union(*(resources for _, resources in group)),
                          exclusive=True, additional_nodeids=tuple(selected[1:]))
            if name == "stories-before":
                batches.insert(0, batch)
            else:
                batches.append(batch)
    return batches, inventory


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_duration_estimates_use_only_valid_passed_e2e_results
# @matrix testing : parallel-e2e
def duration_estimates(root):
    """Historical timings guide placement only; they never supply run outcomes."""
    hints = os.environ.get("LAGNIAPPE_E2E_DURATIONS")
    if hints:
        # The hosted image carries durations separately from prior test results.
        rows = {node: {"duration": duration, "outcome": "passed"}
                for node, duration in json.loads(Path(hints).read_text(encoding="utf-8")).items()}
    else:
        path = root / "testing/evidence/latest.json"
        if not path.is_file():
            return {}
        rows = json.loads(path.read_text(encoding="utf-8")).get("tests", {})
    return {node.removeprefix("testing/"): float(row["duration"])
            for node, row in rows.items()
            if node.removeprefix("testing/").startswith("tests_e2e/")
            and row.get("outcome") == "passed"
            and isinstance(row.get("duration"), (float, int))
            and not isinstance(row["duration"], bool)
            and math.isfinite(row["duration"]) and row["duration"] > 0}
