"""Plan deterministic Page and Task mutations for one mapped CSV row."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from lagniappe.core.definitions import IngressMutationPlan
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.form_inputs import TextInput
from lagniappe.core.properties.form_select import CategoricalElement
from lagniappe.core.properties.form_table import Table
from lagniappe.core.tools import dates
from lagniappe.core.tools.files import find_page as files

from .mapping import IngressMapping, _form_fields
from .parser import CsvColumns, CsvRow

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.form import Form
    from lagniappe.core.entities.ingress import Ingress

    from .service import IngressService


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
