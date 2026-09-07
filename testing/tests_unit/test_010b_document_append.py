"""Server document appends preserve CRDT identity, drafts, and durable state."""

import copy
import hashlib
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from google.cloud import datastore

from lagniappe.core import exceptions
from lagniappe.core.definitions import MutationIntentType
from lagniappe.core.entities import Entities
from lagniappe.core.mutations import executor, plan_document_checkpoint
from lagniappe.core.mixins.assets import AssetMixin
from lagniappe.core.properties.common_assets import Document
from lagniappe.core.tools import document_crdt as crdt, document_updates
from lagniappe.core.tools.cache import documents
from lagniappe.core.tools.ai.reporting.execution.actions import documents as actions
from lagniappe.core.tools.database import utility
from lagniappe.core.tools.files.html import render_markdown
from testing.tests_unit.test_010_sync_cache import _DocumentRedis
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


class _DocumentEntity(AssetMixin):
    def __init__(self, definition=None):
        self.hash = "checkpoint-page"
        self.db = {"assets": definition} if definition else {}
        self.mutation_intents = []

    def add_mutation_intents(self, *intents):
        self.mutation_intents.extend(intents)


# @source lagniappe/core/properties/common_assets.py::Document.save
# @source lagniappe/core/mutations/base.py::MutationPlanBuilder.consume_intents
# @source lagniappe/core/entities/entity.py::Entity.add_mutation_intents
# @matrix editor mutations : document durable-first cleanup named-versions
@pytest.mark.parametrize("failure", [None, "commit", "cache"])
def test_document_save_retires_only_superseded_blobs_after_commit(monkeypatch, failure):
    from lagniappe.core.tools.database import assets

    row = datastore.Entity(key=datastore.Key("pages", "document", project="test-project"))
    row.update(type="page", hash="document", assets=json.dumps({
        "document": {"type": "html", "path": "old.html", "fingerprint": "old"},
        "snapshot": {"type": "ydoc", "path": "old.ydoc"},
        "image_keep": {"type": "image", "path": "image.png"},
    }), document_history=True)
    page = Entities.PAGE(row)
    stored = {"old.html": "old", "old.ydoc": "old", "image.png": "image", "named.html": "pinned"}
    events = []
    monkeypatch.setattr(assets, "save_text", lambda content, path, *args: stored.update({path: content}))

    def commit(*args, **kwargs):
        events.append("commit")
        if failure == "commit":
            raise RuntimeError("commit failed")

    def refresh(*args):
        if failure == "cache":
            raise RuntimeError("cache failed")

    def cleanup(private, public):
        events.append("cleanup")
        for path in private + public:
            stored.pop(path)
        return []

    monkeypatch.setattr(executor.database_utility, "save_mutations", commit)
    monkeypatch.setattr(executor.database_utility, "delete_blobs", cleanup)
    monkeypatch.setattr(executor.cache, "update", refresh)
    monkeypatch.setattr(executor.cache, "update_owner_projection", lambda *args: None)
    monkeypatch.setattr(executor, "capture", lambda *args, **kwargs: None)
    for text in ("first", "second", "third"):
        page.properties.document.save(html=f"<p>{text}</p>", ydoc=text)
        assert page.db["document_history"] is True  # preserve existing versions
        assert all(intent.intent is MutationIntentType.BLOB_DELETE for intent in page.mutation_intents)
        plan = plan_document_checkpoint(page)
        if failure == "commit":
            with pytest.raises(RuntimeError, match="commit failed"):
                executor.execute_mutation(plan)
            assert events == ["commit"]
            assert stored["old.html"] == "old" and stored["old.ydoc"] == "old"
            assert page.mutation_intents  # retry still owns cleanup
            return
        outcome = executor.execute_mutation(plan)
        assert outcome.durable_committed
        assert stored[page.assets["document"]["path"]] == f"<p>{text}</p>"
        assert stored[page.assets["snapshot"]["path"]] == text
        assert stored["image.png"] == "image" and stored["named.html"] == "pinned"
        if failure == "cache":
            assert not outcome.post_commit_complete
            # Existing post-commit error reporting must not undo the new pair.
            assert stored["old.html"] == "old"
            return
        assert outcome.complete
        assert len(stored) == 4  # current pair, existing image, named version
        assert events[-2:] == ["commit", "cleanup"]


