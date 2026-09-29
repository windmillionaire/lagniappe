"""Non-secret deployed source identity for experiments; no experiment runner."""

import hashlib
import os
from pathlib import Path


# @testable true
# @tests tests_tooling/test_001l_setup_experiments.py::test_source_identity_includes_dirty_code_and_excludes_credentials
# @matrix experiments : source-identity
def source_identity(root):
    """Hash authored runtime/build inputs, including uncommitted new files."""
    root = Path(root)
    paths = set()
    for directory in ("lagniappe", "config", "src", "build", "mcp/src"):
        for current, directories, files in os.walk(root / directory):
            parent = Path(current)
            directories[:] = [
                name
                for name in directories
                if name != "__pycache__"
                and not (parent / name).is_symlink()
                and (parent / name).relative_to(root).as_posix()
                not in {"lagniappe/web/static", "config/files"}
            ]
            for name in files:
                path = parent / name
                if not path.is_symlink() and path.suffix not in {
                    ".pyc",
                    ".pem",
                    ".key",
                }:
                    paths.add(path.relative_to(root))
    for name in (
        "main.py",
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "rollup.config.mjs",
        "mcp/pyproject.toml",
        "mcp/uv.lock",
    ):
        if (root / name).is_file():
            paths.add(Path(name))
    digest = hashlib.sha256()
    for relative in sorted(paths):
        content = (root / relative).read_bytes()
        digest.update(relative.as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()
