"""Tests for the Secret Manager runtime split, IAM provisioning, and doctor checks."""

from __future__ import annotations

import base64
import importlib
import json
import sys
from subprocess import CompletedProcess
from types import SimpleNamespace

import google_crc32c
import pytest
import yaml

from config import secrets as runtime_secrets
from config.recovery import RecoveryConfigurationError, validate_recovery_document
from installer import doctor, secrets as installer_secrets

pytestmark = pytest.mark.tooling


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Import config against an isolated disposable workspace root."""
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    for name in original_modules:
        sys.modules.pop(name)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(tmp_path))
    try:
        yield importlib.import_module("config")
    finally:
        for name in list(sys.modules):
            if name == "config" or name.startswith("config."):
                sys.modules.pop(name)
        sys.modules.update(original_modules)


def _sample_full_app_settings(backend: str = "secret_manager") -> dict[str, object]:
    return {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "GOOGLE_CLOUD_PROJECT": "pilot-project-1",
        "APP_NAME": "Pilot Workspace",
        "APP_URL": "https://pilot-project-1.uc.r.appspot.com",
        "GOOGLE_LOGIN_URI": "https://pilot-project-1.uc.r.appspot.com/users/google_login",
        "GOOGLE_SIGNIN_ENABLED": True,
        "ADMIN_EMAIL": "owner@example.com",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "OCR_LOCATION": "us",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": "lagniappe@pilot-project-1.iam.gserviceaccount.com",
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": "lagniappe@pilot-project-1.iam.gserviceaccount.com",
        "IDENTITY_PLATFORM_CONFIG": {
            "apiKey": "AIzaPublicWebKey",
            "projectId": "pilot-project-1",
        },
        "SECRETS_BACKEND": backend,
        "SECRETS_SECRET_NAME": "lagniappe-runtime-secrets",
        "SECRETS_VERSION": "current",
        "SECRET_KEY": "super-secret-flask-key",
        "GIBBERISH": "super-secret-gibberish",
        "AGENT_ACCESS_CODE": "super-secret-agent-code",
        "REDIS_HOST": "redis.example.test",
        "REDIS_PORT": 6379,
        "REDIS_PASSWORD": "super-secret-redis-pass",
        "REDIS_TLS": False,
        "SENTRY_DSN": "https://secret@o1.ingest.sentry.io/1",
        "SENTRY_JS_DSN": "https://public-browser@o1.ingest.sentry.io/2",
        "AUTH_EMAIL_CONFIG": {
            "provider": "smtp",
            "service": "Gmail",
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
            "username": "owner@example.com",
            "password": "super-secret-smtp-password",
            "senderEmail": "owner@example.com",
            "senderName": "Pilot Workspace",
        },
        "AI_EMAIL_CONFIG": {
            "provider": "resend",
            "enabled": True,
            "domain": "mail.example.com",
            "resend": {
                "domainId": "dom_123",
                "webhookId": "wh_123",
                "webhookSecret": "whsec_super_secret",
                "inboundApiKey": "re_inbound_secret",
                "sendingApiKey": "re_sending_secret",
                "senderEmail": "ai@mail.example.com",
                "senderName": "Pilot AI",
            },
        },
    }


class _FakeSecretSession:
    """In-memory Secret Manager REST simulator for SecretManagerRuntimeStore."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.versions: dict[str, bytes] = {}
        self.aliases: dict[str, str] = {}
        self.etag = "etag-1"
        self.next_version = 1
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, *, json=None, params=None, timeout=None, allow_redirects=True):
        assert allow_redirects is False
        self.calls.append((method, url))
        if method == "GET" and url.endswith(":access"):
            version = url.rsplit("/versions/", 1)[1].removesuffix(":access")
            resolved = self.aliases.get(version, version)
            if resolved not in self.versions:
                return SimpleNamespace(ok=False, status_code=404, json=lambda: {})
            raw = self.versions[resolved]
            payload = {
                "name": f"projects/pilot-project-1/secrets/lagniappe-runtime-secrets/versions/{resolved}",
                "payload": {
                    "data": base64.b64encode(raw).decode("ascii"),
                    "dataCrc32c": str(google_crc32c.value(raw)),
                },
            }
            return SimpleNamespace(ok=True, status_code=200, json=lambda: payload)
        if method == "GET":
            meta = {"etag": self.etag, "versionAliases": dict(self.aliases)}
            return SimpleNamespace(ok=True, status_code=200, json=lambda: meta)
        if method == "POST" and url.endswith(":addVersion"):
            raw = base64.b64decode(json["payload"]["data"], validate=True)
            assert int(json["payload"]["dataCrc32c"]) == google_crc32c.value(raw)
            version = str(self.next_version)
            self.next_version += 1
            self.versions[version] = raw
            return SimpleNamespace(
                ok=True,
                status_code=200,
                json=lambda: {
                    "name": f"projects/pilot-project-1/secrets/lagniappe-runtime-secrets/versions/{version}"
                },
            )
        if method == "PATCH":
            assert json["etag"] == self.etag
            self.aliases = dict(json["versionAliases"])
            self.etag = f"etag-{self.next_version}"
            return SimpleNamespace(ok=True, status_code=200, json=lambda: {"etag": self.etag})
        return SimpleNamespace(ok=False, status_code=500, json=lambda: {})


