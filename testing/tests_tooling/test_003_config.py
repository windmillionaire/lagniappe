"""Tooling smoke tests for load-bearing config surfaces."""

import ast
import importlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import types

import pytest
import yaml

from runner import context as runner_context

pytestmark = pytest.mark.tooling


def _load_recovery_module(monkeypatch):
    """Load recovery contracts without executing runtime config file reads."""
    config_path = Path(__file__).resolve().parents[2] / "config"
    config_package = types.ModuleType("config")
    config_package.__path__ = [str(config_path)]
    monkeypatch.setitem(sys.modules, "config", config_package)
    monkeypatch.delitem(sys.modules, "config.recovery", raising=False)
    return importlib.import_module("config.recovery")


# @matrix config setup : permissions transactional-state utf8
def test_atomic_config_write_preserves_valid_file_and_restricts_secrets(
    monkeypatch,
    tmp_path,
):
    import config

    target = tmp_path / "lagniappe_settings.yaml"
    target.write_text("APP_NAME: Existing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        config._atomic_write_text(target, "", owner_only=True)
    assert target.read_text(encoding="utf-8") == "APP_NAME: Existing\n"

    original_replace = config.os.replace
    monkeypatch.setattr(
        config.os,
        "replace",
        lambda source, destination: (_ for _ in ()).throw(
            OSError("forced replace failure")
        ),
    )
    with pytest.raises(OSError, match="forced"):
        config._atomic_write_text(
            target,
            "APP_NAME: Replacement\n",
            owner_only=True,
        )
    assert target.read_text(encoding="utf-8") == "APP_NAME: Existing\n"
    assert not list(tmp_path.glob(".lagniappe_settings.yaml.*.tmp"))

    monkeypatch.setattr(config.os, "replace", original_replace)
    assert config._atomic_write_text(
        target,
        "APP_NAME: Replacement\n",
        owner_only=True,
    )
    assert target.read_bytes() == b"APP_NAME: Replacement\n"
    if config.os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


# @matrix config deploy setup : completeness generation source-marker
def test_generation_manifest_tracks_constants_and_required_outputs(
    monkeypatch,
    tmp_path,
):
    import config

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    first = app_dir / "first.yaml"
    second = app_dir / "second.json"
    constants = app_dir / "config" / "constants.py"
    constants.parent.mkdir()
    first.write_text("name: one\n", encoding="utf-8")
    second.write_text('{"name": "two"}\n', encoding="utf-8")
    constants.write_text(
        'BUILD_ID = "b1111111"\nINDEX_YAML = {"indexes": []}\n',
        encoding="utf-8",
    )

    class Ref:
        def __init__(self, value):
            self.value = value

        def exists(self):
            return self.value.exists()

    stored = {}

    class ManifestRef:
        def save(self, payload):
            stored.clear()
            stored.update(payload)
            return True

        def load(self):
            return dict(stored)

    monkeypatch.setattr(config, "APP_DIR", app_dir)
    monkeypatch.setattr(config, "GENERATION_FILES", (Ref(first), Ref(second)))
    monkeypatch.setattr(config, "GENERATION_SOURCE_FILE", constants)
    monkeypatch.setattr(
        config,
        "File",
        types.SimpleNamespace(GENERATION_JSON=ManifestRef()),
    )

    assert config.write_generation_manifest()
    assert config.verify_generation_manifest()

    first.write_text("name: locally changed\n", encoding="utf-8")
    assert config.verify_generation_manifest()

    constants.write_text(
        'BUILD_ID = "b2222222"\nINDEX_YAML = {"indexes": []}\n',
        encoding="utf-8",
    )
    assert config.verify_generation_manifest()

    constants.write_text(
        'BUILD_ID = "b2222222"\nINDEX_YAML = {"indexes": [{"kind": "new"}]}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="different constants generation"):
        config.verify_generation_manifest()

    constants.write_text(
        'BUILD_ID = "b1111111"\nINDEX_YAML = {"indexes": []}\n',
        encoding="utf-8",
    )
    second.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing or empty"):
        config.verify_generation_manifest()


def test_gcloudignore_uploads_only_canonical_runtime_config():
    ignore = (Path(__file__).resolve().parents[2] / ".gcloudignore").read_text(
        encoding="utf-8"
    )

    assert "/config/files/*" in ignore
    assert "!/config/files/lagniappe_settings.yaml" in ignore
    assert "!/config/files/redis_ca.pem" in ignore
    assert "/installer/" in ignore
    assert "/runner/" in ignore
    assert "/setup/" not in ignore
    assert "**/gha-creds-*.json" in ignore
    for local_only in (
        "lagniappe_dev.yaml",
        "lagniappe_generation.json",
        "google_oauth_credentials.json",
        "recovery",
        ".tmp",
        ".backup",
    ):
        assert f"!/config/files/{local_only}" not in ignore


# @matrix config setup : app-engine-location compatibility resource-region
def test_google_location_aliases_keep_app_engine_and_regional_resources_distinct():
    from config.locations import (
        normalize_app_engine_location,
        normalize_resource_region,
    )

    assert normalize_app_engine_location("us-central1") == "us-central"
    assert normalize_app_engine_location("us-central") == "us-central"
    assert normalize_resource_region("us-central") == "us-central1"
    assert normalize_resource_region("us-central1") == "us-central1"
    assert normalize_app_engine_location("europe-west1") == "europe-west"
    assert normalize_resource_region("europe-west") == "europe-west1"
    assert normalize_app_engine_location("asia-northeast1") == "asia-northeast1"
    assert normalize_resource_region("asia-northeast1") == "asia-northeast1"


def test_dependency_upgrade_tracks_all_requirement_files():
    from runner import upgrade

    assert [path.name for path in upgrade.REQUIREMENTS_PATHS] == [
        "requirements-installer.txt",
        "requirements.txt",
        "requirements-dev.txt",
    ]


# @pair dependencies:upgrade-requirements
def test_dependency_upgrade_resolves_and_rewrites_all_requirement_files(
    monkeypatch,
    tmp_path,
):
    from runner import upgrade

    setup_requirements = tmp_path / "requirements-installer.txt"
    runtime_requirements = tmp_path / "requirements.txt"
    dev_requirements = tmp_path / "requirements-dev.txt"
    setup_requirements.write_text("yaspin==3.4.0\n", encoding="utf-8")
    runtime_requirements.write_text("flask==3.1.2\n", encoding="utf-8")
    dev_requirements.write_text("ruff==0.15.21\n", encoding="utf-8")

    requirement_paths = (
        setup_requirements,
        runtime_requirements,
        dev_requirements,
    )
    monkeypatch.setattr(upgrade, "REQUIREMENTS_PATHS", requirement_paths)
    monkeypatch.setattr(
        upgrade,
        "collect_pip_installed_versions",
        lambda packages, report: {},
    )

    commands = []

    def resolve(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(upgrade, "run_command", resolve)

    report = upgrade.UpgradeReport()
    assert upgrade.upgrade_pip_packages(report)
    assert commands == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            "yaspin",
            "flask",
            "ruff",
        ]
    ]

    freeze = "\n".join(["yaspin==3.5.0", "Flask==3.1.3", "ruff==0.15.22"])
    monkeypatch.setattr(
        upgrade,
        "run_command",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            f"{freeze}\n",
            "",
        ),
    )

    assert upgrade.update_requirements_files(report)
    assert setup_requirements.read_text(encoding="utf-8") == "yaspin==3.5.0\n"
    assert runtime_requirements.read_text(encoding="utf-8") == "flask==3.1.3\n"
    assert dev_requirements.read_text(encoding="utf-8") == "ruff==0.15.22\n"


