from copy import deepcopy
from datetime import datetime, timezone

from flask_login import current_user
from flask import url_for

from ..definitions import Action, Fetch, MutationIntent, MutationIntentType
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
from .entity import Entity
from . import Entities
from ..tools import database
from ..tools.tasks import scheduling
from ..tools.auth.context import current_context_user


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_entity_lifecycle_readonly_and_save_relations
# @features task
# @dimensions entity-lifecycle readonly save
class Task(AssetMixin, SubmitterMixin, Entity):
    entity_kind = "task"

    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "submission",
                "default_submission",
                "description",
                "assets",
                "schedule",
                "schema_version",
                "assignment_revision",
            }
        )

    @property
    def required(self):
        return self.page.required if self.page else []

    @property
    def url(self):
        return url_for("tasks.view", key=self.urlsafe_key)

    def _get_properties(self):
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
            }
        )
        return properties

    def is_assigned_to(self, user):
        return self.properties.assigned_to.key == user.page.key

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_allowed_assigned_user_page_override
    # @tests tests_unit/test_013_task_properties.py::test_task_allowed_skips_unloaded_page_when_stored_permission_suffices
    # @features task, permissions
    # @dimensions assignee-override, allowed
    def allowed(self, action, user=None):
        user = current_context_user(user)
        if self.restricted_access(user):
            return False

        if super().allowed(action, user=user):
            return True

        page_allowed = self.page.allowed(action, user=user) if self.page else False
        if page_allowed:
            return True

        user_page = getattr(user, "page", None)
        if user_page and self.properties.assigned_to.key == user_page.key:
            return Action.EDIT.implies(action)

        return False

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_update_rejects_assignee_without_restricted_task_access
    # @features task, permissions
    # @dimensions assignment restricted-access
    def validate_assignment(self, assigned_to, actor=None):
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
                actor, assigned_user, channel="assign"
            ):
                raise ValidationError("Assigned user is not eligible for tasks.")

        if self.restricted_access(assigned_user):
            raise ValidationError(
                "Assigned user does not have access to this task's restricted form."
            )

    @property
    def history(self):
        return sorted(
            Entities.fetch(*database.get.task_history(self), request=Fetch.direct()),
            key=lambda h: h.completed_on or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    def save_submission(self):
        super().save_submission()
        self.linked_pages = Entities.fetch(
            *self.derived_page_keys, request=Fetch.direct()
        )

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_postpone_preserves_original_due_date_once
    # @features task, task-scheduling
    # @dimensions postpone, due-date
    def postpone(self, due_date):
        """Push the due date forward, preserving the original as postponed_from."""
        new_date = scheduling.calculate_postponed_due_date(due_date)
        if not self.postponed_from:
            self.db["postponed_from"] = self.due_date
        self.due_date = new_date

    @property
    def postponed_from(self):
        return self.db.get("postponed_from")

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_raises_when_required_submission_missing
    # @features task-completion, submission
    # @dimensions required-fields, validation
    def _check_required(self):
        """Return visible required fields that have no value."""
        submission = self.properties.submission
        incomplete = [
            s for s in submission.fields.values() if s.required and not s.value
        ]
        if not incomplete:
            return []

        return [s for s in incomplete if submission.is_visible(s.id)]

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_without_schedule
    # @features task-completion
    # @dimensions complete, no-schedule, assignee, completed-by
    def complete(self):
        incomplete = self._check_required() if self.form else []
        if incomplete:
            titles = [s.label for s in incomplete]
            raise TaskCompletionError(
                "Required fields are incomplete: " + ", ".join(titles)
            )

        self.completed = True
        self.completed_on = datetime.now(timezone.utc)
        self.completed_by = current_user

        if self.schedule:
            self._complete_active_schedule()
        else:
            self.due_date = None

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_with_schedule_queues_uncomplete
    # @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_repeats_when_completed
    # @features task-scheduling
    # @dimensions complete, schedule-queue, next-due-date, recurring
    # @pairs task-scheduling:complete task-scheduling:schedule-queue
    # @pairs task-scheduling:next-due-date task-scheduling:recurring
    # @pair task-completion:next-due-date
    def _complete_active_schedule(self):
        self.properties.schedule.set_next_due_date()
        scheduling.add_uncomplete_task_to_queue(self)

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_uncomplete_after_complete
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_create_history_entry_accepts_completion_overrides
    # @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_records_older_completed_event_without_mutating_live_task
    # @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
    # @pairs task-completion:history task-completion:uncomplete
    # @pairs task-completion:explicit-overrides task-completion:name
    # @pairs task-completion:description task-completion:attachments
    # @pairs task-completion:submission task-completion:live-task
    # @pairs task-combine:source-snapshot
    def create_history_entry(
        self,
        completed_on=None,
        files=None,
        submission=None,
        name=None,
        description=None,
        form=None,
        snapshot=True,
        history_key=None,
        source=None,
    ):
        overrides = {}
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

        history = Entities.TASK_HISTORY.create(self, overrides or None, source=source)
        self.add_mutation_intents(
            MutationIntent.standard(history, reason="task-history")
        )
        self.db["history"] = True
        return history

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_uncomplete_after_complete
    # @features task-completion, signature
    # @dimensions uncomplete, asset-cleanup
    def clear_submission_assets(self):
        for name in list(self.assets.keys()):
            self.delete_asset(name)

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_uncomplete_after_complete
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_uncomplete_restores_default_submission_and_assignment
    # @tests tests_unit/test_003g_todo_lists.py::test_uncomplete_archives_then_clears_todo_items
    # @pairs task-completion:uncomplete task-completion:history
    # @pairs task-completion:repeating-default task-completion:assignment
    # @pair form-todo:field-reset
    def uncomplete(self, history_key=None):
        """Archive the current completion as TaskHistory and reset the task."""
        if self.completed:
            if history_key is None:
                self.create_history_entry()
            else:
                self.create_history_entry(history_key=history_key)
        self.completed = False
        self.completed_on = None
        self.completed_by = None
        self.due_date = None
        self.clear_submission_assets()
        submission = self.properties.submission
        fields = submission.fields
        defaults = {
            field_id: value
            for field_id, value in self.default_submission.items()
            if field_id not in fields
            or getattr(fields[field_id], "restore_on_uncomplete", True)
        }
        self._set_default_submission(defaults)
        submission._fields = None
        submission.value = deepcopy(defaults)
        self.files = []

    @property
    def new_history_created(self):
        return [
            intent.entity
            for intent in self.mutation_intents
            if intent.intent is MutationIntentType.STANDARD
            and isinstance(intent.entity, Entities.TASK_HISTORY)
        ]

    @property
    def has_history(self):
        return self.db.get("history", False)

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_entity_lifecycle_readonly_and_save_relations
    # @features task
    # @dimensions create
    @classmethod
    def create(cls, data):
        new_task = cls()
        new_task.kind = cls.entity_kind
        new_task.completed = False

        new_task.update(data)
        return new_task

    def _update_tracking(self, tracking):
        if tracking and tracking.kind == "model":
            self.model = tracking
            self.project = tracking.project
        elif tracking and tracking.kind == "project":
            self.project = tracking
            self.model = None
        elif not tracking:
            self.project = None
            self.model = None

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_update_tracks_project_model_and_uploaded_file
    # @tests tests_unit/test_013_task_properties.py::test_task_update_saves_file_relations_from_upload_assets
    # @features task
    # @dimensions update, tracking, uploaded-files
    def update(self, data):
        self.page = data.get("page", self.page)
        self.form = data.get("form")
        self.description = data.get("description")
        self.name = data.get("name")
        self.due_date = data.get("due_date")

        tracking = data.get("model") or data.get("project")
        self._update_tracking(tracking)

        previous_assignee_key = self.properties.assigned_to.key
        assigned_to = data.get("assigned_to")
        actor = current_context_user()
        self.validate_assignment(assigned_to, actor=actor)
        self.assigned_to = assigned_to
        next_assignee_key = self.properties.assigned_to.key
        if previous_assignee_key != next_assignee_key:
            self.db["assignment_revision"] = (
                int(self.db.get("assignment_revision") or 0) + 1
            )
            if actor and getattr(actor, "page", None):
                self.assigned_by = actor.page
            self._add_assignment_notice(actor, self.assigned_to)

        if "asset_files" in data:
            self.files = data.get("asset_files")

        if data.get("submission"):
            self.properties.submission.value = data.get("submission")

        self.updated = True

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_task_assignment_notice_uses_stable_transition_identity
    # @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_assigned_to
    # @pairs task-assignment:transition task-assignment:idempotency task-assignment:self-exclusion
    # @pair notifications:assignee-target
    def _add_assignment_notice(self, actor, assigned_page):
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

        revision = int(self.db.get("assignment_revision") or 0)
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

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_entity_lifecycle_readonly_and_save_relations
    # @features task
    # @dimensions list-owner-fingerprint
    @property
    def task_list_owners(self):
        owners = [self.page, self.project, self.assigned_to, *self.linked_pages]
        return [owner for owner in owners if owner]
