"""Repository contract for direct runtime outbound-HTTP ownership."""

from pathlib import Path

import pytest

from testing.utility.runtime_outbound_http import (
    DIRECT_HTTP_MODULES,
    direct_http_imports,
    runtime_direct_http_imports,
)


pytestmark = pytest.mark.tooling

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_ROOT = _REPOSITORY_ROOT / "lagniappe"
_AUDITED_DIRECT_IMPORTS = {
    "lagniappe/core/tools/http/client.py": frozenset({"requests"}),
    "lagniappe/core/tools/services/identity_platform.py": frozenset({"requests"}),
    "lagniappe/core/tools/email/ai.py": frozenset({"requests"}),
    "lagniappe/core/tools/ai/core.py": frozenset({"httpx"}),
}
# @matrix outbound-http tooling : direct-call-guard provider-ownership source-inventory
def test_runtime_direct_http_imports_match_shared_boundary_and_audited_providers():
    """New direct runtime HTTP dependencies require an explicit owner decision."""
    found = runtime_direct_http_imports(
        _RUNTIME_ROOT,
        repository_root=_REPOSITORY_ROOT,
    )
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

    assert direct_http_imports(source) == DIRECT_HTTP_MODULES
