"""Presentation properties for the core-owned CSV ingress service."""

from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

if TYPE_CHECKING:
    from ..tools.files.validate import CSVMetadata
    from ..entities.ingress import Ingress
    from ..entities.entity import Entity
    from ..entities.form import Form
    from ..tools.ingress import FieldsById, ImportField, CsvColumns, CsvRow

from ..definitions import IngressRunStatus, IngressStage
from ..entities import Entities as Entities
from ..exceptions import ValidationError
from ..tools import dates as dates
from ..tools.ingress import IngressMapping, IngressParser, IngressService
from .base_process import ProcessProperty
from .base_property import Property


# @testable true
# @tests tests_unit/test_006d_ingress_service.py::test_property_stage_facade_uses_durable_workflow
# @tests tests_unit/test_006b_ingress_entity.py::test_stage_returns_property
# @tests tests_unit/test_006b_ingress_entity.py::test_stage_set_enum
# @tests tests_unit/test_006b_ingress_entity.py::test_stage_set_string
# @tests tests_unit/test_006b_ingress_entity.py::test_stage_set_invalid_raises
# @tests tests_unit/test_006b_ingress_entity.py::test_stage_default
# @tests tests_unit/test_006b_ingress_entity.py::test_back_moves_to_prior_stage
# @tests tests_unit/test_006b_ingress_entity.py::test_back_at_first_stage_noop
# @tests tests_unit/test_006b_ingress_entity.py::test_next_advances_after_finalize
# @tests tests_unit/test_006b_ingress_entity.py::test_stage_status
# @tests tests_unit/test_006b_ingress_entity.py::test_import_wizard_story_reports_stage_errors_without_advancing
# @matrix ingress : back default enum finalize first-stage navigation presentation property stage status string validation
class Stage(Property["Stage", "Ingress", "str | IngressStage"]):
    """Thin presentation facade over ``IngressService`` workflow state."""

    _id = "stage"

    @property
    # @testable infrastructure
    def service(self) -> IngressService:
        return IngressService(self.entity)

    @property
    # @testable infrastructure
    def value(self) -> Stage:
        return self

    @value.setter
    # @testable infrastructure
    def value(self, value: str | IngressStage) -> None:
        stage = self.service._coerce_stage(value)
        self.service.workflow["current"] = stage.name

    @property
    # @testable infrastructure
    def current(self) -> ProcessProperty[Ingress]:
        return self.status(self.service.stage)

    # @testable infrastructure
    def status(
        self, stage: str | IngressStage | None = None
    ) -> ProcessProperty[Ingress]:
        return self.service.stage_status(stage or self.service.stage)

    # @testable infrastructure
    def finalize(self, form_data: Mapping[str, object] | None = None) -> bool:
        return self.service.finalize(form_data)

    # @testable infrastructure
    def comes_before(self, stage: IngressStage) -> bool:
        return self.service.stage.value < stage.value

    # @testable infrastructure
    def matches(self, stage: IngressStage) -> bool:
        return self.service.stage == stage

    @property
    # @testable infrastructure
    def name(self) -> str:
        return self.service.stage.name

    @property
    # @testable infrastructure
    def is_complete(self) -> bool:
        return self.service.stage == IngressStage.COMPLETED

    # @testable infrastructure
    def can_navigate(self, stage: str | IngressStage) -> bool:
        return self.service.can_navigate(stage)

    # @testable infrastructure
    def back(self) -> None:
        stage = self.service.stage
        if stage.value <= IngressStage.PROCESS_CSV.value:
            return None
        target = IngressStage(stage.value - 1)
        if self.service.can_navigate(target):
            self.service.navigate(target, save=False)
        return None

    # @testable infrastructure
    def next(self, form_data: Mapping[str, object] | None = None) -> None:
        self.service.advance(form_data)
        return None


