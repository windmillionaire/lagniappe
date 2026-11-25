"""Coordinate durable CSV import stages, row commits, and restart."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

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
    IngressProgress,
    IngressRunStatus,
    IngressStage,
    IngressTransitionError,
    MutationOperation,
    enforce_file_consumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mutations import (
    consume_mutation_intents,
    execute_post_commit,
    plan_mutation,
    prepare_durable_writes,
)
from lagniappe.core.tools.database import ingress as ingress_database
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.files import validate as file_validation

from .mapping import IngressMapping
from .parser import CsvRow, IngressParser
from .planner import IngressMutationPlanner

if TYPE_CHECKING:
    from google.cloud.datastore import Key
    from werkzeug.datastructures import FileStorage

    from lagniappe.core.definitions import MutationOutcome
    from lagniappe.core.entities.category import Category, CategoryData
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.form import Form
    from lagniappe.core.entities.ingress import Ingress
    from lagniappe.core.entities.model_task import ModelTask, ModelTaskData
    from lagniappe.core.entities.project import Project, ProjectData
    from lagniappe.core.properties.base_process import ProcessProperty
    from lagniappe.core.tools.database.assets import DirectUploadFile


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


def _stored_rows(entity: Ingress) -> list[CsvRow]:
    rows = entity.properties.rows.asset
    if rows is None:
        raise ValidationError("The parsed CSV rows are unavailable. Upload the file again.")
    return rows


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
