"""Report-history deletion scope, cleanup, and partial failure behavior."""

from types import SimpleNamespace

from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai import report_history
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user


# @matrix ai-report : delete file-cleanup guarded-delete
def test_report_delete_preserves_referenced_files_and_fences_cleanup(monkeypatch):
    orphan = SimpleNamespace(has_references=False)
    attached = SimpleNamespace(has_references=True)
    report = SimpleNamespace(
        origin="web",
        status="complete",
        deferred_job=None,
        input_files=[orphan, attached],
        upload_manifest=[{"token": "upload"}],
        db={"status": "complete"},
    )
    effects = []
    monkeypatch.setattr(
        report_history.DeferredJobs, "cancel", lambda job: effects.append("cancel")
    )
    monkeypatch.setattr(
        report_history.ai,
        "cleanup_report_upload_manifest",
        lambda report: effects.append("uploads"),
    )
    monkeypatch.setattr(Entities, "delete", lambda *entities: effects.append(entities))

    assert report_history.delete_report_record(report) == "committed"
    assert effects == ["cancel", "uploads", (report, orphan)]

    for outcome in ("busy", "stale", "missing", "committed"):
        effects.clear()

        def commit(current, snapshot, *entities):
            assert snapshot == {"status": "complete"}
            assert entities == (report, orphan)
            effects.append("fence")
            return outcome

        monkeypatch.setattr(
            report_history.external_operations, "delete_plan_if_idle", commit
        )
        assert report_history.delete_report_record(report, guarded=True) == outcome
        assert effects == (
            ["fence", "cancel", "uploads"] if outcome == "committed" else ["fence"]
        )

    report.origin = "api"
    report.deferred_job = {"key": "active-job"}
    effects.clear()
    assert report_history.delete_report_record(report) == "busy"
    assert effects == []


# @matrix ai-report : bulk-delete delete-snapshot ownership delete-failure
def test_bulk_delete_scopes_ownership_state_snapshot_and_partial_failures(monkeypatch):
    _patch_fake_keys(monkeypatch)
    owner, other = _test_user("history-owner"), _test_user("history-other")

    def report(tool="create", status="complete", user=owner, **extra):
        return Entities.REPORT.create(
            {"user": user, "tool": tool, "status": status, **extra}
        )

    rows = {
        "web": report(),
        "email": report("organize", origin="email"),
        "ask": report("ask"),
        "foreign": report(user=other),
        "ready": report(status="ready"),
        "failed": report(status="failed"),
        "undoing": report(status="undoing"),
        "undone": report(status="undone"),
        "pending": report(pending=True),
        "busy": report(origin="api"),
        "broken": report(),
        "after-snapshot": report(),
    }
    deleted, touched, errors = [], [], []
    monkeypatch.setattr(Entities, "fetch_one", lambda key, **kwargs: rows.get(key))
    monkeypatch.setattr(Entities, "touch", lambda user: touched.append(user))
    monkeypatch.setattr(
        report_history.exceptions,
        "capture",
        lambda error, **kwargs: errors.append(error),
    )

    def delete(item, *, guarded):
        assert guarded is True
        if item is rows["broken"]:
            raise RuntimeError("storage unavailable")
        if item is rows["busy"]:
            return "busy"
        deleted.append(item)
        return "committed"

    monkeypatch.setattr(report_history, "delete_report_record", delete)
    keys = [
        "broken",
        "web",
        "web",
        "email",
        "ask",
        "foreign",
        "ready",
        "failed",
        "undoing",
        "undone",
        "pending",
        "busy",
        "missing",
    ]
    result = report_history.delete_executed_reports(owner, keys)
    assert result == {
        "deleted": ["web", "email"],
        "skipped": [
            "ask",
            "foreign",
            "ready",
            "failed",
            "undoing",
            "undone",
            "pending",
            "busy",
            "missing",
        ],
        "failed": ["broken"],
    }
    assert deleted == [rows["web"], rows["email"]]
    assert touched == [owner]
    assert len(errors) == 1
    assert report_history.delete_executed_reports(owner, []) == {
        "deleted": [],
        "skipped": [],
        "failed": [],
    }
    assert touched == [owner]
