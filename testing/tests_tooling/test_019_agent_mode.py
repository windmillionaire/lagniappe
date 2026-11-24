"""Tests for non-interactive agent-assisted installation (--agent)."""

from __future__ import annotations

import base64
import importlib
import json
import sys
from types import SimpleNamespace

import google_crc32c
import pytest

from installer import agent_mode
from installer.__main__ import _parser
from installer.secret_vault import VaultSubmitResult

pytestmark = pytest.mark.tooling


class _FakeSecretSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.versions: dict[str, bytes] = {}
        self.aliases: dict[str, str] = {}
        self.etag = "etag-1"
        self.next_version = 1

    def request(self, method, url, *, json=None, params=None, timeout=None, allow_redirects=True):
        if method == "GET" and url.endswith(":access"):
            version = url.rsplit("/versions/", 1)[1].removesuffix(":access")
            resolved = self.aliases.get(version, version)
            if resolved not in self.versions:
                return SimpleNamespace(ok=False, status_code=404, json=lambda: {})
            raw = self.versions[resolved]
            return SimpleNamespace(
                ok=True,
                status_code=200,
                json=lambda: {
                    "name": f"projects/pilot-project-1/secrets/lagniappe-runtime-secrets/versions/{resolved}",
                    "payload": {
                        "data": base64.b64encode(raw).decode("ascii"),
                        "dataCrc32c": str(google_crc32c.value(raw)),
                    },
                },
            )
        if method == "GET":
            return SimpleNamespace(
                ok=True,
                status_code=200,
                json=lambda: {"etag": self.etag, "versionAliases": dict(self.aliases)},
            )
        if method == "POST" and url.endswith(":addVersion"):
            raw = base64.b64decode(json["payload"]["data"], validate=True)
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
            self.aliases = dict(json["versionAliases"])
            self.etag = f"etag-{self.next_version}"
            return SimpleNamespace(ok=True, status_code=200, json=lambda: {"etag": self.etag})
        return SimpleNamespace(ok=False, status_code=500, json=lambda: {})


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "config" or name.startswith("config.")
    }
    for name in original_modules:
        sys.modules.pop(name)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(tmp_path))
    monkeypatch.setenv("LAGNIAPPE_SETUP_STATE_DIR", str(tmp_path / "state"))
    # Seed minimal package.json + constants.py checksum target for generation manifest.
    (tmp_path / "package.json").write_text('{"version": "2.5.0"}\n', encoding="utf-8")
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "constants.py").write_text('BUILD_ID = "test"\n', encoding="utf-8")
    cfg = importlib.import_module("config")
    secrets_mod = importlib.import_module("config.secrets")
    real_store_cls = secrets_mod.SecretManagerRuntimeStore
    session = _FakeSecretSession()
    monkeypatch.setattr(
        secrets_mod,
        "SecretManagerRuntimeStore",
        lambda project_id, secret_name: real_store_cls(
            project_id,
            secret_name,
            access_token="fake-token",
            session=session,
        ),
    )
    monkeypatch.setattr(agent_mode, "File", cfg.File)
    try:
        yield tmp_path, cfg, secrets_mod, session
    finally:
        for name in list(sys.modules):
            if name == "config" or name.startswith("config."):
                sys.modules.pop(name)
        sys.modules.update(original_modules)


def test_agent_answers_reject_secrets_and_report_missing_inputs(
    isolated_env, tmp_path, capsys
):
    _, cfg, _, _ = isolated_env

    # Any secret field in answers.json is hard-rejected with exit code 2.
    bad_answers = tmp_path / "bad_answers.json"
    bad_answers.write_text(
        json.dumps({"app_name": "Demo", "redis_password": "leaked-value"}),
        encoding="utf-8",
    )
    rc = agent_mode.run_agent_install(
        answers_path=bad_answers,
        json_output=True,
        draft=cfg.SettingsDraft(),
    )
    assert rc == agent_mode.EXIT_INVALID_ANSWERS
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"
    assert "redis_password" in out["message"]
    assert "leaked-value" not in out["message"]

    # Partial non-secret answers return deterministic needs_input (exit code 3).
    partial_answers = tmp_path / "partial.json"
    partial_answers.write_text(json.dumps({"app_name": "Demo"}), encoding="utf-8")
    rc = agent_mode.run_agent_install(
        answers_path=partial_answers,
        json_output=True,
        draft=cfg.SettingsDraft(),
    )
    assert rc == agent_mode.EXIT_NEEDS_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "needs_input"
    keys = {item["key"] for item in payload["missing_fields"]}
    assert keys == {"project_id", "admin_name", "admin_email"}


