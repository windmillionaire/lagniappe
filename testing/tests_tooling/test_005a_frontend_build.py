"""Tooling contracts for coherent frontend build completion metadata."""

import hashlib
import json

import pytest

from runner.frontend_build import (
    FilesystemFrontendBuildReader,
    inspect_frontend_build,
    verify_frontend_build,
)


pytestmark = pytest.mark.tooling


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _write_completed_build(root, *, mode="production", version="1.2.3"):
    contract = {
        "schema": 1,
        "source_roots": ["build", "src/script"],
        "source_files": ["package.json"],
        "exclusive_artifact_roots": ["lagniappe/web/static/chunks"],
        "required_artifacts": [
            "lagniappe/web/static/script.js",
            "lagniappe/web/static/sw.js",
        ],
        "required_artifact_prefixes": [
            "lagniappe/web/static/chunks/",
            "lagniappe/web/static/chunks/views/",
        ],
    }
    sources = {
        "build/publication.json": f"{json.dumps(contract, sort_keys=True)}\n",
        "package.json": f'{{"version": "{version}"}}\n',
        "src/script/main.mjs": "export const current = true;\n",
    }
    artifacts = {
        "lagniappe/web/static/chunks/shared.js": "export const shared = true;\n",
        "lagniappe/web/static/chunks/views/home.js": ("export const home = true;\n"),
        "lagniappe/web/static/script.js": "import './chunks/shared.js';\n",
        "lagniappe/web/static/sw.js": 'const BUILD_ID = "b1234567";\n',
    }
    for relative, content in {**sources, **artifacts}.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    constants = root / "config/constants.py"
    constants.parent.mkdir(parents=True, exist_ok=True)
    constants.write_text('BUILD_ID = "b1234567"\n', encoding="utf-8")

    digest = hashlib.sha256(b"frontend-source-v1\0")
    for relative in sorted(sources):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(sources[relative].encode())
        digest.update(b"\0")
    metadata = {
        "schema": 1,
        "build_id": "b1234567",
        "mode": mode,
        "version": version,
        "source": {"sha256": digest.hexdigest()},
        "artifacts": [
            {
                "path": relative,
                "sha256": _sha256(content.encode()),
                "size": len(content.encode()),
            }
            for relative, content in sorted(artifacts.items())
        ],
    }
    metadata_path = root / "lagniappe/web/static/build.json"
    metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n", encoding="utf-8")
    return metadata


# @features frontend-build
# @dimensions artifact-integrity source-integrity build-metadata
def test_frontend_build_validator_checks_recursive_artifacts_and_source_identity(
    tmp_path,
):
    _write_completed_build(tmp_path)
    reader = FilesystemFrontendBuildReader(tmp_path)

    validation, issues = inspect_frontend_build(
        reader,
        expected_mode="production",
        expected_version="1.2.3",
    )

    assert issues == []
    assert validation.metadata["build_id"] == "b1234567"
    assert len(validation.output_fingerprint) == 64

    nested_chunk = tmp_path / "lagniappe/web/static/chunks/views/home.js"
    nested_chunk.write_text("corrupt\n", encoding="utf-8")
    validation, issues = inspect_frontend_build(reader)
    assert validation is None
    assert any("artifact hash does not match" in issue for issue in issues)

    _write_completed_build(tmp_path)
    (tmp_path / "src/script/new.mjs").write_text("export const added = true;\n")
    validation, issues = inspect_frontend_build(reader)
    assert validation is None
    assert "Frontend build was created from different source inputs." in issues

    _write_completed_build(tmp_path)
    (tmp_path / "lagniappe/web/static/chunks/stale.js").write_text(
        "stale\n",
        encoding="utf-8",
    )
    validation, issues = inspect_frontend_build(reader)
    assert validation is None
    assert any("not in the artifact inventory" in issue for issue in issues)


# @features frontend-build
# @dimensions artifact-integrity path-safety build-identity
def test_frontend_build_validator_rejects_unsafe_and_incoherent_metadata(tmp_path):
    metadata = _write_completed_build(tmp_path, mode="development")
    metadata["artifacts"][0]["path"] = "../outside.js"
    (tmp_path / "lagniappe/web/static/build.json").write_text(
        f"{json.dumps(metadata)}\n",
        encoding="utf-8",
    )
    (tmp_path / "config/constants.py").write_text(
        'BUILD_ID = "bdifferent"\n',
        encoding="utf-8",
    )

    validation, issues = inspect_frontend_build(
        FilesystemFrontendBuildReader(tmp_path),
        expected_mode="production",
    )

    assert validation is None
    assert any("unsafe path" in issue for issue in issues)
    assert any("expected production" in issue for issue in issues)
    assert any("different build IDs" in issue for issue in issues)


# @features frontend-build deploy
# @dimensions validation safe-failure
def test_verify_frontend_build_reports_actionable_failure(tmp_path):
    with pytest.raises(RuntimeError, match="Rerun the appropriate npm build command"):
        verify_frontend_build(
            app_dir=tmp_path,
            expected_mode="production",
            expected_version="1.2.3",
        )
