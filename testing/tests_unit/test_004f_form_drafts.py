"""Draft-only Form editing and immutable definition publication contracts."""

from copy import deepcopy
from contextlib import nullcontext
import copy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

from google.cloud import datastore
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.entities.form import Form
from lagniappe.core.mutations import executor, plan_mutation
from lagniappe.core.tools import form_drafts as drafts
from lagniappe.core.tools.database import assets, get as database_get, utility as database_utility

pytestmark = pytest.mark.unit


@pytest.fixture
def memory_forms(monkeypatch):
    """Replace only storage, database, authorization, and rebuildable effects."""
    rows, blobs, commits = {}, {}, []
    key = datastore.Key("models", "draft-form", project="test-project")
    row = datastore.Entity(key=key)
    row.update({
        "type": "form", "hash": "draft-form", "name": "Instructions",
        "form_type": "task", "version": "legacy-version", "schema_format": 1,
        "schema": json.dumps([{"id": "notes", "type": "html", "title": "Notes"}]),
        "created": datetime(2026, 9, 11, tzinfo=timezone.utc),
        "modified": datetime(2026, 9, 11, tzinfo=timezone.utc),
        "assets": json.dumps({"notes": {
            "type": "html", "path": "original.html", "generation": "1",
            "fingerprint": hashlib.md5(b"<p>Original</p>").hexdigest(),
        }}),
    })
    rows[key] = deepcopy(row)
    blobs["original.html"] = "<p>Original</p>"

    def fetch_one(identifier, *, request):
        if hasattr(identifier, "db"):
            identifier = identifier.key
        if isinstance(identifier, datastore.Entity):
            item = identifier
        else:
            item = rows.get(identifier)
        if item is None:
            return None
        cls = Entities.FORM if item.get("type") == "form" else Entities.FORM_HISTORY
        return cls(deepcopy(item))

    def fetch(*identifiers, request):
        return [entity for item in identifiers if (entity := fetch_one(item, request=request)) is not None]

    def commit(writes, *, guards=None):
        writes = list(writes)
        for guard_key, expected in guards or []:
            current = rows.get(guard_key)
            if (current is not None if expected is None else current is None or (
                dict(current) != expected if isinstance(expected, database_utility.ExactEntityState)
                else any(current.get(name) != value for name, value in expected.items())
            )):
                raise exceptions.MutationConflict("Saved state changed while saving; reload and retry.")
        for entity, mask in writes:
            if mask:
                for name in mask:
                    if name in entity.db:
                        rows[entity.key][name] = deepcopy(entity.db[name])
                    else:
                        rows[entity.key].pop(name, None)
            else:
                rows[entity.key] = deepcopy(entity.db)
        commits.append([entity.key for entity, _mask in writes])

    def save_text(content, path, *args, **kwargs):
        blobs[path] = content
        return SimpleNamespace(generation=str(len(blobs)), size=len(content))

    def save_file(content, path, *args, **kwargs):
        return save_text(content.read(), path)

    def copy_file(source, visibility, destination, target_visibility, **kwargs):
        if source not in blobs:
            return None
        return save_text(blobs[source], destination)

    monkeypatch.setattr(Entities, "fetch_one", fetch_one)
    monkeypatch.setattr(Entities, "fetch", fetch)
    monkeypatch.setattr(Form, "allowed", lambda self, action, user=None: True)
    monkeypatch.setattr(database_get, "form_users", lambda form: [])
    monkeypatch.setattr(executor.database_utility, "save_mutations", commit)
    monkeypatch.setattr(executor, "execute_post_commit", lambda plan: ([], []))
    monkeypatch.setattr(assets, "get_text", lambda path, *args, **kwargs: blobs.get(path))
    monkeypatch.setattr(assets, "download_file", lambda path, *args, **kwargs: blobs.get(path))
    monkeypatch.setattr(assets, "save_text", save_text)
    monkeypatch.setattr(assets, "save_file", save_file)
    monkeypatch.setattr(assets, "copy_file", copy_file)
    monkeypatch.setattr(assets, "delete_file_generation", lambda path, visibility, generation: blobs.pop(path, None) is not None)
    monkeypatch.setattr(drafts, "Query", lambda kind: SimpleNamespace(
        ancestor=lambda key: SimpleNamespace(filter=lambda query: SimpleNamespace(fetch_all=lambda: []))
    ))
    return SimpleNamespace(rows=rows, blobs=blobs, commits=commits, key=key,
                           form=lambda: fetch_one(key, request=Fetch.direct()), commit=commit)


