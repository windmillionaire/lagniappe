"""Non-interactive agent-assisted installation driver (``./setup.sh --agent``).

Accepts strictly non-secret choices from an answers file, returns deterministic
``needs_input`` JSON when required decisions are missing, launches the
localhost one-shot browser secret vault for all provider credentials, stores
runtime secrets exclusively in GCP Secret Manager, and verifies the finished
installation with read-only ``doctor``.
"""

from __future__ import annotations

import contextlib
import json
import re
import secrets as py_secrets
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config import File, SettingsDraft, constants
from config.locations import normalize_app_engine_location, normalize_resource_region
from config.remote_mcp import mcp_connection_name
from config.secrets import (
    DEFAULT_RUNTIME_SECRET_NAME,
    DEFAULT_RUNTIME_SECRET_VERSION,
    SECRETS_BACKEND_SECRET_MANAGER,
    find_leaked_secret_keys,
)
from installer.errors import SetupError
from installer.secret_vault import (
    VaultSection,
    VaultSubmitResult,
    build_install_vault_sections,
    parse_oauth_vault_inputs,
    run_secret_vault,
)
from installer.state import record_step

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INVALID_ANSWERS = 2
EXIT_NEEDS_INPUT = 3


class AgentAnswersError(SetupError):
    """Raised when an agent answers file is invalid or contains secret fields."""

    category = "validation"
    exit_code = EXIT_INVALID_ANSWERS


class AgentNeedsInputError(SetupError):
    """Raised when provisioning requires one more non-secret choice from the user."""

    category = "validation"
    exit_code = EXIT_NEEDS_INPUT

    def __init__(self, message: str, missing_fields: list[MissingField]) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_SENTRY_DSN_PATTERN = re.compile(r"^https://[^@\s]+@[^/\s]+/\d+$")

_ALLOWED_NON_SECRET_KEYS = frozenset(
    {
        "app_name",
        "project_id",
        "gcloud_account",
        "billing_account",
        "admin_name",
        "admin_email",
        "app_engine_location",
        "resource_region",
        "ocr_location",
        "google_signin_enabled",
        "google_client_id",
        "auth_email_provider",
        "auth_email_service",
        "auth_email_host",
        "auth_email_port",
        "auth_email_security",
        "auth_email_username",
        "auth_email_sender_email",
        "auth_email_sender_name",
        "ai_enabled",
        "external_ai_enabled",
        "mcp_name",
        "capture_errors",
        "sentry_js_dsn",
        "analytics",
        "public_manual",
        "public_page_indexing",
        "deploy_now",
        "secrets_secret_name",
        "open_browser",
    }
)

_FORBIDDEN_SECRET_MARKERS = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "API_KEY",
    "APIKEY",
    "TOKEN",
    "CREDENTIAL",
    "GIBBERISH",
    "ACCESS_CODE",
    "PRIVATE_KEY",
    "WEBHOOK_SECRET",
    "DSN",
)


@dataclass(frozen=True)
class MissingField:
    """One non-secret installation decision the AI agent should ask the user."""

    key: str
    label: str
    field_type: str = "string"
    help_text: str = ""
    choices: tuple[str, ...] = ()
    default: object = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "key": self.key,
            "label": self.label,
            "type": self.field_type,
            "help": self.help_text,
        }
        if self.choices:
            data["choices"] = list(self.choices)
        if self.default is not None:
            data["default"] = self.default
        return data


def _normalized_key(key: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(key).upper()).strip("_")


def find_forbidden_answer_keys(
    mapping: Mapping[str, object], *, prefix: str = ""
) -> list[str]:
    """Return any key path in an answers file that looks like a secret."""
    forbidden: list[str] = []
    for raw_key, value in mapping.items():
        dotted = f"{prefix}.{raw_key}" if prefix else str(raw_key)
        lowered = str(raw_key).strip().casefold()
        normalized = _normalized_key(raw_key)
        compact = normalized.replace("_", "")
        if lowered not in _ALLOWED_NON_SECRET_KEYS and any(
            marker.replace("_", "") in compact for marker in _FORBIDDEN_SECRET_MARKERS
        ):
            forbidden.append(dotted)
        elif isinstance(value, Mapping):
            forbidden.extend(find_forbidden_answer_keys(value, prefix=dotted))
    return sorted(forbidden)


