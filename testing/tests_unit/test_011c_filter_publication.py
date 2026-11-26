"""Filter coordination at the Redis and Datastore boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from redis.exceptions import WatchError

from lagniappe.core.tools.cache import filter_publication as filters


pytestmark = pytest.mark.unit


@pytest.fixture
def backend(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(filters.filter_cache, "_redis", client)
    return client


@pytest.mark.parametrize("kind", ["category", "project"])
def test_second_cold_reader_joins_the_finished_build(backend, monkeypatch, kind):
    # The index appears while this reader is waiting to acquire the lease.
    from lagniappe.core.tools.filters.cache import FilterCache

    reader = FilterCache(SimpleNamespace(kind=kind, hash="parent"), user=Mock())
    monkeypatch.setattr(filters.filter_cache, "query", Mock(side_effect=[None, []]))
    backend.lock.return_value.acquire.return_value = False
    reader.cache()
    backend.lock.return_value.acquire.assert_called_once_with(blocking=False)


@pytest.mark.parametrize(("changed", "checkpoint_present", "expect_reload"), [
    (["project", "new-task"], True, True),       # new member was absent from the snapshot
    (["other-project", "old-task"], True, True), # moved out, or removed without a published index
    (["other-project", "other-task"], True, False),
    (["*"], True, True),                         # oversized write batch
    (["other-project"], False, True),            # eviction or trimmed history
])
def test_only_covered_unchanged_snapshots_can_publish(backend, changed, checkpoint_present, expect_reload):
    start = b'["start",[]]'
    edit = json.dumps(["edit", changed]).encode()
    backend.lindex.return_value = edit
    backend.lrange.return_value = [edit, start] if checkpoint_present else [edit]
    pipe = backend.pipeline.return_value.__enter__.return_value
    lease = Mock()
    lease.owned.return_value = True
    rows = {"old-task": {"name": "First"}}

    assert filters._publish("index", "project", "history", rows, start, lease) is (not expect_reload)
    if expect_reload:
        pipe.execute.assert_not_called()
    else:
        command, key, path, document = pipe.execute_command.call_args.args
        assert (command, key, path) == ("JSON.SET", "index", "$")
        assert json.loads(document) == {
            "old-task": {"name": "First"}, "access": {"hash": "project"},
        }
        pipe.execute.assert_called_once()


def test_publisher_rechecks_ownership_after_a_transaction_conflict(backend):
    start = b'["start",[]]'
    backend.lindex.return_value = start
    pipe = backend.pipeline.return_value.__enter__.return_value
    pipe.execute.side_effect = WatchError()
    lease = Mock()
    lease.owned.side_effect = [True, False]

    assert not filters._publish("index", "project", "history", {}, start, lease)
    assert lease.owned.call_count == 2
    pipe.execute.assert_called_once()


def test_dirty_refresh_reloads_after_a_concurrent_write_and_drops_a_departed_task(backend, monkeypatch):
    marker = {"id": "task-key", "cache_key": "task"}
    monkeypatch.setattr(filters.filter_cache, "query", Mock(return_value=[marker]))
    pipe = backend.pipeline.return_value.__enter__.return_value
    pipe.execute.side_effect = [WatchError(), []]
    reload_rows = Mock(side_effect=[{"task": {"name": "Old"}}, {}])
    load = Mock(side_effect=AssertionError("an incremental refresh ran a full scan"))

    filters.ensure("index", "project", "history", load, reload_rows, force=False)
    assert reload_rows.call_count == 2
    pipe.json.return_value.delete.assert_called_once_with("index", "$.task")


def test_mixed_batch_fences_each_domain_and_all_destination_categories(backend):
    page = SimpleNamespace(kind="page", hash="page")
    task = SimpleNamespace(kind="task", hash="task")
    user = SimpleNamespace(kind="user", hash="page")
    filters.record_changes([page, task, user], {"page": {"primary", "additional"}, "task": {"project"}})
    pipe = backend.pipeline.return_value.__enter__.return_value
    events = {call.args[0]: json.loads(call.args[1])[1] for call in pipe.lpush.call_args_list}
    assert events == {
        filters.Keys.PROJECT_FILTER_CHANGES.value: ["project", "task"],
        filters.Keys.CATEGORY_FILTER_CHANGES.value: ["additional", "page", "primary"],
    }
    pipe.execute.assert_called_once()


def test_modified_only_user_and_page_with_the_same_hash_refresh_the_page(backend, monkeypatch):
    from lagniappe.core.tools.cache import add

    page = SimpleNamespace(kind="page", hash="shared", urlsafe_key="page-id")
    user = SimpleNamespace(kind="user", hash="shared", urlsafe_key="user-id")
    monkeypatch.setattr(add.filter_cache, "get_existing_parents", lambda hashes: {"shared": ["index"]})
    monkeypatch.setattr(add.cache, "_redis", backend)
    add.invalidate_revisions(page, user)

    pipe = backend.pipeline.return_value.__enter__.return_value
    history, event = pipe.lpush.call_args.args
    assert history == filters.Keys.CATEGORY_FILTER_CHANGES.value
    assert json.loads(event)[1] == ["shared"]
    pipe.json.return_value.set.assert_called_once_with(
        "index", "$.shared", {"refresh": 1, "id": "page-id", "cache_key": "shared"}, xx=True,
    )


def test_a_page_without_a_search_row_still_signals_each_filter_parent(backend, monkeypatch):
    from lagniappe.core.tools.cache import add

    page = SimpleNamespace(kind="page", hash="page", db={"active": True}, to_cache={},
                           categories=[SimpleNamespace(hash="primary"), SimpleNamespace(hash="additional")])
    monkeypatch.setattr(add.filter_cache, "get_existing_parents", lambda hashes: {})
    monkeypatch.setattr(add.filter_cache, "get_new_parents", lambda parents: [])
    add.update(page)

    pipe = backend.pipeline.return_value.__enter__.return_value
    history, event = pipe.lpush.call_args.args
    assert history == filters.Keys.CATEGORY_FILTER_CHANGES.value
    assert json.loads(event)[1] == ["additional", "page", "primary"]
