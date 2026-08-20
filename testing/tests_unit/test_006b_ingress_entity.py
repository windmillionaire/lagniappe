"""
Unit tests for Ingress entity and Stage orchestrator.

Tests stage navigation, related-entity fields (project/category/model/form),
and stage finalization.

Full import execution (Ingress.save, production entity creation, and cache-backed
page lookup) is not covered here—see e2e import flows. Local import-row
orchestration is covered with faked entity creation.
Assign ``project`` / ``category`` / ``model`` (and ``form`` when needed) directly;
do not assert ``ingress.parent`` here—``TestEntityMixin.parent`` touches
``properties.parent`` (FILTER-only) before delegating and breaks on INGRESS.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

import lagniappe.core.entities.ingress as ingress_module
import lagniappe.core.exceptions.unloaded_relations as unloaded_relations_module
import lagniappe.core.properties.file_ingress as file_ingress
import lagniappe.core.tools.ingress as ingress_service
from lagniappe.core.definitions import (
    Fetch,
    FileConsumerLimitError,
    IngressFormatError,
    IngressStage,
    LARGE_ASSET_BYTES,
)
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import PropertyError, ValidationError
from lagniappe.core.tools.files.validate import process_csv
from lagniappe.core.properties.file_ingress import ProcessCSV, Stage

from testing.utility.test_entities import TestEntities


CSV_DIR = Path(__file__).parent.parent / "files"


@pytest.mark.unit
def test_ingress_rejects_oversized_csv_before_read():
    upload = SimpleNamespace(
        filename="oversized.csv",
        size=LARGE_ASSET_BYTES + 1,
        read=lambda: (_ for _ in ()).throw(
            AssertionError("oversized CSV must not be read")
        ),
    )

    with pytest.raises(
        FileConsumerLimitError,
        match=r"oversized\.csv is too large for CSV import",
    ):
        Entities.INGRESS.create(upload)


@pytest.fixture
def sample_csv_data():
    """Load and process sample CSV data."""
    csv_path = CSV_DIR / "sample_data.csv"
    text = csv_path.read_text()
    return process_csv(text)


@pytest.fixture
def ingress_entity(sample_csv_data):
    """Create a test ingress entity with processed CSV data."""
    test_spec = {
        "hash": "ingress001",
        "name": "Test Import",
        "kind": "ingress",
    }
    ingress = TestEntities.get("INGRESS", test_spec)
    ingress.db["ingress_format"] = 1
    ingress.get_process("workflow").update(
        {
            "current": "PROCESS_CSV",
            "highest_completed": "PROCESS_CSV",
            "configuration_revision": 1,
            "process_csv": {
                "delimiter": sample_csv_data["delimiter"],
                "columns": sample_csv_data["columns"],
                "row_count": sample_csv_data["row_count"],
                "column_count": sample_csv_data["column_count"],
                "complete": True,
            },
        }
    )
    ingress.get_process("execution").update(
        {"status": "idle", "cursor": 0, "total_rows": 2}
    )
    ingress.db["rows"] = sample_csv_data["rows"]
    return ingress


def make_raw_ingress(name="Test Import", entity_type=None):
    """Create a production Ingress instance with no datastore key side effects."""
    ingress = Entities.INGRESS(testing=True)
    ingress.db.update(
        {
            "type": "ingress",
            "hash": f"{name.lower().replace(' ', '_')}_hash",
            "name": name,
            "active": True,
            "requires": ["site"],
            "ingress_format": 1,
        }
    )
    ingress.get_process("workflow").update(
        {
            "current": "PROCESS_CSV",
            "highest_completed": "PROCESS_CSV",
            "configuration_revision": 1,
            "process_csv": {"complete": True},
        }
    )
    ingress.get_process("execution").update(
        {"status": "idle", "cursor": 0, "total_rows": 0}
    )
    if entity_type:
        ingress.properties.choose_type.entity_type = entity_type
    return ingress


def set_ingress_csv_payload(ingress, csv_data):
    ingress.properties.process_csv.columns = csv_data["columns"]
    ingress.properties.process_csv.row_count = csv_data["row_count"]
    ingress.properties.process_csv.column_count = csv_data["column_count"]
    ingress.properties.process_csv.delimiter = csv_data["delimiter"]
    ingress.properties.rows._asset = csv_data["rows"]


# @features ingress
# @dimensions stage property
def test_stage_returns_property(ingress_entity):
    """ingress.stage returns the Stage orchestrator; name matches Enum member name."""
    stage = ingress_entity.stage

    assert isinstance(stage, Stage)
    assert stage.name == "PROCESS_CSV"
    assert ingress_entity.get_process("workflow")["current"] == "PROCESS_CSV"


# @features ingress
# @dimensions stage enum
def test_stage_set_enum(ingress_entity):
    """Setting stage via IngressStage enum updates db and Stage.name."""
    ingress_entity.properties.stage.value = IngressStage.CHOOSE_TYPE

    assert ingress_entity.stage.name == "CHOOSE_TYPE"
    assert ingress_entity.get_process("workflow")["current"] == "CHOOSE_TYPE"


# @features ingress
# @dimensions stage string
def test_stage_set_string(ingress_entity):
    """Setting stage with uppercase string key."""
    ingress_entity.properties.stage.value = "CHOOSE_FORM"

    assert ingress_entity.stage.name == "CHOOSE_FORM"
    assert ingress_entity.get_process("workflow")["current"] == "CHOOSE_FORM"


# @features ingress
# @dimensions stage validation
def test_stage_set_invalid_raises(ingress_entity):
    """Invalid stage value raises."""
    with pytest.raises(ValueError, match="Invalid stage"):
        ingress_entity.properties.stage.value = 12345


# @features ingress
# @dimensions stage default
def test_stage_default():
    """Unversioned ingress rows are rejected instead of guessed."""
    test_spec = {"hash": "ingress002", "name": "New Import", "kind": "ingress"}
    ingress = TestEntities.get("INGRESS", test_spec)
    ingress.db.pop("ingress_format", None)
    ingress.processes.clear()

    with pytest.raises(IngressFormatError, match="unsupported ingress format"):
        _ = ingress.stage.name


# @features ingress
# @dimensions stage navigation back
def test_back_moves_to_prior_stage(ingress_entity):
    """Stage.back() moves to previous stage (returns None; check db)."""
    ingress_entity.properties.stage.value = IngressStage.CHOOSE_TYPE

    result = ingress_entity.properties.stage.back()

    assert result is None
    assert ingress_entity.get_process("workflow")["current"] == "PROCESS_CSV"
    assert ingress_entity.stage.name == "PROCESS_CSV"


# @features ingress
# @dimensions stage navigation first-stage
def test_back_at_first_stage_noop(ingress_entity):
    """Stage.back() at first stage returns None and leaves stage unchanged."""
    ingress_entity.properties.stage.value = IngressStage.PROCESS_CSV

    result = ingress_entity.properties.stage.back()

    assert result is None
    assert ingress_entity.get_process("workflow")["current"] == "PROCESS_CSV"


# @features ingress
# @dimensions stage navigation finalize
def test_next_advances_after_finalize(ingress_entity):
    """Stage.next() finalizes current stage and advances (returns None; check db)."""
    ingress_entity.properties.stage.value = IngressStage.CHOOSE_TYPE
    ingress_entity.properties.choose_type.entity_type = "page"

    result = ingress_entity.properties.stage.next()

    assert result is None
    assert ingress_entity.get_process("workflow")["current"] == "CHOOSE_PARENT"
    assert ingress_entity.stage.name == "CHOOSE_PARENT"


# @features ingress
# @dimensions stage status
def test_stage_status(ingress_entity):
    """properties.stage.status(stage) returns the ProcessProperty for that stage."""
    status = ingress_entity.properties.stage.status(IngressStage.PROCESS_CSV)

    assert isinstance(status, ProcessCSV)
    assert status.section_id == "process_csv"


# @features ingress
# @dimensions choose-type update
def test_choose_type_update_via_current_stage_property(ingress_entity):
    """Update current stage data through choose_type.update (Stage has no update)."""
    ingress_entity.properties.stage.value = IngressStage.CHOOSE_TYPE
    form_data = {"entity-type": "page"}

    ingress_entity.properties.choose_type.update(form_data)

    assert ingress_entity.properties.choose_type.entity_type == "page"


# @features ingress
# @dimensions choose-type clear-downstream
@pytest.mark.unit
def test_import_wizard_story_restarts_downstream_choices_when_entity_type_changes(
    ingress_entity,
):
    ingress_entity.properties.choose_type.entity_type = "page"
    ingress_entity.properties.choose_parent.section = {
        "parent-choice": "existing-parent",
        "parent-id": "category-key",
    }
    ingress_entity.properties.choose_form.section = {
        "form-choice": "existing-form",
        "form-id": "form-key",
    }
    ingress_entity.properties.assign_columns.section = {"col-name": "name"}
    ingress_entity.properties.verify_import.section = {"index-to": "name"}
    ingress_entity.properties.importing.section = {"complete": True}
    ingress_entity.properties.completed.section = {"complete": True}

    ingress_entity.properties.choose_type.update({"entity-type": "page"})

    assert ingress_entity.properties.choose_parent.parent_choice == "existing-parent"
    assert ingress_entity.properties.choose_form.form_id == "form-key"
    assert ingress_entity.properties.assign_columns.section == {"col-name": "name"}

    ingress_entity.properties.choose_type.update({"entity-type": "task"})

    assert ingress_entity.properties.choose_type.entity_type == "task"
    assert ingress_entity.properties.choose_parent.section == {}
    assert ingress_entity.properties.choose_form.section == {}
    assert ingress_entity.properties.assign_columns.section == {}
    assert ingress_entity.properties.verify_import.section == {}
    assert ingress_entity.properties.importing.section == {}
    assert ingress_entity.properties.completed.section == {}


# @features ingress form
# @dimensions choose-form schema-generation default-form
@pytest.mark.unit
def test_import_wizard_story_builds_or_selects_the_submission_form(
    sample_csv_data, monkeypatch
):
    created_form = TestEntities.get(
        "FORM", {"hash": "created_form", "name": "Created Form"}
    )
    existing_form = TestEntities.get(
        "FORM", {"hash": "existing_form", "name": "Existing Form"}
    )
    old_form = TestEntities.get("FORM", {"hash": "old_form", "name": "Old Form"})
    category = TestEntities.get(
        "CATEGORY", {"hash": "category_form_parent", "name": "People"}
    )
    created_forms = []
    loaded_forms = []

    class FormFactory:
        def __call__(self, form_id):
            loaded_forms.append(form_id)
            return existing_form

        def create(self, data):
            created_forms.append(data)
            created_form.form_type = data["form-type"]
            created_form.set_schema(data["schema"])
            return created_form

    monkeypatch.setattr(file_ingress.Entities, "FORM", FormFactory())

    page_ingress = make_raw_ingress("People Import", "page")
    page_ingress.category = category
    set_ingress_csv_payload(page_ingress, sample_csv_data)
    page_ingress.properties.choose_form.update(
        {
            "form-choice": "use-columns",
            "form-name": "People Import Form",
            "set-default-form": "on",
        }
    )

    page_ingress.properties.choose_form.process()

    assert len(created_forms) == 1
    assert created_forms[0]["name"] == "People Import Form"
    assert created_forms[0]["form-type"] == "page"
    assert any(field["title"] == "email" for field in created_forms[0]["schema"])
    assert page_ingress.form is created_form
    assert category.form is created_form
    assert any(field["title"] == "email" for field in created_form.schema)
    assert page_ingress.properties.choose_form.separator is None

    task_ingress = make_raw_ingress("Task Import", "task")
    task_ingress.form = old_form
    cleared = []
    task_ingress.clear_form_stages = lambda: cleared.append(True)
    task_ingress.properties.choose_form.update(
        {
            "form-choice": "existing-form",
            "form-id": "existing_form",
        }
    )

    task_ingress.properties.choose_form.process()

    assert loaded_forms == ["existing_form"]
    assert task_ingress.form is existing_form
    assert cleared == [True]


# @features ingress project
# @dimensions related-entities parent
def test_related_entities_project():
    """Setting project establishes parent for project-only import target."""
    project = TestEntities.get("PROJECT", {"hash": "proj001", "name": "Test Project"})
    test_spec = {"hash": "ingress003", "name": "Import", "kind": "ingress"}
    ingress = TestEntities.get("INGRESS", test_spec)

    ingress.project = project

    assert ingress.project == project
    assert ingress.form is None


# @features ingress category form
# @dimensions related-entities parent
def test_related_entities_category_and_form():
    """Setting category; form set explicitly (same outcome as parent=category)."""
    form = TestEntities.get("FORM", {"hash": "form002", "name": "Test Form"})
    category = TestEntities.get("CATEGORY", {"hash": "cat001", "name": "Test Category"})
    category.properties.form._value = form
    test_spec = {"hash": "ingress004", "name": "Import", "kind": "ingress"}
    ingress = TestEntities.get("INGRESS", test_spec)

    ingress.category = category
    ingress.form = form

    assert ingress.category == category
    assert ingress.form == form


# @features ingress project form task
# @dimensions related-entities model
def test_related_entities_model_project_form():
    """Setting model and project (and form) matches model-as-parent wiring."""
    form = TestEntities.get("FORM", {"hash": "form003", "name": "Test Form"})
    project = TestEntities.get("PROJECT", {"hash": "proj002", "name": "Test Project"})
    model = TestEntities.get(
        "MODEL_TASK",
        {"hash": "model001", "name": "Test Model", "project": "proj002"},
        project=project,
    )
    model.properties.form._value = form
    test_spec = {"hash": "ingress005", "name": "Import", "kind": "ingress"}
    ingress = TestEntities.get("INGRESS", test_spec)

    ingress.model = model
    ingress.project = project
    ingress.form = form

    assert ingress.model == model
    assert ingress.project == project
    assert ingress.form == form


# @features relations
# @dimensions validation key-validation
@pytest.mark.unit
def test_related_entity_setter_rejects_values_without_key():
    ingress = make_raw_ingress("Invalid Relation", "page")

    with pytest.raises(ValueError, match="Value must have a key"):
        ingress.category = SimpleNamespace()


# @features ingress
# @dimensions stage finalize process-complete
def test_finalize_sets_choose_type_complete(ingress_entity):
    """Stage.finalize() runs finalize path on current stage ProcessProperty."""
    ingress_entity.properties.stage.value = IngressStage.CHOOSE_TYPE
    ingress_entity.properties.choose_type.entity_type = "page"

    ingress_entity.properties.stage.finalize()

    assert ingress_entity.properties.choose_type.complete is True


# @features ingress
# @dimensions process-state clear
def test_stage_clear():
    """clear() on a ProcessProperty resets section-backed fields."""
    test_spec = {"hash": "ingress_clear", "name": "Import", "kind": "ingress"}
    ingress = TestEntities.get("INGRESS", test_spec)
    ingress.db["stage"] = "CHOOSE_TYPE"

    ingress.properties.choose_type.entity_type = "page"
    ingress.properties.choose_type.complete = True

    assert ingress.properties.choose_type.entity_type == "page"
    assert ingress.properties.choose_type.complete is True

    ingress.properties.choose_type.clear()

    assert ingress.properties.choose_type.entity_type is None
    assert ingress.properties.choose_type.complete is None


# @features ingress
# @dimensions stage error-handling
@pytest.mark.unit
def test_import_wizard_story_reports_stage_errors_without_advancing(
    ingress_entity, monkeypatch
):
    captured = []
    ingress_entity.properties.stage.value = IngressStage.PROCESS_CSV
    ingress_entity.mimetype = "application/pdf"
    ingress_entity.properties.choose_type.entity_type = "page"

    def capture_error(error, context=None):
        captured.append((str(error), context))

    monkeypatch.setattr(ingress_service.exceptions, "capture", capture_error)

    ingress_entity.properties.stage.next()

    assert ingress_entity.stage.name == "PROCESS_CSV"
    assert ingress_entity.properties.process_csv.error == "File must be a CSV file."
    assert ingress_entity.properties.process_csv.complete is None
    assert ingress_entity.properties.choose_type.entity_type == "page"
    assert captured == []


# @features ingress
# @dimensions process-csv upload-counts rows asset-storage
@pytest.mark.unit
def test_import_wizard_story_parses_the_uploaded_csv_into_rows_and_columns(
    sample_csv_data,
):
    ingress = TestEntities.get(
        "INGRESS", {"hash": "ingress_csv_process", "name": "CSV Import"}
    )
    saved_assets = {}
    csv_text = (CSV_DIR / "sample_data.csv").read_text()
    ingress.mimetype = "text/csv"
    ingress.properties.text._asset = csv_text

    def save_asset(content, name, asset_type, visibility="private"):
        saved_assets[name] = {
            "content": content,
            "type": asset_type,
            "visibility": visibility,
        }
        return SimpleNamespace(get=lambda: content)

    ingress.save_asset = save_asset

    ingress.properties.process_csv.process()

    assert ingress.properties.process_csv.delimiter == sample_csv_data["delimiter"]
    assert ingress.properties.process_csv.row_count == sample_csv_data["row_count"]
    assert ingress.properties.process_csv.column_count == sample_csv_data["column_count"]
    assert ingress.properties.process_csv.columns == sample_csv_data["columns"]
    assert saved_assets == {
        "rows": {
            "content": sample_csv_data["rows"],
            "type": "json",
            "visibility": "private",
        }
    }


# @features ingress
# @dimensions choose-parent parent model form-reset
@pytest.mark.unit
def test_import_wizard_story_reuses_or_creates_the_parent_before_form_mapping(
    monkeypatch,
):
    category = TestEntities.get(
        "CATEGORY", {"hash": "new_category", "name": "New Category"}
    )
    project = TestEntities.get(
        "PROJECT", {"hash": "existing_project", "name": "Existing Project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"hash": "new_model", "name": "Imported Tasks", "project": project.hash},
        project=project,
    )
    old_form = TestEntities.get("FORM", {"hash": "old_parent_form", "name": "Old"})
    new_form = TestEntities.get("FORM", {"hash": "new_parent_form", "name": "New"})
    form_category = TestEntities.get(
        "CATEGORY", {"hash": "form_category", "name": "Form Category"}
    )
    form_category.properties.form._value = new_form
    created_categories = []
    created_models = []

    monkeypatch.setattr(
        file_ingress.Entities,
        "CATEGORY",
        SimpleNamespace(
            create=lambda data: created_categories.append(data) or category
        ),
    )
    monkeypatch.setattr(
        file_ingress.Entities,
        "MODEL_TASK",
        SimpleNamespace(
            create=lambda parent, data: created_models.append((parent, data)) or model
        ),
    )
    loaded_parents = []

    def get_parent(parent_id, *, request):
        loaded_parents.append((parent_id, request))
        return project if parent_id == project.key else form_category

    monkeypatch.setattr(file_ingress.Entities, "fetch_one", get_parent)

    page_ingress = make_raw_ingress("Create Category Import", "page")
    page_ingress.properties.choose_parent.update(
        {
            "parent-choice": "create-parent",
            "parent-name": "New Category",
        }
    )
    page_ingress.properties.choose_parent.process()

    assert created_categories == [{"name": "New Category"}]
    assert page_ingress.category is category
    assert page_ingress.project is None
    assert page_ingress.model is None

    task_ingress = make_raw_ingress("Create Model Import", "task")
    task_ingress.properties.choose_parent.update(
        {
            "parent-choice": "existing-parent",
            "parent-id": project.key,
            "create-model": "on",
            "model-name": "Imported Tasks",
        }
    )
    task_ingress.properties.choose_parent.process()

    assert task_ingress.project is project
    assert task_ingress.model is model
    assert created_models == [(project, {"name": "Imported Tasks"})]
    assert loaded_parents == [(project.key, Fetch.direct())]

    reset_ingress = make_raw_ingress("Reset Form Import", "page")
    reset_ingress.form = old_form
    cleared = []
    reset_ingress.clear_form_stages = lambda: cleared.append(True)
    reset_ingress.properties.choose_parent.update(
        {
            "parent-choice": "existing-parent",
            "parent-id": form_category.key,
        }
    )
    reset_ingress.properties.choose_parent.process()

    assert reset_ingress.category is form_category
    assert reset_ingress.form is new_form
    assert cleared == [True]
    assert loaded_parents == [
        (project.key, Fetch.direct()),
        (form_category.key, Fetch.direct()),
    ]


# @features ingress relations
# @dimensions existing-parent model-load required-validation
@pytest.mark.unit
def test_import_wizard_existing_model_parent_loads_project_for_required(monkeypatch):
    project = TestEntities.get(
        "PROJECT", {"hash": "existing_model_project", "name": "Existing Project"}
    )
    form = TestEntities.get(
        "FORM", {"hash": "existing_model_form", "name": "Existing Form"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {
            "hash": "existing_model_task",
            "name": "Existing Model",
            "project": project.hash,
        },
        project=project,
    )
    model.form = form
    loaded = []

    def get_parent(parent_id, *, request):
        loaded.append((parent_id, request))
        return model

    monkeypatch.setattr(file_ingress.Entities, "fetch_one", get_parent)

    ingress = make_raw_ingress("Existing Model Import", "task")
    ingress.properties.choose_parent.update(
        {
            "parent-choice": "existing-parent",
            "parent-id": model.key,
        }
    )

    ingress.properties.choose_parent.process()

    assert loaded == [(model.key, Fetch.direct())]
    assert ingress.model is model
    assert ingress.project is project
    assert ingress.form is form
    assert model.required == ["models", model.hash, project.hash]


# @features requires
# @dimensions validation unloaded-relation
@pytest.mark.unit
def test_model_task_required_reports_unloaded_project_relation(monkeypatch):
    monkeypatch.setattr(
        unloaded_relations_module.CONFIG,
        "STRICT_RELATION_LOADS",
        False,
    )
    model = Entities.MODEL_TASK(testing=True)
    model.db.update(
        {
            "type": "model",
            "hash": "model_missing_project",
            "name": "Missing Project",
            "project": "project_key",
        }
    )

    with pytest.raises(PropertyError, match="requires a loaded project relation"):
        _ = model.required

    with pytest.raises(PropertyError, match="requires a loaded project relation"):
        model.properties.requires.update()


# @features ingress
# @dimensions assign-columns table-fields ignored-columns guessed-fields task-name multiple-columns
@pytest.mark.unit
def test_import_wizard_story_maps_csv_columns_to_page_task_and_table_fields(
    get_schema,
):
    ingress = TestEntities.get(
        "INGRESS", {"hash": "ingress_assign_columns", "name": "Assign Columns"}
    )
    form = TestEntities.get(
        "FORM", {"hash": "assign_form", "name": "Assign Form"}
    )
    form.schema = get_schema("complex_types")
    ingress.form = form
    ingress.properties.choose_type.entity_type = "task"
    ingress.properties.process_csv.columns = {
        "col-name": {"label": "Name", "icon": "text", "type": "string"},
        "col-email": {"label": "Email", "icon": "email", "type": "string"},
        "col-due": {"label": "Due Date", "icon": "date", "type": "datetime"},
        "col-task-prefix": {
            "label": "Task Prefix",
            "icon": "text",
            "type": "string",
        },
        "col-task-name": {
            "label": "Task Name",
            "icon": "text",
            "type": "string",
        },
        "col-website": {"label": "Website", "icon": "link", "type": "string"},
        "col-ignore": {"label": "Ignore Me", "icon": "text", "type": "string"},
    }
    ingress.properties.assign_columns.update(
        {
            "col-name": "name",
            "col-email": "row-emailef34",
            "col-due": "due_date",
            "col-task-prefix": "task_name",
            "col-task-name": "task_name",
            "ignore-col-ignore": "on",
        }
    )

    assign = ingress.properties.assign_columns

    assert {
        "name",
        "task_name",
        "completed_on",
        "due_date",
        "row-emailef34",
    }.issubset(assign.fields)
    assert "signature-signop" not in assign.fields
    assert "html-instructqr" not in assign.fields
    assert assign.ignore("col-ignore") == "on"
    assert assign.guess_field("col-website")["id"] == "link-externalij"
    assert assign.column_map == {
        "col-name": {
            **assign.fields["name"],
            "index": 0,
        },
        "col-email": {
            **assign.fields["row-emailef34"],
            "index": 1,
        },
        "col-due": {
            **assign.fields["due_date"],
            "index": 2,
        },
        "col-task-prefix": {
            **assign.fields["task_name"],
            "index": 3,
        },
        "col-task-name": {
            **assign.fields["task_name"],
            "index": 4,
        },
    }
    assert assign.field_map == {
        "name": ["col-name"],
        "task_name": ["col-task-prefix", "col-task-name"],
        "due_date": ["col-due"],
        "row-emailef34": ["col-email"],
    }
    assert assign.field("name")["description"] == "{ Name }"
    assert assign.field("task_name")["description"] == (
        "{ Task Prefix } { Task Name }"
    )
    assert assign.field("row-emailef34")["description"] == "{ Email }"


# @features ingress
# @dimensions assign-columns stale-field
@pytest.mark.unit
def test_import_wizard_stale_form_field_mapping_is_ignored(get_schema):
    ingress = TestEntities.get(
        "INGRESS", {"hash": "ingress_stale_field", "name": "Stale Field"}
    )
    form = TestEntities.get(
        "FORM", {"hash": "stale_field_form", "name": "Stale Field Form"}
    )
    form.schema = get_schema("basic_inputs")
    ingress.form = form
    ingress.properties.choose_type.entity_type = "page"
    ingress.properties.process_csv.columns = {
        "col-name": {"label": "Name", "icon": "text", "type": "string"},
        "col-stale": {"label": "Old Notes", "icon": "text", "type": "string"},
    }
    ingress.properties.assign_columns.update(
        {
            "col-name": "name",
            "col-stale": "textarea-old-notes",
        }
    )

    assign = ingress.properties.assign_columns

    assert assign.field("textarea-old-notes") is None
    assert assign.column_map == {
        "col-name": {
            **assign.fields["name"],
            "index": 0,
        },
    }
    assert assign.field_map == {"name": ["col-name"]}


# @features ingress link
# @dimensions assign-columns fuzzy-match internal table-fields
@pytest.mark.unit
def test_import_wizard_internal_link_fields_offer_fuzzy_import(get_schema):
    ingress = TestEntities.get(
        "INGRESS",
        {"hash": "ingress_internal_link_fuzzy", "name": "Internal Link Fuzzy"},
    )
    form = TestEntities.get(
        "FORM", {"hash": "internal_link_fuzzy_form", "name": "Links Form"}
    )
    form.schema = get_schema("submission_integration_links")
    ingress.form = form
    ingress.properties.choose_type.entity_type = "page"
    ingress.properties.process_csv.columns = {
        "col-top": {"label": "Top Link", "icon": "link", "type": "string"},
        "col-row": {"label": "Row Link", "icon": "link", "type": "string"},
    }
    ingress.properties.assign_columns.update(
        {
            "col-top": "top_link",
            "col-row": "row_rel",
        }
    )

    assign = ingress.properties.assign_columns
    verify = ingress.properties.verify_import
    verify.update(
        {
            "fuzzy-top_link": "on",
            "fuzzy-row_rel": "on",
        }
    )

    assert assign.fields["top_link"]["fuzzy_import"] is True
    assert assign.fields["row_rel"]["fuzzy_import"] is True
    assert verify.fuzzy_match("top_link") is True
    assert verify.fuzzy_match("row_rel") is True


# @features ingress
# @dimensions verify-import page-lookup fuzzy-match
@pytest.mark.unit
def test_task_import_story_chooses_page_lookup_fields_before_rows_are_imported(
    get_schema, monkeypatch
):
    ingress = TestEntities.get(
        "INGRESS", {"hash": "ingress_verify_import", "name": "Verify Import"}
    )
    task_form = TestEntities.get(
        "FORM", {"hash": "verify_task_form", "name": "Task Form"}
    )
    page_form = TestEntities.get(
        "FORM", {"hash": "verify_page_form", "name": "Page Form"}
    )
    task_form.schema = get_schema("basic_inputs")
    page_form.schema = get_schema("basic_inputs")
    ingress.form = task_form
    ingress.properties.choose_type.entity_type = "task"
    ingress.properties.process_csv.columns = {
        "col-name": {"label": "Name", "icon": "text", "type": "string"},
        "col-note": {"label": "Note", "icon": "text", "type": "string"},
        "col-count": {"label": "Count", "icon": "number", "type": "number"},
    }
    ingress.properties.assign_columns.update({"col-name": "name"})
    loaded_forms = []

    monkeypatch.setattr(
        file_ingress.Entities,
        "FORM",
        lambda form_id: loaded_forms.append(form_id) or page_form,
    )

    verify = ingress.properties.verify_import
    verify.process()

    assert verify.index_from == "name"
    assert verify.index_to == "name"
    assert verify.index_field_choice == "name"
    assert verify.fuzzy_page is True
    assert verify.index_from_field == {
        "id": "name",
        "label": "Name",
        "icon": "text",
        "kind": "file",
    }
    assert verify.index_to_field == {
        "id": "name",
        "label": "Name",
        "icon": "text",
        "kind": "page",
    }
    assert verify.file_options == [
        {
            "id": "name",
            "label": "Name",
            "icon": "text",
            "kind": "file",
        },
        {
            "id": "col-note",
            "label": "Note",
            "icon": "csv",
            "kind": "file",
        },
    ]

    verify.update(
        {
            "index-field-choice": "page-form",
            "page-form-id": page_form.key,
            "index-to": "input-textab12",
            "fuzzy-input-textab12": "on",
        }
    )

    assert verify.page_form is page_form
    assert loaded_forms == [page_form.key]
    assert {
        "id": "input-textab12",
        "label": "Text Field",
        "icon": "text",
        "kind": "form",
    } in verify.page_options
    assert verify.fuzzy_match("input-textab12") is True


# @features ingress
# @dimensions import-pages row-results validation-errors asset-storage
@pytest.mark.unit
def test_importer_story_processes_page_rows_into_entities_and_results(monkeypatch):
    field = SimpleNamespace(
        label="Title",
        warnings=["trimmed"],
        errors=[ValidationError("Invalid title")],
    )
    verify = SimpleNamespace(
        field_map={"title": ["col-title"]},
        column_map={"col-name": {"id": "name"}},
        fuzzy_match=lambda field_id: False,
    )
    entity = SimpleNamespace(
        form=SimpleNamespace(fields={"title": field}),
        properties=SimpleNamespace(
            process_csv=SimpleNamespace(
                columns={
                    "col-title": {"label": "Title"},
                    "col-name": {"label": "Name"},
                }
            ),
            rows=SimpleNamespace(
                asset=[
                    {"col-title": "Good", "col-name": "Ada"},
                    {"col-title": "Bad", "col-name": "Grace"},
                ]
            ),
            assign_columns=SimpleNamespace(
                field_map={"title": ["col-title"]},
                column_map={"col-name": {"id": "name"}},
            ),
            verify_import=verify,
            choose_type=SimpleNamespace(entity_type="page"),
            choose_form=SimpleNamespace(separator=","),
            results=SimpleNamespace(slots=[]),
        ),
    )
    entity.get_process = lambda process_id: {}

    def create_page(self, to_validate):
        if to_validate["title"] == "Bad":
            raise ValidationError("Bad title")
        return SimpleNamespace(
            details={"id": "page-1", "name": to_validate["name"]}
        )

    monkeypatch.setattr(
        ingress_service.IngressMutationPlanner,
        "_create_page",
        create_page,
    )

    imported = [
        ingress_service.IngressMutationPlanner(entity, row_index=index).plan(row).result
        for index, row in enumerate(entity.properties.rows.asset)
    ]

    assert json.loads(imported[0]["row"]) == {
        "Name": "Ada",
        "Title": "Good",
    }
    assert imported[0]["entity"] == {"id": "page-1", "name": "Ada"}
    assert imported[0]["warnings"] == ["trimmed"]
    assert imported[0]["errors"] == ["Invalid title"]
    assert imported[1]["warnings"] == ["Bad title"]
    assert "entity" not in imported[1]


# @features ingress
# @dimensions import-pages list-normalization entity-name
@pytest.mark.unit
def test_importer_story_space_joins_entity_name_fallback(get_schema, monkeypatch):
    form = TestEntities.get("FORM", {"hash": "name_fallback_form", "name": "Form"})
    uncategorized = TestEntities.get(
        "CATEGORY",
        {"hash": "name_fallback_category", "name": "Uncategorized Pages"},
    )
    form.schema = get_schema("text_input_only")
    created_pages = []

    monkeypatch.setattr(
        Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: uncategorized,
    )

    def create_page(data):
        page = TestEntities.get(
            "PAGE", {"hash": "name_fallback_page", "name": "Original"}
        )
        page.update(data)
        created_pages.append(page)
        return page

    monkeypatch.setattr(
        file_ingress.Entities,
        "PAGE",
        SimpleNamespace(create=create_page),
    )

    entity = SimpleNamespace(form=form, parent=None)
    entity.get_process = lambda process_id: {}

    page = ingress_service.IngressMutationPlanner(entity)._create_page(
        {
            "name": ["Harold", "", None, "Heath"],
            "description": ["General", "Contractor"],
        }
    )

    assert page is created_pages[0]
    assert page.name == "Harold Heath"
    assert page.db["name"] == "Harold Heath"
    assert page.description == "General Contractor"
    assert page.db["description"] == "General Contractor"


# @features ingress
# @dimensions task-import page-match completion-history due-date task-name multiple-columns
@pytest.mark.unit
def test_importer_story_creates_tasks_for_matched_pages_and_records_history(
    monkeypatch,
):
    parsed_dates = {
        "2026-01-06": datetime(2026, 1, 6, tzinfo=timezone.utc),
        "2026-01-10": datetime(2026, 1, 10, tzinfo=timezone.utc),
    }
    page = SimpleNamespace(key="page-key", name="Target Page")
    project = SimpleNamespace(key="project-key")
    model = SimpleNamespace(key="model-key")
    form = SimpleNamespace(key="form-key")
    created_tasks = []
    page_queries = []

    class FakeHistory:
        def __init__(self, completed_on=None, name=None, description=None):
            self.completed_on = completed_on
            self.name = name
            self.description = description
            self.imported = []

        def import_submission(self, to_validate, process):
            self.imported.append((to_validate, process))

    class FakeTask:
        def __init__(self):
            self.page = page
            self.name = "Imported Task"
            self.description = "Imported description"
            self.due_date = None
            self.completed = False
            self.completed_on = None
            self.completed_by = None
            self.assigned_to = None
            self.model = model
            self.active = True
            self.histories = []
            self.imported = []
            self.related = []

        @property
        def new_history_created(self):
            return self.histories

        def create_history_entry(self, **overrides):
            history = FakeHistory(
                completed_on=overrides.get("completed_on"),
                name=overrides.get("name", self.name),
                description=overrides.get("description", self.description),
            )
            self.histories.append(history)
            return history

        def uncomplete(self):
            history = self.create_history_entry(completed_on=self.completed_on)
            history.imported = list(self.imported)
            self.completed = False
            self.completed_on = None
            self.completed_by = None
            self.assigned_to = None
            self.due_date = None
            self.imported = []

        def import_submission(self, to_validate, process):
            self.imported.append((to_validate, process))
            self.name = to_validate.get("name", self.name)
            self.description = to_validate.get("description", self.description)

    task = FakeTask()
    entity = SimpleNamespace(
        form=form,
        project=project,
        model=model,
        results=[],
        properties=SimpleNamespace(
            process_csv=SimpleNamespace(columns={}),
            rows=SimpleNamespace(asset=[]),
            assign_columns=SimpleNamespace(
                field_map={
                    "task_name": ["task-name-prefix", "task-name"],
                    "completed_on": ["completed"],
                    "due_date": ["due"],
                }
            ),
            verify_import=SimpleNamespace(
                index_from="page-name",
                index_to_field={"label": "Name"},
                fuzzy_page=False,
                fuzzy_match=lambda field_id: False,
            ),
            choose_type=SimpleNamespace(entity_type="task"),
            choose_form=SimpleNamespace(separator=","),
            choose_parent=SimpleNamespace(task_name="Imported Task"),
            completed=SimpleNamespace(complete=None),
            results=SimpleNamespace(save=lambda: None),
        ),
    )
    entity.get_process = lambda process_id: {}

    monkeypatch.setattr(
        file_ingress.dates,
        "parse_imported_date_as_utc",
        lambda value: parsed_dates[value],
    )
    monkeypatch.setattr(file_ingress.Entities, "PAGE", lambda page_id: page)
    monkeypatch.setattr(
        file_ingress.Entities,
        "TASK",
        SimpleNamespace(
            create=lambda data: created_tasks.append(data) or task
        ),
    )

    def get_task_page(self, map_to_value, field_label, result):
        page_queries.append((map_to_value, field_label, result))
        return page.key

    monkeypatch.setattr(
        ingress_service.IngressMutationPlanner,
        "_get_task_page",
        get_task_page,
    )

    importing = ingress_service.IngressMutationPlanner(entity)
    result = {}
    returned_task = importing._create_task(
        {
            "page-name": "Target Page",
            "task-name-prefix": "Annual",
            "task-name": "Inspection",
            "completed": "2026-01-06",
            "due": "2026-01-10",
        },
        {
            "name": "Imported completion",
            "description": "Imported description",
        },
        result,
    )

    assert returned_task is task
    assert page_queries == [("Target Page", "Name", result)]
    assert created_tasks == [
        {
            "page": page,
            "form": form,
            "name": "Annual Inspection",
            "description": "Imported description",
            "model": model,
            "project": project,
        }
    ]
    assert task.name == "Annual Inspection"
    assert task.due_date == parsed_dates["2026-01-10"]
    assert task.active is True
    assert task.related == []
    assert task.completed is False
    assert task.completed_on is None
    assert len(task.histories) == 1
    assert task.histories[0].completed_on == parsed_dates["2026-01-06"]
    assert task.histories[0].name == "Imported completion"
    assert task.histories[0].description == "Imported description"
    assert task.histories[0].imported == [
        (
            {
                "name": "Imported completion",
                "description": "Imported description",
            },
            importing,
        )
    ]
    assert task.imported == []
    assert result == {}


# @features ingress
# @dimensions task-import row-task existing-model-task completion-history live-completion multiple-columns
@pytest.mark.unit
def test_task_import_creates_distinct_tasks_per_row_with_same_row_completion_history(
    monkeypatch,
):
    parsed_dates = {
        "2026-01-06": datetime(2026, 1, 6, tzinfo=timezone.utc),
        "2026-01-10": datetime(2026, 1, 10, tzinfo=timezone.utc),
    }
    model = SimpleNamespace(key="model-key")
    project = SimpleNamespace(key="project-key")
    form = SimpleNamespace(key="form-key")
    created_tasks = []

    class FakeHistory:
        def __init__(self, completed_on=None, name=None, description=None, form=None):
            self.completed_on = completed_on
            self.name = name
            self.description = description
            self.form = form
            self.imported = []

        def import_submission(self, to_validate, process):
            self.imported.append((to_validate, process))

    class FakeTask:
        def __init__(self, data, *, key=None):
            self.key = key
            self.page = data["page"]
            self.name = data["name"]
            self.description = data["description"]
            self.model = data["model"]
            self.project = data["project"]
            self.form = data["form"]
            self.completed = False
            self.completed_on = None
            self.completed_by = None
            self.assigned_to = None
            self.due_date = None
            self.histories = []
            self.imported = []
            self.related = []

        @property
        def new_history_created(self):
            return self.histories

        def create_history_entry(self, **overrides):
            history = FakeHistory(
                completed_on=overrides.get("completed_on"),
                name=overrides.get("name", self.name),
                description=overrides.get("description", self.description),
                form=overrides.get("form"),
            )
            self.histories.append(history)
            return history

        def uncomplete(self):
            history = self.create_history_entry(completed_on=self.completed_on)
            history.imported = list(self.imported)
            self.completed = False
            self.completed_on = None
            self.completed_by = None
            self.assigned_to = None
            self.due_date = None
            self.imported = []

        def import_submission(self, to_validate, process):
            self.imported.append((to_validate, process))

    page = SimpleNamespace(key="page-key", name="Target Page")
    task_data = {
        "page": page,
        "form": form,
        "name": "Imported Task",
        "description": "Imported description",
        "model": model,
        "project": project,
    }
    existing_task = FakeTask(task_data, key="existing-task-key")
    page._tasks = [existing_task]
    page._completed = []

    entity = SimpleNamespace(
        form=form,
        project=project,
        model=model,
        results=[],
        properties=SimpleNamespace(
            process_csv=SimpleNamespace(columns={}),
            rows=SimpleNamespace(asset=[]),
            assign_columns=SimpleNamespace(
                field_map={"completed_on": ["completed-a", "completed-b"]}
            ),
            verify_import=SimpleNamespace(
                index_from="page-name",
                index_to_field={"label": "Name"},
                fuzzy_page=False,
                fuzzy_match=lambda field_id: False,
            ),
            choose_type=SimpleNamespace(entity_type="task"),
            choose_form=SimpleNamespace(separator=","),
            choose_parent=SimpleNamespace(task_name="Imported Task"),
            completed=SimpleNamespace(complete=None),
            results=SimpleNamespace(save=lambda: None),
        ),
    )
    entity.get_process = lambda process_id: {}

    monkeypatch.setattr(
        file_ingress.dates,
        "parse_imported_date_as_utc",
        lambda value: parsed_dates[value],
    )
    monkeypatch.setattr(file_ingress.Entities, "PAGE", lambda page_id: page)

    def create_task(data):
        created_tasks.append(FakeTask(data))
        return created_tasks[-1]

    monkeypatch.setattr(
        file_ingress.Entities,
        "TASK",
        SimpleNamespace(create=create_task),
    )
    page_queries = []
    monkeypatch.setattr(
        ingress_service.IngressMutationPlanner,
        "_get_task_page",
        lambda self, map_to_value, field_label, result: (
            page_queries.append((map_to_value, field_label)) or page.key
        ),
    )

    importing = ingress_service.IngressMutationPlanner(entity)
    result = {}
    rows = [
        {
            "page-name": "Target Page",
            "completed-a": "2026-01-06",
            "completed-b": "2026-01-10",
        }
        for _ in range(2)
    ]
    returned_tasks = [
        importing._create_task(
            row,
            {
                "name": "Imported completion",
                "description": "Imported description",
            },
            result,
        )
        for row in rows
    ]

    assert returned_tasks == created_tasks
    assert returned_tasks[0] is not returned_tasks[1]
    assert page_queries == [("Target Page", "Name"), ("Target Page", "Name")]
    assert existing_task.completed is False
    assert existing_task.histories == []
    assert existing_task.imported == []
    for task in returned_tasks:
        assert task.completed is True
        assert task.completed_on == parsed_dates["2026-01-10"]
        assert task.due_date is None
        assert task.related == []
        assert len(task.histories) == 1
        assert task.histories[0].completed_on == parsed_dates["2026-01-06"]
        assert task.histories[0].imported == [
            (
                {
                    "name": "Imported completion",
                    "description": "Imported description",
                },
                importing,
            )
        ]
        assert task.imported == [
            (
                {
                    "name": "Imported completion",
                    "description": "Imported description",
                },
                importing,
            )
        ]
    assert importing.created_entities == returned_tasks
    assert result == {}


# @features ingress
# @dimensions task-import completion-history name description
@pytest.mark.unit
def test_importer_records_older_completion_snapshot_text():
    form = SimpleNamespace(key="history-form")
    imported = []
    captured = []
    history = SimpleNamespace(
        import_submission=lambda values, process: imported.append((values, process))
    )
    task = SimpleNamespace(
        form=form,
        create_history_entry=lambda **overrides: captured.append(overrides) or history,
    )
    entity = SimpleNamespace(form=form, get_process=lambda _process_id: {})
    importing = ingress_service.IngressMutationPlanner(entity)
    completed_on = datetime(2025, 4, 3, tzinfo=timezone.utc)
    values = {
        "name": "Historical inspection",
        "description": "Imported historical details",
    }

    assert importing._record_completed_history(task, completed_on, values) is history
    assert captured == [
        {
            "completed_on": completed_on,
            "files": [],
            "submission": None,
            "name": "Historical inspection",
            "description": "Imported historical details",
            "form": form,
        }
    ]
    assert imported == [(values, importing)]


# @features ingress
# @dimensions task-import page-match fuzzy-match
@pytest.mark.unit
def test_importer_task_page_lookup_uses_shared_find_page(monkeypatch):
    calls = []
    entity = SimpleNamespace(
        properties=SimpleNamespace(
            process_csv=SimpleNamespace(columns={}),
            rows=SimpleNamespace(asset=[]),
            assign_columns=SimpleNamespace(field_map={}),
            verify_import=SimpleNamespace(
                fuzzy_page=True,
                fuzzy_match=lambda field_id: False,
            ),
            choose_type=SimpleNamespace(entity_type="task"),
            choose_form=SimpleNamespace(separator=","),
            completed=SimpleNamespace(complete=None),
            results=SimpleNamespace(save=lambda: None),
        ),
        results=[],
    )
    entity.get_process = lambda process_id: {}

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        calls.append((value, match_field_label, fuzzy, error_label))
        return {
            "id": "page-key",
            "warnings": ["Weak match for Name: 'Target Page'"],
            "errors": [],
        }

    monkeypatch.setattr(file_ingress.files, "find_page", find_page)

    importing = ingress_service.IngressMutationPlanner(entity)
    result = {}

    assert importing._get_task_page("Targt Page", "Name", result) == "page-key"
    assert calls == [("Targt Page", "Name", True, None)]
    assert result == {"warnings": ["Weak match for Name: 'Target Page'"]}


# @features ingress
# @dimensions completed row-results
@pytest.mark.unit
def test_completed_ingress_shows_results():
    ingress = TestEntities.get(
        "INGRESS", {"hash": "ingress_completed", "name": "Completed Import"}
    )
    saved_assets = []
    rows = [{"col": "value"}]
    results = [{"row": "{\"Column\": \"value\"}"}]
    ingress.properties.rows._asset = rows

    def save_asset(content, name, asset_type, visibility="private"):
        saved_assets.append((content, name, asset_type, visibility))
        return SimpleNamespace(get=lambda: content)

    ingress.save_asset = save_asset
    ingress.properties.results.value = results
    ingress.get_process("execution")["cursor"] = len(results)

    ingress.properties.completed.process()

    assert ingress.properties.completed.complete is True
    assert ingress.properties.completed.results is results
    assert saved_assets == [(results, "results", "json", "private")]


# @features ingress
# @dimensions row-results asset-storage regression
@pytest.mark.unit
def test_results_asset_loads_stored_json_without_recursing():
    ingress = make_raw_ingress("Stored Results", "page")
    stored_results = [{"row": "{\"Name\": \"Ada\"}", "entity": {"name": "Ada"}}]
    calls = []

    def get_asset(name):
        calls.append(name)
        return SimpleNamespace(get=lambda: stored_results)

    ingress.get_asset = get_asset
    ingress.get_process("execution")["cursor"] = len(stored_results)

    assert ingress.results is stored_results
    assert ingress.properties.results.value is stored_results
    assert calls == ["results"]


# @features ingress
# @dimensions row-results delete
@pytest.mark.unit
def test_ingress_results_remove_deleted_imported_entities():
    ingress = make_raw_ingress("Remove Results", "page")
    saved_assets = []
    results = [
        {"entity": {"id": "page-1", "name": "Ada"}},
        {"entity": {"id": "task-1", "name": "Follow Up"}},
        {"row": "{\"Name\": \"Bad\"}", "errors": ["Bad row"]},
    ]
    ingress.properties.results._asset = results
    ingress.get_process("execution")["cursor"] = len(results)

    def save_asset(content, name, asset_type, visibility="private"):
        saved_assets.append((list(content), name, asset_type, visibility))
        return SimpleNamespace(get=lambda: content)

    ingress.save_asset = save_asset

    assert ingress.remove_results_for_entities("page-1") == 1
    assert results == [
        {"entity": {"id": "task-1", "name": "Follow Up"}},
        {"row": "{\"Name\": \"Bad\"}", "errors": ["Bad row"]},
    ]
    assert saved_assets == [(list(results), "results", "json", "private")]


# @features ingress
# @dimensions row-results delete reload
@pytest.mark.unit
def test_ingress_results_prune_missing_entities(monkeypatch):
    ingress = make_raw_ingress("Prune Results", "page")
    page = TestEntities.get("PAGE", {"hash": "page-1", "name": "Ada"})
    saved_assets = []
    results = [
        {"entity": {"id": "page-1", "name": "Ada"}},
        {"entity": {"id": "task-1", "name": "Follow Up"}},
        {"row": "{\"Name\": \"Bad\"}", "errors": ["Bad row"]},
    ]
    ingress.properties.results._asset = results
    ingress.get_process("execution")["cursor"] = len(results)
    ingress.save_asset = (
        lambda content, name, asset_type, visibility="private": saved_assets.append(
            (list(content), name, asset_type, visibility)
        )
        or SimpleNamespace(get=lambda: content)
    )

    monkeypatch.setattr(
        ingress_module.Entities,
        "fetch",
        lambda *ids, request: [page],
    )

    assert ingress.prune_missing_results() == 1
    assert results == [
        {"entity": {"id": "page-1", "name": "Ada"}},
        {"row": "{\"Name\": \"Bad\"}", "errors": ["Bad row"]},
    ]
    assert saved_assets == [(list(results), "results", "json", "private")]


# @features ingress
# @dimensions row-results delete bulk-delete
@pytest.mark.unit
def test_ingress_delete_imported_entities_deletes_pages_and_tasks(monkeypatch):
    ingress = make_raw_ingress("Bulk Delete Results", "page")
    page = TestEntities.get("PAGE", {"hash": "page-1", "name": "Ada"})
    task = TestEntities.get("TASK", {"hash": "task-1", "name": "Follow Up"})
    deleted = []
    results = [
        {"entity": {"id": "page-1", "name": "Ada"}},
        {"entity": {"id": "task-1", "name": "Follow Up"}},
        {"entity": {"id": "form-1", "name": "Unrelated Form", "kind": "form"}},
        {"row": "{\"Name\": \"Bad\"}", "errors": ["Bad row"]},
    ]
    ingress.properties.results._asset = results
    ingress.get_process("execution")["cursor"] = len(results)
    ingress.save_asset = lambda content, name, asset_type, visibility="private": (
        SimpleNamespace(get=lambda: content)
    )

    monkeypatch.setattr(
        ingress_module.Entities,
        "fetch",
        lambda *ids, request: [page, task],
    )
    monkeypatch.setattr(
        ingress_module.Entities,
        "delete",
        lambda *entities: deleted.extend(entities),
    )

    assert ingress.delete_imported_entities() == 2
    assert deleted == [page, task]
    assert results == [
        {"entity": {"id": "form-1", "name": "Unrelated Form", "kind": "form"}},
        {"row": "{\"Name\": \"Bad\"}", "errors": ["Bad row"]},
    ]
