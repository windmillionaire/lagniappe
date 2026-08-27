"""Tooling tests for setup validation and configuration helpers."""

import json
from pathlib import Path
import shutil
import sys
import types

import pytest
import yaml

from installer.errors import SetupCancelled, SetupError

from testing.utility.setup_fakes import (
    SpinnerRecorder,
    completed_process,
    spinner_factory,
)

pytestmark = pytest.mark.tooling

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _use_isolated_app_dir(monkeypatch, app_dir):
    (app_dir / "main.py").write_text("", encoding="utf-8")
    config_dir = app_dir / "config"
    config_dir.mkdir()
    shutil.copyfile(
        REPOSITORY_ROOT / "config" / "constants.py",
        config_dir / "constants.py",
    )
    for name in list(sys.modules):
        if name == "config" or name.startswith("config."):
            sys.modules.pop(name, None)
    monkeypatch.setenv("LAGNIAPPE_CONFIG_ROOT", str(app_dir))
    monkeypatch.chdir(app_dir)


def _fake_formatter():
    return types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            info=lambda message: message,
            warning=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=spinner_factory(SpinnerRecorder()),
        )
    )


@pytest.fixture(autouse=True)
def fake_yaspin_module(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "yaspin", types.SimpleNamespace(yaspin=spinner_factory())
    )


@pytest.fixture
def isolated_setup_config(monkeypatch, tmp_path):
    _use_isolated_app_dir(monkeypatch, tmp_path)


def _stub_existing_install_preflight(
    monkeypatch,
    create_config,
    *,
    app_name,
    account,
    project_id,
):
    preflight = {
        "project": {"state": "available", "details": {}, "error": None},
        "billing_account": "billing-1",
        "billing_enabled": True,
        "enabled_apis": set(create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS),
        "missing_apis": [],
    }
    identity = {
        "state": "success",
        "principal": account,
        "project": project_id,
        "quota_project": project_id,
        "error": None,
    }
    monkeypatch.setattr(
        create_config,
        "_active_cli_identity",
        lambda: {
            "configuration": create_config._gcloud_configuration_name(app_name),
            "account": account,
            "project": project_id,
        },
    )
    monkeypatch.setattr(create_config, "_target_preflight", lambda target: preflight)
    monkeypatch.setattr(
        create_config,
        "_preflight_operator_authority",
        lambda selected_account, target, **kwargs: types.SimpleNamespace(),
    )
    monkeypatch.setattr(
        create_config,
        "_ensure_adc_principal",
        lambda selected_account, target=None: identity,
    )
    monkeypatch.setattr(
        create_config,
        "_set_adc_quota_project",
        lambda target, spinner: identity,
    )
    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda target, **kwargs: {
            "installer": [],
            "billing": [],
            "deployer": [],
        },
    )
    monkeypatch.setattr(
        create_config,
        "_display_install_identity_summary",
        lambda target_preflight, adc: None,
    )
    monkeypatch.setattr(
        create_config,
        "_apply_target_preflight",
        lambda target, target_preflight, project_ready=None: None,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "y")


# @pair setup:validation
def test_setup_validators_cover_expected_inputs():
    from installer import admin
    from installer.domain.validation import (
        validate_cloudflare_api_token,
        validate_domain,
    )

    assert validate_domain("app.example.com")
    assert not validate_domain("-bad.example.com")
    assert validate_cloudflare_api_token("scoped-token-" + ("a" * 20))
    assert not validate_cloudflare_api_token("short")
    assert admin.validate_oauth_client_id("1234-test.apps.googleusercontent.com")
    assert not admin.validate_oauth_client_id("not-google")


# @pair setup:interactive-input
def test_validate_input_retries_allows_empty_and_exits(monkeypatch):
    from installer.utils import validate_input

    answers = iter(["", "bad", "ok"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    @validate_input("Value", validation_fn=lambda value: value == "ok")
    def get_value(value):
        return value

    assert get_value() == "ok"

    monkeypatch.setattr("builtins.input", lambda prompt: "")

    @validate_input("Optional", allow_empty=True)
    def get_optional_value(value):
        return value

    assert get_optional_value() == ""

    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "",
    )

    @validate_input("Suggested", default="chosen-value")
    def get_default_value(value):
        return value

    assert get_default_value() == "chosen-value"
    assert prompts == [
        "Suggested [chosen-value] "
        "(press Enter to use the bracketed value; x to exit): "
    ]

    monkeypatch.setattr("builtins.input", lambda prompt: "x")

    @validate_input("Value")
    def never_returns(value):
        return value

    with pytest.raises(SetupCancelled):
        never_returns()


# @pair setup:project-id
def test_validate_project_id_and_project_state_are_non_mutating(
    monkeypatch,
    isolated_setup_config,
):
    from installer import create_config

    calls = []

    def fake_gcloud(command, check=True):
        calls.append((command, check))
        return completed_process(command, returncode=1, stderr="not found")

    monkeypatch.setattr(create_config, "run_gcloud_command", fake_gcloud)

    assert not create_config.validate_project_id("BadProject")
    assert not calls
    assert create_config.validate_project_id("valid-project-1")
    assert not calls
    assert create_config._project_state("valid-project-1") == {
        "state": "absent",
        "details": None,
        "error": None,
    }
    assert calls == [
        (
            ["projects", "describe", "valid-project-1", "--format=json"],
            False,
        )
    ]

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=True: completed_process(
            command,
            stdout='{"projectId": "valid-project-1"}',
        ),
    )
    assert create_config._project_state("valid-project-1") == {
        "state": "available",
        "details": {"projectId": "valid-project-1"},
        "error": None,
    }

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=True: completed_process(
            command,
            returncode=1,
            stderr=(
                "PERMISSION_DENIED: the caller does not have permission "
                "(or it may not exist)"
            ),
        ),
    )
    assert create_config._project_state("valid-project-1") == {
        "state": "unverified",
        "details": None,
        "error": (
            "the project is either unused or inaccessible to the selected account"
        ),
    }


