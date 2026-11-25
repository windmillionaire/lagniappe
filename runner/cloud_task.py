"""Start an operator command with task-local OIDC credentials and pinned settings."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from runner import cloud_settings as settings
from runner.context import GCLOUD_CLI


def connection_file(account: str) -> str:
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    manifest = os.environ.get("OIC_MANIFEST_PATH")
    if manifest:
        connections = json.loads(Path(manifest).read_text(encoding="utf-8"))[
            "connections"
        ]
        alias = os.environ.get("LAGNIAPPE_OIDC_ALIAS")
        choices = [
            c
            for c in connections
            if c.get("credentials_file")
            and (c.get("alias") == alias if alias else c.get("is_default"))
        ]
        if len(choices) != 1:
            raise RuntimeError(
                "Select the operator connection using LAGNIAPPE_OIDC_ALIAS."
            )
        path = choices[0]["credentials_file"]
    if not path:
        raise RuntimeError("Attach the environment's Google OIDC connection first.")
    credentials = json.loads(Path(path).read_text(encoding="utf-8"))
    endpoint = urlsplit(credentials.get("service_account_impersonation_url", ""))
    target = f"/v1/projects/-/serviceAccounts/{account}:generateAccessToken"
    route = unquote(endpoint.path)
    if endpoint.hostname == "iamcredentials.googleapis.com":
        matches_target = endpoint.port in (None, 443) and route == target
    else:
        # Cloud's identity relay adds a routing prefix on the managed proxy host.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
        matches_target = (
            bool(endpoint.hostname)
            and endpoint.hostname == urlsplit(proxy).hostname
            and route.endswith(target)
        )
    if (
        credentials.get("type") != "external_account"
        or endpoint.scheme != "https"
        or endpoint.username is not None
        or endpoint.query
        or endpoint.fragment
        or not matches_target
    ):
        raise RuntimeError(
            "The Cloud connection must federate into the selected project service account."
        )
    return str(Path(path).resolve())


def _gcloud(*arguments: str, env: dict[str, str]) -> None:
    result = subprocess.run(
        [GCLOUD_CLI or "gcloud", *arguments, "--quiet"], env=env, capture_output=True
    )
    if result.returncode:
        raise RuntimeError(
            "The task-local gcloud configuration or federated login failed."
        )


def probe(project: str, *, check_redis: bool = False) -> None:
    from config import SETTINGS
    from config.experiments import normalize_experiments_config
    from runner.gcloud import activate_repository_gcloud

    policy = normalize_experiments_config(SETTINGS.APP)
    if not policy["EXPERIMENTS_ENABLED"] or policy["EXPERIMENTS_PROJECT"] != project:
        raise RuntimeError(
            "The restored project is not the selected experiments installation."
        )
    activate_repository_gcloud(
        ensure_adc=True, ensure_cli_token=True, allow_adc_login=False
    )
    print(f"Verified CLI and ADC for {project}.", flush=True)
    if not check_redis:
        return

    from config.redis import redis_connection_kwargs
    from redis import Redis

    client = Redis(
        **redis_connection_kwargs(SETTINGS.APP, socket_timeout=5, socket_connect_timeout=5)
    )
    try:
        if not client.ping():
            raise RuntimeError("Redis did not answer PING.")
    finally:
        client.close()
    print(f"Verified direct Redis connectivity for {project}.")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default=os.environ.get("LAGNIAPPE_CLOUD_PROJECT"),
        required=not os.environ.get("LAGNIAPPE_CLOUD_PROJECT"),
    )
    parser.add_argument("--account", default=os.environ.get("LAGNIAPPE_CLOUD_ACCOUNT"))
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument(
        "--check-connection",
        action="store_true",
        help="Verify the federated gcloud login and exit before restoring settings.",
    )
    checks.add_argument(
        "--check-redis",
        action="store_true",
        help="Also test direct Redis access from this task during startup.",
    )
    parser.add_argument(
        "--version",
        help="Numeric version or current. Defaults to the version already pinned in this checkout.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="A command after --, or omit to verify Google identity and read hosted status.",
    )
    args = parser.parse_args(arguments)
    if args.check_connection and (args.version or args.command):
        parser.error("--check-connection runs by itself.")
    project = args.project
    account = args.account or f"lagniappe-codex@{project}.iam.gserviceaccount.com"
    if not settings.PROJECT.fullmatch(project) or not account.endswith(
        f"@{project}.iam.gserviceaccount.com"
    ):
        parser.error("Select a project and a service account in that project.")
    try:
        credentials = connection_file(account)
        with tempfile.TemporaryDirectory(prefix="lagniappe-gcloud-") as directory:
            env = dict(
                os.environ,
                CLOUDSDK_CONFIG=directory,
                GOOGLE_APPLICATION_CREDENTIALS=credentials,
                GOOGLE_CLOUD_PROJECT=project,
                GOOGLE_CLOUD_QUOTA_PROJECT=project,
                CLOUDSDK_CORE_DISABLE_PROMPTS="1",
                LAGNIAPPE_CLOUD_PROJECT=project,
                LAGNIAPPE_CLOUD_ACCOUNT=account,
                LAGNIAPPE_CLOUD_CHECKPOINT_PROJECT=project,
            )
            for key in (
                "CLOUDSDK_ACTIVE_CONFIG_NAME",
                "CLOUDSDK_CORE_PROJECT",
                "CLOUDSDK_CORE_ACCOUNT",
            ):
                env.pop(key, None)
            name = "lagniappe-operator"
            _gcloud(
                "config", "configurations", "create", name, "--no-activate", env=env
            )
            env["CLOUDSDK_ACTIVE_CONFIG_NAME"] = name
            _gcloud("auth", "login", f"--cred-file={credentials}", "--brief", env=env)
            _gcloud("config", "set", "project", project, env=env)
            if args.check_connection:
                settings.cli_token(project, name, account, env=env)
                print(f"Verified federated Google login as {account} for {project}.")
                return 0
            receipt = settings._receipt(settings.APP_DIR)
            version = args.version or receipt.get("version", "current")
            root = settings.APP_DIR
            cli = [sys.executable, str(root / "run.py")]
            if (
                args.version
                or receipt.get("project") != project
                or receipt.get("operator_target") != {"NAME": name, "ACCOUNT": account}
                or receipt.get("source") != settings._source(root)
                or (root / settings.JOURNAL).exists()
            ):
                subprocess.run(
                    [
                        *cli,
                        "cloud-settings",
                        "restore",
                        "--operator",
                        "--version",
                        version,
                    ],
                    env=env,
                    cwd=root,
                    check=True,
                )
            cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not cmd or args.check_redis:
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys; from runner.cloud_task import probe; "
                        "probe(sys.argv[1], check_redis='--check-redis' in sys.argv[2:])",
                        project,
                        *(["--check-redis"] if args.check_redis else []),
                    ],
                    cwd=root,
                    env=env,
                    check=True,
                )
            if not cmd:
                cmd = [*cli, "hosted-e2e", "status"]
            return subprocess.run(cmd, cwd=root, env=env).returncode
    except (settings.CloudSettingsError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        print(f"Operator startup failed ({type(error).__name__}).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