# @testable infrastructure
class ProcessCSV(ProcessProperty["Ingress"]):
    """Parsed CSV metadata projected for the first wizard stage."""

    if TYPE_CHECKING:
        columns: CsvColumns | None
        row_count: int | None
        column_count: int | None
        delimiter: str | None

    process_id = "workflow"
    section_id = "process_csv"
    label = "Verify Columns"
    attributes = ("delimiter", "column_count", "row_count", "columns")

    # @testable infrastructure
    def process(self) -> CSVMetadata:
        metadata, rows = IngressParser.parse_entity(self.entity)
        self.entity.properties.rows.value = rows
        self.section = dict(metadata)
        return metadata


# @testable infrastructure
class ChooseType(ProcessProperty["Ingress"]):
    """Page/task choice stored in the canonical workflow document."""

    if TYPE_CHECKING:
        entity_type: str | None

    process_id = "workflow"
    section_id = "choose_type"
    label = "Select Entity Type"
    attributes = ("entity_type",)

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_choose_type_update_via_current_stage_property
    # @tests tests_unit/test_006b_ingress_entity.py::test_import_wizard_story_restarts_downstream_choices_when_entity_type_changes
    # @matrix ingress : choose-type clear-downstream update
    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.CHOOSE_TYPE,
            form_data,
            save=False,
        )


# @testable infrastructure
class ChooseParent(ProcessProperty["Ingress"]):
    """Parent selection facade; creation is owned by ``IngressService``."""

    if TYPE_CHECKING:
        parent_choice: str | None
        parent_id: str | None
        parent_name: str | None
        create_model: bool | None
        model_name: str | None

    process_id = "workflow"
    section_id = "choose_parent"
    attributes = (
        "parent_choice",
        "parent_id",
        "parent_name",
        "create_model",
        "model_name",
    )

    @property
    # @testable infrastructure
    def label(self) -> str:
        entity_type = self.entity.properties.choose_type.entity_type
        if entity_type == "task":
            return "Select Project"
        if entity_type == "page":
            return "Select Category"
        return "Select Parent"

    # @testable infrastructure
    def process(self) -> list[Entity]:
        return IngressService(self.entity)._apply_parent_choice()

    # @testable infrastructure
    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.CHOOSE_PARENT,
            form_data,
            save=False,
        )

    @property
    # @testable infrastructure
    def task_name(self) -> str | None:
        return self.entity.parent.name if self.entity.parent else self.entity.name


# @testable infrastructure
class ChooseForm(ProcessProperty["Ingress"]):
    """Form choice facade; form creation is owned by ``IngressService``."""

    if TYPE_CHECKING:
        form_choice: str | None
        form_id: str | None
        form_name: str | None
        set_default_form: bool | None
        separator: str | None

    process_id = "workflow"
    section_id = "choose_form"
    label = "Select Form"
    attributes = (
        "form_choice",
        "form_id",
        "form_name",
        "set_default_form",
        "separator",
    )

    @property
    # @testable infrastructure
    def columns(self) -> CsvColumns | None:
        return self.entity.properties.process_csv.columns

    @property
    # @testable infrastructure
    def rows(self) -> list[CsvRow] | None:
        return self.entity.properties.rows.asset

    @property
    # @testable infrastructure
    def entity_type(self) -> str | None:
        return self.entity.properties.choose_type.entity_type

    # @testable infrastructure
    def process(self) -> list[Entity]:
        return IngressService(self.entity)._apply_form_choice()

    # @testable infrastructure
    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.CHOOSE_FORM,
            form_data,
            save=False,
        )


# @testable infrastructure
class AssignColumns(ProcessProperty["Ingress"]):
    """Presentation facade over the canonical ``IngressMapping`` projection."""

    process_id = "workflow"
    section_id = "assign_columns"
    label = "Assign Columns"
    attributes = tuple()

    @property
    # @testable infrastructure
    def mapping(self) -> IngressMapping:
        return IngressMapping(self.entity)

    @property
    # @testable infrastructure
    def columns(self) -> CsvColumns:
        return self.mapping.columns

    @property
    # @testable infrastructure
    def entity_type(self) -> str | None:
        return self.mapping.entity_type

    @property
    # @testable infrastructure
    def form(self) -> Form | None:
        return self.mapping.form

    @property
    # @testable infrastructure
    def fields(self) -> FieldsById:
        return self.mapping.fields

    # @testable infrastructure
    def field(self, field_id: str) -> ImportField | None:
        return self.mapping.field(field_id)

    # @testable infrastructure
    def ignore(self, column_id: str) -> object:
        return self.mapping.ignore(column_id)

    # @testable infrastructure
    def guess_field(self, column_id: str) -> ImportField | None:
        return self.mapping.guess_field(column_id)

    @property
    # @testable infrastructure
    def column_map(self) -> FieldsById:
        return self.mapping.column_map

    @property
    # @testable infrastructure
    def field_map(self) -> dict[str, list[str]]:
        return self.mapping.field_map

    # @testable infrastructure
    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.ASSIGN_COLUMNS,
            form_data,
            save=False,
        )