# @matrix setup : gcloud-config gcloud-token interactive-input
def test_gcloud_account_selection_requires_an_explicit_authenticated_identity(
    monkeypatch,
    isolated_setup_config,
    capsys,
):
    from installer import create_config
    from runner import gcloud

    checked = []
    commands = []
    monkeypatch.setattr(
        gcloud,
        "check_account_authentication",
        lambda account: checked.append(account),
    )
    def run_gcloud(command, **kwargs):
        commands.append((command, kwargs))
        if command[:2] == ["auth", "list"]:
            return completed_process(command, stdout="installer@example.com\n")
        return completed_process(command, stdout="short-lived-token")

    monkeypatch.setattr(create_config, "run_gcloud_command", run_gcloud)
    answers = iter(["maybe", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert create_config._get_gcloud_account("") == "installer@example.com"
    assert checked == ["installer@example.com"]
    assert commands == [
        (
            [
                "auth",
                "list",
                "--filter=status:ACTIVE",
                "--format=value(account)",
            ],
            {"check": False},
        ),
        (
            ["auth", "print-access-token", "installer@example.com"],
            {"check": False, "timeout": 60},
        )
    ]
    output = capsys.readouterr().out
    assert "The active gcloud CLI account is: installer@example.com" in output
    assert "Enter Y to confirm this account" in output
    assert (
        "[OK] Verified gcloud CLI installation account: installer@example.com"
        in output
    )

    commands.clear()
    checked.clear()
    assert create_config._get_gcloud_account("saved@example.com") == (
        "saved@example.com"
    )
    assert checked == ["saved@example.com"]
    assert commands == []

    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    with pytest.raises(SetupCancelled, match="account confirmation"):
        create_config._get_gcloud_account("")
    assert "gcloud auth login" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, **kwargs: (
            completed_process(command, stdout="installer@example.com\n")
            if command[:2] == ["auth", "list"]
            else completed_process(command, returncode=1, stderr="login expired")
        ),
    )
    with pytest.raises(RuntimeError, match="could not be verified"):
        create_config._get_gcloud_account("")


# @matrix setup : interactive-input project-id
def test_project_id_selection_prefers_requested_name_and_suffixes_collisions(
    monkeypatch,
    isolated_setup_config,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(create_config.secrets, "token_hex", lambda length: "abc123")
    monkeypatch.setattr(
        create_config,
        "_gcloud_debug_value",
        lambda command: {
            "state": create_config.GCLOUD_VALUE_UNSET,
            "value": None,
            "error": None,
            "command": command,
        },
    )
    inspected = []
    monkeypatch.setattr(
        create_config,
        "_project_state",
        lambda project_id: inspected.append(project_id)
        or {
            "state": "unverified",
            "details": None,
            "error": "unused or inaccessible",
        },
    )
    prompts = []
    answers = iter(["", "y"])
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or next(answers),
    )

    assert create_config._get_gcloud_project("", "demo-app") == "demo-app"
    assert inspected == ["demo-app"]
    assert create_config.validate_project_id("demo-app")
    assert prompts == [
        (
            "Press Enter to use the suggested Google Cloud project ID "
            "[demo-app], or type a different project ID: "
        ),
        "Create a new project 'demo-app'? [y/N]: ",
    ]

    def matching_active_config(command):
        value = (
            "active-project-1"
            if command == ["config", "get-value", "project"]
            else "demo-app"
        )
        return {
            "state": create_config.GCLOUD_VALUE_SUCCESS,
            "value": value,
            "error": None,
            "command": command,
        }

    monkeypatch.setattr(
        create_config,
        "_gcloud_debug_value",
        matching_active_config,
    )
    monkeypatch.setattr(
        create_config,
        "_project_state",
        lambda project_id: {
            "state": (
                "available"
                if project_id == "active-project-1"
                else "unverified"
            ),
            "details": (
                {"projectId": project_id}
                if project_id == "active-project-1"
                else None
            ),
            "error": None,
        },
    )
    prompts.clear()
    answers = iter(["y"])
    assert (
        create_config._get_gcloud_project("", "demo-app")
        == "active-project-1"
    )
    assert prompts == ["Use the existing project 'active-project-1'? [y/N]: "]

    monkeypatch.setattr(
        create_config,
        "_project_state",
        lambda project_id: {
            "state": (
                "available"
                if project_id in {"active-project-1", "demo-app"}
                else "unverified"
            ),
            "details": (
                {"projectId": project_id}
                if project_id in {"active-project-1", "demo-app"}
                else None
            ),
            "error": None,
        },
    )
    prompts.clear()
    answers = iter(["n", "", "n", "", "y"])
    assert create_config._get_gcloud_project("", "demo-app") == "demo-app-abc123"
    assert prompts == [
        "Use the existing project 'active-project-1'? [y/N]: ",
        (
            "Press Enter to use the suggested Google Cloud project ID "
            "[demo-app], or type a different project ID: "
        ),
        "Use the existing project 'demo-app'? [y/N]: ",
        (
            "Press Enter to use the suggested Google Cloud project ID "
            "[demo-app-abc123], or type a different project ID: "
        ),
        "Create a new project 'demo-app-abc123'? [y/N]: ",
    ]

    def matching_exact_active_config(command):
        result = matching_active_config(command)
        if command == ["config", "get-value", "project"]:
            result["value"] = "demo-app"
        return result

    monkeypatch.setattr(
        create_config,
        "_gcloud_debug_value",
        matching_exact_active_config,
    )
    prompts.clear()
    answers = iter(["n", "", "y"])
    assert create_config._get_gcloud_project("", "demo-app") == "demo-app-abc123"
    assert prompts == [
        "Use the existing project 'demo-app'? [y/N]: ",
        (
            "Press Enter to use the suggested Google Cloud project ID "
            "[demo-app-abc123], or type a different project ID: "
        ),
        "Create a new project 'demo-app-abc123'? [y/N]: ",
    ]

    def mismatched_active_config(command):
        result = matching_active_config(command)
        if command != ["config", "get-value", "project"]:
            result["value"] = "different-installation"
        return result

    monkeypatch.setattr(
        create_config,
        "_gcloud_debug_value",
        mismatched_active_config,
    )
    prompts.clear()
    answers = iter(["", "y"])
    assert (
        create_config._get_gcloud_project("", "new-lagniappe")
        == "new-lagniappe"
    )
    assert not any("active-project-1" in prompt for prompt in prompts)

    prompts.clear()
    answers = iter(["", "n"])
    with pytest.raises(
        SetupCancelled,
        match="Installation cancelled during project selection",
    ):
        create_config._get_gcloud_project("", "new-lagniappe")
    assert prompts[-1] == (
        "Create a new project 'new-lagniappe'? [y/N]: "
    )


# @matrix setup : delegated-install existing-project gcloud-config interactive-input project-iam project-picker provider-discovery
def test_delegated_project_picker_lists_only_direct_owner_projects(
    monkeypatch,
    isolated_setup_config,
    capsys,
):
    from installer import create_config

    commands = []
    discovered = [
        {
            "projectId": "zulu-project-1",
            "name": "Zulu Project",
            "projectNumber": "300",
        },
        {
            "projectId": "alpha-project-1",
            "displayName": "Alpha Project",
            "name": "projects/100",
            "projectNumber": "100",
        },
        {"projectId": "bad", "name": "Invalid ID"},
    ]

    def run_gcloud(command, check=True):
        commands.append((command, check))
        if command[:2] == ["projects", "list"]:
            return completed_process(command, stdout=json.dumps(discovered))
        project_id = command[2]
        condition = (
            {
                "title": "temporary",
                "expression": (
                    "request.time < timestamp('2030-01-01T00:00:00Z')"
                ),
            }
            if project_id == "alpha-project-1"
            else None
        )
        binding = {
            "role": "roles/owner",
            "members": ["user:installer@example.com"],
        }
        if condition:
            binding["condition"] = condition
        return completed_process(
            command,
            stdout=json.dumps({"bindings": [binding]}),
        )

    monkeypatch.setattr(create_config, "run_gcloud_command", run_gcloud)
    inspected = []
    monkeypatch.setattr(
        create_config,
        "_project_state",
        lambda project_id: inspected.append(project_id)
        or {
            "state": "available",
            "details": {"projectId": project_id},
            "error": None,
        },
    )
    answers = iter(["9", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert create_config._select_existing_gcloud_project(
        "installer@example.com"
    ) == ("Zulu Project", "zulu-project-1")
    assert commands[0] == (
        [
            "projects",
            "list",
            "--filter=lifecycleState=ACTIVE",
            "--format=json",
            "--account=installer@example.com",
        ],
        False,
    )
    assert [command[0][2] for command in commands[1:]] == [
        "alpha-project-1",
        "zulu-project-1",
    ]
    assert inspected == ["zulu-project-1"]
    output = capsys.readouterr().out
    assert "Alpha Project" not in output
    assert "1. Zulu Project (zulu-project-1)" in output
    assert "Enter one of the project numbers shown above" in output

    commands.clear()
    inspected.clear()
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    assert create_config._select_existing_gcloud_project(
        "installer@example.com", direct_owner_required=False
    ) == ("Alpha Project", "alpha-project-1")
    assert commands == [
        (
            [
                "projects",
                "list",
                "--filter=lifecycleState=ACTIVE",
                "--format=json",
                "--account=installer@example.com",
            ],
            False,
        )
    ]
    assert inspected == ["alpha-project-1"]
    output = capsys.readouterr().out
    assert "projects accessible to installer@example.com" in output
    assert "1. Alpha Project (alpha-project-1)" in output
    assert "2. Zulu Project (zulu-project-1)" in output

    def no_owner_projects(command, check=True):
        if command[:2] == ["projects", "list"]:
            return completed_process(
                command,
                stdout=json.dumps([discovered[1]]),
            )
        return completed_process(
            command,
            stdout=json.dumps(
                {
                    "bindings": [
                        {
                            "role": "roles/owner",
                            "members": ["user:installer@example.com"],
                            "condition": {"title": "conditional"},
                        }
                    ]
                }
            ),
        )

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        no_owner_projects,
    )
    with pytest.raises(
        RuntimeError,
        match="direct, unconditional Project Owner role",
    ):
        create_config._list_owned_projects("installer@example.com")


# @matrix setup : delegated-install interactive-input ordinary-install project-picker
def test_initial_target_choice_uses_delegated_picker_or_ordinary_name_flow(
    monkeypatch,
    isolated_setup_config,
    capsys,
):
    from installer import create_config

    selections = []

    def select_existing(account, *, direct_owner_required):
        selections.append((account, direct_owner_required))
        return "Existing App", "existing-project-1"

    monkeypatch.setattr(
        create_config,
        "_select_existing_gcloud_project",
        select_existing,
    )
    monkeypatch.setattr(
        create_config,
        "_get_app_name",
        lambda: pytest.fail("existing project should supply the app name"),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert create_config._select_initial_target("installer@example.com") == (
        "Existing App",
        "existing-project-1",
    )
    assert selections == [("installer@example.com", True)]

    answers = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert create_config._select_initial_target("installer@example.com") == (
        "Existing App",
        "existing-project-1",
    )
    assert selections[-1] == ("installer@example.com", False)

    monkeypatch.setattr(create_config, "_get_app_name", lambda: "New App")
    monkeypatch.setattr(
        create_config,
        "_get_gcloud_project",
        lambda project_id, sanitized_name: "new-app-project-1",
    )
    answers = iter(["maybe", "n", "maybe", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert create_config._select_initial_target("installer@example.com") == (
        "New App",
        "new-app-project-1",
    )
    output = capsys.readouterr().out
    assert "Enter Y for a delegated installation" in output
    assert "Enter Y to select an existing project" in output


# @matrix setup : adc gcloud-config
def test_adc_identity_reports_principal_project_and_quota(
    monkeypatch,
    isolated_setup_config,
):
    from installer import create_config
    import installer.utils as setup_utils
    import google.auth

    credentials = types.SimpleNamespace(quota_project_id="quota-project-1")
    requested_scopes = []

    monkeypatch.setattr(setup_utils, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: requested_scopes.extend(scopes)
        or (credentials, "adc-project-1"),
    )
    monkeypatch.setattr(
        create_config,
        "_get_current_account_email",
        lambda selected_credentials: "owner@example.com",
    )

    assert create_config._adc_identity() == {
        "state": "success",
        "principal": "owner@example.com",
        "project": "adc-project-1",
        "quota_project": "quota-project-1",
        "error": None,
    }
    assert "https://www.googleapis.com/auth/cloud-platform" in requested_scopes


# @matrix setup : adc gcloud-config identity
def test_adc_principal_mismatch_requires_explicit_reauthentication(
    monkeypatch,
    isolated_setup_config,
    capsys,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    identities = iter(
        [
            {
                "state": "success",
                "principal": "wrong@example.com",
                "project": "old-project-1",
                "quota_project": "old-project-1",
                "error": None,
            },
            {
                "state": "success",
                "principal": "owner@example.com",
                "project": "target-project-1",
                "quota_project": "target-project-1",
                "error": None,
            },
        ]
    )
    login_calls = []
    monkeypatch.setattr(create_config, "_adc_identity", lambda: next(identities))
    monkeypatch.setattr(
        create_config,
        "_run_adc_login",
        lambda account, project_id=None: login_calls.append((account, project_id))
        or completed_process(),
    )

    identity = create_config._ensure_adc_principal(
        "owner@example.com",
        "target-project-1",
    )

    assert identity["principal"] == "owner@example.com"
    assert login_calls == [("owner@example.com", "target-project-1")]
    output = capsys.readouterr().out
    assert "First-time Google Cloud use" in output
    assert create_config.GOOGLE_CLOUD_TERMS_URL in output
    assert "owner@example.com" in output


# @matrix setup : billing gcloud-config interactive-input
def test_billing_selection_defers_to_project_console_when_cli_returns_no_open_account(
    monkeypatch,
    capsys,
    isolated_setup_config,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail(f"billing selection should be deferred: {prompt}"),
    )

    assert create_config._select_billing_account([]) is None
    assert create_config._select_billing_account(
        [
            {
                "name": "billingAccounts/closed-1",
                "displayName": "Closed",
                "open": False,
            }
        ]
    ) is None
    assert capsys.readouterr().out == ""


# @matrix setup : billing browser interactive-input
def test_project_billing_authorization_uses_existing_account_and_project_console(
    monkeypatch,
    capsys,
    isolated_setup_config,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    opened = []
    monkeypatch.setattr(
        create_config.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or True,
    )
    billing_states = iter(
        [
            {"billingEnabled": False},
            {
                "billingEnabled": True,
                "billingAccountName": "billingAccounts/billing-1",
            },
        ]
    )
    checks = []
    monkeypatch.setattr(
        create_config,
        "_load_gcloud_json",
        lambda command, description: checks.append((command, description))
        or next(billing_states),
    )
    prompts = []
    answers = iter(["", ""])
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or next(answers),
    )

    assert (
        create_config._authorize_project_billing("target-project-1")
        == "billing-1"
    )
    assert opened == [
        "https://console.cloud.google.com/billing/linkedaccount"
        "?project=target-project-1"
    ]
    assert len(checks) == 2
    assert prompts[0] == (
        "After the existing billing account is linked, press Enter to "
        "continue (x to exit): "
    )
    output = capsys.readouterr().out
    assert "select 'Link a billing account'" in output
    assert "existing billing account" in output
    assert "create a billing account" not in output


# @matrix setup : billing preflight provider-apis
def test_target_preflight_selects_billing_and_reports_required_apis(
    monkeypatch,
    isolated_setup_config,
):
    from installer import create_config

    fake_config = types.SimpleNamespace(
        constants=types.SimpleNamespace(
            REQUIRED_GOOGLE_CLOUD_APIS={
                "enabled.googleapis.com": "Enabled",
                "missing.googleapis.com": "Missing",
            }
        )
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setattr(
        create_config,
        "_project_state",
        lambda project_id: {"state": "available", "details": {}, "error": None},
    )

    def fake_load(command, description):
        if command[:3] == ["billing", "accounts", "list"]:
            assert command == [
                "billing",
                "accounts",
                "list",
                "--format=json",
            ]
            return [
                {
                    "name": "billingAccounts/billing-1",
                    "displayName": "Primary",
                    "open": True,
                }
            ]
        assert command[:3] == ["billing", "projects", "describe"]
        return {"billingEnabled": False}

    monkeypatch.setattr(create_config, "_load_gcloud_json", fake_load)
    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=False: completed_process(
            command,
            stdout="enabled.googleapis.com\n",
        ),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail(
            f"the sole existing billing account should be automatic: {prompt}"
        ),
    )

    preflight = create_config._target_preflight("target-project-1")

    assert preflight["billing_account"] == "billing-1"
    assert not preflight["billing_enabled"]
    assert preflight["enabled_apis"] == {"enabled.googleapis.com"}
    assert preflight["missing_apis"] == ["missing.googleapis.com"]


# @matrix setup : billing preflight project-create provider-apis
def test_target_preflight_defers_billing_discovery_until_new_project_exists(
    monkeypatch,
    isolated_setup_config,
):
    from installer import create_config

    fake_config = types.SimpleNamespace(
        constants=types.SimpleNamespace(
            REQUIRED_GOOGLE_CLOUD_APIS={"one.googleapis.com": "One"}
        )
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setattr(
        create_config,
        "_project_state",
        lambda project_id: {"state": "absent", "details": None, "error": None},
    )
    monkeypatch.setattr(
        create_config,
        "_load_gcloud_json",
        lambda command, description: pytest.fail(
            f"provider discovery ran before the new project existed: {command}"
        ),
    )

    preflight = create_config._target_preflight("target-project-1")

    assert preflight["billing_account"] is None
    assert not preflight["billing_enabled"]
    assert preflight["enabled_apis"] == set()
    assert preflight["missing_apis"] == ["one.googleapis.com"]


# @matrix setup : billing preflight project-create
def test_apply_target_preflight_creates_and_bills_confirmed_project(
    monkeypatch,
    isolated_setup_config,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    events = []

    def fake_gcloud(command, check=False, **kwargs):
        events.append(command)
        return completed_process(command)

    monkeypatch.setattr(create_config, "run_gcloud_command", fake_gcloud)
    monkeypatch.setattr(
        create_config,
        "_load_gcloud_json",
        lambda command, description: events.append(command)
        or {
            "billingEnabled": True,
            "billingAccountName": "billingAccounts/billing-1",
        },
    )
    preflight = {
        "project": {
            "state": "unverified",
            "details": None,
            "error": "unused or inaccessible",
        },
        "billing_account": "billing-1",
        "billing_enabled": False,
        "enabled_apis": set(create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS),
        "missing_apis": ["one.googleapis.com"],
    }

    create_config._apply_target_preflight(
        "target-project-1",
        preflight,
        project_ready=lambda: events.append("project-ready"),
    )

    assert events == [
        ["projects", "create", "target-project-1"],
        "project-ready",
        [
            "billing",
            "projects",
            "link",
            "target-project-1",
            "--billing-account=billing-1",
        ],
        [
            "billing",
            "projects",
            "describe",
            "target-project-1",
            "--format=json",
        ],
        [
            "services",
            "list",
            "--enabled",
            "--project=target-project-1",
            "--format=value(config.name)",
        ],
    ]


# @matrix setup : billing browser preflight project-create
def test_apply_target_preflight_authorizes_billing_after_project_creation_when_cli_list_is_empty(
    monkeypatch,
    isolated_setup_config,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    events = []

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=False, **kwargs: events.append(command)
        or completed_process(command),
    )
    monkeypatch.setattr(
        create_config,
        "_authorize_project_billing",
        lambda project_id: events.append(["authorize-billing", project_id])
        or "billing-1",
    )
    monkeypatch.setattr(
        create_config,
        "_load_gcloud_json",
        lambda command, description: (
            events.append(command)
            or (
                []
                if command[:3] == ["billing", "accounts", "list"]
                else {
                    "billingEnabled": True,
                    "billingAccountName": "billingAccounts/billing-1",
                }
            )
        ),
    )
    preflight = {
        "project": {"state": "absent", "details": None, "error": None},
        "billing_account": None,
        "billing_enabled": False,
        "enabled_apis": set(),
        "missing_apis": ["one.googleapis.com"],
    }

    create_config._apply_target_preflight(
        "target-project-1",
        preflight,
        project_ready=lambda: events.append("project-ready"),
    )

    assert preflight["billing_account"] == "billing-1"
    assert events[:4] == [
        ["projects", "create", "target-project-1"],
        [
            "services",
            "enable",
            "cloudbilling.googleapis.com",
            "cloudresourcemanager.googleapis.com",
            "serviceusage.googleapis.com",
            "--project=target-project-1",
            "--quiet",
        ],
        ["billing", "accounts", "list", "--format=json"],
        "project-ready",
    ]
    assert ["authorize-billing", "target-project-1"] in events


# @matrix setup : billing preflight project-create provider-apis
def test_apply_target_preflight_rediscovers_and_links_existing_billing_account(
    monkeypatch,
    isolated_setup_config,
):
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    events = []

    def fake_gcloud(command, check=False, **kwargs):
        events.append(command)
        if command[:3] == ["services", "list", "--enabled"]:
            return completed_process(
                command,
                stdout="\n".join(create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS),
            )
        return completed_process(command)

    def fake_load(command, description):
        events.append(command)
        if command[:3] == ["billing", "accounts", "list"]:
            return [
                {
                    "name": "billingAccounts/billing-1",
                    "displayName": "Primary",
                    "open": True,
                }
            ]
        return {
            "billingEnabled": True,
            "billingAccountName": "billingAccounts/billing-1",
        }

    monkeypatch.setattr(create_config, "run_gcloud_command", fake_gcloud)
    monkeypatch.setattr(create_config, "_load_gcloud_json", fake_load)
    monkeypatch.setattr(
        create_config,
        "_authorize_project_billing",
        lambda project_id: pytest.fail(
            "browser fallback should not run when the existing account is visible"
        ),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail(
            f"the sole existing billing account should be automatic: {prompt}"
        ),
    )
    preflight = {
        "project": {"state": "absent", "details": None, "error": None},
        "billing_account": None,
        "billing_enabled": False,
        "enabled_apis": set(),
        "missing_apis": sorted(create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS),
    }

    create_config._apply_target_preflight(
        "target-project-1",
        preflight,
        project_ready=lambda: events.append("project-ready"),
    )

    assert preflight["billing_account"] == "billing-1"
    assert events[:4] == [
        ["projects", "create", "target-project-1"],
        [
            "services",
            "enable",
            "cloudbilling.googleapis.com",
            "cloudresourcemanager.googleapis.com",
            "serviceusage.googleapis.com",
            "--project=target-project-1",
            "--quiet",
        ],
        ["billing", "accounts", "list", "--format=json"],
        "project-ready",
    ]
    assert [
        "billing",
        "projects",
        "link",
        "target-project-1",
        "--billing-account=billing-1",
    ] in events


# @matrix setup : error-guidance google-cloud-terms identity provider-apis
def test_google_cloud_terms_failure_has_account_specific_repair(
    monkeypatch,
    isolated_setup_config,
):
    import config
    import installer as setup_pkg
    from installer import create_config

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    config.SETTINGS.GCLOUD_CONFIG["ACCOUNT"] = "installer@business.example"
    provider_detail = (
        "ERROR: The terms of service 'cloud' must be accepted. "
        "violations: tos_id=cloud reason: UREQ_TOS_NOT_ACCEPTED "
        "Help Token: do-not-repeat-this-token"
    )
    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, **kwargs: completed_process(
            command,
            returncode=1,
            stderr=provider_detail,
        ),
    )
    preflight = {
        "project": {"state": "available", "details": {}, "error": None},
        "billing_account": "billing-1",
        "billing_enabled": True,
        "enabled_apis": set(),
        "missing_apis": sorted(create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS),
    }

    assert create_config._is_google_cloud_terms_error(provider_detail)
    assert not create_config._is_google_cloud_terms_error("permission denied")
    with pytest.raises(SetupError) as error:
        create_config._apply_target_preflight("project-1", preflight)

    assert "installer@business.example" in str(error.value)
    assert "Help Token" not in str(error.value)
    assert error.value.repair_action == (
        "Sign in as 'installer@business.example' at "
        f"{create_config.GOOGLE_CLOUD_TERMS_URL}, accept the Google Cloud "
        "service terms, then rerun ./setup.sh."
    )


# @matrix setup : app-name validation
def test_app_name_validation_rejects_control_characters_and_long_names(
    isolated_setup_config,
):
    from installer import create_config

    assert create_config._validate_app_name("My Installation")
    assert not create_config._validate_app_name("")
    assert not create_config._validate_app_name("bad\nname")
    assert not create_config._validate_app_name("bad\x7fname")
    assert not create_config._validate_app_name("x" * 81)
    assert create_config._gcloud_configuration_name("🎉") == "lagniappe"
    assert create_config._gcloud_configuration_name("A") == "a-setup"


# @matrix setup : gcloud-config identity
def test_cli_identity_snapshot_fails_closed_on_unset_or_error(
    monkeypatch,
    isolated_setup_config,
):
    from installer import create_config

    results = iter(
        [
            {
                "state": create_config.GCLOUD_VALUE_SUCCESS,
                "value": "demo",
                "error": None,
                "command": [],
            },
            {
                "state": create_config.GCLOUD_VALUE_UNSET,
                "value": None,
                "error": None,
                "command": [],
            },
            {
                "state": create_config.GCLOUD_VALUE_ERROR,
                "value": None,
                "error": "permission denied",
                "command": [],
            },
        ]
    )
    monkeypatch.setattr(create_config, "_gcloud_debug_value", lambda command: next(results))

    with pytest.raises(RuntimeError, match=r"account=\(unset\).*permission denied"):
        create_config._active_cli_identity()

    values = {
        "configurations": "demo",
        "account": "owner@example.com",
        "project": "target-project-1",
    }

    def successful_value(command):
        key = "configurations" if "configurations" in command else command[-1]
        return {
            "state": create_config.GCLOUD_VALUE_SUCCESS,
            "value": values[key],
            "error": None,
            "command": command,
        }

    monkeypatch.setattr(create_config, "_gcloud_debug_value", successful_value)
    assert create_config._active_cli_identity() == {
        "configuration": "demo",
        "account": "owner@example.com",
        "project": "target-project-1",
    }


# @pair setup:config-files
def test_set_application_defaults_deep_copies_templates(monkeypatch, tmp_path):
    _use_isolated_app_dir(monkeypatch, tmp_path)

    import config
    import runner.gcloud as switcher
    import installer as setup_pkg
    from config import constants
    from installer import create_config

    (tmp_path / "package.json").write_text(json.dumps({"version": "1.0.0"}))
    config.SETTINGS.NODE = config.File.PACKAGE_JSON.load()
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    config.SETTINGS.APP.update(
        {
            "APP_NAME": "My App",
            "ADMIN_NAME": "Owner",
            "ADMIN_EMAIL": "admin@example.com",
            "GOOGLE_SIGNIN_ENABLED": True,
            "DEPLOY_SCALING_TYPE": "automatic",
            "DEPLOY_MAX_INSTANCES": "2",
            "DEPLOY_IDLE_TIMEOUT": "15m",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "F2",
            "DEPLOY_MIN_IDLE_INSTANCES": "1",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
                "svc@my-project-1.iam.gserviceaccount.com"
            ),
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                "svc@my-project-1.iam.gserviceaccount.com"
            ),
        }
    )
    monkeypatch.setattr(
        create_config, "_get_gcloud_account", lambda account: "admin@example.com"
    )
    monkeypatch.setattr(
        create_config,
        "_get_gcloud_project",
        lambda project_id, sanitized_app_name: "my-project-1",
    )
    monkeypatch.setattr(switcher, "config_gcloud", lambda: None)
    monkeypatch.setattr(
        create_config, "_set_adc_quota_project", lambda project, sp: None
    )
    _stub_existing_install_preflight(
        monkeypatch,
        create_config,
        app_name="My App",
        account="admin@example.com",
        project_id="my-project-1",
    )

    assert create_config.set_application_defaults()

    app_yaml = yaml.safe_load((tmp_path / "lagniappe.yaml").read_text())
    dev_config = yaml.safe_load(
        (tmp_path / "config" / "files" / "lagniappe_dev.yaml").read_text()
    )

    assert app_yaml["service_account"] == (
        "svc@my-project-1.iam.gserviceaccount.com"
    )
    assert app_yaml["inbound_services"] == ["warmup"]
    assert app_yaml["handlers"] == constants.APP_HANDLERS
    assert dev_config["gcloud_config"]["PROJECT"] == "my-project-1"
    assert dev_config["gcloud_config"]["ACCOUNT"] == "admin@example.com"


# @pair setup:config-files
def test_set_application_defaults_generates_fresh_settings(monkeypatch, tmp_path):
    _use_isolated_app_dir(monkeypatch, tmp_path)

    import config
    import runner.gcloud as switcher
    import installer as setup_pkg
    from installer import create_config

    (tmp_path / "package.json").write_text(json.dumps({"version": "9.8.7"}))
    config.SETTINGS.NODE = config.File.PACKAGE_JSON.load()
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    config.SETTINGS.APP["APP_NAME"] = "Fresh App"
    config.SETTINGS.APP["ADMIN_NAME"] = "Owner"
    config.SETTINGS.APP["ADMIN_EMAIL"] = "owner@example.com"
    config.SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] = True

    token_calls = []

    def fake_token_hex(length):
        token_calls.append(length)
        return f"token-{length}"

    monkeypatch.setattr(create_config.secrets, "token_hex", fake_token_hex)
    monkeypatch.setattr(
        create_config.secrets,
        "token_urlsafe",
        lambda length: f"url-token-{length}",
    )
    monkeypatch.setattr(
        create_config, "_get_gcloud_account", lambda account: "owner@example.com"
    )
    monkeypatch.setattr(
        create_config,
        "_get_gcloud_project",
        lambda project_id, sanitized_app_name: "fresh-project-1",
    )
    monkeypatch.setattr(switcher, "config_gcloud", lambda: None)
    monkeypatch.setattr(
        create_config, "_set_adc_quota_project", lambda project, sp: None
    )
    _stub_existing_install_preflight(
        monkeypatch,
        create_config,
        app_name="Fresh App",
        account="owner@example.com",
        project_id="fresh-project-1",
    )

    assert create_config.set_application_defaults()

    settings = yaml.safe_load(
        (tmp_path / "config" / "files" / "lagniappe_settings.yaml").read_text()
    )
    dev_config = yaml.safe_load(
        (tmp_path / "config" / "files" / "lagniappe_dev.yaml").read_text()
    )

    assert settings["APP_NAME"] == "Fresh App"
    assert settings["GOOGLE_CLOUD_PROJECT"] == "fresh-project-1"
    assert settings["INSTALLER_EMAIL"] == "owner@example.com"
    assert settings["DEPLOYER_EMAIL"] == "owner@example.com"
    assert settings["ADMIN_EMAIL"] == "owner@example.com"
    assert settings["BOOTSTRAP_ADMIN_EMAIL"] == ""
    assert settings["VERSION"] == "9.8.7"
    assert "BUILD_ID" not in settings
    assert settings["GIBBERISH"] == "token-16"
    assert settings["SECRET_KEY"] == "token-32"
    assert settings["AGENT_ACCESS_ENABLED"] == "False"
    assert settings["AGENT_ACCESS_EMAIL"] == "agent@localhost"
    assert settings["AGENT_ACCESS_NAME"] == "Agent"
    assert settings["AGENT_ACCESS_CODE"] == "url-token-32"
    app_yaml = yaml.safe_load((tmp_path / "lagniappe.yaml").read_text())
    assert "inbound_services" not in app_yaml
    assert token_calls == [16, 32]
    assert dev_config["gcloud_config"] == {
        "NAME": "fresh-app",
        "ACCOUNT": "owner@example.com",
        "PROJECT": "fresh-project-1",
        "BILLING_ACCOUNT": "billing-1",
    }


# @matrix setup : config-files gcloud-config interactive-input
def test_set_application_defaults_persists_prompted_name_before_cloud_change(
    monkeypatch,
    tmp_path,
    capsys,
):
    _use_isolated_app_dir(monkeypatch, tmp_path)

    import config
    import runner.gcloud as switcher
    from installer import admin
    from installer import create_config

    (tmp_path / "package.json").write_text(json.dumps({"version": "1.0.0"}))
    config.SETTINGS.NODE = config.File.PACKAGE_JSON.load()

    account = "owner@example.com"
    project_id = "named-project-1"
    identity = {
        "state": "success",
        "principal": account,
        "project": None,
        "quota_project": None,
        "error": None,
    }
    preflight = {
        "project": {"state": "absent", "details": None, "error": None},
        "billing_account": None,
        "billing_enabled": False,
        "enabled_apis": set(),
        "missing_apis": ["one.googleapis.com"],
    }
    cloud_boundary = []
    adc_events = []
    permission_checks = []

    monkeypatch.setattr(
        create_config,
        "_select_initial_target",
        lambda selected_account: ("Named App", project_id),
    )
    monkeypatch.setattr(
        admin,
        "collect_owner_and_signin_choice",
        lambda selected_installer: config.SETTINGS.APP.update(
            {"ADMIN_NAME": "Owner", "ADMIN_EMAIL": account}
        )
        or True,
    )
    monkeypatch.setattr(create_config, "_get_gcloud_account", lambda saved: account)
    monkeypatch.setattr(switcher, "config_gcloud", lambda: None)
    monkeypatch.setattr(
        create_config,
        "_active_cli_identity",
        lambda: {
            "configuration": "named-app",
            "account": account,
            "project": project_id,
        },
    )
    def target_preflight(target):
        draft = config.File.DEV_YAML.load()
        assert draft["setup_draft"] == {"APP_NAME": "Named App"}
        assert draft["gcloud_config"]["NAME"] == "named-app"
        assert draft["gcloud_config"]["ACCOUNT"] == account
        assert draft["gcloud_config"]["PROJECT"] == project_id
        return preflight

    monkeypatch.setattr(create_config, "_target_preflight", target_preflight)
    monkeypatch.setattr(
        create_config,
        "_ensure_adc_principal",
        lambda selected_account, target=None: adc_events.append(
            ("premature-adc", selected_account, target)
        ),
    )
    monkeypatch.setattr(
        create_config,
        "_set_adc_quota_project",
        lambda target, spinner: adc_events.append(("project-adc", target))
        or {
            **identity,
            "project": project_id,
            "quota_project": project_id,
        },
    )
    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda target, **kwargs: permission_checks.append((target, kwargs))
        or {
            "installer": [],
            "billing": [],
            "deployer": [],
        },
    )

    def apply_preflight(target, target_preflight, project_ready=None):
        persisted = config.File.APP_SETTINGS_YAML.load()
        cloud_boundary.append(
            {
                "target": target,
                "app_name": persisted["APP_NAME"],
                "saved_project": persisted["GOOGLE_CLOUD_PROJECT"],
                "dev_exists": config.File.DEV_YAML.exists(),
                "app_yaml_exists": config.File.APP_YAML.exists(),
            }
        )
        assert project_ready is not None
        project_ready()
        target_preflight["billing_account"] = "billing-1"

    monkeypatch.setattr(
        create_config,
        "_apply_target_preflight",
        apply_preflight,
    )
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "y",
    )

    assert create_config.set_application_defaults()
    output = capsys.readouterr().out
    assert "=== Configuration ===" in output
    assert "Creating the confirmed local configuration draft" not in output
    assert "ADC authentication: after project creation" not in output
    assert "Project state:" not in output
    assert prompts[-1] == "Continue with installation? [y/N]: "
    assert config.SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS == set()
    assert cloud_boundary == [
        {
            "target": project_id,
            "app_name": "Named App",
            "saved_project": project_id,
            "dev_exists": True,
            "app_yaml_exists": True,
        }
    ]
    assert adc_events == [("project-adc", project_id)]
    assert permission_checks == [
        (
            project_id,
            {
                "billing_account": None,
                "require_billing_link": False,
            },
        )
    ]
    assert config.File.DEV_YAML.load()["gcloud_config"]["BILLING_ACCOUNT"] == (
        "billing-1"
    )

    monkeypatch.setattr(
        create_config,
        "_apply_target_preflight",
        lambda *args, **kwargs: pytest.fail(
            "cloud mutation must not run after cancellation"
        ),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    with pytest.raises(SetupCancelled):
        create_config.set_application_defaults()

    persisted = config.File.APP_SETTINGS_YAML.load()
    assert persisted["APP_NAME"] == "Named App"
    assert persisted["GOOGLE_CLOUD_PROJECT"] == project_id
    assert config.File.DEV_YAML.exists()
    assert config.File.APP_YAML.exists()
    assert "setup_draft" not in config.File.DEV_YAML.load()


# @matrix setup : adc existing-project interactive-input preconfirmation provider-apis
def test_existing_project_prepares_bootstrap_apis_before_adc(
    monkeypatch,
    tmp_path,
):
    _use_isolated_app_dir(monkeypatch, tmp_path)

    import config
    import installer as setup_pkg
    import runner.gcloud as switcher
    from installer import create_config

    (tmp_path / "package.json").write_text(json.dumps({"version": "1.0.0"}))
    config.SETTINGS.NODE = config.File.PACKAGE_JSON.load()
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    account = "owner@example.com"
    project_id = "existing-project-1"
    config.SETTINGS.APP.update(
        {
            "APP_NAME": "Existing App",
            "ADMIN_NAME": "Owner",
            "ADMIN_EMAIL": account,
            "GOOGLE_SIGNIN_ENABLED": True,
        }
    )
    monkeypatch.setattr(create_config, "_get_gcloud_account", lambda saved: account)
    monkeypatch.setattr(
        create_config,
        "_get_gcloud_project",
        lambda saved, generated: project_id,
    )
    monkeypatch.setattr(switcher, "config_gcloud", lambda: None)
    monkeypatch.setattr(
        create_config,
        "_active_cli_identity",
        lambda: {
            "configuration": "existing-app",
            "account": account,
            "project": project_id,
        },
    )
    preflight = {
        "project": {"state": "available", "details": {}, "error": None},
        "billing_account": "billing-1",
        "billing_enabled": True,
        "enabled_apis": set(),
        "missing_apis": sorted(create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS),
    }
    monkeypatch.setattr(create_config, "_target_preflight", lambda target: preflight)
    monkeypatch.setattr(
        create_config,
        "_preflight_operator_authority",
        lambda selected_account, target: object(),
    )
    monkeypatch.setattr(
        create_config,
        "_ensure_adc_principal",
        lambda *args: pytest.fail(
            "ADC must wait until the missing management APIs are prepared"
        ),
    )
    events = []
    identity = {
        "state": "success",
        "principal": account,
        "project": project_id,
        "quota_project": project_id,
        "error": None,
    }
    monkeypatch.setattr(
        create_config,
        "_set_adc_quota_project",
        lambda target, spinner: events.append("adc") or identity,
    )
    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda target, **kwargs: events.append("permissions") or {},
    )
    monkeypatch.setattr(
        create_config,
        "_display_install_identity_summary",
        lambda target_preflight, adc: events.append(("summary", adc["state"])),
    )

    def apply_preflight(target, target_preflight, project_ready=None):
        events.append("prepare-apis")
        assert project_ready is not None
        target_preflight["enabled_apis"].update(
            create_config.BOOTSTRAP_GOOGLE_CLOUD_APIS
        )
        project_ready()

    monkeypatch.setattr(create_config, "_apply_target_preflight", apply_preflight)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert create_config.set_application_defaults()
    assert events == [
        ("summary", "pending"),
        "prepare-apis",
        "adc",
        "permissions",
    ]


# @matrix admin : bootstrap-email google-oauth google-signin interactive-input prompt-clarity
# @matrix setup : billing delegated-install existing-project owner preconfirmation project-iam
def test_delegated_setup_automatically_enables_google_and_installer_bootstrap(
    monkeypatch, tmp_path, capsys
):
    _use_isolated_app_dir(monkeypatch, tmp_path)

    import config
    from installer import admin, create_config

    monkeypatch.setattr(admin, "_get_admin_name", lambda: "Business Owner")
    monkeypatch.setattr(
        admin, "_get_admin_email", lambda: "OWNER@business.example"
    )
    monkeypatch.setattr(
        admin,
        "configure_google_signin_choice",
        lambda: pytest.fail(
            "delegated setup must not ask whether to enable Google sign-in"
        ),
    )

    assert admin.collect_owner_and_signin_choice(
        "INSTALLER@business.example"
    ) is True
    assert config.SETTINGS.APP["ADMIN_NAME"] == "Business Owner"
    assert config.SETTINGS.APP["ADMIN_EMAIL"] == "owner@business.example"
    assert config.SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] is True
    owner_prompt = capsys.readouterr().out
    normalized_owner_prompt = " ".join(owner_prompt.split())
    assert "Permanent site Owner" in normalized_owner_prompt
    assert (
        "exact Google account email, not a forwarding alias"
        in normalized_owner_prompt
    )
    assert (
        "Owner does not need to sign in on this computer"
        in normalized_owner_prompt
    )

    new_project = {
        "project": {"state": "absent"},
        "billing_enabled": False,
    }
    with pytest.raises(RuntimeError, match="existing Google Cloud project"):
        create_config._configure_delegated_bootstrap(
            new_project, "INSTALLER@business.example"
        )

    ready_project = {
        "project": {"state": "available"},
        "billing_enabled": True,
    }
    events = []
    project_client = object()

    def check_owner(project_id, owner_email, *, client=None):
        events.append(("owner", project_id, owner_email, client))
        return True

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail(
            "delegated bootstrap access must not require another prompt"
        ),
    )
    config.SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] = False
    config.SETTINGS.APP["BOOTSTRAP_ADMIN_EMAIL"] = ""
    assert create_config._configure_delegated_bootstrap(
        ready_project,
        "INSTALLER@business.example",
        project_id="project-1",
        project_client=project_client,
        owner_checker=check_owner,
    )
    assert config.SETTINGS.APP["BOOTSTRAP_ADMIN_EMAIL"] == (
        "installer@business.example"
    )
    assert config.SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] is True
    assert events == [
        (
            "owner",
            "project-1",
            "owner@business.example",
            project_client,
        )
    ]
    output = capsys.readouterr().out
    assert "Delegated installer application access is ready" in output
    assert "permanent Owner binding was read" not in output
    assert "Allow this installer account" not in output

    signin_choices = []
    config.SETTINGS.APP["ADMIN_EMAIL"] = "installer@business.example"
    monkeypatch.setattr(
        admin,
        "configure_google_signin_choice",
        lambda: signin_choices.append("asked") or False,
    )
    assert admin.collect_owner_and_signin_choice(
        "installer@business.example"
    ) is False
    assert signin_choices == ["asked"]