# @matrix forms mutations : lazy-construction immutable-baseline guarded-save
def test_form_construction_retains_serialized_state_without_hydration_or_deepcopy(memory_forms, monkeypatch):
    row = deepcopy(memory_forms.rows[memory_forms.key])
    row["groups"] = ["original-group"]
    original_schema, original_assets = row["schema"], row["assets"]
    reads = []
    monkeypatch.setattr(database_get, "entity", lambda key: reads.append(key) or row)
    with monkeypatch.context() as construction:
        construction.setattr(copy, "deepcopy", lambda *args, **kwargs: pytest.fail("constructor copied the row graph"))
        loaded = Form(row)
        keyed = Form(row.key)
    assert reads == []
    assert loaded.properties._instances == {} and keyed.properties._instances == {}
    assert loaded._form_source_state["schema"] is original_schema
    assert loaded._form_source_state["assets"] is original_assets
    assert keyed._db == {}
    row["groups"].append("later-group")
    row["schema"] = "[]"
    saved = loaded.saved_form_state()
    assert saved["groups"] == ["original-group"]
    assert saved["schema"] == original_schema
    assert keyed.name == "Instructions"
    assert reads == [row.key]
    keyed.name = "Edited after load"
    assert keyed.saved_form_state()["name"] == "Instructions"


# @matrix form-schema : validation identity conditions
@pytest.mark.parametrize("fields", [
    [{"id": "pick", "type": "select", "options": [
        {"value": "a", "label": "A"}, {"value": "a", "label": "B"},
    ]}],
    [{"id": "text", "type": "textarea", "visibility": [{"id": "missing", "value": "a"}]}],
    [{"id": "check", "type": "checkbox"}, {"id": "text", "type": "textarea",
      "visibility": [{"id": "check", "type": "checkbox", "value": "false"}]}],
    [{"id": "s1", "type": "signature"}, {"id": "s2", "type": "signature"}],
])
def test_draft_schema_rejects_collisions_and_broken_conditions(fields):
    with pytest.raises((ValueError, exceptions.ValidationError)):
        drafts.validate_draft_schema(fields, "task")


# @matrix form-schema : identity migration-required save-guard
def test_compatible_schema_preserves_representation_and_identity():
    source = [{"id": "pick", "type": "select", "options": [{"value": "stable", "label": "Old"}]},
              {"id": "table", "type": "table", "columns": [{"id": "cell", "type": "input", "input": "text"}]}]
    target = deepcopy(source)
    target[0]["options"][0]["label"] = "New"
    target[1]["columns"][0]["title"] = "Renamed"
    accepted = drafts.validate_compatible_schema(source, target, "task")
    assert accepted[0]["options"][0] == {"value": "stable", "label": "New"}
    assert accepted[1]["columns"][0]["id"] == "cell"
    for mutate in (
        lambda fields: fields.pop(),
        lambda fields: fields[0].update(multiple=True),
        lambda fields: fields[0]["options"][0].update(value="changed"),
        lambda fields: fields[1]["columns"][0].update(input="number"),
    ):
        invalid = deepcopy(target)
        mutate(invalid)
        with pytest.raises(exceptions.ValidationError, match="migration"):
            drafts.validate_compatible_schema(source, invalid, "task")
    assert source[0]["options"][0]["label"] == "Old"


