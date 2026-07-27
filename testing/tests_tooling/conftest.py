"""Tooling test safeguards."""

import builtins
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def setup_tests_do_not_touch_local_config_files(monkeypatch, request):
    """Fail setup tooling tests that open real config/files entries."""
    guarded_files = (
        request.node.path.name.startswith("test_001")
        or request.node.path.name == "test_003_config.py"
    )
    if not guarded_files:
        return

    config_files_dir = Path(__file__).resolve().parents[2] / "config" / "files"
    real_open = builtins.open
    real_path_open = Path.open

    def is_local_config_file(path):
        try:
            resolved = Path(path).resolve()
        except TypeError:
            return False
        return resolved.is_relative_to(config_files_dir)

    def guarded_open(file, *args, **kwargs):
        if is_local_config_file(file):
            raise AssertionError(f"setup tooling test touched local config file: {file}")
        return real_open(file, *args, **kwargs)

    def guarded_path_open(self, *args, **kwargs):
        if is_local_config_file(self):
            raise AssertionError(f"setup tooling test touched local config file: {self}")
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
