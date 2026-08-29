"""E2E coverage for the unified polling contract."""

from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.cache.keys import Keys
from lagniappe.core.tools.notifications.service import create_ordinary_notification
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
                    closed_documents: [],
                }),
            });
            const text = await response.text();
            let data = text;
            try { data = JSON.parse(text); } catch {}
            return { status: response.status, data };
        }""",
        subscriptions,
    )


# @matrix polling : authorization batching channel entity fingerprint identifiers permissions protocol revision unavailable validation
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
        count=5,
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
                    "generation": None,
                    "revision": "not-an-integer",
                    "presence_digest": None,
                }
            ],
        )
        assert malformed_document["status"] == 422
        assert malformed_document["data"] == {
            "error": "Invalid polling request.",
            "code": "invalid_poll_contract",
            "path": "subscriptions[0].revision",
            "reason": "type",
        }

        malformed_revision = poll(owner, [{**descriptor, "revision": {"nested": True}}])
        assert malformed_revision["status"] == 422

        retired_notification_channel = poll(
            owner,
            [
                {
                    "id": "notifications",
                    "type": "channel",
                    "channel": "notifications",
                    "revision": None,
                }
            ],
        )
        assert retired_notification_channel["status"] == 422

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


# @matrix notifications : cold-seed ping redis-projection
# @matrix polling : personal-state piggyback
# @pair web-headers:notification-state
def test_cold_notification_state_seeds_through_one_poll(get_user):
    owner = get_user(Users.OWNER)
    actor = Entities.USER.load(owner.email)
    state_key = Keys.NOTIFICATIONS.value.format(actor.urlsafe_key)
    epoch_key = Keys.NOTIFICATION_EPOCH.value.format(actor.urlsafe_key)
    owner.go(SitePages.HOME)
    body = f"Cold notification seed {uuid4().hex}"
    create_ordinary_notification(
        actor,
        identifier=uuid4().hex,
        body=body,
    )
    expected_count = len(Entities.NOTIFICATION.keys_for_parent(actor))

    cache.core.cache.redis.delete(state_key, epoch_key)
    with owner.page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/l/poll"
            and response.request.method == "POST"
        )
    ):
        owner.page.reload()

    count = owner.locate("[data-role='notification-count']")
    expect(count).to_have_text(str(expected_count), timeout=15000)
    notifications = owner.locate("[data-role='notifications']")
    expect(notifications).to_have_attribute(
        "aria-label", f"Notifications: {expected_count}"
    )
    notifications.click()
    expect(
        owner.page.locator("[role='listbox'][data-visible='true']").get_by_text(
            body, exact=True
        )
    ).to_be_visible()