# @pair dependencies:upgrade-report
def test_dependency_upgrade_report_includes_setup_pins(capsys):
    from runner import upgrade

    report = upgrade.UpgradeReport()
    report.add_change(
        "pip",
        "yaspin",
        "3.4.0",
        "3.5.0",
        "requirements-installer.txt",
    )

    markdown = upgrade.render_upgrade_report(report)
    assert "requirements-installer.txt Pins" in markdown
    assert "yaspin" in markdown

    report_path = Path("reports/upgrade-test.md")
    upgrade.print_upgrade_summary(report, True, report_path)
    output = capsys.readouterr().out
    assert "pip packages" in output
    assert "yaspin" in output
    assert str(report_path) in output


# @matrix dependencies : node-version pinning upgrade
def test_dependency_upgrade_updates_node_version_pin(monkeypatch, tmp_path):
    from runner import upgrade

    responses = iter(
        [
            subprocess.CompletedProcess(["node", "--version"], 0, "v24.11.0\n", ""),
            subprocess.CompletedProcess(["which", "n"], 0, "/usr/local/bin/n\n", ""),
            subprocess.CompletedProcess(["sudo", "n", "lts"], 0, "", ""),
            subprocess.CompletedProcess(["node", "--version"], 0, "v26.5.0\n", ""),
        ]
    )
    pin_path = tmp_path / ".nvmrc"
    original_update_pin = upgrade.update_node_version_pin

    monkeypatch.setattr(upgrade.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(upgrade, "run_command", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(
        upgrade,
        "update_node_version_pin",
        lambda version, report: original_update_pin(version, report, pin_path),
    )

    report = upgrade.UpgradeReport()
    assert upgrade.upgrade_node(report)
    assert pin_path.read_text(encoding="utf-8") == "26.5.0\n"
    assert any(
        change.name == "Node.js pin" and change.after == "26.5.0"
        for change in report.changes
    )


# @matrix config : config-files parsing
def test_python_config_package_resolves_expected_repo_files(monkeypatch, tmp_path):
    app_dir = tmp_path / "demo-app"
    config_files_dir = app_dir / "config" / "files"
    config_files_dir.mkdir(parents=True)

    (app_dir / "main.py").write_text("")
    (app_dir / "package.json").write_text("{}")
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
                "BUILD_ID": "stale-local-build",
                "FIREBASE_CONFIG": '{"apiKey": "demo"}',
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

    original_config_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    for name in list(original_config_modules):
        sys.modules.pop(name, None)

    # Repository upgrades reload config after replacing the checkout, while an
    # old-generation runner.testing module may still be cached by Python.
    stale_testing = types.ModuleType("runner.testing")
    monkeypatch.setitem(sys.modules, "runner.testing", stale_testing)

    def restore_config_modules():
        for name in [
            name
            for name in sys.modules
            if name == "config" or name.startswith("config.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(original_config_modules)

    monkeypatch.setattr(runner_context, "REPOSITORY_ROOT", app_dir)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(app_dir))
    monkeypatch.chdir(app_dir)
    monkeypatch.setenv("FLASK_ENV", "testing")
    # monkeypatch.setenv("LAGNIAPPE_GCLOUD_CONFIGURED", "demo")

    try:
        from config import APP_DIR, Directory, Environment, File, SETTINGS, constants

        assert sys.modules["runner.testing"] is stale_testing
        assert APP_DIR == app_dir
        assert Directory.CONFIG.value == config_files_dir
        assert Environment.TESTING.value == "testing"

        for file_ref in [
            File.APP_YAML,
            File.DEV_YAML,
            File.APP_SETTINGS_YAML,
            File.INDEX_YAML,
            File.PACKAGE_JSON,
        ]:
            assert file_ref.exists(), file_ref.name

        assert SETTINGS.test_config["BASE_URL"].startswith("http://")
        assert SETTINGS.test_config["AGENT_ACCESS_ENABLED"] is True
        assert SETTINGS.test_config["EXTERNAL_AGENT_API_ENABLED"] is True
        assert SETTINGS.test_config["ANALYTICS"] is True
        assert SETTINGS.test_config["AI_OBSERVABILITY"] is True
        assert SETTINGS.test_config["PUBLIC_MANUAL"] is True
        assert "BUILD_ID" not in SETTINGS.app_config
        assert "BUILD_ID" not in SETTINGS.app_settings
        assert (
            SETTINGS.test_config["AGENT_ACCESS_CODE"]
            == constants.DEFAULT_AGENT_ACCESS_TEST_CODE
        )
        assert (
            SETTINGS.test_config["AGENT_ACCESS_EMAIL"]
            == constants.DEFAULT_AGENT_ACCESS_EMAIL
        )
        assert (
            SETTINGS.test_config["AGENT_ACCESS_NAME"]
            == constants.DEFAULT_AGENT_ACCESS_NAME
        )
        assert SETTINGS.GCLOUD_CONFIG["NAME"] == "demo"
        assert SETTINGS.GCLOUD_CONFIG["PROJECT"] == "project-1"
        assert SETTINGS.dev_config["SERVER_PORT"] == "5050"

        SETTINGS.TEST_CONFIG.update(
            {
                "AGENT_ACCESS_ENABLED": False,
                "EXTERNAL_AGENT_API_ENABLED": False,
                "AGENT_ACCESS_CODE": "custom-test-code",
                "AI_OBSERVABILITY": False,
            }
        )
        SETTINGS._TEST_SETTINGS = None

        assert SETTINGS.test_config["AGENT_ACCESS_ENABLED"] is False
        assert SETTINGS.test_config["EXTERNAL_AGENT_API_ENABLED"] is False
        assert SETTINGS.test_config["AGENT_ACCESS_CODE"] == "custom-test-code"
        assert SETTINGS.test_config["AI_OBSERVABILITY"] is False

        SETTINGS.APP["BUILD_ID"] = "stale-local-build"
        File.APP_SETTINGS_YAML.save(SETTINGS.APP)
        saved_settings = yaml.safe_load(
            (config_files_dir / "lagniappe_settings.yaml").read_text()
        )
        assert "BUILD_ID" not in saved_settings
    finally:
        restore_config_modules()


# @pairs cache:bundle-consistency frontend-build:chunk-versioning
def test_app_engine_chunk_handler_uses_immutable_cache_before_general_js():
    constants_path = Path(__file__).resolve().parents[2] / "config" / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "lagniappe_constants_under_test",
        constants_path,
    )
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)

    handlers = constants.APP_HANDLERS
    css_handler = next(
        handler for handler in handlers if handler.get("url") == "/(.*\\.css)$"
    )
    chunk_index = next(
        index
        for index, handler in enumerate(handlers)
        if handler.get("url") == "/chunks/(.*\\.js)$"
    )
    general_js_index = next(
        index
        for index, handler in enumerate(handlers)
        if handler.get("url") == "/(.*\\.m?js)$"
    )
    chunk_handler = handlers[chunk_index]

    assert css_handler["mime_type"] == "text/css; charset=utf-8"
    assert chunk_index < general_js_index
    assert chunk_handler["http_headers"]["Cache-Control"] == (
        "public, max-age=31536000, immutable"
    )
    assert "expiration" not in chunk_handler


# @matrix deploy : app-yaml pdf-preview static-assets
def test_app_engine_pdfjs_wasm_handlers_precede_general_js():
    constants_path = Path(__file__).resolve().parents[2] / "config" / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "lagniappe_constants_under_test",
        constants_path,
    )
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)

    handlers = constants.APP_HANDLERS
    wasm_handler = next(
        handler
        for handler in handlers
        if handler.get("url") == "/pdfjs/wasm/(.*\\.wasm)$"
    )
    pdfjs_index = next(
        index
        for index, handler in enumerate(handlers)
        if handler.get("url") == "/pdfjs/wasm/(.*\\.js)$"
    )
    general_js_index = next(
        index
        for index, handler in enumerate(handlers)
        if handler.get("url") == "/(.*\\.m?js)$"
    )
    general_js_handler = handlers[general_js_index]

    assert wasm_handler["mime_type"] == "application/wasm"
    assert pdfjs_index < general_js_index
    assert general_js_handler["mime_type"] == "text/javascript"
    assert re.fullmatch(general_js_handler["url"], "/pdf.worker.min.mjs")
    assert re.fullmatch(
        general_js_handler["upload"],
        "lagniappe/web/static/pdf.worker.min.mjs",
    )


