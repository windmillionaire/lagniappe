"""Draft-only Form editing and immutable definition publication contracts."""

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
from uuid import uuid4

from google.cloud import datastore
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.entities.form import Form
from lagniappe.core.mutations import executor, plan_mutation
from lagniappe.core.tools.forms import definitions, drafts
from lagniappe.core.tools.cache import restrictions as restriction_cache
from lagniappe.core.tools.database import assets, get as database_get, utility as database_utility

pytestmark = pytest.mark.unit


@pytest.fixture
def memory_forms(monkeypatch):
    """Replace only storage, database, authorization, and rebuildable effects."""
    execute_post_commit = executor.execute_post_commit
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
    monkeypatch.setattr(database_utility, "create_key", lambda kind, parent=None: datastore.Key(
        "history" if kind == "form_history" else "models", uuid4().hex,
        parent=parent.key if parent else None, project="test-project",
    ))
    monkeypatch.setattr(Form, "allowed", lambda self, action, user=None: True)
    monkeypatch.setattr(database_get, "form_users", lambda form: [])
    monkeypatch.setattr(database_get, "entity", lambda identifier: deepcopy(rows.get(identifier)))
    monkeypatch.setattr(executor.database_utility, "save_mutations", commit)
    monkeypatch.setattr(executor, "execute_post_commit", lambda plan: ([], []))
    monkeypatch.setattr(assets, "get_text", lambda path, *args, **kwargs: blobs.get(path))
    monkeypatch.setattr(assets, "download_file", lambda path, *args, **kwargs: blobs.get(path))
    monkeypatch.setattr(assets, "save_text", save_text)
    monkeypatch.setattr(assets, "save_file", save_file)
    monkeypatch.setattr(assets, "copy_file", copy_file)
    monkeypatch.setattr(assets, "delete_file_generation", lambda path, visibility, generation: blobs.pop(path, None) is not None)
    monkeypatch.setattr(definitions, "Query", lambda kind: SimpleNamespace(
        ancestor=lambda key: SimpleNamespace(filter=lambda query: SimpleNamespace(fetch_all=lambda: []))
    ))
    return SimpleNamespace(rows=rows, blobs=blobs, commits=commits, key=key,
                           form=lambda: fetch_one(key, request=Fetch.direct()), commit=commit,
                           execute_post_commit=execute_post_commit)


# @source lagniappe/core/entities/form.py::Form.get_html_field
# @matrix forms html-field : draft no-write
def test_form_reads_do_not_fetch_or_archive_definitions(memory_forms, monkeypatch):
    form = memory_forms.form()
    before = deepcopy(memory_forms.rows), deepcopy(memory_forms.blobs)
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: pytest.fail("Form read fetched history"))
    monkeypatch.setattr(assets, "copy_file", lambda *args, **kwargs: pytest.fail("Form read copied assets"))
    assert form.name == "Instructions"
    assert form.schema[0]["title"] == "Notes"
    assert form.get_html_field("notes") == "<p>Original</p>"
    assert form.generation == 0
    assert (memory_forms.rows, memory_forms.blobs) == before


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
# @matrix form : schema-version update
def test_content_version_changes_only_with_definition_content(memory_forms):
    form = memory_forms.form()
    form.properties.version.update()
    version = form.version
    form.name = "Another name"
    assert form.properties.version.update() is False
    assert form.version == version
    form.assets["notes"]["fingerprint"] = "different"
    form.properties.version.update()
    assert form.version != version
    assert form.generation == 0


# @matrix form-schema html-field : history generation immutable-assets
def test_archived_generation_preserves_schema_html_and_images(memory_forms):
    source = memory_forms.form()
    source.assets["image_notes_photo"] = {
        "type": "image", "path": "photo.png", "generation": "1", "fingerprint": "photo",
    }
    source.db["assets"] = json.dumps(source.assets)
    memory_forms.blobs["photo.png"] = b"original picture"
    history = drafts.archive_form_generation(source)
    assert history.generation == 0
    assert history.schema == source.schema
    assert history.get_html_field("notes") == "<p>Original</p>"
    assert history.assets["notes"]["path"] != "original.html"
    image_path = history.assets["image_notes_photo"]["path"]
    assert image_path != "photo.png"
    memory_forms.blobs["original.html"] = "<p>Later</p>"
    memory_forms.blobs["photo.png"] = b"later picture"
    assert history.get_html_field("notes") == "<p>Original</p>"
    assert memory_forms.blobs[image_path] == b"original picture"
    assert not history.allowed(Action.VIEW)


