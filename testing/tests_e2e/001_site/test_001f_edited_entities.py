"""E2E coverage for the unified polling contract."""

import pytest

from testing.definitions import Pages, SitePages, Users


pytestmark = pytest.mark.e2e


def poll(user, subscriptions):
    return user.page.evaluate(
        """async (subscriptions) => {
            const response = await fetch("/poll", {
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
        path="/poll",
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
