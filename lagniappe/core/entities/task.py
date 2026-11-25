from collections.abc import Iterable
from typing import TYPE_CHECKING, Self, TypedDict, cast

from datetime import datetime, UTC
from uuid import uuid4
import json

from flask_login import current_user
from flask import url_for

from ..definitions import Action, Fetch, FetchReason, MutationIntent, MutationIntentType
from ..exceptions import TaskCompletionError, ValidationError
from ..mixins import AssetMixin, SubmitterMixin
from ..properties import (
    common_entity,
    common_related,
    task_related,
    task_dates,
    task_scheduling,
    form_submission,
)
from .entity import Entity, EntityProperties
from . import Entities
from lagniappe.core.tools.database import get as database_get
from ..tools.tasks import scheduling
from lagniappe.core.tools.forms.definitions import (
    capture_completed_submission,
    completed_envelope,
    immutable_submission,
    preload_definitions,
    stage_completion_guards,
    validate_completion_values,
)
from ..tools.auth.context import current_context_user
from ..tools.auth.restrictions import permission_relation


if TYPE_CHECKING:
    from ..tools.forms.definitions import FormIdentity, SubmissionDefinition
    from google.cloud.datastore import Entity as Row, Key

    from ..mixins.field_host import FieldUser
    from ..properties.schema import SchemaField
    from ..tools.forms.definitions import CompletionGuard
    from . import property_types
    from .history import TaskHistory, TaskHistoryOverrides
    from .model_task import ModelTask
    from .project import Project
    from .form import Form
    from .file import File
    from .user import User
    from .page import Page


class TaskData(TypedDict, total=False):
    page: Page | None
    task: Task | None
    form: Form | None
    name: str | None
    description: str | None
    due_date: datetime | str | float | None
    model: ModelTask | None
    project: Project | None
    assigned_to: Page | User | None
    asset_files: list[File] | None
    submission: object


