"""Transactional credentials and Plan-operation claims for the external API."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from google.cloud.datastore import Entity as DatastoreEntity

from .core import DATA
from . import get as database_get
from . import utility as database_utility
from .transactions import retry_aborted
from .utility import create_named_key


EXCLUDED_FIELDS = ("token_digest",)
PLAN_OPERATION_LEASE_SECONDS = 5 * 60
PLAN_OPERATION_PHASES = frozenset({"create", "finalize", "submit"})
PLAN_OPERATION_CLAIMED = "claimed"
PLAN_OPERATION_BUSY = "busy"
PLAN_OPERATION_COMMITTED = "committed"
PLAN_OPERATION_COMPLETE = "complete"
PLAN_OPERATION_INVALID = "invalid"
PLAN_OPERATION_LOST = "lost"
PLAN_OPERATION_MISMATCH = "mismatch"
PLAN_OPERATION_MISSING = "missing"
PLAN_OPERATION_PENDING = "pending"
PLAN_OPERATION_STALE = "stale"
_UPLOAD_BATCH_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_PLAN_OPERATION_TOKEN_PATTERN = re.compile(r"^[a-f0-9]{32}$")


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::rotate_credential
# @reason named key construction is exercised through transactional rotation
def credential_key(identifier):
    return create_named_key("agent_api_credential", identifier)


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::authenticate_credential
# @reason raw lookup is owned by the authenticated credential boundary
def get_credential(identifier):
    return DATA.datastore.get(credential_key(identifier))


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason stable claim-key construction is exercised through competing claims
def plan_operation_claim_key(report_key):
    """Return the one serialized external-operation claim beneath a report."""
    return create_named_key(
        "agent_api_plan_operation_claim",
        "operation",
        parent=report_key,
    )


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_upload_file_identity_is_deterministic_per_batch_record
# @matrix agent-api mcp-upload : deterministic-file-identity retry
def upload_file_key(report_key, upload_batch_id, file_index):
    """Return a stable File key for one server-issued upload batch record."""
    report_identity = database_get.urlsafe_key(report_key)
    if (
        not isinstance(report_identity, str)
        or not report_identity
        or not isinstance(upload_batch_id, str)
        or not _UPLOAD_BATCH_PATTERN.fullmatch(upload_batch_id)
        or isinstance(file_index, bool)
        or not isinstance(file_index, int)
        or not 0 <= file_index < 20
    ):
        raise ValueError("Invalid external upload file identity")
    digest = hashlib.sha256(
        f"{report_identity}\0{upload_batch_id}\0{file_index}".encode("utf-8")
    ).hexdigest()
    return create_named_key("file", f"agent-upload-{digest}")


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason raw report JSON is validated through public claim outcomes
def _json_field(row, name, expected_type, default):
    value = row.get(name)
    if value is None:
        return default
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, expected_type) else None


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason canonical process-backed status is validated through public claim outcomes
def _report_process(row):
    process = _json_field(row, "process", dict, {})
    if process is None:
        return None
    report_process = process.get("report")
    return report_process if isinstance(report_process, dict) else None


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason canonical process-backed status is validated through public claim outcomes
def _report_status(row):
    report_process = _report_process(row)
    if report_process is None:
        return None
    return report_process.get("status")


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason shared report-state validation is exercised through public claim outcomes
def _report_operation_state(report, phase):
    """Return validated state used to decide one serialized Plan operation."""
    if (
        report is None
        or report.get("type") != "report"
        or report.get("origin") != "api"
    ):
        return None

    tool = report.get("tool")
    report_process = _report_process(report)
    status = report_process.get("status") if report_process is not None else None
    if phase in {"create", "finalize"}:
        if tool != "organize" or status != "draft":
            return None
    else:
        reusable_status = "complete" if tool == "ask" else "ready"
        if tool not in {"ask", "create", "organize"} or status not in {
            "draft",
            reusable_status,
        }:
            return None

    manifest = _json_field(report, "upload_manifest", list, [])
    agent_manifest = _json_field(report, "agent_manifest", dict, {})
    deferred_job = (
        report_process.get("deferred-job", {})
        if report_process is not None
        else None
    )
    if deferred_job is None:
        deferred_job = {}
    if manifest is None or agent_manifest is None or deferred_job is None:
        return None
    current_batch_id = agent_manifest.get("upload_batch_id")
    if current_batch_id is not None and (
        not isinstance(current_batch_id, str)
        or not _UPLOAD_BATCH_PATTERN.fullmatch(current_batch_id)
    ):
        return None
    if manifest and (
        current_batch_id is None
        or any(
            not isinstance(record, dict)
            or record.get("upload_batch_id") != current_batch_id
            for record in manifest
        )
    ):
        return None
    if tool != "organize" and (manifest or current_batch_id is not None):
        return None
    if phase == "submit" and deferred_job:
        return None
    return {
        "tool": tool,
        "status": status,
        "manifest": manifest,
        "upload_batch_id": current_batch_id,
    }


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason durable phase transitions are exercised through competing operation claims
def _completed_claim_transition(claim, state):
    """Whether a prior owner already committed its report-side transition."""
    phase = claim["phase"]
    operation_id = claim["operation_id"]
    manifest = state["manifest"]
    current_batch_id = state["upload_batch_id"]
    if phase == "create":
        return bool(manifest) and current_batch_id == operation_id
    if phase == "finalize":
        return not manifest and current_batch_id == operation_id
    # A report may already be ready/complete before a replacement submission
    # starts, so status cannot prove that a particular submit owner committed.
    # Keep an active submit lease exclusive until its owner releases it (or it
    # expires); a crash after commit therefore costs at most one lease period.
    return False


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::claim_plan_operation
# @reason claim validation is exercised through the public transaction
def _valid_claim(row):
    if row is None:
        return None
    phase = row.get("phase")
    operation_id = row.get("operation_id")
    token = row.get("claim_token")
    expires_at = row.get("expires_at")
    if (
        phase not in PLAN_OPERATION_PHASES
        or not isinstance(operation_id, str)
        or not _UPLOAD_BATCH_PATTERN.fullmatch(operation_id)
        or not isinstance(token, str)
        or not _PLAN_OPERATION_TOKEN_PATTERN.fullmatch(token)
        or not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
    ):
        return None
    return {
        "phase": phase,
        "operation_id": operation_id,
        "claim_token": token,
        "expires_at": expires_at,
    }


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_plan_operation_claim_serializes_competing_workers
# @matrix agent-api mcp-upload : claim concurrency lease transaction
@retry_aborted
def claim_plan_operation(
    report_key,
    *,
    phase,
    operation_id,
    claim_token,
    now=None,
):
    """Claim one report's create, finalize, or submit transition."""
    if (
        phase not in PLAN_OPERATION_PHASES
        or not isinstance(operation_id, str)
        or not _UPLOAD_BATCH_PATTERN.fullmatch(operation_id)
        or not isinstance(claim_token, str)
        or not _PLAN_OPERATION_TOKEN_PATTERN.fullmatch(claim_token)
    ):
        raise ValueError("Invalid external Plan-operation claim")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Plan-operation claim time must be timezone-aware")

    key = plan_operation_claim_key(report_key)
    with DATA.datastore.transaction() as transaction:
        report = DATA.datastore.get(report_key, transaction=transaction)
        if report is None:
            return PLAN_OPERATION_MISSING
        state = _report_operation_state(report, phase)
        if state is None:
            return PLAN_OPERATION_INVALID
        manifest = state["manifest"]
        current_batch_id = state["upload_batch_id"]

        existing_row = DATA.datastore.get(key, transaction=transaction)
        existing = _valid_claim(existing_row)
        if existing_row is not None and existing is None:
            return PLAN_OPERATION_INVALID

        if phase == "create":
            if manifest:
                return PLAN_OPERATION_PENDING
        elif phase == "finalize":
            if current_batch_id != operation_id:
                return PLAN_OPERATION_MISMATCH
            if not manifest:
                # Do not remove a claim here. A delayed retry for the prior
                # finalized batch may overlap the next creator's active claim.
                return PLAN_OPERATION_COMPLETE

        if existing:
            if (
                existing["phase"] == phase
                and existing["operation_id"] == operation_id
                and existing["claim_token"] == claim_token
            ):
                return PLAN_OPERATION_CLAIMED
            if not _completed_claim_transition(existing, state) and (
                existing["expires_at"] > now
            ):
                return PLAN_OPERATION_BUSY

        claim = DatastoreEntity(key=key)
        claim.update(
            {
                "phase": phase,
                "operation_id": operation_id,
                "claim_token": claim_token,
                "expires_at": now + timedelta(seconds=PLAN_OPERATION_LEASE_SECONDS),
            }
        )
        transaction.put(claim)
    return PLAN_OPERATION_CLAIMED


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_plan_operation_claim_serializes_competing_workers
# @matrix agent-api mcp-upload : fencing lease renewal
@retry_aborted
def renew_plan_operation(
    report_key,
    *,
    phase,
    operation_id,
    claim_token,
    now=None,
):
    """Renew only the owned Plan-operation claim; reject a replacement owner."""
    now = now or datetime.now(timezone.utc)
    key = plan_operation_claim_key(report_key)
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(key, transaction=transaction)
        claim = _valid_claim(row)
        if not claim or (
            claim["phase"] != phase
            or claim["operation_id"] != operation_id
            or claim["claim_token"] != claim_token
        ):
            return False
        row["expires_at"] = now + timedelta(seconds=PLAN_OPERATION_LEASE_SECONDS)
        transaction.put(row)
    return True


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_plan_operation_commit_rejects_a_replacement_owner
# @matrix agent-api mcp-upload : atomic-checkpoint cas claim fencing transaction
@retry_aborted
def commit_plan_operation(
    report_key,
    *,
    phase,
    operation_id,
    claim_token,
    expected_report,
    writes,
    now=None,
):
    """Commit prepared entity writes only while the exact claim is still owned.

    Reading the claim and report and writing every checkpoint in the same
    Datastore transaction turns the claim token into a fence: a takeover writes
    the same claim entity, forcing this transaction to retry and observe that
    its token was replaced before any stale entity mutation can commit.
    """
    if (
        phase not in PLAN_OPERATION_PHASES
        or not isinstance(operation_id, str)
        or not _UPLOAD_BATCH_PATTERN.fullmatch(operation_id)
        or not isinstance(claim_token, str)
        or not _PLAN_OPERATION_TOKEN_PATTERN.fullmatch(claim_token)
        or not isinstance(expected_report, dict)
    ):
        raise ValueError("Invalid external Plan-operation commit")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Plan-operation commit time must be timezone-aware")

    prepared = []
    report_write = None
    for entity, property_mask in writes:
        row = getattr(entity, "db", entity)
        key = getattr(row, "key", None)
        if key is None:
            continue
        mask = None if property_mask is None else tuple(property_mask)
        prepared.append((entity, row, mask))
        if key == report_key:
            report_write = row
    if report_write is None:
        raise ValueError("Guarded Plan-operation commit must include its report")

    fingerprint_entities = [
        row
        for entity, row, mask in prepared
        if database_utility._advances_site_fingerprint(entity, mask)
    ]
    fingerprint_rows = (
        database_utility.update_site_fingerprints(*fingerprint_entities)
        if fingerprint_entities
        else []
    )
    key = plan_operation_claim_key(report_key)
    with DATA.datastore.transaction() as transaction:
        current_report = DATA.datastore.get(report_key, transaction=transaction)
        if current_report is None:
            return PLAN_OPERATION_MISSING
        if dict(current_report) != expected_report:
            return PLAN_OPERATION_STALE

        row = DATA.datastore.get(key, transaction=transaction)
        claim = _valid_claim(row)
        if not claim or (
            claim["phase"] != phase
            or claim["operation_id"] != operation_id
            or claim["claim_token"] != claim_token
        ):
            return PLAN_OPERATION_LOST

        row["expires_at"] = now + timedelta(seconds=PLAN_OPERATION_LEASE_SECONDS)
        transaction.put(row)
        for _entity, row, property_mask in prepared:
            database_utility._put_mutation(transaction, row, property_mask)
        for fingerprint in fingerprint_rows:
            transaction.put(fingerprint)
    return PLAN_OPERATION_COMMITTED


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_idle_plan_mutation_fences_api_claims_and_stale_browser_snapshots
# @matrix agent-api ai-report : browser-review cas claim fencing transaction
@retry_aborted
def commit_plan_mutation_if_idle(
    report_key,
    *,
    expected_report,
    writes=(),
    deletes=(),
    now=None,
):
    """Commit one browser mutation only when no API operation owns the Plan.

    The claim key is deleted in the same transaction even when it is absent or
    expired. That write fences a concurrent API claimant on the shared key,
    while the raw Report comparison prevents a stale browser snapshot from
    overwriting an API operation that completed and released its claim first.
    """
    if not isinstance(expected_report, dict):
        raise ValueError("Invalid idle Plan mutation snapshot")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Idle Plan mutation time must be timezone-aware")

    prepared_writes = []
    for entity, property_mask in writes:
        row = getattr(entity, "db", entity)
        key = getattr(row, "key", None)
        if key is None:
            continue
        mask = None if property_mask is None else tuple(property_mask)
        prepared_writes.append((entity, row, mask))

    prepared_deletes = []
    for entity in deletes:
        row = getattr(entity, "db", entity)
        if getattr(row, "key", None) is not None:
            prepared_deletes.append(row)

    write_keys = {row.key for _entity, row, _mask in prepared_writes}
    delete_keys = {row.key for row in prepared_deletes}
    if write_keys & delete_keys:
        raise ValueError("Idle Plan mutation cannot write and delete one entity")
    if report_key not in write_keys | delete_keys:
        raise ValueError("Idle Plan mutation must include its report")

    fingerprint_entities = [
        row
        for entity, row, mask in prepared_writes
        if database_utility._advances_site_fingerprint(entity, mask)
    ]
    fingerprint_entities.extend(
        row for row in prepared_deletes if row.get("type") != "notification"
    )
    fingerprint_rows = (
        database_utility.update_site_fingerprints(*fingerprint_entities)
        if fingerprint_entities
        else []
    )

    claim_key = plan_operation_claim_key(report_key)
    with DATA.datastore.transaction() as transaction:
        current_report = DATA.datastore.get(report_key, transaction=transaction)
        if current_report is None:
            return PLAN_OPERATION_MISSING
        if dict(current_report) != expected_report:
            return PLAN_OPERATION_STALE

        claim_row = DATA.datastore.get(claim_key, transaction=transaction)
        claim = _valid_claim(claim_row)
        if claim_row is not None and claim is None:
            return PLAN_OPERATION_INVALID
        if claim and claim["expires_at"] > now:
            return PLAN_OPERATION_BUSY

        # Deleting an absent/expired claim is intentional: this transaction
        # must write the same key an API claimant creates or replaces.
        transaction.delete(claim_key)
        for _entity, row, property_mask in prepared_writes:
            database_utility._put_mutation(transaction, row, property_mask)
        for row in prepared_deletes:
            transaction.delete(row.key)
        for fingerprint in fingerprint_rows:
            transaction.put(fingerprint)
    return PLAN_OPERATION_COMMITTED


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_plan_operation_claim_serializes_competing_workers
# @matrix agent-api mcp-upload : claim cleanup ownership
@retry_aborted
def release_plan_operation(
    report_key,
    *,
    phase,
    operation_id,
    claim_token,
):
    """Delete a Plan-operation claim only for its exact current owner."""
    key = plan_operation_claim_key(report_key)
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(key, transaction=transaction)
        claim = _valid_claim(row)
        if not claim or (
            claim["phase"] != phase
            or claim["operation_id"] != operation_id
            or claim["claim_token"] != claim_token
        ):
            return False
        transaction.delete(key)
    return True


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_credential_rotation_and_revocation_are_transactional
# @matrix agent-api : credential persistence revoke rotate
@retry_aborted
def rotate_credential(
    identifier,
    user_key,
    *,
    token_digest,
    display_prefix,
    issued_at,
    expires_at,
):
    """Replace the user's sole credential and return its public metadata."""
    key = credential_key(identifier)
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        generation = int((current or {}).get("generation") or 0) + 1
        row = DatastoreEntity(key=key, exclude_from_indexes=EXCLUDED_FIELDS)
        row.update(
            {
                "user": user_key,
                "credential_id": identifier,
                "generation": generation,
                "token_digest": token_digest,
                "display_prefix": display_prefix,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "active": True,
            }
        )
        transaction.put(row)
    return row


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_credential_rotation_and_revocation_are_transactional
# @matrix agent-api : credential persistence revoke rotate
@retry_aborted
def revoke_credential(identifier, user_key, *, revoked_at):
    """Invalidate the user's credential without deleting its audit metadata."""
    key = credential_key(identifier)
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        if current is None or current.get("user") != user_key:
            return None
        current["generation"] = int(current.get("generation") or 0) + 1
        current["active"] = False
        current["revoked_at"] = revoked_at
        current.pop("token_digest", None)
        transaction.put(current)
    return current