# @matrix forms html-field : draft baseline no-write
def test_builder_draft_and_staged_html_are_read_only(memory_forms):
    form = memory_forms.form()
    before_rows, before_blobs = deepcopy(memory_forms.rows), deepcopy(memory_forms.blobs)
    saved = drafts.builder_draft(form)
    form.set_html_field("notes", "<p>Draft</p>")
    assert drafts.builder_draft(form)["html_fields"] == {"notes": "<p>Draft</p>"}
    assert saved["html_fields"] == {"notes": "<p>Original</p>"}
    assert memory_forms.rows == before_rows and memory_forms.blobs == before_blobs
    assert memory_forms.commits == []


# @source lagniappe/core/properties/form.py::SchemaVersion
# @matrix form-schema html-field : content-version fingerprint
# @matrix form : schema-version update
def test_content_version_changes_only_with_definition_content(memory_forms):
    form = memory_forms.form()
    version = drafts.definition_version(form)
    form.name = "Another name"
    assert drafts.definition_version(form) == version
    form.assets["notes"]["fingerprint"] = "different"
    assert drafts.definition_version(form) != version
    form.properties.version.update()
    assert form.version == drafts.definition_version(form)
    del form.assets["notes"]["fingerprint"]
    with pytest.raises(exceptions.ValidationError, match="fingerprint"):
        drafts.definition_version(form)


# @matrix form-schema html-field : history immutable-assets content-version
# @pair html-field:missing-content
def test_history_snapshot_owns_original_assets_and_marks_legacy_content_unknown(memory_forms):
    form = memory_forms.form()
    history = Entities.FORM_HISTORY.snapshot(form, "known", content_available=True)
    assert history.get_html_field("notes") == "<p>Original</p>"
    assert history.assets["notes"]["path"] != "original.html"
    memory_forms.blobs["original.html"] = "<p>Later</p>"
    assert history.get_html_field("notes") == "<p>Original</p>"
    legacy = Entities.FORM_HISTORY.snapshot(form, "legacy", content_available=False)
    assert not legacy.content_available and not legacy.assets
    assert legacy.get_html_field("notes") is None


# @source lagniappe/core/mutations/save.py::FormMutation.plan_save
# @source lagniappe/core/mutations/executor.py::execute_mutation
# @matrix forms html-field mutations : content-version history guarded-save
# @matrix form : save schema-history
# @matrix mutations : save durable-first
def test_publication_stages_immutable_history_and_guards_original_row(memory_forms):
    form = memory_forms.form()
    form.set_html_field("notes", "<p>Accepted</p>")
    plan = plan_mutation(MutationOperation.SAVE, form, registry=Entities)
    assert memory_forms.rows[memory_forms.key]["version"] == "legacy-version"
    memory_forms.rows[memory_forms.key]["restricted_to"] = ["newer-restriction"]
    with pytest.raises(exceptions.ValidationError, match="changed"):
        executor.execute_mutation(plan)
    assert memory_forms.rows[memory_forms.key]["version"] == "legacy-version"
    assert memory_forms.blobs["original.html"] == "<p>Original</p>"
    assert memory_forms.rows[memory_forms.key]["restricted_to"] == ["newer-restriction"]


# @matrix forms mutations permissions : guarded-save concurrent-restrictions
def test_exact_publication_guard_rejects_new_properties_but_document_guard_is_subset(monkeypatch):
    written = []
    transaction = SimpleNamespace(put=written.append)
    row = {"assets": "unchanged", "restricted_to": ["new-restriction"]}
    store = SimpleNamespace(transaction=lambda: nullcontext(transaction), get=lambda *args, **kwargs: row)
    monkeypatch.setattr(database_utility, "DATA", SimpleNamespace(datastore=store))
    monkeypatch.setattr(database_utility, "_put_mutation", lambda writer, row, mask: written.append(row))
    entity = SimpleNamespace(db={"assets": "draft"})
    with pytest.raises(exceptions.MutationConflict):
        database_utility._save_guarded_mutations([(entity, None)], [], [
            ("form", database_utility.ExactEntityState({"assets": "unchanged"})),
        ])
    assert written == []
    database_utility._save_guarded_mutations([(entity, ("assets",))], [], [
        ("page", {"assets": "unchanged"}),
    ])
    assert written == [{"assets": "draft"}]