# @matrix setup : adc gcloud-token operator-permissions preflight
def test_existing_project_checks_cli_installer_permissions_before_adc_authentication(
    monkeypatch,
    capsys,
):
    from installer import create_config

    events = []
    project_client = object()

    monkeypatch.setattr(
        create_config,
        "_gcloud_project_client",
        lambda account: events.append(("cli-token", account)) or project_client,
    )
    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda project_id, **kwargs: events.append(
            ("permissions", project_id, kwargs.get("client"))
        ),
    )
    monkeypatch.setattr(
        create_config,
        "_ensure_adc_principal",
        lambda *args, **kwargs: pytest.fail(
            "CLI authority preflight must not read or authenticate ADC"
        ),
    )

    assert create_config._preflight_operator_authority(
        "installer@example.test",
        "project-1",
    ) is project_client
    assert events == [
        ("cli-token", "installer@example.test"),
        ("permissions", "project-1", project_client),
    ]
    assert "gcloud CLI installer access is ready" in capsys.readouterr().out

    def reject_permissions(*args, **kwargs):
        raise RuntimeError("missing required permission")

    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        reject_permissions,
    )
    with pytest.raises(RuntimeError, match="before ADC authentication") as error:
        create_config._preflight_operator_authority(
            "installer@example.test",
            "project-1",
            client=project_client,
        )
    assert "Application Default Credentials were not changed" in str(error.value)
    assert "missing required permission" in str(error.value)