def test_app_engine_dynamic_handler_allowlist_covers_registered_routes():
    repository_root = Path(__file__).resolve().parents[2]
    constants_path = repository_root / "config" / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "lagniappe_constants_under_test",
        constants_path,
    )
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)

    blueprint_tree = ast.parse(
        (repository_root / "lagniappe/web/start/blueprints.py").read_text()
    )
    blueprint_prefixes = {
        keyword.value.value.removeprefix("/").split("/", 1)[0]
        for node in ast.walk(blueprint_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_blueprint"
        for keyword in node.keywords
        if keyword.arg == "url_prefix"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    assert blueprint_prefixes == set(constants.APP_BLUEPRINT_ROUTE_PREFIXES)
    unprefixed_blueprints = {
        node.args[0].id
        for node in ast.walk(blueprint_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_blueprint"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and not any(keyword.arg == "url_prefix" for keyword in node.keywords)
    }
    assert unprefixed_blueprints == {"home"}

    root_prefixes = set()
    has_root_route = False
    for route_path in sorted(
        (repository_root / "lagniappe/web/routes/home").glob("*.py")
    ):
        route_tree = ast.parse(route_path.read_text())
        for node in ast.walk(route_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "home"
                    and decorator.func.attr == "route"
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)
                ):
                    continue
                route = decorator.args[0].value
                if route == "/":
                    has_root_route = True
                else:
                    root_prefixes.add(route.removeprefix("/").split("/", 1)[0])

    main_tree = ast.parse((repository_root / "main.py").read_text())
    root_prefixes.update(
        node.args[0].value.removeprefix("/").split("/", 1)[0]
        for node in ast.walk(main_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "app"
        and node.func.attr == "route"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )
    assert has_root_route
    assert root_prefixes == set(constants.APP_ROOT_ROUTE_PREFIXES)

    script_urls = [
        handler["url"]
        for handler in constants.APP_HANDLERS
        if handler.get("script") == "auto"
    ]
    assert script_urls == [
        *(
            f"/{prefix}(/.*)?$"
            for prefix in (
                *constants.APP_BLUEPRINT_ROUTE_PREFIXES,
                *constants.APP_ROOT_ROUTE_PREFIXES,
            )
        ),
        "/$",
    ]
    assert constants.APP_HANDLERS[-1] == {
        "url": "/(.*)$",
        "mime_type": "text/html; charset=utf-8",
        "secure": "always",
        "static_files": "lagniappe/web/static/404.html",
        "upload": "lagniappe/web/static/404.html",
        "expiration": "0s",
        "http_headers": {
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
        },
    }
    assert not (
        repository_root / "app_engine_404" / "handler-anchor.txt"
    ).exists()
    static_404_page = repository_root / "lagniappe/web/static/404.html"
    assert static_404_page.is_file()
    assert "That page was not found on this server." in static_404_page.read_text()


# @matrix deploy : deploy-surface gcloudignore imports requirements
def test_runtime_deploy_surface_flags_ignored_local_imports_and_missing_requirements(
    monkeypatch, tmp_path
):
    app_dir = tmp_path / "demo-app"
    config_files_dir = app_dir / "config" / "files"
    installer_dir = app_dir / "installer"
    runner_dir = app_dir / "runner"
    routes_dir = app_dir / "lagniappe" / "web" / "routes"
    testing_route_dir = routes_dir / "testing"
    config_files_dir.mkdir(parents=True)
    installer_dir.mkdir()
    runner_dir.mkdir()
    testing_route_dir.mkdir(parents=True)

    (app_dir / "main.py").write_text(
        "\n".join(
            [
                "import json",
                "import requests",
                "from flask import Flask",
                "from google.cloud import firestore_admin_v1",
                "from installer.deployment import normalize_deployment_settings",
                "from runner.context import REPOSITORY_ROOT",
            ]
        )
    )
    (installer_dir / "__init__.py").write_text("")
    (installer_dir / "deployment.py").write_text("")
    (runner_dir / "__init__.py").write_text("")
    (runner_dir / "context.py").write_text("")
    (routes_dir / "__init__.py").write_text("from .testing import testing\n")
    (testing_route_dir / "__init__.py").write_text("testing = object()\n")
    (app_dir / ".gcloudignore").write_text(
        "installer/\nrunner/\ntesting/\n.gcloudignore\n"
    )
    (app_dir / "requirements.txt").write_text(
        "flask==3.1.3\ngoogle-cloud-firestore==2.28.0\n"
    )
    (app_dir / "package.json").write_text(json.dumps({"version": "1.0"}))
    (app_dir / "index.yaml").write_text("indexes: []\n")
    (app_dir / "lagniappe.yaml").write_text("runtime: python314\n")
    (config_files_dir / "lagniappe_settings.yaml").write_text("{}\n")
    (config_files_dir / "lagniappe_dev.yaml").write_text(
        "gcloud_config: {}\ndev_settings: {}\ntest_settings: {}\n"
    )

    original_config_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    for name in list(original_config_modules):
        sys.modules.pop(name, None)
    original_runner_deploy = sys.modules.pop("runner.deploy", None)

    monkeypatch.setattr(runner_context, "REPOSITORY_ROOT", app_dir)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(app_dir))
    monkeypatch.chdir(app_dir)
    try:
        from runner.deploy import (
            runtime_deploy_surface_issues,
            verify_runtime_deploy_surface,
        )

        issues = runtime_deploy_surface_issues(app_dir)
        assert any("installer.deployment" in issue for issue in issues)
        assert any("runner.context" in issue for issue in issues)
        assert any("lagniappe.web.routes.testing" in issue for issue in issues)
        assert any("lagniappe/web/routes/testing/" in issue for issue in issues)
        assert any("excluded by .gcloudignore" in issue for issue in issues)
        assert any("imports 'requests'" in issue for issue in issues)
        assert not any("imports 'flask'" in issue for issue in issues)
        assert not any("firestore_admin_v1" in issue for issue in issues)

        with pytest.raises(RuntimeError, match="Runtime deploy surface check failed"):
            verify_runtime_deploy_surface(app_dir)

        (app_dir / ".gcloudignore").write_text(
            "/installer/\n/runner/\n/testing/\n.gcloudignore\n"
        )
        issues = runtime_deploy_surface_issues(app_dir)
        assert any("installer.deployment" in issue for issue in issues)
        assert any("runner.context" in issue for issue in issues)
        assert not any("lagniappe.web.routes.testing" in issue for issue in issues)
    finally:
        for name in [
            name
            for name in sys.modules
            if name == "config" or name.startswith("config.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(original_config_modules)
        sys.modules.pop("runner.deploy", None)
        if original_runner_deploy is not None:
            sys.modules["runner.deploy"] = original_runner_deploy

# @matrix deploy : deploy-surface gcloudignore imports package-boundary
def test_runtime_upload_boundary_has_no_local_orchestration_imports():
    from runner.deploy import runtime_deploy_surface_issues

    assert runtime_deploy_surface_issues(runner_context.REPOSITORY_ROOT) == []


# @matrix config : current-schema messaging-removal recovery-export
# @pair public-pages:recovery-export
def test_recovery_snapshot_is_complete_flat_and_merges_live_settings(monkeypatch):
    recovery = _load_recovery_module(monkeypatch)

    persisted = {
        "CONFIG_KIND": recovery.CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": str(recovery.CONFIG_SCHEMA_VERSION),
        "APP_NAME": "Custom Name",
        "GOOGLE_CLOUD_PROJECT": "custom-project-1",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@custom-project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@custom-project-1.iam.gserviceaccount.com"
        ),
        "SENTRY_AUTH_TOKEN": "sentry-secret",
        "DEPLOY_MAX_INSTANCES": "1",
        "AI_MODEL": "persisted-model",
        "BUILD_ID": "generated-build",
        "FIREBASE_CONFIG": {"apiKey": "retired"},
        "REDIS_TLS": False,
    }

    snapshot = recovery.build_recovery_snapshot(
        persisted,
        deployment_settings={
            "DEPLOY_MAX_INSTANCES": "3",
            "version": 8,
            "IGNORED": "not-owned",
        },
        ai_settings={
            "AI_MODEL": "live-model",
            "AI_LOCATION": "global",
            "version": 4,
        },
        public_page_settings={
            "PUBLIC_PAGE_INDEXING": True,
            "version": 2,
            "IGNORED_PUBLIC": "not-owned",
        },
    )

    assert snapshot["APP_NAME"] == "Custom Name"
    assert snapshot["RUNTIME_SERVICE_ACCOUNT_EMAIL"].startswith("runtime@")
    assert snapshot["SENTRY_AUTH_TOKEN"] == "sentry-secret"
    assert snapshot["DEPLOY_MAX_INSTANCES"] == "3"
    assert snapshot["AI_MODEL"] == "live-model"
    assert snapshot["AI_LOCATION"] == "global"
    assert snapshot["PUBLIC_PAGE_INDEXING"] is True
    assert snapshot["CONFIG_KIND"] == recovery.CONFIG_KIND
    assert snapshot["CONFIG_SCHEMA_VERSION"] == recovery.CONFIG_SCHEMA_VERSION
    assert snapshot["GOOGLE_SIGNIN_ENABLED"] is True
    assert snapshot["BOOTSTRAP_ADMIN_EMAIL"] == ""
    assert "BUILD_ID" not in snapshot
    assert "FIREBASE_CONFIG" not in snapshot
    assert "version" not in snapshot
    assert "IGNORED" not in snapshot
    assert "IGNORED_PUBLIC" not in snapshot
    assert persisted["DEPLOY_MAX_INSTANCES"] == "1"


# @matrix config : public-page-indexing validation
def test_public_page_settings_normalize_boolean_values():
    from config.public_pages import (
        ConfigPublicPageSettingsError,
        normalize_public_page_settings,
    )

    assert normalize_public_page_settings(
        {"PUBLIC_PAGE_INDEXING": "true"}
    ) == {"PUBLIC_PAGE_INDEXING": True}
    assert normalize_public_page_settings(
        {"PUBLIC_PAGE_INDEXING": "off"}
    ) == {"PUBLIC_PAGE_INDEXING": False}
    with pytest.raises(ConfigPublicPageSettingsError):
        normalize_public_page_settings({"PUBLIC_PAGE_INDEXING": "sometimes"})


# @matrix config : recovery-display secrets
def test_recovery_display_redacts_nested_and_flat_secrets_without_mutation():
    from config import recovery

    settings = {
        "APP_NAME": "Custom Name",
        "SECRET_KEY": "top-secret",
        "SENTRY_DSN": "https://secret@example.test/1",
        "AUTH_EMAIL_CONFIG": {"password": "smtp-secret"},
        "FIREBASE_CONFIG": json.dumps(
            {
                "apiKey": "firebase-secret",
                "projectId": "custom-project-1",
            }
        ),
        "REDIS_CA_PEM": "certificate-data",
    }

    displayed = recovery.redact_settings_for_display(settings)

    assert displayed["APP_NAME"] == "Custom Name"
    assert displayed["SECRET_KEY"] == recovery.REDACTED_VALUE
    assert displayed["SENTRY_DSN"] == recovery.REDACTED_VALUE
    assert displayed["AUTH_EMAIL_CONFIG"]["password"] == recovery.REDACTED_VALUE
    assert "firebase-secret" not in displayed["FIREBASE_CONFIG"]
    assert recovery.REDACTED_VALUE in displayed["FIREBASE_CONFIG"]
    assert displayed["REDIS_CA_PEM"] == recovery.REDACTED_VALUE
    assert settings["SECRET_KEY"] == "top-secret"
    assert settings["AUTH_EMAIL_CONFIG"]["password"] == "smtp-secret"


def _valid_recovery_document():
    from config import recovery

    return {
        "CONFIG_KIND": recovery.CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": recovery.CONFIG_SCHEMA_VERSION,
        "APP_NAME": "Recovered App",
        "ADMIN_EMAIL": "owner@example.com",
        "GOOGLE_CLOUD_PROJECT": "recovered-project-1",
        "GIBBERISH": "bucket-secret",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "OCR_LOCATION": "us",
        "APP_URL": "https://recovered-project-1.us-central1.r.appspot.com",
        "GOOGLE_LOGIN_URI": (
            "https://recovered-project-1.us-central1.r.appspot.com/users/google-signin"
        ),
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@recovered-project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@recovered-project-1.iam.gserviceaccount.com"
        ),
        "FIREBASE_CONFIG": json.dumps(
            {
                "apiKey": "firebase-api-key",
                "projectId": "recovered-project-1",
                "appId": "firebase-app-1",
                "messagingSenderId": "123456789",
                "vapidKey": "firebase-vapid-key",
            }
        ),
        "IDENTITY_PLATFORM_CONFIG": {
            "apiKey": "identity-api-key",
            "projectId": "recovered-project-1",
        },
        "AUTH_EMAIL_CONFIG": {
            "provider": "smtp",
            "service": "Resend",
            "host": "smtp.resend.com",
            "port": 465,
            "security": "ssl",
            "username": "resend",
            "password": "provider-key",
            "senderEmail": "noreply@example.com",
            "senderName": "Recovered App",
        },
        "OCR_PROCESSOR_ID": (
            "projects/recovered-project-1/locations/us/processors/processor-1"
        ),
    }


# @matrix config : project-identity project-number recovery-validation
def test_recovery_document_cross_checks_all_persisted_project_identities():
    from config import recovery

    recovered = recovery.validate_recovery_document(_valid_recovery_document())

    assert recovered["GOOGLE_CLOUD_PROJECT"] == "recovered-project-1"
    assert recovered["CONFIG_SCHEMA_VERSION"] == recovery.CONFIG_SCHEMA_VERSION
    assert recovered["GOOGLE_SIGNIN_ENABLED"] is True
    assert recovered["BOOTSTRAP_ADMIN_EMAIL"] == ""
    assert recovered["RUNTIME_SERVICE_ACCOUNT_EMAIL"].startswith("runtime@")
    assert "FIREBASE_CONFIG" not in recovered
    assert recovered["IDENTITY_PLATFORM_CONFIG"] == {
        "apiKey": "identity-api-key",
        "projectId": "recovered-project-1",
    }
    assert recovered["APP_ENGINE_LOCATION"] == "us-central"
    assert recovered["RESOURCE_REGION"] == "us-central1"
    assert recovered["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] == (
        "runtime@recovered-project-1.iam.gserviceaccount.com"
    )

    custom_domain = _valid_recovery_document()
    custom_domain["CUSTOM_DOMAIN"] = "lagniappe.example.com"
    custom_domain["GOOGLE_LOGIN_URI"] = (
        "https://lagniappe.example.com/users/google-signin"
    )
    assert recovery.validate_recovery_document(custom_domain)

    delegated = _valid_recovery_document()
    delegated["BOOTSTRAP_ADMIN_EMAIL"] = " Installer@Business.Example "
    assert recovery.validate_recovery_document(delegated)[
        "BOOTSTRAP_ADMIN_EMAIL"
    ] == "installer@business.example"

    google_disabled = _valid_recovery_document()
    google_disabled["GOOGLE_SIGNIN_ENABLED"] = False
    assert (
        recovery.validate_recovery_document(google_disabled)[
            "GOOGLE_SIGNIN_ENABLED"
        ]
        is False
    )

    numeric_ocr_parent = _valid_recovery_document()
    numeric_ocr_parent["OCR_PROCESSOR_ID"] = (
        "projects/552322920786/locations/us/processors/processor-1"
    )
    assert recovery.validate_recovery_document(numeric_ocr_parent)


# @matrix config : messaging-removal recovery-validation schema-upgrade
def test_recovery_upgrades_schema_2_and_discards_legacy_messaging_config(monkeypatch):
    recovery = _load_recovery_module(monkeypatch)

    document = _valid_recovery_document()
    document["CONFIG_SCHEMA_VERSION"] = 2

    recovered = recovery.validate_recovery_document(document)

    assert recovered["CONFIG_SCHEMA_VERSION"] == 3
    assert "FIREBASE_CONFIG" not in recovered


# @matrix config : current-schema recovery-validation required-settings
@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("CONFIG_SCHEMA_VERSION", "CONFIG_SCHEMA_VERSION"),
        ("APP_ENGINE_LOCATION", "APP_ENGINE_LOCATION"),
        ("RESOURCE_REGION", "RESOURCE_REGION"),
        ("RUNTIME_SERVICE_ACCOUNT_EMAIL", "RUNTIME_SERVICE_ACCOUNT_EMAIL"),
        (
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL",
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL",
        ),
        ("IDENTITY_PLATFORM_CONFIG", "IDENTITY_PLATFORM_CONFIG"),
        ("AUTH_EMAIL_CONFIG", "AUTH_EMAIL_CONFIG"),
    ],
)
def test_recovery_requires_complete_current_configuration(setting, message):
    from config import recovery

    document = _valid_recovery_document()
    document.pop(setting)

    with pytest.raises(recovery.RecoveryConfigurationError, match=message):
        recovery.validate_recovery_document(document)