# @matrix form-schema html-field : history legacy missing-version
def test_resolver_prefers_snapshot_and_does_not_invent_legacy_content(memory_forms):
    form = memory_forms.form()
    legacy = drafts.resolve_form_version(form, form.version)
    assert legacy.schema == form.schema and not legacy.content_available
    snapshot = drafts.ensure_form_snapshot(form)
    memory_forms.blobs["original.html"] = "<p>Later</p>"
    resolved = drafts.resolve_form_version(form.key, snapshot.version)
    assert resolved.get_html_field("notes") == "<p>Original</p>"
    assert drafts.resolve_form_version(form, "missing") is None
    memory_forms.rows[snapshot.key]["form"] = datastore.Key("models", "another", project="test-project")
    with pytest.raises(exceptions.ValidationError, match="inconsistent"):
        drafts.resolve_form_version(form.key, snapshot.version)


# @matrix task-completion form-schema : immutable-snapshot content-version
def test_completion_snapshot_is_exact_and_does_not_relabel_legacy_version(memory_forms):
    form = memory_forms.form()
    snapshot = drafts.ensure_form_snapshot(form)
    repeated = drafts.ensure_form_snapshot(form)
    assert snapshot.version.startswith("fc1-") and repeated.key == snapshot.key
    assert snapshot.version != "legacy-version"
    assert memory_forms.rows[memory_forms.key]["version"] == "legacy-version"
    assert len(memory_forms.commits) == 1
    form.set_html_field("notes", "<p>Unsaved</p>")
    with pytest.raises(exceptions.ValidationError, match="Save the Form draft"):
        drafts.ensure_form_snapshot(form)
    assert len(memory_forms.commits) == 1


# @matrix task-completion form-schema : content-version current-definition no-extra-read
def test_completion_reuses_clean_current_content_without_snapshot_reads(memory_forms, monkeypatch):
    original = memory_forms.form()
    draft = drafts.builder_draft(original)
    baseline = draft.pop("baseline")
    drafts.save_form_draft(original, draft, baseline, "publish-current", object())
    current = memory_forms.form()
    with monkeypatch.context() as current_read:
        current_read.setattr(Entities, "fetch_one", lambda *args, **kwargs: pytest.fail("completion looked up a history snapshot"))
        current_read.setattr(assets, "copy_file", lambda *args, **kwargs: pytest.fail("completion copied current content"))
        assert current.snapshot_for_completion() is current
        assert current.content_available
        schema = current.schema
        schema[0]["title"] = "Unsaved label"
        current.schema = schema
        assert not current.content_available
    current = memory_forms.form()
    current.set_html_field("notes", "<p>Unsaved</p>")
    assert not current.content_available
    with pytest.raises(exceptions.ValidationError, match="Save the Form draft"):
        current.snapshot_for_completion()


# @matrix forms : draft save-receipt conflict publication
# @pairs html-field:upload mutations:conflict
def test_save_draft_checks_receipt_baseline_and_validation_before_uploads(memory_forms):
    form = memory_forms.form()
    draft = drafts.builder_draft(form)
    baseline = draft.pop("baseline")
    with pytest.raises(drafts.FormDraftConflict):
        drafts.save_form_draft(form, draft, "stale", "save-1", object(), images={
            "image": {"field_id": "notes", "file": lambda: pytest.fail("premature upload")},
        })
    draft["name"] = "First save"
    result = drafts.save_form_draft(form, draft, baseline, "save-1", object())
    before = len(memory_forms.commits)
    assert drafts.save_form_draft(form, draft, baseline, "save-1", object()) == result
    assert len(memory_forms.commits) == before
    next_draft = deepcopy(result["draft"])
    next_draft["name"] = "Later name"
    drafts.save_form_draft(form, next_draft, result["baseline"], "save-2", object())
    with pytest.raises(drafts.FormDraftConflict):
        drafts.save_form_draft(form, draft, baseline, "save-1", object())


