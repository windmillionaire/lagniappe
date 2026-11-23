"""Publish and materialize one project's installer-owned settings in Secret Manager."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys

import google_crc32c
import requests
import yaml

from config import (
    APP_DIR,
    File,
    _atomic_write_text,
    decode_app_settings,
    write_generation_manifest,
)
from config.constants import REDIS_CA_CERT_RELATIVE_PATH
from config.recovery import validate_recovery_document
from config.redis import redis_tls_enabled
from installer.config_builders import (
    build_deploy_yaml,
    build_index_yaml,
    build_manifest,
)
from installer.state import SetupProcessLock
from runner.context import GCLOUD_CLI, GIT_CLI

SECRET = "lagniappe-cloud-settings"
FILES = Path("config/files")
APP = FILES / "lagniappe_settings.yaml"
DEV = FILES / "lagniappe_dev.yaml"
CA = Path(REDIS_CA_CERT_RELATIVE_PATH)
RECEIPT = FILES / "lagniappe_cloud.json"
JOURNAL = FILES / ".lagniappe_cloud_restore.json"
LIMIT = 65536
PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"[1-9][0-9]*")


# @testable infrastructure
class CloudSettingsError(RuntimeError):
    """A secret-free diagnostic suitable for an operator console."""


# @testable infrastructure
def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# @testable infrastructure
def _read(root, path):
    target = root / path
    if target.resolve() != target:
        raise CloudSettingsError(f"Expected an installation-owned file at {path}.")
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


# @testable infrastructure
def _receipt(root):
    raw = _read(root, RECEIPT)
    return json.loads(raw) if raw is not None else {}


# @testable infrastructure
def _source(root):
    result = subprocess.run(
        [GIT_CLI, "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    sha = result.stdout.strip()
    if result.returncode or not SHA.fullmatch(sha):
        raise CloudSettingsError(
            "A checkout with a committed source revision is required."
        )
    return sha


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_bundle_round_trip
# @matrix config setup : secrets project-identity redis-tls
def validate_bundle(bundle, project):
    """Validate all documents together before staging any changes."""
    if (
        not PROJECT.fullmatch(project)
        or not isinstance(bundle, dict)
        or (
            set(bundle) != {"schema", "project", "app", "dev", "ca"}
            or bundle["schema"] != 1
            or bundle["project"] != project
        )
    ):
        raise CloudSettingsError(
            "The settings bundle schema or project does not match."
        )
    try:
        if len(_json(bundle).encode()) > LIMIT:
            raise ValueError
        app = decode_app_settings(yaml.safe_load(bundle["app"]))
        validate_recovery_document(app)
        dev = yaml.safe_load(bundle["dev"])
        target = dev["gcloud_config"]
        if (
            app["GOOGLE_CLOUD_PROJECT"] != project
            or target["PROJECT"] != project
            or not app.get("SECRET_KEY")
            or not target["ACCOUNT"]
            or not target["NAME"]
            or not all(
                isinstance(dev.get(key, {}), dict)
                for key in ("dev_settings", "test_settings")
            )
        ):
            raise ValueError
        ca = bundle["ca"]
        if redis_tls_enabled(app) and (
            app.get("REDIS_CA_CERT") != CA.as_posix() or not ca
        ):
            raise ValueError
        if ca is not None:
            ssl.create_default_context(cadata=ca)
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        RuntimeError,
        yaml.YAMLError,
    ):
        raise CloudSettingsError(
            "Invalid runtime settings, developer settings, Redis CA, or project identity."
        ) from None
    return app, dev


# @testable infrastructure
def _local_bundle(root, project, receipt):
    bundle = {
        "schema": 1,
        "project": project,
        "app": _read(root, APP),
        "dev": _read(root, DEV),
        "ca": _read(root, CA),
    }
    _, dev = validate_bundle(bundle, project)
    if receipt.get("operator_target"):
        target = dev["gcloud_config"]
        if any(target.get(k) != v for k, v in receipt["operator_target"].items()):
            raise CloudSettingsError(
                "The restored operator's gcloud target was changed."
            )
        target.update(receipt["author_target"])
    projection = receipt.get("release_version")
    if projection:
        app = yaml.safe_load(bundle["app"])
        if app.get("VERSION") == projection["checkout"]:
            if projection["installation"] is None:
                app.pop("VERSION", None)
            else:
                app["VERSION"] = projection["installation"]
            bundle["app"] = yaml.safe_dump(app, allow_unicode=True)
    bundle["dev"] = yaml.safe_dump(dev, allow_unicode=True, sort_keys=True)
    return bundle


# @testable infrastructure
def _same_settings(left, right):
    return (
        left["schema"] == right["schema"]
        and left["project"] == right["project"]
        and left["ca"] == right["ca"]
        and all(
            _json(yaml.safe_load(left[key])) == _json(yaml.safe_load(right[key]))
            for key in ("app", "dev")
        )
    )


# @testable infrastructure
def _snapshot(root):
    return hashlib.sha256(
        _json([_read(root, path) for path in (APP, DEV, CA)]).encode()
    ).hexdigest()


# @testable infrastructure
def _record(root, project, version, source, **extra):
    receipt = dict(
        project=project,
        secret=SECRET,
        version=version,
        source=source,
        fingerprint=_snapshot(root),
        **extra,
    )
    _atomic_write_text(root / RECEIPT, _json(receipt) + "\n", owner_only=True)
    return receipt


# @testable infrastructure
def cli_token(project, configuration, account, *, env=None):
    """Get a short-lived token for the project's explicitly selected CLI identity."""
    if (
        not GCLOUD_CLI
        or not configuration
        or not account
        or not PROJECT.fullmatch(project)
    ):
        raise CloudSettingsError(
            "Select a valid project, gcloud configuration, and account."
        )
    args = [GCLOUD_CLI, f"--configuration={configuration}", "--quiet"]
    properties = subprocess.run(
        [
            *args,
            "config",
            "configurations",
            "describe",
            configuration,
            "--format=json(properties.core)",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if properties.returncode:
        raise CloudSettingsError("The named gcloud configuration is unavailable.")
    core = json.loads(properties.stdout).get("properties", {}).get("core", {})
    if core.get("project") != project or core.get("account") != account:
        raise CloudSettingsError(
            "The selected gcloud configuration has a different account or project."
        )
    auth = subprocess.run(
        [
            *args,
            f"--project={project}",
            f"--account={account}",
            "auth",
            "print-access-token",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if auth.returncode or not auth.stdout.strip():
        raise CloudSettingsError(
            "The selected Google identity could not obtain an access token."
        )
    return auth.stdout.strip()


# @testable infrastructure
class SecretManager:
    """Use only the explicitly selected CLI identity. Never log provider bodies."""

    def __init__(self, project, configuration, account):
        self.url = f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{SECRET}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Bearer " + cli_token(
            project, configuration, account
        )

    def request(self, method, suffix="", **kwargs):
        response = self.session.request(
            method, self.url + suffix, timeout=30, allow_redirects=False, **kwargs
        )
        if not response.ok:
            raise CloudSettingsError(
                f"Secret Manager returned HTTP {response.status_code}. Check the target, access, and current version."
            )
        return response.json()

    def access(self, version):
        if not (VERSION.fullmatch(version) or version == "current"):
            raise CloudSettingsError("Use a numeric secret version or current.")
        data = self.request("GET", f"/versions/{version}:access")
        number = data["name"].rsplit("/", 1)[-1]
        raw = base64.b64decode(data["payload"]["data"], validate=True)
        if (
            not VERSION.fullmatch(number)
            or version not in {"current", number}
            or len(raw) > LIMIT
            or google_crc32c.value(raw) != int(data["payload"]["dataCrc32c"])
        ):
            raise CloudSettingsError(
                "Secret Manager version or checksum verification failed."
            )
        return number, json.loads(raw)


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_publish_rejects_stale_writers
# @matrix config setup : secrets transactional-state
def publish(root, project, store, receipt, source):
    bundle = _local_bundle(root, project, receipt)
    metadata = store.request("GET")
    aliases = metadata.get("versionAliases", {})
    current = str(aliases.get("current", ""))
    if current and _same_settings(store.access(current)[1], bundle):
        version = current
    else:
        if current != str(receipt.get("version", "")):
            raise CloudSettingsError(
                "A newer bundle is current. Restore it in a fresh checkout and reconcile the edits."
            )
        raw = _json(bundle).encode()
        if len(raw) > LIMIT:
            raise CloudSettingsError("Settings exceed the 64 KiB Secret Manager limit.")
        payload = {
            "data": base64.b64encode(raw).decode(),
            "dataCrc32c": str(google_crc32c.value(raw)),
        }
        response = store.request("POST", ":addVersion", json={"payload": payload})
        version = response["name"].rsplit("/", 1)[-1]
        if not VERSION.fullmatch(version) or store.access(version)[1] != bundle:
            raise CloudSettingsError(
                "The new secret version failed read-back verification."
            )
        store.request(
            "PATCH",
            params={"updateMask": "version_aliases"},
            json={
                "etag": metadata["etag"],
                "versionAliases": {**aliases, "current": version},
            },
        )
    overlay = {
        k: receipt[k]
        for k in ("author_target", "operator_target", "release_version")
        if k in receipt
    }
    return _record(root, project, version, source, **overlay)


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_deploy_requires_pinned_experiments_target
# @matrix deploy setup : project-identity
def verify_operator_target(root, project, draft):
    from config.experiments import normalize_experiments_config

    receipt = _receipt(root)
    operator = receipt.get("operator_target", {})
    policy = normalize_experiments_config(draft.APP)
    if (
        not policy["EXPERIMENTS_ENABLED"]
        or policy["EXPERIMENTS_PROJECT"] != project
        or receipt.get("project") != project
        or receipt.get("secret") != SECRET
        or draft.GCLOUD_CONFIG.get("PROJECT") != project
        or not operator
        or any(draft.GCLOUD_CONFIG.get(k) != v for k, v in operator.items())
        or receipt.get("source") != _source(root)
        or receipt.get("fingerprint") != _snapshot(root)
    ):
        raise CloudSettingsError(
            "Restore the pinned experiments settings for this revision before deploying."
        )


# @testable infrastructure
def _restore_paths():
    # Use the same output locations and permissions as installer generation.
    generated = (
        File.APP_YAML,
        File.INDEX_YAML,
        File.MANIFEST_JSON,
        File.GENERATION_JSON,
    )
    paths = {path: True for path in (APP, DEV, CA, RECEIPT)}
    paths.update(
        {
            ref.value.relative_to(APP_DIR): ref == File.GENERATION_JSON
            for ref in generated
        }
    )
    return paths


# @testable infrastructure
def _recover(root):
    raw = _read(root, JOURNAL)
    if raw is None:
        return
    backup = json.loads(raw)
    paths = _restore_paths()
    if set(backup) != {p.as_posix() for p in paths}:
        raise CloudSettingsError(
            "The restore journal is invalid. Preserve it for owner recovery."
        )
    for path, private in paths.items():
        old = backup[path.as_posix()]
        if old is None:
            (root / path).unlink(missing_ok=True)
        else:
            _atomic_write_text(root / path, old, owner_only=private)
    (root / JOURNAL).unlink()


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_restore_preserves_previous_installation
# @matrix config deploy : config-files transactional-state recovery
def restore(root, project, version, bundle, receipt, source, operator, replace=False):
    app, dev = validate_bundle(bundle, project)
    local_app = _read(root, APP)
    local_dev = _read(root, DEV)
    if (
        local_app
        and decode_app_settings(yaml.safe_load(local_app)).get("GOOGLE_CLOUD_PROJECT")
        != project
    ):
        raise CloudSettingsError("This checkout already belongs to another project.")
    if (
        local_dev
        and yaml.safe_load(local_dev).get("gcloud_config", {}).get("PROJECT") != project
    ):
        raise CloudSettingsError(
            "This checkout's developer settings belong to another project."
        )
    if (
        any(_read(root, path) is not None for path in (APP, DEV, CA))
        and _snapshot(root) != receipt.get("fingerprint")
        and not replace
    ):
        raise CloudSettingsError(
            "Local settings have unrecorded edits. Publish them or explicitly --replace after review."
        )
    extra = {}
    app_text = bundle["app"]
    if operator:
        if not operator["ACCOUNT"].endswith(f"@{project}.iam.gserviceaccount.com"):
            raise CloudSettingsError(
                "The Cloud operator must be a service account in the selected project."
            )
        extra = {
            "operator_target": operator,
            "author_target": {k: dev["gcloud_config"][k] for k in operator},
        }
        dev["gcloud_config"].update(operator)
        version_from_source = json.loads(_read(root, Path("package.json")))["version"]
        if not isinstance(version_from_source, str) or not re.fullmatch(
            r"\d+\.\d+\.\d+", version_from_source
        ):
            raise CloudSettingsError("package.json has no valid release version.")
        raw_app = yaml.safe_load(app_text)
        extra["release_version"] = {
            "installation": raw_app.get("VERSION"),
            "checkout": version_from_source,
        }
        if raw_app.get("VERSION") != version_from_source:
            raw_app["VERSION"] = app["VERSION"] = version_from_source
            app_text = yaml.safe_dump(raw_app, allow_unicode=True)
    dev_text = (
        yaml.safe_dump(dev, allow_unicode=True, sort_keys=True)
        if operator
        else bundle["dev"]
    )
    _, deploy = build_deploy_yaml(app, File.APP_YAML.load())
    indexes = build_index_yaml(File.INDEX_YAML.load())
    manifest = build_manifest(app, File.MANIFEST_JSON.load())
    backup = {path.as_posix(): _read(root, path) for path in _restore_paths()}
    _atomic_write_text(root / JOURNAL, _json(backup), owner_only=True)
    try:
        for path, value in ((APP, app_text), (DEV, dev_text), (CA, bundle["ca"])):
            if value is None:
                (root / path).unlink(missing_ok=True)
            else:
                _atomic_write_text(root / path, value, owner_only=True)
        File.APP_YAML.save(deploy)
        File.INDEX_YAML.save(indexes)
        File.MANIFEST_JSON.save(manifest)
        write_generation_manifest()
        result = _record(root, project, version, source, **extra)
        (root / JOURNAL).unlink()
        return result
    except BaseException:
        _recover(root)
        raise


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_cloud_settings_cli
# @matrix config setup : cli-routing project-identity
def main(arguments):
    parser = argparse.ArgumentParser(prog="run.py cloud-settings")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("publish", "restore", "check"):
        command = commands.add_parser(action)
        command.add_argument(
            "--project",
            default=os.environ.get("LAGNIAPPE_CLOUD_PROJECT"),
            required=not os.environ.get("LAGNIAPPE_CLOUD_PROJECT"),
        )
        command.add_argument(
            "--configuration", default=os.environ.get("CLOUDSDK_ACTIVE_CONFIG_NAME")
        )
        command.add_argument(
            "--account", default=os.environ.get("LAGNIAPPE_CLOUD_ACCOUNT")
        )
        if action == "publish":
            command.add_argument("--from-checkout", type=Path, default=APP_DIR)
        else:
            command.add_argument("--version", default="current")
        if action == "restore":
            command.add_argument(
                "--operator",
                action="store_true",
                help="Use the selected service account for developer commands.",
            )
            command.add_argument(
                "--replace",
                action="store_true",
                help="Replace edited settings for this same installation.",
            )
    args = parser.parse_args(arguments)
    root = getattr(args, "from_checkout", APP_DIR).resolve()
    try:
        if not PROJECT.fullmatch(args.project) or not (root / "package.json").is_file():
            raise CloudSettingsError(
                "Select a Lagniappe checkout and a valid Google project."
            )
        if (root / FILES).resolve() != root / FILES:
            raise CloudSettingsError(
                "The settings directory must belong to the checkout."
            )
        with SetupProcessLock(root / FILES / ".lagniappe_setup.lock"):
            _recover(root)
            receipt = _receipt(root)
            if receipt and (
                receipt.get("project") != args.project
                or receipt.get("secret") != SECRET
            ):
                raise CloudSettingsError(
                    "The local receipt belongs to another settings bundle."
                )
            local = _read(root, DEV)
            target = yaml.safe_load(local)["gcloud_config"] if local else {}
            account = args.account or target.get("ACCOUNT")
            name = args.configuration or target.get("NAME")
            store = SecretManager(args.project, name, account)
            source = _source(root)
            if args.action == "publish":
                result = publish(root, args.project, store, receipt, source)
                version = result["version"]
            else:
                version, bundle = store.access(args.version)
                validate_bundle(bundle, args.project)
                if args.action == "restore":
                    operator = (
                        {"NAME": name, "ACCOUNT": account} if args.operator else None
                    )
                    restore(
                        root,
                        args.project,
                        version,
                        bundle,
                        receipt,
                        source,
                        operator,
                        args.replace,
                    )
                elif (
                    not receipt
                    or receipt.get("version") != version
                    or not _same_settings(
                        _local_bundle(root, args.project, receipt), bundle
                    )
                ):
                    raise CloudSettingsError(
                        "This checkout does not match the selected secret version."
                    )
        print(
            f"{args.action} succeeded for {args.project}/{SECRET} version {version} at checkout {source}."
        )
        return 0
    except CloudSettingsError as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        # Parser and provider exceptions can contain the input, including credentials.
        print(
            f"Cloud settings {args.action} failed ({type(error).__name__}).",
            file=sys.stderr,
        )
    return 1
