"""Google Places API integration (autocomplete and place details)."""

import json
import math
import re
import time
from urllib.parse import quote

from google.auth.exceptions import GoogleAuthError
from flask import session
from google.auth.transport.requests import Request

from lagniappe import CONFIG

from ... import exceptions
from ..http import (
    PLACES_AUTOCOMPLETE_POLICY,
    PLACES_DETAILS_POLICY,
    request_trusted_content,
)

_token_cache = {"token": None, "expires_at": 0}

# Trailing secondary unit (suite, apt, etc.) without a preceding comma.
_TRAILING_UNIT = re.compile(
    r"(?i)\s+(?:suite|ste|apt|apartment|unit|floor|fl)\s*[\.#:]?\s*[\w\-/#]+(?:\s*$)"
)
# Trailing "# 12" or "#12" (common in pasted addresses).
_TRAILING_HASH_UNIT = re.compile(r"(?i)\s+#\s*[\w\-]+\s*$")
# From a comma before suite/apt through end of string (e.g. ", Suite 400, City, ST").
_COMMA_THEN_UNIT = re.compile(
    r"(?i)[,;]\s*(?:suite|ste|apt|apartment|unit|floor|fl|bldg|building|#)\s.*$"
)
_UNIT_LABEL = re.compile(
    r"(?i)^(?:suite|ste|apt|apartment|unit|floor|fl|room|rm|#)\b|^#"
)


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_normalize_location_coordinates_rejects_malformed_values
# @matrix location : coordinates session-bias validation
def normalize_location_coordinates(value):
    """Return normalized finite latitude/longitude coordinates, or ``None``."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
    if not isinstance(value, dict):
        return None

    latitude = value.get("latitude")
    longitude = value.get("longitude")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return None

    latitude = float(latitude)
    longitude = float(longitude)
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return None
    return {"latitude": latitude, "longitude": longitude}


# @testable false
# @covered-by lagniappe/core/tools/services/places.py::search_places
# @covered-by lagniappe/core/tools/services/places.py::get_place_details
# @reason fixed-host provider transport is exercised through both public Places operations
def _request_places_json(method, path, *, operation, policy, params=None, data=None):
    status = None
    try:
        access_token = get_places_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        result = request_trusted_content(
            method,
            path,
            policy,
            headers=headers,
            params=params,
            json_body=data,
        )
        status = result.http_status
        if not result.ok:
            raise exceptions.NetworkError("Places request failed.")
        payload = json.loads(result.body)
        if not isinstance(payload, dict):
            raise exceptions.NetworkError("Places response did not match its contract.")
        return payload
    except (
        GoogleAuthError,
        RuntimeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        exceptions.NetworkError,
    ):
        exceptions.capture(
            exceptions.NetworkError("Places provider operation failed."),
            {
                "context": operation,
                "method": method,
                **({"status": status} if status is not None else {}),
            },
        )
        return None


# @testable false
# @covered-by lagniappe/core/tools/services/places.py::search_places
# @covered-by lagniappe/core/tools/services/places.py::get_place_details
# @reason provider-shape failures share the same sanitized diagnostic boundary
def _capture_contract_failure(operation, method):
    exceptions.capture(
        exceptions.NetworkError("Places response did not match its contract."),
        {"context": operation, "method": method},
    )


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_simplify_address_for_search_comma_suite
# @tests tests_unit/test_003d_submission_location.py::test_simplify_address_for_search_trailing_suite
# @tests tests_unit/test_003d_submission_location.py::test_simplify_address_for_search_no_change
# @pair location:suite-stripping
def simplify_address_for_search(query):
    """Strip one secondary-address clause for a follow-up Places search.

    Returns a shorter string or None if nothing was removed or the result is too short.
    """
    if not query or not isinstance(query, str):
        return None
    s = query.strip()
    if len(s) < 3:
        return None

    t = _COMMA_THEN_UNIT.sub("", s).strip()
    if t != s and len(t) >= 3:
        return t

    t = _TRAILING_UNIT.sub("", s).strip()
    if t != s and len(t) >= 3:
        return t

    t = _TRAILING_HASH_UNIT.sub("", s).strip()
    if t != s and len(t) >= 3:
        return t

    return None


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_resolve_location_query_retries_after_simplify
# @tests tests_unit/test_003d_submission_location.py::test_resolve_location_query_first_hit_wins
# @matrix location : first-hit retry suite-stripping
def resolve_location_query(query):
    """Autocomplete a query; if empty, retry once with simplified address text.

    Returns the first ``{id, name}`` suggestion or None if no match.
    """
    if not query or not isinstance(query, str):
        return None
    q = query.strip()
    if len(q) < 3:
        return None

    places = search_places(q)
    if places:
        return places[0]

    simplified = simplify_address_for_search(q)
    if simplified:
        places = search_places(simplified)
        if places:
            return places[0]

    return None


# @testable false
# @covered-by lagniappe/core/tools/services/places.py::get_place_details
# @reason address component parsing is private Places response normalization
def _address_component(address_components, component_type, text_key="longText"):
    for component in address_components or []:
        if component_type in component.get("types", []):
            return component.get(text_key) or component.get("longText")
    return None


# @testable false
# @covered-by lagniappe/core/tools/services/places.py::get_place_details
# @reason unit label formatting is private Places response normalization
def _format_address2(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _UNIT_LABEL.search(text):
        return text
    return f"Unit {text}"


# @testable false
# @covered-by lagniappe/core/tools/services/places.py::get_place_details
# @reason place-name filtering is private Places response normalization
def _meaningful_place_name(name, formatted_address, address_components):
    if not name:
        return None

    text = str(name).strip()
    if not text:
        return None

    street_number = _address_component(address_components, "street_number")
    route = _address_component(address_components, "route")
    street_address = " ".join(v for v in [street_number, route] if v)
    address_line = (formatted_address or "").split(",", 1)[0].strip()
    candidates = [formatted_address, address_line, street_address]

    normalized = re.sub(r"[^a-z0-9]+", "", text.casefold())
    for candidate in candidates:
        candidate = re.sub(r"[^a-z0-9]+", "", str(candidate or "").casefold())
        if candidate and normalized == candidate:
            return None

    return text


# @testable false
# @covered-by lagniappe/core/tools/services/places.py::get_place_details
# @reason address cleanup is private Places response normalization
def _formatted_address_without_unit(formatted_address, address2):
    if not formatted_address:
        return None

    address = str(formatted_address).strip()
    if not address or not address2:
        return address or None

    unit = str(address2).casefold()
    parts = [part.strip() for part in address.split(",")]
    filtered = [part for part in parts if unit not in part.casefold()]
    return ", ".join(filtered) or address


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_get_places_access_token_reuses_cached_token_until_refresh_window
# @matrix location : api-cache oauth
def get_places_access_token():
    """Get a cached OAuth2 access token for the Places API."""
    now = time.time()

    if _token_cache["token"] and _token_cache["expires_at"] > (now + 60):
        return _token_cache["token"]

    credentials = CONFIG.google_credentials
    credentials.before_request(
        Request(),
        "POST",
        "https://places.googleapis.com/",
        {},
    )
    if not credentials.token:
        raise RuntimeError(
            "Application Default Credentials did not provide a Places access token."
        )

    _token_cache["token"] = credentials.token
    expiry = getattr(credentials, "expiry", None)
    _token_cache["expires_at"] = (
        expiry.timestamp() if expiry is not None else time.time() + 300
    )

    return credentials.token


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_get_place_details_formats_address2_and_meaningful_name
# @tests tests_unit/test_003d_submission_location.py::test_get_place_details_omits_street_address_display_name
# @tests tests_unit/test_003d_submission_location.py::test_places_provider_failures_capture_once_and_degrade
# @matrix location : address2 api-request deadline degradation diagnostics name-normalization provider-failure
def get_place_details(place_id):
    """Fetch place details (name, address) from Google Places API."""
    if not place_id:
        return None

    data = _request_places_json(
        "GET",
        f"places/{quote(str(place_id), safe='')}",
        operation="get_place_details",
        policy=PLACES_DETAILS_POLICY,
        params={
            "fields": (
                "id,displayName,formattedAddress,addressComponents,location,"
                "nationalPhoneNumber,websiteUri,regularOpeningHours"
            )
        },
    )
    if data is None:
        return None

    address_components = data.get("addressComponents", [])
    display_name = data.get("displayName", {})
    formatted_address = data.get("formattedAddress")
    if (
        not isinstance(data.get("id"), str)
        or not data["id"].strip()
        or not isinstance(address_components, list)
        or not all(isinstance(component, dict) for component in address_components)
        or not all(
            isinstance(component.get("types", []), list)
            and all(
                isinstance(component_type, str)
                for component_type in component.get("types", [])
            )
            and isinstance(component.get("longText"), (str, type(None)))
            and isinstance(component.get("shortText"), (str, type(None)))
            for component in address_components
        )
        or not isinstance(display_name, dict)
        or not isinstance(display_name.get("text", ""), str)
        or not isinstance(formatted_address, (str, type(None)))
    ):
        _capture_contract_failure("get_place_details", "GET")
        return None

    address2 = _format_address2(
        _address_component(address_components, "subpremise")
    )
    address = _formatted_address_without_unit(formatted_address, address2)
    name = _meaningful_place_name(
        display_name.get("text"),
        formatted_address,
        address_components,
    )

    place = {
        "id": data.get("id"),
        "name": name,
        "address": address,
        "address2": address2,
    }
    place = {key: value for key, value in place.items() if value}
    if not place.get("name") and not place.get("address"):
        _capture_contract_failure("get_place_details", "GET")
        return None
    return place


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_search_places_uses_session_location_bias_and_maps_suggestions
# @tests tests_unit/test_003d_submission_location.py::test_places_provider_failures_capture_once_and_degrade
# @tests tests_unit/test_003d_submission_location.py::test_places_malformed_provider_payload_captures_once
# @matrix location : api-request deadline degradation diagnostics provider-contract provider-failure response-mapping session-bias
def search_places(query):
    """Autocomplete a place query, biased to the user's session location."""
    if not query or len(query) < 3:
        return []

    data = {"input": query}
    location = normalize_location_coordinates(session.get("location"))
    if location:
        data["locationBias"] = {
            "circle": {
                "center": location,
                "radius": 25000.0,
            }
        }

    payload = _request_places_json(
        "POST",
        "places:autocomplete",
        operation="search_places",
        policy=PLACES_AUTOCOMPLETE_POLICY,
        data=data,
    )
    if payload is None:
        return []

    suggestions = payload.get("suggestions", [])
    if not isinstance(suggestions, list):
        _capture_contract_failure("search_places", "POST")
        return []

    results = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        place_prediction = suggestion.get("placePrediction")
        if not isinstance(place_prediction, dict):
            continue
        prediction_text = place_prediction.get("text", {})
        if not isinstance(prediction_text, dict):
            continue
        place_id = place_prediction.get("placeId")
        full_text = prediction_text.get("text")
        if place_id and full_text:
            results.append({"id": place_id, "name": full_text})

    return results
