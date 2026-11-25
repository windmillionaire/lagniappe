"""Durable direct-upload staging for AI report input files."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.tools.database.assets import DirectUploadFile


from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.definitions import (
    FileConsumer,
    FileConsumerLimitError,
    INDIVIDUAL_FILES_ONLY_ERROR,
    MutationIntent,
    enforce_file_consumer,
)
from lagniappe.core.tools.database import assets as storage_assets


class SaveUploadProgress(Protocol):
    def __call__(self, *entities: Entity) -> object: ...


class FileFactory(Protocol):
    def __call__(self, *, upload: DirectUploadFile, data: dict[str, object]) -> models.File: ...


class FailedFileCleanup(Protocol):
    def __call__(
        self, *, file: models.File | None, upload: DirectUploadFile,
        error: BaseException, checkpoint_disposition: str,
    ) -> None: ...

DIRECT_UPLOAD_RECORD_KEYS = (
    "token",
    "input_name",
    "filename",
    "content_type",
    "size",
    "generation",
    "path",
)
CHECKPOINT_NOT_COMMITTED = "not_committed"
CHECKPOINT_AMBIGUOUS = "ambiguous"


def prepare_report_upload_manifest(
    records: Iterable[object] | None,
    input_name: str = "tool-files",
    *,
    upload_batch_id: str | None = None,
) -> list[dict[str, object]]:
    """Return bounded signed-upload metadata safe to persist on a report."""
    if upload_batch_id is not None and (
        not isinstance(upload_batch_id, str) or not upload_batch_id
    ):
        raise exceptions.ValidationError(
            "The upload batch identity could not be prepared."
        )
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
            key: value
            for key in DIRECT_UPLOAD_RECORD_KEYS
            if (value := record.get(key)) is not None
        }
        normalized["token"] = token.strip()
        normalized["filename"] = filename.strip()
        normalized["input_name"] = input_name
        if upload_batch_id is not None:
            normalized["upload_batch_id"] = upload_batch_id

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


def finalize_report_upload_manifest(
    report: models.AIReport,
    user: models.User,
    *,
    save: SaveUploadProgress | None = None,
    upload_loader: Callable[[dict[str, object]], DirectUploadFile] | None = None,
    file_factory: FileFactory | None = None,
    upload_cleanup: Callable[[dict[str, object]], bool] | None = None,
    failed_file_cleanup: FailedFileCleanup | None = None,
    ensure_active: Callable[[], None] | None = None,
) -> list[models.File]:
    """Finalize staged uploads before removing their checkpointed sources."""
    stored = report.upload_manifest
    if stored is not None and not isinstance(stored, list):
        raise exceptions.ValidationError("Report upload manifest is invalid.")
    manifest = list(stored or [])
    if not manifest:
        return []

    save = save or Entities.save
    upload_loader = upload_loader or storage_assets.direct_upload_file
    if file_factory is None:

        def create_report_file(*, upload, data):
            return Entities.FILE.create(
                upload=upload,
                data=data,
                report_user=user,
            )

        file_factory = create_report_file

    upload_cleanup = upload_cleanup or storage_assets.delete_direct_upload
    input_files = list(report.input_files or [])
    attached = {file.urlsafe_key: file for file in input_files}
    total = len(manifest)
    prepared = 0
    finalized = []

    def cleanup_source(record):
        if not upload_cleanup(record):
            raise exceptions.ValidationError(
                "Temporary upload cleanup did not complete. Retry finalization."
            )

    for record in manifest:
        if ensure_active:
            ensure_active()
        if not isinstance(record, dict):
            raise exceptions.ValidationError(
                "One or more uploaded files could not be prepared."
            )

        file_key = record.get("file_key")
        if record.get("complete") is True and file_key in attached:
            cleanup_source(record)
            prepared += 1
            continue

        upload = upload_loader(record)
        filename = getattr(upload, "filename", record.get("filename"))
        try:
            enforce_file_consumer(
                upload,
                FileConsumer.AI_REPORT,
                filename=filename if isinstance(filename, str) else None,
            )
        except FileConsumerLimitError as error:
            raise exceptions.ValidationError(str(error)) from error
        upload.lagniappe_preserve_source = True
        file = None
        checkpoint_started = False
        try:
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
            # Keep the caller's potentially old User snapshot out of this
            # checkpoint. An explicit intent preserves owner-list invalidation
            # as a modified-only update without reverting concurrent profile,
            # group, or permission changes.
            if hasattr(report, "add_mutation_intents"):
                report.add_mutation_intents(
                    MutationIntent.touch(
                        user,
                        reason="report-upload-owner-invalidation",
                    )
                )
            checkpoint_started = True
            save(file, report)
        except BaseException as error:
            if failed_file_cleanup:
                disposition = getattr(error, "checkpoint_disposition", None)
                if disposition not in {
                    CHECKPOINT_NOT_COMMITTED,
                    CHECKPOINT_AMBIGUOUS,
                }:
                    disposition = (
                        CHECKPOINT_AMBIGUOUS
                        if checkpoint_started
                        else CHECKPOINT_NOT_COMMITTED
                    )
                failed_file_cleanup(
                    file=file,
                    upload=upload,
                    error=error,
                    checkpoint_disposition=disposition,
                )
            raise
        cleanup_source(record)
        finalized.append(file)

    report.upload_manifest = None
    report.summary = None
    if ensure_active:
        ensure_active()
    if hasattr(report, "add_mutation_intents"):
        report.add_mutation_intents(
            MutationIntent.touch(
                user,
                reason="report-upload-owner-invalidation",
            )
        )
    save(report)
    return finalized


def cleanup_report_upload_manifest(
    report: models.AIReport,
    delete_upload: Callable[[dict[str, object]], bool] | None = None,
) -> int:
    """Delete every temporary source still represented by an upload manifest."""
    delete_upload = delete_upload or storage_assets.delete_direct_upload
    deleted = 0
    manifest = report.upload_manifest
    if not isinstance(manifest, list):
        return 0
    for record in manifest:
        if not isinstance(record, dict):
            continue
        if delete_upload(record):
            deleted += 1
    return deleted
