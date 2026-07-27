"""Durable direct-upload staging for AI report input files."""

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.definitions import (
    FileConsumer,
    FileConsumerLimitError,
    INDIVIDUAL_FILES_ONLY_ERROR,
    enforce_file_consumer,
)
from lagniappe.core.tools.database import assets as storage_assets


DIRECT_UPLOAD_RECORD_KEYS = (
    "token",
    "input_name",
    "filename",
    "content_type",
    "size",
    "generation",
    "path",
)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_prepare_report_upload_manifest_normalizes_browser_records
# @features ai-report direct-upload
# @dimensions upload-manifest validation normalization
def prepare_report_upload_manifest(records, input_name="tool-files"):
    """Return bounded signed-upload metadata safe to persist on a report."""
    manifest = []
    for record in records or []:
        if not isinstance(record, dict):
            raise exceptions.ValidationError(
                "One or more uploaded files could not be prepared."
            )

        token = record.get("token")
        filename = record.get("filename")
        record_input = record.get("input_name") or input_name
        if (
            not isinstance(token, str)
            or not token.strip()
            or not isinstance(filename, str)
            or not filename.strip()
            or record_input != input_name
        ):
            raise exceptions.ValidationError(
                "One or more uploaded files could not be prepared."
            )

        normalized = {
            key: record.get(key)
            for key in DIRECT_UPLOAD_RECORD_KEYS
            if record.get(key) is not None
        }
        normalized["token"] = token.strip()
        normalized["filename"] = filename.strip()
        normalized["input_name"] = input_name

        if "size" in normalized:
            try:
                normalized["size"] = int(normalized["size"])
            except (TypeError, ValueError) as error:
                raise exceptions.ValidationError(
                    "One or more uploaded files could not be prepared."
                ) from error
            if normalized["size"] == 0:
                raise exceptions.ValidationError(INDIVIDUAL_FILES_ONLY_ERROR)
            if normalized["size"] < 0:
                raise exceptions.ValidationError(
                    "One or more uploaded files could not be prepared."
                )
            try:
                enforce_file_consumer(
                    normalized["size"],
                    FileConsumer.AI_REPORT,
                    filename=normalized["filename"],
                )
            except FileConsumerLimitError as error:
                raise exceptions.ValidationError(str(error)) from error

        manifest.append(normalized)

    return manifest


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_finalize_report_upload_manifest_resumes_and_checkpoints
# @tests tests_unit/test_020_ai_reports.py::test_finalize_report_upload_manifest_retains_source_until_checkpoint
# @tests tests_unit/test_020_ai_reports.py::test_finalize_report_upload_manifest_accepts_actual_oversized_object
# @features ai-report direct-upload
# @dimensions upload-manifest background-finalization resume progress checkpoint-failure large-file active-request
def finalize_report_upload_manifest(
    report,
    user,
    *,
    save=None,
    upload_loader=None,
    file_factory=None,
    upload_cleanup=None,
    ensure_active=None,
):
    """Finalize staged uploads before removing their checkpointed sources."""
    manifest = list(report.upload_manifest or [])
    if not manifest:
        return []

    save = save or Entities.save
    upload_loader = upload_loader or storage_assets.direct_upload_file
    file_factory = file_factory or Entities.FILE.create
    upload_cleanup = upload_cleanup or storage_assets.delete_direct_upload
    input_files = list(report.input_files or [])
    attached = {file.urlsafe_key: file for file in input_files}
    total = len(manifest)
    prepared = 0
    finalized = []

    for record in manifest:
        if ensure_active:
            ensure_active()
        if not isinstance(record, dict):
            raise exceptions.ValidationError(
                "One or more uploaded files could not be prepared."
            )

        file_key = record.get("file_key")
        if record.get("complete") is True and file_key in attached:
            upload_cleanup(record)
            prepared += 1
            continue

        upload = upload_loader(record)
        try:
            enforce_file_consumer(
                upload,
                FileConsumer.AI_REPORT,
                filename=getattr(upload, "filename", record.get("filename")),
            )
        except FileConsumerLimitError as error:
            raise exceptions.ValidationError(str(error)) from error
        upload.lagniappe_preserve_source = True
        file = file_factory(
            upload=upload,
            data={
                "filename": upload.filename,
                "mimetype": upload.content_type,
            },
        )
        input_files.append(file)
        attached[file.urlsafe_key] = file
        report.input_files = input_files

        record["file_key"] = file.urlsafe_key
        record["complete"] = True
        prepared += 1
        report.upload_manifest = manifest
        report.summary = f"Preparing files ({prepared} of {total})..."
        if ensure_active:
            ensure_active()
        save(file, report, user)
        upload_cleanup(record)
        finalized.append(file)

    report.upload_manifest = None
    report.summary = None
    if ensure_active:
        ensure_active()
    save(report, user)
    return finalized


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_cleanup_report_upload_manifest_deletes_only_pending_uploads
# @features ai-report direct-upload
# @dimensions upload-manifest cleanup partial-progress
def cleanup_report_upload_manifest(report, delete_upload=None):
    """Delete temporary objects that were not finalized into File entities."""
    delete_upload = delete_upload or storage_assets.delete_direct_upload
    deleted = 0
    for record in report.upload_manifest or []:
        if not isinstance(record, dict) or record.get("complete") is True:
            continue
        if delete_upload(record):
            deleted += 1
    return deleted
