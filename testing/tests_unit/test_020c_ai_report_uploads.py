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

# @features ai-report direct-upload
# @dimensions upload-manifest validation normalization
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




# @features ai-report direct-upload
# @dimensions upload-manifest background-finalization resume progress active-request
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
        upload_cleanup=lambda record: cleaned.append(record["filename"]),
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
    assert saved[0]["manifest"][1]["complete"] is True
    assert saved[0]["manifest"][1]["file_key"] == finalized[0].urlsafe_key
    assert saved[-1]["manifest"] is None
    assert report.upload_manifest is None
    assert report.summary is None
    assert len(active_checks) == 4




# @features ai-report direct-upload
# @dimensions upload-manifest background-finalization checkpoint-failure
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




# @pair ai-report:large-file
# @pair direct-upload:large-file
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
        upload_cleanup=lambda record: cleaned.append(record),
    )

    assert finalized == [file]
    assert report.input_files == [file]
    assert report.upload_manifest is None
    assert upload.lagniappe_preserve_source is True
    assert len(saves) == 2
    assert len(cleaned) == 1




# @features ai-report direct-upload
# @dimensions upload-manifest cleanup partial-progress
@pytest.mark.unit
def test_cleanup_report_upload_manifest_deletes_only_pending_uploads(monkeypatch):
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

    assert count == 1
    assert deleted == ["pending.pdf"]