# @matrix forms : draft save-receipt publication
# @matrix html-field : upload publication
def test_save_draft_publishes_images_once_and_retains_failed_attempt_originals(memory_forms):
    form = memory_forms.form()
    draft = drafts.builder_draft(form)
    baseline = draft.pop("baseline")
    draft["html_fields"]["notes"] = '<p>Accepted<img src="draft-image:photo"></p>'
    source = BytesIO(b"picture")
    source.content_type = "image/png"
    result = drafts.save_form_draft(form, draft, baseline, "save-image", object(), images={
        "photo": {"field_id": "notes", "file": source},
    })
    assert "draft-image:" not in result["draft"]["html_fields"]["notes"]
    assert result["image_urls"]["draft-image:photo"] in result["draft"]["html_fields"]["notes"]
    assert memory_forms.blobs["original.html"] == "<p>Original</p>"
    count = len(memory_forms.blobs)
    drafts.save_form_draft(form, draft, baseline, "save-image", object(), images={
        "photo": {"field_id": "notes", "file": lambda: pytest.fail("retry consumed upload")},
    })
    assert len(memory_forms.blobs) == count


# @matrix form-schema : history batch-read
def test_definition_versions_batch_shared_history_reads(memory_forms, monkeypatch):
    form = memory_forms.form()
    snapshot = drafts.ensure_form_snapshot(form)
    actual_fetch = Entities.fetch
    calls = []

    def fetch(*keys, request):
        calls.append(keys)
        return actual_fetch(*keys, request=request)

    monkeypatch.setattr(Entities, "fetch", fetch)
    result = drafts.resolve_form_versions([(form, snapshot.version), (form.key, snapshot.version)])
    assert list(result) == [(form.key, snapshot.version)]
    assert result[(form.key, snapshot.version)].schema == form.schema
    assert calls == [(snapshot.key,)]


# @matrix forms html-field : copy draft immutable-assets save-receipt
def test_copy_draft_owns_content_and_is_idempotent_without_saving_source(memory_forms):
    form = memory_forms.form()
    initial = drafts.builder_draft(form)
    initial_baseline = initial.pop("baseline")
    initial["html_fields"]["notes"] = '<p>Original<img src="draft-image:photo"></p>'
    source_image = BytesIO(b"original-picture")
    source_image.content_type = "image/png"
    drafts.save_form_draft(form, initial, initial_baseline, "source-image", object(), images={
        "photo": {"field_id": "notes", "file": source_image},
    })
    form = memory_forms.form()
    draft = drafts.builder_draft(form)
    baseline = draft.pop("baseline")
    source_url = next(form.get_asset(name).url for name in form.assets if name.startswith("image_"))
    draft["html_fields"]["notes"] = f'<p>Unsaved copy content<img src="{source_url}"></p>'
    before = deepcopy(memory_forms.rows[form.key])
    actor = SimpleNamespace(key="copy-actor")
    result = drafts.copy_form_draft(form, draft, baseline, "copy-1", actor)
    assert result["draft"]["name"] == "Copy of Instructions"
    assert "Unsaved copy content" in result["draft"]["html_fields"]["notes"]
    assert source_url not in result["draft"]["html_fields"]["notes"]
    assert memory_forms.rows[form.key] == before
    copy_keys = [key for key, row in memory_forms.rows.items() if row.get("type") == "form" and key != form.key]
    assert len(copy_keys) == 1
    copied = Entities.fetch_one(copy_keys[0], request=Fetch.root())
    assert copied.assets["notes"]["path"] != form.assets["notes"]["path"]
    image_name = next(name for name in form.assets if name.startswith("image_"))
    copied_image = copied.get_asset(image_name)
    assert copied_image.url in result["draft"]["html_fields"]["notes"]
    assert copied_image.path != form.get_asset(image_name).path
    assert memory_forms.blobs[copied_image.path] == b"original-picture"
    commits = len(memory_forms.commits)
    assert drafts.copy_form_draft(form, draft, baseline, "copy-1", actor) == result
    assert len(memory_forms.commits) == commits