# @source lagniappe/core/properties/common_assets.py::Document.save
# @matrix editor : document isolated-checkpoint tombstones
def test_document_checkpoint_blobs_are_isolated_and_empty_snapshots_survive(
    monkeypatch,
):
    from lagniappe.core.tools.database import assets

    stored = {}
    monkeypatch.setattr(
        assets, "save_text", lambda content, path, *args: stored.update({path: content})
    )
    monkeypatch.setattr(
        assets,
        "delete_file",
        lambda *args: pytest.fail("Checkpoint deleted a prior blob"),
    )
    original = _DocumentEntity()
    document = SimpleNamespace(
        entity=original, id="document", _ydoc_id="snapshot"
    )
    Document.save(document, html="<p>Original</p>", ydoc="initial-snapshot")
    old_paths = {name: item["path"] for name, item in original.assets.items()}
    loser = _DocumentEntity(original.db["assets"])
    Document.save(document, html="<p>Winner</p>", ydoc="winner-snapshot")
    winner_paths = {name: item["path"] for name, item in original.assets.items()}
    Document.save(
        SimpleNamespace(
            entity=loser, id="document", _ydoc_id="snapshot"
        ),
        html="<p>Loser</p>",
        ydoc="loser-snapshot",
    )
    assert stored[old_paths["document"]] == "<p>Original</p>"
    assert stored[winner_paths["document"]] == "<p>Winner</p>"
    assert all(intent.intent is MutationIntentType.BLOB_DELETE for intent in original.mutation_intents)
    assert {intent.path for intent in original.mutation_intents}.issuperset(old_paths.values())

    # Equal contents in separate attempts still need distinct paths so delayed
    # cleanup cannot remove a future winner or a restored version.
    same = _DocumentEntity()
    Document.save(
        SimpleNamespace(entity=same, id="document", _ydoc_id="snapshot"),
        html="<p>Winner</p>", ydoc="winner-snapshot",
    )
    assert all(same.assets[name]["path"] != path for name, path in winner_paths.items())
    assert stored[winner_paths["snapshot"]] == "winner-snapshot"
    assert all(
        loser.assets[name]["path"] != path for name, path in winner_paths.items()
    )
    Document.save(document, html="<p>Winner</p>", ydoc="same-html-new-snapshot")
    assert original.assets["document"]["path"] == winner_paths["document"]
    assert stored[original.assets["snapshot"]["path"]] == "same-html-new-snapshot"
    Document.save(document, html="", ydoc="empty-tombstones")
    assert "document" not in original.assets
    assert stored[original.assets["snapshot"]["path"]] == "empty-tombstones"
    assert stored[winner_paths["document"]] == "<p>Winner</p>"


# @matrix editor sync : document append idempotency offline-replay
def test_append_preserves_existing_crdt_and_is_idempotent():
    baseline, _ = crdt.append_fragment(None, "<p>Existing</p>", "initial")
    offline = crdt.load_document(baseline)
    text = offline["default"].children[0].children[0]
    text.insert(len(text), " draft 🌿")
    appended, receipt = crdt.append_fragment(
        baseline, "<blockquote><p>Source</p></blockquote><p>Added</p>", "append"
    )
    retry, repeated = crdt.append_fragment(
        appended, "<p>Must not duplicate</p>", "append"
    )
    assert retry == appended
    assert repeated == receipt
    merged = crdt.load_document(
        crdt.merge_documents(appended, crdt.encode_document(offline))
    )
    assert (
        str(merged["default"])
        == "<paragraph>Existing draft 🌿</paragraph><blockquote><paragraph>Source</paragraph></blockquote><paragraph>Added</paragraph>"
    )
    assert len(merged["default"].children) == 3


# @matrix editor markdown : document append formatting
def test_append_converts_supported_markdown_blocks():
    html = render_markdown(
        "# Heading\n\nA **bold** and *italic* [link](https://example.com).\n\n- one\n- two\n\n---\n\n- [x] done\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```\n"
    )
    snapshot, _ = crdt.append_fragment(None, html, "formatting")
    root = crdt.load_document(snapshot)["default"]
    tags = [child.tag for child in root.children]
    assert tags == [
        "heading",
        "paragraph",
        "bulletList",
        "horizontalRule",
        "taskList",
        "table",
        "codeBlock",
    ]
    assert dict(root.children[0].attributes)["level"] == 1
    assert root.children[2].children[0].children[0].tag == "paragraph"
    assert root.children[5].children[0].children[0].tag == "tableHeader"
    assert dict(root.children[4].children[0].attributes)["checked"] is True


