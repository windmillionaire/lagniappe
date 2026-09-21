"""Repository contract for direct runtime outbound-HTTP ownership."""

from pathlib import Path

import pytest

from testing.utility.runtime_outbound_http import (
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
    # Provider retry classification owns the SDK transport exception types.
    "lagniappe/core/tools/ai/provider_policy.py": frozenset({"httpx"}),
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
@pytest.mark.parametrize(
    "code, expected",
    [
        pytest.param(
            "import requests.sessions\nfrom httpx import Client\nfrom urllib import request",
            {"requests", "httpx", "urllib.request"},
            id="all-boundaries",
        ),
        pytest.param("import requests as transport", {"requests"}, id="alias"),
        pytest.param(
            "from requests.sessions import Session", {"requests"}, id="submodule"
        ),
        pytest.param(
            "import urllib.request as transport", {"urllib.request"}, id="urllib-alias"
        ),
        pytest.param(
            "from urllib.request import urlopen", {"urllib.request"}, id="urllib-from"
        ),
        pytest.param(
            "# import requests\ntext = 'from httpx import Client'", set(), id="prose"
        ),
        pytest.param(
            "import requests_cache\nimport httpx_helpers\nimport urllib.parse",
            set(),
            id="similar-names",
        ),
    ],
)
def test_direct_http_inventory_recognizes_supported_import_forms(
    tmp_path, code, expected
):
    source = tmp_path / "runtime_http.py"
    source.write_text(code, encoding="utf-8")

    assert direct_http_imports(source) == expected