# @matrix setup : adc gcloud-token identity
def test_gcloud_project_client_uses_selected_cli_account_without_adc(monkeypatch):
    from google.cloud import resourcemanager_v3
    from google.oauth2 import credentials as oauth_credentials
    from installer import create_config
    from installer import utils

    events = []
    project_client = object()
    credential = object()

    monkeypatch.setattr(utils, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, **kwargs: events.append(
            ("gcloud", command, kwargs)
        )
        or completed_process(command, stdout="short-lived-token\n"),
    )
    monkeypatch.setattr(
        oauth_credentials,
        "Credentials",
        lambda *, token: events.append(("credential", token)) or credential,
    )
    monkeypatch.setattr(
        resourcemanager_v3,
        "ProjectsClient",
        lambda *, credentials: events.append(("client", credentials))
        or project_client,
    )

    assert create_config._gcloud_project_client(
        "installer@example.test"
    ) is project_client
    assert events == [
        (
            "gcloud",
            ["auth", "print-access-token", "installer@example.test"],
            {"check": False, "timeout": 60},
        ),
        ("credential", "short-lived-token"),
        ("client", credential),
    ]

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, **kwargs: completed_process(
            command,
            returncode=1,
            stderr="expired login",
        ),
    )
    with pytest.raises(RuntimeError, match=r"setup\.sh auth"):
        create_config._gcloud_project_client("installer@example.test")


