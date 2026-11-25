"""Deferred-job adapters for the files domain."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from lagniappe.core.definitions.asset import AssetDefinition
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.definitions import DeferredJobSpec
    from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
    from collections.abc import Mapping

from ..context import required_input
from copy import deepcopy
import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai import summarize as ai_summarize
from lagniappe.core.tools.files import extract as files

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDependencyFailedError,
    DeferredJobDriftError,
)


class FileAdapter(DeferredJobAdapter):
    notification_policy = "completion"

    def authorization(self, spec: DeferredJobSpec) -> dict[str, object]:
        authorization = super().authorization(spec)
        file = spec.inputs.get("file")
        try:
            asset_fingerprint = file.get_asset("file").fingerprint if file is not None else None
        except AttributeError:
            asset_fingerprint = None
        if asset_fingerprint:
            authorization.pop("fingerprints", None)
            authorization["file_asset_fingerprint"] = asset_fingerprint
        return authorization

    def validate_apply(self, context: DeferredJobContext) -> None:
        expected = (context.job.authorization or {}).get("file_asset_fingerprint")
        if expected is None:
            return super().validate_apply(context)
        file = context.input("file")
        try:
            asset = file.get_asset("file") if file is not None else None
            current = asset.fingerprint if asset is not None else None
        except AttributeError:
            current = None
        if current != expected:
            raise DeferredJobDriftError(
                "The original file changed while this operation was running."
            )

    def authorize(self, context: DeferredJobContext) -> None:
        super().authorize(context)
        file = context.input("file")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred file user is invalid.")
        if not isinstance(file, Entities.FILE):
            raise exceptions.ValidationError("Deferred file is invalid.")
        if not file.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to process this file."
            )

    def notification_target(self, context: DeferredJobContext) -> Entity | None:
        file = context.input("file")
        return file if isinstance(file, Entities.FILE) else None


class FileExtractAdapter(FileAdapter):
    job_type = DeferredJobType.FILE_EXTRACT
    mutation_inputs = ("file",)

    def prepare(self, context: DeferredJobContext) -> Mapping[str, object] | None:
        context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
        file = required_input(context, "file")
        extract = files.ocr_file(file, raise_errors=True)
        if not extract.complete:
            raise exceptions.ValidationError(
                extract.error or "Text extraction did not complete."
            )
        text_asset = deepcopy(file.assets.get("text"))
        if not text_asset:
            raise exceptions.ValidationError(
                "Extracted text could not be attached to the file."
            )
        return {
            "process": deepcopy(extract.section),
            "text_asset": text_asset,
        }

    def inspect(self, context: DeferredJobContext) -> DeferredJobInspection:
        file = required_input(context, "file")
        if file is None:
            raise exceptions.ValidationError("Deferred file is missing.")
        return (
            DeferredJobInspection.APPLIED
            if file.properties.extract.complete and file.get_asset("text")
            else DeferredJobInspection.NOT_APPLIED
        )

    def apply(self, context: DeferredJobContext) -> Mapping[str, object] | None:
        context.ensure_active()
        file = required_input(context, "file")
        text_asset = context.checkpoint.get("text_asset")
        if not isinstance(text_asset, dict):
            raise exceptions.ValidationError(
                "Extracted text asset metadata is missing."
            )
        file.assets["text"] = deepcopy(cast("AssetDefinition", text_asset))
        file.db["assets"] = json.dumps(file.assets)
        file.properties.extract.section = context.checkpoint["process"]
        file.save()
        return {"file_key": file.urlsafe_key, "complete": True}

    def failure(self, context: DeferredJobContext, error: BaseException | str) -> None:
        file = context.input("file")
        if isinstance(file, Entities.FILE):
            file.properties.extract.error = str(error)
            file.save()

    def terminal_message(self, context: DeferredJobContext, *, succeeded: bool, error: BaseException | str | None = None) -> str:
        file = context.input("file")
        name = getattr(file, "name", "file")
        if succeeded:
            return f"Text extraction complete for {name}"
        return f"Text extraction failed for {name}. {str(error or '').strip()}".strip()


class FileSummarizeAdapter(FileAdapter):
    job_type = DeferredJobType.FILE_SUMMARIZE
    required_ai_access = AI.CREATE
    mutation_inputs = ("file",)

    def prepare(self, context: DeferredJobContext) -> Mapping[str, object] | None:
        context.set_phase(DeferredJobPhase.SUMMARIZING)
        file = required_input(context, "file")
        summarize = ai_summarize.generate_summary(file, raise_quota=True, raise_errors=True)
        if not summarize.complete:
            raise DeferredJobDependencyFailedError(
                summarize.error or "File summary did not complete."
            )
        return {
            "summary": file.summary,
            "process": deepcopy(summarize.section),
        }

    def inspect(self, context: DeferredJobContext) -> DeferredJobInspection:
        file = required_input(context, "file")
        if file is None:
            raise exceptions.ValidationError("Deferred file is missing.")
        if (
            file.summary == context.checkpoint.get("summary")
            and file.properties.summarize.complete
        ):
            return DeferredJobInspection.APPLIED
        return DeferredJobInspection.NOT_APPLIED

    def apply(self, context: DeferredJobContext) -> Mapping[str, object] | None:
        context.ensure_active()
        file = required_input(context, "file")
        file.summary = context.checkpoint.get("summary")
        file.properties.summarize.section = context.checkpoint["process"]
        file.save()
        return {"file_key": file.urlsafe_key}

    def failure(self, context: DeferredJobContext, error: BaseException | str) -> None:
        file = context.input("file")
        if isinstance(file, Entities.FILE):
            file.properties.summarize.error = str(error)
            file.save()

    def cleanup(self, context: DeferredJobContext, *, terminal: bool) -> None:
        if (
            not terminal
            or context.job.status
            not in {
                DeferredJobStatus.SUCCEEDED.value,
                DeferredJobStatus.FAILED.value,
            }
            or not context.parameters.get("extract_after_summary")
        ):
            return

        file = context.input("file")
        if not isinstance(file, Entities.FILE):
            return
        file.properties.extract.status = "Extracting text..."
        file.save()
        identity = hashlib.sha256(
            str(context.job.idempotency_key).encode("utf-8")
        ).hexdigest()
        files.start_file_extraction(
            file,
            actor=context.actor,
            idempotency_key=f"file-extract-follow-up:{identity}",
            delay_seconds=0,
        )
        context.parameters.pop("extract_after_summary", None)

    def terminal_message(self, context: DeferredJobContext, *, succeeded: bool, error: BaseException | str | None = None) -> str:
        file = context.input("file")
        name = getattr(file, "name", "file")
        if succeeded:
            return f"File summary complete for {name}"
        return f"File summary failed for {name}. {str(error or '').strip()}".strip()
