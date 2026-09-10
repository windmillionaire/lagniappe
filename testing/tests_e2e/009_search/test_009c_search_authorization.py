import json
from uuid import uuid4
from urllib.parse import urlencode

import pytest
import requests
from playwright.sync_api import expect

from lagniappe.core.definitions import General, Levels, Restriction
from lagniappe.core.entities import Entities
from lagniappe import CONFIG
from testing.definitions import Forms, Pages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.elements import HeaderSearch
from testing.resources import Page, User
from testing.utility.network import assert_same_etag, manual_mutation_headers
from testing.utility.user_cache import acknowledge_user_cache_invalidation


pytestmark = pytest.mark.e2e


# @matrix search permissions : source-clauses pagination restricted-access
def test_redis_search_matches_each_restriction_source_before_pagination():
    from lagniappe.core.tools.auth.restrictions import restriction_fields
    from lagniappe.core.tools.cache import query
    from lagniappe.core.tools.cache.core import cache
    from lagniappe.core.tools.cache.keys import Keys, Search

    token = f"policy{uuid4().hex}"
    group_a, group_b, group_c, group_d = (uuid4().hex[:12] for _ in range(4))
    policies = {
        "open": {},
        "choice": {"page": [group_a, group_b]},
        "a": {"page": [group_a]},
        "b": {"page_form": [group_b]},
        "two": {"page": [group_a, group_b], "task_form": [group_c, group_d]},
        "three": {"page": [group_a, group_b], "page_form": [group_b, group_c],
                  "task_form": [group_c, group_d]},
        "administrators": {"task_form": ["admin"]},
    }
    ids = {name: f"{token}{name}" for name in policies}
    hashes = {name: uuid4().hex[:12] for name in policies}
    keys = [Search.page.value.format(key) for key in ids.values()]
    try:
        with cache.pipeline() as pipe:
            for name, restrictions in policies.items():
                row = {
                    "name": f"{token} {name}", "kind": "page",
                    "requires": token, "details_key": hashes[name],
                }
                row.update(restriction_fields(restrictions))
                pipe.hset(Search.page.value.format(ids[name]), mapping=row)
                pipe.hset(Keys.ENTITY_HASHES.value, hashes[name], json.dumps({
                    "id": ids[name], "hash": hashes[name], "kind": "page",
                    "name": row["name"],
                }))
            pipe.execute()

        raw = cache.search(query.Query(f"@requires:{{ {token} }}").dialect(2))
        assert raw.total == len(policies)
        for memberships, permitted in (
            ([], {"open"}),
            (Restriction.BELONGS_TO_NONE, {"open"}),
            ([group_a], {"open", "choice", "a"}),
            ([group_b], {"open", "choice", "b"}),
            ([group_c], {"open"}),
            ([group_a, group_b], {"open", "choice", "a", "b"}),
            ([group_a, group_c], {"open", "choice", "a", "two", "three"}),
            ([group_b, group_d], {"open", "choice", "b", "two", "three"}),
            ([group_a, group_b, group_c, group_d], set(policies) - {"administrators"}),
            (Restriction.BELONGS_TO_ALL, set(policies)),
        ):
            results, total = query.search(
                token, [token], memberships, kinds=["page"], limit=20,
            )
            assert total == len(permitted)
            assert {result["id"] for result in results} == {ids[name] for name in permitted}

        ungrouped, ungrouped_total = query.search(
            token, Restriction.UNRESTRICTED, Restriction.BELONGS_TO_NONE, kinds=["page"], limit=20,
        )
        assert ungrouped_total == 1
        assert [result["id"] for result in ungrouped] == [ids["open"]]

        first, first_total = query.search(
            token, [token], [group_a, group_b], kinds=["page"], page=1, limit=2,
        )
        second, second_total = query.search(
            token, [token], [group_a, group_b], kinds=["page"], page=2, limit=2,
        )
        assert first_total == second_total == 4
        assert len(first) == len(second) == 2
        assert {row["id"] for row in [*first, *second]} == {
            ids[name] for name in ("open", "choice", "a", "b")
        }
    finally:
        with cache.pipeline() as pipe:
            pipe.delete(*keys)
            pipe.hdel(Keys.ENTITY_HASHES.value, *hashes.values())
            pipe.execute()


