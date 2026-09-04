"""Repository-only tests for MCP release and deployment artifacts."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from runner import mcp_artifact
from runner.context import GIT_CLI


def _write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")


def _fixture_pyproject(version="0.1.0") -> str:
    return f'''\
[build-system]
requires = ["uv_build==0.12.9"]
build-backend = "uv_build"

[project]
name = "lagniappe-mcp"
version = "{version}"
description = "fixture"
requires-python = ">=3.14,<3.15"
license = "GPL-3.0-or-later"
dependencies = ["fixture-dependency==1.2.3"]

[project.urls]
Source = "https://example.test/source"
License = "https://example.test/license"

[project.scripts]
lagniappe-mcp = "lagniappe_mcp.cli:main"

[dependency-groups]
test = ["pytest==9.1.1", "uv-build==0.12.9"]

[tool.uv]
required-version = "==0.12.9"
'''


def _fixture_lock(version="0.1.0") -> str:
    return f'''\
version = 1
revision = 3
requires-python = "==3.14.*"

[[package]]
name = "fixture-dependency"
version = "1.2.3"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "https://files.pythonhosted.org/packages/fixture_dependency-1.2.3-py3-none-any.whl", hash = "sha256:{"a" * 64}", size = 1234 }},
]

[[package]]
name = "lagniappe-mcp"
version = "{version}"
source = {{ editable = "." }}
dependencies = [{{ name = "fixture-dependency" }}]

[package.dev-dependencies]
test = [{{ name = "pytest" }}, {{ name = "uv-build" }}]

[package.metadata]
requires-dist = [
  {{ name = "fixture-dependency", specifier = "==1.2.3" }},
]

[package.metadata.requires-dev]
test = [
  {{ name = "pytest", specifier = "==9.1.1" }},
  {{ name = "uv-build", specifier = "==0.12.9" }},
]

[[package]]
name = "pytest"
version = "9.1.1"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "https://files.pythonhosted.org/packages/pytest-9.1.1-py3-none-any.whl", hash = "sha256:{"b" * 64}", size = 1234 }},
]

[[package]]
name = "uv-build"
version = "0.12.9"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "https://files.pythonhosted.org/packages/uv_build-0.12.9-py3-none-any.whl", hash = "sha256:{"c" * 64}", size = 1234 }},
]
'''


def _wheel_bytes(
    version: str,
    *,
    payload="fixture = True\n",
    generator="fixture",
) -> bytes:
    prefix = f"lagniappe_mcp-{version}.dist-info"
    files = {
        "lagniappe_mcp/__init__.py": payload.encode(),
        "lagniappe_mcp/cli.py": b"def main(): pass\n",
        "lagniappe_mcp/limits.py": (
            b'API_VERSION = "v1"\nCONTRACT_VERSION_MIN = 6\nCONTRACT_VERSION_MAX = 6\n'
        ),
        f"{prefix}/METADATA": (
            "Metadata-Version: 2.4\n"
            "Name: lagniappe-mcp\n"
            f"Version: {version}\n"
            "License-Expression: GPL-3.0-or-later\n"
            "Requires-Python: >=3.14,<3.15\n"
            "Requires-Dist: fixture-dependency==1.2.3\n"
            "Project-URL: Source, https://example.test/source\n"
            "Project-URL: License, https://example.test/license\n"
            "\nfixture\n"
        ).encode(),
        f"{prefix}/WHEEL": (
            "Wheel-Version: 1.0\n"
            f"Generator: {generator}\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode(),
        f"{prefix}/entry_points.txt": (
            "[console_scripts]\nlagniappe-mcp = lagniappe_mcp.cli:main\n"
        ).encode(),
    }
    record_name = f"{prefix}/RECORD"
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
        writer.writerow((name, f"sha256={digest.decode()}", len(data)))
    writer.writerow((record_name, "", ""))
    files[record_name] = record.getvalue().encode()

    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("lagniappe_mcp/", f"{prefix}/"):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o40755 << 16
            archive.writestr(info, b"")
        for name, data in files.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return result.getvalue()


def _prepare_source(
    repo_root: Path,
    version="0.1.0",
    *,
    payload="fixture = True\n",
) -> None:
    _write(
        repo_root / "clients/lagniappe_mcp/pyproject.toml", _fixture_pyproject(version)
    )
    _write(repo_root / "clients/lagniappe_mcp/uv.lock", _fixture_lock(version))
    _write(
        repo_root / "clients/lagniappe_mcp/uv-bootstrap.json",
        json.dumps({"schema": 1, "version": "0.12.9"}),
    )
    _write(repo_root / "clients/lagniappe_mcp/README.md", "fixture\n")
    _write(
        repo_root / "clients/lagniappe_mcp/src/lagniappe_mcp/__init__.py",
        payload,
    )
    _write(
        repo_root / "clients/lagniappe_mcp/src/lagniappe_mcp/cli.py",
        "def main(): pass\n",
    )
    _write(
        repo_root / "clients/lagniappe_mcp/src/lagniappe_mcp/limits.py",
        'API_VERSION = "v1"\nCONTRACT_VERSION_MIN = 6\nCONTRACT_VERSION_MAX = 6\n',
    )
    _write(
        repo_root / "lagniappe/core/tools/ai/external_api.py",
        "CONTRACT_VERSION = 6\n"
        'SUPPORTED_PLAN_TOOLS = ("ask", "create", "organize")\n'
        "MAX_PLAN_FILES = 20\n"
        "MAX_FILE_BYTES = 30 * 1024 * 1024\n"
        "MAX_VALIDATION_ERRORS = 20\n"
        'UPLOAD_BATCH_ID_PATTERN = r"^[A-Za-z0-9_-]{16,128}$"\n',
    )
    _write(
        repo_root / "lagniappe/web/routes/api/main.py",
        '''\
@api.get("/openapi.json")
@_route
def openapi_document():
    """Fixture OpenAPI schema."""
    def json_content(schema):
        return {"content": {"application/json": {"schema": schema}}}

    paths = {
        "/api/v1/plans": {
            "post": {
                "requestBody": json_content({
                    "type": "object",
                    "properties": {
                        "tool": {"enum": list(external_api.SUPPORTED_PLAN_TOOLS)},
                        "files": {"maxItems": external_api.MAX_PLAN_FILES},
                        "size": {"maximum": external_api.MAX_FILE_BYTES},
                        "contract": {"const": external_api.CONTRACT_VERSION},
                        "errors": {"maxItems": external_api.MAX_VALIDATION_ERRORS},
                    },
                }),
            },
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{CONFIG.APP_NAME} External Agent API"},
        "servers": [{"url": _api_absolute_url("/").rstrip("/")}],
        "paths": paths,
    }
''',
    )
    _write(repo_root / "config/constants.py", 'BUILD_ID = "b1234567"\n')
    _write(repo_root / "package.json", json.dumps({"version": "1.2.3"}))
    _write(
        repo_root / "lagniappe/web/static/build.json",
        json.dumps({"mode": "production", "version": "1.2.3", "build_id": "b1234567"}),
    )


def _add_release(
    repo_root: Path, version="0.1.0", *, supported=True, payload="fixture = True\n"
):
    project = mcp_artifact._load_project(repo_root)
    temporary = (
        repo_root
        / mcp_artifact.MCP_PROJECT_RELATIVE
        / mcp_artifact._wheel_filename(version)
    )
    _write(temporary, _wheel_bytes(version, payload=payload))
    release_project = mcp_artifact.ProjectMetadata(
        version=version,
        requires_python=project.requires_python,
        dependencies=project.dependencies,
        source_url=project.source_url,
        license_expression=project.license_expression,
        license_url=project.license_url,
    )
    metadata = mcp_artifact._inspect_wheel(temporary, release_project, repo_root)
    entry = mcp_artifact._release_entry(repo_root, release_project, metadata)
    entry["supported"] = supported
    destination = (
        repo_root
        / mcp_artifact.MCP_RELEASES_RELATIVE
        / mcp_artifact._artifact_relative_path(version, metadata.sha256)
    )
    _write(destination, temporary.read_bytes())
    temporary.unlink()
    return entry


def _prepare_release(repo_root: Path):
    _prepare_source(repo_root)
    entry = _add_release(repo_root)
    project = mcp_artifact._load_project(repo_root)
    ledger = mcp_artifact._new_ledger(project, entry)
    _write(
        repo_root / mcp_artifact.MCP_LEDGER_RELATIVE,
        mcp_artifact._canonical_json(ledger),
    )
    return ledger


# @matrix mcp-package agent-api : frozen-openapi canonical-compatibility
def test_compatibility_hashes_canonical_frozen_openapi_document(tmp_path):
    _prepare_source(tmp_path)
    document = mcp_artifact._frozen_openapi_document(tmp_path)
    compatibility = mcp_artifact._compatibility(tmp_path)

    assert document["servers"] == [{"url": "https://application.invalid"}]
    assert document["info"]["title"] == "Lagniappe External Agent API"
    assert "openapi_source_sha256" not in compatibility
    assert (
        compatibility["openapi_sha256"]
        == hashlib.sha256(mcp_artifact._canonical_json(document)).hexdigest()
    )

    source_path = tmp_path / mcp_artifact.OPENAPI_SOURCE_RELATIVE
    original = source_path.read_text(encoding="utf-8")
    _write(source_path, "# presentation-only comment\n" + original)
    assert mcp_artifact._compatibility(tmp_path) == compatibility

    _write(source_path, original.replace("_api_absolute_url", "absolute_url"))
    with pytest.raises(mcp_artifact.McpArtifactError, match="unsafe name"):
        mcp_artifact._compatibility(tmp_path)

    _write(source_path, original.replace("Fixture OpenAPI schema.", "Changed schema."))
    assert mcp_artifact._compatibility(tmp_path) == compatibility
    _write(source_path, original.replace('"type": "object"', '"type": "string"', 1))
    assert (
        mcp_artifact._compatibility(tmp_path)["openapi_sha256"]
        != compatibility["openapi_sha256"]
    )

    assert (
        mcp_artifact._wheel_score(
            "dependency-1.0-cp314-cp314-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        )
        == 550
    )
    assert (
        mcp_artifact._wheel_score(
            "dependency-1.0-cp314-cp314-manylinux_2_99_x86_64.whl"
        )
        is None
    )


# @matrix frontend-build mcp-package : artifact-order content-addressing deploy-preflight deploy-surface
# @pair mcp-package:immutable-ledger
def test_artifact_builder_copies_only_supported_content_addressed_wheels(tmp_path):
    ledger = _prepare_release(tmp_path)

    manifest = mcp_artifact.assemble_deployment_artifacts(tmp_path)
    current = ledger["releases"][0]
    deployed_wheel = (
        tmp_path
        / mcp_artifact.MCP_DEPLOY_RELATIVE
        / "releases"
        / mcp_artifact._artifact_relative_path(current["version"], current["sha256"])
    )

    assert deployed_wheel.read_bytes() == _wheel_bytes("0.1.0")
    assert manifest["current"] == current
    assert manifest["releases"] == [current]
    assert manifest["application"] == {
        "version": "1.2.3",
        "build_id": "b1234567",
        "frontend_build_sha256": hashlib.sha256(
            (tmp_path / "lagniappe/web/static/build.json").read_bytes()
        ).hexdigest(),
    }
    assert not any(
        value.startswith(("http://", "https://"))
        for value in (current["artifact_path"],)
    )
    assert mcp_artifact.check_deployment_artifacts(tmp_path, require_git=False)


# @matrix mcp-package release : immutable-ledger historical-wheel source-verification source-versioning
def test_historical_wheel_remains_valid_after_current_source_changes(tmp_path):
    ledger = _prepare_release(tmp_path)
    old_entry = ledger["releases"][0]

    _write(
        tmp_path / "clients/lagniappe_mcp/pyproject.toml",
        _fixture_pyproject("0.2.0"),
    )
    _write(
        tmp_path / "clients/lagniappe_mcp/uv.lock",
        _fixture_lock("0.2.0"),
    )
    _write(
        tmp_path / "clients/lagniappe_mcp/src/lagniappe_mcp/__init__.py",
        "fixture_v2 = True\n",
    )
    new_entry = _add_release(
        tmp_path,
        version="0.2.0",
        payload="fixture_v2 = True\n",
    )
    ledger["current"] = "0.2.0"
    ledger["releases"].append(new_entry)
    _write(
        tmp_path / mcp_artifact.MCP_LEDGER_RELATIVE,
        mcp_artifact._canonical_json(ledger),
    )

    manifest = mcp_artifact.assemble_deployment_artifacts(tmp_path)
    assert manifest["current"]["version"] == "0.2.0"
    assert [entry["version"] for entry in manifest["releases"]] == [
        "0.1.0",
        "0.2.0",
    ]
    assert old_entry["source_sha256"] != new_entry["source_sha256"]
    assert mcp_artifact.check_deployment_artifacts(tmp_path, require_git=False)

    incompatible = json.loads(json.dumps(ledger))
    incompatible["releases"][0]["compatibility"]["contract_min"] = 5
    incompatible["releases"][0]["compatibility"]["contract_max"] = 5
    with pytest.raises(mcp_artifact.McpArtifactError, match="incompatible"):
        mcp_artifact._manifest(tmp_path, incompatible)


# @matrix mcp-package release : historical-wheel immutable-ledger promotion source-versioning
def test_artifact_builder_promotes_new_source_over_historical_current(
    tmp_path, monkeypatch
):
    original = _prepare_release(tmp_path)["releases"][0]
    _prepare_source(tmp_path, version="0.2.0", payload="fixture_v2 = True\n")

    def build(_repo_root, output):
        output.mkdir(parents=True)
        path = output / mcp_artifact._wheel_filename("0.2.0")
        _write(path, _wheel_bytes("0.2.0", payload="fixture_v2 = True\n"))
        return path

    monkeypatch.setattr(mcp_artifact, "_run_wheel_build", build)

    promoted = mcp_artifact.build_and_promote_release(tmp_path)

    assert promoted["current"] == "0.2.0"
    assert [release["version"] for release in promoted["releases"]] == [
        "0.1.0",
        "0.2.0",
    ]
    assert promoted["releases"][0] == original
    assert mcp_artifact.check_deployment_artifacts(tmp_path, require_git=False)


# @matrix mcp-package : dependency-graph fail-closed immutable-ledger immutable-release locked-dependencies promotion release-validation reproducible-build url-policy
def test_artifact_builder_rejects_rebinding_and_corruption(tmp_path, monkeypatch):
    ledger = _prepare_release(tmp_path)
    original_digest = ledger["releases"][0]["sha256"]

    lock_path = tmp_path / mcp_artifact.LOCK_RELATIVE
    lock_content = lock_path.read_text(encoding="utf-8")
    _write(
        lock_path,
        lock_content.replace(
            'source = { registry = "https://pypi.org/simple" }\n',
            'source = { registry = "https://pypi.org/simple" }\n'
            'dependencies = [{ name = "missing-runtime-pin" }]\n',
            1,
        ),
    )
    with pytest.raises(mcp_artifact.McpArtifactError, match="unresolved"):
        mcp_artifact._dependency_graph(
            tmp_path,
            mcp_artifact._load_project(tmp_path),
        )
    _write(lock_path, lock_content)

    unexpected = tmp_path / mcp_artifact.MCP_RELEASES_RELATIVE / "unexpected.txt"
    _write(unexpected, "not a release artifact\n")
    with pytest.raises(mcp_artifact.McpArtifactError, match="unlisted"):
        mcp_artifact.assemble_deployment_artifacts(tmp_path)
    unexpected.unlink()

    package_data = (
        tmp_path / mcp_artifact.MCP_PROJECT_RELATIVE / "src/lagniappe_mcp/injected.json"
    )
    _write(package_data, '{"untracked": true}\n')
    with pytest.raises(mcp_artifact.McpArtifactError, match="non-Python source"):
        mcp_artifact._source_digest(tmp_path)
    package_data.unlink()

    def changed_build(_repo_root, output):
        path = output / mcp_artifact._wheel_filename("0.1.0")
        _write(path, _wheel_bytes("0.1.0", generator="changed"))
        return path

    monkeypatch.setattr(mcp_artifact, "_run_wheel_build", changed_build)
    with pytest.raises(mcp_artifact.McpArtifactError, match="already bound"):
        mcp_artifact.build_and_promote_release(tmp_path)
    assert (
        mcp_artifact.load_release_ledger(tmp_path)["releases"][0]["sha256"]
        == original_digest
    )

    wheel = next((tmp_path / mcp_artifact.MCP_RELEASES_RELATIVE).rglob("*.whl"))
    original_wheel = wheel.read_bytes()
    wheel.write_bytes(mcp_artifact.LFS_POINTER + b"\noid sha256:" + b"0" * 64)
    with pytest.raises(mcp_artifact.McpArtifactError, match="Git LFS pointer"):
        mcp_artifact.assemble_deployment_artifacts(tmp_path)
    wheel.write_bytes(original_wheel)
    wheel.write_bytes(wheel.read_bytes()[:-10])
    with pytest.raises(mcp_artifact.McpArtifactError, match="corrupt"):
        mcp_artifact.assemble_deployment_artifacts(tmp_path)

    for suffix in ("?token=secret", "#fragment"):
        with pytest.raises(mcp_artifact.McpArtifactError, match="query, or fragment"):
            mcp_artifact._require_https_url(
                f"https://files.pythonhosted.org/package.whl{suffix}",
                label="dependency URL",
            )


# @matrix mcp-package release : expanded-size fail-closed member-count release-validation
# @source runner/mcp_artifact.py::_inspect_wheel
@pytest.mark.parametrize(
    ("limit_name", "expected"),
    [
        pytest.param(
            "MAX_WHEEL_MEMBERS", "invalid or duplicate file list", id="members"
        ),
        pytest.param(
            "MAX_WHEEL_EXPANDED_BYTES",
            "expands beyond its safety ceiling",
            id="expanded-bytes",
        ),
    ],
)
def test_artifact_builder_enforces_wheel_member_and_expanded_size_ceilings(
    tmp_path,
    monkeypatch,
    limit_name,
    expected,
):
    _prepare_source(tmp_path)
    project = mcp_artifact._load_project(tmp_path)
    wheel = (
        tmp_path
        / mcp_artifact.MCP_PROJECT_RELATIVE
        / mcp_artifact._wheel_filename(project.version)
    )
    _write(wheel, _wheel_bytes(project.version))
    monkeypatch.setattr(mcp_artifact, limit_name, 1)

    with pytest.raises(mcp_artifact.McpArtifactError, match=expected):
        mcp_artifact._inspect_wheel(
            wheel,
            project,
            tmp_path,
            match_current_source=False,
        )


# @matrix mcp-package release : fail-closed platform-pin python-floor release-validation
# @source runner/mcp_artifact.py::load_release_ledger
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param(
            "python_requirement",
            ">=3.13,<3.14",
            "Python requirement",
            id="python-requirement",
        ),
        pytest.param("python", "3.13", "unsupported python", id="platform-python"),
        pytest.param(
            "architecture",
            "aarch64",
            "unsupported architecture",
            id="platform-architecture",
        ),
    ],
)
def test_artifact_builder_rejects_unproven_python_and_platform_metadata(
    tmp_path,
    field,
    value,
    expected,
):
    ledger = _prepare_release(tmp_path)
    if field == "python_requirement":
        ledger["releases"][0][field] = value
    else:
        ledger["releases"][0]["platforms"][0][field] = value
    _write(
        tmp_path / mcp_artifact.MCP_LEDGER_RELATIVE,
        mcp_artifact._canonical_json(ledger),
    )

    with pytest.raises(mcp_artifact.McpArtifactError, match=expected):
        mcp_artifact.assemble_deployment_artifacts(tmp_path)


# @matrix mcp-package release : deploy-preflight deploy-surface retirement supported-wheel
# @source runner/mcp_artifact.py::check_deployment_artifacts
def test_artifact_builder_rejects_retired_wheel_on_supported_deploy_surface(tmp_path):
    ledger = _prepare_release(tmp_path)
    retired = ledger["releases"][0]
    retired["supported"] = False
    _write(
        tmp_path / "clients/lagniappe_mcp/pyproject.toml",
        _fixture_pyproject("0.2.0"),
    )
    _write(
        tmp_path / "clients/lagniappe_mcp/uv.lock",
        _fixture_lock("0.2.0"),
    )
    _write(
        tmp_path / "clients/lagniappe_mcp/src/lagniappe_mcp/__init__.py",
        "fixture_v2 = True\n",
    )
    current = _add_release(
        tmp_path,
        version="0.2.0",
        payload="fixture_v2 = True\n",
    )
    ledger["current"] = current["version"]
    ledger["releases"].append(current)
    _write(
        tmp_path / mcp_artifact.MCP_LEDGER_RELATIVE,
        mcp_artifact._canonical_json(ledger),
    )

    manifest = mcp_artifact.assemble_deployment_artifacts(tmp_path)
    assert [entry["version"] for entry in manifest["releases"]] == ["0.2.0"]
    retired_relative = mcp_artifact._artifact_relative_path(
        retired["version"],
        retired["sha256"],
    )
    retired_source = tmp_path / mcp_artifact.MCP_RELEASES_RELATIVE / retired_relative
    assert retired_source.is_file()
    _write(
        tmp_path / mcp_artifact.MCP_DEPLOY_RELATIVE / "releases" / retired_relative,
        retired_source.read_bytes(),
    )

    with pytest.raises(mcp_artifact.McpArtifactError, match="unauthorized file"):
        mcp_artifact.check_deployment_artifacts(tmp_path, require_git=False)


_VALID_TEST_API_KEY = f"lgn_{'A' * 24}.{'B' * 43}"


# @matrix mcp-package release : credential-audit instance-neutrality path-safety public-artifact
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            f'LEAKED_API_KEY = "{_VALID_TEST_API_KEY}"\n',
            "credential or test secret",
            id="api-key",
        ),
        pytest.param(
            'TEST_SECRET = "fixture-super-secret-value"\n',
            "credential or test secret",
            id="test-secret",
        ),
        pytest.param(
            'BUILD_ROOT = "/home/build-agent/private/lagniappe"\n',
            "machine-local path",
            id="local-path",
        ),
        pytest.param(
            'SERVICE_URL = "https://candidate-dot-prod.appspot.com/api/v1"\n',
            "application instance hostname",
            id="instance-hostname",
        ),
    ],
)
def test_public_artifact_audit_rejects_wheel_leaks(tmp_path, payload, expected):
    _prepare_source(tmp_path, payload=payload)
    project = mcp_artifact._load_project(tmp_path)
    wheel = (
        tmp_path
        / mcp_artifact.MCP_PROJECT_RELATIVE
        / mcp_artifact._wheel_filename(project.version)
    )
    _write(wheel, _wheel_bytes(project.version, payload=payload))

    with pytest.raises(mcp_artifact.McpArtifactError, match=expected):
        mcp_artifact._inspect_wheel(wheel, project, tmp_path)


# @matrix mcp-package release : credential-audit path-safety public-artifact
def test_public_artifact_audit_rejects_ledger_and_manifest_leaks(
    tmp_path,
    monkeypatch,
):
    mcp_artifact._audit_public_content(
        [
            (
                "safe public documentation",
                b'fields = {"api_key": key, "token": token}\n'
                b'header = "Bearer {api_key}"\n'
                b'example = "--api-key SECRET"\n',
            )
        ],
        repo_root=tmp_path,
        allowed_urls=("https://example.test/source",),
    )
    context_secret = "opaque-build-context-credential"
    monkeypatch.setenv("LAGNIAPPE_API_KEY", context_secret)
    with pytest.raises(mcp_artifact.McpArtifactError, match="credential data"):
        mcp_artifact._audit_public_content(
            [("environment-bound public content", context_secret.encode())],
            repo_root=tmp_path,
            allowed_urls=("https://example.test/source",),
        )
    ledger = _prepare_release(tmp_path)
    ledger["source_url"] = f"https://example.test/source/{_VALID_TEST_API_KEY}"
    _write(
        tmp_path / mcp_artifact.MCP_LEDGER_RELATIVE,
        mcp_artifact._canonical_json(ledger),
    )
    with pytest.raises(
        mcp_artifact.McpArtifactError, match="credential or test secret"
    ):
        mcp_artifact.load_release_ledger(tmp_path)

    ledger["source_url"] = "https://example.test/source"
    _write(
        tmp_path / mcp_artifact.MCP_LEDGER_RELATIVE,
        mcp_artifact._canonical_json(ledger),
    )
    monkeypatch.setattr(
        mcp_artifact,
        "_application_metadata",
        lambda _repo_root: {
            "version": "1.2.3",
            "build_id": "b1234567",
            "frontend_build_sha256": "a" * 64,
            "private_build_root": "/home/build-agent/private/lagniappe",
        },
    )
    with pytest.raises(mcp_artifact.McpArtifactError, match="machine-local path"):
        mcp_artifact._manifest(tmp_path, ledger)


# @matrix frontend-build mcp-package : artifact-freshness git-boundary
def test_artifact_builder_rejects_stale_frontend_or_uncommitted_release_input(tmp_path):
    _prepare_release(tmp_path)
    mcp_artifact.assemble_deployment_artifacts(tmp_path)

    with pytest.raises(mcp_artifact.McpArtifactError, match="ordinary Git"):
        mcp_artifact.check_deployment_artifacts(tmp_path, git_cli=GIT_CLI)

    _write(
        tmp_path / "lagniappe/web/static/build.json",
        json.dumps({"mode": "production", "version": "1.2.3", "build_id": "b7654321"}),
    )
    with pytest.raises(mcp_artifact.McpArtifactError, match="stale"):
        mcp_artifact.check_deployment_artifacts(tmp_path, require_git=False)


# @matrix mcp-package release : deploy-preflight git-boundary
def test_artifact_git_boundary_rejects_staged_uncommitted_inputs(tmp_path):
    ledger = _prepare_release(tmp_path)
    mcp_artifact.assemble_deployment_artifacts(tmp_path)
    commands = (
        ("init", "-b", "main"),
        ("config", "user.name", "MCP Artifact Test"),
        ("config", "user.email", "mcp-artifact@example.test"),
        ("add", "."),
        ("commit", "-m", "fixture"),
    )
    for command in commands:
        subprocess.run(
            ["git", "-C", str(tmp_path), *command],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    assert (
        mcp_artifact._git_release_input_issues(
            tmp_path,
            ledger,
            git_cli=GIT_CLI,
        )
        == []
    )
    readme = tmp_path / mcp_artifact.MCP_PROJECT_RELATIVE / "README.md"
    _write(readme, "staged but not committed\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", str(readme.relative_to(tmp_path))],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert any(
        "staged but uncommitted" in issue
        for issue in mcp_artifact._git_release_input_issues(
            tmp_path,
            ledger,
            git_cli=GIT_CLI,
        )
    )


# @matrix mcp-package : build check cli-routing
def test_mcp_artifact_cli_checks_without_gcloud(monkeypatch, capsys):
    manifest = {"current": {"version": "0.1.0"}}
    monkeypatch.setattr(
        mcp_artifact,
        "build_and_promote_release",
        lambda repo_root: {"current": "0.1.0"},
    )
    monkeypatch.setattr(
        mcp_artifact,
        "check_deployment_artifacts",
        lambda repo_root, **_kwargs: manifest,
    )

    assert mcp_artifact.run_mcp_artifact_command(["build"], repo_root=Path(".")) == 0
    assert mcp_artifact.run_mcp_artifact_command(["check"], repo_root=Path(".")) == 0
    output = capsys.readouterr().out
    assert "Built MCP adapter 0.1.0" in output
    assert "adapter 0.1.0" in output