class Task(AssetMixin, SubmitterMixin, Entity):
    if TYPE_CHECKING:
        @property
        def restricted_to(self) -> dict[str, list[str]]: ...

        _submission_definition: tuple[FormIdentity, SubmissionDefinition] | None
        completed: bool
        model: ModelTask | None
        project: Project | None
        deferred_job: dict[str, object] | None
        _completion_write_guards: list[CompletionGuard]
        @property
        def schedule(self) -> dict[str, object]: ...

        @property
        def assigned_to(self) -> Page | None: ...
        @assigned_to.setter
        def assigned_to(self, value: Page | User | None) -> None: ...

        @property
        def assigned_by(self) -> Page | None: ...
        @assigned_by.setter
        def assigned_by(self, value: Page | User | None) -> None: ...

        form: Form | None
        @property
        def due_date(self) -> datetime | None: ...

        @due_date.setter
        def due_date(self, value: datetime | str | float | None) -> None: ...

        page: Page | None
        description: str | None
        @property
        def submission(self) -> dict[str, object]: ...

        @submission.setter
        def submission(self, value: dict[str, object] | str | None) -> None: ...

        linked_pages: list[Page]
        @property
        def files(self) -> list[File]: ...
        @files.setter
        def files(self, value: list[File] | None) -> None: ...

        @property
        def completed_on(self) -> datetime | None: ...

        @completed_on.setter
        def completed_on(self, value: datetime | None) -> None: ...

        @property
        def completed_by(self) -> Page | None: ...

        @completed_by.setter
        def completed_by(self, value: Page | User | None) -> None: ...


        @property
        def properties(self) -> property_types.TaskProperties: ...

    entity_kind = "task"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset(
            {
                "submission",
                "pre_migration",
                "form_change_receipt",
                "completed_submission",
                "default_submission",
                "description",
                "assets",
                "schedule",
                "schema_version",
                "assignment_revision",
                "scheduled_uncomplete_token",
                "deferred_job",
                "autofill_reviews",
            }
        )

    @property
    def scheduled_uncomplete_token(self) -> str:
        return str(self.db.get("scheduled_uncomplete_token") or "")

    @property
    def scheduled_uncomplete_at(self) -> datetime | None:
        value = cast("datetime | None", self.db.get("scheduled_uncomplete_at"))
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _defer_scheduled_uncomplete(self, schedule_at: datetime) -> None:
        self.db["scheduled_uncomplete_token"] = uuid4().hex
        self.db["scheduled_uncomplete_at"] = schedule_at
        self.add_mutation_intents(
            MutationIntent.dispatch_scheduled_uncomplete(
                self,
                reason="scheduled-task-uncompletion",
            )
        )

    def _clear_scheduled_uncomplete(self) -> None:
        self.db.pop("scheduled_uncomplete_token", None)
        self.db.pop("scheduled_uncomplete_at", None)
        self._mutation_intents = [
            intent
            for intent in self.mutation_intents
            if intent.intent is not MutationIntentType.SCHEDULED_UNCOMPLETE_DISPATCH
        ]

    @property
    def required(self) -> list[str]:
        return self.page.required if self.page else []

    @property
    def url(self) -> str:
        return url_for("tasks.view", key=self.urlsafe_key)

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "description": common_entity.Description,
                "page": task_related.TaskPage,
                "categories": task_related.TaskCategories,
                "form": common_related.AttachedForm,
                "restricted_to": common_entity.RestrictedTo,
                "groups": common_related.Groups,
                "model": task_related.TaskModel,
                "project": common_related.AttachedProject,
                "due_date": task_dates.DueDate,
                "assigned_to": task_related.AssignedTo,
                "assigned_by": task_related.AssignedBy,
                "completed": task_dates.Completed,
                "status": task_related.TaskStatus,
                "completed_on": task_dates.CompletedOn,
                "completed_by": task_related.CompletedBy,
                "linked_pages": task_related.LinkedPages,
                "files": task_related.TaskFiles,
                "has_signature": task_related.HasSignature,
                "has_status": task_related.HasStatus,
                "active": common_entity.Active,
                "schedule": task_scheduling.Schedule,
                "recurring": task_scheduling.Recurring,
                "scheduled": task_scheduling.Scheduled,
                "periodic": task_scheduling.Periodic,
                "submission": form_submission.FormSubmission,
                "deferred_job": common_entity.DeferredJobReference,
            }
        )
        return properties

    def is_assigned_to(self, user: User) -> bool:
        return self.properties.assigned_to.key == user.page.key

    def allowed(self, action: Action, user: FieldUser = None) -> bool:
        user = current_context_user(user)
        if self.restricted_access(user):
            return False

        page = cast("Page", permission_relation(self, "page", required=True))
        page_action = Action.VIEW if action is Action.VIEW else Action.EDIT
        if page.allowed(page_action, user=user):
            return True
        user_page = getattr(user, "page", None)
        return bool(
            user_page
            and self.properties.assigned_to.key == user_page.key
            and Action.EDIT.implies(action)
        )

    def validate_assignment(self, assigned_to: Page | User | None, actor: FieldUser = None) -> None:
        if not assigned_to:
            return

        assigned_user = (
            assigned_to
            if isinstance(assigned_to, Entities.USER)
            else getattr(assigned_to, "user", None)
        )
        if not assigned_user:
            raise ValidationError("Assigned page is not linked to a user.")

        actor = current_context_user(actor)
        if (
            actor
            and getattr(actor, "is_authenticated", False)
            and getattr(actor, "key", None) is not None
        ):
            from ..tools import collaboration

            if not collaboration.recipient_allowed(
                cast("User", actor), assigned_user, channel="assign"
            ):
                raise ValidationError("Assigned user is not eligible for tasks.")

        if self.restricted_access(assigned_user):
            raise ValidationError(
                "Assigned user does not have access to this task's restricted form."
            )

    @property
    def has_converted_completion(self) -> bool:
        """Offer original answers only when a later generation changed this completion."""
        if not self.completed or not self.generation:
            return False
        original = completed_envelope(self)
        if original is None or (original.get("generation", 0) or 0) >= self.generation:
            return False
        # Compare stored representations: Python otherwise treats True and 1 as equal.
        return json.dumps(original["submission"], sort_keys=True) != json.dumps(
            self.properties.submission.value, sort_keys=True,
        )

    @property
    def history(self) -> list[TaskHistory]:
        return sorted(
            self.load_history(*database_get.task_history(self)),
            key=lambda h: (
                h.completed_on or datetime.min.replace(tzinfo=UTC),
                h.created or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=True,
        )

    def load_history(self, *records: Row | None) -> list[TaskHistory]:
        """Load snapshots with their live Task and current attachment owners."""
        rows = [record for record in records if record is not None]
        file_keys = {key for record in rows for key in record.get("files", [])}
        histories = [
            entity for entity in Entities.fetch(
                self, *rows, *file_keys,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if isinstance(entity, Entities.TASK_HISTORY)
        ]

        preload_definitions(histories)
        return histories

    def save_submission(self) -> None:
        super().save_submission()
        # derived_page_keys contains only internal Page/User-page link targets.
        self.linked_pages = cast("list[Page]", Entities.fetch(
            *self.derived_page_keys, request=Fetch.direct()
        ))

    def postpone(self, due_date: str) -> None:
        """Push the due date forward, preserving the original as postponed_from."""
        new_date = scheduling.calculate_postponed_due_date(due_date)
        if not self.postponed_from:
            self.db["postponed_from"] = self.due_date
        self.due_date = new_date

    @property
    def postponed_from(self) -> datetime | None:
        return cast("datetime | None", self.db.get("postponed_from"))

    def _check_required(self) -> list[SchemaField]:
        """Return visible required fields that have no value."""
        submission = self.properties.submission
        incomplete = [
            s for s in submission.fields.values() if s.required and not s.value
        ]
        if not incomplete:
            return []

        return [s for s in incomplete if submission.is_visible(s.id)]

    def complete(self, *, user: FieldUser = None, history_key: Key | None = None) -> None:
        if self.completed:
            return

        validate_completion_values(self)
        incomplete = self._check_required() if self.form else []
        if incomplete:
            titles = [s.label or s.id for s in incomplete]
            raise TaskCompletionError(
                "Required fields are incomplete: " + ", ".join(titles)
            )

        capture_completed_submission(self)
        self.db.pop("pre_migration", None)
        self.completed = True
        self.completed_on = datetime.now(UTC)
        self.completed_by = cast("User", user if user is not None else current_user)

        if self.schedule:
            if history_key is None:
                self._complete_active_schedule()
            else:
                self._complete_active_schedule(history_key=history_key)
        else:
            self.due_date = None

    def _complete_active_schedule(self, *, history_key: Key | None = None) -> None:
        self.properties.schedule.set_next_due_date()
        if history_key is None:
            scheduling.add_uncomplete_task_to_queue(self)
        else:
            scheduling.add_uncomplete_task_to_queue(self, history_key=history_key)

    def create_history_entry(
        self,
        completed_on: datetime | None = None,
        files: Iterable[File] | None = None,
        submission: dict[str, object] | None = None,
        name: str | None = None,
        description: str | None = None,
        form: Form | None = None,
        snapshot: bool = True,
        history_key: Key | None = None,
        source: Task | TaskHistory | None = None,
        submission_source: str = "original",
    ) -> TaskHistory:
        overrides: TaskHistoryOverrides = {}
        if history_key is not None:
            overrides["_key"] = history_key
        if completed_on is not None:
            overrides["completed_on"] = completed_on
        if files is not None:
            overrides["files"] = list(files or [])
        if submission is not None:
            overrides["submission"] = submission
        if name is not None:
            overrides["name"] = name
        if description is not None:
            overrides["description"] = description
        if form is not None:
            overrides["form"] = form
        if not snapshot and not overrides:
            overrides["copy_assets"] = False

        history = Entities.TASK_HISTORY.create(
            self, overrides or None, source=source,
            submission_source=submission_source,
        )
        self.add_mutation_intents(
            MutationIntent.standard(history, reason="task-history")
        )
        self.db["history"] = True
        return history

    def clear_submission_assets(self) -> None:
        for name in list(self.assets.keys()):
            asset = self.get_asset(name)
            if asset:
                self.add_mutation_intents(MutationIntent.delete_blob(
                    asset.path, asset.visibility.value, reason="reopened-submission-assets",
                ))
        self.assets.clear()
        self._assets = {}
        self.db.pop("assets", None)

    def uncomplete(self, history_key: Key | None = None, *, submission_source: str = "original") -> None:
        """Archive the selected answers and reset; automatic reopening keeps originals."""

        if submission_source not in ("original", "modified"):
            raise ValidationError("Choose the original or modified submission before reopening.")

        completed_cycle = immutable_submission(self)
        if completed_cycle:
            stage_completion_guards(self, transition="reopen")
            if submission_source == "modified" and not getattr(self, "_completion_transition", None):
                persisted = next(
                    expected for key, expected in self._completion_write_guards
                    if key == self.key
                )
                if persisted is not None and any(
                    persisted.get(name) != self.db.get(name)
                    for name in ("submission", "generation", "form", "assets")
                ):
                    raise ValidationError("The task changed before reopening. Reload and try again.")
        self._clear_scheduled_uncomplete()
        if completed_cycle:
            self.create_history_entry(
                history_key=history_key, submission_source=submission_source,
            )
            self._completion_transition = {
                "action": "reopen",
                "envelope": self.db.get("completed_submission"),
            }
        self.db.pop("completed_submission", None)
        self.db.pop("pre_migration", None)
        self.completed = False
        self._submission_definition = None
        self.completed_on = None
        self.completed_by = None
        self.due_date = None
        self.clear_submission_assets()
        submission = self.properties.submission
        submission._fields = None
        submission.value = {}
        self.db.pop("default_submission", None)
        if self.form:
            self.db["schema_version"] = self.form.version
            self.db["generation"] = self.form.generation
        else:
            self.db.pop("schema_version", None)
            self.db["generation"] = 0
        self.files = []

    @property
    def new_history_created(self) -> list[TaskHistory]:
        return [
            intent.entity
            for intent in self.mutation_intents
            if intent.intent is MutationIntentType.STANDARD
            and isinstance(intent.entity, Entities.TASK_HISTORY)
        ]

    @property
    def has_history(self) -> bool:
        return cast(bool, self.db.get("history", False))

    @classmethod
    def create(cls, data: TaskData, *, key: Key | None = None) -> Self:
        new_task = cls(key)
        new_task.kind = cls.entity_kind
        new_task.completed = False

        new_task.update(data)
        return new_task

    def _update_tracking(self, tracking: ModelTask | Project | None) -> None:
        if tracking and tracking.kind == "model":
            model = cast("ModelTask", tracking)
            self.model = model
            self.project = model.project
        elif tracking and tracking.kind == "project":
            self.project = cast("Project", tracking)
            self.model = None
        elif not tracking:
            self.project = None
            self.model = None

    def update(self, data: TaskData) -> None:
        if self.completed:
            raise ValidationError("Reopen the task before editing its completion.")
        previous_form_key = self.properties.form.key
        self.page = data.get("page", self.page)
        self.form = data.get("form")
        self.description = data.get("description")
        self.name = data.get("name")
        self.due_date = data.get("due_date")

        tracking = data.get("model") or data.get("project")
        self._update_tracking(tracking)
        form_changed = previous_form_key != self.properties.form.key

        previous_assignee_key = self.properties.assigned_to.key
        assigned_to = data.get("assigned_to")
        actor = current_context_user()
        next_assignee_key = getattr(assigned_to, "key", None)
        if previous_assignee_key != next_assignee_key:
            self.validate_assignment(assigned_to, actor=actor)
            self.assigned_to = assigned_to
            self.db["assignment_revision"] = (
                int(cast(int, self.db.get("assignment_revision") or 0)) + 1
            )
            if actor and getattr(actor, "page", None):
                self.assigned_by = actor.page
            self._add_assignment_notice(actor, self.assigned_to)
        elif form_changed and assigned_to:
            assigned_user = (
                assigned_to
                if isinstance(assigned_to, Entities.USER)
                else getattr(assigned_to, "user", None)
            )
            if assigned_user and self.restricted_access(assigned_user):
                raise ValidationError(
                    "Assigned user does not have access to this task's restricted form."
                )

        if "asset_files" in data:
            self.files = data.get("asset_files")

        if data.get("submission"):
            self.properties.submission.value = data.get("submission")

        self.updated = True

    def _add_assignment_notice(self, actor: FieldUser, assigned_page: Page | None) -> None:
        """Plan one stable notification for a non-self assignee transition."""
        recipient = getattr(assigned_page, "user", None) if assigned_page else None
        if (
            not recipient
            or not actor
            or not getattr(actor, "is_authenticated", False)
            or actor.key == recipient.key
        ):
            return
        import hashlib

        revision = int(cast(int, self.db.get("assignment_revision") or 0))
        identity = hashlib.sha256(
            f"{self.urlsafe_key}:{revision}:{recipient.urlsafe_key}".encode()
        ).hexdigest()
        notification = Entities.NOTIFICATION.create(
            {
                "identifier": f"task-assignment-{identity}",
                "parent": recipient,
                "target": self,
                "body": f"{actor.name} assigned you a task.",
                "event_type": "task_assignment",
                "sender_name": actor.name,
            }
        )
        self.add_mutation_intents(
            MutationIntent.standard(notification, reason="task-assignment-notice")
        )

    @property
    def task_list_owners(self) -> list[Page | Project]:
        owners = [self.page, self.project, self.assigned_to, *self.linked_pages]
        return [owner for owner in owners if owner]
