"""Tooling tests for the managed browser test-server command."""

from pathlib import Path
import importlib
import json
import sys
import types

import pytest
import yaml

pytestmark = pytest.mark.tooling


class FakeAuthority:
    nonce = "session-nonce-0123456789012345"
    mode = "local-e2e"

    def __init__(self):
        self.updates = []

    def assert_active(self, **_kwargs):
        return True

    def update(self, **changes):
        self.updates.append(changes)


@pytest.fixture
def import_config_testing(monkeypatch):
    from runner import context as runner_context

    original_config_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    original_runner_testing = sys.modules.pop("runner.testing", None)

    def fresh_import(app_dir: Path):
        for name in list(sys.modules):
            if name == "config" or name.startswith("config."):
                sys.modules.pop(name, None)
        sys.modules.pop("runner.testing", None)
        monkeypatch.setattr(runner_context, "REPOSITORY_ROOT", app_dir)
        monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(app_dir))
        monkeypatch.chdir(app_dir)
        return importlib.import_module("runner.testing")

    yield fresh_import

    for name in [
        name for name in sys.modules if name == "config" or name.startswith("config.")
    ]:
        sys.modules.pop(name, None)
    sys.modules.update(original_config_modules)
    sys.modules.pop("runner.testing", None)
    if original_runner_testing is not None:
        sys.modules["runner.testing"] = original_runner_testing


def make_demo_app(tmp_path: Path) -> Path:
    app_dir = tmp_path / "demo-app"
    config_files_dir = app_dir / "config" / "files"
    config_files_dir.mkdir(parents=True)

    (app_dir / "main.py").write_text("")
    (app_dir / "package.json").write_text("{}")
    (app_dir / "config" / "browser_protocol.json").write_text(
        '{"id": "demo", "version": 1}'
    )
    (app_dir / "index.yaml").write_text("indexes: []\n")
    (app_dir / "lagniappe.yaml").write_text("runtime: python312\n")
    (config_files_dir / "lagniappe_settings.yaml").write_text(
        yaml.safe_dump(
            {
                "APP_NAME": "Demo",
                "GIBBERISH": "secret",
                "AI_MODEL": "gemini-test",
                "AI_UTILITY_MODEL": "gemini-lite-test",
                "AI_IMAGE_MODEL": "imagen-test",
            }
        )
    )
    (config_files_dir / "lagniappe_dev.yaml").write_text(
        yaml.safe_dump(
            {
                "gcloud_config": {
                    "NAME": "demo",
                    "ACCOUNT": "owner@example.com",
                    "PROJECT": "project-1",
                },
                "dev_settings": {
                    "SERVER_NAME": "127.0.0.1",
                    "SERVER_PORT": "5050",
                },
                "test_settings": {
                    "SERVER_NAME": "127.0.0.1",
                    "SERVER_PORT": "5000",
                    "PREFIX": "test-",
                },
            }
        )
    )

    return app_dir


# @matrix frontend-build : freshness no-op
# @pair test-server:freshness
def test_test_frontend_bundle_skips_current_build(
    import_config_testing,
    monkeypatch,
    tmp_path,
):
    testing = import_config_testing(make_demo_app(tmp_path))
    state_path = tmp_path / "test-frontend-bundle.json"
    state = {"schema": 2, "inputs": "inputs-1", "outputs": "outputs-1"}
    state_path.write_text(json.dumps(state))

    monkeypatch.setattr(testing, "_TEST_FRONTEND_BUNDLE_STATE", state_path)
    monkeypatch.setattr(testing, "_test_frontend_input_fingerprint", lambda: "inputs-1")
    monkeypatch.setattr(
        testing,
        "_inspect_test_frontend_bundle",
        lambda **_kwargs: (
            types.SimpleNamespace(
                metadata={"mode": "development"},
                output_fingerprint="outputs-1",
            ),
            [],
        ),
    )
    monkeypatch.setattr(
        testing.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("fresh bundle must not invoke npm"),
    )

    assert testing.ensure_test_frontend_bundle(FakeAuthority()) is False


