"""Preserve JUnit results when one runner invocation uses two environments."""

from contextlib import contextmanager
from pathlib import Path
import os
import tempfile
from xml.etree import ElementTree

from .pytest_routing import PytestPartitions


# @testable false
# @covered-by runner/pytest_reports.py::partition_junit_reports
# @reason pytest's two JUnit option spellings share one partition boundary
def _without_junit(arguments):
    remaining = []
    destination = None
    arguments = iter(arguments)
    for argument in arguments:
        option, separator, value = argument.partition("=")
        if option in {"--junitxml", "--junit-xml"}:
            destination = value if separator else next(arguments)
        else:
            remaining.append(argument)
    return destination, remaining


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_merges_partition_junit
# @tests tests_tooling/test_007_run_py_test_command.py::test_partition_junit_reports_preserves_single_run_and_rejects_missing_results
# @matrix testing mcp-package : junit result-aggregation environment-isolation
@contextmanager
def partition_junit_reports(partitions):
    """Give each process a fresh XML path, then atomically publish their union."""
    if partitions.root_args is None or partitions.mcp_args is None:
        yield partitions
        return
    destination, root_args = _without_junit(partitions.root_args)
    if destination is None:
        yield partitions
        return
    _, mcp_args = _without_junit(partitions.mcp_args)
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".pytest-partitions-", dir=destination.parent
    ) as temporary:
        root_path = Path(temporary) / "root.xml"
        mcp_path = Path(temporary) / "mcp.xml"
        yield PytestPartitions(
            root_args=(*root_args, f"--junitxml={root_path}"),
            mcp_args=(*mcp_args, f"--junitxml={mcp_path}"),
        )
        combined = ElementTree.Element("testsuites")
        for path in (root_path, mcp_path):
            try:
                result = ElementTree.parse(path).getroot()
            except (OSError, ElementTree.ParseError) as error:
                raise RuntimeError(f"Missing or invalid partition JUnit: {path.name}") from error
            if result.tag == "testsuites":
                combined.extend(result)
            elif result.tag == "testsuite":
                combined.append(result)
            else:
                raise RuntimeError(f"Invalid partition JUnit root: {path.name}")
        merged = Path(temporary) / "merged.xml"
        ElementTree.ElementTree(combined).write(
            merged, encoding="utf-8", xml_declaration=True
        )
        os.replace(merged, destination)
