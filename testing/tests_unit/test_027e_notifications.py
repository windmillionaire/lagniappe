"""Durable ordinary-notification aggregate contracts."""

from types import SimpleNamespace

from google.api_core import exceptions as google_exceptions
import pytest

from lagniappe.core import exceptions as core_exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import notifications as notification_database
from lagniappe.core.tools.database import transactions
from lagniappe.core.tools.email.notifications import capture as email_capture
from lagniappe.core.tools.notifications import service as notification_service
from testing.utility.messaging_fakes import MemoryDatastore, managed_user


pytestmark = pytest.mark.unit


def test_ordinary_notification_service_mutates_aggregate_once(monkeypatch):
    store = MemoryDatastore()
    monkeypatch.setattr(notification_database.DATA, "_datastore_client", store)
    user = managed_user("notice-user", "Notice User")
    aggregate = notification_database.new_aggregate(
        notification_database.aggregate_key(user)
    )
    store.put(aggregate)
    monkeypatch.setattr(Entities, "fetch_one", lambda row, request: row)
    email_attempts = []
    email_errors = []

    def fail_email_capture(*args, **kwargs):
        email_attempts.append((args, kwargs))
        raise RuntimeError("email capture unavailable")

    monkeypatch.setattr(email_capture, "record_notification_event", fail_email_capture)
    monkeypatch.setattr(
        core_exceptions,
        "capture",
        lambda *args, **kwargs: email_errors.append((args, kwargs)),
    )

    first, created = notification_service.create_ordinary_notification(
        user,
        identifier="notice-one",
        body="<em>First</em>",
    )
    replay, replay_created = notification_service.create_ordinary_notification(
        user,
        identifier="notice-one",
        body="<em>First</em>",
    )
    assert created is True
    assert replay_created is False
    assert replay.key == first.key
    assert first["body"] == "First"
    assert aggregate["ordinary_count"] == 1
    assert len(email_attempts) == 1
    assert email_errors[0][1]["context"] == {
        "operation": "notification-email-capture"
    }

    second, _created = notification_service.create_ordinary_notification(
        user,
        identifier="notice-two",
        body="Second",
    )
    assert aggregate["ordinary_count"] == 2
    assert notification_service.delete_ordinary_notification(user, first.key)
    assert aggregate["ordinary_count"] == 1
    assert notification_service.clear_ordinary_notifications(user, [second.key]) == 1
    assert aggregate["ordinary_count"] == 0

    mutation = SimpleNamespace(
        parent=user,
        notification_type="ordinary",
        _notification_count_delta=1,
    )
    projected = notification_service.apply_ordinary_mutations(upserts=[mutation])
    assert projected[user.urlsafe_key]["ordinary_count"] == 1
    revision = projected[user.urlsafe_key]["aggregate_revision"]
    mutation._notification_count_delta = 0
    projected = notification_service.apply_ordinary_mutations(upserts=[mutation])
    assert projected[user.urlsafe_key]["ordinary_count"] == 1
    assert projected[user.urlsafe_key]["aggregate_revision"] == revision + 1
    assert projected[user.urlsafe_key]["message_revision"] == 0

    repair_user = managed_user("repair-user", "Repair User")
    repaired = notification_database.repair_notification_aggregate(
        repair_user, ordinary_count=2
    )
    assert repaired["ordinary_count"] == 2
    assert notification_database.ensure_notification_aggregate(repair_user) is repaired

    attempts = []
    monkeypatch.setattr(transactions.time, "sleep", lambda delay: attempts.append(delay))

    @transactions.retry_aborted
    def contended():
        if len(attempts) < 2:
            raise google_exceptions.Aborted("retry")
        return "done"

    assert contended() == "done"
    assert attempts == [0.05, 0.1]

    captured = []
    monkeypatch.setattr(
        core_exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    from lagniappe.core.tools import cache as notification_cache

    monkeypatch.setattr(
        notification_cache,
        "publish_notification_aggregate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
    )
    notification_service.publish_notification_aggregate(user, aggregate)
    assert captured and captured[0][1]["context"] == {
        "operation": "notification-aggregate-publish"
    }


@pytest.mark.parametrize("clear", [False, True], ids=["dismiss-one", "clear-all"])
def test_dismissal_publishes_committed_counts_and_refreshes_on_noop(monkeypatch, clear):
    from unittest.mock import Mock

    user = managed_user("notice-user", "Notice User")
    committed = {"ordinary_count": 0}
    recent = {"ordinary_count": 2}
    mutation = Mock(side_effect=[(1 if clear else True, committed), (0 if clear else False, None)])
    lookup = Mock(return_value=recent)
    publish = Mock()
    monkeypatch.setattr(notification_database, "get_notification_aggregate", lookup)
    monkeypatch.setattr(notification_service, "publish_notification_aggregate", publish)
    if clear:
        monkeypatch.setattr(notification_database, "clear_ordinary_notification_records", mutation)
        dismiss, target = notification_service.clear_ordinary_notifications, [user.key]
    else:
        monkeypatch.setattr(notification_database, "delete_ordinary_notification_record", mutation)
        dismiss, target = notification_service.delete_ordinary_notification, user.key

    assert dismiss(user, target)
    publish.assert_called_once_with(user, committed)
    lookup.assert_not_called()
    assert not dismiss(user, target)
    lookup.assert_called_once_with(user)
    publish.assert_called_with(user, recent)
