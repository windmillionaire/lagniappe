"""Focused AI-report characterization coverage."""

import copy
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import LARGE_ASSET_BYTES
from lagniappe.core.entities.ai_report import AIReport
from lagniappe.core.tools.ai.reporting import uploads as report_uploads
from testing.utility.ai_report_fakes import (
    _patch_fake_keys,
    _test_file,
    _test_user,
)

# @matrix ai-report direct-upload : normalization upload-manifest validation
@pytest.mark.unit
def test_prepare_report_upload_manifest_normalizes_browser_records():
    manifest = report_uploads.prepare_report_upload_manifest(
        [
            {
                "token": " signed-token ",
                "input_name": "tool-files",
                "filename": " scan.pdf ",
                "content_type": "application/pdf",
                "size": "42",
                "generation": "7",
                "path": "tmp/uploads/scan.pdf",
                "complete": True,
                "file_key": "untrusted-file",
                "unexpected": "discarded",
            }
        ]
    )

    assert manifest == [
        {
            "token": "signed-token",
            "input_name": "tool-files",
            "filename": "scan.pdf",
            "content_type": "application/pdf",
            "size": 42,
            "generation": "7",
            "path": "tmp/uploads/scan.pdf",
        }
    ]

    with pytest.raises(exceptions.ValidationError, match="could not be prepared"):
        report_uploads.prepare_report_upload_manifest(
            [
                {
                    "token": "signed-token",
                    "input_name": "another-input",
                    "filename": "scan.pdf",
                }
            ]
        )

    with pytest.raises(
        exceptions.ValidationError,
        match="Only individual files are supported",
    ):
        report_uploads.prepare_report_upload_manifest(
            [
                {
                    "token": "signed-token",
                    "input_name": "tool-files",
                    "filename": "folder",
                    "size": 0,
                }
            ]
        )

    assert report_uploads.prepare_report_upload_manifest(
        [
            {
                "token": "signed-token",
                "input_name": "tool-files",
                "filename": "oversized.pdf",
                "size": LARGE_ASSET_BYTES + 1,
            }
        ]
    ) == [
        {
            "token": "signed-token",
            "input_name": "tool-files",
            "filename": "oversized.pdf",
            "size": LARGE_ASSET_BYTES + 1,
        }
    ]




# @matrix ai-report direct-upload : active-request background-finalization progress resume upload-manifest
@pytest.mark.unit
def test_finalize_report_upload_manifest_resumes_and_checkpoints(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("upload-finalizer-owner")
    existing = _test_file("first.pdf")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Staged upload report",
            "input_files": [existing],
            "upload_manifest": [
                {
                    "token": "first-token",
                    "input_name": "tool-files",
                    "filename": "first.pdf",
                    "complete": True,
                    "file_key": existing.urlsafe_key,
                },
                {
                    "token": "second-token",
                    "input_name": "tool-files",
                    "filename": "second.pdf",
                },
            ],
        }
    )
    loaded = []
    cleaned = []
    saved = []
    active_checks = []

    def load_upload(record):
        loaded.append(record["filename"])
        return SimpleNamespace(
            filename=record["filename"],
            content_type="application/pdf",
            size=1024,
        )

    def create_file(*, upload, data):
        assert data == {
            "filename": upload.filename,
            "mimetype": "application/pdf",
        }
        return _test_file(upload.filename)

    def save_entities(*entities):
        saved.append(
            {
                "entities": entities,
                "summary": report.summary,
                "manifest": copy.deepcopy(report.upload_manifest),
            }
        )

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        user,
        save=save_entities,
        upload_loader=load_upload,
        file_factory=create_file,
        upload_cleanup=lambda record: cleaned.append(record["filename"]) or True,
        ensure_active=lambda: active_checks.append(True),
    )

    assert loaded == ["second.pdf"]
    assert cleaned == ["first.pdf", "second.pdf"]
    assert [file.filename for file in finalized] == ["second.pdf"]
    assert [file.filename for file in report.input_files] == [
        "first.pdf",
        "second.pdf",
    ]
    assert saved[0]["summary"] == "Preparing files (2 of 2)..."
    assert saved[0]["entities"] == (finalized[0], report)
    assert saved[0]["manifest"][1]["complete"] is True
    assert saved[0]["manifest"][1]["file_key"] == finalized[0].urlsafe_key
    assert saved[-1]["manifest"] is None
    assert saved[-1]["entities"] == (report,)
    assert report.upload_manifest is None
    assert report.summary is None
    assert len(active_checks) == 4