# @matrix setup : config-files config-version
def test_update_config_sets_application_version_from_package(monkeypatch):
    from installer import create_config

    settings = types.SimpleNamespace(APP={"VERSION": "1.0"}, NODE={"version": "2.0"})
    calls = []

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=settings,
            constants=types.SimpleNamespace(DEFAULT_GOOGLE_SIGNIN_ENABLED=True),
        ),
    )
    def fake_set_default_config():
        calls.append(("defaults", settings.APP["VERSION"]))
        settings.APP.setdefault("AGENT_ACCESS_ENABLED", False)

    monkeypatch.setattr(create_config, "_set_default_config", fake_set_default_config)

    assert create_config.update_config() == "2.0"
    assert settings.APP["VERSION"] == "2.0"
    assert "BUILD_ID" not in settings.APP
    assert settings.APP["AGENT_ACCESS_ENABLED"] is False
    assert settings.APP["GOOGLE_SIGNIN_ENABLED"] is True
    assert calls == [("defaults", "2.0")]


# @matrix setup : agent-access ai-defaults config-files source-link
def test_build_app_settings_refreshes_agent_access_defaults(monkeypatch, tmp_path):
    _use_isolated_app_dir(monkeypatch, tmp_path)

    from config import constants
    from installer import create_config

    settings = types.SimpleNamespace(
        APP={
            "VERSION": "1.0",
            "GIBBERISH": "existing-gibberish",
            "SECRET_KEY": "existing-secret",
            "AGENT_ACCESS_ENABLED": True,
            "AGENT_ACCESS_EMAIL": "",
            "AGENT_ACCESS_NAME": "Review Agent",
            "AGENT_ACCESS_CODE": "",
        },
        GCLOUD_CONFIG={
            "NAME": "project-1",
            "PROJECT": "project-1",
            "ACCOUNT": "owner@example.com",
        },
        NODE={"version": "2.0"},
    )
    token_calls = []

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings, constants=constants),
    )
    monkeypatch.setattr(
        create_config.secrets,
        "token_urlsafe",
        lambda length: token_calls.append(length) or "generated-agent-code",
    )

    create_config._build_app_settings()

    assert settings.APP["AGENT_ACCESS_ENABLED"] is True
    assert settings.APP["AGENT_ACCESS_EMAIL"] == constants.DEFAULT_AGENT_ACCESS_EMAIL
    assert settings.APP["AGENT_ACCESS_NAME"] == "Review Agent"
    assert settings.APP["AGENT_ACCESS_CODE"] == "generated-agent-code"
    assert settings.APP["AI_MODEL"] == constants.DEFAULT_AI_MODEL
    assert settings.APP["AI_UTILITY_MODEL"] == constants.DEFAULT_UTILITY_AI_MODEL
    assert settings.APP["AI_IMAGE_MODEL"] == constants.DEFAULT_AI_IMAGE_MODEL
    assert settings.APP["SOURCE_URL"] == constants.DEFAULT_SOURCE_URL
    assert settings.APP["SENTRY_TRACES_SAMPLE_RATE"] == 1.0
    assert settings.APP["SENTRY_PROFILE_SESSION_SAMPLE_RATE"] == 1.0
    assert settings.APP["REDIS_TLS"] is False
    assert settings.APP["VERSION"] == "2.0"
    assert settings.APP["INSTALLER_EMAIL"] == "owner@example.com"
    assert settings.APP["DEPLOYER_EMAIL"] == "owner@example.com"
    assert settings.APP["APP_ENGINE_LOCATION"] == "us-central"
    assert settings.APP["RESOURCE_REGION"] == "us-central1"
    assert settings.APP["RUNTIME_SERVICE_ACCOUNT_EMAIL"] == (
        "project-1@project-1.iam.gserviceaccount.com"
    )
    assert settings.APP["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] == (
        "project-1@project-1.iam.gserviceaccount.com"
    )
    assert "AI_OBSERVABILITY" not in settings.APP
    assert "AI_OBSERVABILITY" not in constants.REQUIRED_APPLICATION_SETTINGS
    assert token_calls == [32]

    settings.APP.update(
        {
            "AGENT_ACCESS_ENABLED": True,
            "AGENT_ACCESS_EMAIL": "changed@example.com",
            "AGENT_ACCESS_NAME": "Changed Agent",
            "AGENT_ACCESS_CODE": "changed-code",
            "AI_UTILITY_MODEL": "custom-utility-model",
            "AI_IMAGE_MODEL": "custom-image-model",
            "AI_OBSERVABILITY": True,
            "SENTRY_TRACES_SAMPLE_RATE": 0.25,
            "SENTRY_PROFILE_SESSION_SAMPLE_RATE": 0.5,
            "SOURCE_URL": "https://example.test/custom-source",
            "REDIS_TLS": True,
            "REDIS_CA_CERT": "config/files/redis_ca.pem",
        }
    )
    token_calls.clear()

    create_config._build_app_settings()

    assert settings.APP["AGENT_ACCESS_EMAIL"] == "changed@example.com"
    assert settings.APP["AGENT_ACCESS_NAME"] == "Changed Agent"
    assert settings.APP["AGENT_ACCESS_CODE"] == "changed-code"
    assert settings.APP["AI_UTILITY_MODEL"] == "custom-utility-model"
    assert settings.APP["AI_IMAGE_MODEL"] == "custom-image-model"
    assert settings.APP["AI_OBSERVABILITY"] is True
    assert settings.APP["SENTRY_TRACES_SAMPLE_RATE"] == 0.25
    assert settings.APP["SENTRY_PROFILE_SESSION_SAMPLE_RATE"] == 0.5
    assert settings.APP["SOURCE_URL"] == "https://example.test/custom-source"
    assert settings.APP["REDIS_TLS"] is True
    assert settings.APP["REDIS_CA_CERT"] == "config/files/redis_ca.pem"
    assert token_calls == []