# @matrix config : authentication-email recovery-validation secrets
def test_recovery_validates_and_normalizes_auth_email_smtp():
    from config import recovery

    snapshot = _valid_recovery_document()
    snapshot["AUTH_EMAIL_CONFIG"] = {
        "provider": "smtp",
        "service": "Resend",
        "host": "smtp.resend.com",
        "port": "465",
        "security": "SSL",
        "username": "resend",
        "password": "provider-key",
        "senderEmail": "noreply@example.com",
        "senderName": "Recovered App",
    }
    recovered = recovery.validate_recovery_document(snapshot)
    assert recovered["AUTH_EMAIL_CONFIG"]["service"] == "Resend"
    assert recovered["AUTH_EMAIL_CONFIG"]["port"] == 465
    assert recovered["AUTH_EMAIL_CONFIG"]["security"] == "ssl"

    snapshot["AUTH_EMAIL_CONFIG"]["security"] = "plaintext"
    with pytest.raises(recovery.RecoveryConfigurationError, match="AUTH_EMAIL_CONFIG"):
        recovery.validate_recovery_document(snapshot)


# @pair config:ai-email
def test_recovery_accepts_and_redacts_optional_ai_email_config():
    from config import recovery
    from config.ai_email import AI_EMAIL_LIMITS

    snapshot = _valid_recovery_document()
    snapshot["AI_EMAIL_CONFIG"] = {
        "version": 1,
        "provider": "resend",
        "enabled": False,
        "domain": "inbound.example.com",
        "aliases": {
            "ai": "ai",
            "ask": "ask",
            "create": "create",
            "organize": "organize",
        },
        "resend": {
            "domainId": "domain-1",
            "webhookId": "webhook-1",
            "webhookSecret": "whsec_secret",
            "inboundApiKey": "re_full",
            "sendingApiKey": "re_send",
            "senderEmail": "noreply@example.com",
            "senderName": "Lagniappe",
        },
        "limits": dict(AI_EMAIL_LIMITS),
    }

    recovered = recovery.validate_recovery_document(snapshot)
    displayed = recovery.redact_settings_for_display(recovered)

    assert recovered["AI_EMAIL_CONFIG"]["domain"] == "inbound.example.com"
    assert displayed["AI_EMAIL_CONFIG"]["resend"]["webhookSecret"] == "[REDACTED]"
    assert displayed["AI_EMAIL_CONFIG"]["resend"]["inboundApiKey"] == "[REDACTED]"
    assert displayed["AI_EMAIL_CONFIG"]["resend"]["sendingApiKey"] == "[REDACTED]"


