"""Tooling contracts for coherent frontend build completion metadata."""

import hashlib
import io
import json
import stat
import zipfile
from dataclasses import replace
from urllib.error import HTTPError
from pathlib import Path

import pytest
from werkzeug.routing import Map, Rule

from runner import frontend_bundle as bundle
from runner.browser_endpoints import render_endpoints
from runner.frontend_build import (
    FilesystemFrontendBuildReader,
    inspect_frontend_build,
    verify_frontend_build,
)


pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_browser_endpoints_bind_arguments_by_name_and_keep_client_query():
    routes = Map([Rule("/assets/<field>/<key>", endpoint="assets.field")])
    template = '`{{ path("assets.field", key="settings.key", field="fieldId") }}?page=${page}`'

    assert render_endpoints(routes, template) == '`/assets/${fieldId}/${settings.key}?page=${page}`'


def test_browser_endpoints_detect_removed_routes_and_shared_path_drift():
    routes = Map([
        Rule("/notices", endpoint="read"),
        Rule("/notices/clear", endpoint="clear"),
        Rule("/items/<key>", endpoint="detail"),
    ])
    with pytest.raises(ValueError, match="no longer share a URL"):
        render_endpoints(routes, '{{ path("read", "clear") }}')
    with pytest.raises(ValueError, match="No registered Flask endpoint"):
        render_endpoints(routes, '{{ path("removed") }}')
    with pytest.raises(ValueError, match="expected one route with parameters"):
        render_endpoints(routes, '{{ path("detail", old_key="key") }}')


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _write_completed_build(root, *, mode="production", version="1.2.3", packaged=False):
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
    if packaged:
        contract["distribution"] = "release-zip"
    sources = {
        "build/publication.json": f"{json.dumps(contract, sort_keys=True)}\n",
        "package.json": f'{{"version": "{version}"}}\n',
        "src/script/main.ts": "export const current = true;\n",
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
    build_id = f"b{digest.hexdigest()[:7]}" if packaged else "b1234567"
    worker = "lagniappe/web/static/sw.js"
    artifacts[worker] = f'const BUILD_ID = "{build_id}";\n'
    (root / worker).write_text(artifacts[worker], encoding="utf-8")
    metadata = {
        "schema": 1,
        "build_id": build_id,
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


def test_verify_frontend_build_reports_actionable_failure(tmp_path):
    with pytest.raises(RuntimeError, match="Rerun the appropriate npm build command"):
        verify_frontend_build(
            app_dir=tmp_path,
            expected_mode="production",
            expected_version="1.2.3",
        )


def test_authored_frontend_scripts_and_tsconfig_stay_strict_typescript():
    script_root = REPO_ROOT / "src" / "script"
    allowed_generated_js = {
        "src/script/generated/icons.mjs",
        "src/script/generated/styles.mjs",
    }
    js_files = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in script_root.rglob("*")
        if path.is_file() and path.suffix in {".js", ".mjs", ".cjs"}
    )
    assert set(js_files) <= allowed_generated_js, (
        "Authored frontend modules under src/script/ must be TypeScript (.ts/.mts); "
        f"found unexpected JS files: {sorted(set(js_files) - allowed_generated_js)}"
    )

    tsconfig = json.loads((REPO_ROOT / "tsconfig.json").read_text(encoding="utf-8"))
    compiler_options = tsconfig["compilerOptions"]
    assert compiler_options["strict"] is True
    assert compiler_options["noEmit"] is True
    assert compiler_options["erasableSyntaxOnly"] is True
    assert compiler_options["allowImportingTsExtensions"] is True
    assert compiler_options["allowJs"] is True
    assert compiler_options["checkJs"] is False
    assert tsconfig["include"] == ["src/script/**/*.ts", "src/script/**/*.mts"]
    assert tsconfig["exclude"] == ["testing/"]

    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["typecheck"] == "tsc --noEmit"


def test_package_json_matches_canonical_config_serialization():
    package_path = REPO_ROOT / "package.json"
    raw = package_path.read_text(encoding="utf-8")
    canonical = f"{json.dumps(json.loads(raw), indent=2, sort_keys=True)}\n"
    assert raw == canonical, (
        "package.json must match File.PACKAGE_JSON's sorted JSON serialization "
        "so setup/upgrade saves do not rewrite it and invalidate build.json."
    )


def test_frontend_archive_branch_install_then_pinned_offline_repair(tmp_path, monkeypatch):
    metadata = _write_completed_build(tmp_path, packaged=True)
    reader = FilesystemFrontendBuildReader(tmp_path)
    target, archive = bundle.pack(tmp_path, tmp_path / "build-output")
    data = archive.read_bytes()
    assert bundle.pack(tmp_path, tmp_path / "second-build")[1].read_bytes() == data
    for item in metadata["artifacts"]:
        (tmp_path / item["path"]).unlink()
    marker = tmp_path / bundle.BUILD_METADATA_PATH
    marker.unlink()
    manifest = marker.with_name("manifest.json")
    manifest.write_text('{"name":"My site"}')
    old_chunk = marker.parent / "chunks/obsolete.js"
    old_chunk.touch()
    requests = []

    def github(url, limit):
        requests.append(url)
        if "/releases/download/" in url:
            return data
        tag = url.rsplit("/", 1)[1]
        return json.dumps({"tag_name": tag, "assets": [
            {"name": target.name, "size": len(data), "digest": f"sha256:{target.digest}"}
        ]}).encode()

    monkeypatch.setattr(bundle, "_read_url", github)
    bundle.sync(tmp_path, repo="owner/repo")
    assert len(requests) == 2 and all(target.tag in url for url in requests)
    assert json.loads(marker.read_bytes()) == metadata
    assert not old_chunk.exists()
    assert manifest.read_text() == '{"name":"My site"}'
    with pytest.raises(bundle.BundleError, match="Freeze"):
        bundle.BundleTarget.read(reader, require_pin=True)

    (tmp_path / bundle.PIN_PATH).write_text(json.dumps({
        "source_sha256": target.source, "archive_sha256": target.digest,
    }))
    (marker.parent / "script.js").write_text("broken")
    bundle.sync(tmp_path)
    assert len(requests) == 2
    assert bundle.release_bundle(reader, tmp_path)[0] == target
    assert verify_frontend_build(app_dir=tmp_path).metadata == metadata

    # An official release is preferred once it exists. A missing official tag
    # before release is only permission to fetch the same pinned candidate.
    (tmp_path / bundle.CACHE / target.name).unlink()
    requests.clear()

    def prerelease_only(url, limit):
        if url.endswith("/v1.2.3"):
            requests.append(url)
            raise HTTPError(url, 404, "not released", {}, None)
        return github(url, limit)

    monkeypatch.setattr(bundle, "_read_url", prerelease_only)
    bundle.sync(tmp_path, repo="owner/repo", require_pin=True)
    assert requests[0].endswith("/v1.2.3") and target.tag in requests[1]
    (tmp_path / "src/script/main.ts").write_text("new inputs")
    with pytest.raises(bundle.BundleError, match="Freeze"):
        bundle.release_bundle(reader, tmp_path)


@pytest.mark.parametrize("member", ["../escape", "config/constants.py", "extra.js", "link"])
def test_frontend_archive_rejects_wrong_or_unlisted_members(tmp_path, member):
    _write_completed_build(tmp_path, packaged=True)
    target, archive = bundle.pack(tmp_path, tmp_path / "out")
    data = io.BytesIO(archive.read_bytes())
    with zipfile.ZipFile(data, "a") as modified:
        name = "lagniappe/web/static/chunks/link.js" if member == "link" else member
        info = zipfile.ZipInfo(name)
        info.external_attr = ((stat.S_IFLNK if member == "link" else stat.S_IFREG) | 0o644) << 16
        modified.writestr(info, b"untrusted")
    reader = FilesystemFrontendBuildReader(tmp_path)
    with pytest.raises(bundle.BundleError, match="SHA-256"):
        bundle.unpack(data.getvalue(), reader, target)
    with pytest.raises(bundle.BundleError, match="Unexpected frontend ZIP member"):
        bundle.unpack(data.getvalue(), reader, replace(target, digest=_sha256(data.getvalue())))


def test_missing_or_corrupt_branch_bundle_preserves_installed_generation(tmp_path, monkeypatch):
    original = _write_completed_build(tmp_path, packaged=True)
    target, archive = bundle.pack(tmp_path, tmp_path / "out")
    marker = tmp_path / bundle.BUILD_METADATA_PATH
    monkeypatch.setattr(bundle, "_release_digest", lambda *_: None)
    with pytest.raises(bundle.BundleError, match="not published"):
        bundle.sync(tmp_path, repo="owner/repo")
    monkeypatch.setattr(bundle, "_release_digest", lambda *_: target.digest)
    monkeypatch.setattr(bundle, "_read_url", lambda *_: archive.read_bytes()[:-8])
    with pytest.raises(bundle.BundleError, match="SHA-256"):
        bundle.sync(tmp_path, repo="owner/repo")
    assert json.loads(marker.read_bytes()) == original
    assert not (tmp_path / bundle.CACHE / target.name).exists()
