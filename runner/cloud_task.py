"""Start an operator command with task-local OIDC credentials and pinned settings."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import unquote

from runner import cloud_settings as settings
from runner.context import GCLOUD_CLI


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_cloud_connection_requires_target_identity
# @matrix auth setup : adc project-identity
def connection_file(account):
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    manifest = os.environ.get("OIC_MANIFEST_PATH")
    if manifest:
        connections = json.loads(Path(manifest).read_text())["connections"]
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
    credentials = json.loads(Path(path).read_text())
    expected = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}:generateAccessToken"
    if (
        credentials.get("type") != "external_account"
        or unquote(credentials.get("service_account_impersonation_url", "")) != expected
    ):
        raise RuntimeError(
            "The Cloud connection must federate into the selected project service account."
        )
    return str(Path(path).resolve())


# @testable infrastructure
def _gcloud(*arguments, env):
    result = subprocess.run(
        [GCLOUD_CLI, *arguments, "--quiet"], env=env, capture_output=True
    )
    if result.returncode:
        raise RuntimeError(
            "The task-local gcloud configuration or federated login failed."
        )


# @testable infrastructure
def probe(project):
    from config import SETTINGS
    from config.experiments import normalize_experiments_config
    from config.redis import redis_client_kwargs
    from redis import Redis
    from runner.gcloud import activate_repository_gcloud

    policy = normalize_experiments_config(SETTINGS.APP)
    if not policy["EXPERIMENTS_ENABLED"] or policy["EXPERIMENTS_PROJECT"] != project:
        raise RuntimeError(
            "The restored project is not the selected experiments installation."
        )
    activate_repository_gcloud(
        ensure_adc=True, ensure_cli_token=True, allow_adc_login=False
    )
    client = Redis(
        **redis_client_kwargs(SETTINGS.APP, socket_timeout=5, socket_connect_timeout=5)
    )
    try:
        if not client.ping():
            raise RuntimeError("Redis did not answer PING.")
    finally:
        client.close()
    print(f"Verified CLI, ADC, and authenticated Redis connectivity for {project}.")


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_task_reuses_pinned_version
# @matrix setup : cli-routing project-identity
def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default=os.environ.get("LAGNIAPPE_CLOUD_PROJECT"),
        required=not os.environ.get("LAGNIAPPE_CLOUD_PROJECT"),
    )
    parser.add_argument("--account", default=os.environ.get("LAGNIAPPE_CLOUD_ACCOUNT"))
    parser.add_argument(
        "--version",
        help="Numeric version or current. Defaults to the version already pinned in this checkout.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="A command after --, or omit to check Redis and hosted status.",
    )
    args = parser.parse_args(arguments)
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
            if not cmd:
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import os; from runner.cloud_task import probe; probe(os.environ['LAGNIAPPE_CLOUD_PROJECT'])",
                    ],
                    cwd=root,
                    env=env,
                    check=True,
                )
                cmd = [*cli, "hosted-e2e", "status"]
            return subprocess.run(cmd, cwd=root, env=env).returncode
    except (settings.CloudSettingsError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        print(f"Operator startup failed ({type(error).__name__}).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