# @matrix config : project-identity recovery-validation
def test_recovery_rejects_current_configuration_identity_mismatch():
    from config import recovery

    cases = [
        (
            lambda value: value.update(CONFIG_KIND="different-kind"),
            "CONFIG_KIND",
        ),
        (
            lambda value: value.update(GOOGLE_CLOUD_PROJECT="ambient-project-1"),
            "RUNTIME_SERVICE_ACCOUNT_EMAIL",
        ),
        (
            lambda value: value.update(
                RUNTIME_SERVICE_ACCOUNT_EMAIL=(
                    "runtime@wrong-project-1.iam.gserviceaccount.com"
                )
            ),
            "RUNTIME_SERVICE_ACCOUNT_EMAIL",
        ),
        (
            lambda value: value.update(
                IDENTITY_PLATFORM_CONFIG={
                    "apiKey": "identity-api-key",
                    "projectId": "wrong-project-1",
                }
            ),
            "IDENTITY_PLATFORM_CONFIG.projectId",
        ),
        (
            lambda value: value.update(APP_URL="https://wrong-project-1.appspot.com"),
            "APP_URL",
        ),
        (
            lambda value: value.update(
                OCR_PROCESSOR_ID=(
                    "projects/wrong-project-1/locations/us/processors/processor-1"
                )
            ),
            "OCR_PROCESSOR_ID",
        ),
        (
            lambda value: value.update(
                INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL=(
                    "other@recovered-project-1.iam.gserviceaccount.com"
                )
            ),
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL",
        ),
    ]
    for mutate, message in cases:
        document = _valid_recovery_document()
        mutate(document)

        with pytest.raises(recovery.RecoveryConfigurationError, match=message):
            recovery.validate_recovery_document(document)