# @matrix editor sync : document append undo tombstones
def test_undo_emits_tombstones_without_resetting_existing_nodes():
    baseline, _ = crdt.append_fragment(None, "<p>Keep</p>", "initial")
    appended, _ = crdt.append_fragment(baseline, "<p>Remove</p>", "append")
    undone = crdt.undo_fragment(appended, "append")
    assert crdt.undo_fragment(undone, "append") == undone
    offline = crdt.load_document(appended)
    offline["default"].children[0].children[0].insert(4, " draft")
    merged = crdt.load_document(
        crdt.merge_documents(undone, crdt.encode_document(offline))
    )
    assert str(merged["default"]) == "<paragraph>Keep draft</paragraph>"
    assert merged["lagniappeReports"]["append"]["state"] == "undone"


# @matrix editor sync : document append write-lock
def test_document_write_lock_is_scoped_and_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(
        documents.cache,
        "_redis",
        SimpleNamespace(
            lock=lambda key, **options: calls.append((key, options)) or nullcontext()
        ),
    )
    with documents.document_write_lock("one:document"):
        pass
    assert calls == [
        (
            f"{documents.Sync.DOCUMENTS.key('one:document')}:write",
            {"timeout": 60, "blocking_timeout": 5},
        )
    ]


# @matrix editor sync : document append cache-recovery offline-replay
def test_publish_checkpoint_preserves_live_updates(monkeypatch):
    redis = _DocumentRedis()
    monkeypatch.setattr(documents.cache, "_redis", redis)
    baseline, _ = crdt.append_fragment(None, "<p>Base</p>", "initial")
    live = crdt.load_document(baseline)
    live["default"].children[0].children[0].insert(4, " draft")
    appended, _ = crdt.append_fragment(baseline, "<p>Added</p>", "append")
    state, _ = documents._mutate(
        "page:document",
        {"ydoc": baseline, "fingerprint": "old"},
        lambda current: current.update(
            updates=[{"revision": 1, "update": crdt.encode_document(live)}]
        ),
    )
    fresh = documents.current_document_state(
        "page:document", seed={"ydoc": appended, "fingerprint": "new"}
    )
    assert fresh["generation"] != state["generation"]
    assert fresh["fingerprint"] == "new"
    assert (
        str(crdt.load_document(fresh["ydoc"])["default"])
        == "<paragraph>Base draft</paragraph><paragraph>Added</paragraph>"
    )


# @matrix editor sync : document append checkpoint conflict
def test_append_requires_a_checkpointed_collaborative_baseline(monkeypatch):
    baseline, _ = crdt.append_fragment(None, "<p>Base</p>", "initial")
    doc = SimpleNamespace(
        ydoc=baseline, html="<p>Base</p>", fingerprint="base", sync_id="page:document"
    )
    page = SimpleNamespace(properties=SimpleNamespace(document=doc))
    state = {"ydoc": baseline, "updates": []}
    monkeypatch.setattr(
        documents, "current_document_state", lambda *_args, **_kwargs: state
    )
    assert document_updates.checkpointed_document(page)["ydoc"] == baseline
    state["updates"] = [{"update": "pending"}]
    with pytest.raises(exceptions.ValidationError, match="unsaved collaborative"):
        document_updates.checkpointed_document(page)
    state["updates"] = []
    doc.ydoc = None
    with pytest.raises(exceptions.ValidationError, match="Open and save"):
        document_updates.checkpointed_document(page)


# @matrix editor sync : document permissions fresh-read
def test_fresh_document_rechecks_current_permissions(monkeypatch):
    actor = object()
    stale = SimpleNamespace(key="page", allowed=lambda *args, **kwargs: True)
    permissions = []
    fresh = SimpleNamespace(
        allowed=lambda action, *, user: permissions.append((action, user)) or True
    )
    reads = []
    monkeypatch.setattr(
        document_updates.Entities,
        "fetch_one",
        lambda key, **kwargs: reads.append(key) or fresh,
    )
    assert document_updates.fresh_document(stale, actor) is fresh
    assert reads == ["page"]
    assert permissions == [(document_updates.Action.EDIT, actor)]
    fresh.allowed = lambda *args, **kwargs: False
    with pytest.raises(exceptions.ValidationError, match="no longer editable"):
        document_updates.fresh_document(stale, actor)
    fresh = None
    with pytest.raises(exceptions.ValidationError, match="unavailable"):
        document_updates.fresh_document(stale, actor)


