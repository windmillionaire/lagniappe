"""Package, verify and install Lagniappe's production frontend using only Python."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from runner.context import GIT_CLI, REPOSITORY_ROOT
from runner.frontend_build import (
    BUILD_METADATA_PATH,
    PUBLICATION_CONTRACT_PATH,
    SHA256_RE,
    FilesystemFrontendBuildReader,
    FrontendReader,
    frontend_source_sha256,
    inspect_frontend_build,
)

PIN_PATH = "config/frontend-release.json"
STATIC = "lagniappe/web/static/"
CACHE = "reports/frontend-bundles"
MAX_SIZE = 64 * 1024 * 1024
FONT = re.compile(r"lagniappe/web/static/fonts/[a-z0-9-]+\.[0-9a-f]{12}\.woff2")
REPOSITORY = re.compile(r"[\w.-]+/[\w.-]+")


class BundleError(RuntimeError):
    """A bundle could not be acquired or verified."""


def uses_bundle(reader: FrontendReader) -> bool:
    """Historical revisions used tracked build outputs."""
    try:
        return (
            json.loads(reader.read_bytes(PUBLICATION_CONTRACT_PATH)).get("distribution")
            == "release-zip"
        )
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class BundleTarget:
    source: str
    version: str
    digest: str | None

    @property
    def name(self) -> str:
        return f"lagniappe-frontend-{self.source}.zip"

    @property
    def tag(self) -> str:
        return f"frontend-{self.source}"

    @property
    def build_id(self) -> str:
        return f"b{self.source[:7]}"

    @classmethod
    def read(cls, reader: FrontendReader, *, require_pin: bool = False) -> BundleTarget:
        source = frontend_source_sha256(reader)
        version = json.loads(reader.read_bytes("package.json"))["version"]
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise BundleError(
                "Expected a stable package version for the frontend bundle."
            )
        try:
            pin = json.loads(reader.read_bytes(PIN_PATH))
        except FileNotFoundError:
            pin = {}
        digest = None
        if pin.get("source_sha256") == source:
            digest = pin.get("archive_sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise BundleError(f"Invalid frontend archive digest in {PIN_PATH}.")
        if require_pin and not digest:
            raise BundleError(
                f"Freeze the current production bundle with 'python -m runner.frontend_bundle pin' and stage {PIN_PATH}."
            )
        return cls(source, version, digest)


def _managed(path: str, contract: dict) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or any(
        p in {"", ".", ".."} for p in path.split("/")
    ):
        return False
    if (
        path == BUILD_METADATA_PATH
        or path in contract["required_artifacts"]
        or FONT.fullmatch(path)
    ):
        return True
    return path.endswith((".js", ".wasm")) and any(
        path.startswith(root + "/") for root in contract["exclusive_artifact_roots"]
    )


class BundleFiles(dict[str, bytes]):
    """Read a validated ZIP inventory with the existing build verifier."""

    def read_bytes(self, path: str) -> bytes:
        try:
            return self[path]
        except KeyError as error:
            raise FileNotFoundError(path) from error

    def list_files(self, roots: Sequence[str]) -> list[str]:
        return sorted(
            path for path in self if any(path.startswith(root + "/") for root in roots)
        )


def _verify(files: BundleFiles, reader: FrontendReader, target: BundleTarget) -> None:
    build, issues = inspect_frontend_build(
        files,
        source_reader=reader,
        expected_mode="production",
        expected_version=target.version,
    )
    if issues or not build:
        raise BundleError("Invalid production bundle: " + ", ".join(issues))
    paths = {a["path"] for a in build.metadata["artifacts"]} | {BUILD_METADATA_PATH}
    if set(files) != paths or build.metadata["build_id"] != target.build_id:
        raise BundleError(
            "Frontend ZIP inventory or build ID differs from the requested source."
        )
    for path in paths:
        if not path.startswith(STATIC) and files[path] != reader.read_bytes(path):
            raise BundleError(f"Bundled style binding differs from source: {path}")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
    try:
        tmp.write_bytes(content)
        tmp.chmod(0o644)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def pack(root: Path, output: Path) -> tuple[BundleTarget, Path]:
    """Write a reproducible ZIP from a completed production build."""
    reader = FilesystemFrontendBuildReader(root)
    target = BundleTarget.read(reader)
    build, issues = inspect_frontend_build(
        reader, expected_mode="production", expected_version=target.version
    )
    if issues or not build:
        raise BundleError("Cannot package this production build: " + ", ".join(issues))
    contract = json.loads(reader.read_bytes(PUBLICATION_CONTRACT_PATH))
    paths = sorted(
        [BUILD_METADATA_PATH, *(a["path"] for a in build.metadata["artifacts"])]
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for path in paths:
            if not _managed(path, contract):
                raise BundleError(f"Unexpected frontend output: {path}")
            info = zipfile.ZipInfo(path)  # Fixed ZIP epoch and portable file mode.
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, reader.read_bytes(path))
    data = out.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if target.digest and digest != target.digest:
        raise BundleError(
            "Production ZIP differs from the committed SHA-256 for these inputs."
        )
    target = BundleTarget(target.source, target.version, digest)
    unpack(data, reader, target)
    path = output / target.name
    _atomic_write(path, data)
    return target, path


def unpack(data: bytes, reader: FrontendReader, target: BundleTarget) -> BundleFiles:
    """Check the external digest, member types and complete manifest before writing."""
    if len(data) > MAX_SIZE or hashlib.sha256(data).hexdigest() != target.digest:
        raise BundleError(
            "Frontend archive SHA-256 or size differs from the expected release asset."
        )
    contract = json.loads(reader.read_bytes(PUBLICATION_CONTRACT_PATH))
    files = BundleFiles()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            size = 0
            for entry in archive.infolist():
                path = entry.filename
                size += entry.file_size
                if (
                    len(files) >= 2048
                    or size > MAX_SIZE
                    or entry.compress_type != zipfile.ZIP_STORED
                    or not stat.S_ISREG(entry.external_attr >> 16)
                    or path in files
                    or not _managed(path, contract)
                ):
                    raise BundleError(f"Unexpected frontend ZIP member: {path}")
                files[path] = archive.read(entry)
    except (zipfile.BadZipFile, OSError) as error:
        raise BundleError(f"Unreadable frontend ZIP: {error}") from error
    _verify(files, reader, target)
    return files


def repository_slug(root: Path) -> str:
    """Resolve public releases from this checkout's GitHub origin (including forks)."""
    url = (
        subprocess.check_output(
            [GIT_CLI or "git", "config", "--get", "remote.origin.url"], cwd=root, text=True
        )
        .strip()
        .removesuffix(".git")
    )
    match = re.fullmatch(
        r"(?:https://github\.com/|(?:ssh://)?git@github\.com[:/])([\w.-]+/[\w.-]+)", url
    )
    if not match:
        raise BundleError(
            "Expected a GitHub origin. Use --repo OWNER/REPO for a mirror."
        )
    return match[1]


