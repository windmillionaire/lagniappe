"""Discover named resources and group collected E2E stories without app imports."""

import ast
import inspect
import json
import os
from pathlib import Path

from runner.e2e_parallel import Batch


ENUMS = frozenset({"Pages", "Tasks", "Projects", "Categories", "Forms", "Files",
                   "ModelTasks", "Users", "Groups"})


# @testable infrastructure
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
        records.append({"nodeid": item.nodeid, "serial": bool(item.get_closest_marker("e2e_serial")),
                        "fixtures": fixtures})
    Path(destination).write_text(json.dumps(records), encoding="utf-8")


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_inventory_follows_helpers_constants_and_fixtures
# @matrix testing : parallel-e2e
def discover_resources(root, path, name, fixtures=()):
    """Follow local helper/constant references; no transitive entity graph."""
    visited, resources = set(), set()

    def scan(relative, symbol):
        identity = (relative, symbol)
        if identity in visited:
            return
        visited.add(identity)
        file = root / relative
        tree = ast.parse(file.read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        constants = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                     for t in n.targets if isinstance(t, ast.Name)}
        aliases = {}
        for n in tree.body:
            if isinstance(n, ast.ImportFrom) and n.module == "testing.definitions":
                aliases.update({a.asname or a.name: a.name for a in n.names if a.name in ENUMS})
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
            elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in functions:
                scan(relative, child.func.id)

    scan(path, name)
    for fixture_path, fixture_name in fixtures:
        scan(fixture_path, fixture_name)
    # Anonymous contexts have no shared user row or persisted settings.
    resources.discard("Users.ANONYMOUS")
    return frozenset(resources)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_inventory_groups_shared_resources_and_drains_serial_stories
# @matrix testing : parallel-e2e
def story_batches(root, records, *, workers=3):
    """Keep connected resource users sequential; balance components across workers."""
    groups, serial, inventory = [], [], []
    for record in records:
        nodeid = record["nodeid"].removeprefix("testing/")
        path, name = nodeid.split("::", 1)
        resources = discover_resources(root, "testing/" + path, name.split("[")[0], record["fixtures"])
        inventory.append({**record, "resources": sorted(resources)})
        if record["serial"]:
            serial.append((nodeid, resources))
            continue
        merged_nodes, merged_resources = [nodeid], set(resources)
        for group in list(groups):
            if merged_resources & group[1]:
                merged_nodes.extend(group[0])
                merged_resources.update(group[1])
                groups.remove(group)
        groups.append((merged_nodes, merged_resources))
    order = {record["nodeid"].removeprefix("testing/"): i for i, record in enumerate(records)}
    bins = [([], set()) for _ in range(workers)]
    for nodes, resources in sorted(groups, key=lambda group: -len(group[0])):
        assigned, held = min(bins, key=lambda group: len(group[0]))
        assigned.extend(nodes)
        held.update(resources)
    batches = []
    for i, (nodes, resources) in enumerate(bins):
        if nodes:
            nodes.sort(key=order.__getitem__)
            selected = ["testing/" + node for node in nodes]
            batches.append(Batch(f"stories-{i + 1}", selected[0], frozenset(resources),
                                 additional_nodeids=tuple(selected[1:])))
    if serial:
        selected = ["testing/" + node for node, _ in serial]
        batches.append(Batch("stories-serial", selected[0],
                             frozenset().union(*(resources for _, resources in serial)),
                             exclusive=True, additional_nodeids=tuple(selected[1:])))
    return batches, inventory
