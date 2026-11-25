"""Map CSV columns to form fields and page matches."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.form_links import Link
from lagniappe.core.properties.form_special import HTML, Signature, Status
from lagniappe.core.properties.form_table import Table

from .parser import CsvColumns

if TYPE_CHECKING:
    from lagniappe.core.entities.form import Form
    from lagniappe.core.entities.ingress import Ingress
    from lagniappe.core.properties.schema import SchemaField


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
