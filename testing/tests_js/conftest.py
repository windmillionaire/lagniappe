"""Shared fixtures for Node-backed JavaScript behavior tests."""

from pathlib import Path
import shutil

import pytest

from testing.utility.native_js_pytest import collect_file, prepare_registries


SUITE_ROOT = Path(__file__).resolve().parent


def pytest_collect_file(parent, file_path):
    return collect_file(parent, file_path)


def pytest_runtest_setup(item):
    prepare_registries(item)


def pytest_collection_modifyitems(items):
    """Mark only tests collected from this directory as JavaScript tests."""
    for item in items:
        if Path(item.path).resolve().is_relative_to(SUITE_ROOT):
            item.add_marker(pytest.mark.js)


@pytest.fixture(scope="session")
def node_binary():
    """Return the Node executable or skip the JavaScript suite cleanly."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for JavaScript behavior tests")
    return node
