"""Release-readiness tests for setup diagnostics and operator output."""

import hashlib
import importlib.util
import json
from pathlib import Path
import types

import yaml

from installer import doctor, summary, verify


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _write_generation(root):
    documents = {
        "lagniappe.yaml": {
            "runtime": "python314",
            "service_account": (
                "runtime@demo-project.iam.gserviceaccount.com"
            ),
        },
        "config/files/lagniappe_settings.yaml": {
            "CONFIG_KIND": "lagniappe-settings",
            "CONFIG_SCHEMA_VERSION": 3,
            "APP_NAME": "Demo",
            "APP_URL": "https://demo.example.test",
            "GOOGLE_CLOUD_PROJECT": "demo-project",
            "INSTALLER_EMAIL": "installer@example.test",
            "DEPLOYER_EMAIL": "deployer@example.test",
            "ADMIN_EMAIL": "owner@example.test",
            "APP_ENGINE_LOCATION": "us-central",
            "RESOURCE_REGION": "us-central1",
            "OCR_LOCATION": "us",
            "TASK_QUEUE_NAME": "lagniappe-tasks",
            "GIBBERISH": "bucket-source-secret",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
                "runtime@demo-project.iam.gserviceaccount.com"
            ),
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                "runtime@demo-project.iam.gserviceaccount.com"
            ),
        },
        "config/files/lagniappe_dev.yaml": {
            "gcloud_config": {
                "NAME": "demo",
                "ACCOUNT": "deployer@example.test",
                "PROJECT": "demo-project",
            }
        },
        "package.json": {"name": "lagniappe", "version": "0.2"},
        "index.yaml": {"indexes": []},
        "lagniappe/web/static/manifest.json": {"name": "Demo"},
    }
    for relative, document in documents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            content = f"{json.dumps(document, sort_keys=True)}\n"
        else:
            content = yaml.safe_dump(document, sort_keys=True)
        path.write_text(content, encoding="utf-8")

    constants_path = root / doctor.GENERATION_SOURCE
    constants_path.parent.mkdir(parents=True, exist_ok=True)
    constants_path.write_text(
        'BUILD_ID = "b1111111"\nINDEX_YAML = {"indexes": []}\n',
        encoding="utf-8",
    )
    stable_constants = b'INDEX_YAML = {"indexes": []}\n'
    source_checksum = hashlib.sha256(stable_constants).hexdigest()

    generation = {
        "schema": 2,
        "source": {
            "path": doctor.GENERATION_SOURCE,
            "sha256": source_checksum,
        },
        "generation": source_checksum,
    }
    generation_path = root / doctor.GENERATION_MANIFEST
    generation_path.write_text(
        f"{json.dumps(generation, sort_keys=True)}\n",
        encoding="utf-8",
    )
    for relative in doctor.SECRET_FILES:
        (root / relative).chmod(0o600)


# @matrix setup : operator-summary secret-redaction
def test_redacted_install_summary_is_allowlisted():
    settings = {
        "APP_NAME": "Demo",
        "APP_URL": "https://demo.example.test",
        "GOOGLE_CLOUD_PROJECT": "demo-project",
        "INSTALLER_EMAIL": "installer@example.test",
        "DEPLOYER_EMAIL": "deployer@example.test",
        "ADMIN_EMAIL": "owner@example.test",
        "BOOTSTRAP_ADMIN_EMAIL": "installer@example.test",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "OCR_LOCATION": "us",
        "TASK_QUEUE_NAME": "lagniappe-tasks",
        "OCR_PROCESSOR_ID": "projects/demo/locations/us/processors/123",
        "REDIS_HOST": "redis.example.test",
        "REDIS_PORT": 6379,
        "REDIS_PASSWORD": "redis-secret",
        "GIBBERISH": "bucket-source-secret",
        "SECRET_KEY": "flask-secret",
        "SENTRY_DSN": "https://sentry-secret@example.test/1",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@demo-project.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@demo-project.iam.gserviceaccount.com"
        ),
    }

    lines = summary.install_summary_lines(
        settings,
        deploy={"runtime": "python314"},
        node={"version": "0.2"},
        gcloud_config={"NAME": "demo", "PROJECT": "demo-project"},
        deployed=True,
    )
    text = "\n".join(lines)

    assert "Demo" in text
    assert "Temporary application Administrator: installer@example.test" in text
    assert "runtime@demo-project.iam.gserviceaccount.com" in text
    assert "lagniappe-tasks" in text
    assert "python314" in text
    assert "Google sign-in: enabled" in text
    assert "Optional health check: ./setup.sh doctor" in text
    assert "Repair if needed: ./setup.sh repair" in text
    assert lines[-1] == (
        "Lagniappe has been installed successfully. "
        "Log in at https://demo.example.test"
    )
    for secret in (
        "bucket-source-secret",
        "redis-secret",
        "flask-secret",
        "sentry-secret",
    ):
        assert secret not in text

    manual_lines = summary.install_summary_lines(settings)
    assert manual_lines[-1] == "After manual deployment: ./setup.sh jobs"