# @matrix config : certificate-validation recovery-export recovery-restore redis-tls
def test_recovery_redis_ca_round_trips_through_one_file(monkeypatch, tmp_path):
    from config import recovery

    source_root = tmp_path / "source"
    source_ca = source_root / "config" / "files" / "redis_ca.pem"
    source_ca.parent.mkdir(parents=True)
    source_ca.write_text("-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----\n")

    validated = []

    def validate(path, *, app_dir=None):
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = Path(app_dir) / resolved
        assert resolved.is_file()
        validated.append(resolved)
        return resolved

    monkeypatch.setattr(recovery, "validate_redis_ca_cert", validate)
    settings = {
        "CONFIG_KIND": recovery.CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": recovery.CONFIG_SCHEMA_VERSION,
        "REDIS_TLS": True,
        "REDIS_CA_CERT": "config/files/redis_ca.pem",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": ("runtime@project-1.iam.gserviceaccount.com"),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
    }

    pem = recovery.read_recovery_redis_ca(settings, app_dir=source_root)
    snapshot = recovery.build_recovery_snapshot(settings, redis_ca_pem=pem)
    restore_root = tmp_path / "restore"
    target = recovery.materialize_recovery_redis_ca(
        snapshot,
        app_dir=restore_root,
    )

    assert snapshot["REDIS_CA_PEM"] == source_ca.read_text()
    assert snapshot["REDIS_CA_CERT"] == "config/files/redis_ca.pem"
    assert target == restore_root / "config" / "files" / "redis_ca.pem"
    assert target.read_text() == source_ca.read_text()
    assert validated[0] == source_ca
    assert len(validated) == 2
    assert validated[1].parent == target.parent


