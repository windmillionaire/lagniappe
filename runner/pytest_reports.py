"""Preserve JUnit results when one runner invocation uses two environments."""

import os
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree

from .pytest_routing import PytestPartitions


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


@contextmanager
def partition_junit_reports(partitions: PytestPartitions) -> Iterator[PytestPartitions]:
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
        merge_junit_reports((root_path, mcp_path), destination)


def merge_junit_reports(paths: Iterable[Path], destination: Path) -> None:
    """Publish every phase's results, rejecting missing or malformed reports."""
    combined = ElementTree.Element("testsuites")
    for path in paths:
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
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pytest-junit-", dir=destination.parent) as temporary:
        merged = Path(temporary) / "merged.xml"
        ElementTree.ElementTree(combined).write(merged, encoding="utf-8", xml_declaration=True)
        os.replace(merged, destination)