# @matrix setup : adc doctor keyless-config project-identity
def test_doctor_reports_keyless_identity_drift():
    runtime_email = "runtime@demo-project.iam.gserviceaccount.com"
    assert doctor._keyless_identity_issues(
        {
            "CONFIG_KIND": "lagniappe-settings",
            # Settings YAML quotes environment-style scalar values.
            "CONFIG_SCHEMA_VERSION": "3",
            "GOOGLE_CLOUD_PROJECT": "demo-project",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": runtime_email,
        },
        {"service_account": runtime_email},
    ) == []
    issues = doctor._keyless_identity_issues(
        {
            "CONFIG_KIND": "lagniappe-settings",
            "CONFIG_SCHEMA_VERSION": 3,
            "GOOGLE_CLOUD_PROJECT": "demo-project",
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                "other@demo-project.iam.gserviceaccount.com"
            ),
        },
        {},
    )
    assert "RUNTIME_SERVICE_ACCOUNT_EMAIL is not configured" in issues


# @matrix setup : doctor drift independent-provider-check provider-identity read-only
def test_doctor_reports_drift_without_writing(tmp_path, capsys):
    _write_generation(tmp_path)
    active_values = {
        "configurations": "demo",
        "account": "deployer@example.test",
        "project": "demo-project",
    }

    def gcloud(command, check=False):
        key = (
            "configurations"
            if "configurations" in command
            else command[-1]
        )
        return types.SimpleNamespace(
            returncode=0,
            stdout=f"{active_values[key]}\n",
            stderr="",
        )

    provider_calls = []

    def adc():
        return {
            "state": "success",
            "principal": "deployer@example.test",
            "project": "demo-project",
            "quota_project": "demo-project",
        }

    def provider(settings, project):
        provider_calls.append((settings["APP_NAME"], project))
        return {
            "app-engine": {
                "state": "AVAILABLE",
                "details": {},
                "error": None,
            }
        }

    before = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mode)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert (
        doctor.run_doctor(
            root=tmp_path,
            gcloud_runner=gcloud,
            adc_checker=adc,
            provider_checker=provider,
        )
        == 0
    )
    assert provider_calls == [("Demo", "demo-project")]
    assert "Provider state: OK" in capsys.readouterr().out

    constants_path = tmp_path / doctor.GENERATION_SOURCE
    constants_path.write_text(
        'BUILD_ID = "b2222222"\nINDEX_YAML = {"indexes": [{"kind": "changed"}]}\n',
        encoding="utf-8",
    )
    drift_before = constants_path.read_bytes()
    provider_calls.clear()
    assert (
        doctor.run_doctor(
            root=tmp_path,
            gcloud_runner=gcloud,
            adc_checker=adc,
            provider_checker=provider,
        )
        == 1
    )
    assert provider_calls == [("Demo", "demo-project")]
    assert constants_path.read_bytes() == drift_before
    assert "Local generated state: DRIFT" in capsys.readouterr().out

    after = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mode)
        for path in tmp_path.rglob("*")
        if path.is_file() and path != constants_path
    }
    assert after == {
        relative: value
        for relative, value in before.items()
        if relative != Path(doctor.GENERATION_SOURCE)
    }