# @matrix setup : config-files gcloud-config
def test_setup_config_status_save_and_gcloud_login_helpers(monkeypatch, tmp_path):
    app_dir = tmp_path
    _use_isolated_app_dir(monkeypatch, app_dir)

    from installer import config_file_status, create_config

    (app_dir / "lagniappe.yaml").write_text("runtime: python312\n")
    config_dir = app_dir / "config" / "files"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "lagniappe_dev.yaml").write_text("gcloud_config: {}\n")

    assert config_file_status() == {
        "APP_YAML": True,
        "DEV_YAML": True,
        "APP_SETTINGS_YAML": False,
    }

    (config_dir / "lagniappe_settings.yaml").write_text("APP_NAME: Demo\n")
    assert config_file_status()["APP_SETTINGS_YAML"] is True

    assert (
        create_config._adc_login_command("configured@example.com", "project-1")
        == create_config.format_command(
            [
                create_config.GCLOUD_CLI,
                "auth",
                "application-default",
                "login",
                "configured@example.com",
                "--project=project-1",
                "--scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/cloud-platform",
            ]
        )
    )
    assert (
        create_config._adc_login_command(
            "configured@example.com",
            "project-1",
            force=True,
        )
        == create_config.format_command(
            [
                create_config.GCLOUD_CLI,
                "auth",
                "application-default",
                "login",
                "--project=project-1",
                "--scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/cloud-platform",
            ]
        )
    )
    assert "sqlservice.login" not in create_config._adc_login_command(
        "configured@example.com",
        "project-1",
    )

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=False: completed_process(
            command, returncode=1, stderr="permission denied"
        ),
    )

    command = ["config", "get-value", "account"]
    assert create_config._gcloud_debug_value(command) == {
        "state": create_config.GCLOUD_VALUE_ERROR,
        "value": None,
        "error": "permission denied",
        "command": command,
    }

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=False: completed_process(command, stdout="(unset)\n"),
    )
    assert create_config._gcloud_debug_value(command) == {
        "state": create_config.GCLOUD_VALUE_UNSET,
        "value": None,
        "error": None,
        "command": command,
    }


