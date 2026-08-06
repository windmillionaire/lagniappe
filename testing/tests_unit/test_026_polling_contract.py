"""Focused tests for the strict adaptive-polling wire contract."""

import pytest

from lagniappe.core.tools.polling_contract import (
    MAX_POLL_REVISION,
    MAX_POLL_SUBSCRIPTIONS,
    PollContractError,
    parse_poll_request,
)


pytestmark = pytest.mark.unit


def poll_request(subscriptions=None, **overrides):
    request = {
        "version": 1,
        "client_id": "poll-contract-test",
        "subscriptions": subscriptions or [],
        "closed_documents": [],
    }
    request.update(overrides)
    return request


# @source lagniappe/core/tools/polling_contract.py::parse_poll_request
# @source lagniappe/core/tools/polling_contract.py::PollContractError
# @features polling
# @dimensions protocol descriptors validation
def test_poll_contract_accepts_each_descriptor_type():
    descriptors = [
        {
            "id": "entity:one",
            "type": "entity",
            "key": "entity-one",
            "revision": None,
        },
        {
            "id": "channel:tasks",
            "type": "channel",
            "channel": "tasks",
            "revision": "channel-cursor",
        },
        {
            "id": "lock:one",
            "type": "form-lock",
            "key": "entity-one",
            "revision": "unlocked",
        },
        {
            "id": "ingress:one",
            "type": "ingress",
            "key": "ingress-one",
            "revision": None,
        },
        {
            "id": "operation:one",
            "type": "operation",
            "key": "operation-one",
            "revision": 0,
        },
        {
            "id": "document:one:document",
            "type": "document",
            "key": "entity-one",
            "sync_id": "one:document",
            "generation": None,
            "revision": 0,
            "presence_digest": None,
        },
    ]

    parsed = parse_poll_request(
        poll_request(
            descriptors,
            closed_documents=["closed:document"],
            notification_state={
                "generation": "notification-generation",
                "revision": 4,
                "seed": False,
            },
        )
    )

    assert parsed.client_id == "poll-contract-test"
    assert parsed.subscriptions == tuple(descriptors)
    assert parsed.closed_documents == ("closed:document",)
    assert parsed.notification_state == {
        "generation": "notification-generation",
        "revision": 4,
        "seed": False,
    }
    cold = parse_poll_request(
        poll_request(
            notification_state={
                "generation": None,
                "revision": None,
                "seed": True,
            }
        )
    )
    assert cold.notification_state["seed"] is True


# @source lagniappe/core/tools/polling_contract.py::parse_poll_request
# @source lagniappe/core/tools/polling_contract.py::PollContractError
# @features polling
# @dimensions validation diagnostics strict-fields cursor-types bounds
@pytest.mark.parametrize(
    ("payload", "path", "reason"),
    [
        (None, "request", "type"),
        (
            {"version": 1, "client_id": "client", "subscriptions": []},
            "closed_documents",
            "missing",
        ),
        (
            poll_request(extra=True),
            "extra",
            "unexpected",
        ),
        (
            poll_request(version=True),
            "version",
            "type",
        ),
        (
            poll_request(client_id=" "),
            "client_id",
            "blank",
        ),
        (
            poll_request(subscriptions="invalid"),
            "subscriptions",
            "type",
        ),
        (
            poll_request(
                [
                    {"id": "same", "type": "entity", "key": "one", "revision": None},
                    {"id": "same", "type": "entity", "key": "two", "revision": None},
                ]
            ),
            "subscriptions[1].id",
            "duplicate",
        ),
        (
            poll_request(
                [
                    {
                        "id": "entity:one",
                        "type": "entity",
                        "key": "one",
                        "revision": "",
                    }
                ]
            ),
            "subscriptions[0].revision",
            "blank",
        ),
        (
            poll_request(
                [
                    {
                        "id": "operation:one",
                        "type": "operation",
                        "key": "one",
                        "revision": "0",
                    }
                ]
            ),
            "subscriptions[0].revision",
            "type",
        ),
        (
            poll_request(
                [
                    {
                        "id": "operation:one",
                        "type": "operation",
                        "key": "one",
                        "revision": MAX_POLL_REVISION + 1,
                    }
                ]
            ),
            "subscriptions[0].revision",
            "limit",
        ),
        (
            poll_request(
                [
                    {
                        "id": "document:one",
                        "type": "document",
                        "key": "one",
                        "sync_id": "one:document",
                        "generation": None,
                        "revision": False,
                        "presence_digest": None,
                    }
                ]
            ),
            "subscriptions[0].revision",
            "type",
        ),
        (
            poll_request(
                [
                    {
                        "id": "document:one",
                        "type": "document",
                        "key": "one",
                        "sync_id": "one:document",
                        "generation": None,
                        "revision": 0,
                    }
                ]
            ),
            "subscriptions[0].presence_digest",
            "missing",
        ),
        (
            poll_request(
                [
                    {
                        "id": "document:one",
                        "type": "document",
                        "key": "one",
                        "sync_id": "one:document",
                        "generation": None,
                        "revision": 0,
                        "presence_digest": None,
                        "fingerprint": "unused",
                    }
                ]
            ),
            "subscriptions[0].fingerprint",
            "unexpected",
        ),
        (
            poll_request(
                [
                    {
                        "id": "channel:retired",
                        "type": "channel",
                        "channel": "notifications",
                        "revision": None,
                    }
                ]
            ),
            "subscriptions[0].channel",
            "unsupported",
        ),
        (
            poll_request(
                [
                    {
                        "id": f"entity:{index}",
                        "type": "entity",
                        "key": str(index),
                        "revision": None,
                    }
                    for index in range(MAX_POLL_SUBSCRIPTIONS + 1)
                ]
            ),
            "subscriptions",
            "limit",
        ),
    ],
)
def test_poll_contract_reports_exact_invalid_field(payload, path, reason):
    with pytest.raises(PollContractError) as captured:
        parse_poll_request(payload)

    assert captured.value.path == path
    assert captured.value.reason == reason


# @source lagniappe/core/tools/polling_contract.py::parse_poll_request
# @features polling notifications
# @dimensions notification-state presence validation duplicates
@pytest.mark.parametrize(
    ("overrides", "path", "reason"),
    [
        (
            {
                "notification_state": {
                    "generation": None,
                    "revision": None,
                    "seed": False,
                }
            },
            "notification_state",
            "state",
        ),
        (
            {
                "notification_state": {
                    "generation": "warm",
                    "revision": 1,
                    "seed": True,
                }
            },
            "notification_state",
            "state",
        ),
        (
            {"closed_documents": ["same:document", "same:document"]},
            "closed_documents[1]",
            "duplicate",
        ),
        (
            {"closed_documents": ["form:not-a-document"]},
            "closed_documents[0]",
            "unsupported",
        ),
    ],
)
def test_poll_contract_rejects_invalid_notification_and_close_state(
    overrides, path, reason
):
    with pytest.raises(PollContractError) as captured:
        parse_poll_request(poll_request(**overrides))

    assert (captured.value.path, captured.value.reason) == (path, reason)