# @source lagniappe/core/mutations/save.py::FormMutation.plan_save
# @source lagniappe/core/mutations/executor.py::execute_mutation
# @matrix forms mutations : guarded-save publication
# @matrix mutations : save durable-first
def test_publication_reads_saved_form_only_at_save(memory_forms):
    form = memory_forms.form()
    form.set_html_field("notes", "<p>Accepted</p>")
    plan = plan_mutation(MutationOperation.SAVE, form, registry=Entities)
    memory_forms.rows[memory_forms.key]["restricted_to"] = ["newer-restriction"]
    with pytest.raises(exceptions.MutationConflict, match="changed"):
        executor.execute_mutation(plan)
    assert memory_forms.rows[memory_forms.key]["version"] == "legacy-version"
    assert memory_forms.blobs["original.html"] == "<p>Original</p>"
    assert memory_forms.rows[memory_forms.key]["restricted_to"] == ["newer-restriction"]


# @matrix forms mutations : generation publication
def test_compatible_saves_update_version_without_archiving_generation(memory_forms):
    for content in ("<p>First edit</p>", "<p>Second edit</p>"):
        form = memory_forms.form()
        previous_version = form.version
        form.set_html_field("notes", content)
        form.save()
        saved = memory_forms.form()
        assert saved.version != previous_version
        assert saved.generation == 0
        assert saved.get_html_field("notes") == content
    assert len(memory_forms.rows) == 1


# @source lagniappe/core/tools/forms/drafts.py::prepare_form_publication
# @source lagniappe/core/mutations/executor.py::execute_post_commit
# @matrix html-field : isolated-assets cleanup
# @matrix mutations : durable-first rejected-save
# @pair forms:publication
@pytest.mark.parametrize("content", ["<p>Replacement</p>", ""], ids=["replace", "clear"])
@pytest.mark.parametrize("accepted", [True, False], ids=["accepted", "rejected"])
def test_replaced_live_html_is_deleted_only_after_commit_and_preserves_archive(
    memory_forms, monkeypatch, content, accepted,
):
    form = memory_forms.form()
    history = drafts.archive_form_generation(form)
    history.save()
    archived_path = history.assets["notes"]["path"]
    before_blobs = deepcopy(memory_forms.blobs)
    before_row = deepcopy(memory_forms.rows[form.key])
    events = []

    def commit(writes, *, guards=None):
        assert memory_forms.blobs["original.html"] == "<p>Original</p>"
        assert memory_forms.blobs[archived_path] == "<p>Original</p>"
        events.append("commit")
        if not accepted:
            raise exceptions.MutationConflict("Rejected the edited Form")
        memory_forms.commit(writes, guards=guards)

    def delete_blobs(paths, *, on_error):
        # The accepted row must already point to the replacement or clear.
        assert events == ["commit"]
        assert memory_forms.form().get_html_field("notes") == (content or None)
        events.append("delete")
        for path in paths:
            memory_forms.blobs.pop(path)

    monkeypatch.setattr(executor.database_utility, "save_mutations", commit)
    monkeypatch.setattr(executor, "execute_post_commit", memory_forms.execute_post_commit)
    monkeypatch.setattr(executor.cache, "update", lambda *args: None)
    monkeypatch.setattr(executor.cache, "update_owner_projection", lambda *args: None)
    monkeypatch.setattr(restriction_cache, "prepare_changes", lambda entities: [])
    monkeypatch.setattr(restriction_cache, "dispatch_changes", lambda previous: None)
    bucket = SimpleNamespace(delete_blobs=delete_blobs)
    monkeypatch.setattr(database_utility, "DATA", SimpleNamespace(
        private_bucket=bucket, public_bucket=bucket,
    ))

    form.set_html_field("notes", content)
    plan = plan_mutation(MutationOperation.SAVE, form, registry=Entities)
    assert memory_forms.blobs["original.html"] == "<p>Original</p>"
    if accepted:
        outcome = executor.execute_mutation(plan)
        assert outcome.post_commit_complete
        assert events == ["commit", "delete"]
        assert "original.html" not in memory_forms.blobs
        assert memory_forms.form().get_html_field("notes") == (content or None)
    else:
        with pytest.raises(exceptions.MutationConflict, match="Rejected"):
            executor.execute_mutation(plan)
        assert events == ["commit"]
        assert memory_forms.rows[form.key] == before_row
        assert memory_forms.blobs == before_blobs
    saved_history = Entities.fetch_one(history.key, request=Fetch.root())
    assert saved_history.get_html_field("notes") == "<p>Original</p>"
    assert memory_forms.blobs[archived_path] == "<p>Original</p>"


