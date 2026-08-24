"""Google Places helpers, Location field, and free-text fallback.

Field/link/select/radio submissions are in ``test_003b_submission_links_and_select.py``.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.properties.form_links import Location
from lagniappe.core.tools.services import places as loc


class _FakeCredentials:
    def __init__(self, tokens):
        self.token = None
        self.tokens = iter(tokens)
        self.before_requests = []
        self.expiry = None

    def before_request(self, request, method, url, headers):
        self.before_requests.append((request, method, url, headers))
        self.token = next(self.tokens)


class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


def _location_field(existing=None):
    submission = {"where": existing} if existing else {}
    return Location(
        {"id": "where", "type": "location", "title": "Where"},
        entity=SimpleNamespace(submission=submission),
    )


# @features location
# @dimensions session-bias validation coordinates
@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-json",
        [],
        {},
        {"latitude": True, "longitude": 1},
        {"latitude": "1", "longitude": 1},
        {"latitude": float("nan"), "longitude": 1},
        {"latitude": 91, "longitude": 1},
        {"latitude": 1, "longitude": -181},
    ],
)
def test_normalize_location_coordinates_rejects_malformed_values(value):
    assert loc.normalize_location_coordinates(value) is None

    assert loc.normalize_location_coordinates(
        json.dumps({"latitude": 29, "longitude": -90, "ignored": "value"})
    ) == {"latitude": 29.0, "longitude": -90.0}


# @features location
# @dimensions suite-stripping
def test_simplify_address_for_search_comma_suite():
    """Comma-separated suite clause should be stripped for retry."""
    out = loc.simplify_address_for_search("123 Main St, Suite 400, City, ST")
    assert out == "123 Main St"


# @features location
# @dimensions suite-stripping
def test_simplify_address_for_search_trailing_suite():
    out = loc.simplify_address_for_search("123 Main St Suite 4")
    assert out == "123 Main St"


# @features location
# @dimensions suite-stripping
def test_simplify_address_for_search_no_change():
    assert loc.simplify_address_for_search("123 Main St") is None


# @features location
# @dimensions retry suite-stripping
def test_resolve_location_query_retries_after_simplify():
    """Second search uses simplified query when first returns empty."""
    with patch.object(
        loc, "search_places", side_effect=[[], [{"id": "p1", "name": "Hit"}]]
    ):
        result = loc.resolve_location_query("123 Main St Suite 4")
    assert result == {"id": "p1", "name": "Hit"}


# @features location
# @dimensions first-hit
def test_resolve_location_query_first_hit_wins():
    with patch.object(
        loc,
        "search_places",
        return_value=[{"id": "p1", "name": "First"}],
    ):
        result = loc.resolve_location_query("Some Cafe")
    assert result == {"id": "p1", "name": "First"}


# @features location
# @dimensions api-cache oauth
@pytest.mark.unit
def test_get_places_access_token_reuses_cached_token_until_refresh_window(monkeypatch):
    """OAuth credentials should refresh only when the cached token is near expiry."""
    auth_request = object()
    credentials = _FakeCredentials(["token-1", "token-2"])

    monkeypatch.setitem(loc._token_cache, "token", None)
    monkeypatch.setitem(loc._token_cache, "expires_at", 0)
    monkeypatch.setattr(
        loc,
        "CONFIG",
        SimpleNamespace(google_credentials=credentials),
    )

    with (
        patch.object(loc.time, "time", side_effect=[100, 100, 200, 400, 400]),
        patch.object(loc, "Request", return_value=auth_request),
    ):
        first = loc.get_places_access_token()
        second = loc.get_places_access_token()
        refreshed = loc.get_places_access_token()

    assert (first, second, refreshed) == ("token-1", "token-1", "token-2")
    assert credentials.before_requests == [
        (
            auth_request,
            "POST",
            "https://places.googleapis.com/",
            {},
        ),
        (
            auth_request,
            "POST",
            "https://places.googleapis.com/",
            {},
        ),
    ]


# @features location
# @dimensions api-request session-bias response-mapping
@pytest.mark.unit
def test_search_places_uses_session_location_bias_and_maps_suggestions(monkeypatch):
    """Autocomplete should send a biased request and return compact suggestions."""
    response = _FakeResponse(
        {
            "suggestions": [
                {
                    "placePrediction": {
                        "placeId": "place-1",
                        "text": {"text": "Cafe Du Test"},
                    }
                },
                {"queryPrediction": {"text": {"text": "ignored"}}},
                {
                    "placePrediction": {
                        "placeId": "place-2",
                        "text": {"text": "Test Market"},
                    }
                },
            ]
        }
    )

    monkeypatch.setattr(
        loc,
        "session",
        {"location": json.dumps({"latitude": 29.95, "longitude": -90.07})},
    )

    with (
        patch.object(
            loc, "get_places_access_token", return_value="access-token"
        ) as token,
        patch.object(loc.requests, "post", return_value=response) as post,
    ):
        results = loc.search_places("coffee")

    assert results == [
        {"id": "place-1", "name": "Cafe Du Test"},
        {"id": "place-2", "name": "Test Market"},
    ]
    token.assert_called_once_with()
    post.assert_called_once_with(
        "https://places.googleapis.com/v1/places:autocomplete",
        headers={
            "Authorization": "Bearer access-token",
            "Content-Type": "application/json",
        },
        json={
            "input": "coffee",
            "locationBias": {
                "circle": {
                    "center": {"latitude": 29.95, "longitude": -90.07},
                    "radius": 25000.0,
                }
            },
        },
        timeout=loc.PLACES_AUTOCOMPLETE_TIMEOUT,
    )


# @features location
# @dimensions api-request address2 name-normalization
@pytest.mark.unit
def test_get_place_details_formats_address2_and_meaningful_name():
    response = _FakeResponse(
        {
            "id": "place-1",
            "displayName": {"text": "Cafe Du Test"},
            "formattedAddress": "123 Main St, New Orleans, LA 70112, USA",
            "addressComponents": [
                {"longText": "123", "types": ["street_number"]},
                {"longText": "Main St", "types": ["route"]},
                {"longText": "400", "types": ["subpremise"]},
            ],
        }
    )

    with (
        patch.object(loc, "get_places_access_token", return_value="access-token"),
        patch.object(loc.requests, "get", return_value=response) as get,
    ):
        result = loc.get_place_details("place-1")

    assert result == {
        "id": "place-1",
        "name": "Cafe Du Test",
        "address": "123 Main St, New Orleans, LA 70112, USA",
        "address2": "Unit 400",
    }
    get.assert_called_once()
    assert get.call_args.kwargs["timeout"] == loc.PLACES_DETAILS_TIMEOUT
    assert get.call_args.kwargs["params"]["fields"] == (
        "id,displayName,formattedAddress,addressComponents,location,"
        "nationalPhoneNumber,websiteUri,regularOpeningHours"
    )


# @features location
# @dimensions name-normalization
@pytest.mark.unit
def test_get_place_details_omits_street_address_display_name():
    response = _FakeResponse(
        {
            "id": "place-1",
            "displayName": {"text": "123 Main St"},
            "formattedAddress": "123 Main St, New Orleans, LA 70112, USA",
            "addressComponents": [
                {"longText": "123", "types": ["street_number"]},
                {"longText": "Main St", "types": ["route"]},
            ],
        }
    )

    with (
        patch.object(loc, "get_places_access_token", return_value="access-token"),
        patch.object(loc.requests, "get", return_value=response),
    ):
        result = loc.get_place_details("place-1")

    assert result == {
        "id": "place-1",
        "address": "123 Main St, New Orleans, LA 70112, USA",
    }


# @features location
# @dimensions provider-failure deadline diagnostics degradation
@pytest.mark.unit
def test_places_provider_failures_capture_once_and_degrade(monkeypatch):
    captured = []
    monkeypatch.setattr(loc, "session", {"location": "not-json"})
    monkeypatch.setattr(loc.exceptions, "capture", lambda error, context: captured.append((error, context)))

    with (
        patch.object(loc, "get_places_access_token", return_value="access-token"),
        patch.object(loc.requests, "post", side_effect=loc.requests.Timeout) as post,
    ):
        assert loc.search_places("coffee") == []

    assert post.call_args.kwargs["timeout"] == loc.PLACES_AUTOCOMPLETE_TIMEOUT
    assert len(captured) == 1
    assert captured[0][1] == {"context": "search_places", "method": "POST"}

    captured.clear()
    with (
        patch.object(loc, "get_places_access_token", return_value="access-token"),
        patch.object(
            loc.requests,
            "get",
            return_value=_FakeResponse({}, status_code=503),
        ),
    ):
        assert loc.get_place_details("place-1") is None

    assert len(captured) == 1
    assert captured[0][1] == {
        "context": "get_place_details",
        "method": "GET",
        "status": 503,
    }


# @features location
# @dimensions provider-contract diagnostics degradation
@pytest.mark.unit
def test_places_malformed_provider_payload_captures_once(monkeypatch):
    captured = []
    monkeypatch.setattr(loc, "session", {})
    monkeypatch.setattr(loc.exceptions, "capture", lambda error, context: captured.append((error, context)))

    with (
        patch.object(loc, "get_places_access_token", return_value="access-token"),
        patch.object(
            loc.requests,
            "post",
            return_value=_FakeResponse({"suggestions": {"not": "a list"}}),
        ),
    ):
        assert loc.search_places("coffee") == []

    assert len(captured) == 1
    assert captured[0][1] == {"context": "search_places", "method": "POST"}

    captured.clear()
    with (
        patch.object(loc, "get_places_access_token", return_value="access-token"),
        patch.object(
            loc.requests,
            "get",
            return_value=_FakeResponse(
                {
                    "id": "place-1",
                    "displayName": {"text": {"not": "text"}},
                    "formattedAddress": "123 Main St",
                    "addressComponents": [],
                }
            ),
        ),
    ):
        assert loc.get_place_details("place-1") is None

    assert len(captured) == 1
    assert captured[0][1] == {"context": "get_place_details", "method": "GET"}


# @features location
# @dimensions column free-text
@pytest.mark.unit
def test_location_address_only_value_and_column():
    field = _location_field()
    field.value = {"address": "123 Main St Suite 4", "name": "123 Main St Suite 4"}
    assert field.value["address"] == "123 Main St Suite 4"
    assert field.value.get("id") is None
    cv = field.column_value
    assert cv["url"] == (
        "https://www.google.com/maps/search/?api=1&query=123+Main+St+Suite+4"
    )
    assert cv["title"] == "123 Main St Suite 4"


# @features location
# @dimensions address2 column filter-value ai-value
@pytest.mark.unit
def test_location_place_value_preserves_address2():
    field = _location_field()
    details = {"id": "p1", "name": "Mock Place", "address": "123 Main St, City"}

    with patch.object(loc, "get_place_details", return_value=details.copy()):
        field.validate_submission({"id": "p1", "address2": "Suite 400"})

    assert field.value == {
        "id": "p1",
        "name": "Mock Place",
        "address": "123 Main St, City",
        "address2": "Suite 400",
    }
    assert field.column_value["title"] == "Mock Place, 123 Main St, Suite 400, City"
    assert field.column_value["url"] == (
        "https://www.google.com/maps/search/"
        "?api=1&query=Mock+Place%2C+123+Main+St%2C+Suite+400%2C+City"
        "&query_place_id=p1"
    )
    assert field.filter_value == "Mock Place, 123 Main St, Suite 400, City"
    assert field.ai_value == "Mock Place, 123 Main St, Suite 400, City"


# @features location
# @dimensions address2 column free-text
@pytest.mark.unit
def test_location_free_text_value_preserves_address2():
    field = _location_field()

    field.value = {
        "address": "123 Main St",
        "name": "123 Main St",
        "address2": "Apt 5",
    }

    assert field.value == {
        "address": "123 Main St",
        "name": "123 Main St",
        "address2": "Apt 5",
    }
    assert field.column_value["title"] == "123 Main St, Apt 5"


# @features location
# @dimensions address2 no-refetch
@pytest.mark.unit
def test_location_same_id_updates_address2_without_refetch():
    field = _location_field(
        {
            "id": "p1",
            "name": "Mock Place",
            "address": "123 Main St",
        }
    )
    field.db_value = {
        "id": "p1",
        "name": "Mock Place",
        "address": "123 Main St",
    }

    with patch.object(loc, "get_place_details") as get_place_details:
        field.value = {"id": "p1", "address2": "Unit B"}

    get_place_details.assert_not_called()
    assert field.value == {
        "id": "p1",
        "name": "Mock Place",
        "address": "123 Main St",
        "address2": "Unit B",
    }


# @features location
# @dimensions provider-failure free-text fallback warnings
@pytest.mark.unit
def test_location_place_detail_failure_falls_back_to_submitted_text():
    field = _location_field()

    with patch.object(loc, "get_place_details", return_value=None):
        field.validate_submission(
            {
                "id": "unverified-place",
                "name": "Cafe Du Test, New Orleans",
                "address2": "Suite 4",
            }
        )

    assert field.value == {
        "address": "Cafe Du Test, New Orleans",
        "name": "Cafe Du Test, New Orleans",
        "address2": "Suite 4",
    }
    assert "id" not in field.value
    assert field.warnings


# @features location
# @dimensions fallback warnings
@pytest.mark.unit
def test_location_validate_ai_fallback():
    field = _location_field()
    with patch.object(loc, "resolve_location_query", return_value=None):
        field.validate_ai("Nowhereville XYZ 99999")
    assert field.value["address"] == "Nowhereville XYZ 99999"
    assert field.warnings


# @features location
# @dimensions import fallback
@pytest.mark.unit
def test_location_validate_import_fallback():
    field = _location_field()
    with patch.object(loc, "resolve_location_query", return_value=None):
        field.validate_import("No match here")
    assert field.value["address"] == "No match here"
