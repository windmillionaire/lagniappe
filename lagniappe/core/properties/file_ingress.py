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


class Stage(Property["Stage", "Ingress", "str | IngressStage"]):
    """Thin presentation facade over ``IngressService`` workflow state."""

    _id = "stage"

    @property
    def service(self) -> IngressService:
        return IngressService(self.entity)

    @property
    def value(self) -> Stage:
        return self

    @value.setter
    def value(self, value: str | IngressStage) -> None:
        stage = self.service._coerce_stage(value)
        self.service.workflow["current"] = stage.name

    @property
    def current(self) -> ProcessProperty[Ingress]:
        return self.status(self.service.stage)

    def status(
        self, stage: str | IngressStage | None = None
    ) -> ProcessProperty[Ingress]:
        return self.service.stage_status(stage or self.service.stage)

    def finalize(self, form_data: Mapping[str, object] | None = None) -> bool:
        return self.service.finalize(form_data)

    def comes_before(self, stage: IngressStage) -> bool:
        return self.service.stage.value < stage.value

    def matches(self, stage: IngressStage) -> bool:
        return self.service.stage == stage

    @property
    def name(self) -> str:
        return self.service.stage.name

    @property
    def is_complete(self) -> bool:
        return self.service.stage == IngressStage.COMPLETED

    def can_navigate(self, stage: str | IngressStage) -> bool:
        return self.service.can_navigate(stage)

    def back(self) -> None:
        stage = self.service.stage
        if stage.value <= IngressStage.PROCESS_CSV.value:
            return None
        target = IngressStage(stage.value - 1)
        if self.service.can_navigate(target):
            self.service.navigate(target, save=False)
        return None

    def next(self, form_data: Mapping[str, object] | None = None) -> None:
        self.service.advance(form_data)
        return None


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

    def process(self) -> CSVMetadata:
        metadata, rows = IngressParser.parse_entity(self.entity)
        self.entity.properties.rows.value = rows
        self.section = dict(metadata)
        return metadata


class ChooseType(ProcessProperty["Ingress"]):
    """Page/task choice stored in the canonical workflow document."""

    if TYPE_CHECKING:
        entity_type: str | None

    process_id = "workflow"
    section_id = "choose_type"
    label = "Select Entity Type"
    attributes = ("entity_type",)

    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.CHOOSE_TYPE,
            form_data,
            save=False,
        )


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
    def label(self) -> str:
        entity_type = self.entity.properties.choose_type.entity_type
        if entity_type == "task":
            return "Select Project"
        if entity_type == "page":
            return "Select Category"
        return "Select Parent"

    def process(self) -> list[Entity]:
        return IngressService(self.entity)._apply_parent_choice()

    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.CHOOSE_PARENT,
            form_data,
            save=False,
        )

    @property
    def task_name(self) -> str | None:
        return self.entity.parent.name if self.entity.parent else self.entity.name


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
    def columns(self) -> CsvColumns | None:
        return self.entity.properties.process_csv.columns

    @property
    def rows(self) -> list[CsvRow] | None:
        return self.entity.properties.rows.asset

    @property
    def entity_type(self) -> str | None:
        return self.entity.properties.choose_type.entity_type

    def process(self) -> list[Entity]:
        return IngressService(self.entity)._apply_form_choice()

    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.CHOOSE_FORM,
            form_data,
            save=False,
        )


class AssignColumns(ProcessProperty["Ingress"]):
    """Presentation facade over the canonical ``IngressMapping`` projection."""

    process_id = "workflow"
    section_id = "assign_columns"
    label = "Assign Columns"
    attributes = tuple()

    @property
    def mapping(self) -> IngressMapping:
        return IngressMapping(self.entity)

    @property
    def columns(self) -> CsvColumns:
        return self.mapping.columns

    @property
    def entity_type(self) -> str | None:
        return self.mapping.entity_type

    @property
    def form(self) -> Form | None:
        return self.mapping.form

    @property
    def fields(self) -> FieldsById:
        return self.mapping.fields

    def field(self, field_id: str) -> ImportField | None:
        return self.mapping.field(field_id)

    def ignore(self, column_id: str) -> object:
        return self.mapping.ignore(column_id)

    def guess_field(self, column_id: str) -> ImportField | None:
        return self.mapping.guess_field(column_id)

    @property
    def column_map(self) -> FieldsById:
        return self.mapping.column_map

    @property
    def field_map(self) -> dict[str, list[str]]:
        return self.mapping.field_map

    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.ASSIGN_COLUMNS,
            form_data,
            save=False,
        )


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
    def mapping(self) -> IngressMapping:
        return IngressMapping(self.entity)

    @property
    def fields(self) -> FieldsById:
        return self.mapping.fields

    @property
    def column_map(self) -> FieldsById:
        return self.mapping.column_map

    @property
    def field_map(self) -> dict[str, list[str]]:
        return self.mapping.field_map

    @property
    def columns(self) -> CsvColumns:
        return self.mapping.columns

    def process(self) -> None:
        try:
            IngressService(self.entity)._validate_import_settings()
        except ValidationError as error:
            self.error = str(error)

    def fuzzy_match(self, field_id: str) -> bool:
        return self.mapping.fuzzy_match(field_id)

    @property
    def file_options(self) -> list[ImportField]:
        return self.mapping.file_options

    @property
    def page_form(self) -> Form | None:
        return self.mapping.page_form

    @property
    def page_options(self) -> list[ImportField]:
        return self.mapping.page_options

    @property
    def index_from_field(self) -> ImportField | None:
        return self.mapping.index_from_field

    @property
    def index_to_field(self) -> ImportField | None:
        return self.mapping.index_to_field

    def update(self, form_data: Mapping[str, object]) -> dict[str, object]:
        return IngressService(self.entity).update_stage(
            IngressStage.VERIFY_IMPORT,
            form_data,
            save=False,
        )


class Importing(ProcessProperty["Ingress"]):
    """Execution presentation facade."""

    process_id = "workflow"
    section_id = "importing"
    label = "Import Data"
    attributes = tuple()

    @property
    def stopped(self) -> bool:
        status = self.entity.get_process("execution").get("status")
        return status in {
            IngressRunStatus.STOPPED.value,
            IngressRunStatus.FAILED.value,
        }

    @stopped.setter
    def stopped(self, value: bool) -> None:
        execution = self.entity.get_process("execution")
        if value:
            execution["status"] = IngressRunStatus.STOPPED.value
        elif execution.get("status") == IngressRunStatus.STOPPED.value:
            execution["status"] = IngressRunStatus.IDLE.value


class Completed(ProcessProperty["Ingress"]):
    """Terminal results presentation facade."""

    process_id = "workflow"
    section_id = "completed"
    label = "Import Complete"
    attributes = tuple()

    def process(self) -> None:
        self.complete = True

    @property
    def results(self) -> list[dict[str, Any] | None]:
        return self.entity.results