# @matrix forms mutations permissions : guarded-save concurrent-restrictions
def test_exact_publication_guard_rejects_new_properties_but_document_guard_is_subset(monkeypatch):
    written = []
    transaction = SimpleNamespace(put=written.append)
    key = datastore.Key("models", "form", project="test-project")
    row = datastore.Entity(key)
    row.update(assets="unchanged", restricted_to=["new-restriction"])
    store = SimpleNamespace(transaction=lambda: nullcontext(transaction), get_multi=lambda *args, **kwargs: [row])
    monkeypatch.setattr(database_utility, "DATA", SimpleNamespace(datastore=store))
    monkeypatch.setattr(database_utility, "_put_mutation", lambda writer, row, mask: written.append(row))
    entity = SimpleNamespace(db={"assets": "draft"})
    with pytest.raises(exceptions.MutationConflict):
        database_utility._save_guarded_mutations([(entity, None)], [], [
            (key, database_utility.ExactEntityState({"assets": "unchanged"})),
        ])
    assert written == []
    database_utility._save_guarded_mutations([(entity, ("assets",))], [], [
        (key, {"assets": "unchanged"}),
    ])
    assert written == [{"assets": "draft"}]


# @matrix form-schema : history generation
def test_generation_resolution_ignores_legacy_versions(memory_forms, monkeypatch):
    form = memory_forms.form()
    monkeypatch.setattr(definitions, "Query", lambda *args, **kwargs: pytest.fail("Matching generation queried history"))
    assert definitions.resolve_form_generation(form, 0) is form
    assert definitions.resolve_form_generation(form.key, 0).schema == form.schema
    assert form.version == "legacy-version"


# @matrix form-schema : history generation
def test_generation_resolution_loads_only_the_requested_archive(memory_forms, monkeypatch):
    source = memory_forms.form()
    archived = drafts.archive_form_generation(source)
    current = memory_forms.form()
    current.generation = 1
    current.schema = [{"id": "different", "type": "input", "title": "Current"}]
    calls = []
    def stored(key, generation):
        calls.append((key, generation))
        return archived if generation == 0 else None
    monkeypatch.setattr(definitions, "_stored_generation", stored)
    assert definitions.resolve_form_generation(current, 0) is archived
    assert definitions.resolve_form_generation(current, 1) is current
    assert definitions.resolve_form_generation(current, 99) is None
    assert calls == [(source.key, 0), (source.key, 99)]





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


# @matrix form-schema : history generation batch-read
def test_generation_resolution_batches_current_forms(memory_forms, monkeypatch):
    form = memory_forms.form()
    actual_fetch = Entities.fetch
    calls = []
    def fetch(*keys, request):
        calls.append(keys)
        return actual_fetch(*keys, request=request)
    monkeypatch.setattr(Entities, "fetch", fetch)
    result = definitions.resolve_form_generations([(form.key, 0), (form.key, 0)])
    assert list(result) == [(form.key, 0)]
    assert result[(form.key, 0)].schema == form.schema
    assert calls == [(form.key,)]


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
    snapshot = drafts.archive_form_generation(memory_forms.form())
    snapshot.save()
    assert snapshot.created is not None
    assert snapshot.modified == snapshot.created
    assert snapshot.fingerprint
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


# @source lagniappe/core/tools/forms/drafts.py::save_form_draft
# @matrix forms : draft conflict publication
# @pair mutations:conflict
@pytest.mark.parametrize("race_timing", ["after-initial-fetch", "before-commit"])
def test_save_retry_preserves_concurrent_restrictions(memory_forms, monkeypatch, race_timing):
    form = memory_forms.form()
    draft = drafts.builder_draft(form)
    baseline = draft.pop("baseline")
    draft["name"] = "Accepted after restriction edit"
    raced = False
    allowed_restrictions = []
    fetch_one = Entities.fetch_one

    def check_permission(self, action, user=None):
        allowed_restrictions.append(self.db.get("restricted_to"))
        return True

    def fetch(identifier, *, request):
        nonlocal raced
        current = fetch_one(identifier, request=request)
        if race_timing == "after-initial-fetch" and not raced:
            raced = True
            memory_forms.rows[form.key]["restricted_to"] = ["admin"]
        return current

    def race(writes, *, guards=None):
        nonlocal raced
        if race_timing == "before-commit" and not raced:
            raced = True
            memory_forms.rows[form.key]["restricted_to"] = ["admin"]
        return memory_forms.commit(writes, guards=guards)

    monkeypatch.setattr(Form, "allowed", check_permission)
    monkeypatch.setattr(Entities, "fetch_one", fetch)
    monkeypatch.setattr(executor.database_utility, "save_mutations", race)
    result = drafts.save_form_draft(form, draft, baseline, "save-race", object())
    assert result["draft"]["name"] == "Accepted after restriction edit"
    assert memory_forms.rows[form.key]["restricted_to"] == ["admin"]
    assert allowed_restrictions == [None, ["admin"]]
    assert memory_forms.form().generation == 0
    assert len(memory_forms.rows) == 1
