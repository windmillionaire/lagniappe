"""Transactional guard reads preserve every precondition while batching keys."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted, ServiceUnavailable
from google.auth.credentials import AnonymousCredentials
from google.cloud.datastore import Client, Entity, helpers
from google.cloud.datastore_v1.types import BeginTransactionResponse, CommitResponse, LookupResponse

from lagniappe.core.exceptions import MutationConflict
from lagniappe.core.tools.database import deferred_jobs, transactions, utility

pytestmark = pytest.mark.unit


@pytest.fixture
def guard_store(monkeypatch):
    """Keep the Datastore SDK and transaction protocol; replace only RPCs."""
    client = Client(project="guard-tests", credentials=AnonymousCredentials())
    rows, transaction_ids = {}, []

    def begin(**kwargs):
        transaction_id = f"transaction-{len(transaction_ids)}".encode()
        transaction_ids.append(transaction_id)
        return BeginTransactionResponse(transaction=transaction_id)

    def lookup(*, request, **kwargs):
        found, missing = [], []
        # Provider order is unrelated to requested key order.
        for key_pb in reversed(request["keys"]):
            key = helpers.key_from_protobuf(key_pb)
            if key in rows:
                found.append({"entity": helpers.entity_to_protobuf(rows[key])})
            else:
                missing.append({"entity": {"key": key_pb}})
        return LookupResponse(found=found, missing=missing)

    api = SimpleNamespace(
        begin_transaction=Mock(side_effect=begin),
        lookup=Mock(side_effect=lookup),
        commit=Mock(return_value=CommitResponse()),
        rollback=Mock(),
    )
    client._datastore_api_internal = api
    data = SimpleNamespace(datastore=client)
    monkeypatch.setattr(utility, "DATA", data)
    monkeypatch.setattr(deferred_jobs, "DATA", data)
    monkeypatch.setattr(transactions.time, "sleep", lambda _seconds: None)

    def row(name, **values):
        entity = Entity(client.key("records", name))
        entity.update(values)
        rows[entity.key] = entity
        return entity

    return SimpleNamespace(client=client, rows=rows, row=row, api=api,
                           lookup=lookup, transaction_ids=transaction_ids)


# @matrix mutations : concurrency batched-reads
def test_guarded_write_batches_distinct_keys_and_matches_unordered_results(guard_store):
    page = guard_store.row("page", assets="saved", unrelated="kept")
    form = guard_store.row("form", generation=2)
    history_key = guard_store.client.key("records", "new-history")
    guards = [
        (page.key, {"assets": "saved"}),
        (history_key, None),
        (form.key, utility.ExactEntityState(generation=2)),
        (page.key, {"unrelated": "kept"}),
        (history_key, None),
    ]
    updated = Entity(page.key)
    updated.update(assets="next", unrelated="kept")
    utility._save_guarded_mutations([(SimpleNamespace(db=updated), ("assets",))], [], guards)

    lookup, = guard_store.api.lookup.call_args_list
    assert lookup.kwargs["request"]["keys"] == [
        page.key.to_protobuf(), history_key.to_protobuf(), form.key.to_protobuf(),
    ]
    assert lookup.kwargs["request"]["read_options"].transaction == guard_store.transaction_ids[0]
    commit = guard_store.api.commit.call_args.kwargs["request"]
    assert commit["transaction"] == guard_store.transaction_ids[0]
    mutation, = commit["mutations"]
    assert mutation.update.properties["assets"].string_value == "next"
    assert list(mutation.property_mask.paths) == ["assets"]


# @matrix mutations : concurrency batched-reads
@pytest.mark.parametrize("saved,expectations,conflict", [
    (None, [None, None], False),
    ({}, [None, {}], True),
    ({}, [{}, None], True),
    (None, [{}, None], True),
    (None, [None, {}], True),
    ({}, [{}, {"absent": None}], False),
    ({}, [utility.ExactEntityState()], False),
    (None, [utility.ExactEntityState()], True),
    ({"version": 2}, [{"version": 1}, {"version": 2}], True),
    ({"version": 2}, [{"version": 2}, {"version": 1}], True),
    ({"version": 2, "extra": True}, [{"version": 2}], False),
    ({"version": 2, "extra": True}, [utility.ExactEntityState(version=2), {"version": 2}], True),
    ({"version": 2}, [utility.ExactEntityState(version=2, absent=None)], True),
])
def test_guarded_write_enforces_every_expectation(guard_store, saved, expectations, conflict):
    key = guard_store.client.key("records", "guarded")
    if saved is not None:
        guard_store.row("guarded", **saved)
    output = Entity(key)
    output["version"] = 3
    guards = [(key, expected) for expected in expectations]
    if conflict:
        with pytest.raises(MutationConflict, match="Saved state changed"):
            utility._save_guarded_mutations([(SimpleNamespace(db=output), None)], [], guards)
        guard_store.api.commit.assert_not_called()
        guard_store.api.rollback.assert_called_once()
    else:
        utility._save_guarded_mutations([(SimpleNamespace(db=output), None)], [], guards)
        guard_store.api.commit.assert_called_once()
    guard_store.api.lookup.assert_called_once()
    assert guard_store.api.lookup.call_args.kwargs["request"]["keys"] == [key.to_protobuf()]


# @matrix mutations : concurrency batched-reads
@pytest.mark.parametrize("count,sizes", [(0, []), (1000, [1000]), (1001, [1000, 1]), (2001, [1000, 1000, 1])])
def test_guard_reads_respect_lookup_limit_and_skip_empty_input(guard_store, count, sizes):
    keys = [guard_store.client.key("records", str(index)) for index in range(count)]
    guards = [(key, None) for key in keys + keys[:2]]
    with guard_store.client.transaction() as transaction:
        utility.check_mutation_guards(transaction, iter(guards))
    requests = [call.kwargs["request"] for call in guard_store.api.lookup.call_args_list]
    assert [len(request["keys"]) for request in requests] == sizes
    assert [key for request in requests for key in request["keys"]] == [key.to_protobuf() for key in keys]
    assert all(request["read_options"].transaction == guard_store.transaction_ids[0] for request in requests)


# @matrix mutations : concurrency batched-reads
@pytest.mark.parametrize("unresolved", [False, True])
def test_guard_reads_resolve_deferred_keys_before_accepting_absence(guard_store, monkeypatch, unresolved):
    from google.cloud.datastore import client as datastore_client

    monkeypatch.setattr(datastore_client, "_MAX_LOOPS", 2)
    key = guard_store.client.key("records", "deferred")
    output = Entity(key)
    output["version"] = 1
    attempts = []

    def lookup(*, request, **kwargs):
        attempts.append(request)
        if unresolved or len(attempts) == 1:
            return LookupResponse(deferred=request["keys"])
        return guard_store.lookup(request=request)

    guard_store.api.lookup.side_effect = lookup
    if unresolved:
        with pytest.raises(ServiceUnavailable, match="did not resolve"):
            utility._save_guarded_mutations([(SimpleNamespace(db=output), None)], [], [(key, None)])
        guard_store.api.commit.assert_not_called()
    else:
        utility._save_guarded_mutations([(SimpleNamespace(db=output), None)], [], [(key, None)])
        guard_store.api.commit.assert_called_once()
    assert len(attempts) == 2
    assert all(request["read_options"].transaction == guard_store.transaction_ids[0] for request in attempts)


# @matrix mutations : concurrency batched-reads
@pytest.mark.parametrize("changed", [False, True])
def test_guarded_write_rechecks_batched_guards_after_aborted_commit(guard_store, changed):
    saved = guard_store.row("guarded", version=1)
    output = Entity(saved.key)
    output["version"] = 2

    def commit(**kwargs):
        if guard_store.api.commit.call_count == 1:
            if changed:
                saved["version"] = 9
            raise Aborted("Concurrent transaction")
        return CommitResponse()

    guard_store.api.commit.side_effect = commit
    if changed:
        with pytest.raises(MutationConflict):
            utility._save_guarded_mutations([(SimpleNamespace(db=output), None)], [], [(saved.key, {"version": 1})])
        assert guard_store.api.commit.call_count == 1
    else:
        utility._save_guarded_mutations([(SimpleNamespace(db=output), None)], [], [(saved.key, {"version": 1})])
        assert guard_store.api.commit.call_count == 2
    assert len(guard_store.transaction_ids) == 2
    assert [call.kwargs["request"]["read_options"].transaction
            for call in guard_store.api.lookup.call_args_list] == guard_store.transaction_ids


# @matrix mutations : concurrency batched-reads
@pytest.mark.parametrize("conflict", [False, True])
def test_atomic_job_start_enforces_duplicate_guards_before_writing(guard_store, conflict):
    source = guard_store.row("report", revision=2, status="ready")
    job_row = Entity(guard_store.client.key("records", "job"))
    job_row["status"] = "queued"
    job = SimpleNamespace(key=job_row.key, db=job_row, properties=None, exclude_from_index=())
    guards = [(source.key, {"revision": 1 if conflict else 2}), (source.key, {"status": "ready"})]
    if conflict:
        with pytest.raises(MutationConflict):
            deferred_jobs.create_deferred_job_if_absent(job, guards=guards)
        guard_store.api.commit.assert_not_called()
    else:
        result = deferred_jobs.create_deferred_job_if_absent(job, guards=guards)
        assert result["created"] is True
        commit = guard_store.api.commit.call_args.kwargs["request"]
        assert any(mutation.upsert.key == job_row.key.to_protobuf() for mutation in commit["mutations"])
    requests = [call.kwargs["request"] for call in guard_store.api.lookup.call_args_list]
    assert sum(key == source.key.to_protobuf() for request in requests for key in request["keys"]) == 1
    assert all(request["read_options"].transaction == guard_store.transaction_ids[0] for request in requests)


@pytest.mark.parametrize(
    "racing_write", ["hint", "cleared_hint", "added", "removed", "changed", "deleted", "strict_guard"]
)
def test_page_form_save_preserves_note_hint_and_rejects_other_changes(guard_store, monkeypatch, racing_write):
    from copy import deepcopy
    from datetime import UTC, datetime, timedelta

    from lagniappe.core.entities import Entities
    from lagniappe.core.tools.forms.review import stage_submission_guard

    revision = datetime(2025, 5, 1, tzinfo=UTC)
    current = guard_store.row(
        "page", type="page", modified=revision,
        **{"legacy.field": "remove locally", "access": "original"},
    )
    current["name"] = "Old"
    if racing_write == "cleared_hint":
        current.update(has_notes=False, notes_checked_revision=revision)
    form_page = Entities.PAGE(deepcopy(current))
    notes_page = Entities.PAGE(deepcopy(current))
    assert stage_submission_guard(form_page, {"form-revision": form_page.autofill_revision})

    def save_note_hint(page, *, property_mask):
        current.update({name: page.db[name] for name in property_mask})

    monkeypatch.setattr(Entities, "save_root", save_note_hint)
    if racing_write == "cleared_hint":
        current.pop("has_notes")
        current.pop("notes_checked_revision")
    else:
        notes_page.remember_empty_notes()
        assert current["notes_checked_revision"] == revision
    form_page.db.pop("legacy.field")
    form_page.db.update(name="Edited", modified=revision + timedelta(seconds=1))
    if racing_write == "added":
        current["restricted_to"] = "new permission"
    elif racing_write == "removed":
        current.pop("access")
    elif racing_write == "changed":
        current["name"] = "Another edit"
    elif racing_write == "deleted":
        del guard_store.rows[current.key]

    writes = [(form_page, None)]
    guards = form_page._form_additional_guards
    if racing_write == "strict_guard":
        guards = [*guards, (current.key, utility.ExactEntityState(guards[0][1]))]
    if racing_write not in {"hint", "cleared_hint"}:
        with pytest.raises(MutationConflict):
            utility._save_guarded_mutations(writes, [], guards)
        guard_store.api.commit.assert_not_called()
        return

    utility._save_guarded_mutations(writes, [], guards)
    [mutation] = guard_store.api.commit.call_args.kwargs["request"]["mutations"]
    saved = helpers.entity_from_protobuf(mutation.upsert)
    assert saved.key == current.key
    assert saved["name"] == "Edited" and "legacy.field" not in saved
    if racing_write == "hint":
        assert saved["has_notes"] is False and saved["notes_checked_revision"] == revision
        assert "has_notes" not in form_page.db
    else:
        assert "has_notes" not in saved and "notes_checked_revision" not in saved
        assert form_page.db["has_notes"] is False
    assert Entities.PAGE(saved).has_notes  # Old observations never hide notes at a later revision.


def test_task_form_save_still_guards_the_whole_row(guard_store):
    from copy import deepcopy

    from lagniappe.core.entities import Entities
    from lagniappe.core.tools.forms.review import stage_submission_guard

    current = guard_store.row("task", type="task")
    task = Entities.TASK(deepcopy(current))
    assert stage_submission_guard(task, {"form-revision": task.autofill_revision})
    current["has_notes"] = False
    with pytest.raises(MutationConflict):
        utility._save_guarded_mutations([(task, None)], [], task._form_additional_guards)
    guard_store.api.commit.assert_not_called()