# @matrix form-schema html-field : history permission-boundary
def test_definition_snapshot_requires_submitter_scoped_authorization(memory_forms):
    snapshot = drafts.ensure_form_snapshot(memory_forms.form())
    # Entity permission decorators read the fingerprint before calling allowed.
    assert snapshot.created is not None
    assert snapshot.modified == snapshot.created
    assert snapshot.fingerprint
    assert snapshot.name == snapshot.db.get("name")
    for action in (Action.VIEW, Action.EDIT, Action.DELETE):
        assert snapshot.allowed(action, user=SimpleNamespace(is_admin=True)) is False


# @matrix html-field : isolated-assets cleanup
# @matrix mutations : rejected-save ambiguous-commit
@pytest.mark.parametrize("uncertain", [False, True])
def test_rejected_save_cleans_only_attempt_blobs_and_ambiguous_commit_retains_them(memory_forms, monkeypatch, uncertain):
    form = memory_forms.form()
    draft = drafts.builder_draft(form)
    baseline = draft.pop("baseline")
    draft["html_fields"]["notes"] = "<p>Different</p>"
    original_blobs = deepcopy(memory_forms.blobs)

    def reject(*args, **kwargs):
        if uncertain:
            raise RuntimeError("Transport failed after commit may have started")
        raise exceptions.MutationConflict("Rejected stale snapshot")

    monkeypatch.setattr(executor.database_utility, "save_mutations", reject)
    with pytest.raises((RuntimeError, drafts.FormDraftConflict)):
        drafts.save_form_draft(form, draft, baseline, "rejected", object(), _retry=False)
    assert memory_forms.blobs["original.html"] == "<p>Original</p>"
    if uncertain:
        assert len(memory_forms.blobs) > len(original_blobs)
    else:
        assert memory_forms.blobs == original_blobs


# @source lagniappe/core/tools/form_drafts.py::save_form_draft
# @source lagniappe/core/tools/form_drafts.py::ensure_form_snapshot
# @matrix forms : draft conflict publication
# @pair mutations:conflict
# @matrix task-completion form-schema : immutable-snapshot content-version
def test_save_reuses_snapshot_won_by_concurrent_completion(memory_forms, monkeypatch):
    form = memory_forms.form()
    draft = drafts.builder_draft(form)
    baseline = draft.pop("baseline")
    draft["name"] = "Accepted after completion"
    raced = False
    winner = None

    def race(writes, *, guards=None):
        nonlocal raced, winner
        if not raced:
            raced = True
            winner = drafts.ensure_form_snapshot(memory_forms.form())
        return memory_forms.commit(writes, guards=guards)

    monkeypatch.setattr(executor.database_utility, "save_mutations", race)
    result = drafts.save_form_draft(form, draft, baseline, "save-race", object())
    assert result["draft"]["name"] == "Accepted after completion"
    assert memory_forms.form().version == winner.version
    assert len([row for row in memory_forms.rows.values() if row.get("schema_version") == winner.version]) == 1
    assert memory_forms.blobs[winner.get_asset("notes").path] == "<p>Original</p>"
    assert len(memory_forms.blobs) == 2  # original plus the winning independent snapshot
