"""E2E coverage for batched committed-entity fingerprint checks."""

import pytest

from testing.definitions import Pages, SitePages, Users


pytestmark = pytest.mark.e2e


def check_entities(user, entities):
    return user.page.evaluate(
        """async (entities) => {
            const response = await fetch("/edited", {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.getElementById("token")?.value,
                    "X-Lagniappe-Request": "true",
                },
                body: JSON.stringify({ entities }),
            });
            const text = await response.text();
            let data = text;
            try { data = JSON.parse(text); } catch {}
            return { status: response.status, data };
        }""",
        entities,
    )


# @pair edited-entity-notice:batch
# @pair edited-entity-notice:fingerprint
# @pair edited-entity-notice:unavailable
# @pair edited-entity-notice:authorization
# @pair edited-entity-notice:descriptor-validation
# @pair edited-entity-notice:batch-limit
# @pair edited-entity-notice:duplicate-keys
# @pair permissions:batch
# @pair permissions:fingerprint
# @pair permissions:unavailable
# @pair permissions:authorization
def test_edited_endpoint_batches_fingerprint_checks(get_user):
    owner = get_user(Users.OWNER)
    page = Pages.test_sync_form_page.get(owner)
    owner.go(page)

    descriptor = {
        "key": page.entity.urlsafe_key,
        "fingerprint": page.entity.fingerprint,
    }
    current = check_entities(owner, [descriptor])
    assert current == {
        "status": 200,
        "data": {"edited": [], "operations": []},
    }

    stale = check_entities(owner, [{**descriptor, "fingerprint": "stale"}])
    assert stale["status"] == 200
    assert stale["data"] == {
        "edited": [
            {
                "key": page.entity.urlsafe_key,
                "fingerprint": page.entity.fingerprint,
                "modified": page.entity.modified.isoformat(),
            }
        ],
        "operations": [],
    }

    blocked = get_user(Users.user_no_access)
    blocked.go(SitePages.HOME)
    inaccessible = check_entities(blocked, [descriptor])
    assert inaccessible == {
        "status": 200,
        "data": {
            "edited": [
                {"key": page.entity.urlsafe_key, "unavailable": True}
            ],
            "operations": [],
        },
    }

    duplicate = check_entities(owner, [descriptor, descriptor])
    assert duplicate["status"] == 422
    assert duplicate["data"] == "Invalid edited entity descriptors."

    oversized = check_entities(
        owner,
        [
            {"key": f"entity-{index}", "fingerprint": "same"}
            for index in range(33)
        ],
    )
    assert oversized["status"] == 422