def test_agent_mode_returns_needs_input_on_billing_choice_and_keeps_json_stdout_clean(
    isolated_env, tmp_path, capsys
):
    _, cfg, _, _ = isolated_env
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(
        json.dumps(
            {
                "app_name": "Billing Pilot",
                "project_id": "billing-pilot-1",
                "admin_name": "Alex",
                "admin_email": "alex@example.com",
            }
        ),
        encoding="utf-8",
    )

    def _provision_needs_billing(_draft):
        print("Provisioning log noise must go to stderr under --json")
        raise agent_mode.AgentNeedsInputError(
            "Multiple open Google Cloud billing accounts are available.",
            [
                agent_mode.MissingField(
                    key="billing_account",
                    label="Google Cloud billing account ID",
                    choices=("01AAAA-BBBBBB-CCCCCC", "02DDDD-EEEEEE-FFFFFF"),
                )
            ],
        )

    rc = agent_mode.run_agent_install(
        answers_path=answers_file,
        json_output=True,
        draft=cfg.SettingsDraft(),
        provision_fn=_provision_needs_billing,
    )
    assert rc == agent_mode.EXIT_NEEDS_INPUT
    captured = capsys.readouterr()
    assert "Provisioning log noise must go to stderr under --json" in captured.err
    payload = json.loads(captured.out)
    assert payload["status"] == "needs_input"
    assert payload["missing_fields"][0]["key"] == "billing_account"
    assert payload["missing_fields"][0]["choices"] == [
        "01AAAA-BBBBBB-CCCCCC",
        "02DDDD-EEEEEE-FFFFFF",
    ]


def test_agent_install_vault_handoff_resume_and_zero_disk_secrets(
    isolated_env, tmp_path, capsys
):
    _, cfg, secrets_mod, session = isolated_env
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(
        json.dumps(
            {
                "app_name": "Pilot Workspace",
                "project_id": "pilot-project-1",
                "admin_name": "Alex",
                "admin_email": "alex@example.com",
                "auth_email_provider": "gmail",
                "google_signin_enabled": True,
                "ai_enabled": True,
                "external_ai_enabled": False,
                "capture_errors": False,
                "deploy_now": True,
            }
        ),
        encoding="utf-8",
    )

    oauth_calls: list[tuple[str, str]] = []
    vault_invocations = 0

    def fake_vault(sections, on_submit):
        nonlocal vault_invocations
        vault_invocations += 1
        assert [s.section_id for s in sections] == [
            "google_oauth",
            "auth_email",
            "redis",
        ]
        # First attempt has a bad Gmail app password -> rejected inline.
        bad = on_submit(
            {
                "oauth_credentials_json": "",
                "oauth_client_id": "123456.apps.googleusercontent.com",
                "oauth_client_secret": "GOCSPX-transient-secret",
                "auth_email_password": "short",
                "redis_cli_command": "redis-cli -u redis://default:redis-secret-pass@redis.test:6379",
                "redis_host": "",
                "redis_port": "",
                "redis_password": "",
            }
        )
        assert bad.ok is False
        assert "auth_email_password" in bad.field_errors
        assert "GOCSPX-transient-secret" not in bad.error

        # Second attempt succeeds.
        good = on_submit(
            {
                "oauth_credentials_json": "",
                "oauth_client_id": "123456.apps.googleusercontent.com",
                "oauth_client_secret": "GOCSPX-transient-secret",
                "auth_email_password": "abcd efgh ijkl mnop",
                "redis_cli_command": "redis-cli -u redis://default:redis-secret-pass@redis.test:6379",
                "redis_host": "",
                "redis_port": "",
                "redis_password": "",
            }
        )
        assert good.ok is True
        return good

    draft = cfg.SettingsDraft()
    rc = agent_mode.run_agent_install(
        answers_path=answers_file,
        json_output=True,
        draft=draft,
        provision_fn=lambda d: None,
        vault_runner=fake_vault,
        validate_oauth=lambda cid, csec, uri: oauth_calls.append((cid, csec)),
        validate_smtp=lambda cfg_map, rcpt: None,
        validate_redis=lambda settings_map: None,
        deploy_fn=lambda d: True,
        doctor_fn=lambda: 0,
    )
    assert rc == agent_mode.EXIT_OK
    assert vault_invocations == 1
    assert oauth_calls[-1] == ("123456.apps.googleusercontent.com", "GOCSPX-transient-secret")

    out_text = capsys.readouterr().out
    result = json.loads(out_text)
    assert result["status"] == "ok"
    assert result["secrets_backend"] == "secret_manager"
    assert result["deployed"] is True
    assert result["doctor_exit_code"] == 0
    # Zero secret values in JSON stdout or on disk!
    for secret_str in ("GOCSPX-transient-secret", "abcdefghijklmnop", "redis-secret-pass"):
        assert secret_str not in out_text
        assert secret_str not in cfg.File.APP_SETTINGS_YAML.value.read_text(encoding="utf-8")
    assert secrets_mod.find_leaked_secret_keys(cfg.File.APP_SETTINGS_YAML.load()) == []
    assert session.aliases.get("current") is not None

    # Resume pass: reopening draft hydrates secrets from Secret Manager and skips vault!
    resumed_draft = cfg.SettingsDraft()
    rc2 = agent_mode.run_agent_install(
        answers_path=answers_file,
        json_output=True,
        draft=resumed_draft,
        provision_fn=lambda d: None,
        vault_runner=lambda sections, cb: VaultSubmitResult(
            ok=False, error="Vault should have been skipped on resume!"
        ),
        deploy_fn=lambda d: True,
        doctor_fn=lambda: 0,
    )
    assert rc2 == agent_mode.EXIT_OK
    resumed_out = json.loads(capsys.readouterr().out)
    assert resumed_out["status"] == "ok"
    assert resumed_out["vault_sections_completed"] == []


