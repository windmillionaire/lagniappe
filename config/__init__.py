from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import yaml

os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"


APP_DIR = Path(
    os.environ.get(
        "LAGNIAPPE_CONFIG_ROOT",
        Path(__file__).resolve().parent.parent,
    )
).resolve()


def _find_config_file_dir():
    path = APP_DIR / "config" / "files"
    if path.exists():
        return path

    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_FILE_DIR = _find_config_file_dir()


class Directory(Enum):
    APP = APP_DIR
    CONFIG = CONFIG_FILE_DIR
    JS_CHUNKS = APP_DIR / "lagniappe/web/static/chunks"
    REPORTS = APP_DIR / "reports"
    TEST_FAILURES = REPORTS / "test_failures"
    TEST_REPORTS = REPORTS / "test_reports"
    SITE_IMAGES = APP_DIR / "lagniappe/web/static/images"

    def clean(self):
        if self.value.exists():
            shutil.rmtree(self.value)

    def get_or_create(self):
        if not self.value.exists():
            self.value.mkdir(parents=True, exist_ok=True)

        return self.value

    def create(self):
        return self.get_or_create()


class Environment(Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class File(Enum):
    MANIFEST_JSON = Directory.APP.value / "lagniappe/web/static/manifest.json"
    PACKAGE_JSON = Directory.APP.value / "package.json"
    APP_YAML = Directory.APP.value / "lagniappe.yaml"
    DEV_YAML = Directory.CONFIG.value / "lagniappe_dev.yaml"
    APP_SETTINGS_YAML = Directory.CONFIG.value / "lagniappe_settings.yaml"
    BROWSER_PROTOCOL_JSON = Directory.APP.value / "config/browser_protocol.json"
    INDEX_YAML = Directory.APP.value / "index.yaml"
    GENERATION_JSON = Directory.CONFIG.value / "lagniappe_generation.json"
    MANAGED_TEST_SERVER_PID = Directory.REPORTS.value / "test-server.pid"
    MANAGED_TEST_SERVER_LOG = Directory.REPORTS.value / "test-server.log"

    @property
    def convert(self):
        return self.name == "APP_SETTINGS_YAML"

    def exists(self):
        return self.value.exists()

    # @testable true
    # @tests tests_tooling/test_003_config.py::test_atomic_config_write_preserves_valid_file_and_restricts_secrets
    # @matrix config : permissions transactional-state utf8
    def save(self, data):
        if self.name.endswith("_YAML"):
            content = self._serialize_yaml(data)
        elif self.name.endswith("_JSON"):
            content = self._serialize_json(data)
        else:
            raise ValueError(f"Unknown file: {self.name}")
        return _atomic_write_text(
            self.value,
            content,
            owner_only=self in SECRET_BEARING_FILES,
        )

    # @testable true
    # @tests tests_tooling/test_003_config.py::test_python_config_package_resolves_expected_repo_files
    # @matrix config : config-files parsing
    def load(self):
        if not self.exists():
            return {}

        if self.name.endswith("_YAML"):
            return self._load_from_yaml()
        elif self.name.endswith("_JSON"):
            return self._load_from_json()
        else:
            raise ValueError(f"Unknown file: {self.value.name}")

    # @testable false
    # @covered-by config/__init__.py::File.load
    # @reason YAML parsing adapter is owned by the public file loader
    def _load_from_yaml(self):
        with open(self.value, "r", encoding="utf-8", newline="") as f:
            data = yaml.safe_load(f) or {}

        if not self.convert:
            return data

        data.pop("BUILD_ID", None)
        for k, v in data.items():
            value = str(v)
            if value.lower() == "true":
                data[k] = True
            elif value.lower() == "false":
                data[k] = False
            elif value.isdigit():
                data[k] = int(value)
            elif value.startswith("{"):
                data[k] = json.loads(value)
            elif value.startswith("["):
                data[k] = json.loads(value)

        return data

    # @testable false
    # @covered-by config/__init__.py::File.save
    # @reason deterministic YAML serialization is owned by atomic file save
    def _serialize_yaml(self, data):
        if not data:
            raise ValueError("Nothing to save")

        yaml_data = data.copy()
        if self.convert:
            yaml_data.pop("BUILD_ID", None)
            for key, value in yaml_data.items():
                if isinstance(value, (list, dict)):
                    yaml_data[key] = json.dumps(value)
                elif not isinstance(value, str) and value is not None:
                    yaml_data[key] = str(value)
                elif value:
                    yaml_data[key] = value

        return yaml.dump(
            yaml_data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=True,
        )

    # @testable false
    # @covered-by config/__init__.py::File.load
    # @reason JSON parsing adapter is owned by the public file loader
    def _load_from_json(self):
        with open(self.value, "r", encoding="utf-8", newline="") as f:
            return json.load(f)

    # @testable false
    # @covered-by config/__init__.py::File.save
    # @reason deterministic JSON serialization is owned by atomic file save
    def _serialize_json(self, data):
        if not data:
            raise ValueError("Nothing to save")

        return f"{json.dumps(data, indent=2, sort_keys=True)}\n"


GENERATION_SCHEMA_VERSION = 2
GENERATION_FILES = (
    File.APP_YAML,
    File.APP_SETTINGS_YAML,
    File.DEV_YAML,
    File.PACKAGE_JSON,
    File.INDEX_YAML,
    File.MANIFEST_JSON,
)
GENERATION_SOURCE_FILE = APP_DIR / "config" / "constants.py"
SECRET_BEARING_FILES = frozenset(
    {
        File.APP_SETTINGS_YAML,
        File.DEV_YAML,
        File.GENERATION_JSON,
    }
)


# @testable false
# @covered-by config/__init__.py::_atomic_write_text
# @reason Windows ACL application is a platform adapter owned by atomic writes
def _restrict_windows_acl(path):
    """Best-effort owner ACL for the supported Google Cloud SDK cmd shell."""
    if os.name != "nt":
        return True
    username = str(os.environ.get("USERNAME") or "").strip()
    if not username:
        return False
    try:
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{username}:(R,W)",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


# @testable false
# @covered-by config/__init__.py::_atomic_write_text
# @reason platform permission adapter is owned by atomic configuration writes
def _apply_file_permissions(path, mode, *, owner_only):
    if os.name == "nt":
        if owner_only and not _restrict_windows_acl(path):
            print(
                f"WARNING: Could not restrict the Windows ACL for {path}. "
                "Protect this secret-bearing file manually before continuing."
            )
            return False
        return True
    os.chmod(path, mode)
    return True


# @testable false
# @covered-by config/__init__.py::_atomic_write_text
# @reason platform directory-fsync adapter is owned by atomic writes
def _fsync_directory(path):
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# @testable true
# @tests tests_tooling/test_003_config.py::test_atomic_config_write_preserves_valid_file_and_restricts_secrets
# @matrix config setup : permissions transactional-state utf8
def _atomic_write_text(path, content, *, owner_only=False):
    """Atomically replace one non-empty UTF-8 text file in its own directory."""
    path = Path(path)
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"Refusing to replace {path.name} with an empty document.")
    encoded = content.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        _apply_file_permissions(
            path,
            0o600 if owner_only else 0o644,
            owner_only=owner_only,
        )
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        mode = 0o600 if owner_only else 0o644
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as temporary:
            descriptor = None
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        _apply_file_permissions(path, mode, owner_only=owner_only)
        _fsync_directory(path.parent)
        return True
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


