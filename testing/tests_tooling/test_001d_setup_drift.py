"""Read-only provider drift probes for setup APIs."""

import json

import pytest

pytestmark = pytest.mark.tooling


def _fetch_json(url):
    import requests

    try:
        response = requests.get(url, timeout=10)
    except (requests.ConnectionError, requests.Timeout) as exc:
        pytest.skip(f"Network unavailable for setup drift probe: {exc}")
    response.raise_for_status()
    return response.json()


# @pair setup:api-drift
@pytest.mark.setup_drift
def test_app_engine_discovery_has_domain_mapping_create():
    data = _fetch_json(
        "https://appengine.googleapis.com/$discovery/rest?version=v1"
    )
    text = json.dumps(data)

    assert "appengine.apps.domainMappings.create" in text
    assert "domainMappings" in text


# @pair setup:api-drift
@pytest.mark.setup_drift
def test_vertex_discovery_has_cache_config_disable_cache():
    data = _fetch_json(
        "https://aiplatform.googleapis.com/$discovery/rest?version=v1beta1"
    )
    text = json.dumps(data)

    assert "CacheConfig" in text
    assert "disableCache" in text