def test_cli_parser_supports_agent_flags_and_secrets_migrate():
    parser = _parser()
    parsed = parser.parse_args(["--agent", "--answers", "answers.json", "--json"])
    assert parsed.agent is True
    assert parsed.answers == "answers.json"
    assert parsed.json_output is True

    migrate = parser.parse_args(["secrets", "migrate"])
    assert migrate.command == "secrets"
    assert migrate.secrets_action == "migrate"


def test_configure_secrets_migrate_offers_and_runs_deploy(monkeypatch):
    from installer import deploy as installer_deploy
    from installer import secrets as installer_secrets
    from installer import verify as installer_verify
    from runner import presentation as ui

    events: list[str] = []
    monkeypatch.setattr(
        installer_verify,
        "prepare_existing_installation",
        lambda: events.append("prepare"),
    )
    monkeypatch.setattr(
        installer_secrets,
        "migrate_local_yaml_to_secret_manager",
        lambda: (
            events.append("migrate")
            or {"project_id": "demo-proj", "secret_name": "lagniappe-runtime-secrets"}
        ),
    )
    monkeypatch.setattr(
        installer_deploy,
        "deploy_to_app_engine",
        lambda *, print_final_summary=True: events.append(
            f"deploy:{print_final_summary}"
        ),
    )
    monkeypatch.setattr(ui, "output", lambda *a, **k: None)

    monkeypatch.setattr(ui, "read_input", lambda prompt="": "")
    assert installer_secrets.configure_secrets_migrate() == 0
    assert events == ["prepare", "migrate", "deploy:False"]

    events.clear()
    monkeypatch.setattr(ui, "read_input", lambda prompt="": "n")
    assert installer_secrets.configure_secrets_migrate() == 0
    assert events == ["prepare", "migrate"]


