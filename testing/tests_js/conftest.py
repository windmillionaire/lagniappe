"""Shared fixtures for Node-backed JavaScript behavior tests."""

from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_ROOT = Path(__file__).resolve().parent


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


@pytest.fixture
def run_node(node_binary):
    """Run an inline Node program from the repository root."""

    def run(script: str, *, module: bool = False, timeout: int = 30):
        command = [node_binary]
        if module:
            command.append("--input-type=module")
        command.extend(["-e", script])
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        return result

    return run