# @matrix mutations sync : document append guarded-checkpoint durable-first
def test_checkpoint_persists_before_publishing_and_guards_assets(monkeypatch):
    events = []
    page = SimpleNamespace(
        db={"assets": "old"},
        properties=SimpleNamespace(
            document=SimpleNamespace(
                sync_id="page:document",
                ydoc="new",
                fingerprint="new",
                html="new",
                save=lambda **kwargs: events.append(("assets", kwargs)),
            )
        ),
    )
    monkeypatch.setattr(
        document_updates.Entities,
        "save_document_checkpoint",
        lambda entity, **kwargs: events.append(("commit", kwargs)),
    )
    monkeypatch.setattr(
        documents,
        "publish_document_checkpoint",
        lambda *args, **kwargs: events.append(("publish", kwargs)),
    )
    document_updates.save_checkpoint(page, html="new", ydoc="new")
    assert [event[0] for event in events] == ["assets", "commit", "publish"]
    assert events[1][1] == {"advance_parent": True, "expected_state": {"assets": "old"}}


# @matrix mutations sync : document checkpoint cas conflict
def test_guarded_checkpoint_rejects_a_concurrent_asset_change(monkeypatch):
    writes = []
    transaction = SimpleNamespace(put=lambda row: writes.append(row))
    store = SimpleNamespace(
        transaction=lambda: nullcontext(transaction),
        get=lambda key, **kwargs: {"assets": "winner"},
    )
    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=store))
    monkeypatch.setattr(
        utility, "_put_mutation", lambda writer, row, mask: writes.append(row)
    )
    entity = SimpleNamespace(db={"assets": "loser"})
    with pytest.raises(exceptions.ValidationError, match="Document changed"):
        utility._save_guarded_mutations(
            [(entity, ("assets",))], [], [("page", {"assets": "old"})]
        )
    assert writes == []
    utility._save_guarded_mutations(
        [(entity, ("assets",))], [], [("page", {"assets": "winner"})]
    )
    assert writes == [{"assets": "loser"}]


# @matrix agent-api email editor : document source-attribution
@pytest.mark.parametrize(
    "origin,manifest,label",
    [
        ("web", {}, "Application"),
        ("email", {}, "Email"),
        ("api", {}, "External API / skill"),
        ("api", {"source": "remote_mcp"}, "Remote MCP"),
        ("email", {"source": "remote_mcp"}, "Email"),
    ],
)
def test_source_quote_uses_trusted_origin(origin, manifest, label):
    report = SimpleNamespace(origin=origin, agent_manifest=manifest)
    assert (
        actions.document_source_quote(report, "2026-09-06 18:00:00 UTC")
        == f"<blockquote><p>2026-09-06 18:00:00 UTC · {label}</p></blockquote>"
    )


# @source lagniappe/core/tools/ai/reporting/execution/actions/recovery.py::_inspect_action_applied
# @pair ai-report:skipped-prefix
def test_skipped_document_append_needs_no_receipt_on_retry(monkeypatch):
    from lagniappe.core.tools.ai.reporting.execution.actions import recovery

    monkeypatch.setattr(
        actions, "inspect_document_append", lambda *args: pytest.fail("Skipped append was inspected")
    )
    assert recovery._inspect_action_applied(
        {"type": "append_page_document"}, None, None, {"status": "skipped"}
    ) == recovery.ACTION_APPLIED