# @matrix frontend-build : freshness output-validation rebuild
# @pair test-server:freshness
def test_test_frontend_bundle_rebuilds_stale_build(
    import_config_testing,
    monkeypatch,
    tmp_path,
):
    testing = import_config_testing(make_demo_app(tmp_path))
    state_path = tmp_path / "test-frontend-bundle.json"
    calls = []
    output_fingerprints = iter(["outputs-old", "outputs-new"])

    monkeypatch.setattr(testing, "_TEST_FRONTEND_BUNDLE_STATE", state_path)
    monkeypatch.setattr(
        testing, "_test_frontend_input_fingerprint", lambda: "inputs-new"
    )
    monkeypatch.setattr(
        testing,
        "_inspect_test_frontend_bundle",
        lambda **_kwargs: (
            types.SimpleNamespace(
                metadata={"mode": "development"},
                output_fingerprint=next(output_fingerprints),
            ),
            [],
        ),
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(testing.subprocess, "run", fake_run)

    assert testing.ensure_test_frontend_bundle(FakeAuthority()) is True
    assert calls == [
        ([testing.NPM_CLI, "run", "dev"], {"cwd": testing.APP_DIR, "check": False})
    ]
    assert json.loads(state_path.read_text()) == {
        "schema": 2,
        "inputs": "inputs-new",
        "outputs": "outputs-new",
    }


# @matrix frontend-build : freshness no-op production-preservation
# @pair test-server:freshness
def test_test_frontend_bundle_preserves_current_production_build(
    import_config_testing,
    monkeypatch,
    tmp_path,
    capsys,
):
    testing = import_config_testing(make_demo_app(tmp_path))
    monkeypatch.setattr(
        testing,
        "_inspect_test_frontend_bundle",
        lambda **_kwargs: (
            types.SimpleNamespace(
                metadata={"mode": "production"},
                output_fingerprint="production-outputs",
            ),
            [],
        ),
    )
    monkeypatch.setattr(
        testing,
        "_test_frontend_input_fingerprint",
        lambda: pytest.fail("production bundle must bypass dev fingerprinting"),
    )
    monkeypatch.setattr(
        testing.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail(
            "production bundle must not invoke npm run dev"
        ),
    )

    assert testing.ensure_test_frontend_bundle(FakeAuthority()) is False
    assert "Current production frontend bundle detected" in capsys.readouterr().out


# @matrix frontend-build : freshness production-preservation rebuild
# @pair test-server:freshness
def test_test_frontend_bundle_replaces_stale_production_build(
    import_config_testing,
    monkeypatch,
    tmp_path,
):
    testing = import_config_testing(make_demo_app(tmp_path))
    state_path = tmp_path / "test-frontend-bundle.json"
    calls = []
    inspections = iter(
        [
            (None, ["Frontend build was created from different source inputs."]),
            (
                types.SimpleNamespace(
                    metadata={"mode": "development"},
                    output_fingerprint="development-outputs",
                ),
                [],
            ),
        ]
    )
    monkeypatch.setattr(testing, "_TEST_FRONTEND_BUNDLE_STATE", state_path)
    monkeypatch.setattr(
        testing, "_test_frontend_input_fingerprint", lambda: "inputs-new"
    )
    monkeypatch.setattr(
        testing,
        "_inspect_test_frontend_bundle",
        lambda **_kwargs: next(inspections),
    )
    monkeypatch.setattr(
        testing.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs)) or types.SimpleNamespace(returncode=0)
        ),
    )

    assert testing.ensure_test_frontend_bundle(FakeAuthority()) is True
    assert calls == [
        ([testing.NPM_CLI, "run", "dev"], {"cwd": testing.APP_DIR, "check": False})
    ]
    assert json.loads(state_path.read_text()) == {
        "schema": 2,
        "inputs": "inputs-new",
        "outputs": "development-outputs",
    }


def test_run_py_test_server_command_dispatches_start(monkeypatch, capsys):
    import run

    fake_config = types.ModuleType("config")
    fake_config.__path__ = []
    fake_config.SETTINGS = types.SimpleNamespace(
        test_config={"BASE_URL": "http://127.0.0.1:5000"}
    )
    fake_config_testing = types.ModuleType("runner.testing")
    fake_config_testing.start_managed_test_server = lambda packs: {
        "pid": 2468,
        "keeper_pid": 2467,
        "seed_summary": None,
    }

    def unexpected_teardown():
        raise AssertionError("teardown should not run for --start")

    fake_config_testing.teardown_managed_test_server = unexpected_teardown
    fake_config_testing.test_server_status = lambda: {}
    fake_config_testing.recover_managed_test_server = lambda: {}

    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_config_testing)

    assert run.run_test_server_command(["--start"]) == 0

    output = capsys.readouterr().out
    assert "http://127.0.0.1:5000" in output
    assert "2468" in output