# @matrix ai-report direct-upload : background-finalization checkpoint-failure upload-manifest
@pytest.mark.unit
def test_finalize_report_upload_manifest_retains_source_until_checkpoint(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("upload-finalizer-retry-owner")
    original_manifest = [
        {
            "token": "signed-token",
            "input_name": "tool-files",
            "filename": "retry.pdf",
        }
    ]
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Interrupted staged upload report",
            "upload_manifest": copy.deepcopy(original_manifest),
        }
    )
    source_available = True
    events = []

    def load_upload(record):
        assert source_available
        events.append("load-source")
        return SimpleNamespace(
            filename=record["filename"],
            content_type="application/pdf",
            size=1024,
        )

    def create_file(*, upload, data):
        assert upload.lagniappe_preserve_source is True
        events.append("copy-source")
        return _test_file(data["filename"])

    def interrupted_save(*entities):
        events.append("checkpoint-failed")
        raise RuntimeError("worker interrupted before checkpoint")

    def cleanup_upload(record):
        nonlocal source_available
        events.append("delete-source")
        source_available = False
        return True

    with pytest.raises(RuntimeError, match="interrupted before checkpoint"):
        report_uploads.finalize_report_upload_manifest(
            report,
            user,
            save=interrupted_save,
            upload_loader=load_upload,
            file_factory=create_file,
            upload_cleanup=cleanup_upload,
        )

    assert source_available is True
    assert events == ["load-source", "copy-source", "checkpoint-failed"]

    # A Cloud Tasks retry reloads the last persisted report state.
    report.input_files = []
    report.upload_manifest = copy.deepcopy(original_manifest)
    report.summary = None
    events.clear()

    def save_entities(*entities):
        events.append("checkpoint-saved")

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        user,
        save=save_entities,
        upload_loader=load_upload,
        file_factory=create_file,
        upload_cleanup=cleanup_upload,
    )

    assert [file.filename for file in finalized] == ["retry.pdf"]
    assert source_available is False
    assert events == [
        "load-source",
        "copy-source",
        "checkpoint-saved",
        "delete-source",
        "checkpoint-saved",
    ]
    assert report.upload_manifest is None


# @matrix ai-report direct-upload : checkpoint-failure generation-cleanup lease-renewal
# @source lagniappe/core/tools/ai/reporting/uploads.py::finalize_report_upload_manifest
@pytest.mark.unit
def test_finalize_report_upload_manifest_cleans_copied_file_after_definite_lease_loss():
    user = SimpleNamespace()
    report = SimpleNamespace(
        upload_manifest=[{"token": "signed", "filename": "lost.pdf"}],
        input_files=[],
        summary=None,
    )
    upload = SimpleNamespace(
        filename="lost.pdf",
        content_type="application/pdf",
        size=1024,
    )
    file = SimpleNamespace(filename="lost.pdf", urlsafe_key="lost-file")
    active_checks = 0
    events = []

    def ensure_active():
        nonlocal active_checks
        active_checks += 1
        if active_checks == 2:
            raise RuntimeError("lease was replaced")

    with pytest.raises(RuntimeError, match="lease was replaced"):
        report_uploads.finalize_report_upload_manifest(
            report,
            user,
            save=lambda *_entities: pytest.fail("checkpoint must not run"),
            upload_loader=lambda _record: upload,
            file_factory=lambda **_kwargs: file,
            upload_cleanup=lambda _record: events.append("delete-source") or True,
            failed_file_cleanup=lambda **failure: events.append(failure),
            ensure_active=ensure_active,
        )

    assert len(events) == 1
    assert events[0]["file"] is file
    assert events[0]["upload"] is upload
    assert str(events[0]["error"]) == "lease was replaced"
    assert events[0]["checkpoint_disposition"] == (
        report_uploads.CHECKPOINT_NOT_COMMITTED
    )


# @matrix ai-report direct-upload : factory-failure generation-cleanup
# @source lagniappe/core/tools/ai/reporting/uploads.py::finalize_report_upload_manifest
@pytest.mark.unit
def test_finalize_report_upload_manifest_owns_cleanup_when_file_factory_fails():
    report = SimpleNamespace(
        upload_manifest=[{"token": "signed", "filename": "factory.pdf"}],
        input_files=[],
        summary=None,
    )
    upload = SimpleNamespace(
        filename="factory.pdf",
        content_type="application/pdf",
        size=1024,
        lagniappe_saved_destination={
            "path": "factory_attempt.pdf",
            "visibility": "private",
            "generation": "19",
        },
    )
    failures = []

    with pytest.raises(RuntimeError, match="factory failed after copy"):
        report_uploads.finalize_report_upload_manifest(
            report,
            SimpleNamespace(),
            save=lambda *_entities: pytest.fail("checkpoint must not run"),
            upload_loader=lambda _record: upload,
            file_factory=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("factory failed after copy")
            ),
            upload_cleanup=lambda _record: pytest.fail(
                "temporary source must remain"
            ),
            failed_file_cleanup=lambda **failure: failures.append(failure),
        )

    assert len(failures) == 1
    assert failures[0]["file"] is None
    assert failures[0]["upload"] is upload
    assert failures[0]["checkpoint_disposition"] == (
        report_uploads.CHECKPOINT_NOT_COMMITTED
    )


