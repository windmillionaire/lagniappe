"""Tooling tests for the managed browser test-server command."""

from pathlib import Path
import importlib
import sys
import types

import pytest
import yaml

pytestmark = pytest.mark.tooling


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


def test_run_py_test_server_command_dispatches_start(monkeypatch, capsys):
    import run

    fake_config = types.ModuleType("config")
    fake_config.__path__ = []
    fake_config.SETTINGS = types.SimpleNamespace(
        test_config={"BASE_URL": "http://127.0.0.1:5000"}
    )
    fake_config_testing = types.ModuleType("runner.testing")
    fake_config_testing.start_managed_test_server = lambda: 2468

    def unexpected_teardown():
        raise AssertionError("teardown should not run for --start")

    fake_config_testing.teardown_managed_test_server = unexpected_teardown

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
    fake_config_testing.start_managed_test_server = lambda: (_ for _ in ()).throw(
        RuntimeError("Run python run.py auth and retry.")
    )
    fake_config_testing.teardown_managed_test_server = lambda: None

    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_config_testing)

    assert run.run_test_server_command(["--start"]) == 1
    output = capsys.readouterr().out
    assert "Test server command stopped:" in output
    assert "run.py auth" in output


def test_run_test_server_prepares_frontend_before_flask_launch(
    import_config_testing, monkeypatch, tmp_path
):
    testing = import_config_testing(make_demo_app(tmp_path))
    calls = []

    class FakeProcess:
        stdout = object()
        stderr = object()

        def poll(self):
            return None

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            calls.append(("thread", target, args, daemon))

        def start(self):
            calls.append("thread-start")

    monkeypatch.setattr(
        testing,
        "ensure_test_frontend_bundle",
        lambda: calls.append("frontend-bundle"),
    )
    monkeypatch.setattr(
        testing,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(("gcloud", kwargs)),
    )
    monkeypatch.setattr(
        testing,
        "_kill_existing_test_server",
        lambda base_url: calls.append(("kill", base_url)),
    )
    monkeypatch.setattr(
        testing,
        "_launch_test_server",
        lambda **kwargs: calls.append(("launch", kwargs)) or FakeProcess(),
    )
    monkeypatch.setattr(testing.threading, "Thread", FakeThread)
    monkeypatch.setattr(testing, "wait_for_server", lambda base_url: True)

    process = testing.run_test_server()

    assert isinstance(process, FakeProcess)
    assert calls[:4] == [
        "frontend-bundle",
        (
            "gcloud",
            {
                "ensure_adc": True,
                "allow_runtime_adc": True,
                "allow_adc_login": False,
            },
        ),
        ("kill", "http://127.0.0.1:5000"),
        (
            "launch",
            {"stdout": testing.subprocess.PIPE, "stderr": testing.subprocess.PIPE},
        ),
    ]


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
    fake_config_testing.start_managed_test_server = lambda: 2468
    fake_config_testing.teardown_managed_test_server = lambda: None

    fake_seed = types.ModuleType("testing.utility.test_server_seed")
    fake_seed.LOAD_REPORT = Path("reports/test-server-load.json")
    fake_seed.available_pack_names = lambda: ("project-review",)

    def fake_load_packs(packs):
        calls.append(("load", packs))
        return {
            "packs": packs,
            "resources": [{"ref": "Projects.test_filter_project"}],
            "landings": [
                {
                    "name": "Filter Project",
                    "url": "http://127.0.0.1:5000/projects/abc",
                }
            ],
        }

    fake_seed.load_packs = fake_load_packs

    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_config_testing)
    monkeypatch.setitem(sys.modules, "testing.utility.test_server_seed", fake_seed)
    monkeypatch.setattr(testing.utility, "test_server_seed", fake_seed, raising=False)

    assert run.run_test_server_command(["--start", "--load", "project-review"]) == 0

    output = capsys.readouterr().out
    assert calls == [("load", ["project-review"])]
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


def test_start_managed_test_server_detaches_and_records_pid(
    import_config_testing, monkeypatch, tmp_path
):
    testing = import_config_testing(make_demo_app(tmp_path))
    calls = []

    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        calls.append(("popen", command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(
        testing,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(
            (
                "gcloud",
                testing.SETTINGS.GCLOUD_CONFIG["NAME"],
                kwargs,
            )
        ),
    )
    monkeypatch.setattr(
        testing,
        "ensure_test_frontend_bundle",
        lambda: calls.append("frontend-bundle"),
    )
    monkeypatch.setattr(
        testing,
        "_kill_existing_test_server",
        lambda base_url: calls.append(("kill", base_url)),
    )
    monkeypatch.setattr(testing, "wait_for_server", lambda base_url: True)
    monkeypatch.setattr(testing.subprocess, "Popen", fake_popen)

    stale_failure = testing.Directory.TEST_FAILURES.value / "old.txt"
    stale_failure.parent.mkdir(parents=True)
    stale_failure.write_text("old")

    pid = testing.start_managed_test_server()

    assert pid == 4321
    assert calls[0] == "frontend-bundle"
    assert testing.File.MANAGED_TEST_SERVER_PID.value.read_text() == "4321\n"
    assert not stale_failure.exists()

    popen_call = next(call for call in calls if call[0] == "popen")
    _, command, kwargs = popen_call
    assert command[-2:] == ["--port", "5000"]
    assert kwargs["cwd"] == testing.APP_DIR
    assert kwargs["stderr"] == testing.subprocess.STDOUT
    assert kwargs["start_new_session"] is True
    assert kwargs["env"]["FLASK_ENV"] == "testing"
    assert kwargs["stdout"].name == str(testing.File.MANAGED_TEST_SERVER_LOG.value)


# @features test-server
# @dimensions teardown process-management
def test_teardown_managed_test_server_stops_before_cleaning(
    import_config_testing, monkeypatch, tmp_path
):
    testing = import_config_testing(make_demo_app(tmp_path))
    calls = []
    testing.Directory.REPORTS.create()
    testing.File.MANAGED_TEST_SERVER_PID.value.write_text("4321\n")

    monkeypatch.setattr(testing, "cleanup_test_data", lambda: calls.append("cleanup"))
    monkeypatch.setattr(
        testing,
        "_terminate_managed_test_server_pid",
        lambda pid: calls.append(("terminate", pid)),
    )
    monkeypatch.setattr(testing, "_server_port_in_use", lambda base_url: False)

    pid = testing.teardown_managed_test_server()

    assert pid == 4321
    assert calls == [("terminate", 4321), "cleanup"]
    assert not testing.File.MANAGED_TEST_SERVER_PID.value.exists()
