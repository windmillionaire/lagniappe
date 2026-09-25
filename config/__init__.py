from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import MappingProxyType

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


# @testable false
# @covered-by config/__init__.py::File.load
# @covered-by installer/doctor.py::run_doctor
# @reason shared saved-settings decoding is exercised by normal loading and read-only diagnostics
def decode_app_settings(data):
    """Decode saved scalar/JSON strings while preserving native YAML values."""
    decoded = dict(data)
    decoded.pop("BUILD_ID", None)
    for key, value in decoded.items():
        if not isinstance(value, str):
            continue
        if value.lower() == "true":
            decoded[key] = True
        elif value.lower() == "false":
            decoded[key] = False
        elif value.isdigit():
            decoded[key] = int(value)
        elif value.startswith(("{", "[")):
            decoded[key] = json.loads(value)
    return decoded


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
    TEST_SESSION_STATE = Directory.REPORTS.value / "test-session.json"
    TEST_SESSION_LOCK = Directory.REPORTS.value / "test-session.lock"

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

        return decode_app_settings(data)

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


# @testable false
# @covered-by config/__init__.py::RuntimeSettings
# @reason recursive value ownership is exercised through snapshot construction
def _freeze_settings(value):
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_settings(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_settings(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_settings(item) for item in value)
    return value


# @testable false
# @covered-by config/__init__.py::RuntimeSettings
# @reason mutable consumer copies are exercised through the snapshot API
def _copy_settings(value):
    if isinstance(value, Mapping):
        return {key: _copy_settings(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_copy_settings(item) for item in value]
    if isinstance(value, frozenset):
        return set(value)
    return value


# @testable true
# @tests tests_tooling/test_003_config.py::test_runtime_settings_own_nested_values_and_return_independent_copies
# @matrix config : configuration transactional-state
@dataclass(frozen=True)
class RuntimeSettings:
    """Owned, immutable settings for one environment; values stay out of repr."""

    environment: Environment
    values: Mapping[str, object] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "environment", Environment(self.environment))
        object.__setattr__(self, "values", _freeze_settings(self.values))

    def as_dict(self):
        """Return plain containers owned by the caller for runtime normalization."""
        return _copy_settings(self.values)


# @testable false
# @covered-by config/__init__.py::load_runtime_settings
# @covered-by config/__init__.py::SettingsDraft.snapshot
# @reason shared environment precedence is exercised by saved and draft projections
def _project_runtime_settings(app_settings, overrides, environment):
    environment = Environment(environment)
    projected = dict(app_settings)
    if environment == Environment.TESTING:
        from . import constants

        projected.update(
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
    projected.update(overrides)
    if environment == Environment.TESTING:
        from .hosted_e2e import hosted_e2e_settings_overrides

        hosted_overrides = hosted_e2e_settings_overrides(projected)
        if hosted_overrides:
            projected.update(hosted_overrides)
        else:
            projected["BASE_URL"] = (
                f"http://{projected['SERVER_NAME']}:{projected['SERVER_PORT']}"
            )
    return RuntimeSettings(environment, projected)


# @testable true
# @tests tests_tooling/test_003_config.py::test_runtime_loading_is_independent_of_drafts_and_generated_documents
# @tests tests_tooling/test_003_config.py::test_runtime_and_draft_projections_preserve_environment_precedence
# @tests tests_tooling/test_003_config.py::test_hosted_runtime_projection_preserves_validated_overrides
# @matrix config : config-files configuration parsing
def load_runtime_settings(environment):
    """Read saved settings for one process without constructing an installer draft."""
    environment = Environment(environment)
    app_settings = File.APP_SETTINGS_YAML.load()
    overrides = {}
    if environment != Environment.PRODUCTION:
        development = File.DEV_YAML.load()
        key = (
            "dev_settings"
            if environment == Environment.DEVELOPMENT
            else "test_settings"
        )
        overrides = development.get(key, {})
    return _project_runtime_settings(app_settings, overrides, environment)


# @testable true
# @tests tests_tooling/test_003_config.py::test_saved_settings_reader_preserves_raw_values_without_loading_a_draft
# @matrix config : config-files parsing
def read_saved_app_settings():
    """Read canonical persisted values for configuration display and recovery."""
    with open(
        File.APP_SETTINGS_YAML.value, "r", encoding="utf-8", newline=""
    ) as stream:
        data = yaml.safe_load(stream) or {}
    data.pop("BUILD_ID", None)
    return data


# @testable true
# @tests tests_tooling/test_003_config.py::test_settings_drafts_own_documents_and_preserve_internal_aliases
# @matrix config : configuration transactional-state
class SettingsDraft:
    """Mutable generated documents owned by one installer or runner session."""

    def __init__(self):
        self.DEPLOY = File.APP_YAML.load()
        self.APP = File.APP_SETTINGS_YAML.load()
        self.DEV = File.DEV_YAML.load()
        self.NODE = File.PACKAGE_JSON.load()
        self.INDEX = File.INDEX_YAML.load()
        self.MANIFEST = File.MANIFEST_JSON.load()
        self.BROWSER_PROTOCOL = File.BROWSER_PROTOCOL_JSON.load()
        self.GCLOUD_CONFIG = self.DEV.get("gcloud_config", {})
        self.DEV_CONFIG = self.DEV.get("dev_settings", {})
        self.TEST_CONFIG = self.DEV.get("test_settings", {})

    # @testable true
    # @tests tests_tooling/test_003_config.py::test_draft_save_preserves_identity_and_publishes_only_selected_files
    # @matrix config : config-files transactional-state
    def save(self, *file_refs):
        """Persist only changed selected files, then commit one generation manifest."""
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
    # @testable false
    # @covered-by config/__init__.py::read_saved_app_settings
    # @reason compatibility adapter for persisted configuration exports
    def app_settings(self):
        return read_saved_app_settings()

    # @testable true
    # @tests tests_tooling/test_003_config.py::test_runtime_and_draft_projections_preserve_environment_precedence
    # @tests tests_tooling/test_003_config.py::test_draft_projections_observe_edits_without_saving_or_aliasing
    # @matrix config : configuration transactional-state
    def snapshot(self, environment):
        """Project current draft values without reading or writing saved settings."""
        environment = Environment(environment)
        overrides = {
            Environment.PRODUCTION: {},
            Environment.DEVELOPMENT: self.DEV_CONFIG,
            Environment.TESTING: self.TEST_CONFIG,
        }[environment]
        return _project_runtime_settings(self.APP, overrides, environment)

    @property
    # @testable false
    # @covered-by config/__init__.py::SettingsDraft.snapshot
    # @reason compatibility adapter for an independent production draft projection
    def app_config(self):
        return self.snapshot(Environment.PRODUCTION).as_dict()

    @property
    # @testable false
    # @covered-by config/__init__.py::SettingsDraft.snapshot
    # @reason compatibility adapter for an independent development draft projection
    def dev_config(self):
        return self.snapshot(Environment.DEVELOPMENT).as_dict()

    @property
    # @testable false
    # @covered-by config/__init__.py::SettingsDraft.snapshot
    # @reason compatibility adapter for an independent testing draft projection
    def test_config(self):
        return self.snapshot(Environment.TESTING).as_dict()


Settings = SettingsDraft
# reload(config) is the source-upgrade boundary. Discard both the lazy instance
# and any eagerly bound SETTINGS left by an older source generation.
globals().pop("SETTINGS", None)
_settings_draft = None


# @testable true
# @tests tests_tooling/test_003_config.py::test_settings_singleton_is_lazy_and_reloads_saved_documents
# @matrix config setup : config-files git-upgrade
def __getattr__(name):
    if name != "SETTINGS":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    global _settings_draft
    if _settings_draft is None:
        _settings_draft = SettingsDraft()
    return _settings_draft


from .deployment import apply_deployment_settings, normalize_deployment_settings

__all__ = [
    "verify_generation_manifest",
    "write_generation_manifest",
    "apply_deployment_settings",
    "normalize_deployment_settings",
    "SETTINGS",
    "Settings",
    "SettingsDraft",
    "RuntimeSettings",
    "load_runtime_settings",
    "read_saved_app_settings",
    "Environment",
    "Directory",
    "File",
]