def test_run_py_test_server_adc_mismatch_points_to_auth(monkeypatch, capsys):
    import run

    fake_config = types.ModuleType("config")
    fake_config.__path__ = []
    fake_config.SETTINGS = types.SimpleNamespace(
        test_config={"BASE_URL": "http://127.0.0.1:5000"}
    )
    fake_config_testing = types.ModuleType("runner.testing")
    fake_config_testing.start_managed_test_server = lambda packs: (_ for _ in ()).throw(
        RuntimeError("Run python run.py auth and retry.")
    )
    fake_config_testing.teardown_managed_test_server = lambda: None
    fake_config_testing.test_server_status = lambda: {}
    fake_config_testing.recover_managed_test_server = lambda: {}

    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_config_testing)

    assert run.run_test_server_command(["--start"]) == 1
    output = capsys.readouterr().out
    assert "Test server command stopped:" in output
    assert "run.py auth" in output


# @matrix test-session : health-nonce readiness slow-start
def test_wait_for_session_server_allows_slow_local_startup(
    import_config_testing, monkeypatch, tmp_path
):
    testing = import_config_testing(make_demo_app(tmp_path))
    import requests

    attempts = []
    sleeps = []
    now = [100.0]

    def delayed_ping(url, timeout):
        attempts.append((url, timeout))
        if len(attempts) <= 10:
            raise requests.ConnectionError("server still starting")
        return types.SimpleNamespace(
            status_code=200,
            json=lambda: {
                "ready": True,
                "mode": "local-e2e",
                "session_nonce": "nonce-1",
                "pid": 4321,
            },
        )

    def fake_sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr("requests.get", delayed_ping)
    monkeypatch.setattr(testing, "monotonic", lambda: now[0])
    monkeypatch.setattr(testing, "sleep", fake_sleep)

    assert testing.wait_for_session_server(
        "http://127.0.0.1:5000",
        "nonce-1",
        expected_pid=4321,
        expected_mode="local-e2e",
    ) is True
    assert len(attempts) == 11
    assert {url for url, _timeout in attempts} == {
        "http://127.0.0.1:5000/testing/health"
    }
    assert all(
        connect > 0 and read > 0 and connect + read <= 20
        for _url, (connect, read) in attempts
    )
    assert sleeps == [0.5] * 10


# @matrix test-session : deadline diagnostics readiness stalled-response
def test_wait_for_session_server_bounds_stalled_requests_by_one_deadline(
    import_config_testing, monkeypatch, tmp_path, capsys
):
    testing = import_config_testing(make_demo_app(tmp_path))
    import requests

    attempts = []
    now = [0.0]

    def stalled_ping(url, timeout):
        attempts.append((url, timeout))
        now[0] += sum(timeout)
        raise requests.ReadTimeout("listener did not answer")

    def fake_sleep(delay):
        now[0] += delay

    monkeypatch.setattr("requests.get", stalled_ping)
    monkeypatch.setattr(testing, "monotonic", lambda: now[0])
    monkeypatch.setattr(testing, "sleep", fake_sleep)

    assert testing.wait_for_session_server(
        "http://127.0.0.1:5000",
        "nonce-1",
        expected_pid=4321,
        expected_mode="local-e2e",
    ) is False
    assert now[0] <= 20.0
    assert attempts
    assert all(sum(timeout) <= 20.0 for _url, timeout in attempts)
    output = capsys.readouterr().out
    assert "timed out after 20s" in output
    assert "ReadTimeout" in output


# @matrix test-session : diagnostics http-state readiness
def test_wait_for_session_server_reports_last_http_state(
    import_config_testing, monkeypatch, tmp_path, capsys
):
    testing = import_config_testing(make_demo_app(tmp_path))
    now = [0.0]

    monkeypatch.setattr(
        "requests.get",
        lambda url, timeout: types.SimpleNamespace(status_code=503),
    )
    monkeypatch.setattr(testing, "monotonic", lambda: now[0])
    monkeypatch.setattr(testing, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))

    assert testing.wait_for_session_server(
        "http://127.0.0.1:5000",
        "nonce-1",
        expected_pid=4321,
        expected_mode="local-e2e",
        timeout_seconds=1,
    ) is False
    assert "last state: HTTP 503" in capsys.readouterr().out