# @testable infrastructure
class VerifyImport(ProcessProperty["Ingress"]):
    """Final verification facade over the canonical mapping projection."""

    if TYPE_CHECKING:
        index_from: str | None
        index_to: str | None
        index_field_choice: str | None
        page_form_id: str | None
        fuzzy_page: bool | None

    process_id = "workflow"
    section_id = "verify_import"
    label = "Finalize Settings"
    attributes = (
        "index_from",
        "index_to",
        "index_field_choice",
        "page_form_id",
        "fuzzy_page",
    )

    @property
    # @testable infrastructure
    def mapping(self) -> IngressMapping:
        return IngressMapping(self.entity)

    @property
    # @testable infrastructure
    def fields(self) -> FieldsById:
        return self.mapping.fields

    @property
    # @testable infrastructure
    def column_map(self) -> FieldsById:
        return self.mapping.column_map

    @property
    # @testable infrastructure
    def field_map(self) -> dict[str, list[str]]:
        return self.mapping.field_map

    @property
    # @testable infrastructure
    def columns(self) -> CsvColumns:
        return self.mapping.columns

    # @testable infrastructure
    def process(self) -> None:
        try:
            IngressService(self.entity)._validate_import_settings()
        except ValidationError as error:
            self.error = str(error)

    # @testable infrastructure
    def fuzzy_match(self, field_id: str) -> bool:
        return self.mapping.fuzzy_match(field_id)

    @property
    # @testable infrastructure
    def file_options(self) -> list[ImportField]:
        return self.mapping.file_options

    @property
    # @testable infrastructure
    def page_form(self) -> Form | None:
        return self.mapping.page_form

    @property
    # @testable infrastructure
    def page_options(self) -> list[ImportField]:
        return self.mapping.page_options

    @property
    # @testable infrastructure
    def index_from_field(self) -> ImportField | None:
        return self.mapping.index_from_field

    @property
    # @testable infrastructure
    def index_to_field(self) -> ImportField | None:
        return self.mapping.index_to_field

    # @testable infrastructure
    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.VERIFY_IMPORT,
            form_data,
            save=False,
        )


# @testable infrastructure
class Importing(ProcessProperty["Ingress"]):
    """Execution presentation facade."""

    process_id = "workflow"
    section_id = "importing"
    label = "Import Data"
    attributes = tuple()

    @property
    # @testable infrastructure
    def stopped(self) -> bool:
        status = self.entity.get_process("execution").get("status")
        return status in {
            IngressRunStatus.STOPPED.value,
            IngressRunStatus.FAILED.value,
        }

    @stopped.setter
    # @testable infrastructure
    def stopped(self, value: bool) -> None:
        execution = self.entity.get_process("execution")
        if value:
            execution["status"] = IngressRunStatus.STOPPED.value
        elif execution.get("status") == IngressRunStatus.STOPPED.value:
            execution["status"] = IngressRunStatus.IDLE.value


# @testable infrastructure
class Completed(ProcessProperty["Ingress"]):
    """Terminal results presentation facade."""

    process_id = "workflow"
    section_id = "completed"
    label = "Import Complete"
    attributes = tuple()

    # @testable infrastructure
    def process(self) -> None:
        self.complete = True

    @property
    # @testable infrastructure
    def results(self) -> list[dict[str, Any] | None]:
        return self.entity.results
