"""Repository contract for direct runtime outbound-HTTP ownership."""

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.tooling

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_ROOT = _REPOSITORY_ROOT / "lagniappe"
_DIRECT_HTTP_MODULES = frozenset({"requests", "httpx", "urllib.request"})
_AUDITED_DIRECT_IMPORTS = {
    "lagniappe/core/tools/http/client.py": frozenset({"requests"}),
    "lagniappe/core/tools/services/identity_platform.py": frozenset({"requests"}),
    "lagniappe/core/tools/email/ai.py": frozenset({"requests"}),
    "lagniappe/core/tools/ai/core.py": frozenset({"httpx"}),
}


def _direct_http_imports(path):
    imports = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                for direct_module in _DIRECT_HTTP_MODULES:
                    if module == direct_module or module.startswith(
                        f"{direct_module}."
                    ):
                        imports.add(direct_module)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "requests" or module.startswith("requests."):
                imports.add("requests")
            elif module == "httpx" or module.startswith("httpx."):
                imports.add("httpx")
            elif module == "urllib.request":
                imports.add("urllib.request")
            elif module == "urllib" and any(
                alias.name == "request" for alias in node.names
            ):
                imports.add("urllib.request")
    return frozenset(imports)


# @matrix outbound-http tooling : direct-call-guard provider-ownership source-inventory
def test_runtime_direct_http_imports_match_shared_boundary_and_audited_providers():
    """New direct runtime HTTP dependencies require an explicit owner decision."""
    found = {}
    for path in sorted(_RUNTIME_ROOT.rglob("*.py")):
        imports = _direct_http_imports(path)
        if imports:
            found[path.relative_to(_REPOSITORY_ROOT).as_posix()] = imports

    assert found == _AUDITED_DIRECT_IMPORTS


# @matrix outbound-http tooling : import-syntax source-inventory
def test_direct_http_inventory_recognizes_supported_import_forms(tmp_path):
    source = tmp_path / "runtime_http.py"
    source.write_text(
        "\n".join(
            [
                "import requests.sessions",
                "from httpx import Client",
                "from urllib import request",
            ]
        ),
        encoding="utf-8",
    )

    assert _direct_http_imports(source) == _DIRECT_HTTP_MODULES
