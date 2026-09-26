"""Early Task-list validation must fail closed on unknown or moving state."""

from types import SimpleNamespace

from google.cloud.datastore import Entity, Key
import pytest

from lagniappe.core.tools.polling import task_lists


pytestmark = pytest.mark.unit


# @matrix tasks cache : conditional-response durable-revision job-lifecycle
@pytest.mark.parametrize("change", [
    "quiet", "busy", "delivery", "missing-control", "old-schema", "missing-channel",
    "deferred-channel", "empty-channel", "missing-membership", "bad-generation",
])
def test_snapshot_requires_complete_quiet_durable_state(monkeypatch, change):
    rows = {}
    calls = []

    def key(kind, name):
        return Key(kind, name, project="unit-project")

    for channel in task_lists.CONTENT_CHANNELS:
        row = Entity(key("site", channel))
        row["fingerprint"] = channel + "-revision"
        rows[row.key] = row
    control = Entity(key(task_lists.KINDS.site.value, "deferred-jobs-control"))
    control.update(schema_version=2, tracked_jobs=[], active_jobs=0, desired_state="paused", generation=5)
    rows[control.key] = control
    if change in {"busy", "delivery"}:
        control.update(tracked_jobs=["operation"], active_jobs=1, desired_state="enabled")
    elif change == "missing-control":
        rows.pop(control.key)
    elif change == "old-schema":
        control["schema_version"] = 1
    elif change in {"missing-channel", "deferred-channel"}:
        rows.pop(key("site", "forms"))
    elif change == "empty-channel":
        rows[key("site", "forms")]["fingerprint"] = None
    elif change == "missing-membership":
        control.pop("tracked_jobs")
    elif change == "bad-generation":
        control["generation"] = "5"

    def get_multi(keys):
        calls.append(keys)
        return [rows[k] for k in keys if k in rows]

    monkeypatch.setattr(task_lists, "DATA", SimpleNamespace(datastore=SimpleNamespace(key=key, get_multi=get_multi)))
    snapshot = task_lists.quiet_snapshot()
    assert len(calls) == 1 and len(calls[0]) == 7
    if change != "quiet":
        assert snapshot is None
        return
    assert snapshot is not None
    control["generation"] += 2  # An entire operation happened between reads.
    assert task_lists.quiet_snapshot() != snapshot
    control["generation"] -= 2
    rows[key("site", "tasks")]["fingerprint"] = "changed-task"
    assert task_lists.quiet_snapshot() != snapshot


# @matrix tasks cache : conditional-response durable-revision job-lifecycle
@pytest.mark.parametrize("complete", [True, False])
def test_snapshot_reuses_supplied_records_without_reading(monkeypatch, complete):
    def key(kind, name):
        return Key(kind, name, project="unit-project")

    def forbidden_read(*args, **kwargs):
        pytest.fail("A supplied revision batch must not cause a second lookup")

    monkeypatch.setattr(task_lists, "DATA", SimpleNamespace(datastore=SimpleNamespace(key=key, get_multi=forbidden_read)))
    rows = {
        key("site", channel): {"fingerprint": channel + "-revision"}
        for channel in task_lists.CONTENT_CHANNELS
    }
    rows[key(task_lists.KINDS.site.value, "deferred-jobs-control")] = dict(
        schema_version=2, tracked_jobs=[], active_jobs=0, desired_state="paused", generation=5,
    )
    if not complete:
        rows = {}
    expected = ("categories-revision", "projects-revision", "pages-revision", "tasks-revision", "forms-revision", "users-revision", 5)
    assert task_lists.quiet_snapshot(rows) == (expected if complete else None)


# @matrix tasks cache : conditional-response viewer-scope concurrent-load
def test_validator_covers_viewer_and_preloaded_context():
    related = SimpleNamespace(urlsafe_key="form", fingerprint="form-before")
    page = SimpleNamespace(urlsafe_key="page", fingerprint="page-before", related_entities={"form": related})
    user = SimpleNamespace(urlsafe_key="viewer", fingerprint="user-before", page=page, related_entities={})
    before = task_lists.quiet_fingerprint(("revision", 1), page, user)
    assert before == task_lists.quiet_fingerprint(("revision", 1), page, user)
    related.fingerprint = "form-after"
    assert before != task_lists.quiet_fingerprint(("revision", 1), page, user)
    related.fingerprint = "form-before"
    user.urlsafe_key = "another-viewer"
    assert before != task_lists.quiet_fingerprint(("revision", 1), page, user)
    user.urlsafe_key = "viewer"
    assert before != task_lists.quiet_fingerprint(("revision", 2), page, user)


# @matrix tasks cache : conditional-response operation-retention form-migration
@pytest.mark.parametrize("dependency", ["none", "retained-job", "private-review", "migration"])
def test_operation_references_prevent_quiet_validator(dependency):
    task = SimpleNamespace(deferred_job=None, db={}, form=SimpleNamespace(db={}))
    if dependency == "retained-job":
        task.deferred_job = {"key": "already-terminal-job"}
    elif dependency == "private-review":
        task.db["autofill_reviews"] = '{"viewer":"operation"}'
    elif dependency == "migration":
        task.form.db["pending_form_change"] = "operation"
    assert task_lists.has_operation_dependencies([task]) is (dependency != "none")
