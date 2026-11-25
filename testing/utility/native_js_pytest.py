"""Individual pytest items backed by the native Node test runner."""

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import subprocess

import pytest

from testing.utility import native_js


class _JavaScriptSessionRunner:
    """Runs collected native JS files in parallel batches with isolated fallback."""

    def __init__(self, session: pytest.Session) -> None:
        self._cases_by_file: dict[Path, list[str]] = {}
        for item in session.items:
            if not isinstance(item, JavaScriptItem):
                continue
            if item.case["status"] in {"skip", "todo"}:
                continue
            resolved = Path(item.path).resolve()
            self._cases_by_file.setdefault(resolved, []).append(item.name)

        self._results: dict[Path, dict[str, native_js.CaseOutcome]] = {}
        self._futures: dict[Path, Future[dict[str, native_js.CaseOutcome]]] = {}
        self._executor: ThreadPoolExecutor | None = None

        maxfail = getattr(session.config.option, "maxfail", 0)
        workers = native_js.worker_count()
        if not maxfail and len(self._cases_by_file) > 1 and workers > 1:
            pool_size = min(workers, len(self._cases_by_file))
            self._executor = ThreadPoolExecutor(
                max_workers=pool_size, thread_name_prefix="native-js"
            )
            session.config.add_cleanup(self.close)
            for file_path, names in self._cases_by_file.items():
                self._futures[file_path] = self._executor.submit(
                    native_js.run_file_cases, file_path, names
                )

    def outcome(self, path: Path, name: str) -> native_js.CaseOutcome:
        resolved = path.resolve()
        file_results = self._results.get(resolved)
        if file_results is None:
            future = self._futures.pop(resolved, None)
            if future is not None:
                file_results = future.result()
            else:
                names = self._cases_by_file.get(resolved) or [name]
                file_results = native_js.run_file_cases(resolved, names)
            self._results[resolved] = file_results

        if name not in file_results:
            file_results.update(native_js.run_file_cases(resolved, [name]))
        return file_results[name]

    def close(self) -> None:
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def _session_runner(item: JavaScriptItem) -> _JavaScriptSessionRunner:
    runner = getattr(item.config, "_native_js_session_runner", None)
    if runner is None:
        runner = _JavaScriptSessionRunner(item.session)
        item.config._native_js_session_runner = runner
    return runner


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

    def setup(self):
        if self.case["status"] in {"skip", "todo"}:
            pytest.skip(f"node:test {self.case['status']}")
        outcome = _session_runner(self).outcome(Path(self.path), self.name)
        if isinstance(outcome, native_js.JavaScriptLaunchError):
            # A batch shares one launch error. Keep other items' pytest frames out of its traceback.
            raise outcome.with_traceback(None)
        self.result = outcome

    def runtest(self):
        if isinstance(self.result, native_js.JavaScriptFailure):
            raise self.result
        if self.result.get("skip") or self.result.get("todo"):
            pytest.skip(str(self.result.get("skip") or self.result.get("todo")))

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