# @testable false
# @covered-by config/__init__.py::write_generation_manifest
# @covered-by config/__init__.py::verify_generation_manifest
# @reason completeness inspection is owned by generation commit and validation
def _require_generation_files():
    for file_ref in GENERATION_FILES:
        if not file_ref.exists() or file_ref.value.stat().st_size == 0:
            raise RuntimeError(
                f"Generated configuration is incomplete: {file_ref.value.name} "
                "is missing or empty."
            )


# @testable false
# @covered-by config/__init__.py::write_generation_manifest
# @covered-by config/__init__.py::verify_generation_manifest
# @reason source fingerprinting is owned by generation commit and validation
def _generation_source_checksum():
    if (
        not GENERATION_SOURCE_FILE.is_file()
        or GENERATION_SOURCE_FILE.stat().st_size == 0
    ):
        raise RuntimeError(
            "Generated configuration source is incomplete: constants.py is "
            "missing or empty."
        )
    content = GENERATION_SOURCE_FILE.read_bytes()
    stable_content = re.sub(
        rb"(?m)^BUILD_ID\s*=.*(?:\r?\n|$)",
        b"",
        content,
    )
    return hashlib.sha256(stable_content).hexdigest()


# @testable true
# @tests tests_tooling/test_003_config.py::test_generation_manifest_tracks_constants_and_required_outputs
# @matrix config setup : completeness generation source-marker
def write_generation_manifest():
    """Record the constants generation after every output has been persisted."""
    _require_generation_files()
    source_path = GENERATION_SOURCE_FILE.relative_to(APP_DIR).as_posix()
    source_checksum = _generation_source_checksum()
    return File.GENERATION_JSON.save(
        {
            "schema": GENERATION_SCHEMA_VERSION,
            "generation": source_checksum,
            "source": {
                "path": source_path,
                "sha256": source_checksum,
            },
        }
    )


# @testable true
# @tests tests_tooling/test_003_config.py::test_generation_manifest_tracks_constants_and_required_outputs
# @matrix config deploy : completeness generation source-marker
def verify_generation_manifest():
    """Fail when required outputs or their constants generation are stale."""
    try:
        manifest = File.GENERATION_JSON.load()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "Generated configuration manifest is unreadable. Rerun setup."
        ) from error
    if manifest.get("schema") != GENERATION_SCHEMA_VERSION:
        raise RuntimeError(
            "Generated configuration manifest is missing or unsupported. Rerun setup."
        )
    _require_generation_files()
    source_path = GENERATION_SOURCE_FILE.relative_to(APP_DIR).as_posix()
    source_checksum = _generation_source_checksum()
    if manifest.get("source") != {
        "path": source_path,
        "sha256": source_checksum,
    }:
        raise RuntimeError(
            "Generated configuration was created from a different constants "
            "generation. Rerun setup before deploying."
        )
    if manifest.get("generation") != source_checksum:
        raise RuntimeError(
            "Generated configuration manifest checksum is invalid. Rerun setup."
        )
    return True