def test_setup_app_engine_provisions_secret_manager_before_saving(monkeypatch):
    import config
    from installer import gcloud as installer_gcloud
    from installer import secrets as installer_secrets

    events: list[str] = []

    class _FakeSettings:
        APP = {
            "SECRETS_BACKEND": "secret_manager",
            "SECRETS_SECRET_NAME": "lagniappe-runtime-secrets",
            "SECRET_KEY": "generated-secret",
        }
        DEPLOY: dict[str, object] = {}
        GCLOUD_CONFIG = {"PROJECT": "demo-proj"}

        def save(self, *args):
            events.append("save")
            return ()

    fake_settings = _FakeSettings()
    monkeypatch.setattr(config, "SETTINGS", fake_settings)
    monkeypatch.setattr(
        installer_gcloud,
        "configure_service_account",
        lambda: (
            events.append("sa")
            or {"client_email": "demo@demo-proj.iam.gserviceaccount.com"}
        ),
    )
    monkeypatch.setattr(
        installer_secrets,
        "ensure_runtime_secrets_infrastructure",
        lambda project_id, runtime_email, *, secret_name: (
            events.append(f"secrets_infra:{project_id}:{runtime_email}:{secret_name}")
            or {}
        ),
    )
    monkeypatch.setattr(
        installer_gcloud,
        "create_app_engine_app",
        lambda *, confirm=True: (
            events.append(f"app_engine:confirm={confirm}")
            or SimpleNamespace(
                location_id="us-central",
                default_hostname="demo-proj.uc.r.appspot.com",
            )
        ),
    )

    installer_gcloud.setup_app_engine(confirm=False)
    assert events == [
        "sa",
        "secrets_infra:demo-proj:demo@demo-proj.iam.gserviceaccount.com:lagniappe-runtime-secrets",
        "save",
        "app_engine:confirm=False",
        "save",
    ]


def test_populate_generated_documents_fills_index_and_deploy_before_provisioning(
    isolated_env,
):
    _, cfg, _, _ = isolated_env
    draft = cfg.SettingsDraft()
    answers = {
        "app_name": "Fresh Checkout",
        "project_id": "fresh-checkout-1",
        "admin_name": "Owner",
        "admin_email": "owner@example.com",
    }
    agent_mode._apply_non_secret_answers(answers, draft)
    agent_mode._populate_generated_documents(draft)

    assert draft.INDEX.get("indexes")
    assert draft.DEPLOY.get("service_account") == "fresh-checkout@fresh-checkout-1.iam.gserviceaccount.com"
    assert draft.MANIFEST.get("name") == "Fresh Checkout"
    # Saving all generated files succeeds on a fresh checkout (no "Nothing to save").
    draft.save()


def test_secret_manager_publish_retries_transient_403_propagation(monkeypatch):
    from config import secrets as runtime_secrets

    calls = 0

    class _FlakySession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.versions: dict[str, bytes] = {}
            self.aliases: dict[str, str] = {}

        def request(self, method, url, *, json=None, params=None, timeout=None, allow_redirects=True):
            nonlocal calls
            calls += 1
            if calls == 1:
                return SimpleNamespace(ok=False, status_code=403, json=lambda: {})
            if method == "GET" and url.endswith(":access"):
                import base64

                ver = url.rsplit("/versions/", 1)[1].removesuffix(":access")
                raw = self.versions[self.aliases.get(ver, ver)]
                return SimpleNamespace(
                    ok=True,
                    status_code=200,
                    json=lambda: {
                        "name": f"projects/p/secrets/s/versions/{ver}",
                        "payload": {"data": base64.b64encode(raw).decode("ascii")},
                    },
                )
            if method == "GET":
                return SimpleNamespace(
                    ok=True,
                    status_code=200,
                    json=lambda: {"etag": "e1", "versionAliases": dict(self.aliases)},
                )
            if method == "POST" and url.endswith(":addVersion"):
                import base64

                self.versions["1"] = base64.b64decode(json["payload"]["data"])
                return SimpleNamespace(
                    ok=True,
                    status_code=200,
                    json=lambda: {"name": "projects/p/secrets/s/versions/1"},
                )
            if method == "PATCH":
                self.aliases = dict(json["versionAliases"])
                return SimpleNamespace(
                    ok=True,
                    status_code=200,
                    json=lambda: {"versionAliases": dict(self.aliases)},
                )
            raise AssertionError(f"Unexpected {method} {url}")

    monkeypatch.setattr(runtime_secrets.time, "sleep", lambda _s: None)
    store = runtime_secrets.SecretManagerRuntimeStore(
        "pilot-project-1",
        access_token="fake-token",
        session=_FlakySession(),
        propagation_retry_delays=(0.01, 0.01),
    )
    assert store.publish({"SECRET_KEY": "abc"}) == "1"
    assert calls >= 5