# @matrix config : certificate-validation redis-connection redis-tls settings
def test_redis_client_kwargs_support_verified_tls(monkeypatch, tmp_path):
    from config import redis as redis_config

    ca_bundle = tmp_path / "config" / "files" / "redis_ca.pem"
    ca_bundle.parent.mkdir(parents=True)
    ca_bundle.write_text("test CA bundle")
    validated = []
    monkeypatch.setattr(
        redis_config.ssl,
        "create_default_context",
        lambda **kwargs: validated.append(kwargs) or types.SimpleNamespace(),
    )

    plain = redis_config.redis_client_kwargs(
        {
            "REDIS_HOST": "redis.example.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": False,
        },
        app_dir=tmp_path,
        retry_on_timeout=True,
    )
    assert plain == {
        "host": "redis.example.com",
        "port": 12345,
        "password": "secret",
        "retry_on_timeout": True,
    }

    tls = redis_config.redis_client_kwargs(
        {
            "REDIS_HOST": "redis.example.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": "true",
            "REDIS_CA_CERT": "config/files/redis_ca.pem",
        },
        app_dir=tmp_path,
        socket_timeout=5,
    )
    assert tls == {
        "host": "redis.example.com",
        "port": 12345,
        "password": "secret",
        "socket_timeout": 5,
        "ssl": True,
        "ssl_ca_certs": str(ca_bundle),
        "ssl_cert_reqs": "required",
        "ssl_check_hostname": True,
    }
    assert validated == [{"cafile": str(ca_bundle)}]


# @matrix config : certificate-validation failure redis-tls
def test_redis_tls_requires_a_valid_ca_bundle(monkeypatch, tmp_path):
    from config import redis as redis_config

    settings = {
        "REDIS_HOST": "redis.example.com",
        "REDIS_PORT": 12345,
        "REDIS_PASSWORD": "secret",
        "REDIS_TLS": True,
        "REDIS_CA_CERT": "missing.pem",
    }
    with pytest.raises(redis_config.RedisTLSConfigurationError, match="not found"):
        redis_config.redis_client_kwargs(settings, app_dir=tmp_path)

    invalid = tmp_path / "invalid.pem"
    invalid.write_text("not a certificate")
    settings["REDIS_CA_CERT"] = str(invalid)
    monkeypatch.setattr(
        redis_config.ssl,
        "create_default_context",
        lambda **kwargs: (_ for _ in ()).throw(OSError("invalid")),
    )
    with pytest.raises(redis_config.RedisTLSConfigurationError, match="valid readable"):
        redis_config.redis_client_kwargs(settings, app_dir=tmp_path)

    settings["REDIS_TLS"] = "sometimes"
    with pytest.raises(redis_config.RedisTLSConfigurationError, match="boolean"):
        redis_config.redis_client_kwargs(settings, app_dir=tmp_path)