def test_secret_split_extract_strip_merge_and_leak_detection():
    full = _sample_full_app_settings("secret_manager")
    extracted = runtime_secrets.extract_secret_settings(full)
    stripped = runtime_secrets.strip_secret_settings(full)

    assert set(extracted) == {
        "SECRET_KEY",
        "GIBBERISH",
        "AGENT_ACCESS_CODE",
        "REDIS_PASSWORD",
        "SENTRY_DSN",
        "AUTH_EMAIL_CONFIG",
        "AI_EMAIL_CONFIG",
    }
    assert extracted["AUTH_EMAIL_CONFIG"] == {"password": "super-secret-smtp-password"}
    assert extracted["AI_EMAIL_CONFIG"] == {
        "resend": {
            "webhookSecret": "whsec_super_secret",
            "inboundApiKey": "re_inbound_secret",
            "sendingApiKey": "re_sending_secret",
        }
    }

    assert runtime_secrets.find_leaked_secret_keys(stripped) == []
    # Non-secret sibling fields stay on disk.
    assert stripped["SENTRY_JS_DSN"] == "https://public-browser@o1.ingest.sentry.io/2"
    assert stripped["AUTH_EMAIL_CONFIG"]["host"] == "smtp.gmail.com"
    assert stripped["AUTH_EMAIL_CONFIG"]["senderEmail"] == "owner@example.com"
    assert "password" not in stripped["AUTH_EMAIL_CONFIG"]
    assert stripped["AI_EMAIL_CONFIG"]["resend"]["domainId"] == "dom_123"
    assert "webhookSecret" not in stripped["AI_EMAIL_CONFIG"]["resend"]

    merged = runtime_secrets.merge_secret_settings(stripped, extracted)
    assert merged == full
    assert runtime_secrets.find_leaked_secret_keys(full) == [
        "AGENT_ACCESS_CODE",
        "AI_EMAIL_CONFIG.resend.inboundApiKey",
        "AI_EMAIL_CONFIG.resend.sendingApiKey",
        "AI_EMAIL_CONFIG.resend.webhookSecret",
        "AUTH_EMAIL_CONFIG.password",
        "GIBBERISH",
        "REDIS_PASSWORD",
        "SECRET_KEY",
        "SENTRY_DSN",
    ]


def test_secret_manager_store_publish_is_idempotent_and_verifies_round_trip():
    session = _FakeSecretSession()
    store = runtime_secrets.SecretManagerRuntimeStore(
        "pilot-project-1",
        access_token="fake-token",
        session=session,
    )
    secrets_map = runtime_secrets.extract_secret_settings(_sample_full_app_settings())

    v1 = store.publish(secrets_map)
    assert v1 == "1"
    assert session.aliases == {"current": "1"}
    # Identical publish reuses current without adding version 2.
    assert store.publish(secrets_map) == "1"
    assert list(session.versions) == ["1"]

    resolved, hydrated = store.access("current")
    assert resolved == "1"
    assert hydrated == secrets_map

    # Updating a secret publishes version 2 and advances current.
    updated = {**secrets_map, "REDIS_PASSWORD": "rotated-redis-pass"}
    v2 = store.publish(updated)
    assert v2 == "2"
    assert store.access("current") == ("2", updated)


