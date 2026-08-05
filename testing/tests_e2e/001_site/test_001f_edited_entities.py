"""E2E coverage for the unified polling contract."""

import json
from urllib.parse import urlsplit

import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.cache.keys import Keys
from testing.definitions import Pages, SitePages, Users


pytestmark = pytest.mark.e2e


def poll(user, subscriptions):
    return user.page.evaluate(
        """async (subscriptions) => {
            const response = await fetch("/l/poll", {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.getElementById("token")?.value,
                    "X-Lagniappe-Request": "true",
                },
                body: JSON.stringify({
                    version: 1,
                    client_id: "poll-contract-test",
                    subscriptions,
                }),
            });
            const text = await response.text();
            let data = text;
            try { data = JSON.parse(text); } catch {}
            return { status: response.status, data };
        }""",
        subscriptions,
    )


# @pairs polling:protocol polling:entity polling:channel polling:batching
# @pairs polling:identifiers polling:fingerprint polling:revision
# @pairs polling:unavailable polling:authorization polling:validation
# @pair polling:permissions
def test_poll_endpoint_batches_entity_changes(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = Pages.test_sync_form_page.get(owner)
    owner.go(page)

    descriptor = {
        "id": "entity-under-test",
        "type": "entity",
        "key": page.entity.urlsafe_key,
        "revision": page.entity.fingerprint,
    }
    current = poll(owner, [descriptor])
    assert current["status"] == 200
    assert current["data"]["version"] == 1
    assert current["data"]["results"] == [
        {
            "id": "entity-under-test",
            "type": "entity",
            "status": "unchanged",
            "revision": page.entity.fingerprint,
            "poll_after_ms": 15000,
        }
    ]

    stale = poll(owner, [{**descriptor, "revision": "stale"}])
    assert stale["data"]["results"][0] == {
        "id": "entity-under-test",
        "type": "entity",
        "status": "changed",
        "revision": page.entity.fingerprint,
        "poll_after_ms": 15000,
        "payload": {
            "fingerprint": page.entity.fingerprint,
            "modified": page.entity.modified.isoformat(),
        },
    }

    channel = poll(
        owner,
        [
            {
                "id": "home-channel",
                "type": "channel",
                "channel": "home",
                "revision": None,
            }
        ],
    )["data"]["results"][0]
    assert channel["status"] == "changed"
    assert channel["payload"] == {"refresh": True}
    unchanged_channel = poll(
        owner,
        [
            {
                "id": "home-channel",
                "type": "channel",
                "channel": "home",
                "revision": channel["revision"],
            }
        ],
    )["data"]["results"][0]
    assert unchanged_channel["status"] == "unchanged"

    blocked = get_user(Users.user_no_access)
    blocked.go(SitePages.HOME)
    inaccessible = poll(blocked, [descriptor])
    assert inaccessible["data"]["results"][0]["status"] == "unavailable"

    with browser_failures.expect_http_error(
        owner,
        status=422,
        path="/l/poll",
        count=4,
    ):
        duplicate = poll(owner, [descriptor, descriptor])
        assert duplicate["status"] == 422

        malformed_document = poll(
            owner,
            [
                {
                    "id": "invalid-document",
                    "type": "document",
                    "key": page.entity.urlsafe_key,
                    "sync_id": page.entity.sync_ids["document"]["id"],
                    "revision": "not-an-integer",
                }
            ],
        )
        assert malformed_document["status"] == 422

        malformed_revision = poll(owner, [{**descriptor, "revision": {"nested": True}}])
        assert malformed_revision["status"] == 422

        oversized = poll(
            owner,
            [
                {
                    "id": f"entity-{index}",
                    "type": "entity",
                    "key": f"entity-{index}",
                    "revision": "same",
                }
                for index in range(65)
            ],
        )
        assert oversized["status"] == 422


# @pairs notifications:cold-seed notifications:ping notifications:redis-projection
# @pairs polling:personal-state polling:piggyback web-headers:notification-state
def test_cold_notification_state_seeds_through_one_poll(get_user):
    owner = get_user(Users.OWNER)
    actor = Entities.USER.load(owner.email)
    state_key = Keys.NOTIFICATIONS.value.format(actor.urlsafe_key)
    epoch_key = Keys.NOTIFICATION_EPOCH.value.format(actor.urlsafe_key)
    owner.go(SitePages.HOME)
    owner.page.wait_for_timeout(250)
    cache.core.cache.redis.delete(state_key, epoch_key)

    poll_requests = []

    def record_poll(request):
        if urlsplit(request.url).path == "/l/poll":
            poll_requests.append(request)

    owner.page.on("request", record_poll)
    with owner.page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/l/ping"
            and response.request.method == "HEAD"
        )
    ) as cold_ping_info, owner.page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/l/poll"
            and response.request.method == "POST"
        )
    ) as seed_poll_info:
        owner.page.reload()

    missing = json.loads(
        cold_ping_info.value.headers["x-lagniappe-notification-state"]
    )
    seed_request = seed_poll_info.value.request.post_data_json
    seeded = json.loads(
        seed_poll_info.value.headers["x-lagniappe-notification-state"]
    )

    assert missing == {
        "generation": None,
        "revision": None,
        "count": None,
    }
    assert seed_request["subscriptions"] == []
    assert seed_request["notification_state"] == {
        "generation": None,
        "revision": None,
        "seed": True,
    }
    assert isinstance(seeded["generation"], str)
    assert seeded["revision"] >= 0
    assert seeded["count"] >= 0
    assert len(poll_requests) == 1

    poll_requests.clear()
    with owner.page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/l/ping"
            and response.request.method == "HEAD"
        )
    ) as warm_ping_info:
        owner.page.reload()
    owner.page.wait_for_timeout(750)

    warm = json.loads(
        warm_ping_info.value.headers["x-lagniappe-notification-state"]
    )
    assert warm == seeded
    assert poll_requests == []
