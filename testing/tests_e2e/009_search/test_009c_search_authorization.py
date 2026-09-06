from uuid import uuid4
from urllib.parse import urlencode

import pytest
import requests
from playwright.sync_api import expect

from lagniappe.core.definitions import General, Levels
from lagniappe.core.entities import Entities
from lagniappe import CONFIG
from testing.definitions import Forms, Pages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.elements import HeaderSearch
from testing.resources import Page, User
from testing.utility.user_cache import acknowledge_user_cache_invalidation


pytestmark = pytest.mark.e2e


# @matrix cache user : invalidation acknowledgement concurrency property-mask
# @pair cache:invalidation-acknowledgement
def test_cache_acknowledgement_preserves_newer_permissions(get_user, setup_test_server):
    owner = get_user(Users.OWNER)
    user = User(user=owner, definition=UserDefinition(
        name="Cache Acknowledgement", email=f"cache-ack-{uuid4().hex}@example.test",
    )).create()
    # Exercise the real HTTP acknowledgement protocol without an automatic
    # worker consuming the revisions we deliberately deliver out of order.
    cookies = {cookie["name"]: cookie["value"] for cookie in setup_test_server.browser_cookies}
    headers = {"Origin": CONFIG.BASE_URL, "X-Lagniappe-Request": "true",
               "User-Agent": "Lagniappe cache acknowledgement regression"}

    def send(method, path, **options):
        # Replay cookies only to this exact origin, including on the local HTTP
        # runner. Preserve Set-Cookie without duplicate host/domain cookie jars.
        response = requests.request(
            method, f"{CONFIG.BASE_URL}{path}", cookies=cookies,
            headers={**headers, **options.pop("headers", {})},
            timeout=30, allow_redirects=False, **options,
        )
        cookies.update(response.cookies.get_dict())
        return response

    # A browser login starts keepalive timezone updates even when its temporary
    # context closes. Use HTTP-only login so this protocol test owns all requests.
    login = send("GET", f"/users/login?{urlencode({'test_user': user.email})}")
    assert login.status_code == 302
    user.entity = Entities.USER.load(user.email)
    user.entity.invalidate_cache = True
    user.entity.save()
    initial = send("GET", "/")
    assert initial.status_code == 200
    old_revision = initial.headers["X-Lagniappe-Cache-Revision"]
    token = send("GET", "/l/token")
    assert token.status_code == 200
    user.entity.is_admin = True
    user.entity.save()
    try:
        payload = {"cacheCleared": True, "responseCacheCleared": True, "cacheRevision": old_revision}
        stale = send("POST", "/l/validate-user", json=payload,
                     headers={"X-CSRFToken": token.text})
        assert stale.status_code == 200
        assert stale.json()["cacheCleared"] is False
        current = Entities.USER.load(user.email)
        assert current.is_admin is True and current.invalidate_cache is True
        token = send("GET", "/l/token")
        assert token.status_code == 200
        payload["cacheRevision"] = stale.headers["X-Lagniappe-Cache-Revision"]
        assert payload["cacheRevision"] != old_revision
        accepted = send("POST", "/l/validate-user", json=payload,
                        headers={"X-CSRFToken": token.text})
        assert accepted.status_code == 200
        assert accepted.json()["cacheCleared"] is True
        current = Entities.USER.load(user.email)
        assert current.is_admin is True and current.invalidate_cache is False
    finally:
        user.entity = Entities.USER.load(user.email)
        user.entity.is_admin = False
        user.entity.save()


# @matrix search : permissions
# @pair cache:invalidation-acknowledgement
def test_search_matches_explicit_denial_and_administrator_content_access(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    user = get_user(
        UserDefinition(
            name=f"Search Authorization User {suffix[:8]}",
            email=f"search-authorization-{suffix}@example.test",
        ),
        creator=owner,
    )
    unrestricted_form = Forms.test_basic_inputs_form.get(owner)
    restricted_page = Pages.test_owner_restricted_page.get(owner)
    restricted_page.entity.properties.restricted_to.add("owner")
    restricted_page.entity.save()

    user.entity.properties.permissions.create({General.FORMS.value: Levels.NONE.name})
    user.entity.save()
    acknowledge_user_cache_invalidation(user)
    HeaderSearch(user).verify_entity_not_in_results(unrestricted_form)

    user.entity.is_admin = True
    user.entity.save()
    try:
        acknowledge_user_cache_invalidation(user)
        HeaderSearch(user).verify_entity_in_results(restricted_page)
        user.go(restricted_page)
        expect(user.locate(Page.PAGE_TITLE)).to_contain_text(
            restricted_page.definition.name
        )
    finally:
        user.entity = Entities.USER.load(user.email)
        user.entity.is_admin = False
        user.entity.save()
        acknowledge_user_cache_invalidation(user)