def load_agent_answers(path: str | Path | None) -> dict[str, Any]:
    """Load and validate a non-secret JSON/YAML answers file."""
    if path is None:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        raise AgentAnswersError(f"Answers file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8")
    try:
        loaded = (
            json.loads(raw)
            if file_path.suffix.casefold() == ".json"
            else yaml.safe_load(raw)
        )
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise AgentAnswersError(
            f"Answers file could not be parsed: {file_path.name}"
        ) from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise AgentAnswersError(
            "Answers file must contain a JSON or YAML object mapping."
        )
    forbidden = find_forbidden_answer_keys(loaded)
    if forbidden:
        raise AgentAnswersError(
            "Refusing answers file containing secret fields ("
            + ", ".join(forbidden)
            + "). Secrets must be entered only in the localhost browser vault."
        )
    unknown = sorted(
        key for key in loaded if str(key).strip().casefold() not in _ALLOWED_NON_SECRET_KEYS
    )
    if unknown:
        raise AgentAnswersError(
            "Answers file contains unsupported fields: " + ", ".join(unknown)
        )
    return {str(key).strip().casefold(): value for key, value in loaded.items()}


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _sanitize_gcloud_config_name(app_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", app_name.strip().casefold()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"lagniappe-{cleaned}" if cleaned else "lagniappe"
    return cleaned[:30].rstrip("-") or "lagniappe"


def collect_missing_inputs(
    answers: Mapping[str, Any],
    draft: SettingsDraft,
) -> list[MissingField]:
    """Inspect answers + existing draft and return any missing non-secret fields."""
    missing: list[MissingField] = []
    app = draft.APP
    gcloud_cfg = draft.GCLOUD_CONFIG

    app_name = str(answers.get("app_name") or app.get("APP_NAME") or "").strip()
    if not app_name:
        missing.append(
            MissingField(
                key="app_name",
                label="Workspace name",
                help_text="Short human-readable name for your Lagniappe site (e.g. 'My Workspace').",
            )
        )

    project_id = str(
        answers.get("project_id")
        or app.get("GOOGLE_CLOUD_PROJECT")
        or gcloud_cfg.get("PROJECT")
        or ""
    ).strip()
    if not project_id or not _PROJECT_PATTERN.fullmatch(project_id):
        missing.append(
            MissingField(
                key="project_id",
                label="Google Cloud project ID",
                help_text="Existing or new GCP project ID (6–30 lowercase letters, digits, hyphens).",
            )
        )

    admin_name = str(answers.get("admin_name") or app.get("ADMIN_NAME") or "").strip()
    if not admin_name:
        missing.append(
            MissingField(
                key="admin_name",
                label="Owner display name",
                default="Owner",
                help_text="Your name as the permanent Owner of this workspace.",
            )
        )

    admin_email = str(
        answers.get("admin_email") or app.get("ADMIN_EMAIL") or ""
    ).strip()
    if not admin_email or not _EMAIL_PATTERN.fullmatch(admin_email):
        missing.append(
            MissingField(
                key="admin_email",
                label="Owner Google account email",
                help_text="Email address of the permanent workspace Owner.",
            )
        )

    existing_email = app.get("AUTH_EMAIL_CONFIG")
    has_existing_email = isinstance(existing_email, Mapping) and bool(
        existing_email.get("host")
    )
    provider = str(answers.get("auth_email_provider") or "gmail").strip().casefold()
    if not has_existing_email and provider not in {"gmail", "resend", "custom_smtp"}:
        missing.append(
            MissingField(
                key="auth_email_provider",
                label="Authentication email provider",
                choices=("gmail", "resend", "custom_smtp"),
                default="gmail",
                help_text="Provider used to send sign-in and password-reset emails.",
            )
        )
    elif provider == "resend":
        sender = str(answers.get("auth_email_sender_email") or "").strip()
        if not sender or not _EMAIL_PATTERN.fullmatch(sender):
            missing.append(
                MissingField(
                    key="auth_email_sender_email",
                    label="Verified Resend sender email",
                    help_text="Email address on your verified Resend sending domain.",
                )
            )
    elif provider == "custom_smtp":
        for key, label, ftype in (
            ("auth_email_host", "SMTP server host", "string"),
            ("auth_email_port", "SMTP port", "integer"),
            ("auth_email_security", "SMTP security mode", "string"),
            ("auth_email_username", "SMTP login username", "string"),
            ("auth_email_sender_email", "Sender email address", "string"),
        ):
            val = answers.get(key)
            if val in (None, ""):
                missing.append(
                    MissingField(
                        key=key,
                        label=label,
                        field_type=ftype,
                        choices=("starttls", "ssl") if key == "auth_email_security" else (),
                    )
                )

    return missing


def _build_non_secret_auth_email(
    answers: Mapping[str, Any], draft: SettingsDraft
) -> dict[str, Any]:
    existing = draft.APP.get("AUTH_EMAIL_CONFIG")
    if isinstance(existing, Mapping) and existing.get("host"):
        return dict(existing)

    provider = str(answers.get("auth_email_provider") or "gmail").strip().casefold()
    app_name = str(draft.APP.get("APP_NAME") or "Lagniappe").strip()
    admin_email = str(draft.APP.get("ADMIN_EMAIL") or "").strip()
    sender_name = str(answers.get("auth_email_sender_name") or app_name).strip()

    if provider == "resend":
        sender_email = str(answers.get("auth_email_sender_email") or "").strip()
        return {
            "provider": "smtp",
            "service": "Resend",
            "host": "smtp.resend.com",
            "port": 465,
            "security": "ssl",
            "username": "resend",
            "senderEmail": sender_email,
            "senderName": sender_name,
        }
    if provider == "custom_smtp":
        return {
            "provider": "smtp",
            "service": str(answers.get("auth_email_service") or "SMTP").strip(),
            "host": str(answers.get("auth_email_host") or "").strip(),
            "port": int(answers.get("auth_email_port") or 587),
            "security": str(answers.get("auth_email_security") or "starttls")
            .strip()
            .casefold(),
            "username": str(answers.get("auth_email_username") or "").strip(),
            "senderEmail": str(answers.get("auth_email_sender_email") or "").strip(),
            "senderName": sender_name,
        }
    # Default: Gmail SMTP with App Password
    sender_email = str(
        answers.get("auth_email_sender_email") or admin_email
    ).strip()
    username = str(answers.get("auth_email_username") or sender_email).strip()
    return {
        "provider": "smtp",
        "service": "Gmail",
        "host": "smtp.gmail.com",
        "port": 587,
        "security": "starttls",
        "username": username,
        "senderEmail": sender_email,
        "senderName": sender_name,
    }


def _apply_non_secret_answers(
    answers: Mapping[str, Any], draft: SettingsDraft
) -> None:
    app = draft.APP
    gcloud_cfg = draft.GCLOUD_CONFIG

    app_name = str(answers.get("app_name") or app.get("APP_NAME") or "").strip()
    project_id = str(
        answers.get("project_id")
        or app.get("GOOGLE_CLOUD_PROJECT")
        or gcloud_cfg.get("PROJECT")
        or ""
    ).strip()
    admin_name = str(answers.get("admin_name") or app.get("ADMIN_NAME") or "Owner").strip()
    admin_email = str(
        answers.get("admin_email") or app.get("ADMIN_EMAIL") or ""
    ).strip().casefold()
    account = str(
        answers.get("gcloud_account")
        or gcloud_cfg.get("ACCOUNT")
        or admin_email
    ).strip().casefold()

    config_name = str(
        gcloud_cfg.get("NAME") or _sanitize_gcloud_config_name(app_name)
    ).strip()
    gcloud_cfg["NAME"] = config_name
    gcloud_cfg["PROJECT"] = project_id
    gcloud_cfg["ACCOUNT"] = account
    if answers.get("billing_account"):
        gcloud_cfg["BILLING_ACCOUNT"] = str(answers["billing_account"]).strip()

    app["APP_NAME"] = app_name
    app["GOOGLE_CLOUD_PROJECT"] = project_id
    app["ADMIN_NAME"] = admin_name
    app["ADMIN_EMAIL"] = admin_email
    app.setdefault("INSTALLER_EMAIL", account)
    app.setdefault("DEPLOYER_EMAIL", account)
    app["APP_ENGINE_LOCATION"] = normalize_app_engine_location(
        answers.get("app_engine_location")
        or app.get("APP_ENGINE_LOCATION")
        or constants.DEFAULT_APP_ENGINE_LOCATION
    )
    app["RESOURCE_REGION"] = normalize_resource_region(
        answers.get("resource_region")
        or app.get("RESOURCE_REGION")
        or constants.DEFAULT_RESOURCE_REGION
    )
    app["OCR_LOCATION"] = str(
        answers.get("ocr_location")
        or app.get("OCR_LOCATION")
        or constants.DEFAULT_OCR_LOCATION
    ).strip()
    app["GOOGLE_SIGNIN_ENABLED"] = _as_bool(
        answers.get("google_signin_enabled"),
        bool(app.get("GOOGLE_SIGNIN_ENABLED", True)),
    )
    if answers.get("google_client_id"):
        app["GOOGLE_CLIENT_ID"] = str(answers["google_client_id"]).strip()

    ai_enabled = _as_bool(answers.get("ai_enabled"), bool(app.get("AI_ENABLED", True)))
    app["AI_ENABLED"] = ai_enabled
    app["EXTERNAL_AI_ENABLED"] = (
        _as_bool(
            answers.get("external_ai_enabled"),
            bool(app.get("EXTERNAL_AI_ENABLED", False)),
        )
        if ai_enabled
        else False
    )
    if answers.get("mcp_name"):
        app["MCP_NAME"] = mcp_connection_name(answers["mcp_name"])

    app["CAPTURE_ERRORS"] = _as_bool(
        answers.get("capture_errors"),
        bool(app.get("CAPTURE_ERRORS", False)),
    )
    if answers.get("sentry_js_dsn"):
        app["SENTRY_JS_DSN"] = str(answers["sentry_js_dsn"]).strip()
    app["ANALYTICS"] = _as_bool(
        answers.get("analytics"),
        bool(app.get("ANALYTICS", constants.DEFAULT_ANALYTICS_ENABLED)),
    )
    app["PUBLIC_MANUAL"] = _as_bool(
        answers.get("public_manual"),
        bool(app.get("PUBLIC_MANUAL", constants.DEFAULT_PUBLIC_MANUAL)),
    )
    app["PUBLIC_PAGE_INDEXING"] = _as_bool(
        answers.get("public_page_indexing"),
        bool(app.get("PUBLIC_PAGE_INDEXING", constants.DEFAULT_PUBLIC_PAGE_INDEXING)),
    )

    secret_name = str(
        answers.get("secrets_secret_name")
        or app.get("SECRETS_SECRET_NAME")
        or DEFAULT_RUNTIME_SECRET_NAME
    ).strip()
    app["SECRETS_BACKEND"] = SECRETS_BACKEND_SECRET_MANAGER
    app["SECRETS_SECRET_NAME"] = secret_name
    app["SECRETS_VERSION"] = DEFAULT_RUNTIME_SECRET_VERSION

    # Generate internal application secrets in RAM (persisted only to Secret Manager).
    if not app.get("SECRET_KEY"):
        app["SECRET_KEY"] = py_secrets.token_hex(32)
    if not app.get("GIBBERISH"):
        app["GIBBERISH"] = py_secrets.token_hex(16)
    if not app.get("AGENT_ACCESS_CODE"):
        app["AGENT_ACCESS_CODE"] = py_secrets.token_urlsafe(32)

    runtime_email = str(
        app.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
        or f"{config_name}@{project_id}.iam.gserviceaccount.com"
    ).strip().casefold()
    app["RUNTIME_SERVICE_ACCOUNT_EMAIL"] = runtime_email
    app["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] = runtime_email


def _missing_vault_flags(draft: SettingsDraft) -> dict[str, bool]:
    app = draft.APP
    auth_email = app.get("AUTH_EMAIL_CONFIG")
    has_auth_email_secret = (
        isinstance(auth_email, Mapping) and bool(str(auth_email.get("password") or "").strip())
    )
    has_redis = bool(
        str(app.get("REDIS_HOST") or "").strip()
        and app.get("REDIS_PORT")
        and str(app.get("REDIS_PASSWORD") or "").strip()
    )
    has_oauth = not bool(app.get("GOOGLE_SIGNIN_ENABLED", True)) or bool(
        str(app.get("GOOGLE_CLIENT_ID") or "").strip()
    )
    has_sentry = not bool(app.get("CAPTURE_ERRORS", False)) or bool(
        str(app.get("SENTRY_DSN") or "").strip()
    )
    return {
        "include_oauth": not has_oauth,
        "include_auth_email": not has_auth_email_secret,
        "include_redis": not has_redis,
        "include_sentry": not has_sentry,
    }


def _sync_settings_singleton(source: SettingsDraft, target: SettingsDraft) -> None:
    """Copy draft mappings into/out of config.SETTINGS when they are distinct objects."""
    if source is target:
        return
    for attr in ("APP", "DEPLOY", "DEV", "GCLOUD_CONFIG", "DEV_CONFIG", "TEST_CONFIG"):
        dest = getattr(target, attr)
        dest.clear()
        dest.update(getattr(source, attr))


def _ensure_project_and_billing(
    project_id: str,
    account: str,
    config_name: str,
    app_name: str,
    *,
    configured_billing_account: str = "",
) -> str:
    """Non-interactively ensure the GCP project exists, bootstrap APIs are on, and billing is linked."""
    from installer import project_bootstrap, setup_target
    from installer.commands import run_gcloud_command

    project_state = setup_target._project_state(project_id)
    if project_state["state"] == "unavailable":
        raise SetupError(
            f"Could not inspect Google Cloud project '{project_id}': "
            f"{project_state.get('error') or 'unknown error'}"
        )
    if project_state["state"] in ("absent", "unverified"):
        record_step("create Google Cloud project")
        created = run_gcloud_command(
            ["projects", "create", project_id, f"--name={app_name}"],
            check=False,
        )
        if created.returncode != 0:
            detail = (created.stderr or created.stdout or "").strip()
            raise SetupError(
                f"Failed to create Google Cloud project '{project_id}': "
                f"{detail or 'gcloud projects create failed'}"
            )

    record_step("enable bootstrap Google Cloud APIs")
    enable_boot = run_gcloud_command(
        [
            "services",
            "enable",
            *sorted(project_bootstrap.BOOTSTRAP_GOOGLE_CLOUD_APIS),
            f"--project={project_id}",
            "--quiet",
        ],
        check=False,
        timeout=project_bootstrap.BOOTSTRAP_API_TIMEOUT,
    )
    if enable_boot.returncode != 0:
        detail = (enable_boot.stderr or enable_boot.stdout or "").strip()
        raise SetupError(
            f"Could not enable bootstrap APIs on '{project_id}': "
            f"{detail or 'gcloud services enable failed'}"
        )

    billing = project_bootstrap._load_gcloud_json(
        ["billing", "projects", "describe", project_id, "--format=json"],
        "Project billing check",
    )
    billing_enabled = bool(isinstance(billing, Mapping) and billing.get("billingEnabled"))
    linked_account = (
        str(billing.get("billingAccountName") or "").removeprefix("billingAccounts/")
        if isinstance(billing, Mapping)
        else ""
    )
    if billing_enabled and linked_account:
        return linked_account

    billing_account = configured_billing_account.strip()
    if not billing_account:
        accounts = project_bootstrap._load_gcloud_json(
            ["billing", "accounts", "list", "--format=json"],
            "Billing-account discovery",
        )
        open_accounts = [
            item
            for item in (accounts or [])
            if isinstance(item, Mapping)
            and item.get("open") is not False
            and str(item.get("name") or "").removeprefix("billingAccounts/")
        ]
        if not open_accounts:
            raise SetupError(
                "No open Google Cloud billing account was found for this Google account. "
                "Create or enable a billing account at https://console.cloud.google.com/billing "
                "and rerun setup --agent."
            )
        if len(open_accounts) == 1:
            billing_account = str(open_accounts[0]["name"]).removeprefix("billingAccounts/")
        else:
            choices = tuple(
                str(item["name"]).removeprefix("billingAccounts/")
                for item in open_accounts
            )
            described = ", ".join(
                f"{str(item['name']).removeprefix('billingAccounts/')} "
                f"({item.get('displayName') or 'unnamed'})"
                for item in open_accounts
            )
            raise AgentNeedsInputError(
                "Multiple open Google Cloud billing accounts are available; choose one in answers.json.",
                [
                    MissingField(
                        key="billing_account",
                        label="Google Cloud billing account ID",
                        choices=choices,
                        help_text=f"Available open billing accounts: {described}",
                    )
                ],
            )

    record_step("link Google Cloud billing account")
    link = run_gcloud_command(
        [
            "billing",
            "projects",
            "link",
            project_id,
            f"--billing-account={billing_account}",
        ],
        check=False,
    )
    if link.returncode != 0:
        detail = (link.stderr or link.stdout or "").strip()
        raise SetupError(
            f"Failed to link billing account '{billing_account}' to '{project_id}': "
            f"{detail or 'gcloud billing projects link failed'}"
        )
    return billing_account


def _default_provision_infrastructure(draft: SettingsDraft) -> None:
    from config import SETTINGS
    from installer import FORMATTER, credentials, gcloud, identity, setup_target
    from installer.secrets import ensure_runtime_secrets_infrastructure
    from runner import gcloud as switcher

    _sync_settings_singleton(draft, SETTINGS)
    app_name = str(SETTINGS.APP["APP_NAME"])
    project_id = str(SETTINGS.APP["GOOGLE_CLOUD_PROJECT"])
    account = str(SETTINGS.GCLOUD_CONFIG["ACCOUNT"])
    config_name = str(SETTINGS.GCLOUD_CONFIG["NAME"])

    SETTINGS.DEV["setup_draft"] = {"APP_NAME": app_name}
    SETTINGS.save(File.DEV_YAML)

    record_step("configure gcloud target")
    switcher.config_gcloud()

    billing_account = _ensure_project_and_billing(
        project_id,
        account,
        config_name,
        app_name,
        configured_billing_account=str(SETTINGS.GCLOUD_CONFIG.get("BILLING_ACCOUNT") or ""),
    )
    if billing_account and SETTINGS.GCLOUD_CONFIG.get("BILLING_ACCOUNT") != billing_account:
        SETTINGS.GCLOUD_CONFIG["BILLING_ACCOUNT"] = billing_account
        SETTINGS.save(File.DEV_YAML)

    target = setup_target.SetupTarget(
        app_name=app_name,
        configuration_name=config_name,
        account=account,
        project_id=project_id,
    )
    f = FORMATTER.initialize()
    record_step("align Google Cloud ADC credentials")
    with credentials._adc_auth_transaction() as transaction:
        credentials._ensure_adc_principal(target, transaction=transaction)
        with f.progress(
            text="Verifying Google Cloud credentials",
            success_text="Google Cloud credentials verified",
        ) as sp:
            credentials._set_adc_quota_project(target, sp, transaction=transaction)
            sp.ok()
        transaction.commit()

    record_step("enable Google Cloud APIs")
    gcloud.enable_gcloud_apis()
    record_step("reconcile App Engine and runtime service account")
    gcloud.setup_app_engine(confirm=False)
    record_step("provision runtime Secret Manager infrastructure")
    ensure_runtime_secrets_infrastructure(
        str(SETTINGS.APP["GOOGLE_CLOUD_PROJECT"]),
        str(SETTINGS.APP["RUNTIME_SERVICE_ACCOUNT_EMAIL"]),
        secret_name=str(
            SETTINGS.APP.get("SECRETS_SECRET_NAME") or DEFAULT_RUNTIME_SECRET_NAME
        ),
    )
    record_step("reconcile storage buckets")
    gcloud.configure_storage_buckets()
    record_step("reconcile task queue")
    gcloud.create_task_queue()
    record_step("reconcile database data protection")
    gcloud.configure_data_protection()
    record_step("reconcile OCR processor")
    gcloud.create_ocr_processor()
    record_step("reconcile standalone Identity Platform")
    identity.setup_identity_platform()
    _sync_settings_singleton(SETTINGS, draft)


def _default_validate_oauth(
    client_id: str, client_secret: str, redirect_uri: str
) -> None:
    from installer import admin, identity

    if not admin.validate_oauth_client_id(client_id):
        raise ValueError("Invalid Google OAuth Client ID format.")
    if redirect_uri:
        admin.verify_oauth_web_client(client_id, redirect_uri)
    identity.setup_google_provider(client_id, client_secret)


def _default_validate_smtp(config: Mapping[str, object], recipient: str) -> None:
    from installer.auth_email import test_smtp_delivery

    test_smtp_delivery(config, recipient=recipient)


def _default_validate_redis(settings: Mapping[str, object]) -> None:
    from installer.redis import test_redis_connection

    test_redis_connection(settings, exit_on_failure=True)


def _default_deploy(draft: SettingsDraft) -> bool:
    from installer import deploy, gcloud, monitoring, upgrade
    from installer import FORMATTER

    f = FORMATTER.initialize()
    record_step("deploy application")
    deploy.deploy_to_app_engine(print_final_summary=False, first_install=True)
    if not upgrade._configure_deferred_job_recovery(f, gcloud):
        return False
    monitoring.reconcile_memory_alert()
    return True


def _default_doctor() -> int:
    from installer.doctor import run_doctor

    return run_doctor()


def build_vault_submit_handler(
    *,
    draft: SettingsDraft,
    answers: Mapping[str, Any],
    flags: Mapping[str, bool],
    validate_oauth: Callable[[str, str, str], None] = _default_validate_oauth,
    validate_smtp: Callable[[Mapping[str, object], str], None] = _default_validate_smtp,
    validate_redis: Callable[[Mapping[str, object]], None] = _default_validate_redis,
) -> Callable[[dict[str, str]], VaultSubmitResult]:
    """Build an in-RAM validation and persistence callback for the localhost vault."""
    from installer.auth_email import normalize_app_password, normalize_auth_email_config
    from installer.redis import _parse_redis_cli_command

    def on_submit(values: dict[str, str]) -> VaultSubmitResult:
        summary: list[str] = []
        pending_updates: dict[str, Any] = {}
        oauth_pair: tuple[str, str] | None = None

        if flags.get("include_oauth"):
            try:
                client_id, client_secret = parse_oauth_vault_inputs(values)
                redirect_uri = str(draft.APP.get("GOOGLE_LOGIN_URI") or "").strip()
                validate_oauth(client_id, client_secret, redirect_uri)
            except Exception as error:
                return VaultSubmitResult(
                    ok=False,
                    error="Google OAuth validation failed.",
                    field_errors={"oauth_client_id": str(error)},
                )
            oauth_pair = (client_id, client_secret)
            pending_updates["GOOGLE_CLIENT_ID"] = client_id
            pending_updates["GOOGLE_SIGNIN_ENABLED"] = True
            summary.append("Google Sign-In OAuth client verified and configured in Identity Platform.")

        if flags.get("include_auth_email"):
            provider = str(answers.get("auth_email_provider") or "gmail").strip().casefold()
            raw_password = values.get("auth_email_password", "")
            password = (
                normalize_app_password(raw_password)
                if provider == "gmail"
                else raw_password.strip()
            )
            if not password:
                return VaultSubmitResult(
                    ok=False,
                    error="Authentication email credential is invalid.",
                    field_errors={
                        "auth_email_password": (
                            "Enter the 16-character Gmail App Password."
                            if provider == "gmail"
                            else "Authentication email password/API key is required."
                        )
                    },
                )
            candidate_email = {
                **_build_non_secret_auth_email(answers, draft),
                "password": password,
            }
            normalized_email = normalize_auth_email_config(candidate_email)
            if not normalized_email:
                return VaultSubmitResult(
                    ok=False,
                    error="Authentication email configuration is incomplete.",
                    field_errors={"auth_email_password": "Check SMTP host, port, sender, and password."},
                )
            try:
                recipient = str(draft.APP.get("ADMIN_EMAIL") or normalized_email["senderEmail"])
                validate_smtp(normalized_email, recipient)
            except Exception:
                return VaultSubmitResult(
                    ok=False,
                    error="SMTP verification failed. Check the password/API key and try again.",
                    field_errors={"auth_email_password": "SMTP sign-in or test message failed."},
                )
            pending_updates["AUTH_EMAIL_CONFIG"] = normalized_email
            summary.append(
                f"Authentication email ({normalized_email['service']}) verified and saved to Secret Manager."
            )

        if flags.get("include_redis"):
            cli_text = values.get("redis_cli_command", "").strip()
            if cli_text:
                try:
                    parsed = _parse_redis_cli_command(cli_text)
                except ValueError as error:
                    return VaultSubmitResult(
                        ok=False,
                        error="Redis connection input could not be parsed.",
                        field_errors={"redis_cli_command": str(error)},
                    )
                host = str(parsed["host"])
                port = int(parsed["port"])
                redis_password = str(parsed["password"])
            else:
                host = values.get("redis_host", "").strip()
                raw_port = values.get("redis_port", "").strip()
                redis_password = values.get("redis_password", "").strip()
                try:
                    port = int(raw_port)
                except ValueError:
                    port = 0
                if not host or not 1 <= port <= 65535 or not redis_password:
                    return VaultSubmitResult(
                        ok=False,
                        error="Provide either a copied Redis CLI command or host, port, and password.",
                        field_errors={"redis_password": "Redis host, valid port, and password are required."},
                    )
            redis_probe = {
                **draft.APP,
                "REDIS_HOST": host,
                "REDIS_PORT": port,
                "REDIS_PASSWORD": redis_password,
            }
            try:
                validate_redis(redis_probe)
            except Exception:
                return VaultSubmitResult(
                    ok=False,
                    error="Redis connection test failed. Check the host, port, and password.",
                    field_errors={"redis_password": "Could not connect to Redis with these credentials."},
                )
            pending_updates["REDIS_HOST"] = host
            pending_updates["REDIS_PORT"] = port
            pending_updates["REDIS_PASSWORD"] = redis_password
            summary.append("Redis connection verified and password saved to Secret Manager.")

        if flags.get("include_sentry"):
            dsn = values.get("sentry_dsn", "").strip()
            if not _SENTRY_DSN_PATTERN.fullmatch(dsn):
                return VaultSubmitResult(
                    ok=False,
                    error="Sentry DSN format is invalid.",
                    field_errors={"sentry_dsn": "Expected https://<key>@<host>/<project-id>."},
                )
            pending_updates["SENTRY_DSN"] = dsn
            pending_updates["SENTRY_JS_DSN"] = values.get("sentry_js_dsn", "").strip() or dsn
            pending_updates["CAPTURE_ERRORS"] = True
            summary.append("Sentry DSN saved to Secret Manager.")

        # Apply validated updates to in-memory draft and persist immediately to
        # Secret Manager + stripped non-secret YAML (OAuth secret stays transient).
        del oauth_pair
        draft.APP.update(pending_updates)
        draft.save(File.APP_SETTINGS_YAML)
        return VaultSubmitResult(ok=True, summary=tuple(summary))

    return on_submit


def _emit(payload: Mapping[str, object], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, sort_keys=True))
        return
    status = str(payload.get("status") or "")
    message = str(payload.get("message") or "")
    if message:
        print(message)
    if status == "needs_input":
        missing = payload.get("missing_fields")
        if isinstance(missing, list):
            for item in missing:
                if isinstance(item, Mapping):
                    print(f"  - {item.get('key')}: {item.get('label')}")


def run_agent_install(
    *,
    answers_path: str | Path | None = None,
    json_output: bool = False,
    draft: SettingsDraft | None = None,
    provision_fn: Callable[[SettingsDraft], None] = _default_provision_infrastructure,
    vault_runner: Callable[
        [tuple[VaultSection, ...], Callable[[dict[str, str]], VaultSubmitResult]],
        VaultSubmitResult,
    ]
    | None = None,
    validate_oauth: Callable[[str, str, str], None] = _default_validate_oauth,
    validate_smtp: Callable[[Mapping[str, object], str], None] = _default_validate_smtp,
    validate_redis: Callable[[Mapping[str, object]], None] = _default_validate_redis,
    deploy_fn: Callable[[SettingsDraft], bool] = _default_deploy,
    doctor_fn: Callable[[], int] = _default_doctor,
) -> int:
    """Execute one resumable non-interactive agent-assisted install pass."""
    try:
        answers = load_agent_answers(answers_path)
    except SetupError as error:
        _emit(
            {
                "status": "error",
                "code": "invalid_answers",
                "message": str(error),
            },
            json_output=json_output,
        )
        return error.exit_code

    active_draft = draft if draft is not None else SettingsDraft()
    missing = collect_missing_inputs(answers, active_draft)
    if missing:
        _emit(
            {
                "status": "needs_input",
                "missing_fields": [item.to_dict() for item in missing],
                "message": (
                    "Additional non-secret choices are required before provisioning. "
                    "Add them to your answers file and rerun setup --agent."
                ),
            },
            json_output=json_output,
        )
        return EXIT_NEEDS_INPUT

    record_step("apply non-secret agent answers")
    _apply_non_secret_answers(answers, active_draft)

    stream_guard = (
        contextlib.redirect_stdout(sys.stderr)
        if json_output
        else contextlib.nullcontext()
    )

    record_step("provision cloud infrastructure")
    try:
        with stream_guard:
            provision_fn(active_draft)
    except AgentNeedsInputError as error:
        _emit(
            {
                "status": "needs_input",
                "missing_fields": [item.to_dict() for item in error.missing_fields],
                "message": str(error),
            },
            json_output=json_output,
        )
        return EXIT_NEEDS_INPUT

    # Ensure generated config defaults are built in memory (without secrets on disk).
    from installer import config_builders

    version = str(active_draft.NODE.get("version") or "2.5.0").strip()
    built_app = config_builders.build_app_settings(
        active_draft.APP,
        active_draft.GCLOUD_CONFIG,
        version=version,
        secret_defaults={},
    )
    active_draft.APP.clear()
    active_draft.APP.update(built_app)
    if not active_draft.APP.get("APP_URL"):
        project_id = str(active_draft.APP["GOOGLE_CLOUD_PROJECT"])
        active_draft.APP["APP_URL"] = f"https://{project_id}.appspot.com"
    if not active_draft.APP.get("GOOGLE_LOGIN_URI"):
        active_draft.APP["GOOGLE_LOGIN_URI"] = (
            f"{active_draft.APP['APP_URL']}/users/google-signin"
        )

    flags = _missing_vault_flags(active_draft)
    vault_summary: list[str] = []
    if any(flags.values()):
        sections = build_install_vault_sections(
            active_draft.APP,
            include_oauth=flags["include_oauth"],
            include_auth_email=flags["include_auth_email"],
            include_redis=flags["include_redis"],
            include_sentry=flags["include_sentry"],
            auth_email_provider=str(answers.get("auth_email_provider") or "gmail"),
        )
        submit_handler = build_vault_submit_handler(
            draft=active_draft,
            answers=answers,
            flags=flags,
            validate_oauth=validate_oauth,
            validate_smtp=validate_smtp,
            validate_redis=validate_redis,
        )
        record_step("collect provider credentials via localhost browser vault")
        with stream_guard:
            if vault_runner is not None:
                outcome = vault_runner(sections, submit_handler)
            else:
                open_browser = _as_bool(answers.get("open_browser"), True)
                outcome = run_secret_vault(
                    sections,
                    submit_handler,
                    open_browser=open_browser,
                    on_ready=lambda url: print(
                        f"Open the local credential vault in your browser: {url}",
                        file=sys.stderr if json_output else sys.stdout,
                        flush=True,
                    ),
                )
        if not outcome.ok:
            _emit(
                {
                    "status": "error",
                    "code": "vault_failed",
                    "message": outcome.error or "Credential vault did not complete.",
                },
                json_output=json_output,
            )
            return EXIT_ERROR
        vault_summary.extend(outcome.summary)

    # Finalize and persist all generated files (secrets strictly in Secret Manager).
    built_app, deploy_doc = config_builders.build_deploy_yaml(
        active_draft.APP, active_draft.DEPLOY
    )
    dev_cfg, test_cfg = config_builders.build_dev_yaml(
        active_draft.DEV_CONFIG, active_draft.TEST_CONFIG
    )
    indexes = config_builders.build_index_yaml(active_draft.INDEX)
    manifest = config_builders.build_manifest(built_app, active_draft.MANIFEST)
    for target, generated in (
        (active_draft.APP, built_app),
        (active_draft.DEPLOY, deploy_doc),
        (active_draft.DEV_CONFIG, dev_cfg),
        (active_draft.TEST_CONFIG, test_cfg),
        (active_draft.INDEX, indexes),
        (active_draft.MANIFEST, manifest),
    ):
        target.clear()
        target.update(generated)
    record_step("persist generated configuration")
    active_draft.save()

    leaked = find_leaked_secret_keys(File.APP_SETTINGS_YAML.load())
    if leaked:
        _emit(
            {
                "status": "error",
                "code": "secret_leak_detected",
                "leaked_keys": leaked,
                "message": "Aborted: secret keys were detected on disk.",
            },
            json_output=json_output,
        )
        return EXIT_ERROR

    deploy_now = _as_bool(answers.get("deploy_now"), True)
    deployed = False
    if deploy_now:
        with stream_guard:
            deployed = bool(deploy_fn(active_draft))
        if not deployed:
            _emit(
                {
                    "status": "error",
                    "code": "deploy_failed",
                    "message": "Deployment did not complete cleanly.",
                },
                json_output=json_output,
            )
            return EXIT_ERROR

    record_step("verify installation with doctor")
    with stream_guard:
        doctor_code = int(doctor_fn())
    result_payload: dict[str, object] = {
        "status": "ok" if doctor_code == 0 else "error",
        "project_id": str(active_draft.APP.get("GOOGLE_CLOUD_PROJECT") or ""),
        "app_url": str(active_draft.APP.get("APP_URL") or ""),
        "secrets_backend": SECRETS_BACKEND_SECRET_MANAGER,
        "vault_sections_completed": vault_summary,
        "deployed": deployed,
        "doctor_exit_code": doctor_code,
        "message": (
            "Lagniappe installation verified and ready."
            if doctor_code == 0
            else "Installation finished with doctor findings; run ./setup.sh doctor for details."
        ),
    }
    _emit(result_payload, json_output=json_output)
    return EXIT_OK if doctor_code == 0 else EXIT_ERROR
