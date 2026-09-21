"""Individual pytest items backed by the native Node test runner."""

from pathlib import Path
import subprocess

import pytest

from testing.utility import native_js


class JavaScriptFile(pytest.File):
    def collect(self):
        try:
            cases = native_js.inventory(self.path)["cases"]
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise self.CollectError(str(error)) from error
        if not cases:
            raise self.CollectError(f"{self.path} contains no literal node:test cases")
        for case in cases:
            item = JavaScriptItem.from_parent(self, name=case["name"], case=case)
            item.add_marker(pytest.mark.js)
            if case["status"] == "todo":
                item.add_marker(pytest.mark.unfinished)
            yield item


class JavaScriptItem(pytest.Item):
    def __init__(self, *, case, **kwargs):
        super().__init__(**kwargs)
        self.case = case

    def runtest(self):
        if self.case["status"] in {"skip", "todo"}:
            pytest.skip(f"node:test {self.case['status']}")
        result = native_js.run_case(Path(self.path), self.name)
        if result.get("skip") or result.get("todo"):
            pytest.skip(str(result.get("skip") or result.get("todo")))

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, native_js.JavaScriptFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.path, self.case["lineno"] - 1, self.name


def collect_file(parent, file_path):
    if file_path.suffix == ".mjs" and file_path.name.startswith("test_"):
        return JavaScriptFile.from_parent(parent, path=file_path)
    return None


def prepare_registries(item):
    """Shared by native items and legacy functions; never runs during collection."""
    if getattr(item.config, "_js_registries_ready", False):
        return
    result = subprocess.run(
        [native_js.node_binary(), "build/generate-registries.mjs"],
        cwd=native_js.REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        pytest.fail(
            f"Registry generation failed; run npm ci if dependencies are missing:\n{result.stdout}{result.stderr}"
        )
    item.config._js_registries_ready = True