def test_default_deploy_syncs_post_vault_draft_into_settings_singleton(monkeypatch):
    import config
    from installer import deploy as installer_deploy
    from installer import monitoring as installer_monitoring
    from installer import upgrade as installer_upgrade

    stale_settings = SimpleNamespace(
        APP={"APP_NAME": "Demo", "GOOGLE_CLOUD_PROJECT": "demo-proj"},
        DEPLOY={},
        DEV={},
        GCLOUD_CONFIG={"PROJECT": "demo-proj"},
        DEV_CONFIG={},
        TEST_CONFIG={},
        INDEX={},
        MANIFEST={},
    )
    post_vault_draft = SimpleNamespace(
        APP={
            "APP_NAME": "Demo",
            "GOOGLE_CLOUD_PROJECT": "demo-proj",
            "REDIS_HOST": "redis.cloud.example",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret-redis-password",
            "GOOGLE_CLIENT_ID": "12345.apps.googleusercontent.com",
            "AUTH_EMAIL_CONFIG": {"host": "smtp.gmail.com", "password": "app-password"},
        },
        DEPLOY={"service_account": "demo@demo-proj.iam.gserviceaccount.com"},
        DEV={},
        GCLOUD_CONFIG={"PROJECT": "demo-proj"},
        DEV_CONFIG={},
        TEST_CONFIG={},
        INDEX={"indexes": []},
        MANIFEST={"name": "Demo"},
    )

    seen_during_deploy: dict[str, object] = {}

    def _fake_deploy(*, print_final_summary=True, first_install=False):
        seen_during_deploy["REDIS_HOST"] = config.SETTINGS.APP.get("REDIS_HOST")
        seen_during_deploy["REDIS_PORT"] = config.SETTINGS.APP.get("REDIS_PORT")
        seen_during_deploy["GOOGLE_CLIENT_ID"] = config.SETTINGS.APP.get(
            "GOOGLE_CLIENT_ID"
        )
        seen_during_deploy["AUTH_EMAIL_CONFIG"] = config.SETTINGS.APP.get(
            "AUTH_EMAIL_CONFIG"
        )

    monkeypatch.setattr(config, "SETTINGS", stale_settings)
    monkeypatch.setattr(installer_deploy, "deploy_to_app_engine", _fake_deploy)
    monkeypatch.setattr(
        installer_upgrade,
        "_configure_deferred_job_recovery",
        lambda _f, _g: True,
    )
    monkeypatch.setattr(
        installer_monitoring,
        "reconcile_memory_alert",
        lambda: None,
    )
    monkeypatch.setattr(
        agent_mode,
        "_verify_live_site_responds",
        lambda _url: True,
    )

    assert agent_mode._default_deploy(post_vault_draft) is True  # type: ignore[arg-type]
    assert seen_during_deploy == {
        "REDIS_HOST": "redis.cloud.example",
        "REDIS_PORT": 12345,
        "GOOGLE_CLIENT_ID": "12345.apps.googleusercontent.com",
        "AUTH_EMAIL_CONFIG": {"host": "smtp.gmail.com", "password": "app-password"},
    }


def test_verify_live_site_responds_retries_cold_start_and_fails_on_500():
    attempts: list[str] = []

    def _warming_get(url, *, timeout=20, allow_redirects=True):
        attempts.append(url)
        code = 503 if len(attempts) == 1 else 200
        return SimpleNamespace(status_code=code)

    assert (
        agent_mode._verify_live_site_responds(
            "https://demo.uc.r.appspot.com",
            request_get=_warming_get,
            retry_delays=(0.0, 0.0),
        )
        is True
    )
    assert attempts == [
        "https://demo.uc.r.appspot.com/users/login",
        "https://demo.uc.r.appspot.com/users/login",
    ]

    assert (
        agent_mode._verify_live_site_responds(
            "https://demo.uc.r.appspot.com",
            request_get=lambda url, **_kw: SimpleNamespace(status_code=500),
            retry_delays=(0.0, 0.0),
        )
        is False
    )
