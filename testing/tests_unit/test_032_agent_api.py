"""Provider-free external-agent API domain and credential coverage."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import threading

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
import pytest

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.entities.ai_report import AIReport
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import external_operations
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai import references as ai_references
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.database import agent_api as credential_store
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_file, _test_user


def _contract_actor():
    page = SimpleNamespace(
        hash="personalpage",
        name="Personal Page",
        url="/pages/personal-page",
        allowed=lambda action, user=None: True,
    )
    return SimpleNamespace(page=page)


# @matrix agent-api : bootstrap discovery secret-handling tool-envelope
@pytest.mark.unit
def test_client_skill_markdown_is_minimal_and_discovery_first():
    skill = external_api.client_skill_markdown("https://lagniappe.test/api/v1/")

    assert skill.startswith("---\nname: lagniappe\n")
    assert "https://lagniappe.test/api/v1`" in skill
    assert "$LAGNIAPPE_API_KEY" in skill
    assert "`openapi_url`" in skill
    assert "`actor_url`" in skill
    assert '{"arguments": {...}}' in skill
    assert "reuse them in memory" in skill
    assert "exact `input_schema`" in skill
    assert "follow its returned `contract_url`" in skill
    assert "instead of reconstructing those lifecycle" in skill
    assert "Choose Ask for a read-only answer" in skill
    assert "untrusted evidence" in skill
    assert "ready for authenticated website review" in skill
    assert "can be edited and resubmitted" in skill
    assert "authenticated website" in skill
    assert "create_page" not in skill
    assert "Bearer <" not in skill


# @matrix agent-api ai-report : draft report-session status
# @pair agent-api:entitlement-independent
# @pair agent-api:origin
@pytest.mark.unit
def test_api_report_draft_preserves_agent_manifest(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("agent-api-owner")
    user.ai_access = "NONE"
    user.access = lambda required: pytest.fail(
        "External plan creation consulted provider entitlement"
    )
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    report = external_api.create_plan(
        user,
        instructions="  Put these records into project pages.  ",
        name="Records import",
    )

    assert saved == [report]
    assert report.origin == "api"
    assert report.status == "draft"
    assert report.pending is False
    assert report.tool == "organize"
    assert report.instructions == "Put these records into project pages."
    assert report.agent_manifest["version"] == 1
    assert report.agent_manifest["contract_version"] == external_api.CONTRACT_VERSION
    assert report.note == "Waiting for external plan"


# @matrix agent-api ai-report : upload-batch-identity upload-manifest
@pytest.mark.unit
def test_external_upload_batch_identity_is_preserved_in_every_record():
    records = [
        {
            "token": "first-storage-token",
            "input_name": "agent-api-files",
            "filename": "same.bin",
            "content_type": "application/octet-stream",
            "size": 4,
            "upload_batch_id": "caller-controlled-value",
        },
        {
            "token": "second-storage-token",
            "input_name": "agent-api-files",
            "filename": "same.bin",
            "content_type": "application/octet-stream",
            "size": 4,
        },
    ]

    manifest = external_api.prepare_upload_manifest(
        records,
        upload_batch_id="batch-aaaaaaaaaaaaaaaa",
    )

    assert {record["upload_batch_id"] for record in manifest} == {
        "batch-aaaaaaaaaaaaaaaa"
    }
    assert [record["token"] for record in manifest] == [
        "first-storage-token",
        "second-storage-token",
    ]
    assert records[0]["upload_batch_id"] == "caller-controlled-value"


# @matrix agent-api mcp-upload : deterministic-file-identity retry upload-manifest
# @matrix ai-report : deterministic-file-identity upload-manifest
@pytest.mark.unit
def test_upload_file_identity_is_deterministic_per_batch_record(monkeypatch):
    report_key = object()

    def urlsafe_key(key):
        if key is report_key:
            return "encoded-report-key"
        return f"encoded:{key[1]}"

    monkeypatch.setattr(credential_store.database_get, "urlsafe_key", urlsafe_key)
    monkeypatch.setattr(
        credential_store,
        "create_named_key",
        lambda kind, identifier, parent=None: (kind, identifier, parent),
    )
    batch_id = "batch-aaaaaaaaaaaaaaaa"

    first = credential_store.upload_file_key(report_key, batch_id, 0)
    repeated = credential_store.upload_file_key(report_key, batch_id, 0)
    second = credential_store.upload_file_key(report_key, batch_id, 1)
    other_batch = credential_store.upload_file_key(
        report_key,
        "batch-bbbbbbbbbbbbbbbb",
        0,
    )
    bound = external_api.bind_upload_file_identities(
        SimpleNamespace(key=report_key),
        [
            {
                "token": "storage-token",
                "filename": "records.pdf",
                "input_name": "agent-api-files",
                "upload_batch_id": batch_id,
            }
        ],
        upload_batch_id=batch_id,
    )

    assert first == repeated
    assert len({first, second, other_batch}) == 3
    assert bound[0]["file_index"] == 0
    assert bound[0]["file_key"] == f"encoded:{first[1]}"


# @matrix agent-api mcp-upload : claim cleanup concurrency fencing lease ownership renewal transaction
@pytest.mark.unit
def test_plan_operation_claim_serializes_competing_workers(monkeypatch):
    report_key = Key("activity", "report", project="test-project")
    claim_key = Key(
        "agent-api-plan-operation-claims",
        "operation",
        parent=report_key,
    )
    report_row = DatastoreEntity(key=report_key)
    report_row.update(
        {
            "type": "report",
            "origin": "api",
            "tool": "organize",
            "process": json.dumps({"report": {"status": "draft"}}),
            "agent_manifest": json.dumps({"contract_version": 1}),
        }
    )
    rows = {report_key: report_row}
    datastore_lock = threading.Lock()

    class Transaction:
        def __enter__(self):
            datastore_lock.acquire()
            return self

        def __exit__(self, *args):
            datastore_lock.release()
            return False

        def put(self, row):
            rows[row.key] = row

        def delete(self, key):
            rows.pop(key, None)

    class Datastore:
        def transaction(self):
            return Transaction()

        def get(self, requested, transaction=None):
            assert isinstance(transaction, Transaction)
            return rows.get(requested)

    monkeypatch.setattr(
        credential_store,
        "plan_operation_claim_key",
        lambda _key: claim_key,
    )
    monkeypatch.setattr(credential_store.DATA, "_datastore_client", Datastore())
    now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

    def compete(calls):
        start = threading.Barrier(len(calls) + 1)
        results = []
        failures = []

        def worker(options):
            try:
                start.wait()
                outcome = credential_store.claim_plan_operation(
                    report_key,
                    now=now,
                    **options,
                )
                results.append((options, outcome))
            except BaseException as error:  # surfaced in the joining test thread
                failures.append(error)

        threads = [threading.Thread(target=worker, args=(call,)) for call in calls]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        assert not failures
        return results

    create_calls = [
        {
            "phase": "create",
            "operation_id": "batch-aaaaaaaaaaaaaaaa",
            "claim_token": "a" * 32,
        },
        {
            "phase": "create",
            "operation_id": "batch-bbbbbbbbbbbbbbbb",
            "claim_token": "b" * 32,
        },
    ]
    create_results = compete(create_calls)
    assert sorted(outcome for _options, outcome in create_results) == [
        credential_store.PLAN_OPERATION_BUSY,
        credential_store.PLAN_OPERATION_CLAIMED,
    ]
    creator = next(
        options
        for options, outcome in create_results
        if outcome == credential_store.PLAN_OPERATION_CLAIMED
    )

    # Once the creator's manifest is durable, finalization is the next valid
    # phase even if best-effort release of the create claim did not run.
    report_row["agent_manifest"] = json.dumps(
        {
            "contract_version": 1,
            "upload_batch_id": creator["operation_id"],
        }
    )
    report_row["upload_manifest"] = json.dumps(
        [{"upload_batch_id": creator["operation_id"]}]
    )
    finalize_token = "c" * 32
    assert credential_store.claim_plan_operation(
        report_key,
        phase="finalize",
        operation_id=creator["operation_id"],
        claim_token=finalize_token,
        now=now,
    ) == credential_store.PLAN_OPERATION_CLAIMED
    assert not credential_store.release_plan_operation(
        report_key,
        **creator,
    )

    # A deterministic barrier makes two workers compete for the exact same
    # pending batch; exactly one may enter the storage side-effect section.
    assert credential_store.release_plan_operation(
        report_key,
        phase="finalize",
        operation_id=creator["operation_id"],
        claim_token=finalize_token,
    )
    finalize_calls = [
        {
            "phase": "finalize",
            "operation_id": creator["operation_id"],
            "claim_token": "d" * 32,
        },
        {
            "phase": "finalize",
            "operation_id": creator["operation_id"],
            "claim_token": "e" * 32,
        },
    ]
    finalize_results = compete(finalize_calls)
    assert sorted(outcome for _options, outcome in finalize_results) == [
        credential_store.PLAN_OPERATION_BUSY,
        credential_store.PLAN_OPERATION_CLAIMED,
    ]
    finalizer = next(
        options
        for options, outcome in finalize_results
        if outcome == credential_store.PLAN_OPERATION_CLAIMED
    )
    assert credential_store.renew_plan_operation(
        report_key,
        **finalizer,
        now=now + timedelta(seconds=1),
    )
    loser = next(options for options in finalize_calls if options != finalizer)
    assert not credential_store.renew_plan_operation(
        report_key,
        **loser,
        now=now + timedelta(seconds=1),
    )
    assert not credential_store.release_plan_operation(
        report_key,
        **loser,
    )
    assert credential_store.release_plan_operation(
        report_key,
        **finalizer,
    )

    # A delayed retry for the just-finalized batch must not remove or replace
    # the active claim for the next batch.
    report_row.pop("upload_manifest")
    next_creator = {
        "phase": "create",
        "operation_id": "batch-cccccccccccccccc",
        "claim_token": "f" * 32,
    }
    assert credential_store.claim_plan_operation(
        report_key,
        **next_creator,
        now=now,
    ) == credential_store.PLAN_OPERATION_CLAIMED
    assert credential_store.claim_plan_operation(
        report_key,
        phase="finalize",
        operation_id=creator["operation_id"],
        claim_token="1" * 32,
        now=now,
    ) == credential_store.PLAN_OPERATION_COMPLETE
    assert rows[claim_key]["phase"] == "create"
    assert rows[claim_key]["operation_id"] == next_creator["operation_id"]
    assert rows[claim_key]["claim_token"] == next_creator["claim_token"]

    # Submission participates in the same report claim and cannot race a
    # creator before that creator's report-side checkpoint is durable.
    assert credential_store.claim_plan_operation(
        report_key,
        phase="submit",
        operation_id="submit-aaaaaaaaaaaaaaaa",
        claim_token="2" * 32,
        now=now,
    ) == credential_store.PLAN_OPERATION_BUSY

    # Existing ready/complete status does not prove that an in-flight
    # replacement submission committed. Its active lease remains exclusive.
    assert credential_store.release_plan_operation(report_key, **next_creator)
    report_row["process"] = json.dumps(
        {
            "report": {
                "status": "ready",
                "deferred-job": {
                    "key": "active-execution-job",
                    "idempotency_key": "run-1",
                },
            }
        }
    )
    assert credential_store.claim_plan_operation(
        report_key,
        phase="submit",
        operation_id="submit-blockedbyjob",
        claim_token="2" * 32,
        now=now,
    ) == credential_store.PLAN_OPERATION_INVALID
    report_row["process"] = json.dumps({"report": {"status": "ready"}})
    submitter = {
        "phase": "submit",
        "operation_id": "submit-aaaaaaaaaaaaaaaa",
        "claim_token": "2" * 32,
    }
    assert credential_store.claim_plan_operation(
        report_key,
        **submitter,
        now=now,
    ) == credential_store.PLAN_OPERATION_CLAIMED
    assert credential_store.claim_plan_operation(
        report_key,
        phase="submit",
        operation_id="submit-bbbbbbbbbbbbbbbb",
        claim_token="3" * 32,
        now=now,
    ) == credential_store.PLAN_OPERATION_BUSY


# @matrix agent-api mcp-upload : atomic-checkpoint cas claim fencing transaction
@pytest.mark.unit
def test_plan_operation_commit_rejects_a_replacement_owner(monkeypatch):
    report_key = Key("activity", "report", project="test-project")
    claim_key = Key(
        "agent-api-plan-operation-claims",
        "operation",
        parent=report_key,
    )
    report_row = DatastoreEntity(key=report_key)
    report_row.update(
        {
            "type": "report",
            "origin": "api",
            "tool": "organize",
            "process": json.dumps({"report": {"status": "draft"}}),
            "agent_manifest": json.dumps({"contract_version": 1}),
        }
    )
    claim_row = DatastoreEntity(key=claim_key)
    claim_row.update(
        {
            "phase": "create",
            "operation_id": "batch-aaaaaaaaaaaaaaaa",
            "claim_token": "a" * 32,
            "expires_at": datetime(2026, 9, 4, 12, 5, tzinfo=timezone.utc),
        }
    )
    rows = {report_key: report_row, claim_key: claim_row}

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, row):
            rows[row.key] = row

    class Datastore:
        def transaction(self):
            return Transaction()

        def get(self, requested, transaction=None):
            assert isinstance(transaction, Transaction)
            return rows.get(requested)

    monkeypatch.setattr(
        credential_store,
        "plan_operation_claim_key",
        lambda _key: claim_key,
    )
    monkeypatch.setattr(credential_store.DATA, "_datastore_client", Datastore())
    monkeypatch.setattr(
        credential_store.database_utility,
        "update_site_fingerprints",
        lambda *_rows: [],
    )
    expected = dict(report_row)
    replacement = DatastoreEntity(key=report_key)
    replacement.update(
        {
            **expected,
            "upload_manifest": json.dumps(
                [{"upload_batch_id": "batch-aaaaaaaaaaaaaaaa"}]
            ),
        }
    )
    entity = SimpleNamespace(db=replacement, key=report_key)
    options = {
        "phase": "create",
        "operation_id": "batch-aaaaaaaaaaaaaaaa",
        "claim_token": "a" * 32,
        "expected_report": expected,
        "writes": [(entity, None)],
        "now": datetime(2026, 9, 4, 12, 1, tzinfo=timezone.utc),
    }

    # A lease takeover immediately before the guarded save replaces the exact
    # token. The stale worker cannot write its report snapshot.
    rows[claim_key] = DatastoreEntity(key=claim_key)
    rows[claim_key].update({**claim_row, "claim_token": "b" * 32})
    assert credential_store.commit_plan_operation(
        report_key,
        **options,
    ) == credential_store.PLAN_OPERATION_LOST
    assert "upload_manifest" not in rows[report_key]

    # A non-claim writer changing the report after the route's authoritative
    # reload is detected by the raw-state compare-and-set.
    rows[claim_key] = claim_row
    rows[report_key]["concurrent_change"] = True
    assert credential_store.commit_plan_operation(
        report_key,
        **options,
    ) == credential_store.PLAN_OPERATION_STALE
    assert "upload_manifest" not in rows[report_key]

    rows[report_key].pop("concurrent_change")
    assert credential_store.commit_plan_operation(
        report_key,
        **options,
    ) == credential_store.PLAN_OPERATION_COMMITTED
    assert json.loads(rows[report_key]["upload_manifest"])[0][
        "upload_batch_id"
    ] == "batch-aaaaaaaaaaaaaaaa"
    assert rows[claim_key]["claim_token"] == "a" * 32
    assert rows[claim_key]["expires_at"] > options["now"]


# @matrix agent-api ai-report : browser-review cas claim fencing transaction
@pytest.mark.unit
def test_idle_plan_mutation_fences_api_claims_and_stale_browser_snapshots(
    monkeypatch,
):
    report_key = Key("activity", "report", project="test-project")
    file_key = Key("activity", "file", project="test-project")
    user_key = Key("activity", "user", project="test-project")
    claim_key = Key(
        "agent-api-plan-operation-claims",
        "operation",
        parent=report_key,
    )
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    report_row = DatastoreEntity(key=report_key)
    report_row.update(
        {
            "type": "report",
            "origin": "api",
            "tool": "create",
            "process": json.dumps({"report": {"status": "ready"}}),
            "proposal": json.dumps({"summary": "API proposal"}),
        }
    )
    file_row = DatastoreEntity(key=file_key)
    file_row.update({"type": "file", "name": "report-only"})
    user_row = DatastoreEntity(key=user_key)
    user_row.update(
        {
            "type": "user",
            "email": "new-profile@example.com",
            "modified": "concurrent",
        }
    )
    claim_row = DatastoreEntity(key=claim_key)
    claim_row.update(
        {
            "phase": "submit",
            "operation_id": "submit-aaaaaaaaaaaaaaaa",
            "claim_token": "a" * 32,
            "expires_at": now + timedelta(minutes=1),
        }
    )
    rows = {
        report_key: report_row,
        file_key: file_row,
        user_key: user_row,
        claim_key: claim_row,
    }
    applied = []

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, row):
            rows[row.key] = row

        def delete(self, key):
            rows.pop(key, None)

    class Datastore:
        def transaction(self):
            return Transaction()

        def get(self, requested, transaction=None):
            assert isinstance(transaction, Transaction)
            return rows.get(requested)

    def put_mutation(_transaction, row, mask=None):
        applied.append((row.key, mask))
        if mask is None:
            rows[row.key] = row
            return
        current = rows[row.key]
        for field in mask:
            if field in row:
                current[field] = row[field]
            else:
                current.pop(field, None)

    monkeypatch.setattr(
        credential_store,
        "plan_operation_claim_key",
        lambda _key: claim_key,
    )
    monkeypatch.setattr(credential_store.DATA, "_datastore_client", Datastore())
    monkeypatch.setattr(
        credential_store.database_utility,
        "_put_mutation",
        put_mutation,
    )
    monkeypatch.setattr(
        credential_store.database_utility,
        "update_site_fingerprints",
        lambda *_rows: [],
    )

    expected = dict(report_row)
    browser_report = DatastoreEntity(key=report_key)
    browser_report.update(
        {**expected, "proposal": json.dumps({"summary": "Browser skip"})}
    )
    stale_user = DatastoreEntity(key=user_key)
    stale_user.update(
        {
            "type": "user",
            "email": "old-profile@example.com",
            "modified": "browser-touch",
        }
    )
    options = {
        "expected_report": expected,
        "writes": [
            (SimpleNamespace(db=browser_report, key=report_key), None),
            (SimpleNamespace(db=stale_user, key=user_key), ("modified",)),
        ],
        "deletes": [SimpleNamespace(db=file_row, key=file_key)],
        "now": now,
    }

    assert credential_store.commit_plan_mutation_if_idle(
        report_key,
        **options,
    ) == credential_store.PLAN_OPERATION_BUSY
    assert rows[report_key]["proposal"] == expected["proposal"]
    assert file_key in rows
    assert applied == []

    rows[claim_key]["expires_at"] = now - timedelta(seconds=1)
    rows[report_key]["proposal"] = json.dumps({"summary": "Newer API proposal"})
    assert credential_store.commit_plan_mutation_if_idle(
        report_key,
        **options,
    ) == credential_store.PLAN_OPERATION_STALE
    assert rows[report_key]["proposal"] != browser_report["proposal"]
    assert file_key in rows

    rows[report_key]["proposal"] = expected["proposal"]
    assert credential_store.commit_plan_mutation_if_idle(
        report_key,
        **options,
    ) == credential_store.PLAN_OPERATION_COMMITTED
    assert rows[report_key]["proposal"] == browser_report["proposal"]
    assert claim_key not in rows
    assert file_key not in rows
    assert rows[user_key]["email"] == "new-profile@example.com"
    assert rows[user_key]["modified"] == "browser-touch"
    assert (user_key, ("modified",)) in applied

    # The expired API owner cannot publish even if it reloads the browser's
    # latest Report revision after losing the shared claim key.
    assert credential_store.commit_plan_operation(
        report_key,
        phase="submit",
        operation_id="submit-aaaaaaaaaaaaaaaa",
        claim_token="a" * 32,
        expected_report=dict(rows[report_key]),
        writes=[(SimpleNamespace(db=browser_report, key=report_key), None)],
        now=now,
    ) == credential_store.PLAN_OPERATION_LOST


# @matrix agent-api ai-report : browser-review cas delete file-cleanup save
@pytest.mark.unit
def test_external_browser_plan_save_and_delete_use_idle_transaction(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("external-browser-owner")
    file = _test_file("evidence.pdf")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "External browser mutation",
            "tool": "organize",
            "origin": "api",
            "status": "ready",
            "input_files": [file],
        }
    )
    expected = external_operations.report_snapshot(report)
    report.proposal = {"summary": "Skipped one action"}
    calls = []

    def commit(report_key, **options):
        calls.append((report_key, options))
        return credential_store.PLAN_OPERATION_COMMITTED

    monkeypatch.setattr(
        external_operations.agent_api_store,
        "commit_plan_mutation_if_idle",
        commit,
    )
    monkeypatch.setattr(
        external_operations,
        "execute_post_commit",
        lambda _plan: ([], []),
    )

    assert external_operations.save_plan_if_idle(
        report,
        expected,
        file,
        report,
    ) == credential_store.PLAN_OPERATION_COMMITTED
    writes = calls[-1][1]["writes"]
    masks = {entity.key: mask for entity, mask in writes}
    assert masks[report.key] is None
    assert masks[file.key] is None
    assert masks[user.key] == ("modified",)
    assert calls[-1][1]["deletes"] == []

    calls.clear()
    expected = external_operations.report_snapshot(report)
    assert external_operations.delete_plan_if_idle(
        report,
        expected,
        report,
        file,
    ) == credential_store.PLAN_OPERATION_COMMITTED
    assert calls[-1][1]["writes"] == []
    assert {entity.key for entity in calls[-1][1]["deletes"]} == {
        report.key,
        file.key,
    }


# @matrix agent-api ai-report : external-schema proposal-contract structured-output
@pytest.mark.unit
def test_external_proposal_schema_has_named_discriminated_actions():
    schema = external_api.external_report_proposal_response_schema(
        allowed_actions=(
            "create_task",
            "attach_file_to_task",
            "summarize_file",
        ),
        require_file_summary_terms=True,
    )

    assert "propertyOrdering" not in schema
    assert schema["properties"]["actions"]["items"] == {
        "oneOf": [
            {"$ref": "#/$defs/create_task"},
            {"$ref": "#/$defs/attach_file_to_task"},
            {"$ref": "#/$defs/summarize_file"},
        ],
        "discriminator": {
            "propertyName": "type",
            "mapping": {
                "create_task": "#/$defs/create_task",
                "attach_file_to_task": "#/$defs/attach_file_to_task",
                "summarize_file": "#/$defs/summarize_file",
            },
        },
    }
    create_task = schema["$defs"]["create_task"]
    assert create_task["properties"]["type"] == {
        "type": "string",
        "const": "create_task",
    }
    assert create_task["properties"]["data"]["allOf"][0]["anyOf"] == [
        {"required": ["page"]},
        {"required": ["page_action"]},
    ]
    summary_data = schema["$defs"]["summarize_file"]["properties"]["data"]
    assert "retrieval_terms" in summary_data["required"]
    assert summary_data["properties"]["retrieval_terms"]["uniqueItems"] is True
    assert summary_data["properties"]["retrieval_terms"]["items"][
        "maxLength"
    ] == 80


# @matrix agent-api ai-report : file-placement file-summary permissions proposal-contract
@pytest.mark.unit
def test_external_plan_contract_is_permission_and_file_scoped(monkeypatch):
    actor = _contract_actor()
    report = SimpleNamespace(
        tool="organize",
        input_files=[SimpleNamespace(hash="aaaaaaaaaaaa")],
    )
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page", "move_page"),
    )
    monkeypatch.setattr(
        external_api,
        "external_report_proposal_response_schema",
        lambda **options: {
            "allowed": options["allowed_actions"],
            "require_file_summary_terms": options["require_file_summary_terms"],
        },
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed": allowed},
    )
    monkeypatch.setattr(
        external_api.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    contract = external_api.plan_contract(
        report,
        actor,
        submit_url="https://example.test/api/v1/plans/report-key/submit",
    )

    assert set(contract) == {
        "contract_version",
        "tool",
        "current_date",
        "timezone",
        "personal_page",
        "submission_format",
        "proposal_schema",
        "permissions",
        "required_file_refs",
        "upload_inventory",
        "file_checklist",
        "guidance_requirements",
        "uploads_supported",
        "workflow_rules",
        "reference_rules",
        "limits",
        "payload_sizes",
    }
    assert contract["contract_version"] == external_api.CONTRACT_VERSION
    assert "version" not in contract
    assert contract["current_date"] == "2026-08-31"
    assert contract["timezone"] == "UTC"
    assert contract["personal_page"] == {
        "kind": "page",
        "hash": "hash:personalpage",
        "name": "Personal Page",
        "url": "/pages/personal-page",
        "can_view": True,
        "can_edit": True,
    }
    assert contract["workflow_rules"][0].startswith(
        "personal_page is the authenticated user's guaranteed editable Page"
    )
    assert contract["submission_format"] == {
        "method": "POST",
        "url": "https://example.test/api/v1/plans/report-key/submit",
        "contract_version": external_api.CONTRACT_VERSION,
        "body": {
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": {},
        },
        "rule": (
            "Replace the empty proposal template with an object matching "
            "proposal_schema, then send the wrapper body with the stated "
            "method and URL; do not post the proposal object as the top-level "
            "request body."
        ),
    }
    assert contract["proposal_schema"] == {
        "allowed": ("create_page", "move_page", "summarize_file"),
        "require_file_summary_terms": True,
    }
    assert contract["permissions"] == {
        "allowed": ("create_page", "move_page", "summarize_file")
    }
    assert contract["required_file_refs"] == ["hash:aaaaaaaaaaaa"]
    assert contract["upload_inventory"]["count"] == 1
    assert contract["upload_inventory"]["authoritative"] is True
    assert contract["upload_inventory"]["status"] == "finalized"
    assert contract["file_checklist"] == [
        {
            "file": "hash:aaaaaaaaaaaa",
            "inspect_complete_content": "required",
            "duplicate_check": "required",
            "destination_decision": "required",
            "placement_action": "required",
            "attachment": "at_least_one",
            "summary": "exactly_one",
        }
    ]
    assert contract["guidance_requirements"]["required_before_analysis"] == [
        {"task": "organize"}
    ]
    guidance_by_task = {
        item["request"]["task"]: item
        for item in contract["guidance_requirements"]["conditional"]
    }
    assert guidance_by_task["form_autofill"]["request"] == {
        "task": "form_autofill"
    }
    assert guidance_by_task["form_autofill"]["derived_request_arguments"] == {
        "field_types": {
            "type": "array",
            "items": {"type": "string"},
            "source": "unique type values from the exact target schemas",
        }
    }
    assert guidance_by_task["report_actions"]["request"] == {
        "task": "report_actions"
    }
    assert guidance_by_task["report_actions"]["derived_request_arguments"] == {
        "actions": {
            "type": "array",
            "items": {"type": "string"},
            "source": "unique selected proposal action types",
        }
    }
    assert "actual arrays" in contract["guidance_requirements"][
        "derived_request_rule"
    ]
    guidelines_schema = ai_functions.tool_catalog(names=["get_guidelines"])[0][
        "input_schema"
    ]
    derived_samples = {
        "field_types": ["input"],
        "actions": ["create_page"],
    }
    for task, item in guidance_by_task.items():
        assert task in guidelines_schema["properties"]["task"]["enum"]
        result, parts = ai_functions.execute_registered_tool(
            "get_guidelines",
            item["request"],
            actor,
        )
        assert result["task"] == task
        assert parts == []
        for argument, descriptor in item.get(
            "derived_request_arguments", {}
        ).items():
            live_argument = guidelines_schema["properties"][argument]
            assert descriptor["type"] == live_argument["type"] == "array"
            assert descriptor["items"]["type"] == live_argument["items"]["type"]
            selected, selected_parts = ai_functions.execute_registered_tool(
                "get_guidelines",
                {**item["request"], argument: derived_samples[argument]},
                actor,
            )
            assert selected["filters"][argument] == derived_samples[argument]
            assert selected_parts == []
    assert contract["payload_sizes"]["proposal_schema_bytes"] > 0
    assert contract["payload_sizes"]["contract_without_payload_sizes_bytes"] > 0
    assert any(
        "Upload and finalize at least one file" in rule
        for rule in contract["workflow_rules"]
    )
    assert any(
        "get_guidelines with task=organize" in rule
        for rule in contract["workflow_rules"]
    )
    assert any("two phases" in rule for rule in contract["workflow_rules"])
    assert any(
        "will not call a model" in rule for rule in contract["workflow_rules"]
    )
    assert any(
        "exactly one summarize_file" in rule
        for rule in contract["workflow_rules"]
    )
    assert any("never applies" in rule for rule in contract["workflow_rules"])
    assert any(
        "ready Organize proposal remains conversationally revisable" in rule
        for rule in contract["workflow_rules"]
    )
    assert any(
        "exact id of an earlier action" in rule
        and "never takes a workspace hash" in rule
        for rule in contract["reference_rules"]
    )
    assert any(
        "data.submission is the Form field-value object" in rule
        and "not an existing submission reference" in rule
        for rule in contract["reference_rules"]
    )
    assert contract["limits"]["max_tool_calls"] == external_api.MAX_PLAN_TOOL_CALLS


# @pairs agent-api:create-revision agent-api:organize-revision agent-api:proposal-contract ai-report:proposal-contract
# @pair ai-report:task-page
@pytest.mark.unit
def test_external_plan_contracts_distinguish_ask_and_create(monkeypatch):
    actor = _contract_actor()
    monkeypatch.setattr(
        external_api.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    ask_contract = external_api.plan_contract(
        SimpleNamespace(tool="ask", input_files=[]),
        actor,
        submit_url="https://example.test/api/v1/plans/ask/submit",
    )

    assert ask_contract["tool"] == "ask"
    assert ask_contract["uploads_supported"] is False
    assert "execution_supported" not in ask_contract
    assert ask_contract["required_file_refs"] == []
    assert "propertyOrdering" not in ask_contract["proposal_schema"]
    assert "answer_markdown" in ask_contract["proposal_schema"]["properties"]
    assert ask_contract["proposal_schema"]["properties"]["actions"]["maxItems"] == 0
    assert any("separate Create or Organize plan" in rule for rule in ask_contract["workflow_rules"])
    assert any(
        "without waiting for separate save confirmation" in rule
        for rule in ask_contract["workflow_rules"]
    )
    assert any(
        "remain available after an Ask submission" in rule
        for rule in ask_contract["workflow_rules"]
    )

    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page", "create_task", "move_page", "needs_review"),
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed_actions": list(allowed)},
    )
    create_contract = external_api.plan_contract(
        SimpleNamespace(tool="create", input_files=[]),
        actor,
        submit_url="https://example.test/api/v1/plans/create/submit",
    )

    assert create_contract["tool"] == "create"
    assert create_contract["uploads_supported"] is False
    assert "execution_supported" not in create_contract
    assert create_contract["permissions"]["allowed_actions"] == [
        "create_page",
        "create_task",
        "needs_review",
    ]
    action_items = create_contract["proposal_schema"]["properties"]["actions"][
        "items"
    ]
    assert set(action_items["discriminator"]["mapping"]) == {
        "create_page",
        "create_task",
        "needs_review",
    }
    create_page = create_contract["proposal_schema"]["$defs"]["create_page"]
    assert "document_markdown" in create_page["properties"]["data"]["properties"]
    assert any(
        "ready Create proposal remains conversationally revisable" in rule
        for rule in create_contract["workflow_rules"]
    )
    assert any(
        "authenticated website" in rule and "no execution operation" in rule
        for rule in create_contract["workflow_rules"]
    )
    assert any(
        "Every create_task action requires its editable destination Page" in rule
        and "page_name is display context only" in rule
        for rule in create_contract["reference_rules"]
    )


# @matrix agent-api : ask create organize tool-selection
@pytest.mark.unit
def test_external_plan_tool_selection_is_provider_independent():
    assert external_api.normalize_plan_tool(" Ask ") == "ask"
    with pytest.raises(exceptions.ValidationError, match="ask, create, or organize"):
        external_api.normalize_plan_tool("email")


# @source lagniappe/core/tools/ai/functions.py::tool_catalog
# @matrix agent-api ai : provider-neutral-schema tool-catalog
@pytest.mark.unit
def test_external_tool_catalog_uses_id_for_subject_entity_references():
    expected_required = {
        "get_entity": {"id"},
        "get_file": {"id"},
        "get_category_pages": {"id"},
        "get_category_forms": {"id"},
        "get_page_details": {"id"},
        "get_page_file_list": {"id"},
        "get_page_tasks": {"id"},
        "get_task_history": {"id"},
        "get_category_details": {"id"},
        "get_schema": {"id"},
        "get_form_instances": {"id"},
        "get_filter_schema": {"id"},
        "query_workspace_filter": {"id", "conditions"},
    }
    forbidden_legacy_subject_arguments = {
        "get_page_details": "page_id",
        "get_page_file_list": "page_id",
        "get_page_tasks": "page_id",
        "get_task_history": "task_id",
        "get_category_details": "category_id",
        "get_form_instances": "form_id",
        "get_filter_schema": "parent_id",
        "query_workspace_filter": "parent_id",
    }

    catalog = {tool["name"]: tool for tool in ai_functions.tool_catalog()}
    for tool_name, required in expected_required.items():
        schema = catalog[tool_name]["input_schema"]
        assert set(schema["required"]) == required
        assert "id" in schema["properties"]
    for tool_name, forbidden in forbidden_legacy_subject_arguments.items():
        assert forbidden not in catalog[tool_name]["input_schema"]["properties"]

    assert "form_id" in catalog["get_category_pages"]["input_schema"]["properties"]
    assert "parent_id" in catalog["search_entities"]["input_schema"]["properties"]


# @matrix agent-api ai : permission-context provider-neutral-dispatch provider-neutral-schema tool-catalog tool-registry
@pytest.mark.unit
def test_external_tool_catalog_and_dispatch_share_registered_tools(monkeypatch):
    names = [tool["name"] for tool in ai_functions.tool_catalog()]
    assert names == list(ai_functions.DECLARATIONS)
    assert all(tool["input_schema"]["type"] == "object" for tool in ai_functions.tool_catalog())
    assert all("output_schema" in tool for tool in ai_functions.tool_catalog())
    assert all("result_paths" in tool for tool in ai_functions.tool_catalog())
    search_definition = ai_functions.TOOL_DEFINITIONS["search_entities"]
    assert search_definition["output_schema"]["type"] == "array"
    assert search_definition["result_paths"]["primary_collection"] == "$"
    page_definition = ai_functions.TOOL_DEFINITIONS["get_page_details"]
    assert "page" in page_definition["output_schema"]["required"]
    assert page_definition["result_paths"]["primary_entity"] == "$.page"
    assert ai_functions.tool_catalog(
        names=["get_entity", "search_entities"], names_only=True
    ) == ["get_entity", "search_entities"]
    assert [
        tool["name"]
        for tool in ai_functions.tool_catalog(names=["get_entity"])
    ] == ["get_entity"]
    with pytest.raises(ValueError, match="Unknown tool names"):
        ai_functions.tool_catalog(names=["invented_tool"])
    rest_get_file = next(
        tool
        for tool in ai_functions.tool_catalog(transport="rest")
        if tool["name"] == "get_file"
    )
    assert "short-lived download URL" in rest_get_file["description"]
    assert "expires after five minutes" in rest_get_file["description"]
    assert "temporary credential" in rest_get_file["description"]
    assert "provider file part" not in rest_get_file["description"]

    seen = {}

    def execute(arguments, user):
        seen.update(arguments=arguments, user=user)
        return {"items": ["one"]}, [{"uri": "gs://private/one"}]

    actor = object()
    monkeypatch.setitem(ai_functions.HANDLERS, "search_entities", execute)
    monkeypatch.setattr(
        ai_functions,
        "normalize_hash_references",
        lambda arguments: {**arguments, "normalized": True},
    )

    result, parts = ai_functions.execute_registered_tool(
        "search_entities",
        {"query": "one"},
        actor,
    )

    assert seen == {
        "arguments": {"query": "one", "normalized": True},
        "user": actor,
    }
    assert result == {"items": ["one"]}
    assert parts == [{"uri": "gs://private/one"}]


# @matrix agent-api ai-report : file-placement file-summary permissions proposal-validation references
@pytest.mark.unit
def test_external_proposal_validation_enforces_permissions_files_and_shape(
    monkeypatch,
):
    actor = object()
    report = SimpleNamespace(
        tool="organize",
        input_files=[SimpleNamespace(hash="aaaaaaaaaaaa")],
    )
    captured = {}

    def validate(proposal, **options):
        captured.update(options)
        return proposal

    monkeypatch.setattr(external_api, "allowed_report_actions", lambda user: ("create_page",))
    monkeypatch.setattr(external_api, "validate_proposal", validate)

    proposal = {
        "summary": "Create a page for the uploaded file.",
        "confidence": 0.9,
        "issues": [],
        "actions": [],
    }
    assert external_api.validate_external_proposal(proposal, report, actor) is proposal
    assert captured["allowed_actions"] == ("create_page", "summarize_file")
    assert captured["allow_pending_submissions"] is False
    assert captured["required_file_refs"] == ["hash:aaaaaaaaaaaa"]
    assert captured["require_file_summaries"] is True
    assert captured["validate_reference_kinds"] is True

    with pytest.raises(exceptions.AIException, match="confidence"):
        external_api.validate_external_proposal(
            {**proposal, "confidence": "certain"},
            report,
            actor,
        )

    inaccessible = {
        **proposal,
        "actions": [
            {
                "id": "page-1",
                "type": "create_page",
                "data": {"category": "hash:bbbbbbbbbbbb"},
            }
        ],
    }
    monkeypatch.setattr(
        external_api.cache,
        "get_details_by_hash",
        lambda hashes: {"bbbbbbbbbbbb": {"id": "opaque-id"}},
    )
    denied = SimpleNamespace(
        hash="bbbbbbbbbbbb",
        allowed=lambda action, user: False,
    )
    monkeypatch.setattr(
        external_api.Entities,
        "fetch",
        lambda *identifiers, request: [denied],
    )
    with pytest.raises(exceptions.AIException, match="inaccessible"):
        external_api.validate_external_proposal(inaccessible, report, actor)


# @matrix agent-api : envelope schema field-path bounded-validation
@pytest.mark.unit
def test_external_submission_validation_collects_independent_field_errors():
    report = SimpleNamespace(tool="ask")
    errors = external_api.submission_validation_errors(
        {
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": {"actions": []},
        },
        report,
        object(),
    )
    by_path = {error["path"]: error for error in errors}
    assert by_path["$.proposal.summary"]["code"] == "required"
    assert by_path["$.proposal.confidence"]["code"] == "required"

    missing_wrapper = external_api.submission_validation_errors(
        {
            "summary": "This is a raw proposal, not the submission wrapper.",
            "confidence": 0.8,
            "actions": [],
        },
        SimpleNamespace(tool="organize"),
        object(),
    )
    paths = {error["path"] for error in missing_wrapper}
    assert "$.contract_version" in paths
    assert "$.proposal" in paths
    assert "$.summary" in paths
    assert len(missing_wrapper) <= external_api.MAX_VALIDATION_ERRORS

    noisy_wrapper = {
        "summary": "Still not the submission wrapper.",
        **{f"unsupported_{index}": index for index in range(30)},
    }
    bounded = external_api.submission_validation_errors(
        noisy_wrapper,
        SimpleNamespace(tool="organize"),
        object(),
    )
    assert len(bounded) == external_api.MAX_VALIDATION_ERRORS
    assert bounded[-1]["code"] == "validation_errors_truncated"


# @matrix agent-api ai-report : idempotency proposal-publication ready-state
# @pair agent-api:organize-revision
@pytest.mark.unit
def test_external_proposal_submission_is_idempotent_and_provider_free(monkeypatch):
    proposal = {
        "summary": "Create one page.",
        "confidence": 1,
        "issues": [],
        "actions": [],
    }
    saved = []
    report = SimpleNamespace(
        tool="organize",
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[object()],
        agent_manifest={"contract_version": external_api.CONTRACT_VERSION},
    )

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.summary = value["summary"]
            report.status = status

    report.properties = SimpleNamespace(process=Process())
    monkeypatch.setattr(
        external_api,
        "validate_external_proposal",
        lambda value, current_report, user, **_options: value,
    )
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    submitted = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    repeated = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    revised = external_api.submit_plan(
        report,
        object(),
        {**proposal, "summary": "Create a different page."},
        contract_version=external_api.CONTRACT_VERSION,
    )

    assert submitted is repeated is revised is report
    assert report.status == "ready"
    assert report.proposal["summary"] == "Create a different page."
    assert report.agent_manifest["proposal_fingerprint"]
    assert saved == [report, report]


# @pairs agent-api:ask agent-api:ask-revision ai-report:answer-only
@pytest.mark.unit
def test_external_ask_submission_completes_without_files_or_execution(monkeypatch):
    proposal = {
        "summary": "The page has two open tasks.",
        "answer_markdown": "## Result\n\nThere are **two** open tasks.",
        "confidence": 0.95,
        "actions": [],
    }
    report = SimpleNamespace(
        tool="ask",
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[],
        agent_manifest={"contract_version": external_api.CONTRACT_VERSION},
    )

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.summary = value["summary"]
            report.status = status

    report.properties = SimpleNamespace(process=Process())
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    submitted = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    repeated = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    revised = external_api.submit_plan(
        report,
        object(),
        {
            **proposal,
            "summary": "The page now has one open task.",
            "answer_markdown": "## Updated result\n\nThere is **one** open task.",
        },
        contract_version=external_api.CONTRACT_VERSION,
    )

    assert submitted is repeated is revised is report
    assert report.status == "complete"
    assert report.proposal["answer_markdown"].startswith("## Updated result")
    assert report.summary == "The page now has one open task."
    assert "<h2>Updated result</h2>" in report.proposal["answer_html"]
    assert saved == [report, report]


# @pairs agent-api:ask ai-report:answer-only
@pytest.mark.unit
def test_external_ask_submission_allows_hash_token_in_named_link_destination(
    monkeypatch,
):
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "8328b23bef92": {"id": "canonical-cypress-page-key"}
        },
    )
    report = SimpleNamespace(tool="ask")
    proposal = {
        "summary": "Cypress Hive has an open follow-up task.",
        "answer_markdown": (
            "Review [Cypress Hive](/pages/hash:8328b23bef92) for details."
        ),
        "confidence": 0.95,
        "actions": [],
    }

    normalized = external_api.validate_external_proposal(
        proposal,
        report,
        object(),
    )

    assert normalized["answer_markdown"].startswith("Review [Cypress Hive]")
    assert 'href="/pages/canonical-cypress-page-key"' in normalized["answer_html"]
    assert ">Cypress Hive</a>" in normalized["answer_html"]
    assert "hash:8328b23bef92" not in normalized["answer_html"]

    proposal["answer_markdown"] = "The internal reference is hash:8328b23bef92."
    with pytest.raises(exceptions.AIException, match="human names and URLs"):
        external_api.validate_external_proposal(proposal, report, object())

    proposal.pop("answer_markdown")
    proposal["answer_html"] = "<script>alert('unsafe')</script><p>Result</p>"
    with pytest.raises(exceptions.AIException, match="unsupported fields: answer_html"):
        external_api.validate_external_proposal(proposal, report, object())


# @pairs agent-api:create ai-report:proposal-publication
# @pair agent-api:create-revision
@pytest.mark.unit
def test_external_create_submission_renders_markdown_without_files(monkeypatch):
    actor = object()
    proposal = {
        "summary": "Create a field guide page.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "field-guide",
                "type": "create_page",
                "data": {
                    "name": "Field Guide",
                    "document_markdown": (
                        "# Field Guide\n\n- First item\n\n"
                        "[Source](https://example.com/reference) "
                        "[Unsafe](javascript:alert('no'))"
                    ),
                },
            }
        ],
    }
    report = SimpleNamespace(
        tool="create",
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[],
        agent_manifest={"contract_version": external_api.CONTRACT_VERSION},
    )

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.summary = value["summary"]
            report.status = status

    report.properties = SimpleNamespace(process=Process())
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page", "needs_review"),
    )
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    submitted = external_api.submit_plan(
        report,
        actor,
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    initial_document = report.proposal["actions"][0]["data"]["document"]
    assert 'href="https://example.com/reference"' in initial_document
    assert 'rel="noopener noreferrer"' in initial_document
    assert "javascript:" not in initial_document

    revised = external_api.submit_plan(
        report,
        actor,
        {
            **proposal,
            "summary": "Create a field guide page with a revised introduction.",
            "actions": [
                {
                    **proposal["actions"][0],
                    "data": {
                        **proposal["actions"][0]["data"],
                        "document_markdown": "# Field Guide\n\nA revised introduction.",
                    },
                }
            ],
        },
        contract_version=external_api.CONTRACT_VERSION,
    )

    assert submitted is revised is report
    assert report.status == "ready"
    assert submitted.input_files == []
    data = report.proposal["actions"][0]["data"]
    assert data["document_markdown"].startswith("# Field Guide")
    assert data["document"].startswith("<h1>Field Guide</h1>")
    assert "A revised introduction." in data["document"]
    assert saved == [report, report]


# @matrix agent-api ai-report : markdown public-reference round-trip stored-execution
@pytest.mark.unit
def test_public_plan_proposal_round_trips_hash_references_and_markdown(monkeypatch):
    entity = SimpleNamespace(
        urlsafe_key="ah-internal-page-key-with-enough-characters-123456",
        hash="abcdef123456",
    )
    monkeypatch.setattr(
        external_api.database_get,
        "is_urlsafe_key",
        lambda value: value == entity.urlsafe_key,
    )
    monkeypatch.setattr(
        external_api.Entities,
        "fetch",
        lambda *identifiers, request: [entity],
    )
    report = SimpleNamespace(
        tool="create",
        agent_manifest={
            "public_references": {
                entity.urlsafe_key: "hash:abcdef123456",
            }
        },
        proposal={
            "summary": "Create the page.",
            "confidence": 0.9,
            "issues": [],
            "actions": [
                {
                    "id": "page",
                    "type": "create_page",
                    "data": {
                        "name": "Field Guide",
                        "category": entity.urlsafe_key,
                        "document_markdown": "# Field Guide\n\nPublic source.",
                        "document": "<h1>Field Guide</h1><p>Public source.</p>",
                        "submission": {
                            "related-page": f"/pages/{entity.urlsafe_key}",
                        },
                    },
                }
            ],
        },
    )

    public = external_api.public_plan_proposal(report)

    assert public["actions"][0]["data"] == {
        "name": "Field Guide",
        "category": "hash:abcdef123456",
        "document_markdown": "# Field Guide\n\nPublic source.",
        "submission": {
            "related-page": "/pages/hash:abcdef123456",
        },
    }
    assert report.proposal["actions"][0]["data"]["category"] == entity.urlsafe_key


# @matrix agent-api files : complete-inventory deterministic-fingerprint seven-file-regression
@pytest.mark.unit
def test_external_plan_contract_inventories_all_seven_finalized_files(monkeypatch):
    actor = _contract_actor()
    files = [
        SimpleNamespace(
            hash=f"{index:012d}",
            name=f"File {index}",
            filename=f"file-{index}.txt",
            mimetype="text/plain",
            size=index + 1,
        )
        for index in range(7)
    ]
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("attach_file_to_page",),
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed_actions": list(allowed)},
    )
    monkeypatch.setattr(
        external_api.dates,
        "user_today",
        lambda _user=None: datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    report = SimpleNamespace(tool="organize", input_files=files, upload_manifest=None)
    contract = external_api.plan_contract(
        report,
        actor,
        submit_url="https://example.test/api/v1/plans/report-key/submit",
    )
    repeated_inventory = external_api.report_file_inventory(report)

    assert contract["upload_inventory"]["count"] == 7
    assert repeated_inventory["fingerprint"] == contract["upload_inventory"][
        "fingerprint"
    ]
    assert len(contract["required_file_refs"]) == 7
    assert [item["file"] for item in contract["file_checklist"]] == (
        contract["required_file_refs"]
    )


# @matrix agent-api : authentication expiry issue revoke shown-once
@pytest.mark.unit
def test_issue_authenticate_expire_and_revoke_credential(monkeypatch):
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    user = _test_user("credential-owner")
    rows = {}

    def rotate(identifier, user_key, **values):
        row = {
            **values,
            "credential_id": identifier,
            "user": user_key,
            "active": True,
            "generation": int(rows.get(identifier, {}).get("generation") or 0) + 1,
        }
        rows[identifier] = row
        return row

    def revoke(identifier, user_key, **values):
        row = rows[identifier]
        assert row["user"] == user_key
        row = {
            **row,
            **values,
            "active": False,
            "generation": row["generation"] + 1,
        }
        row.pop("token_digest")
        rows[identifier] = row
        return row

    monkeypatch.setattr(credential_store, "rotate_credential", rotate)
    monkeypatch.setattr(credential_store, "revoke_credential", revoke)
    monkeypatch.setattr(
        credential_store,
        "get_credential",
        lambda identifier: rows.get(identifier),
    )
    monkeypatch.setattr(
        agent_auth.Entities,
        "fetch_one",
        lambda identifier, request: user,
    )
    monkeypatch.setattr(CONFIG, "SECRET_KEY", "agent-api-test-secret")

    token, issued = agent_auth.issue_credential(user, now=now)
    authenticated, metadata = agent_auth.authenticate_credential(token, now=now)

    assert authenticated is user
    assert issued == metadata
    assert issued["active"] is True
    assert token.startswith("lgn_")
    assert token not in repr(rows)
    assert agent_auth.credential_status(user, now=now)["active"] is True

    with pytest.raises(agent_auth.AgentAPICredentialError, match="expired"):
        agent_auth.authenticate_credential(
            token,
            now=now + agent_auth.TOKEN_LIFETIME + timedelta(seconds=1),
        )

    revoked = agent_auth.revoke_credential(user, now=now)
    assert revoked["active"] is False
    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(token, now=now)

    replacement_token, replacement = agent_auth.issue_credential(user, now=now)
    assert replacement["active"] is True
    assert replacement["generation"] == revoked["generation"] + 1
    assert replacement_token != token
    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(token, now=now)
    authenticated, metadata = agent_auth.authenticate_credential(
        replacement_token,
        now=now,
    )
    assert authenticated is user
    assert metadata == replacement


# @matrix agent-api : authentication tamper user-binding
@pytest.mark.unit
def test_authenticate_rejects_tampered_and_mismatched_credentials(monkeypatch):
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    user = _test_user("credential-mismatch-owner")
    token = (
        f"lgn_{agent_auth.credential_id(user)}."
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN12"
    )
    row = {
        "user": user.key,
        "active": True,
        "generation": 1,
        "token_digest": agent_auth._token_digest(token),
        "issued_at": now,
        "expires_at": now + timedelta(days=1),
    }
    monkeypatch.setattr(credential_store, "get_credential", lambda identifier: row)
    monkeypatch.setattr(agent_auth.Entities, "fetch_one", lambda identifier, request: user)

    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(f"{token[:-1]}x", now=now)

    monkeypatch.setattr(agent_auth, "credential_id", lambda current_user: "x" * 24)
    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(token, now=now)


# @matrix agent-api : credential persistence revoke rotate
@pytest.mark.unit
def test_credential_rotation_and_revocation_are_transactional(monkeypatch):
    key = Key("agent-api", "credential", project="test-project")
    rows = {}
    transactions = []

    class Transaction:
        def __enter__(self):
            transactions.append(self)
            return self

        def __exit__(self, *args):
            return False

        def put(self, row):
            rows[row.key] = row

    class Datastore:
        def transaction(self):
            return Transaction()

        def get(self, requested, transaction=None):
            assert transaction in transactions
            return rows.get(requested)

    monkeypatch.setattr(credential_store, "credential_key", lambda identifier: key)
    monkeypatch.setattr(credential_store.DATA, "_datastore_client", Datastore())
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)

    first = credential_store.rotate_credential(
        "credential",
        "user-key",
        token_digest="first",
        display_prefix="lgn_first",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    second = credential_store.rotate_credential(
        "credential",
        "user-key",
        token_digest="second",
        display_prefix="lgn_second",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    second_generation = second["generation"]
    revoked = credential_store.revoke_credential(
        "credential",
        "user-key",
        revoked_at=now,
    )
    replacement = credential_store.rotate_credential(
        "credential",
        "user-key",
        token_digest="replacement",
        display_prefix="lgn_replacement",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )

    assert first["generation"] == 1
    assert second_generation == 2
    assert revoked["generation"] == 3
    assert revoked["active"] is False
    assert "token_digest" not in revoked
    assert replacement["generation"] == 4
    assert replacement["active"] is True
    assert replacement["token_digest"] == "replacement"
    assert len(transactions) == 4


# @matrix agent-api ai-report mcp-upload : deterministic-file-identity lease-renewal upload-finalization temporary-view-ownership
@pytest.mark.unit
def test_external_upload_finalization_binds_report_user(monkeypatch):
    actor = object()
    captured = {}
    batch_id = "batch-aaaaaaaaaaaaaaaa"
    report_key = Key("activity", "report", project="test-project")
    file_key = Key("files", "stable-file", project="test-project")
    report = SimpleNamespace(
        key=report_key,
        upload_manifest=[
            {
                "token": "storage-token",
                "input_name": "agent-api-files",
                "filename": "records.pdf",
                "upload_batch_id": batch_id,
            }
        ],
    )

    def finalize(
        current,
        user,
        *,
        file_factory,
        failed_file_cleanup=None,
        ensure_active=None,
        save=None,
    ):
        assert current is report
        assert save is None
        assert callable(failed_file_cleanup)
        captured["failed_file_cleanup"] = failed_file_cleanup
        captured["user"] = user
        if ensure_active:
            ensure_active()
        captured["upload"] = SimpleNamespace(record=current.upload_manifest[0])
        captured["file"] = file_factory(
            upload=captured["upload"],
            data={"filename": "records.pdf"},
        )
        return [captured["file"]]

    monkeypatch.setattr(external_api, "finalize_report_upload_manifest", finalize)
    monkeypatch.setattr(
        credential_store,
        "upload_file_key",
        lambda current_report_key, current_batch_id, index: file_key,
    )
    monkeypatch.setattr(
        external_api.Entities.FILE,
        "create",
        lambda **options: SimpleNamespace(**options),
    )
    active_checks = []
    deleted_generations = []
    monkeypatch.setattr(
        external_api.storage_assets,
        "delete_file_generation",
        lambda path, visibility, generation: deleted_generations.append(
            (path, visibility, generation)
        ),
    )

    files = external_api.finalize_uploads(
        report,
        actor,
        asset_nonce="a" * 32,
        ensure_active=lambda: active_checks.append(True),
    )

    assert files == [captured["file"]]
    assert captured["user"] is actor
    assert captured["file"].report_user is actor
    assert captured["file"].key == file_key
    assert report.upload_manifest[0]["file_index"] == 0
    assert report.upload_manifest[0]["file_key"]
    assert active_checks == [True]
    assert captured["file"]._agent_upload_asset_nonce == "a" * 32

    captured["upload"].lagniappe_saved_destination = {
        "path": "private/files/stable-file.attempt-aaaaaaaa",
        "visibility": "private",
        "generation": 17,
    }
    captured["failed_file_cleanup"](
        file=captured["file"],
        upload=captured["upload"],
        error=RuntimeError("ambiguous transaction response"),
        checkpoint_disposition="ambiguous",
    )
    assert deleted_generations == []

    captured["failed_file_cleanup"](
        file=captured["file"],
        upload=captured["upload"],
        error=SimpleNamespace(code="plan_operation_lost"),
        checkpoint_disposition="not_committed",
    )
    assert deleted_generations == [
        ("private/files/stable-file.attempt-aaaaaaaa", "private", 17)
    ]