# @matrix setup : adc doctor provider-identity read-only
def test_doctor_reads_adc_identity_without_changing_it():
    events = []
    credentials = types.SimpleNamespace(
        service_account_email="adc@example.test",
        quota_project_id="demo-project",
    )

    def auth_default(scopes):
        events.append(tuple(scopes))
        return credentials, "demo-project"

    assert doctor._read_adc_identity(auth_default=auth_default) == {
        "state": "success",
        "principal": "adc@example.test",
        "project": "demo-project",
        "quota_project": "demo-project",
    }
    assert events and "userinfo.email" in events[0][1]


# @matrix setup : doctor operator-permissions project-identity provider-apis provider-discovery
def test_default_doctor_provider_checker_targets_saved_project(monkeypatch):
    calls = []

    def gcloud(command, check=False):
        calls.append((command, check))
        if command[:3] == ["services", "list", "--enabled"]:
            from config import constants

            return types.SimpleNamespace(
                returncode=0,
                stdout="\n".join(constants.REQUIRED_GOOGLE_CLOUD_APIS),
                stderr="",
            )
        return types.SimpleNamespace(
            returncode=0,
            stdout='{"projectNumber": "123456"}',
            stderr="",
        )

    def verify_resources(settings, project, project_details=None):
        calls.append((settings, project, project_details))
        return {"app-engine": {"state": "AVAILABLE"}}

    def inspect_permissions(project):
        calls.append(("permissions", project))
        return {"installer": [], "billing": [], "deployer": []}

    monkeypatch.setattr("installer.utils.run_gcloud_command", gcloud)
    monkeypatch.setattr(
        "installer.recovery.verify_recovery_resources",
        verify_resources,
    )
    monkeypatch.setattr(
        "installer.iam.inspect_operator_permissions",
        inspect_permissions,
    )

    settings = {"APP_NAME": "Demo"}
    assert doctor._default_provider_checker(settings, "demo-project") == {
        "app-engine": {"state": "AVAILABLE"},
        "operator-permissions": {
            "state": "AVAILABLE",
            "details": {"installer": [], "billing": [], "deployer": []},
            "error": None,
        },
        "required-apis": {
            "state": "AVAILABLE",
            "details": {"missing": []},
            "error": None,
        },
    }
    assert calls == [
        (
            [
                "projects",
                "describe",
                "demo-project",
                "--format=json",
            ],
            False,
        ),
        (settings, "demo-project", {"projectNumber": "123456"}),
        ("permissions", "demo-project"),
        (
            [
                "services",
                "list",
                "--enabled",
                "--project=demo-project",
                "--format=value(config.name)",
            ],
            False,
        ),
    ]


# @matrix setup : explicit-mutation repair validation
def test_repair_runs_reconciliation_then_validation(monkeypatch):
    events = []
    monkeypatch.setattr(
        "installer.install.install",
        lambda: events.append("reconcile") or 0,
    )
    monkeypatch.setattr(
        verify,
        "validate_installation",
        lambda: events.append("validate") or True,
    )

    assert verify.repair_installation() == 0
    assert events == ["reconcile", "validate"]


def test_doctor_cli_bypasses_mutating_setup_operation(monkeypatch):
    import installer as setup_package
    from installer import package_install
    from installer import state

    setup_path = REPOSITORY_ROOT / "installer" / "__main__.py"
    spec = importlib.util.spec_from_file_location("_doctor_setup_cli", setup_path)
    setup_cli = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(setup_cli)

    monkeypatch.setattr(setup_package, "verify_setup_runtime", lambda: None)
    monkeypatch.setattr(package_install, "ensure_pip_is_available", lambda: None)
    monkeypatch.setattr(package_install, "ensure_setup_dependencies", lambda: None)
    monkeypatch.setattr(doctor, "run_doctor", lambda: 0)
    monkeypatch.setattr(
        state,
        "setup_operation",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("doctor must not acquire the mutating operation journal")
        ),
    )

    assert setup_cli.main(["doctor"]) == 0
