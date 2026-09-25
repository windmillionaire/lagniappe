"""External API uploads."""

import re
import uuid
from copy import deepcopy

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import (
    agent_api as agent_api_store,
    assets as storage_assets,
    get as database_get,
)

from . import definitions
from ..external_operations import (
    ExternalPlanError,
    claimed_plan_save,
    raise_plan_operation_error,
    release_plan_operation_claim,
)
from ..reporting.uploads import (
    CHECKPOINT_NOT_COMMITTED,
    finalize_report_upload_manifest,
    prepare_report_upload_manifest,
)
from .definitions import MAX_PLAN_FILES
from .plans import load_plan, require_draft, require_plan_access


_UPLOAD_BATCH_PATTERN = re.compile(definitions.UPLOAD_BATCH_ID_PATTERN)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_upload_batch_identity_is_preserved_in_every_record
# @matrix agent-api ai-report : upload-batch-identity upload-manifest
def prepare_upload_manifest(records, *, upload_batch_id):
    """Normalize an external upload batch with one server-issued identity."""
    return prepare_report_upload_manifest(
        records,
        input_name=definitions.UPLOAD_INPUT_NAME,
        upload_batch_id=upload_batch_id,
    )


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_upload_file_identity_is_deterministic_per_batch_record
# @matrix agent-api ai-report mcp-upload : deterministic-file-identity upload-manifest
def bind_upload_file_identities(report, manifest, *, upload_batch_id):
    """Bind each external upload record to one deterministic future File key."""
    if not isinstance(manifest, list) or len(manifest) > MAX_PLAN_FILES:
        raise exceptions.ValidationError("The upload manifest is invalid.")
    result = deepcopy(manifest)
    for index, record in enumerate(result):
        if (
            not isinstance(record, dict)
            or record.get("upload_batch_id") != upload_batch_id
        ):
            raise exceptions.ValidationError("The upload manifest is invalid.")
        try:
            key = agent_api_store.upload_file_key(
                report.key,
                upload_batch_id,
                index,
            )
            identity = database_get.urlsafe_key(key)
        except (TypeError, ValueError) as error:
            raise exceptions.ValidationError(
                "The upload manifest identity is invalid."
            ) from error
        if not isinstance(identity, str) or not identity:
            raise exceptions.ValidationError("The upload manifest identity is invalid.")
        stored_index = record.get("file_index")
        stored_identity = record.get("file_key")
        if stored_index is not None and stored_index != index:
            raise exceptions.ValidationError("The upload manifest identity is invalid.")
        if stored_identity is not None and stored_identity != identity:
            raise exceptions.ValidationError("The upload manifest identity is invalid.")
        record["file_index"] = index
        record["file_key"] = identity
    return result


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_upload_finalization_binds_report_user
# @matrix agent-api ai-report mcp-upload : deterministic-file-identity lease-renewal temporary-view-ownership upload-finalization
def finalize_uploads(
    report,
    user,
    *,
    asset_nonce=None,
    ensure_active=None,
    save=None,
):
    """Finalize external uploads and make draft files visible to their submitter."""

    manifest = list(report.upload_manifest or [])
    batch_ids = {
        record.get("upload_batch_id") for record in manifest if isinstance(record, dict)
    }
    if len(batch_ids) != 1:
        raise exceptions.ValidationError("The upload manifest identity is invalid.")
    upload_batch_id = next(iter(batch_ids))
    report.upload_manifest = bind_upload_file_identities(
        report,
        manifest,
        upload_batch_id=upload_batch_id,
    )

    # @testable false
    # @covered-by lagniappe/core/tools/ai/external/uploads.py::finalize_uploads
    # @reason callback binds report ownership inside the public finalizer
    def create_file(*, upload, data):
        record = getattr(upload, "record", None)
        if not isinstance(record, dict):
            raise exceptions.ValidationError("The upload manifest identity is invalid.")
        file_key = database_get.datastore_key(record.get("file_key"))
        expected_key = agent_api_store.upload_file_key(
            report.key,
            record.get("upload_batch_id"),
            record.get("file_index"),
        )
        if file_key != expected_key:
            raise exceptions.ValidationError("The upload manifest identity is invalid.")
        if asset_nonce is not None:
            upload.lagniappe_asset_nonce = asset_nonce
        file = Entities.FILE.create(
            upload=upload,
            data=data,
            key=expected_key,
            report_user=user,
        )
        file._agent_upload_asset_nonce = asset_nonce
        return file

    # @testable false
    # @covered-by lagniappe/core/tools/ai/external/uploads.py::finalize_uploads
    # @reason failure cleanup is exercised through the public external finalizer
    def cleanup_failed_file(
        *,
        file,
        upload,
        error,
        checkpoint_disposition,
    ):
        if asset_nonce is None or checkpoint_disposition != CHECKPOINT_NOT_COMMITTED:
            return
        destination = getattr(upload, "lagniappe_saved_destination", None) or {}
        if not destination and file is not None:
            destination = (getattr(file, "assets", None) or {}).get("file") or {}
        path = destination.get("path")
        generation = destination.get("generation")
        if not path or generation is None:
            return
        try:
            storage_assets.delete_file_generation(
                path,
                destination.get("visibility", "private"),
                generation,
            )
        except Exception as cleanup_error:
            exceptions.capture(
                cleanup_error,
                context={
                    "agent_api": {
                        "phase": "discard_uncommitted_upload",
                        "report_key": getattr(report, "urlsafe_key", None),
                    }
                },
            )

    return finalize_report_upload_manifest(
        report,
        user,
        file_factory=create_file,
        failed_file_cleanup=cleanup_failed_file,
        ensure_active=ensure_active,
        save=save,
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/external/uploads.py::finalize_upload_batch
# @reason persisted batch-record consistency is asserted through the bound finalize route
def current_upload_batch_id(report):
    """Return the persisted batch identity, rejecting inconsistent state."""
    manifest = (
        report.agent_manifest
        if isinstance(getattr(report, "agent_manifest", None), dict)
        else {}
    )
    batch_id = manifest.get("upload_batch_id")
    pending = getattr(report, "upload_manifest", None)
    if batch_id is None and not pending:
        return None
    if (
        not isinstance(batch_id, str)
        or not _UPLOAD_BATCH_PATTERN.fullmatch(batch_id)
        or (
            pending
            and (
                not isinstance(pending, list)
                or any(
                    not isinstance(record, dict)
                    or record.get("upload_batch_id") != batch_id
                    for record in pending
                )
            )
        )
    ):
        raise ExternalPlanError(
            "invalid_upload_state",
            "The current upload batch state is invalid.",
        )
    return batch_id


# @testable false
# @covered-by lagniappe/core/tools/ai/external/uploads.py::create_upload_sessions
# @reason aggregate limits are exercised through the public upload resource
def _upload_sizes(report, requested):
    existing_sizes = [int(file.size or 0) for file in report.input_files]
    requested_sizes = [int(item["size"]) for item in requested]
    if len(existing_sizes) + len(requested_sizes) > definitions.MAX_PLAN_FILES:
        raise ExternalPlanError(
            "too_many_files",
            f"A plan can contain at most {definitions.MAX_PLAN_FILES} files.",
        )
    if sum(existing_sizes) + sum(requested_sizes) > definitions.MAX_TOTAL_FILE_BYTES:
        raise ExternalPlanError(
            "files_too_large",
            "The plan's files exceed the total upload limit.",
        )


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_upload_batch_identity_rejects_a_same_metadata_last_writer
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_claimed_upload_routes_reload_before_storage_side_effects
# @matrix agent-api mcp-upload : last-writer upload-batch-identity uploads
# @pairs agent-api:authoritative-reload agent-api:concurrency agent-api:stale-snapshot
# @pairs mcp-upload:authoritative-reload mcp-upload:concurrency mcp-upload:stale-snapshot
def create_upload_sessions(report, user, data, *, request_id):
    require_plan_access(report, user)
    plan_id = report.urlsafe_key
    require_uploads_available(report)
    envelope = definitions.upload_request_schema()
    file_schema = definitions.upload_file_schema()
    unsupported_fields = sorted(set(data) - set(envelope["properties"]))
    if unsupported_fields:
        raise ExternalPlanError(
            "unsupported_field",
            "Upload-session request contains unsupported fields.",
            details={
                "path": "$",
                "fields": unsupported_fields,
                "allowed_fields": list(envelope["properties"]),
            },
        )
    requested = data.get("files")
    if not isinstance(requested, list) or not requested:
        raise ExternalPlanError("invalid_files", "files must be a non-empty list.")

    normalized = []
    for index, item in enumerate(requested):
        if not isinstance(item, dict):
            raise ExternalPlanError("invalid_files", "Each file must be an object.")
        unsupported_fields = sorted(set(item) - set(file_schema["properties"]))
        if unsupported_fields:
            details = {
                "path": f"$.files[{index}]",
                "fields": unsupported_fields,
                "allowed_fields": sorted(file_schema["properties"]),
            }
            if "size_bytes" in unsupported_fields:
                details["use_field"] = "size"
            raise ExternalPlanError(
                "unsupported_field",
                "Upload file entry contains unsupported fields.",
                details=details,
            )
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise ExternalPlanError(
                "invalid_file",
                'Each file\'s "filename" must be a non-empty string.',
                details={
                    "path": f"$.files[{index}].filename",
                    "expected": "non-empty string",
                },
            )
        filename = filename.strip()
        content_type = item.get("content_type", file_schema["properties"]["content_type"]["default"])
        if not isinstance(content_type, str) or not content_type.strip():
            raise ExternalPlanError(
                "invalid_content_type",
                'Each file\'s "content_type" must be a non-empty string.',
                details={
                    "path": f"$.files[{index}].content_type",
                    "expected": "non-empty string",
                },
            )
        content_type = content_type.strip()
        size_details = {
            "path": f"$.files[{index}].size",
            "expected": "positive integer byte size",
        }
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ExternalPlanError(
                "invalid_file_size",
                'Each file\'s "size" must be a positive integer byte size.',
                details=size_details,
            )
        if size <= 0:
            raise ExternalPlanError(
                "invalid_file_size",
                'Each file\'s "size" must be a positive integer byte size.',
                details=size_details,
            )
        if size > definitions.MAX_FILE_BYTES:
            raise ExternalPlanError(
                "file_too_large",
                f"{filename} exceeds the per-file upload limit.",
            )
        normalized.append(
            {
                "filename": filename,
                "content_type": content_type,
                "size": size,
            }
        )
    _upload_sizes(report, normalized)

    upload_batch_id = uuid.uuid4().hex
    claim_token = uuid.uuid4().hex
    claim_outcome = agent_api_store.claim_plan_operation(
        report.key,
        phase="create",
        operation_id=upload_batch_id,
        claim_token=claim_token,
    )
    if claim_outcome != agent_api_store.PLAN_OPERATION_CLAIMED:
        raise_plan_operation_error(claim_outcome)

    try:
        # The pre-claim entity may predate a completed upload operation. Always
        # resume from the authoritative state protected by this claim.
        report = load_plan(plan_id, user)
        require_uploads_available(report)
        _upload_sizes(report, normalized)
        save = claimed_plan_save(
            report,
            user=user, request_id=request_id,
            phase="create",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )
        sessions = []
        records = []
        for index, item in enumerate(normalized):
            if not agent_api_store.renew_plan_operation(
                report.key,
                phase="create",
                operation_id=upload_batch_id,
                claim_token=claim_token,
            ):
                raise ExternalPlanError(
                    "plan_operation_lost",
                    "This request no longer owns the Plan's upload batch.",
                )
            session = storage_assets.create_direct_upload_session(
                item["filename"],
                content_type=item["content_type"],
                size=item["size"],
                input_name=definitions.UPLOAD_INPUT_NAME,
                origin=None,
            )
            records.append(
                {
                    "token": session["token"],
                    "input_name": definitions.UPLOAD_INPUT_NAME,
                    **item,
                }
            )
            sessions.append(
                {
                    "index": index,
                    "filename": item["filename"],
                    "session_url": session["session_url"],
                    "chunk_size": session["chunk_size"],
                }
            )
        prepared = prepare_upload_manifest(
            records,
            upload_batch_id=upload_batch_id,
        )
        report.upload_manifest = bind_upload_file_identities(
            report,
            prepared,
            upload_batch_id=upload_batch_id,
        )
        agent_manifest = (
            dict(report.agent_manifest)
            if isinstance(getattr(report, "agent_manifest", None), dict)
            else {}
        )
        agent_manifest["upload_batch_id"] = upload_batch_id
        report.agent_manifest = agent_manifest
        save(report)
        return {
            "plan_id": report.urlsafe_key,
            "upload_batch_id": upload_batch_id,
            "uploads": sessions,
        }
    finally:
        release_plan_operation_claim(
            report,
            phase="create",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_upload_batch_identity_rejects_a_same_metadata_last_writer
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_claimed_upload_routes_reload_before_storage_side_effects
# @matrix agent-api mcp-upload : last-writer upload-batch-identity uploads
# @matrix agent-api mcp-upload : authoritative-reload concurrency checkpoint resume stale-snapshot
def finalize_upload_batch(report, user, data, *, request_id):
    require_plan_access(report, user)
    plan_id = report.urlsafe_key
    require_draft(report)
    envelope = definitions.finalize_request_schema()
    unsupported_fields = sorted(set(data) - set(envelope["properties"]))
    if unsupported_fields:
        raise ExternalPlanError(
            "unsupported_field",
            "Upload finalization request contains unsupported fields.",
            details={
                "path": "$",
                "fields": unsupported_fields,
                "allowed_fields": list(envelope["properties"]),
            },
        )
    upload_batch_id = data.get("upload_batch_id")
    if not isinstance(upload_batch_id, str) or not _UPLOAD_BATCH_PATTERN.fullmatch(
        upload_batch_id
    ):
        raise ExternalPlanError(
            "invalid_upload_batch_id",
            "upload_batch_id must be the opaque identity returned at creation.",
            details={
                "path": "$.upload_batch_id",
                "expected": "server-issued upload batch identity",
            },
        )
    current_batch_id = current_upload_batch_id(report)
    if current_batch_id != upload_batch_id:
        raise ExternalPlanError(
            "upload_batch_mismatch",
            "This upload batch is no longer current for the Plan.",
        )
    if not report.upload_manifest:
        return report

    claim_token = uuid.uuid4().hex
    claim_outcome = agent_api_store.claim_plan_operation(
        report.key,
        phase="finalize",
        operation_id=upload_batch_id,
        claim_token=claim_token,
    )
    if claim_outcome == agent_api_store.PLAN_OPERATION_COMPLETE:
        current = load_plan(plan_id, user)
        return current
    if claim_outcome != agent_api_store.PLAN_OPERATION_CLAIMED:
        raise_plan_operation_error(claim_outcome)

    try:
        # A prior worker may have checkpointed one or more records between this
        # request's first fetch and claim acquisition. Never finalize its stale
        # in-memory manifest.
        report = load_plan(plan_id, user)
        require_draft(report)
        if current_upload_batch_id(report) != upload_batch_id:
            raise ExternalPlanError(
                "upload_batch_mismatch",
                "This upload batch is no longer current for the Plan.",
            )
        if not report.upload_manifest:
            return report

        # @testable false
        # @covered-by lagniappe/core/tools/ai/external/uploads.py::finalize_upload_batch
        # @reason the service-owned callback only maps lease renewal loss to its API conflict
        def ensure_active():
            if not agent_api_store.renew_plan_operation(
                report.key,
                phase="finalize",
                operation_id=upload_batch_id,
                claim_token=claim_token,
            ):
                raise ExternalPlanError(
                    "plan_operation_lost",
                    "This request no longer owns the Plan's upload batch.",
                )

        save = claimed_plan_save(
            report,
            user=user, request_id=request_id,
            phase="finalize",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )
        finalize_uploads(
            report,
            user,
            asset_nonce=claim_token,
            ensure_active=ensure_active,
            save=save,
        )
        report = load_plan(plan_id, user)
    finally:
        release_plan_operation_claim(
            report,
            phase="finalize",
            operation_id=upload_batch_id,
            claim_token=claim_token,
        )
    return report


# @testable false
# @covered-by lagniappe/core/tools/ai/external/uploads.py::create_upload_sessions
# @reason preserve draft/pending checks before HTTP body parsing and after acquiring a claim
def require_uploads_available(report):
    require_draft(report)
    if report.upload_manifest:
        raise ExternalPlanError(
            "uploads_pending", "Finalize the current upload batch before starting another."
        )
