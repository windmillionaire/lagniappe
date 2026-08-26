"""Deferred-job adapters for the files domain."""

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
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai
from lagniappe.core.tools.files import extract as files

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDependencyFailedError,
    DeferredJobDriftError,
)


# @testable infrastructure
class FileAdapter(DeferredJobAdapter):
    notification_policy = "completion"

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_file_adapter_drift_tracks_the_original_asset
    # @matrix deferred-jobs file : authorization fingerprint metadata-isolation original-asset
    def authorization(self, spec):
        authorization = super().authorization(spec)
        file = spec.inputs.get("file")
        try:
            asset_fingerprint = file.get_asset("file").fingerprint
        except AttributeError:
            asset_fingerprint = None
        if asset_fingerprint:
            authorization.pop("fingerprints", None)
            authorization["file_asset_fingerprint"] = asset_fingerprint
        return authorization

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_file_adapter_drift_tracks_the_original_asset
    # @matrix deferred-jobs file : fingerprint metadata-isolation original-asset validation
    def validate_apply(self, context):
        expected = (context.job.authorization or {}).get("file_asset_fingerprint")
        if expected is None:
            return super().validate_apply(context)
        file = context.input("file")
        try:
            current = file.get_asset("file").fingerprint
        except AttributeError:
            current = None
        if current != expected:
            raise DeferredJobDriftError(
                "The original file changed while this operation was running."
            )

    # @testable infrastructure
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_ai_adapters_reject_restricted_actor_before_prepare
    def authorize(self, context):
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

    # @testable infrastructure
    def notification_target(self, context):
        file = context.input("file")
        return file if isinstance(file, Entities.FILE) else None


# @testable infrastructure
class FileExtractAdapter(FileAdapter):
    job_type = DeferredJobType.FILE_EXTRACT
    mutation_inputs = ("file",)

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_file_extract_adapter_checkpoints_and_applies_text_asset
    # @matrix file : extraction text-asset
    # @pair deferred-jobs:checkpoint
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
        file = context.input("file")
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

    # @testable infrastructure
    def inspect(self, context):
        file = Entities.fetch_one(
            context.input("file").urlsafe_key,
            request=Fetch.direct(),
        )
        if file is None:
            raise exceptions.ValidationError("Deferred file is missing.")
        context.inputs["file"] = file
        return (
            DeferredJobInspection.APPLIED
            if file.properties.extract.complete and file.get_asset("text")
            else DeferredJobInspection.NOT_APPLIED
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_file_extract_adapter_checkpoints_and_applies_text_asset
    # @matrix file : extraction text-asset
    # @pair deferred-jobs:checkpoint
    def apply(self, context):
        context.ensure_active()
        file = context.input("file")
        text_asset = context.checkpoint.get("text_asset")
        if not isinstance(text_asset, dict):
            raise exceptions.ValidationError(
                "Extracted text asset metadata is missing."
            )
        file.assets["text"] = deepcopy(text_asset)
        file.db["assets"] = json.dumps(file.assets)
        file.properties.extract.section = context.checkpoint["process"]
        file.save()
        return {"file_key": file.urlsafe_key, "complete": True}

    # @testable infrastructure
    def failure(self, context, error):
        file = context.input("file")
        if isinstance(file, Entities.FILE):
            file.properties.extract.error = str(error)
            file.save()

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        file = context.input("file")
        name = getattr(file, "name", "file")
        if succeeded:
            return f"Text extraction complete for {name}"
        return f"Text extraction failed for {name}. {str(error or '').strip()}".strip()


# @testable infrastructure
class FileSummarizeAdapter(FileAdapter):
    job_type = DeferredJobType.FILE_SUMMARIZE
    required_ai_access = AI.CREATE
    mutation_inputs = ("file",)

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_file_summary_expected_rejection_is_not_reported_twice
    # @matrix deferred-jobs file : expected-failure no-duplicate-capture summary
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.SUMMARIZING)
        file = context.input("file")
        summarize = ai.generate_summary(file, raise_quota=True, raise_errors=True)
        if not summarize.complete:
            raise DeferredJobDependencyFailedError(
                summarize.error or "File summary did not complete."
            )
        return {
            "summary": file.summary,
            "process": deepcopy(summarize.section),
        }

    # @testable infrastructure
    def inspect(self, context):
        file = Entities.fetch_one(
            context.input("file").urlsafe_key,
            request=Fetch.direct(),
        )
        if file is None:
            raise exceptions.ValidationError("Deferred file is missing.")
        context.inputs["file"] = file
        if (
            file.summary == context.checkpoint.get("summary")
            and file.properties.summarize.complete
        ):
            return DeferredJobInspection.APPLIED
        return DeferredJobInspection.NOT_APPLIED

    # @testable infrastructure
    def apply(self, context):
        context.ensure_active()
        file = context.input("file")
        file.summary = context.checkpoint.get("summary")
        file.properties.summarize.section = context.checkpoint["process"]
        file.save()
        return {"file_key": file.urlsafe_key}

    # @testable infrastructure
    def failure(self, context, error):
        file = context.input("file")
        if isinstance(file, Entities.FILE):
            file.properties.summarize.error = str(error)
            file.save()

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_file_summary_terminal_cleanup_starts_extraction_once
    # @matrix deferred-jobs file : extraction follow-up idempotency summary-first terminal
    def cleanup(self, context, *, terminal):
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

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        file = context.input("file")
        name = getattr(file, "name", "file")
        if succeeded:
            return f"File summary complete for {name}"
        return f"File summary failed for {name}. {str(error or '').strip()}".strip()
