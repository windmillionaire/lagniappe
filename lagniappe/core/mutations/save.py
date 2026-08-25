"""Kind-specific save planners."""

from ..definitions import Fetch
from .base import StandardMutation


# @testable infrastructure
class PageMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        user = entity.user
        if user:
            builder.entities.fetch(user, request=Fetch.direct())

        super().plan_save(
            entity,
            builder,
            reason=reason,
            # Page.required includes its user's current requirements. When both
            # are writes in one plan, prepare the user before deriving the page.
            depends_on=(*depends_on, user) if user else depends_on,
        )
        for owner in entity.page_list_owners:
            builder.touch(owner, reason="page-list-owner")


# @testable infrastructure
class TaskMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        for owner in entity.task_list_owners:
            builder.touch(owner, reason="task-list-owner")


# @testable infrastructure
class TaskHistoryMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        owners = [entity.page, *entity.linked_pages]
        for owner in owners:
            if owner:
                builder.touch(owner, reason="task-history-list-owner")


# @testable infrastructure
class UserMutation(StandardMutation):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_existing_user_save_does_not_implicitly_mutate_canonical_page
    # @matrix mutations user : canonical-page intent-isolation save
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        # A newly assigned canonical page is an explicit STANDARD intent from
        # UserPage. Ordinary permission/profile saves do not mutate that page.
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )


# @testable infrastructure
class FormMutation(StandardMutation):
    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_save_records_schema_history_on_version_change
    # @matrix form : relations save schema-history
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        previous_version = entity.version
        entity.properties.version.update()
        if previous_version != entity.version and entity.properties.schema.previous:
            history = builder.entities.FORM_HISTORY.create(entity, previous_version)
            builder.plan_standard(history, reason="form-schema-history")

        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        owners = [*entity.groups, *entity.used_by]
        for owner in owners:
            builder.touch(owner, reason="form-user-invalidation")


# @testable infrastructure
class FileMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        for page in entity.pages:
            builder.touch(page, reason="file-page-owner")


# @testable infrastructure
class ModelMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        if entity.project:
            builder.touch(entity.project, reason="model-project-owner")
        if entity.form:
            builder.touch(entity.form, reason="model-form-user")


# @testable infrastructure
class FilterMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        if entity.parent:
            builder.touch(entity.parent, reason="filter-parent-owner")


# @testable infrastructure
class ReportMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        owners = [entity.parent, entity.user, *entity.input_files]
        for owner in owners:
            if owner:
                builder.touch(owner, reason="report-list-owner")


# @testable infrastructure
class NoteMutation(StandardMutation):
    # @testable infrastructure
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        for owner in (entity.parent, entity.user):
            if owner:
                builder.touch(owner, reason="note-list-owner")


# @testable infrastructure
class NotificationMutation(StandardMutation):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_notification_save_updates_projection_without_touching_user
    # @matrix notifications : cache-failure-isolation cache-isolation mutation personal-activity
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        entity._notification_count_delta = (
            1
            if not entity.created and entity.notification_type == "ordinary"
            else 0
        )
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        if entity.parent and entity.notification_type == "ordinary":
            builder.notification_upsert(
                entity,
                reason="notification-list-owner",
            )


# @testable infrastructure
class JobMutation(StandardMutation):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_job_save_updates_operation_projection_without_touching_relations
    # @matrix deferred-jobs : cache-isolation mutation redis-projection
    def plan_save(self, entity, builder, *, reason, depends_on=()):
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        builder.operation_upsert(entity, reason="job-operation-state")
