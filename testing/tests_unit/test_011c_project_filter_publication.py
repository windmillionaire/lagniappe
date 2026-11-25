"""Project filter coordination at the Redis and Datastore boundaries."""

import json
from unittest.mock import MagicMock, Mock

import pytest
from redis.exceptions import WatchError

from lagniappe.core.tools.cache import project_filters as filters


pytestmark = pytest.mark.unit


@pytest.fixture
def backend(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(filters.filter_cache, "_redis", client)
    return client


def test_second_cold_reader_joins_the_finished_build(backend, monkeypatch):
    # The index appears while this reader is waiting to acquire the lease.
    monkeypatch.setattr(filters.filter_cache, "query", Mock(side_effect=[None, []]))
    load = Mock(side_effect=AssertionError("a second full scan ran"))
    filters.ensure("index", "project", load, Mock(), force=False)
    backend.lock.return_value.acquire.assert_called_once_with(blocking=False)
    load.assert_not_called()


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

    assert filters._publish("index", "project", rows, start, lease) is (not expect_reload)
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

    assert not filters._publish("index", "project", {}, start, lease)
    assert lease.owned.call_count == 2
    pipe.execute.assert_called_once()


def test_dirty_refresh_reloads_after_a_concurrent_write_and_drops_a_departed_task(backend, monkeypatch):
    marker = {"id": "task-key", "cache_key": "task"}
    monkeypatch.setattr(filters.filter_cache, "query", Mock(return_value=[marker]))
    pipe = backend.pipeline.return_value.__enter__.return_value
    pipe.execute.side_effect = [WatchError(), []]
    reload_rows = Mock(side_effect=[{"task": {"name": "Old"}}, {}])
    load = Mock(side_effect=AssertionError("an incremental refresh ran a full scan"))

    filters.ensure("index", "project", load, reload_rows, force=False)
    assert reload_rows.call_count == 2
    pipe.json.return_value.delete.assert_called_once_with("index", "$.task")
