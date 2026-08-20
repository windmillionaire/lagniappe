"""Google Places API integration (autocomplete and place details)."""

import json
import re
import time

from flask import session
from google.auth.transport.requests import Request
import requests

from lagniappe import CONFIG

from .. import exceptions

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
# @tests tests_unit/test_003d_submission_location.py::test_simplify_address_for_search_comma_suite
# @tests tests_unit/test_003d_submission_location.py::test_simplify_address_for_search_trailing_suite
# @tests tests_unit/test_003d_submission_location.py::test_simplify_address_for_search_no_change
# @features location
# @dimensions suite-stripping
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
# @features location
# @dimensions retry, suite-stripping, first-hit
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
# @covered-by lagniappe/core/tools/location.py::get_place_details
# @reason address component parsing is private Places response normalization
def _address_component(address_components, component_type, text_key="longText"):
    for component in address_components or []:
        if component_type in component.get("types", []):
            return component.get(text_key) or component.get("longText")
    return None


# @testable false
# @covered-by lagniappe/core/tools/location.py::get_place_details
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
# @covered-by lagniappe/core/tools/location.py::get_place_details
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
# @covered-by lagniappe/core/tools/location.py::get_place_details
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
# @features location
# @dimensions api-cache, oauth
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
# @features location
# @dimensions api-request, address2, name-normalization
def get_place_details(place_id):
    """Fetch place details (name, address) from Google Places API."""
    if not place_id:
        return None

    try:
        access_token = get_places_access_token()
        if not access_token:
            return None

        url = f"https://places.googleapis.com/v1/places/{place_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        params = {
            "fields": (
                "id,displayName,formattedAddress,addressComponents,location,"
                "nationalPhoneNumber,websiteUri,regularOpeningHours"
            )
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            address_components = data.get("addressComponents", [])
            address2 = _format_address2(
                _address_component(address_components, "subpremise")
            )
            formatted_address = data.get("formattedAddress")
            address = _formatted_address_without_unit(formatted_address, address2)
            name = _meaningful_place_name(
                data.get("displayName", {}).get("text"),
                formatted_address,
                address_components,
            )

            place = {
                "id": data.get("id"),
                "name": name,
                "address": address,
                "address2": address2,
            }
            return {k: v for k, v in place.items() if v}

        else:
            error = exceptions.NetworkError(response.text)
            context = {
                "method": "GET",
                "context": "get_place_details",
                "place_id": place_id,
            }
            exceptions.capture(error, context)
            raise error

    except Exception as e:
        context = {
            "context": "get_place_details",
            "place_id": place_id,
        }
        exceptions.capture(e, context)
        raise e


# @testable true
# @tests tests_unit/test_003d_submission_location.py::test_search_places_uses_session_location_bias_and_maps_suggestions
# @features location
# @dimensions api-request, session-bias, response-mapping
def search_places(query):
    """Autocomplete a place query, biased to the user's session location."""
    if not query or len(query) < 3:
        return []

    try:
        access_token = get_places_access_token()
        if not access_token:
            return []

        url = "https://places.googleapis.com/v1/places:autocomplete"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        data = {"input": query}

        if "location" in session:
            location = json.loads(session["location"])
            data["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": location["latitude"],
                        "longitude": location["longitude"],
                    },
                    "radius": 25000.0,
                }
            }

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            data = response.json()
            suggestions = data.get("suggestions", [])

            results = []
            for suggestion in suggestions:
                place_prediction = suggestion.get("placePrediction")
                if place_prediction:
                    full_text = place_prediction.get("text", {}).get("text", "")

                    results.append(
                        {
                            "id": place_prediction.get("placeId"),
                            "name": full_text,
                        }
                    )

            return results
        else:
            error = exceptions.NetworkError(response.text)
            context = {
                "method": "POST",
                "context": "search_places",
            }
            exceptions.capture(error, context)
            raise error

    except Exception as e:
        context = {
            "method": "POST",
            "context": "search_places",
        }
        exceptions.capture(e, context)
        raise e