def test_settings_draft_save_and_runtime_load_keep_zero_secrets_on_disk(
    isolated_config, monkeypatch
):
    config = isolated_config
    secrets_module = importlib.import_module("config.secrets")
    real_store_cls = secrets_module.SecretManagerRuntimeStore
    session = _FakeSecretSession()

    def _fake_store(project_id: str, secret_name: str):
        return real_store_cls(
            project_id,
            secret_name,
            access_token="fake-token",
            session=session,
        )

    monkeypatch.setattr(secrets_module, "SecretManagerRuntimeStore", _fake_store)

    draft = config.SettingsDraft()
    draft.APP.update(_sample_full_app_settings("secret_manager"))
    draft.save(config.File.APP_SETTINGS_YAML)

    # Zero secret values on disk in lagniappe_settings.yaml!
    raw_disk = config.File.APP_SETTINGS_YAML.value.read_text(encoding="utf-8")
    for secret_value in (
        "super-secret-flask-key",
        "super-secret-gibberish",
        "super-secret-agent-code",
        "super-secret-redis-pass",
        "super-secret-smtp-password",
        "whsec_super_secret",
        "re_inbound_secret",
        "re_sending_secret",
        "https://secret@o1.ingest.sentry.io/1",
    ):
        assert secret_value not in raw_disk
    assert secrets_module.find_leaked_secret_keys(config.File.APP_SETTINGS_YAML.load()) == []

    # In-memory SETTINGS.APP remains unified after save.
    assert draft.APP["SECRET_KEY"] == "super-secret-flask-key"
    assert draft.APP["AUTH_EMAIL_CONFIG"]["password"] == "super-secret-smtp-password"

    # Runtime startup hydrates all secrets into immutable RuntimeSettings.
    runtime_snapshot = config.load_runtime_settings(config.Environment.PRODUCTION)
    hydrated = runtime_snapshot.as_dict()
    assert hydrated["SECRET_KEY"] == "super-secret-flask-key"
    assert hydrated["REDIS_PASSWORD"] == "super-secret-redis-pass"
    assert hydrated["AUTH_EMAIL_CONFIG"]["password"] == "super-secret-smtp-password"
    assert hydrated["AI_EMAIL_CONFIG"]["resend"]["webhookSecret"] == "whsec_super_secret"
    assert hydrated["SENTRY_JS_DSN"] == "https://public-browser@o1.ingest.sentry.io/2"

    # Fresh SettingsDraft also hydrates transparently.
    reopened = config.SettingsDraft()
    assert reopened.APP["SECRET_KEY"] == "super-secret-flask-key"
    assert reopened.APP["AI_EMAIL_CONFIG"]["resend"]["sendingApiKey"] == "re_sending_secret"

    # Browser display helper defaults to secret-free disk view.
    display_raw = config.read_saved_app_settings()
    assert "SECRET_KEY" not in display_raw
    assert secrets_module.find_leaked_secret_keys(config.decode_app_settings(display_raw)) == []


def test_legacy_local_yaml_install_never_contacts_secret_manager(
    isolated_config, monkeypatch
):
    config = isolated_config
    secrets_module = importlib.import_module("config.secrets")
    monkeypatch.setattr(
        secrets_module,
        "SecretManagerRuntimeStore",
        lambda *args, **kwargs: pytest.fail("local_yaml must not touch Secret Manager"),
    )
    draft = config.SettingsDraft()
    local_settings = _sample_full_app_settings("local_yaml")
    local_settings.pop("SECRETS_BACKEND")
    draft.APP.update(local_settings)
    draft.save(config.File.APP_SETTINGS_YAML)

    loaded = config.load_runtime_settings(config.Environment.PRODUCTION).as_dict()
    assert loaded["SECRET_KEY"] == "super-secret-flask-key"
    assert loaded["REDIS_PASSWORD"] == "super-secret-redis-pass"


def test_recovery_validation_accepts_secret_free_secret_manager_snapshot():
    stripped = runtime_secrets.strip_secret_settings(
        _sample_full_app_settings("secret_manager")
    )
    recovered = validate_recovery_document(stripped)
    assert recovered["SECRETS_BACKEND"] == "secret_manager"
    assert recovered["SECRETS_SECRET_NAME"] == "lagniappe-runtime-secrets"
    assert "password" not in recovered["AUTH_EMAIL_CONFIG"]

    # Same stripped document without SECRETS_BACKEND=secret_manager must still fail.
    legacy = dict(stripped)
    legacy["SECRETS_BACKEND"] = "local_yaml"
    with pytest.raises(RecoveryConfigurationError, match="GIBBERISH"):
        validate_recovery_document(legacy)