# @matrix setup : activation deploy-surface gcloud-config transactional-state
def test_verify_installation_is_read_only_and_activation_is_explicit(monkeypatch):
    from installer import verify

    calls = []

    fake_settings = types.SimpleNamespace(
        GCLOUD_CONFIG={
            "NAME": "demo",
            "ACCOUNT": "owner@example.com",
            "PROJECT": "demo-project",
        }
    )

    import installer.utils as setup_utils

    monkeypatch.setattr(setup_utils, "check_gcloud_cli", lambda: None)
    switcher = types.ModuleType("runner.gcloud")
    switcher.config_gcloud = lambda: calls.append("activate")
    monkeypatch.setitem(sys.modules, "runner.gcloud", switcher)
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=fake_settings,
            verify_generation_manifest=lambda: calls.append("generation"),
        ),
    )
    deploy = types.ModuleType("runner.deploy")
    deploy.verify_runtime_deploy_surface = lambda: calls.append("deploy-surface")
    monkeypatch.setitem(sys.modules, "runner.deploy", deploy)

    verify.verify_installation()
    assert calls == ["generation", "deploy-surface"]

    verify.activate_installation()
    assert calls == ["generation", "deploy-surface", "activate"]


# @matrix setup : config-files validation
def test_verify_application_config_reports_missing_areas(monkeypatch, capsys):
    import installer as setup_pkg
    from installer import create_config

    fake_config = types.SimpleNamespace(
        constants=types.SimpleNamespace(
            REQUIRED_APPLICATION_SETTINGS={
                "ADMIN_NAME": "Admin access",
                "ADMIN_EMAIL": "Admin access",
                "SECRET_KEY": "Security",
            }
        ),
        SETTINGS=types.SimpleNamespace(APP={}),
    )

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setitem(sys.modules, "config", fake_config)

    with pytest.raises(SetupError):
        create_config.verify_application_config(upgrade=True)

    output = capsys.readouterr().out

    assert "New features require additional settings" in output
    assert "Missing configuration areas: Admin access, Security" in output
    assert "preserving the current configuration" in output
    assert "ADMIN_EMAIL" not in output
    assert "SECRET_KEY" not in output


# @matrix setup : config-files google-oauth optional validation
def test_verify_application_config_requires_google_client_only_when_enabled(
    monkeypatch,
    capsys,
):
    import installer as setup_pkg
    from installer import create_config

    settings = types.SimpleNamespace(APP={"GOOGLE_SIGNIN_ENABLED": False})
    fake_config = types.SimpleNamespace(
        constants=types.SimpleNamespace(
            REQUIRED_APPLICATION_SETTINGS={
                "GOOGLE_SIGNIN_ENABLED": "Authentication",
            }
        ),
        SETTINGS=settings,
    )
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setitem(sys.modules, "config", fake_config)

    assert create_config.verify_application_config()

    settings.APP["GOOGLE_SIGNIN_ENABLED"] = True
    with pytest.raises(SetupError):
        create_config.verify_application_config()
    assert "Missing configuration areas: Authentication" in capsys.readouterr().out

    settings.APP["GOOGLE_CLIENT_ID"] = "1234-web.apps.googleusercontent.com"
    assert create_config.verify_application_config()


# @matrix setup : config-files keyless-config project-identity validation
def test_verify_application_config_rejects_keyless_identity_mismatch(
    monkeypatch,
    capsys,
):
    import installer as setup_pkg
    from installer import create_config

    fake_config = types.SimpleNamespace(
        constants=types.SimpleNamespace(
            REQUIRED_APPLICATION_SETTINGS={
                "GOOGLE_CLOUD_PROJECT": "Google Cloud project",
                "RUNTIME_SERVICE_ACCOUNT_EMAIL": "Google Cloud runtime identity",
                "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                    "Internal request identity"
                ),
            }
        ),
        SETTINGS=types.SimpleNamespace(
            APP={
                "GOOGLE_CLOUD_PROJECT": "project-1",
                "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
                    "runtime@wrong-project.iam.gserviceaccount.com"
                ),
                "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                    "other@wrong-project.iam.gserviceaccount.com"
                ),
            }
        ),
    )
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setitem(sys.modules, "config", fake_config)

    with pytest.raises(SetupError):
        create_config.verify_application_config()

    assert "Google Cloud keyless identity" in capsys.readouterr().out


# @matrix setup : config-files redis-tls validation
def test_verify_application_config_reports_invalid_redis_tls(monkeypatch, capsys):
    import installer as setup_pkg
    from installer import create_config

    class FakeTLSConfigurationError(ValueError):
        pass

    fake_config = types.ModuleType("config")
    fake_config.__path__ = ["config"]
    fake_config.constants = types.SimpleNamespace(
        REQUIRED_APPLICATION_SETTINGS={"REDIS_TLS": "Redis"}
    )
    fake_config.SETTINGS = types.SimpleNamespace(
        APP={
            "REDIS_TLS": True,
            "REDIS_CA_CERT": "config/files/missing.pem",
        }
    )
    fake_redis = types.ModuleType("config.redis")
    fake_redis.RedisTLSConfigurationError = FakeTLSConfigurationError
    fake_redis.redis_client_kwargs = lambda settings: (_ for _ in ()).throw(
        FakeTLSConfigurationError("missing CA")
    )

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "config.redis", fake_redis)

    with pytest.raises(SetupError):
        create_config.verify_application_config(upgrade=True)

    output = capsys.readouterr().out
    assert "Missing configuration areas: Redis transport security" in output


def _configure_adc_quota_test(monkeypatch, spinner):
    from installer import create_config

    # The runner image intentionally does not install the gcloud CLI. These
    # tests exercise the rendered recovery command, not binary discovery.
    monkeypatch.setattr(create_config, "GCLOUD_CLI", "gcloud")

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=types.SimpleNamespace(
                APP={"APP_NAME": "Demo"},
                GCLOUD_CONFIG={"ACCOUNT": "owner@example.com"},
            ),
        ),
    )

    import installer as setup_pkg

    fake_formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            info=lambda message: message,
            warning=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=spinner_factory(spinner),
        )
    )
    monkeypatch.setattr(setup_pkg, "FORMATTER", fake_formatter)

    return create_config