# @matrix ai-report direct-upload : cleanup partial-progress retry
# @source lagniappe/core/tools/ai/reporting/uploads.py::finalize_report_upload_manifest
@pytest.mark.unit
def test_finalize_report_upload_manifest_retains_checkpoint_when_source_cleanup_fails():
    report = SimpleNamespace(
        upload_manifest=[{"token": "signed", "filename": "cleanup.pdf"}],
        input_files=[],
        summary=None,
    )
    upload = SimpleNamespace(
        filename="cleanup.pdf",
        content_type="application/pdf",
        size=1024,
    )
    file = SimpleNamespace(filename="cleanup.pdf", urlsafe_key="cleanup-file")
    saved = []

    with pytest.raises(exceptions.ValidationError, match="Retry finalization"):
        report_uploads.finalize_report_upload_manifest(
            report,
            SimpleNamespace(),
            save=lambda *_entities: saved.append(copy.deepcopy(report.upload_manifest)),
            upload_loader=lambda _record: upload,
            file_factory=lambda **_kwargs: file,
            upload_cleanup=lambda _record: False,
        )

    assert len(saved) == 1
    assert saved[0][0]["complete"] is True
    assert saved[0][0]["file_key"] == "cleanup-file"
    assert report.upload_manifest[0]["complete"] is True




# @matrix ai-report direct-upload : large-file
@pytest.mark.unit
def test_finalize_report_upload_manifest_accepts_actual_oversized_object():
    report = SimpleNamespace(
        upload_manifest=[{"token": "signed", "filename": "oversized.pdf"}],
        input_files=[],
    )
    upload = SimpleNamespace(
        filename="oversized.pdf",
        content_type="application/pdf",
        size=LARGE_ASSET_BYTES + 1,
    )
    file = SimpleNamespace(
        filename="oversized.pdf",
        urlsafe_key="oversized-file",
    )
    saves = []
    cleaned = []

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        SimpleNamespace(),
        save=lambda *entities: saves.append(entities),
        upload_loader=lambda _record: upload,
        file_factory=lambda **_kwargs: file,
        upload_cleanup=lambda record: cleaned.append(record) or True,
    )

    assert finalized == [file]
    assert report.input_files == [file]
    assert report.upload_manifest is None
    assert upload.lagniappe_preserve_source is True
    assert len(saves) == 2
    assert len(cleaned) == 1


# @matrix ai-report direct-upload : pre-execution upload-manifest
@pytest.mark.unit
def test_finalize_report_upload_manifest_marks_default_files_as_report_only(monkeypatch):
    user = _test_user("default-upload-owner")
    report = SimpleNamespace(
        upload_manifest=[{"token": "signed", "filename": "evidence.pdf"}],
        input_files=[],
        summary=None,
    )
    upload = SimpleNamespace(
        filename="evidence.pdf",
        content_type="application/pdf",
        size=1024,
    )
    created = []

    def create_file(**options):
        created.append(options)
        return SimpleNamespace(
            filename=options["data"]["filename"],
            urlsafe_key="staged-evidence-file",
        )

    monkeypatch.setattr(report_uploads.Entities.FILE, "create", create_file)

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        user,
        save=lambda *_entities: None,
        upload_loader=lambda _record: upload,
        upload_cleanup=lambda _record: True,
    )

    assert finalized == report.input_files
    assert created[0]["report_user"] is user




# @matrix ai-report direct-upload : cleanup partial-progress upload-manifest
@pytest.mark.unit
def test_cleanup_report_upload_manifest_deletes_all_temporary_sources(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("upload-cleanup-owner")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Upload cleanup report",
            "upload_manifest": [
                {"token": "complete", "filename": "complete.pdf", "complete": True},
                {"token": "pending", "filename": "pending.pdf"},
            ],
        }
    )
    deleted = []

    count = report_uploads.cleanup_report_upload_manifest(
        report,
        delete_upload=lambda record: deleted.append(record["filename"]) or True,
    )

    assert count == 2
    assert deleted == ["complete.pdf", "pending.pdf"]
