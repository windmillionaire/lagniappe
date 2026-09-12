"""Immutable completion definitions, compatibility checks and history reads."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import json

import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools import form_definitions as definitions
from lagniappe.core.entities.history import TaskHistory
from testing.utility.test_entities import TestEntities


def _record(*, completed=True, generation=0, kind="task_history"):
    form = SimpleNamespace(key="form-key", generation=1, version="cache-only", schema=[
        {"id": "note", "type": "input", "title": "Current label"},
    ])
    return SimpleNamespace(
        entity_kind=kind, completed=completed, form=form,
        properties=SimpleNamespace(form=SimpleNamespace(key=form.key)),
        generation=generation, schema_version="ignored-legacy", db={}, urlsafe_key="completion-key",
    )


# @matrix submission task-completion : schema-version missing-schema
@pytest.mark.unit
def test_completed_definition_uses_recorded_version_and_reports_missing_schema():
    record = _record()
    old = SimpleNamespace(schema=[{"id": "note", "type": "input", "title": "Original label"}], content_available=False)
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation", return_value=old) as resolve:
        result = definitions.definition_for(record)
        assert result.schema[0]["title"] == "Original label"
        assert result.content_available is False
        assert definitions.definition_for(record) is result
        resolve.assert_called_once_with("form-key", 0)
    record.generation = 9
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation", return_value=None):
        result = definitions.definition_for(record)
        assert result.schema == []
        assert "unavailable" in result.error
    record.generation = 1
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation") as resolve:
        assert definitions.definition_for(record).source is record.form
        resolve.assert_not_called()


# @matrix submission task-completion : live-metadata
@pytest.mark.unit
def test_active_definition_uses_latest_metadata():
    record = _record(completed=False, kind="task")
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation") as resolve:
        assert definitions.definition_for(record).schema[0]["title"] == "Current label"
        record.form.schema[0]["title"] = "Later label"
        assert definitions.definition_for(record).schema[0]["title"] == "Later label"
        resolve.assert_not_called()


def _task():
    task = TestEntities.get("TASK", {
        "name": "Completion", "hash": "completed-definition",
        "page": {"name": "Parent", "hash": "completion-parent"},
        "form": {"name": "Form", "hash": "completion-form"},
    })
    task.form.schema = [{"id": "note", "type": "input", "title": "Current label"}]
    task.db["submission"] = json.dumps({"note": "Preserved answer"})
    task.db["schema_version"] = "original"
    task.form.version = "original"
    return task


# @matrix task-completion : generation original-view no-extra-read
@pytest.mark.unit
@pytest.mark.parametrize(
    "completed,task_generation,form_generation,original_generation,original,current,expected",
    [
        pytest.param(False, 1, 1, 0, {"note": "Old"}, {"note": "New"}, False, id="active-task"),
        pytest.param(True, 0, 0, 0, {"note": "Old"}, {"note": "New"}, False, id="generation-zero"),
        pytest.param(True, 2, 2, 2, {"note": "Old"}, {"note": "New"}, False, id="same-generation"),
        pytest.param(True, 0, 1, 0, {"note": "Old"}, {"note": "New"}, False, id="form-generation-only"),
        pytest.param(True, 1, 1, 0, {"note": "Old"}, {"note": "New"}, True, id="converted-answers"),
        pytest.param(True, 1, 1, 0, {"note": "Same"}, {"note": "Same"}, False, id="unaffected-answers"),
        pytest.param(True, 1, 1, 0, {}, {}, False, id="empty-answers"),
        pytest.param(True, 1, 1, 0, {"a": 1, "b": 2}, {"b": 2, "a": 1}, False, id="dictionary-order"),
        pytest.param(True, 2, 2, 2, {"note": "Same"}, {"note": "Same"}, False, id="completed-in-new-generation"),
        pytest.param(True, 1, 2, 2, {"note": "Old"}, {"note": "New"}, False, id="newer-original-generation"),
        pytest.param(True, 1, 1, None, None, {"note": "New"}, False, id="missing-original"),
        pytest.param(True, 1, 1, 0, {"note": True}, {"note": 1}, True, id="boolean-to-number"),
    ],
)
def test_original_answers_are_available_only_after_completed_values_change(
    completed, task_generation, form_generation, original_generation, original, current, expected,
):
    task = _task()
    task.completed = completed
    task.db["generation"] = task_generation
    task.form.generation = form_generation
    task.form.version = "updated-presentation"
    task.form.schema = [{"id": "note", "type": "input", "title": "Updated label"}]
    task.db["submission"] = json.dumps(current)
    if original_generation is not None:
        task.db["completed_submission"] = json.dumps({
            "submission": original, "generation": original_generation, "form_key": None,
        })

    with (
        patch("lagniappe.core.entities.task.completed_envelope", wraps=definitions.completed_envelope) as read_original,
        patch("lagniappe.core.tools.form_drafts.resolve_form_generation") as resolve,
        patch.object(definitions.database_get, "entity") as fetch,
    ):
        assert task.has_converted_completion is expected
        resolve.assert_not_called()
        fetch.assert_not_called()
        if not completed or task_generation == 0:
            read_original.assert_not_called()


# @matrix task-completion : immutable-submission
@pytest.mark.unit
def test_completed_mutations_are_rejected_before_changing_values():
    task = _task()
    task.completed = True
    before = deepcopy(dict(task.db))
    for mutate in (
        lambda: task.patch_submission({"note": "Changed"}),
        lambda: task.ai_submission({"note": "Changed"}),
        lambda: task.form_submission({"note": "Changed"}),
        lambda: task.update({"name": "Changed"}),
    ):
        with pytest.raises(ValidationError, match="[Cc]omplet|[Rr]eopen"):
            mutate()
        assert dict(task.db) == before
    other = TestEntities.get("FORM", {"name": "Other", "hash": "other-form"})
    with pytest.raises(ValidationError, match="original form"):
        task.form = other
    assert dict(task.db) == before


# @matrix task-completion submission : history-fill identity incompatible-value
@pytest.mark.unit
def test_history_transfer_preserves_identity_and_rejects_incompatible_values():
    source = [{"id": "choice", "type": "select", "title": "Old", "options": [{"value": "a", "label": "Old A"}]}]
    target = deepcopy(source)
    target[0].update(title="New")
    target[0]["options"][0]["label"] = "New A"
    assert definitions.compatible_values(source, target, {"choice": "a"}) == {"choice": "a"}
    target[0]["options"].append({"value": "b", "label": "Added B"})
    assert definitions.compatible_values(source, target, {"choice": "a"}) == {"choice": "a"}
    target[0]["multiple"] = True
    with pytest.raises(ValidationError, match="review"):
        definitions.compatible_values(source, target, {"choice": "a"})
    with pytest.raises(ValidationError, match="review"):
        definitions.compatible_values(source, [], {"choice": False})
    columns = [{"id": "count", "type": "input", "input": "number"}]
    table = [{"id": "items", "type": "table", "columns": columns}]
    values = {"items": {"rows": [{"count": 0}]}}
    copied = definitions.compatible_values(table, table, values)
    assert copied == values and copied is not values
    changed = deepcopy(table)
    changed[0]["columns"][0]["id"] = "other"
    with pytest.raises(ValidationError, match="review"):
        definitions.compatible_values(table, changed, values)
    live = _task()
    historical = _record(kind="task_history")
    historical.properties.form.key = live.properties.form.key
    historical.properties.submission = SimpleNamespace(value={"note": "Exact prior answer"})
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation", return_value=SimpleNamespace(schema=live.form.schema)):
        assert definitions.history_values_for(live, historical, "note") == {"note": "Exact prior answer"}
        historical.properties.form.key = "other-form"
        with pytest.raises(ValidationError, match="different form"):
            definitions.history_values_for(live, historical, "note")


# @matrix tasks task-completion : history schema-version ordering
@pytest.mark.unit
@pytest.mark.parametrize("last_form_key", ["form-key", "other-form-key"])
def test_history_groups_share_generation_tables_and_preserve_row_order(last_form_key):
    records = [_record(generation=generation) for generation in (0, 0, 2, 0)]
    for position, record in enumerate(records):
        record.urlsafe_key = f"completion-{position}"
    records[-1].properties.form.key = last_form_key
    identities = [("form-key", 0), ("form-key", 2)]
    grouped_records = [[records[0], records[1], records[3]], [records[2]]]
    if last_form_key != "form-key":
        identities.append((last_form_key, 0))
        grouped_records = [records[:2], [records[2]], [records[3]]]
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generations", side_effect=lambda pairs: {
        (key, generation): SimpleNamespace(schema=[{"id": "note", "title": generation}])
        for key, generation in pairs
    }) as resolve:
        groups = definitions.history_groups(records)
    assert list(resolve.call_args.args[0]) == identities
    assert [group["identity"] for group in groups] == identities
    assert [group["definition"].schema[0]["title"] for group in groups] == [
        generation for _, generation in identities
    ]
    assert [group["records"] for group in groups] == grouped_records
    assert [record.generation for record in records] == [0, 0, 2, 0]


# @matrix task-completion html-field : schema-version owned-image missing-content
@pytest.mark.unit
def test_history_html_uses_authorized_record_asset_urls():
    record = _record()
    asset = SimpleNamespace(url="/assets/snapshot/image_intro_photo.png", extension="png")
    source = SimpleNamespace(
        schema=[{"id": "intro", "type": "html"}], content_available=True,
        assets={"image_intro_photo": {"type": "image"}},
        get_asset=lambda name: asset,
        get_html_field=lambda field: '<p>Original</p><img src="/assets/snapshot/image_intro_photo.png">',
    )
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation", return_value=source):
        html = definitions.rendered_html_fields(record)["intro"]
        assert "/assets/completion-key/form-generation/0/image_intro_photo.png" in html
        assert "/assets/snapshot/" not in html
        assert "Original" in html
        source.content_available = False
        assert "unavailable" in definitions.rendered_html_fields(record)["intro"]


# @source lagniappe/core/entities/task.py::Task.complete
# @source lagniappe/core/entities/task.py::Task.uncomplete
# @source lagniappe/core/entities/history.py::TaskHistory.create
# @source lagniappe/core/properties/form_submission.py::FormSubmission.fields
# @matrix task-completion : schema-version history
# @pair submission:fields
@pytest.mark.unit
def test_completion_without_answers_pins_definition_and_reopen_archives_original():
    task = _task()
    task.submission = {}
    completer = TestEntities.get("USER", {
        "name": "Completer", "hash": "completion-actor",
        "page": {"name": "Completer page", "hash": "completion-actor-page"},
    })
    task.complete(user=completer)
    envelope = json.loads(task.db["completed_submission"])
    assert envelope == {"submission": {}, "generation": 0, "form_key": None}
    assert task.generation == 0
    task.form.schema = [{"id": "note", "type": "input", "title": "Renamed"}]
    task.properties.submission._fields = None
    assert task.properties.submission.fields["note"].label == "Renamed"
    with patch("lagniappe.core.entities.entity.database_utility.create_key", return_value="history-key"):
        task.uncomplete()
    history = task.new_history_created[0]
    assert history.generation == 0
    assert history.submission == {}
    assert task.completed is False
    assert "completed_submission" not in task.db
    assert task.properties.submission.fields["note"].label == "Renamed"
    assert task.submission == {}


# @source lagniappe/core/entities/task.py::Task.uncomplete
# @source lagniappe/core/entities/task.py::Task.create_history_entry
# @source lagniappe/core/entities/history.py::TaskHistory.create
# @matrix task-completion : history schema-version asset-copy uncomplete
@pytest.mark.unit
@pytest.mark.parametrize("submission_source", [None, "original", "modified"])
def test_uncomplete_archives_selected_raw_answers_and_their_generation(submission_source):
    task = _task()
    original = {"note": "Original answer", "old_value": False}
    modified = {"note": "Modified answer", "new_value": [0, False, None, ""]}
    task.db["submission"] = json.dumps(modified)
    task.db["generation"] = 1
    task.form.db["generation"] = 2
    task.completed = True
    task.db["completed_submission"] = json.dumps({
        "submission": original, "generation": 0,
        "form_key": definitions.database_get.urlsafe_key(task.properties.form.key),
    })
    task.db["default_submission"] = json.dumps({"note": "Repeat this"})
    envelope = task.db["completed_submission"]
    kwargs = {} if submission_source is None else {"submission_source": submission_source}

    with (
        patch("lagniappe.core.entities.entity.database_utility.create_key", return_value="history-key"),
        patch.object(definitions.database_get, "entity", return_value=None),
        patch.object(TaskHistory, "copy_assets", autospec=True) as copy_assets,
        patch.object(TaskHistory, "ai_submission", side_effect=AssertionError("Do not convert saved answers")),
        patch.object(definitions, "completed_envelope", wraps=definitions.completed_envelope) as read_original,
    ):
        task.uncomplete(**kwargs)
        history = task.new_history_created[0]
        copy_assets.assert_called_once_with(history, task)
        if submission_source == "modified":
            read_original.assert_not_called()
        else:
            read_original.assert_called_once_with(task)
        task.uncomplete(**kwargs)
        assert task.new_history_created == [history]
        copy_assets.assert_called_once()

    assert history.submission == (modified if submission_source == "modified" else original)
    assert history.generation == (1 if submission_source == "modified" else 0)
    assert history.properties.form.key == task.properties.form.key
    assert "completed_submission" not in history.db
    assert task._completion_transition["envelope"] == envelope
    assert task.completed is False
    assert "completed_submission" not in task.db
    assert task.submission == {}
    assert "default_submission" not in task.db
    assert task.generation == 2


# @source lagniappe/core/entities/task.py::Task.uncomplete
# @matrix task-completion mutations : immutable-submission concurrency
@pytest.mark.unit
@pytest.mark.parametrize("changed_field,new_value", [
    ("submission", '{"note":"Newer conversion"}'),
    ("generation", 2),
    ("form", "different-form"),
    ("assets", {"signature": {"path": "newer-signature"}}),
])
def test_modified_uncomplete_rejects_stale_current_answers_before_archiving(changed_field, new_value):
    task = _task()
    task.completed = True
    task.db["generation"] = 1
    task.db["completed_submission"] = json.dumps({
        "submission": {"note": "Original"}, "generation": 0, "form_key": None,
    })
    before = deepcopy(dict(task.db))
    persisted = {**before, changed_field: new_value}
    with (
        patch.object(
            definitions.database_get, "entity",
            side_effect=lambda key: persisted if key == task.key else None,
        ),
        patch.object(task, "create_history_entry") as archive,
    ):
        with pytest.raises(ValidationError, match="changed before reopening"):
            task.uncomplete(submission_source="modified")
        archive.assert_not_called()
    assert dict(task.db) == before


# @source lagniappe/core/entities/task.py::Task.uncomplete
# @matrix task-completion : immutable-submission uncomplete
@pytest.mark.unit
@pytest.mark.parametrize("submission_source", [None, "unexpected", ""])
def test_uncomplete_rejects_invalid_submission_selection_before_mutation(submission_source):
    task = _task()
    task.completed = True
    before = deepcopy(dict(task.db))
    with patch.object(definitions.database_get, "entity") as fetch:
        with pytest.raises(ValidationError, match="original or modified"):
            task.uncomplete(submission_source=submission_source)
        fetch.assert_not_called()
    assert dict(task.db) == before
    assert not task.new_history_created


# @matrix task-completion mutations : immutable-submission concurrency
@pytest.mark.unit
def test_completion_write_rejects_raw_changes_and_stages_original_guards():
    task = _task()
    task.completed = True
    task.db["completed_submission"] = json.dumps({
        "submission": {"note": "Original"}, "generation": 0, "form_key": None,
    })
    persisted = deepcopy(dict(task.db))
    definitions.validate_completion_write(task, persisted)
    expected = task._completion_write_guards[0][1]
    assert expected["completed"] is True
    # The current representation can be updated separately by a future transfer;
    # it never replaces the original completion envelope.
    task.db["submission"] = json.dumps({"note": "Transferred current value"})
    task.db["generation"] = 1
    definitions.validate_completion_write(task, persisted)
    assert task.db["completed_submission"] == persisted["completed_submission"]
    task.db["completed_submission"] = persisted["completed_submission"].replace("Original", "Changed")
    with pytest.raises(ValidationError, match="cannot be changed"):
        definitions.validate_completion_write(task, persisted)
    with patch.object(definitions.database_get, "entity", return_value=persisted):
        with pytest.raises(ValidationError, match="cannot be changed"):
            task.uncomplete()


# @matrix task-completion submission : schema-version incompatible-value preservation
@pytest.mark.unit
def test_completion_rejects_unrepresented_values_without_rewriting_answers():
    task = _task()
    task.db["submission"] = json.dumps({"removed": False})
    original = task.db["submission"]
    with pytest.raises(ValidationError, match="unavailable field"):
        task.complete()
    assert task.db["submission"] == original
    assert not task.completed
    task.db["submission"] = json.dumps({"note": "Preserved answer"})
    task.properties.submission.value = {"note": "Preserved answer"}
    task.form.db["generation"] = 1
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation") as resolve:
        with pytest.raises(ValidationError, match="transfer"):
            task.complete()
        resolve.assert_not_called()
    assert "completed_submission" not in task.db


# @matrix submission : ai unknown-fields preservation
@pytest.mark.unit
def test_generated_answers_reject_unknown_fields_before_resetting_values():
    task = _task()
    before = deepcopy(task.submission)
    with pytest.raises(ValidationError, match="unavailable fields"):
        task.ai_submission({"removed": "New answer"})
    assert task.submission == before
    assert task.properties.submission.fields["note"].value == "Preserved answer"


# @source lagniappe/core/entities/task.py::Task
# @matrix task-completion mutations : hydration no-extra-read
@pytest.mark.unit
def test_task_construction_does_not_hydrate_or_copy_whole_rows():
    from google.cloud import datastore
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.task import Task

    assert Task.db is Entity.db
    for entity_type in (Task, TaskHistory):
        key = datastore.Key("tasks", "lazy", project="test")
        raw = datastore.Entity(key=key)
        raw.update(kind=entity_type.entity_kind, submission='{"note":"Saved"}', completed=True,
                   unrelated_metadata={"large": [1, 2, 3]})
        with patch("lagniappe.core.entities.entity.database_get.entity", return_value=raw) as fetch:
            lazy = entity_type(key)
            loaded = entity_type(raw)
            fetch.assert_not_called()
            assert loaded.db is raw
            assert lazy.db is raw
            fetch.assert_called_once_with(key)
            assert "_completion_identity" not in loaded.__dict__
            assert "_completion_identity" not in lazy.__dict__


# @source lagniappe/core/tools/form_definitions.py::preload_definitions
# @source lagniappe/core/properties/form_submission.py::FormSubmission.value
# @matrix submission task-completion : schema-version
# @matrix task-completion : current-definition no-extra-read
@pytest.mark.unit
def test_completed_envelope_uses_matching_current_definition_without_history_read():
    task = _task()
    original_key = task.properties.form.key
    task.db["completed_submission"] = json.dumps({
        "submission": {"note": "Original answer"}, "generation": 0,
        "form_key": definitions.database_get.urlsafe_key(original_key),
    })
    task.completed = True
    task.db["schema_version"] = "ignored-old-version"
    task.db["submission"] = '{"note":"Current answer"}'
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation") as resolve, patch("lagniappe.core.tools.form_drafts.resolve_form_generations") as resolve_many:
        assert task.schema_version == "ignored-old-version"
        assert task.submission == {"note": "Current answer"}
        assert task.submission_definition.source is task.form
        original = definitions.original_completion(task)
        assert original["definition"].source is task.form
        assert original["submission"] == {"note": "Original answer"}
        assert original["generation"] == 0
        definitions.preload_definitions([task, task])
        resolve.assert_not_called()
        resolve_many.assert_not_called()
    # Same-generation presentation changes are current for both views.
    task.form.schema = [{"id": "note", "type": "input", "title": "New presentation"}]
    assert definitions.original_completion(task)["definition"].schema[0]["title"] == "New presentation"
    task.form.db["generation"] = 1
    old = SimpleNamespace(schema=[{"id": "note", "type": "input", "title": "Archived"}], content_available=True)
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation", return_value=old) as resolve:
        assert task.submission_definition.source is task.form
        resolve.assert_not_called()
        original = definitions.original_completion(task)
        assert original["definition"].source is old
        assert original["submission"] == {"note": "Original answer"}
        resolve.assert_called_once_with(original_key, 0)
    assert task.submission == {"note": "Current answer"}


# @source lagniappe/core/entities/task.py::Task.uncomplete
# @matrix task-completion mutations : immutable-submission concurrency
@pytest.mark.unit
def test_envelope_write_guard_rejects_raw_mutation_and_stale_active_overwrite():
    task = _task()
    persisted = deepcopy(dict(task.db))
    task.db["completed"] = True
    with pytest.raises(ValidationError, match="Complete the task"):
        definitions.validate_completion_write(task, persisted)
    task.db["completed"] = False
    with patch.object(definitions.database_get, "entity", side_effect=lambda key: persisted if key == task.key else None):
        definitions.capture_completed_submission(task)
    task.completed = True
    definitions.validate_completion_write(task, persisted)
    original_envelope = task.db["completed_submission"]
    task.db["completed_submission"] = original_envelope.replace("Preserved", "Changed")
    with pytest.raises(ValidationError, match="cannot be changed"):
        definitions.validate_completion_write(task, persisted)
    with pytest.raises(ValidationError, match="cannot be changed"):
        task.uncomplete()
    task.db["completed_submission"] = original_envelope
    concurrent = {**persisted, "submission": '{"note":"Concurrent answer"}'}
    with pytest.raises(ValidationError, match="changed during completion"):
        definitions.validate_completion_write(task, concurrent)


# @source lagniappe/core/tools/form_definitions.py::original_completion
# @matrix submission task-completion : schema-version missing-schema raw-values
@pytest.mark.unit
def test_legacy_original_completion_uses_generation_zero_and_preserves_missing_answers():
    task = _task()
    task.completed = True
    task.db["schema_version"] = "legacy-version-never-used-for-history"
    assert definitions.original_completion(task)["generation"] == 0
    task.form.db["generation"] = 2
    with patch("lagniappe.core.tools.form_drafts.resolve_form_generation", return_value=None) as resolve:
        original = definitions.original_completion(task)
    resolve.assert_called_once_with(task.properties.form.key, 0)
    assert original["submission"] == {"note": "Preserved answer"}
    assert original["definition"].schema == []
    assert "unavailable" in original["definition"].error
    assert task.submission_definition.source is task.form