# @testable infrastructure
class Settings:
    DEPLOY = File.APP_YAML.load()
    APP = File.APP_SETTINGS_YAML.load()
    DEV = File.DEV_YAML.load()
    NODE = File.PACKAGE_JSON.load()
    INDEX = File.INDEX_YAML.load()
    MANIFEST = File.MANIFEST_JSON.load()
    BROWSER_PROTOCOL = File.BROWSER_PROTOCOL_JSON.load()

    GCLOUD_CONFIG = None
    DEV_CONFIG = None
    TEST_CONFIG = None

    _DEV_SETTINGS = None
    _TEST_SETTINGS = None

    def __init__(self):
        self.GCLOUD_CONFIG = self.DEV.get("gcloud_config", {})
        self.DEV_CONFIG = self.DEV.get("dev_settings", {})
        self.TEST_CONFIG = self.DEV.get("test_settings", {})

    def save(self, *file_refs):
        """Persist only changed selected files, then commit one generation manifest."""
        self._DEV_SETTINGS = None
        self._TEST_SETTINGS = None
        selected = tuple(file_refs) or GENERATION_FILES
        invalid = [
            file_ref for file_ref in selected if file_ref not in GENERATION_FILES
        ]
        if invalid:
            raise ValueError(f"Unsupported generated file selection: {invalid}")

        if File.DEV_YAML in selected:
            self.DEV["gcloud_config"] = self.GCLOUD_CONFIG
            self.DEV["dev_settings"] = self.DEV_CONFIG
            self.DEV["test_settings"] = self.TEST_CONFIG

        documents = {
            File.APP_YAML: self.DEPLOY,
            File.APP_SETTINGS_YAML: self.APP,
            File.DEV_YAML: self.DEV,
            File.PACKAGE_JSON: self.NODE,
            File.INDEX_YAML: self.INDEX,
            File.MANIFEST_JSON: self.MANIFEST,
        }
        changed = [
            file_ref.name for file_ref in selected if file_ref.save(documents[file_ref])
        ]
        if all(file_ref.exists() for file_ref in GENERATION_FILES):
            write_generation_manifest()
        return tuple(changed)

    @property
    def app_settings(self):
        with open(
            File.APP_SETTINGS_YAML.value,
            "r",
            encoding="utf-8",
            newline="",
        ) as f:
            data = yaml.safe_load(f) or {}
        data.pop("BUILD_ID", None)
        return data

    @property
    def app_config(self):
        return self.APP

    @property
    def dev_config(self):
        if self._DEV_SETTINGS is not None:
            return self._DEV_SETTINGS

        app_settings = File.APP_SETTINGS_YAML.load()
        app_settings.update(self.DEV_CONFIG)

        self._DEV_SETTINGS = app_settings

        return self._DEV_SETTINGS

    @property
    def test_config(self):
        if self._TEST_SETTINGS is not None:
            return self._TEST_SETTINGS

        from . import constants

        app_settings = File.APP_SETTINGS_YAML.load()
        app_settings.update(
            {
                "AGENT_ACCESS_ENABLED": True,
                "AGENT_ACCESS_EMAIL": constants.DEFAULT_AGENT_ACCESS_EMAIL,
                "AGENT_ACCESS_NAME": constants.DEFAULT_AGENT_ACCESS_NAME,
                "AGENT_ACCESS_CODE": constants.DEFAULT_AGENT_ACCESS_TEST_CODE,
                "ANALYTICS": True,
                "AI_OBSERVABILITY": True,
                "PUBLIC_MANUAL": True,
            }
        )
        app_settings.update(self.TEST_CONFIG)
        from .hosted_e2e import hosted_e2e_settings_overrides

        hosted_overrides = hosted_e2e_settings_overrides(app_settings)
        if hosted_overrides:
            app_settings.update(hosted_overrides)
        else:
            server_name = app_settings["SERVER_NAME"]
            server_port = app_settings["SERVER_PORT"]
            app_settings["BASE_URL"] = f"http://{server_name}:{server_port}"

        self._TEST_SETTINGS = app_settings

        return self._TEST_SETTINGS


SETTINGS = Settings()

from .deployment import apply_deployment_settings, normalize_deployment_settings

__all__ = [
    "verify_generation_manifest",
    "write_generation_manifest",
    "apply_deployment_settings",
    "normalize_deployment_settings",
    "SETTINGS",
    "Environment",
    "Directory",
    "File",
]