# @matrix deploy : package-lock transactional-state utf8 version
def test_deploy_version_update_keeps_package_lock_in_sync(monkeypatch, tmp_path):
    app_dir = tmp_path / "demo-app"
    config_files_dir = app_dir / "config" / "files"
    config_files_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text("")
    (app_dir / "package.json").write_text(json.dumps({"version": "1.23"}))
    (app_dir / "index.yaml").write_text("indexes: []\n")
    (app_dir / "lagniappe.yaml").write_text("runtime: python312\n")
    (config_files_dir / "lagniappe_settings.yaml").write_text("{}\n")
    (config_files_dir / "lagniappe_dev.yaml").write_text("{}\n")

    original_config_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    for name in list(original_config_modules):
        sys.modules.pop(name, None)
    original_runner_deploy = sys.modules.pop("runner.deploy", None)
    monkeypatch.setattr(runner_context, "REPOSITORY_ROOT", app_dir)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(app_dir))
    monkeypatch.chdir(app_dir)

    lock_path = app_dir / "package-lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "name": "lagniappe",
                "version": "1.23",
                "lockfileVersion": 3,
                "packages": {
                    "": {
                        "name": "lagniappe",
                        "version": "1.23",
                        "dependencies": {"example": "^1.0.0"},
                    },
                    "node_modules/example": {
                        "version": "1.0.0",
                        "funding": {"type": "GitHub Sponsors ❤"},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        from runner.deploy import update_package_lock_version

        assert update_package_lock_version("1.24")
    finally:
        for name in [
            name
            for name in sys.modules
            if name == "config" or name.startswith("config.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(original_config_modules)
        sys.modules.pop("runner.deploy", None)
        if original_runner_deploy is not None:
            sys.modules["runner.deploy"] = original_runner_deploy

    package_lock = json.loads(lock_path.read_text())
    assert package_lock["version"] == "1.24"
    assert package_lock["packages"][""]["version"] == "1.24"
    assert package_lock["packages"]["node_modules/example"]["version"] == "1.0.0"
    lock_text = lock_path.read_text(encoding="utf-8")
    assert "GitHub Sponsors ❤" in lock_text
    assert "\\u2764" not in lock_text


# @matrix deploy : app-yaml build capture-output explicit-project failure-output index-yaml progress version
def test_deploy_modes_separate_dev_build_from_setup_publish(
    monkeypatch,
    tmp_path,
    capsys,
):
    app_dir = tmp_path / "demo-app"
    config_files_dir = app_dir / "config" / "files"
    config_source_dir = app_dir / "config"
    chunks_dir = app_dir / "lagniappe" / "web" / "static" / "chunks"
    static_dir = app_dir / "lagniappe" / "web" / "static"
    config_files_dir.mkdir(parents=True)
    chunks_dir.mkdir(parents=True)
    static_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "main.py").write_text("")
    (app_dir / "requirements.txt").write_text("flask==3.1.3\n")
    (app_dir / "package.json").write_text(json.dumps({"version": "1.23"}))
    (app_dir / "index.yaml").write_text("indexes: []\n")
    (app_dir / "lagniappe.yaml").write_text("runtime: python314\n")
    (config_source_dir / "constants.py").write_text(
        'BUILD_ID = "b1111111"\nINDEX_YAML = {"indexes": []}\n',
        encoding="utf-8",
    )
    (static_dir / "manifest.json").write_text(
        json.dumps({"name": "Old", "short_name": "Old", "icons": []})
    )
    (config_files_dir / "lagniappe_settings.yaml").write_text(
        "APP_NAME: Demo\nVERSION: '1.23'\n"
    )
    (config_files_dir / "lagniappe_dev.yaml").write_text(
        "gcloud_config: {}\ndev_settings: {}\ntest_settings: {}\n"
    )
    (chunks_dir / "existing.js").write_text("console.log('built');\n")

    original_config_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    for name in list(original_config_modules):
        sys.modules.pop(name, None)
    original_runner_deploy = sys.modules.pop("runner.deploy", None)

    monkeypatch.setattr(runner_context, "REPOSITORY_ROOT", app_dir)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(app_dir))
    monkeypatch.chdir(app_dir)
    try:
        from config import SETTINGS
        from runner.deploy import deploy as deploy_app

        deploy_module = importlib.import_module("runner.deploy")
        SETTINGS.APP["GOOGLE_CLOUD_PROJECT"] = "demo-project"
        SETTINGS.save()

        commands = []
        preflight_snapshots = []
        build_versions = []
        frontend_verifications = []

        def fake_preflight(app_dir=None):
            preflight_snapshots.append(
                {
                    "version": SETTINGS.NODE["version"],
                    "chunk_exists": (chunks_dir / "existing.js").exists(),
                    "commands": list(commands),
                }
            )
            return True

        monkeypatch.setattr(
            deploy_module, "verify_runtime_deploy_surface", fake_preflight
        )
        monkeypatch.setattr(
            deploy_module,
            "verify_frontend_build",
            lambda **kwargs: frontend_verifications.append(kwargs) or True,
        )

        def fake_run_command(command, **kwargs):
            commands.append((command, kwargs))
            if command == [deploy_module.NPM_CLI, "run", "build"]:
                package_json = json.loads(
                    (app_dir / "package.json").read_text(encoding="utf-8")
                )
                build_versions.append(package_json["version"])
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(deploy_module, "run_command", fake_run_command)

        assert deploy_app(
            build_assets=False,
            deploy_indexes=True,
            quiet=True,
            capture_output=True,
            announce_progress=False,
        )
        assert capsys.readouterr().out == "Deployment complete!\n"
        assert preflight_snapshots == [
            {"version": "1.23", "chunk_exists": True, "commands": []}
        ]
        assert SETTINGS.NODE["version"] == "1.23"
        assert SETTINGS.APP["VERSION"] == "1.23"
        package_json = json.loads(
            (app_dir / "package.json").read_text(encoding="utf-8")
        )
        assert package_json["version"] == "1.23"
        assert (chunks_dir / "existing.js").exists()
        assert commands == [
            (
                [
                    deploy_module.GCLOUD_CLI,
                    "app",
                    "deploy",
                    str(app_dir / "index.yaml"),
                    "--quiet",
                    "--project",
                    "demo-project",
                ],
                {"check": False, "capture_output": True},
            ),
            (
                [
                    deploy_module.GCLOUD_CLI,
                    "app",
                    "deploy",
                    str(app_dir / "lagniappe.yaml"),
                    "--quiet",
                    "--project",
                    "demo-project",
                ],
                {"check": False, "capture_output": True},
            ),
        ]
        assert build_versions == []
        assert frontend_verifications == [
            {
                "app_dir": app_dir,
                "expected_mode": "production",
                "expected_version": "1.23",
            }
        ]

        commands.clear()
        preflight_snapshots.clear()
        frontend_verifications.clear()

        assert deploy_app()
        assert preflight_snapshots == [
            {"version": "1.23", "chunk_exists": True, "commands": []}
        ]
        assert SETTINGS.NODE["version"] == "1.23"
        assert SETTINGS.APP["VERSION"] == "1.23"
        assert build_versions == ["1.23"]
        assert chunks_dir.exists()
        assert frontend_verifications == [
            {
                "app_dir": app_dir,
                "expected_mode": "production",
                "expected_version": "1.23",
            }
        ]
        assert commands == [
            (
                [deploy_module.NPM_CLI, "run", "build"],
                {"check": True, "capture_output": False},
            ),
            (
                [
                    deploy_module.GCLOUD_CLI,
                    "app",
                    "deploy",
                    str(app_dir / "lagniappe.yaml"),
                    "--project",
                    "demo-project",
                ],
                {"check": False, "capture_output": False},
            ),
        ]

        def failed_deploy(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="provider permission denied",
            )

        monkeypatch.setattr(deploy_module, "run_command", failed_deploy)
        with pytest.raises(RuntimeError, match="provider permission denied"):
            deploy_app(
                build_assets=False,
                capture_output=True,
                announce_progress=False,
            )

        commands.clear()
        monkeypatch.setattr(
            deploy_module,
            "verify_frontend_build",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("Frontend build is incomplete or stale")
            ),
        )
        with pytest.raises(RuntimeError, match="Frontend build is incomplete"):
            deploy_app(build_assets=False)
        assert commands == []
    finally:
        for name in [
            name
            for name in sys.modules
            if name == "config" or name.startswith("config.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(original_config_modules)
        sys.modules.pop("runner.deploy", None)
        if original_runner_deploy is not None:
            sys.modules["runner.deploy"] = original_runner_deploy