def _read_url(url: str, limit: int) -> bytes:
    with urlopen(
        Request(url, headers={"User-Agent": "Lagniappe-frontend-installer"}), timeout=60
    ) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise BundleError("GitHub frontend release response exceeded the size limit.")
    return data


def _release_digest(repo: str, tag: str, name: str) -> str | None:
    try:
        record = json.loads(
            _read_url(
                f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
                2 * 1024 * 1024,
            )
        )
    except HTTPError as error:
        error.close()
        if error.code == 404:
            return None
        raise
    if record.get("tag_name") != tag or record.get("draft"):
        raise BundleError("GitHub returned an unexpected frontend release.")
    for asset in record["assets"]:
        if asset.get("name") == name:
            digest = (asset.get("digest") or "").removeprefix("sha256:")
            if not SHA256_RE.fullmatch(digest) or not 0 < asset["size"] <= MAX_SIZE:
                raise BundleError(
                    "GitHub frontend asset has an invalid SHA-256 or size."
                )
            return digest
    return None


def acquire(
    reader: FrontendReader,
    target: BundleTarget,
    cache: Path,
    *,
    repo: str | None = None,
    origin: Path = REPOSITORY_ROOT,
) -> tuple[BundleTarget, Path, BundleFiles]:
    """Get the exact verified release bytes and cache them for offline reuse."""
    path = cache / target.name
    if target.digest and path.exists():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == target.digest:
            return target, path, unpack(data, reader, target)
    repo = repo or repository_slug(origin)
    if not REPOSITORY.fullmatch(repo):
        raise BundleError("Expected a GitHub OWNER/REPO.")
    tags = [f"v{target.version}", target.tag] if target.digest else [target.tag]
    try:
        for tag in tags:
            digest = _release_digest(repo, tag, target.name)
            if not digest:
                continue
            if target.digest and target.digest != digest:
                raise BundleError(
                    f"GitHub asset {tag}/{target.name} differs from {PIN_PATH}."
                )
            verified = BundleTarget(target.source, target.version, digest)
            if path.exists():
                cached = path.read_bytes()
                if hashlib.sha256(cached).hexdigest() == digest:
                    return verified, path, unpack(cached, reader, verified)
            url = f"https://github.com/{repo}/releases/download/{tag}/{target.name}"
            data = _read_url(url, MAX_SIZE)
            files = unpack(data, reader, verified)
            _atomic_write(path, data)
            return verified, path, files
    except URLError as error:
        raise BundleError(
            f"Could not retrieve frontend bundle from {repo}: {error}"
        ) from error
    raise BundleError(
        f"Frontend bundle for {target.source} is not published in {repo} yet. Retry after the Frontend bundle workflow finishes."
    )


