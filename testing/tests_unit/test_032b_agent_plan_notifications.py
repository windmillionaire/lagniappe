"""Atomic external Plan publication and replayable notification delivery."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
import pytest

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import agent_api as plan_database
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import notifications as notification_database
from lagniappe.core.tools.email.notifications import capture as email_capture
from lagniappe.core.tools.notifications import service as notification_service
from testing.utility.messaging_fakes import MemoryDatastore, managed_user
from testing.utility.notification_email_fakes import task_recorder, user_row


pytestmark = pytest.mark.unit


class AtomicDatastore(MemoryDatastore):
    """Isolate reads and stage writes so a failed commit rolls everything back."""

    fail_commit = False

    def key(self, kind, identifier=None, parent=None):
        return Key(kind, identifier, parent=parent, project=parent.project if parent else "messaging-test")

    def get(self, key, transaction=None):
        return deepcopy((transaction.rows if transaction else self.rows).get(key))

    def transaction(self):
        store = self

        class Transaction:
            def __enter__(self):
                self.rows = deepcopy(store.rows)
                return self

            def __exit__(self, error_type, *_args):
                if error_type is None:
                    if store.fail_commit:
                        store.fail_commit = False
                        raise RuntimeError("commit interrupted")
                    store.rows = self.rows
                return False

            def put(self, row):
                self.rows[row.key] = deepcopy(row)

            def delete(self, key):
                self.rows.pop(key, None)

        return Transaction()


@pytest.fixture
def publication_store(monkeypatch):
    store = AtomicDatastore()
    monkeypatch.setattr(plan_database.DATA, "_datastore_client", store)
    monkeypatch.setattr(
        plan_database.database_utility, "update_site_fingerprints", lambda *_rows: []
    )
    return store


# @pairs agent-api:atomic-checkpoint agent-api:creator-bound agent-api:ready-state notifications:idempotency notifications:ordinary-count
@pytest.mark.parametrize("tool", ["ask", "create", "organize"])
def test_publication_notification_commits_with_plan_and_survives_replay(publication_store, tool):
    store = publication_store
    user = managed_user("creator", "Creator")
    now = datetime.now(timezone.utc)
    row = DatastoreEntity(key=store.key("activity", "plan", parent=user.key))
    row.update({
        "type": "report", "origin": "api", "tool": tool,
        "user": user.key, "parent": user.key,
        "agent_manifest": json.dumps({"source": "remote_mcp"}),
        "process": json.dumps({"report": {"status": "draft"}}),
    })
    store.put(row)
    aggregate_key = notification_database.aggregate_key(user)
    store.put(notification_database.new_aggregate(aggregate_key))
    claim = DatastoreEntity(key=plan_database.plan_operation_claim_key(row.key))
    claim.update({
        "phase": "submit", "operation_id": "submit-aaaaaaaaaaaaaaaa",
        "claim_token": "a" * 32, "expires_at": now + timedelta(minutes=5),
    })
    store.put(claim)
    expected = dict(row)
    published = deepcopy(row)
    published["process"] = json.dumps({
        "report": {"status": "complete" if tool == "ask" else "ready"}
    })
    report = Entities.REPORT(published)
    options = {
        "phase": "submit", "operation_id": claim["operation_id"],
        "claim_token": claim["claim_token"], "expected_report": expected,
        "writes": [(report, None)], "notification_user": user, "now": now,
    }

    with pytest.raises(ValueError, match="creator"):
        plan_database.commit_plan_operation(
            row.key, **{**options, "notification_user": managed_user("other", "Other")}
        )
    # A replacement claim fences the alert as well as the proposal.
    assert plan_database.commit_plan_operation(
        row.key, **{**options, "claim_token": "b" * 32}
    ) == plan_database.PLAN_OPERATION_LOST
    assert "publication_notification" not in report.agent_manifest
    assert store.get(aggregate_key)["ordinary_count"] == 0

    store.fail_commit = True
    with pytest.raises(RuntimeError, match="commit interrupted"):
        plan_database.commit_plan_operation(row.key, **options)
    assert store.get(row.key) == expected
    assert "publication_notification" not in report.agent_manifest
    assert store.get(aggregate_key)["ordinary_count"] == 0
    assert len(store.rows) == 3  # Draft, claim, and aggregate; no partial alert.

    assert plan_database.commit_plan_operation(row.key, **options) == "committed"
    marker = report.agent_manifest["publication_notification"]
    notification_key = database_get.datastore_key(marker)
    notification = store.get(notification_key)
    assert notification["parent"] == user.key
    assert notification["target"] == report.key
    assert notification["body"] == f"{tool.title()} report is ready."
    assert notification["pending"] is False
    assert store.get(aggregate_key)["ordinary_count"] == 1
    assert json.loads(store.get(row.key)["agent_manifest"])["publication_notification"] == marker
    assert dict(report.db) == dict(store.get(row.key))

    # A retry after an ambiguous commit cannot write an older report snapshot.
    assert plan_database.commit_plan_operation(row.key, **options) == "stale"
    assert store.get(aggregate_key)["ordinary_count"] == 1
    for dismissed in (False, True):
        if dismissed:
            assert notification_database.delete_ordinary_notification_record(user, notification_key)[0]
        expected_revision = dict(store.get(row.key))
        revised = Entities.REPORT(deepcopy(store.get(row.key)))
        revised.instructions = "Revised plan"
        assert plan_database.commit_plan_operation(row.key, **{
            **options, "expected_report": expected_revision, "writes": [(revised, None)]
        }) == "committed"
        assert revised.agent_manifest["publication_notification"] == marker
        assert store.get(aggregate_key)["ordinary_count"] == (0 if dismissed else 1)
        assert (store.get(notification_key) is None) is dismissed


# @matrix agent-api notifications : cache-failure-isolation idempotency target
def test_publication_delivery_retries_cache_and_email_without_recreating_dismissed_alerts(
    publication_store, monkeypatch
):
    store = publication_store
    now = datetime.now(timezone.utc)
    user = user_row("creator", now)
    report_row = DatastoreEntity(key=store.key("activity", "plan"))
    report_row.update({"type": "report", "tool": "create", "name": "Published plan"})
    report = Entities.REPORT(report_row)
    key = notification_database.ordinary_notification_key(user, "published-plan")
    row = notification_database.prepare_ordinary_notification(
        key, user, body="Create report is ready.", target=report
    )
    store.put(row)
    store.put(notification_database.new_aggregate(
        notification_database.aggregate_key(user), ordinary_count=1
    ))
    report.agent_manifest = {"publication_notification": database_get.urlsafe_key(key)}
    scheduled = task_recorder(monkeypatch)
    projected = []
    captured = []
    monkeypatch.setattr(exceptions, "capture", lambda error, **kwargs: captured.append(kwargs))

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Redis unavailable")

    monkeypatch.setattr(cache, "update_notification_projection", unavailable)
    real_capture = email_capture.record_notification
    monkeypatch.setattr(email_capture, "record_notification", unavailable)
    notification_service.publish_plan_notification(report, user)
    assert [item["context"]["operation"] for item in captured] == [
        "plan-notification-projection", "plan-notification-email"
    ]
    assert store.get(key) is not None
    assert scheduled == []

    monkeypatch.setattr(cache, "update_notification_projection", lambda **kwargs: projected.append(kwargs))
    monkeypatch.setattr(email_capture, "record_notification", real_capture)
    notification_service.publish_plan_notification(report, user)
    notification_service.publish_plan_notification(report, user)
    assert len(projected) == 2
    assert all(item["aggregates"][user.urlsafe_key]["ordinary_count"] == 1 for item in projected)
    assert all(item["upserts"][0].target is report for item in projected)
    events = [row for row in store.rows.values() if row.get("record_type") == "event"]
    assert len(events) == 1
    assert events[0]["target_path"] == f"/tools/reports/{report.urlsafe_key}"
    assert events[0]["occurred_at"] == row["created"]
    assert scheduled
    previous_tasks = len(scheduled)
    assert notification_database.delete_ordinary_notification_record(user, key)[0]
    notification_service.publish_plan_notification(report, user)
    assert len(projected) == 2
    assert len(scheduled) == previous_tasks
    assert store.get(key) is None