def test_installer_secrets_provisioning_probe_and_doctor_leak_check(tmp_path):
    commands: list[list[str]] = []

    def fake_gcloud(command: list[str], *, check: bool = False):
        commands.append(command)
        if command[:2] == ["services", "list"]:
            return CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["services", "enable"]:
            return CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["secrets", "describe"]:
            return CompletedProcess(command, 1, stdout="", stderr="NOT_FOUND")
        if command[:2] == ["secrets", "create"]:
            return CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["secrets", "get-iam-policy"]:
            return CompletedProcess(command, 0, stdout='{"bindings": []}', stderr="")
        if command[:2] == ["secrets", "add-iam-policy-binding"]:
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected gcloud command: {command}")

    result = installer_secrets.ensure_runtime_secrets_infrastructure(
        "pilot-project-1",
        "lagniappe@pilot-project-1.iam.gserviceaccount.com",
        gcloud_runner=fake_gcloud,
    )
    assert result["created_secret"] is True
    assert result["granted_iam"] is True
    assert any(
        cmd[:3] == ["secrets", "add-iam-policy-binding", "lagniappe-runtime-secrets"]
        and "--role=roles/secretmanager.secretAccessor" in cmd
        for cmd in commands
    )

    # Probe verifies metadata + IAM without ever calling versions access.
    def probe_gcloud(command: list[str], *, check: bool = False):
        assert "access" not in command
        if command[:2] == ["secrets", "describe"]:
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps({"versionAliases": {"current": "3"}}),
                stderr="",
            )
        if command[:2] == ["secrets", "get-iam-policy"]:
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "bindings": [
                            {
                                "role": "roles/secretmanager.secretAccessor",
                                "members": [
                                    "serviceAccount:lagniappe@pilot-project-1.iam.gserviceaccount.com"
                                ],
                            }
                        ]
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected probe command: {command}")

    probe = installer_secrets.probe_runtime_secrets_resource(
        _sample_full_app_settings("secret_manager"),
        "pilot-project-1",
        gcloud_runner=probe_gcloud,
    )
    assert probe["state"] == "AVAILABLE"
    assert probe["details"]["version"] == "3"

    # Doctor local check flags secret keys left on disk without printing secret values.
    config_dir = tmp_path / "config" / "files"
    config_dir.mkdir(parents=True)
    leaked_doc = _sample_full_app_settings("secret_manager")
    (config_dir / "lagniappe_settings.yaml").write_text(
        yaml.safe_dump(leaked_doc, sort_keys=True),
        encoding="utf-8",
    )
    _, issues = doctor._local_state(tmp_path)
    joined = "\n".join(issues)
    assert "SECRETS_BACKEND=secret_manager" in joined
    assert "REDIS_PASSWORD" in joined
    assert "AUTH_EMAIL_CONFIG.password" in joined
    assert "super-secret-redis-pass" not in joined
    assert "super-secret-smtp-password" not in joined


def test_doctor_provider_checker_hydrates_secret_manager_settings_in_memory(monkeypatch):
    from installer import commands, iam, monitoring, recovery

    disk_settings = runtime_secrets.strip_secret_settings(
        _sample_full_app_settings("secret_manager")
    )
    assert "GIBBERISH" not in disk_settings
    assert "REDIS_PASSWORD" not in disk_settings

    seen_settings: dict[str, object] = {}

    def _fake_verify_recovery_resources(settings, project, *, project_details=None):
        seen_settings.update(settings)
        return {"storage-buckets": {"state": "AVAILABLE", "details": None, "error": None}}

    def _fake_gcloud(command, *, check=False):
        if command[:2] == ["projects", "describe"]:
            return CompletedProcess(
                command, 0, stdout=json.dumps({"projectId": "pilot-project-1"}), stderr=""
            )
        if command[:2] == ["services", "list"]:
            from config import constants

            apis = sorted(
                {*constants.REQUIRED_GOOGLE_CLOUD_APIS, installer_secrets.SECRET_MANAGER_API}
            )
            return CompletedProcess(command, 0, stdout="\n".join(apis) + "\n", stderr="")
        raise AssertionError(f"Unexpected gcloud command: {command}")

    monkeypatch.setattr(commands, "run_gcloud_command", _fake_gcloud)
    monkeypatch.setattr(
        runtime_secrets,
        "load_runtime_secrets",
        lambda _settings: {
            "GIBBERISH": "hydrated-gibberish",
            "REDIS_PASSWORD": "hydrated-redis-pass",
        },
    )
    monkeypatch.setattr(recovery, "verify_recovery_resources", _fake_verify_recovery_resources)
    monkeypatch.setattr(iam, "inspect_operator_permissions", lambda _project: {})
    monkeypatch.setattr(
        installer_secrets,
        "probe_runtime_secrets_resource",
        lambda _settings, _project: {"state": "AVAILABLE", "details": None, "error": None},
    )
    monkeypatch.setattr(
        monitoring,
        "inspect_memory_alert",
        lambda _settings, _project: {"state": "AVAILABLE", "details": None, "error": None},
    )

    report = doctor._default_provider_checker(disk_settings, "pilot-project-1")
    assert seen_settings["GIBBERISH"] == "hydrated-gibberish"
    assert seen_settings["REDIS_PASSWORD"] == "hydrated-redis-pass"
    # Raw disk settings mapping was not mutated with secrets.
    assert "GIBBERISH" not in disk_settings
    assert "REDIS_PASSWORD" not in disk_settings
    assert all(entry["state"] == "AVAILABLE" for entry in report.values())