# @matrix cache : invalidation no-store etag conditional-response
@pytest.mark.parametrize("path", ["/", "/l/get/tasks"])
def test_invalidation_is_not_replayed_by_browser_http_cache(
    get_user, browser, browser_failures, setup_test_server, path,
):
    owner = get_user(Users.OWNER)
    actor = User(user=owner, definition=UserDefinition(
        name="HTTP Cache Invalidation", email=f"http-cache-{uuid4().hex}@example.test",
    )).create()
    # Isolate the real browser HTTP cache from the worker's separate Cache API.
    # Fetch documents as data from a script-free page so this test owns the ack.
    with browser.new_context(service_workers="block") as context:
        browser_failures.monitor_context(context, label="HTTP cache invalidation")
        context.add_cookies(list(setup_test_server.browser_cookies))
        login = context.request.get(
            f"{CONFIG.BASE_URL}/users/login?{urlencode({'test_user': actor.email})}",
            max_redirects=0,
        )
        assert login.status == 302
        page = context.new_page()
        assert page.goto(f"{CONFIG.BASE_URL}/offline").status == 200

        def fetch(headers=None):
            return page.evaluate(
                """async ({path, headers}) => {
                    const response = await fetch(path, {headers});
                    await response.text();
                    return {
                        status: response.status,
                        etag: response.headers.get('ETag'),
                        cacheControl: response.headers.get('Cache-Control'),
                        invalidation: response.headers.get('X-Lagniappe-Invalidate-Cache'),
                        revision: response.headers.get('X-Lagniappe-Cache-Revision'),
                    };
                }""",
                {"path": path, "headers": headers or {}},
            )

        baseline = fetch()
        assert baseline["status"] == 200
        assert baseline["invalidation"] is None
        actor.entity = Entities.USER.load(actor.email)
        # Keep authorization identical: this proves the user modification
        # timestamp still independently invalidates the home/collection ETag.
        actor.entity.invalidate_cache = True
        actor.entity.save()
        pending = fetch({"If-None-Match": baseline["etag"]})
        assert pending["status"] == 200
        assert pending["etag"] != baseline["etag"]
        assert pending["invalidation"] and pending["revision"]
        assert pending["cacheControl"] == "no-store"
        # Matching validators must deliver the live command as a full
        # no-store response, never merge it into a cached body through 304.
        repeated = fetch({"If-None-Match": pending["etag"]})
        assert repeated["status"] == 200
        assert repeated["cacheControl"] == "no-store"
        assert repeated["revision"] == pending["revision"]
        modified = Entities.USER.load(actor.email).modified
        acknowledged = page.evaluate(
            """async (revision) => {
                const token = await fetch('/l/token');
                if (!token.ok) throw new Error(`Token HTTP ${token.status}`);
                const response = await fetch('/l/validate-user', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': await token.text()},
                    body: JSON.stringify({cacheCleared: true,
                        responseCacheCleared: true, cacheRevision: revision}),
                });
                return {status: response.status, body: await response.json()};
            }""",
            pending["revision"],
        )
        assert acknowledged == {
            "status": 200, "body": {"cacheCleared": True, "retry": False},
        }
        persisted = Entities.USER.load(actor.email)
        assert persisted.invalidate_cache is False
        assert persisted.modified == modified
        for headers, status in [({}, 200), ({}, 200),
                                ({"If-None-Match": pending["etag"]}, 304)]:
            clean = fetch(headers)
            assert clean["status"] == status
            assert clean["invalidation"] is None
            assert clean["revision"] is None
            assert clean["cacheControl"] == "private, no-cache"
            assert_same_etag(clean["etag"], pending["etag"])


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
                     headers=manual_mutation_headers(CONFIG.BASE_URL, token.text))
        assert stale.status_code == 200
        assert stale.json()["cacheCleared"] is False
        current = Entities.USER.load(user.email)
        assert current.is_admin is True and current.invalidate_cache is True
        token = send("GET", "/l/token")
        assert token.status_code == 200
        payload["cacheRevision"] = stale.headers["X-Lagniappe-Cache-Revision"]
        assert payload["cacheRevision"] != old_revision
        accepted = send("POST", "/l/validate-user", json=payload,
                        headers=manual_mutation_headers(CONFIG.BASE_URL, token.text))
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
    restricted_page.entity.properties.restricted_to.materialize(admin_only=True)
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