# @matrix setup : adc permissions transactional-state
def test_adc_authentication_is_kept_only_after_project_permission_confirmation(
    monkeypatch,
    tmp_path,
    capsys,
):
    from installer import create_config

    cloud_sdk_dir = tmp_path / "gcloud"
    cloud_sdk_dir.mkdir()
    adc_path = cloud_sdk_dir / "application_default_credentials.json"
    previous_credentials = '{"principal": "previous@example.com"}\n'
    new_credentials = '{"principal": "selected@example.com"}\n'
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(cloud_sdk_dir))

    def authenticate(command, **kwargs):
        adc_path.write_text(new_credentials, encoding="utf-8")
        return completed_process(command)

    monkeypatch.setattr(create_config.subprocess, "run", authenticate)
    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda project_id, **kwargs: (_ for _ in ()).throw(
            RuntimeError("selected account lacks project permissions")
        ),
    )

    adc_path.write_text(previous_credentials, encoding="utf-8")
    with pytest.raises(RuntimeError, match="lacks project permissions"):
        with create_config._adc_auth_transaction():
            create_config._run_adc_login(
                "selected@example.com",
                "selected-project-1",
            )
            create_config._confirm_operator_permissions("selected-project-1")
    assert adc_path.read_text(encoding="utf-8") == previous_credentials
    assert "restored the Application Default Credentials" in capsys.readouterr().out

    adc_path.unlink()
    with pytest.raises(RuntimeError, match="lacks project permissions"):
        with create_config._adc_auth_transaction():
            create_config._run_adc_login(
                "selected@example.com",
                "selected-project-1",
            )
            create_config._confirm_operator_permissions("selected-project-1")
    assert not adc_path.exists()
    assert "next setup run will reopen authentication" in capsys.readouterr().out

    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda project_id, **kwargs: {
            "installer": [],
            "billing": [],
            "deployer": [],
        },
    )
    with create_config._adc_auth_transaction():
        create_config._run_adc_login(
            "selected@example.com",
            "selected-project-1",
        )
        create_config._confirm_operator_permissions("selected-project-1")
    assert adc_path.read_text(encoding="utf-8") == new_credentials


# @matrix setup : adc new-project transactional-state
def test_new_project_forces_transactional_adc_refresh(monkeypatch):
    spinner = SpinnerRecorder()
    create_config = _configure_adc_quota_test(monkeypatch, spinner)
    quota_project_command = [
        "auth",
        "application-default",
        "set-quota-project",
        "project-1",
        "--quiet",
    ]
    login_calls = []
    gcloud_calls = []
    delays = []
    quota_results = iter(
        [
            completed_process(
                quota_project_command,
                returncode=1,
                stderr="Project not found or deleted.",
            ),
            completed_process(
                quota_project_command,
                returncode=1,
                stderr="Project not found or deleted.",
            ),
            completed_process(quota_project_command),
        ]
    )

    monkeypatch.setattr(
        create_config,
        "_run_adc_login",
        lambda account, project_id, force=False: login_calls.append(
            (account, project_id, force)
        )
        or completed_process(),
    )
    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=True, timeout=None: (
            gcloud_calls.append((command, timeout)) or next(quota_results)
        ),
    )
    monkeypatch.setattr(create_config.time, "sleep", delays.append)
    monkeypatch.setattr(
        create_config,
        "_adc_identity",
        lambda: {
            "state": "success",
            "principal": "owner@example.com",
            "project": "project-1",
            "quota_project": "project-1",
            "error": None,
        },
    )

    with create_config._adc_auth_transaction() as transaction:
        transaction.refresh_required = True
        assert create_config._set_adc_quota_project("project-1", spinner)[
            "project"
        ] == "project-1"

    assert login_calls == [("owner@example.com", "project-1", True)]
    assert any(
        message.startswith("A new project was selected")
        for message in spinner.messages
    )
    assert gcloud_calls == [
        (quota_project_command, create_config.ADC_QUOTA_TIMEOUT),
        (quota_project_command, create_config.ADC_QUOTA_TIMEOUT),
        (quota_project_command, create_config.ADC_QUOTA_TIMEOUT),
    ]
    assert delays == [2, 4]


# @matrix setup : config-files gcloud-config interactive-input
def test_set_application_defaults_refreshes_adc_login_after_quota_failure(monkeypatch):
    spinner = SpinnerRecorder()
    create_config = _configure_adc_quota_test(monkeypatch, spinner)

    quota_project_command = [
        "auth",
        "application-default",
        "set-quota-project",
        "project-1",
        "--quiet",
    ]
    quota_results = iter(
        [
            completed_process(
                quota_project_command,
                returncode=1,
                stderr="quota project mismatch",
            ),
            completed_process(quota_project_command),
        ]
    )
    gcloud_calls = []

    def fake_run_gcloud_command(command, check=True, timeout=None):
        gcloud_calls.append((command, timeout))
        return next(quota_results)

    login_calls = []

    monkeypatch.setattr(create_config, "run_gcloud_command", fake_run_gcloud_command)
    monkeypatch.setattr(
        create_config,
        "_run_adc_login",
        lambda account, project_id: login_calls.append((account, project_id))
        or completed_process(),
    )
    monkeypatch.setattr(
        create_config,
        "_adc_identity",
        lambda: {
            "state": "success",
            "principal": "owner@example.com",
            "project": "project-1",
            "quota_project": "project-1",
            "error": None,
        },
    )

    assert create_config._set_adc_quota_project("project-1", spinner) == {
        "state": "success",
        "principal": "owner@example.com",
        "project": "project-1",
        "quota_project": "project-1",
        "error": None,
    }

    assert gcloud_calls == [
        (quota_project_command, create_config.ADC_QUOTA_TIMEOUT),
        (quota_project_command, create_config.ADC_QUOTA_TIMEOUT),
    ]
    assert login_calls == [("owner@example.com", "project-1")]
    assert spinner.fails == []
    assert any(
        message.startswith("ADC is separate") for message in spinner.messages
    )
    assert any("Opening browser" in message for message in spinner.messages)
    assert not any(
        "Failed to set ADC quota project" in message for message in spinner.messages
    )
    assert any("quota project mismatch" in message for message in spinner.messages)
    messages = " ".join(" ".join(spinner.messages).split())
    assert (
        "gcloud auth application-default login owner@example.com --project=project-1 "
        "--scopes=openid,https://www.googleapis.com/auth/userinfo.email,"
        "https://www.googleapis.com/auth/cloud-platform"
        in messages
    )


# @matrix setup : config-files gcloud-config interactive-input
def test_set_application_defaults_exits_when_adc_login_refresh_fails(monkeypatch):
    spinner = SpinnerRecorder()
    create_config = _configure_adc_quota_test(monkeypatch, spinner)

    monkeypatch.setattr(
        create_config,
        "run_gcloud_command",
        lambda command, check=True, timeout=None: completed_process(
            command, returncode=1, stderr="quota project mismatch"
        ),
    )
    monkeypatch.setattr(
        create_config,
        "_run_adc_login",
        lambda account, project_id: completed_process(
            returncode=1, stderr="browser auth cancelled"
        ),
    )
    with pytest.raises(SetupError) as error:
        create_config._set_adc_quota_project("project-1", spinner)

    assert spinner.fails == ["[X]"]
    assert any(
        message.startswith("ADC is separate") for message in spinner.messages
    )
    assert not any(
        "Failed to set ADC quota project" in message for message in spinner.messages
    )
    assert any("quota project mismatch" in message for message in spinner.messages)
    assert not any(
        "browser auth cancelled" in message for message in spinner.messages
    )
    assert any("Opening browser" in message for message in spinner.messages)
    assert any("ADC login did not complete" in message for message in spinner.messages)
    assert create_config.GOOGLE_CLOUD_TERMS_URL in error.value.repair_action
    assert "owner@example.com" in error.value.repair_action
    messages = " ".join(" ".join(spinner.messages).split())
    assert (
        "gcloud auth application-default login owner@example.com --project=project-1 "
        "--scopes=openid,https://www.googleapis.com/auth/userinfo.email,"
        "https://www.googleapis.com/auth/cloud-platform"
        in messages
    )


# @matrix setup : env-export gcloud-config
def test_gcloud_switcher_exports_project_for_child_processes(monkeypatch):
    import os
    import config
    from runner import gcloud as switcher

    calls = []
    monkeypatch.setattr(
        config,
        "SETTINGS",
        types.SimpleNamespace(
            GCLOUD_CONFIG={
                "NAME": "lagniappe",
                "ACCOUNT": "owner@example.com",
                "PROJECT": "project-1",
            }
        ),
    )
    monkeypatch.setattr(switcher, "get_active_configuration", lambda: "lagniappe")
    monkeypatch.setattr(
        switcher,
        "get_configuration_value",
        lambda key, configuration=None: {
            "account": "owner@example.com",
            "project": "project-1",
        }[key],
    )
    monkeypatch.setattr(
        switcher,
        "check_account_authentication",
        lambda account: calls.append(("auth", account)),
    )
    monkeypatch.setattr(
        switcher,
        "list_configurations",
        lambda: [{"name": "lagniappe"}],
    )
    monkeypatch.setattr(
        switcher,
        "ensure_configuration_properties",
        lambda *args: calls.append(("ensure", args)),
    )
    monkeypatch.setattr(
        switcher,
        "activate_configuration",
        lambda name: calls.append(("activate", name)),
    )

    for key in [
        "CLOUDSDK_ACTIVE_CONFIG_NAME",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
        "GOOGLE_CLOUD_QUOTA_PROJECT",
    ]:
        monkeypatch.delenv(key, raising=False)

    switcher.config_gcloud()

    assert calls == [
        ("auth", "owner@example.com"),
        ("ensure", ("lagniappe", "owner@example.com", "project-1")),
    ]
    assert os.environ["CLOUDSDK_ACTIVE_CONFIG_NAME"] == "lagniappe"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "project-1"
    assert os.environ["GCLOUD_PROJECT"] == "project-1"
    assert os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] == "project-1"
