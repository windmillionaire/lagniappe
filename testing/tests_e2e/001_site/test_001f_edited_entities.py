"""E2E coverage for the unified polling contract."""

from types import SimpleNamespace

import pytest

from testing.definitions import Pages, SitePages, Users


pytestmark = pytest.mark.e2e


# @pairs notifications:personal-activity notifications:revision notifications:datastore-read-isolation
# @source lagniappe/web/routes/home/poll.py::_channel_revision
def test_notification_channel_revision_comes_from_loaded_user(monkeypatch):
    from lagniappe.web.routes.home import poll as poll_routes

    monkeypatch.setattr(
        poll_routes.database,
        "site_fingerprint",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("notification revision read a site fingerprint")
        ),
    )
    user = SimpleNamespace(
        fingerprint="unchanged-user-fingerprint",
        permissions_fingerprint="unchanged-permissions",
        notification_revision=4,
    )

    before = poll_routes._channel_revision("notifications", user)
    user.notification_revision += 1
    after = poll_routes._channel_revision("notifications", user)

    assert before != after


# @features polling deferred-jobs
# @dimensions personal-activity revision datastore-read-isolation batching
# @source lagniappe/web/routes/home/poll.py::_operation_statuses
def test_operation_revision_skips_quiet_job_reads(monkeypatch):
    from lagniappe.web.routes.home import poll as poll_routes

    user = SimpleNamespace(operation_revision=9)
    loaded = []

    def statuses(keys, actor):
        loaded.append((list(keys), actor))
        return [{"key": key, "revision": 3} for key in keys]

    monkeypatch.setattr(poll_routes.DeferredJobs, "statuses", statuses)
    stale = [
        {
            "id": "operation:one",
            "type": "operation",
            "key": "one",
            "operation_revision": None,
        }
    ]
    revision, projected = poll_routes._operation_statuses(stale, user)

    assert revision == 9
    assert projected == {"one": {"key": "one", "revision": 3}}
    assert loaded == [(["one"], user)]

    loaded.clear()
    current = [{**stale[0], "operation_revision": 9}]
    revision, projected = poll_routes._operation_statuses(current, user)

    assert revision == 9
    assert projected == {}
    assert loaded == []


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

        malformed_revision = poll(
            owner, [{**descriptor, "revision": {"nested": True}}]
        )
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