def test_run_test_server_records_identity_and_requires_nonce_health(
    import_config_testing, monkeypatch, tmp_path
):
    testing = import_config_testing(make_demo_app(tmp_path))
    calls = []

    class FakeProcess:
        pid = 4321
        stdout = object()
        stderr = object()

        def poll(self):
            return None

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            calls.append(("thread", target, args, daemon))

        def start(self):
            calls.append("thread-start")

    monkeypatch.setattr(testing, "require_server_port_available", lambda url: calls.append(("port", url)))
    monkeypatch.setattr(
        testing,
        "_launch_test_server",
        lambda **kwargs: calls.append(("launch", kwargs)) or FakeProcess(),
    )
    from runner import test_session

    identity = {
        "pid": 4321,
        "pgid": 4321,
        "boot_id": "boot",
        "started": "started",
        "command_sha256": "hash",
    }
    monkeypatch.setattr(test_session, "capture_process_identity", lambda pid: identity)
    monkeypatch.setattr(testing.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        testing,
        "wait_for_session_server",
        lambda *args, **kwargs: calls.append(("health", args, kwargs)) or True,
    )

    authority = FakeAuthority()
    process = testing.run_test_server(authority)

    assert isinstance(process, FakeProcess)
    assert calls[:2] == [
        ("port", "http://127.0.0.1:5000"),
        (
            "launch",
            {
                "stdout": testing.subprocess.PIPE,
                "stderr": testing.subprocess.PIPE,
                "session_nonce": authority.nonce,
                "session_mode": authority.mode,
                "start_new_session": True,
            },
        ),
    ]
    assert authority.updates == [{"server": identity}]


def test_run_py_test_server_command_dispatches_start_load(monkeypatch, capsys):
    import run
    import testing.utility

    calls = []

    fake_config = types.ModuleType("config")
    fake_config.__path__ = []
    fake_config.SETTINGS = types.SimpleNamespace(
        test_config={"BASE_URL": "http://127.0.0.1:5000"}
    )
    fake_config_testing = types.ModuleType("runner.testing")
    def fake_start(packs):
        calls.append(("start", packs))
        return {
            "pid": 2468,
            "keeper_pid": 2467,
            "seed_summary": {
                "packs": packs,
                "resources": [{"ref": "Projects.test_filter_project"}],
                "landings": [
                    {
                        "name": "Filter Project",
                        "url": "http://127.0.0.1:5000/projects/abc",
                    }
                ],
            },
        }

    fake_config_testing.start_managed_test_server = fake_start
    fake_config_testing.teardown_managed_test_server = lambda: None
    fake_config_testing.test_server_status = lambda: {}
    fake_config_testing.recover_managed_test_server = lambda: {}

    fake_seed = types.ModuleType("testing.utility.test_server_seed")
    fake_seed.LOAD_REPORT = Path("reports/test-server-load.json")
    fake_seed.available_pack_names = lambda: ("project-review",)

    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_config_testing)
    monkeypatch.setitem(sys.modules, "testing.utility.test_server_seed", fake_seed)
    monkeypatch.setattr(testing.utility, "test_server_seed", fake_seed, raising=False)

    assert run.run_test_server_command(["--start", "--load", "project-review"]) == 0

    output = capsys.readouterr().out
    assert calls == [("start", ["project-review"])]
    assert "Loaded test-server seed pack(s): project-review (1 resources)" in output
    assert "Seed landing: Filter Project - http://127.0.0.1:5000/projects/abc" in output


def test_test_server_seed_static_site_page_landing_metadata():
    from config import File

    dev_settings = File.DEV_YAML.load().get("test_settings", {})
    if "SERVER_NAME" not in dev_settings:
        pytest.skip("test_settings in lagniappe_dev.yaml must define SERVER_NAME")

    from testing.definitions import SitePages
    from testing.utility import test_server_seed

    landing = SitePages.TASK_INDEX.get(None)

    assert (
        test_server_seed._resource_name(landing, SitePages.TASK_INDEX) == "Task Index"
    )
    assert (
        test_server_seed._resource_url(landing) == "http://127.0.0.1:5000/tasks/index"
    )