def _destination(root: Path, relative: str) -> Path:
    path = root / relative
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise BundleError(f"Unexpected frontend installation path: {relative}")
    return path


@contextmanager
def _installation_lock(root: Path) -> Iterator[None]:
    # OS locks are released automatically if setup is interrupted.
    path = root / CACHE / "install.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def install_files(root: Path, files: BundleFiles) -> None:
    """Serialize promotion so concurrent installs cannot mix generations."""
    with _installation_lock(root):
        _install_static_files(root, files)


def _install_static_files(root: Path, files: BundleFiles) -> None:
    """Promote verified static files, remove obsolete files and publish build.json last."""
    root = root.resolve()
    reader = FilesystemFrontendBuildReader(root)
    contract = json.loads(reader.read_bytes(PUBLICATION_CONTRACT_PATH))
    paths = {path for path in files if path.startswith(STATIC)}
    generated = set(reader.list_files(contract["exclusive_artifact_roots"]))
    generated.update(
        path for path in reader.list_files([STATIC + "fonts"]) if FONT.fullmatch(path)
    )
    obsolete = generated - paths
    destinations = {p: _destination(root, p) for p in paths | obsolete}
    changed = sorted(
        p
        for p in paths
        if not destinations[p].is_file() or destinations[p].read_bytes() != files[p]
    )
    if not changed and not obsolete:
        return
    marker = destinations[BUILD_METADATA_PATH]
    marker.unlink(missing_ok=True)
    for path in changed:
        if path != BUILD_METADATA_PATH:
            _atomic_write(destinations[path], files[path])
    for path in obsolete:
        destinations[path].unlink(missing_ok=True)
    _atomic_write(marker, files[BUILD_METADATA_PATH])


def sync(
    root: Path,
    *,
    cache: Path | None = None,
    repo: str | None = None,
    require_pin: bool = False,
    origin: Path | None = None,
) -> None:
    reader = FilesystemFrontendBuildReader(root)
    if uses_bundle(reader):
        target = BundleTarget.read(reader, require_pin=require_pin)
        _, _, files = acquire(
            reader, target, cache or root / CACHE, repo=repo, origin=origin or root
        )
        install_files(root, files)


def release_bundle(reader: FrontendReader, root: Path, *, repo: str | None = None):
    """Verify the archive specified by the release index or exact candidate commit."""
    target = BundleTarget.read(reader, require_pin=True)
    return acquire(reader, target, root / CACHE, origin=root, repo=repo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pack", "pin", "sync"))
    parser.add_argument("--repo", help="GitHub OWNER/REPO for release assets")
    parser.add_argument("--cache", type=Path, default=REPOSITORY_ROOT / CACHE)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Freeze a local production ZIP during first publication",
    )
    args = parser.parse_args()
    if args.archive and args.command != "pin":
        parser.error("--archive is only available with pin")
    root = REPOSITORY_ROOT
    try:
        if args.command == "pack":
            _, path = pack(root, args.cache)
            print(path)
        elif args.command == "pin":
            reader = FilesystemFrontendBuildReader(root)
            target = BundleTarget.read(reader)
            # Freeze the published bytes, including for an unreleased version.
            if args.archive:
                data = args.archive.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                if target.digest and target.digest != digest:
                    raise BundleError(
                        "The local archive differs from the existing release pin."
                    )
                verified = BundleTarget(target.source, target.version, digest)
                unpack(data, reader, verified)
                _atomic_write(args.cache / target.name, data)
            else:
                verified, _, _ = acquire(
                    reader, target, args.cache, repo=args.repo, origin=root
                )
            _atomic_write(
                root / PIN_PATH,
                (
                    json.dumps(
                        {
                            "source_sha256": verified.source,
                            "archive_sha256": verified.digest,
                        },
                        indent=2,
                    )
                    + "\n"
                ).encode(),
            )
            print(f"Froze {verified.build_id} in {PIN_PATH}")
        else:
            sync(root, cache=args.cache, repo=args.repo)
            print("Production frontend installed and verified.")
    except (BundleError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