# @matrix ai-report editor : document append retry undo conflict
@pytest.mark.parametrize("existing", [False, True])
def test_report_append_retry_and_undo_preserve_content(monkeypatch, existing):
    _patch_fake_keys(monkeypatch)
    user = _test_user("append-owner")
    page = TestEntities.get("PAGE", {"name": "MCP", "hash": "append-page"})
    page.test_spec["assets"] = {}
    baseline, _ = crdt.append_fragment(None, "<p>Keep</p>", "initial")
    stored_html = {}
    histories = {}

    def save(entity, *, html, ydoc, **kwargs):
        document = entity.properties.document
        document._html, document._ydoc = html, ydoc
        digest = hashlib.md5(html.strip().encode()).hexdigest()
        entity.assets["document"] = {
            "type": "html",
            "path": digest,
            "fingerprint": digest,
        }
        stored_html[digest] = html
        for intent in entity.mutation_intents:
            if intent.intent is MutationIntentType.STANDARD:
                histories["saved-version"] = intent.entity
        entity._mutation_intents = []

    save(
        page,
        html="<p>Keep</p>" if existing else "",
        ydoc=baseline if existing else None,
    )
    if not existing:
        page.assets.pop("document")
    monkeypatch.setattr(actions, "document_write_lock", lambda *_: nullcontext())
    monkeypatch.setattr(actions, "fresh_document", lambda *_: page)
    monkeypatch.setattr(
        actions,
        "checkpointed_document",
        lambda entity: document_updates.document_seed(entity),
    )
    monkeypatch.setattr(actions, "save_checkpoint", save)
    monkeypatch.setattr(actions, "_resolve_entity", lambda *args, **kwargs: page)
    monkeypatch.setattr(actions, "_load_result_entity", lambda *_: page)
    monkeypatch.setattr(actions.database_get, "datastore_key", lambda key: key)
    monkeypatch.setattr(actions.database_get, "urlsafe_key", lambda key: "saved-version")
    def make_version(entity, *, key):
        history = actions.Entities.DOCUMENT_HISTORY(testing=True)
        class HistoryKey:
            parent = page.key
        history._key = HistoryKey()
        history._assets = {"document": copy.deepcopy(entity.assets["document"])}
        return history

    monkeypatch.setattr(actions.Entities.DOCUMENT_HISTORY, "create", make_version)
    monkeypatch.setattr(actions.Entities, "fetch_one", lambda key, **kwargs: histories.get(key))
    from lagniappe.core.tools.database import assets

    monkeypatch.setattr(assets, "get_text", lambda path, *args: stored_html[path])
    action = {
        "type": "append_page_document",
        "data": {"page": page.urlsafe_key, "document": "<p>Added</p>"},
    }
    report = SimpleNamespace(origin="api", agent_manifest={"source": "remote_mcp"})
    record = {"idempotency_key": "append-one"}
    actions.prepare_document_append(action, report, user, {}, record)
    prepared = copy.deepcopy(record)
    assert "assets" not in prepared["before"]
    entity, pending, metadata = actions._append_page_document(
        action, report, user, {}, {"action_record": record}
    )
    assert entity is page and pending == []  # no later full-Page save
    assert "Remote MCP" in page.properties.document.html
    assert page.properties.document.html.startswith(
        "<p>Keep</p><blockquote>" if existing else "<blockquote>"
    )
    assert actions.inspect_document_append(prepared, user) == "applied"
    assert prepared["document_after"] == metadata["document_after"]
    snapshot = page.properties.document.ydoc
    assert len(histories) == int(existing)
    if existing:
        assert histories["saved-version"].name.startswith("Before report append")
    actions._append_page_document(action, report, user, {}, {"action_record": prepared})
    assert page.properties.document.ydoc == snapshot
    saved_html = page.properties.document.html
    changed, _ = crdt.append_fragment(snapshot, "<p>Other edit</p>", "other")
    save(page, html=saved_html + "<p>Other edit</p>", ydoc=changed)
    with pytest.raises(exceptions.ValidationError, match="preserve those edits"):
        actions._undo_page_document(prepared, report, user)
    save(page, html=saved_html, ydoc=snapshot)
    if existing:
        saved_version = histories.pop("saved-version")
        with pytest.raises(exceptions.ValidationError, match="version is unavailable"):
            actions._undo_page_document(prepared, report, user)
        assert page.properties.document.ydoc == snapshot
        histories["saved-version"] = saved_version
    actions._undo_page_document(prepared, report, user)
    assert page.properties.document.html == ("<p>Keep</p>" if existing else "")
    assert str(crdt.load_document(page.properties.document.ydoc)["default"]) == (
        "<paragraph>Keep</paragraph>" if existing else ""
    )
