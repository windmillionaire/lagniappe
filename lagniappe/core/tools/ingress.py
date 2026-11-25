"""Durable CSV ingress parsing, mapping, planning, and execution service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

import hashlib
import json
from datetime import datetime, UTC

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    CONFIGURATION_STAGES,
    INGRESS_BATCH_SIZE,
    INGRESS_FORMAT_VERSION,
    Fetch,
    FileConsumer,
    IngressAction,
    IngressBatchResult,
    IngressFormatError,
    IngressMutationPlan,
    MutationOperation,
    IngressProgress,
    IngressRunStatus,
    IngressStage,
    IngressTransitionError,
    enforce_file_consumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core.mutations import (
    consume_mutation_intents,
    execute_post_commit,
    plan_mutation,
    prepare_durable_writes,
)
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.form_inputs import TextInput
from lagniappe.core.properties.form_links import Link
from lagniappe.core.properties.form_select import CategoricalElement
from lagniappe.core.properties.form_special import HTML, Signature, Status
from lagniappe.core.properties.form_table import Table
from lagniappe.core.tools import dates
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.files import find_page as files
from lagniappe.core.tools.files import validate as file_validation
from lagniappe.core.tools.database import ingress as ingress_database


if TYPE_CHECKING:
    from google.cloud.datastore import Key
    from werkzeug.datastructures import FileStorage
    from ..definitions import MutationOutcome
    from ..entities.entity import Entity
    from ..entities.category import Category, CategoryData
    from ..entities.project import Project, ProjectData
    from ..entities.model_task import ModelTask, ModelTaskData
    from ..entities.form import Form
    from ..entities.ingress import Ingress
    from ..properties.base_process import ProcessProperty
    from ..properties.schema import SchemaField
    from .database.assets import DirectUploadFile


type CsvColumns = dict[str, file_validation.CSVColumn]
type CsvRow = dict[str, str]
class ImportField(TypedDict):
    id: str
    label: str | None
    kind: str
    icon: str | None
    type: NotRequired[str | None]
    choices: NotRequired[bool]
    fuzzy_import: NotRequired[bool]
    description: NotRequired[str | None]
    index: NotRequired[int]


type FieldsById = dict[str, ImportField]


def _form_fields(form: Form | None) -> Mapping[str, SchemaField]:
    if form is None:
        raise ValidationError("Choose a form before mapping import fields.")
    return form.fields or {}


def _stored_rows(entity: Ingress) -> list[CsvRow]:
    rows = entity.properties.rows.asset
    if rows is None:
        raise ValidationError("The parsed CSV rows are unavailable. Upload the file again.")
    return rows


class Workflow(TypedDict):
    current: str
    highest_completed: NotRequired[str]
    configuration_revision: NotRequired[int]


class Execution(TypedDict, total=False):
    cursor: int
    status: str
    total_rows: int
    dispatch_sequence: int
    error: str
    lease_token: str
    lease_expires: str


ACTIVE_RUN_STATUSES = {
    IngressRunStatus.QUEUED.value,
    IngressRunStatus.RUNNING.value,
    IngressRunStatus.STOP_REQUESTED.value,
}


def _utc(value=None):
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _form_data(data):
    if data is None:
        return {}
    items = data.items() if hasattr(data, "items") else dict(data).items()
    return {str(key).replace("_", "-"): value for key, value in items if key != "stage"}


class IngressParser:
    """Pure parsing boundary for an ingress upload or stored text asset."""

    @staticmethod
    def parse_entity(entity: Ingress) -> tuple[file_validation.CSVMetadata, list[CsvRow]]:
        if entity.mimetype != "text/csv":
            raise ValidationError("File must be a CSV file.")
        text = entity.properties.text.asset
        if text is None:
            raise ValidationError("The CSV file has no text to parse.")
        parsed = dict(file_validation.process_csv(text))
        rows = cast(list[CsvRow], parsed.pop("rows", []))
        # ParsedCSV extends CSVMetadata with only the rows field.
        return cast(file_validation.CSVMetadata, parsed), rows


class IngressMapping:
    """Canonical projection from stored ingress configuration to row mappings."""

    def __init__(self, entity: Ingress) -> None:
        self.entity = entity
        self._fields = None
        self._column_map = None
        self._field_map = None
        self._page_form = None
        self._file_options = None
        self._page_options = None

    @property
    def columns(self) -> CsvColumns:
        return self.entity.properties.process_csv.columns or {}

    @property
    def entity_type(self) -> str | None:
        return self.entity.properties.choose_type.entity_type

    @property
    def form(self) -> Form | None:
        return self.entity.form

    @staticmethod
    def _field_details(field: SchemaField) -> ImportField:
        return {
            "label": field.label,
            "id": field.id,
            "kind": field.kind,
            "icon": field.icon,
            "choices": bool(field.choices),
            "fuzzy_import": bool(
                field.choices or isinstance(field, Link) and field.is_entity_valued
            ),
            "type": cast(str | None, field.get("type")),
        }

    def _default_fields(self) -> FieldsById:
        fields: FieldsById = {}
        if not _form_fields(self.form).get("name"):
            fields["name"] = {
                "label": "Page Name",
                "id": "name",
                "kind": "page",
                "icon": "text",
                "type": "input",
            }
        if not _form_fields(self.form).get("description") and self.entity_type == "page":
            fields["description"] = {
                "label": "Description",
                "id": "description",
                "kind": "page",
                "icon": "textarea",
                "type": "textarea",
            }
        if self.entity_type == "task":
            fields.update(
                {
                    "task_name": {
                        "label": "Task Name",
                        "id": "task_name",
                        "kind": "task",
                        "icon": "text",
                        "type": "input",
                    },
                    "completed_on": {
                        "label": "Completed On",
                        "id": "completed_on",
                        "kind": "task",
                        "icon": "date",
                        "type": "input",
                    },
                    "due_date": {
                        "label": "Due Date",
                        "id": "due_date",
                        "kind": "task",
                        "icon": "date",
                        "type": "input",
                    },
                }
            )
        return fields

    @property
    def fields(self) -> FieldsById:
        if self._fields is not None:
            return self._fields
        self._fields = self._default_fields()
        for field_id, field in _form_fields(self.form).items():
            if isinstance(field, (Signature, HTML, Status)):
                continue
            if isinstance(field, Table):
                for sub_field in field.fields.values():
                    self._fields[sub_field.id] = self._field_details(sub_field)
            else:
                self._fields[field_id] = self._field_details(field)
        return self._fields

    def ignore(self, column_id: str) -> object:
        return self.entity.properties.assign_columns.section.get(f"ignore-{column_id}")

    def guess_field(self, column_id: str) -> ImportField | None:
        column = self.columns.get(column_id) or {}
        if self.entity_type == "task" and column.get("label", "").strip().lower() == "name":
            return self.fields.get("name")
        return next(
            (
                field
                for field in self.fields.values()
                if (label := field["label"]) is not None
                and label.lower() == column.get("label", "").lower()
            ),
            None,
        )

    @property
    def column_map(self) -> FieldsById:
        if self._column_map is not None:
            return self._column_map
        section = self.entity.properties.assign_columns.section
        mapped: FieldsById = {}
        for index, column_id in enumerate(self.columns):
            if self.ignore(column_id):
                continue
            field_id = section.get(column_id)
            field = self.fields.get(field_id) if isinstance(field_id, str) else None
            if field:
                mapped[column_id] = {**field, "index": index}
        self._column_map = mapped
        return mapped

    @property
    def field_map(self) -> dict[str, list[str]]:
        if self._field_map is not None:
            return self._field_map
        mapped = {}
        for field_id in self.fields:
            column_ids = [
                column_id
                for column_id, field in self.column_map.items()
                if field["id"] == field_id
            ]
            if column_ids:
                mapped[field_id] = column_ids
        self._field_map = mapped
        return mapped

    def field(self, field_id: str) -> ImportField | None:
        details = self.fields.get(field_id)
        column_ids = self.field_map.get(field_id)
        if not details and isinstance(field := _form_fields(self.form).get(field_id), Table):
            labels = [
                f"[ {', '.join(self.columns[cid].get('label', '') for cid in row if cid)} ]"
                for row in column_ids or []
            ]
            return {
                "label": field.label,
                "id": field.id,
                "kind": "form",
                "icon": "table",
                "type": "table",
                "description": "\n".join(labels) if labels else None,
            }
        if not details:
            return None
        details = details.copy()
        details["description"] = (
            " ".join(
                f"{{ {self.columns[column_id].get('label', '')} }}"
                for column_id in column_ids
            )
            if column_ids
            else None
        )
        return details

    @property
    def verify_section(self) -> dict[str, object]:
        return self.entity.properties.verify_import.section

    def fuzzy_match(self, field_id: str) -> bool:
        return bool(
            self.verify_section.get(f"fuzzy-{field_id}")
            or self.verify_section.get(f"fuzzy-{field_id.replace('_', '-')}")
        )

    @property
    def file_options(self) -> list[ImportField]:
        if self._file_options is not None:
            return self._file_options
        options: list[ImportField] = []
        for column_id, column in self.columns.items():
            if column.get("type") != "string":
                continue
            mapped = self.column_map.get(column_id)
            field_id = mapped["id"] if mapped else None
            icon: str | None = "csv"
            if field_id:
                field = self.fields.get(field_id)
                icon = field["icon"] if field else None
            options.append(
                {
                    "id": field_id or column_id,
                    "label": column.get("label"),
                    "icon": icon,
                    "kind": "file",
                }
            )
        self._file_options = options
        return options

    @property
    def page_form(self) -> Form | None:
        page_form_id = self.verify_section.get("page-form-id")
        if self._page_form is None and isinstance(page_form_id, str) and page_form_id:
            self._page_form = Entities.FORM(page_form_id)
        return self._page_form

    @property
    def page_options(self) -> list[ImportField]:
        if self._page_options is not None:
            return self._page_options
        options: list[ImportField] = [{"id": "name", "label": "Name", "icon": "text", "kind": "page"}]
        if self.page_form:
            for field in _form_fields(self.page_form).values():
                if field.get("type") == "input" and field.id != "name":
                    options.append(
                        {
                            "label": field.label,
                            "id": field.id,
                            "kind": field.kind,
                            "icon": field.icon,
                        }
                    )
        self._page_options = options
        return options

    @property
    def index_from_field(self) -> ImportField | None:
        index_from = self.verify_section.get("index-from")
        if index_from:
            return next(
                (field for field in self.file_options if field["id"] == index_from),
                None,
            )
        return next(
            (
                field
                for field in self.file_options
                if field["id"] == "name" or (field.get("label") or "").lower() == "name"
            ),
            None,
        )

    @property
    def index_to_field(self) -> ImportField | None:
        index_to = self.verify_section.get("index-to")
        if index_to:
            return next(
                (field for field in self.page_options if field["id"] == index_to),
                None,
            )
        return next(
            (field for field in self.page_options if field["id"] == "name"),
            None,
        )


class IngressMutationPlanner:
    """Convert one mapped CSV row into deterministic entity mutations."""

    Entities = Entities
    dates = dates
    files = files

    def __init__(
        self,
        entity: Ingress,
        *,
        row_index: int = 0,
        service: IngressService | None = None,
    ) -> None:
        self.entity = entity
        self.row_index = row_index
        self.service = service
        self.mapping = IngressMapping(entity)
        self.created_entities: list[Entity] = []
        self._history_index = 0

    @property
    def separator(self) -> str | None:
        """Use the saved multi-value separator for categorical submission fields."""
        return self.entity.properties.choose_form.separator

    @property
    def columns(self) -> CsvColumns | None:
        return self.entity.properties.process_csv.columns

    @property
    def field_map(self) -> dict[str, list[str]]:
        verify = self.entity.properties.verify_import
        return getattr(
            verify,
            "field_map",
            self.entity.properties.assign_columns.field_map,
        )

    @property
    def entity_type(self) -> str | None:
        return self.entity.properties.choose_type.entity_type

    @property
    def fuzzy_page_match(self) -> bool | None:
        return self.entity.properties.verify_import.fuzzy_page

    def fuzzy_match(self, field_id: str) -> bool:
        verify = self.entity.properties.verify_import
        method = getattr(verify, "fuzzy_match", None)
        return (
            cast(bool, method(field_id)) if callable(method) else self.mapping.fuzzy_match(field_id)
        )

    @property
    def form(self) -> Form | None:
        return self.entity.form

    @staticmethod
    def _message_strings(messages):
        if not messages:
            return []
        if isinstance(messages, (str, ValidationError)):
            return [str(messages)]
        try:
            return [str(message) for message in messages]
        except TypeError:
            return [str(messages)]

    def _extend_messages(self, result, message_type, messages):
        result.setdefault(message_type, []).extend(self._message_strings(messages))

    def _deterministic_key(self, kind, role):
        if not self.service:
            return None
        return self.service.entity_key(
            kind,
            f"row:{self.row_index}:{role}",
        )

    def plan(self, row: CsvRow) -> IngressMutationPlan:
        columns = self.columns
        if columns is None:
            raise ValidationError("The CSV column mapping is missing.")
        values = {
            columns[column_id]["label"]: value
            for column_id, value in row.items()
            if value
        }
        result: dict[str, Any] = {"row": json.dumps(values, sort_keys=True)}
        try:
            to_validate = self._get_to_validate(row, result)
            if self.entity_type == "task":
                created = self._create_task(row, to_validate, result)
                if created and created.new_history_created:
                    for history in created.new_history_created:
                        text = (
                            f"Completed on {history.completed_on.strftime('%d %b %Y')}"
                        )
                        result.setdefault("history", []).append(text)
                if created:
                    result["entity"] = created.details
                    self._collect_submission_messages(result, created)
                    self._collect_submission_messages(
                        result, *created.new_history_created
                    )
                    self.created_entities.append(created)
            else:
                created = self._create_page(to_validate)
                result["entity"] = created.details
                self._collect_submission_messages(result, created)
                self.created_entities.append(created)

            for field in _form_fields(self.form).values():
                self._extend_messages(result, "warnings", field.warnings)
                self._extend_messages(result, "errors", field.errors)
        except ValidationError as error:
            # Tasks may already be staged when submission validation fails.
            # Do not hand any part of a rejected row to the mutation executor.
            self.created_entities.clear()
            result.pop("entity", None)
            result.pop("history", None)
            result.setdefault("errors", []).append(str(error))
        # Unexpected failures must reach the service's resumable failure boundary,
        # rather than returning a partially staged row as a successful plan.

        entities = []
        seen = set()
        for entity in self.created_entities:
            marker = getattr(entity, "key", None) or id(entity)
            if marker in seen:
                continue
            seen.add(marker)
            entities.append(entity)
        idempotency_key = (
            self.service.idempotency_key(f"row:{self.row_index}")
            if self.service
            else f"row:{self.row_index}"
        )
        result["idempotency_key"] = idempotency_key
        return IngressMutationPlan(
            row_index=self.row_index,
            idempotency_key=idempotency_key,
            result=result,
            entities=tuple(entities),
        )

    def _collect_submission_messages(self, result, *entities):
        for entity in entities:
            submission = getattr(
                getattr(entity, "properties", None), "submission", None
            )
            for field in getattr(submission, "fields", {}).values():
                self._extend_messages(result, "warnings", field.warnings)
                self._extend_messages(result, "errors", field.errors)

    def _get_to_validate(self, row, result):
        to_validate = {}

        def join_values(values):
            return " ".join(
                str(value).strip()
                for value in values
                if value is not None and str(value).strip()
            )

        def import_value(field, values):
            if not values or not any(values):
                return None
            if isinstance(field, (CategoricalElement, TextInput)):
                return values if isinstance(values, list) else [values]
            if len(values) > 1:
                result.setdefault("warnings", []).append(
                    f"Field '{field.label}': Cannot have multiple values"
                )
                return None
            return values[0]

        for field_id, field in _form_fields(self.form).items():
            column_ids = self.field_map.get(field_id)
            if isinstance(field, Table):
                values = [
                    [
                        import_value(field.fields.get(sub_field_id), [row.get(cid)])
                        for cid in self.field_map.get(sub_field_id, [])
                    ]
                    for sub_field_id in field.fields
                ]
                table_rows = [list(value) for value in zip(*values, strict=False)] if values else []
                to_validate[field_id] = [value for value in table_rows if any(value)]
            elif column_ids:
                to_validate[field_id] = import_value(
                    field, [row.get(column_id) for column_id in column_ids]
                )

        for field_id in ("name", "description"):
            if to_validate.get(field_id):
                continue
            verify = self.entity.properties.verify_import
            column_map = getattr(
                verify,
                "column_map",
                self.entity.properties.assign_columns.column_map,
            )
            column_ids = [
                column_id
                for column_id, field in column_map.items()
                if field["id"] == field_id
            ]
            to_validate[field_id] = (
                join_values([row.get(column_id) for column_id in column_ids])
                if column_ids
                else None
            )
        return to_validate

    def _new_page(self, data):
        key = self._deterministic_key("page", "entity")
        if key is None:
            return self.Entities.PAGE.create(data)
        page = self.Entities.PAGE(key)
        page.kind = page.entity_kind
        page.update(data)
        return page

    def _create_page(self, to_validate):
        page = self._new_page({"form": self.form, "model": self.entity.parent})
        page.import_submission(to_validate, self)
        for attribute in ("name", "description"):
            value = getattr(page.submission, "get", lambda *_: None)(attribute)
            value = value or to_validate.get(attribute)
            if isinstance(value, list):
                value = " ".join(
                    str(item).strip()
                    for item in value
                    if item is not None and str(item).strip()
                )
            setattr(page, attribute, value)
        return page

    def _get_due_date(self, row, task):
        due_dates = [row.get(cid) for cid in self.field_map.get("due_date", [])]
        parsed = [
            self.dates.parse_imported_date_as_utc(value) for value in due_dates if value
        ] + [task.due_date]
        parsed = [value for value in parsed if value]
        return max(parsed) if parsed else None

    def _get_completed_on(self, row):
        values = [row.get(cid) for cid in self.field_map.get("completed_on", [])]
        return sorted(
            value
            for value in (
                self.dates.parse_imported_date_as_utc(raw) for raw in values if raw
            )
            if value
        )

    def _history_key(self, role):
        key = self._deterministic_key(
            "task_history", f"history:{self._history_index}:{role}"
        )
        self._history_index += 1
        return key

    def _set_history(self, task, row, to_validate):
        due_date = self._get_due_date(row, task)
        completed_on = self._get_completed_on(row)
        if due_date and any(value > due_date for value in completed_on):
            due_date = None
        for date_completed in completed_on:
            self._apply_completed_import(task, date_completed, to_validate)
        if due_date and task.completed:
            key = self._history_key("due-uncomplete")
            task.uncomplete(history_key=key) if key else task.uncomplete()
        if not completed_on:
            task.import_submission(to_validate, self)
        if due_date and task.due_date != due_date:
            task.due_date = due_date
        return task

    def _apply_completed_import(self, task, completed_on, to_validate):
        current = task.completed_on if task.completed else None
        if current and completed_on <= current:
            self._record_completed_history(task, completed_on, to_validate)
            return
        if task.completed:
            key = self._history_key("advance-completion")
            task.uncomplete(history_key=key) if key else task.uncomplete()
        task.completed = True
        task.completed_on = completed_on
        task.completed_by = None
        task.assigned_to = None
        task.due_date = None
        task.import_submission(to_validate, self)

    def _record_completed_history(self, task, completed_on, to_validate):
        values = {
            "completed_on": completed_on,
            "files": [],
            "submission": None,
            "name": to_validate.get("name"),
            "description": to_validate.get("description"),
            "form": self.form or getattr(task, "form", None),
        }
        key = self._history_key("older-completion")
        if key:
            values["history_key"] = key
        history = task.create_history_entry(**values)
        history.import_submission(to_validate, self)
        return history

    def _new_task(self, data):
        key = self._deterministic_key("task", "entity")
        if key is None:
            return self.Entities.TASK.create(data)
        task = self.Entities.TASK(key)
        task.kind = task.entity_kind
        task.completed = False
        task.update(data)
        return task

    def _create_task(self, row, to_validate, result):
        task_name = " ".join(
            str(row.get(column_id)).strip()
            for column_id in self.field_map.get("task_name", [])
            if row.get(column_id) is not None and str(row.get(column_id)).strip()
        )
        verify = self.entity.properties.verify_import
        map_to_value = to_validate.get(verify.index_from) or row.get(verify.index_from)
        target = (
            getattr(verify, "index_to_field", None) or self.mapping.index_to_field or {}
        )
        field_label = target.get("label")
        if isinstance(map_to_value, list):
            map_to_value = " ".join(
                str(value).strip()
                for value in map_to_value
                if value is not None and str(value).strip()
            )
        if not field_label:
            result.setdefault("errors", []).append("No page index field set")
            return None
        if not map_to_value:
            result.setdefault("errors", []).append(
                f"The '{field_label}' column does not contain a value in this row"
            )
            return None
        page_id = self._get_task_page(map_to_value, field_label, result)
        if not page_id:
            return None
        page = self.Entities.PAGE(page_id)
        task = self._new_task(
            {
                "page": page,
                "form": self.entity.form,
                "name": task_name or self.entity.properties.choose_parent.task_name,
                "description": to_validate.get("description"),
                "model": self.entity.model,
                "project": self.entity.project,
            }
        )
        if task not in self.created_entities:
            self.created_entities.append(task)
        task = self._set_history(task, row, to_validate)
        if task_name:
            task.name = task_name
        return task

    def _get_task_page(self, map_to_value, field_label, result):
        match = self.files.find_page(
            map_to_value,
            match_field_label=field_label,
            fuzzy=self.fuzzy_page_match,
        )
        if match["warnings"]:
            self._extend_messages(result, "warnings", match["warnings"])
        if match["errors"]:
            self._extend_messages(result, "errors", match["errors"])
        return match["id"]


class IngressService:
    """Single durable owner for ingress transitions and row execution."""

    def __init__(self, entity: Ingress) -> None:
        self.entity = entity

    @classmethod
    def create(
        cls,
        upload: FileStorage | DirectUploadFile,
        *,
        entity_cls: type[Ingress] | None = None,
    ) -> Ingress:
        enforce_file_consumer(
            upload,
            FileConsumer.CSV_INGRESS,
            filename=getattr(upload, "filename", None),
        )
        entity_cls = entity_cls or Entities.INGRESS
        entity = entity_cls()
        entity.kind = entity.entity_kind
        entity.db["ingress_format"] = INGRESS_FORMAT_VERSION
        entity.filename = upload.filename
        entity.file = upload
        metadata, rows = IngressParser.parse_entity(entity)
        entity.properties.rows.value = rows
        workflow = entity.get_process("workflow")
        workflow.update(
            {
                "current": IngressStage.PROCESS_CSV.name,
                "highest_completed": IngressStage.PROCESS_CSV.name,
                "configuration_revision": 1,
                "process_csv": {
                    **{key.replace("_", "-"): value for key, value in metadata.items()},
                    "complete": True,
                },
            }
        )
        entity.get_process("execution").update(
            {
                "status": IngressRunStatus.IDLE.value,
                "cursor": 0,
                "total_rows": len(rows),
                "dispatch_sequence": 0,
            }
        )
        return entity

    @property
    def workflow(self) -> Workflow:
        return cast(Workflow, self.entity.get_process("workflow"))

    @property
    def execution(self) -> Execution:
        return cast(Execution, self.entity.get_process("execution"))

    def require_supported(self) -> IngressService:
        if self.entity.db.get("ingress_format") != INGRESS_FORMAT_VERSION:
            raise IngressFormatError(
                "This import was created by an unsupported ingress format. "
                "Please upload the CSV file again."
            )
        try:
            IngressStage[self.workflow["current"]]
        except (KeyError, TypeError) as error:
            raise IngressFormatError(
                "This import has an invalid workflow stage. "
                "Please upload the CSV file again."
            ) from error
        return self

    @property
    def stage(self) -> IngressStage:
        self.require_supported()
        return IngressStage[self.workflow["current"]]

    @property
    def run_status(self) -> str:
        return self.execution.get("status", IngressRunStatus.IDLE.value)

    @property
    def cursor(self) -> int:
        return int(self.execution.get("cursor") or 0)

    @property
    def total(self) -> int:
        return int(self.execution.get("total_rows") or 0)

    def idempotency_key(self, role: str) -> str:
        revision = int(self.workflow.get("configuration_revision") or 1)
        try:
            identifier = self.entity.urlsafe_key
        except (AttributeError, RuntimeError, ValueError):
            identifier = self.entity.db.get("hash") or "testing-ingress"
        source = f"{identifier}:{revision}:{role}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def entity_key(
        self, kind: str, role: str, parent: Entity | Key | None = None
    ) -> Key:
        identifier = self.idempotency_key(role)
        return database_utility.create_named_key(kind, identifier, parent=parent)

    def stage_status(self, stage: str | IngressStage) -> ProcessProperty[Ingress]:
        stage = self._coerce_stage(stage)
        # Every supported stage maps to a registered process section on Ingress.
        return cast("ProcessProperty[Ingress]", self.entity.properties.get(stage.name.lower()))

    @staticmethod
    def _coerce_stage(stage: str | IngressStage) -> IngressStage:
        if isinstance(stage, IngressStage):
            return stage
        if not isinstance(stage, str):
            raise ValueError(f"Invalid stage: {stage}")
        try:
            return IngressStage[stage.upper()]
        except KeyError as error:
            raise ValueError(f"Invalid stage: {stage}") from error

    def can_navigate(self, target: str | IngressStage) -> bool:
        try:
            target = self._coerce_stage(target)
        except ValueError:
            return False
        if target not in CONFIGURATION_STAGES or self.run_status != "idle":
            return False
        highest_name = self.workflow.get("highest_completed")
        try:
            if highest_name is None:
                return target == IngressStage.PROCESS_CSV
            highest = IngressStage[highest_name]
        except (KeyError, TypeError):
            return target == IngressStage.PROCESS_CSV
        return target.value <= min(highest.value + 1, IngressStage.VERIFY_IMPORT.value)

    def navigate(
        self, target: str | IngressStage, *, save: bool = True
    ) -> IngressProgress:
        self.require_supported()
        target = self._coerce_stage(target)
        if not self.can_navigate(target):
            raise IngressTransitionError(
                f"Cannot navigate from {self.stage.name} to {target.name}."
            )
        self.workflow["current"] = target.name
        if save:
            self.save()
        return self.progress()

    def update_current(
        self, data: Mapping[str, object], *, save: bool = True
    ) -> dict[str, object]:
        return self.update_stage(self.stage, data, save=save)

    def update_stage(
        self,
        stage: str | IngressStage,
        data: Mapping[str, object],
        *,
        save: bool = True,
    ) -> dict[str, object]:
        self.require_supported()
        stage = self._coerce_stage(stage)
        if stage not in CONFIGURATION_STAGES:
            raise IngressTransitionError("Execution configuration is immutable.")
        if self.run_status != IngressRunStatus.IDLE.value:
            raise IngressTransitionError(
                "Import settings cannot change after execution starts."
            )
        section = self.stage_status(stage).section
        submitted = _form_data(data)
        current = {
            key: value
            for key, value in section.items()
            if key not in {"complete", "error"}
        }
        if submitted == current:
            return section
        section.clear()
        section.update(submitted)
        self.workflow["configuration_revision"] = (
            int(self.workflow.get("configuration_revision") or 0) + 1
        )
        self._invalidate_from(stage)
        if save:
            self.save()
        return section

    def _invalidate_from(self, stage):
        if stage.value <= IngressStage.CHOOSE_FORM.value:
            self.entity.clear_form_stages()
        for candidate in CONFIGURATION_STAGES:
            if candidate.value <= stage.value:
                continue
            self.stage_status(candidate).clear()
        self.stage_status(IngressStage.IMPORTING).clear()
        self.stage_status(IngressStage.COMPLETED).clear()
        self.stage_status(stage).section.pop("complete", None)
        self.stage_status(stage).section.pop("error", None)
        previous = IngressStage(max(IngressStage.PROCESS_CSV.value, stage.value - 1))
        self.workflow["highest_completed"] = previous.name
        if stage in {IngressStage.CHOOSE_TYPE, IngressStage.CHOOSE_PARENT}:
            self.entity.category = None
            self.entity.project = None
            self.entity.model = None
            self.entity.form = None
        elif stage == IngressStage.CHOOSE_FORM:
            self.entity.form = None

    def finalize(self, data: Mapping[str, object] | None = None) -> bool:
        self.require_supported()
        stage = self.stage
        if stage not in CONFIGURATION_STAGES:
            raise IngressTransitionError(f"Cannot finalize {stage.name}.")
        if data is not None and _form_data(data):
            self.update_stage(stage, data, save=False)
        status = self.stage_status(stage)
        status.section.pop("error", None)
        extra = []
        try:
            if stage == IngressStage.PROCESS_CSV:
                if self.entity.mimetype != "text/csv":
                    raise ValidationError("File must be a CSV file.")
                if not status.columns:
                    raise ValidationError("No CSV columns were found.")
            elif stage == IngressStage.CHOOSE_TYPE:
                if status.entity_type not in {"page", "task"}:
                    raise ValidationError("Please select pages or tasks.")
            elif stage == IngressStage.CHOOSE_PARENT:
                extra = self._apply_parent_choice()
            elif stage == IngressStage.CHOOSE_FORM:
                extra = self._apply_form_choice()
            elif stage == IngressStage.VERIFY_IMPORT:
                self._validate_import_settings()
        except (ValidationError, ValueError) as error:
            status.error = str(error)
            self.save(*extra)
            return False
        except Exception as error:
            status.error = str(error)
            exceptions.capture(error, context={"stage": stage.name})
            self.save(*extra)
            return False
        status.complete = True
        self.workflow["highest_completed"] = stage.name
        self.save(*extra)
        return True

    def advance(self, data: Mapping[str, object] | None = None) -> IngressProgress:
        stage = self.stage
        submitted_stage = data.get("stage") if data is not None and hasattr(data, "get") else None
        if submitted_stage and submitted_stage != stage.name:
            raise IngressTransitionError(
                f"Expected {stage.name}, received {submitted_stage}."
            )
        if stage not in CONFIGURATION_STAGES[:-1]:
            raise IngressTransitionError(f"Cannot advance from {stage.name}.")
        if not self.finalize(data):
            return self.progress()
        self.workflow["current"] = IngressStage(stage.value + 1).name
        self.save()
        return self.progress()

    def _apply_parent_choice(self) -> list[Entity]:
        status = self.entity.properties.choose_parent
        entity_type = self.entity.properties.choose_type.entity_type
        if not status.parent_choice:
            raise ValidationError("Please choose an option")
        if status.parent_choice == "existing-parent" and not status.parent_id:
            raise ValidationError("Please select an existing option")
        created: list[Entity] = []
        if status.parent_choice == "existing-parent":
            parent = Entities.fetch_one(status.parent_id, request=Fetch.direct())
            if parent is None:
                raise ValidationError("The selected parent no longer exists.")
            self.entity.parent = cast("Category | ModelTask | Project", parent)
        elif entity_type == "task":
            project_data: ProjectData = {"name": status.parent_name or self.entity.name}
            if getattr(self.entity, "_testing", False):
                project = Entities.PROJECT.create(project_data)
            else:
                key = self.entity_key("project", "setup:project")
                project = Entities.PROJECT(key)
                project.kind = project.entity_kind
                project.update(project_data)
            self.entity.project = project
            created.append(project)
        else:
            category_data: CategoryData = {"name": status.parent_name or self.entity.name}
            if getattr(self.entity, "_testing", False):
                category = Entities.CATEGORY.create(category_data)
            else:
                key = self.entity_key("category", "setup:category")
                category = Entities.CATEGORY(key)
                category.kind = category.entity_kind
                category.update(category_data)
            self.entity.category = category
            created.append(category)

        if entity_type == "task" and status.create_model:
            project = self.entity.project
            if project is None:
                raise ValidationError("Choose a project before creating its model.")
            model_data: ModelTaskData = {"name": status.model_name or self.entity.name}
            if getattr(self.entity, "_testing", False):
                model = Entities.MODEL_TASK.create(project, model_data)
            else:
                key = self.entity_key("model", "setup:model", parent=project)
                model = Entities.MODEL_TASK(key)
                model.kind = model.entity_kind
                model.project = project
                project.properties.model_tasks.add(model)
                model.update(model_data)
            self.entity.model = model
            created.extend([project, model])
        return created

    def _apply_form_choice(self) -> list[Entity]:
        status = self.entity.properties.choose_form
        if not status.form_choice:
            raise ValidationError("Please choose an option")
        if status.form_choice == "existing-form" and not status.form_id:
            raise ValidationError("Please select an existing form")
        created: list[Entity] = []
        if status.form_choice == "existing-form":
            form = (
                Entities.FORM(status.form_id)
                if getattr(self.entity, "_testing", False)
                else Entities.fetch_one(status.form_id, request=Fetch.direct())
            )
            if form is None:
                raise ValidationError("The selected form no longer exists.")
            self.entity.form = cast("Form", form)
        else:
            form_type = self.entity.properties.choose_type.entity_type
            if form_type is None:
                raise ValidationError("Choose the imported entity type before creating a form.")
            schema, separator = file_validation.create_schema(
                self.entity.properties.process_csv.columns or {},
                _stored_rows(self.entity),
                form_type=form_type,
            )
            data = {
                "name": status.form_name or f"{self.entity.name} Form",
                "form-type": self.entity.properties.choose_type.entity_type,
                "schema": schema,
            }
            if getattr(self.entity, "_testing", False):
                form = Entities.FORM.create(data)
            else:
                key = self.entity_key("form", "setup:form")
                form = Entities.FORM(key)
                form.kind = form.entity_kind
                form.update(data)
            status.separator = separator
            self.entity.form = form
            created.append(form)
        if status.set_default_form:
            parent = self.entity.parent
            if parent is None:
                raise ValidationError("Choose a parent before setting its default form.")
            parent.form = self.entity.form
            created.append(parent)
        return created

    def _validate_import_settings(self):
        if self.entity.properties.choose_type.entity_type == "page":
            return
        status = self.entity.properties.verify_import
        mapping = IngressMapping(self.entity)
        if mapping.field_map.get("name"):
            status.index_from = "name"
            status.index_to = "name"
            status.index_field_choice = "name"
            status.fuzzy_page = True
        if not all([status.index_from, status.index_to, status.index_field_choice]):
            raise ValidationError("Please set the page index field")

    def select_page_form(self, value: str | None) -> IngressMapping:
        self.require_supported()
        if self.stage != IngressStage.VERIFY_IMPORT:
            raise IngressTransitionError(
                "Page matching can only change during import verification."
            )
        status = self.entity.properties.verify_import
        if value == "name":
            status.index_field_choice = "name"
            status.page_form_id = None
            status.index_to = "name"
        else:
            status.page_form_id = value
        status.complete = None
        self.workflow["configuration_revision"] = (
            int(self.workflow.get("configuration_revision") or 0) + 1
        )
        self.save()
        return IngressMapping(self.entity)

    def start(self, client_context: object = None) -> IngressProgress:
        self.require_supported()
        if self.stage == IngressStage.IMPORTING:
            if self.run_status in {
                IngressRunStatus.STOPPED.value,
                IngressRunStatus.FAILED.value,
            }:
                return self.restart(client_context)
            if self.run_status in ACTIVE_RUN_STATUSES:
                return self.progress()
            raise IngressTransitionError(
                f"Cannot start an import in {self.run_status} state."
            )
        if self.stage != IngressStage.VERIFY_IMPORT:
            raise IngressTransitionError(
                f"Cannot start an import from {self.stage.name}."
            )
        if not self.finalize():
            return self.progress()
        self.workflow["current"] = IngressStage.IMPORTING.name
        self.execution.update(
            {
                "status": IngressRunStatus.QUEUED.value,
                "cursor": 0,
                "total_rows": len(_stored_rows(self.entity)),
                "dispatch_sequence": int(self.execution.get("dispatch_sequence") or 0)
                + 1,
            }
        )
        self.execution.pop("error", None)
        self.execution.pop("lease_token", None)
        self.execution.pop("lease_expires", None)
        self.entity.properties.results.save_slots([])
        self.save()
        return self.progress()

    def restart(self, client_context: object = None) -> IngressProgress:
        if self.stage != IngressStage.IMPORTING or self.run_status not in {
            IngressRunStatus.STOPPED.value,
            IngressRunStatus.FAILED.value,
        }:
            raise IngressTransitionError("Only stopped or failed imports can restart.")
        self.execution["status"] = IngressRunStatus.QUEUED.value
        self.execution["dispatch_sequence"] = (
            int(self.execution.get("dispatch_sequence") or 0) + 1
        )
        for key in ("error", "lease_token", "lease_expires"):
            self.execution.pop(key, None)
        self.save()
        return self.progress()

    def mark_dispatch_failed(self, error: object) -> IngressProgress:
        self.execution["status"] = IngressRunStatus.FAILED.value
        self.execution["error"] = str(error)
        self.execution.pop("lease_token", None)
        self.execution.pop("lease_expires", None)
        self.save()
        return self.progress()

    def stop(self, *, now: datetime | None = None) -> IngressProgress:
        self.require_supported()
        if self.stage != IngressStage.IMPORTING:
            raise IngressTransitionError("Only an active import can be stopped.")
        if self.run_status not in ACTIVE_RUN_STATUSES:
            return self.progress()
        now = _utc(now)
        if getattr(self.entity, "_testing", False) or not self.entity.key:
            self.execution["status"] = IngressRunStatus.STOPPED.value
            self.execution.pop("lease_token", None)
            self.execution.pop("lease_expires", None)
            return self.progress()
        updated = ingress_database.update_ingress_status(
            self.entity,
            IngressRunStatus.STOPPED.value,
            now,
        )
        if updated.get("entity") is not None:
            self._replace_from_raw(updated["entity"])
        return self.progress()

    def _replace_from_raw(self, raw):
        replacement = Entities.INGRESS(raw)
        replacement = (
            Entities.fetch_one(replacement, request=Fetch.direct()) or replacement
        )
        self.entity = replacement
        return replacement

    def run_batch(
        self, limit: int = INGRESS_BATCH_SIZE, *, now: datetime | None = None
    ) -> IngressBatchResult:
        self.require_supported()
        now = _utc(now)
        if self.run_status == IngressRunStatus.STOP_REQUESTED.value:
            self.stop(now=now)
        if self.run_status not in {
            IngressRunStatus.QUEUED.value,
            IngressRunStatus.RUNNING.value,
        }:
            return IngressBatchResult(
                state=self.run_status,
                processed=self.cursor,
                total=self.total,
                reason=self.run_status,
            )
        if self.cursor >= self.total:
            self._mark_completed()
            self.save()
            return IngressBatchResult(
                state=IngressRunStatus.COMPLETED.value,
                processed=self.cursor,
                total=self.total,
            )

        emitted = []
        failure_cursor = self.cursor
        try:
            batch_limit = max(1, int(limit))
            for batch_index in range(batch_limit):
                cursor = self.cursor
                failure_cursor = cursor
                if cursor >= self.total:
                    break
                row = _stored_rows(self.entity)[cursor]
                planner = IngressMutationPlanner(
                    self.entity,
                    row_index=cursor,
                    service=self,
                )
                mutation = planner.plan(row)
                slots = list(self.entity.properties.results.slots)
                while len(slots) <= cursor:
                    slots.append(None)
                slots[cursor] = mutation.result
                self.entity.properties.results.save_slots(slots)
                complete = cursor + 1 >= self.total
                dispatch_next = not complete and batch_index == batch_limit - 1
                committed = self._commit_row(
                    mutation,
                    cursor,
                    now,
                    complete=complete,
                    dispatch_next=dispatch_next,
                )
                if not committed.get("committed"):
                    return IngressBatchResult(
                        state=self.run_status,
                        processed=self.cursor,
                        total=self.total,
                        results=tuple(emitted),
                        reason=committed.get("reason"),
                    )
                emitted.append(mutation.result)
                execution = committed.get("execution")
                if execution is None:
                    raise RuntimeError("Committed import row is missing its execution state.")
                self.execution.update(cast(Execution, execution))
                if committed.get("reason") == "stopped":
                    return IngressBatchResult(
                        state=IngressRunStatus.STOPPED.value,
                        processed=self.cursor,
                        total=self.total,
                        results=tuple(emitted),
                        reason="stopped",
                    )
                if complete:
                    return IngressBatchResult(
                        state=IngressRunStatus.COMPLETED.value,
                        processed=self.cursor,
                        total=self.total,
                        results=tuple(emitted),
                    )

            return IngressBatchResult(
                state=IngressRunStatus.QUEUED.value,
                processed=self.cursor,
                total=self.total,
                results=tuple(emitted),
                dispatch_next=True,
            )
        except Exception as error:
            self.fail_run(error, expected_cursor=failure_cursor, now=now)
            raise

    def _commit_row(
        self,
        mutation,
        cursor,
        now,
        *,
        complete=False,
        dispatch_next=False,
    ):
        self.execution["cursor"] = cursor + 1
        self.execution["status"] = IngressRunStatus.QUEUED.value
        self.execution.pop("error", None)
        self.execution.pop("lease_token", None)
        self.execution.pop("lease_expires", None)
        if dispatch_next:
            self.execution["dispatch_sequence"] = (
                int(self.execution.get("dispatch_sequence") or 0) + 1
            )
        if complete:
            self._mark_completed()

        entities = (self.entity, *mutation.entities)
        plan = plan_mutation(MutationOperation.SAVE, *entities, registry=Entities)
        writes = prepare_durable_writes(plan)
        if getattr(self.entity, "_testing", False) or not self.entity.key:
            consume_mutation_intents(plan)
            return {
                "committed": True,
                "reason": "committed",
                "execution": dict(self.execution),
            }
        committed = ingress_database.commit_ingress_row(
            self.entity,
            cursor,
            self.entity,
            ((effect.entity, effect.property_mask) for effect in writes),
            now,
        )
        if not committed.get("committed") and (raw_entity := committed.get("entity")) is not None:
            self._replace_from_raw(raw_entity)
        if committed.get("committed"):
            consume_mutation_intents(plan)
            try:
                execute_post_commit(plan)
            except Exception as error:
                exceptions.capture(
                    error,
                    context={
                        "operation": "ingress_post_commit_cache",
                        "ingress": self.entity.urlsafe_key,
                        "cursor": cursor,
                    },
                )
        return committed

    def _mark_completed(self):
        self.execution.update(
            {
                "status": IngressRunStatus.COMPLETED.value,
                "cursor": self.total,
            }
        )
        self.execution.pop("lease_token", None)
        self.execution.pop("lease_expires", None)
        self.workflow["current"] = IngressStage.COMPLETED.name
        self.workflow["highest_completed"] = IngressStage.COMPLETED.name
        self.entity.properties.completed.complete = True

    def fail_run(
        self,
        error: object,
        *,
        expected_cursor: int | None = None,
        now: datetime | None = None,
    ) -> None:
        now = _utc(now)
        message = "Import failed while processing rows. Please try again."
        if getattr(self.entity, "_testing", False) or not self.entity.key:
            if expected_cursor is not None:
                self.execution["cursor"] = expected_cursor
            self.execution["status"] = IngressRunStatus.FAILED.value
            self.execution["error"] = message
            self.execution.pop("lease_token", None)
            self.execution.pop("lease_expires", None)
        else:
            updated = ingress_database.update_ingress_status(
                self.entity,
                IngressRunStatus.FAILED.value,
                now,
                expected_cursor=expected_cursor,
                error=message,
            )
            if updated.get("entity") is not None:
                self._replace_from_raw(updated["entity"])
        exceptions.capture(
            error,
            context={
                "operation": "ingress_run",
                "ingress": self.entity.urlsafe_key,
                "cursor": self.cursor,
            },
        )

    def progress(self) -> IngressProgress:
        self.require_supported()
        status = self.run_status
        actions = []
        if self.stage in CONFIGURATION_STAGES and status == "idle":
            actions.extend([IngressAction.NAVIGATE.value, IngressAction.ADVANCE.value])
            if self.stage == IngressStage.VERIFY_IMPORT:
                actions.append(IngressAction.START.value)
        elif self.stage == IngressStage.IMPORTING:
            if status in {
                IngressRunStatus.QUEUED.value,
                IngressRunStatus.RUNNING.value,
            }:
                actions.append(IngressAction.STOP.value)
            elif status in {"stopped", "failed"}:
                actions.append(IngressAction.RESTART.value)
        if self.cursor:
            actions.append(IngressAction.DELETE_IMPORTED.value)
        current_error = None
        if self.stage in CONFIGURATION_STAGES:
            current_error = self.stage_status(self.stage).error
        error = self.execution.get("error") or cast(str | None, current_error)
        return IngressProgress(
            stage=self.stage.name,
            run_status=status,
            processed=self.cursor,
            total=self.total,
            error=error,
            stopped=status in {"stopped", "failed"},
            actions=tuple(actions),
            poll_after_ms=2500 if status in ACTIVE_RUN_STATUSES else None,
        )

    def save(self, *entities: Entity | None) -> MutationOutcome | None:
        if getattr(self.entity, "_testing", False):
            return None
        return Entities.save(self.entity, *[entity for entity in entities if entity])

    def delete_imported(self) -> int:
        return self.entity.delete_imported_entities()
