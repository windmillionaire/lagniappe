"""Kind-specific save planners."""
from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

from lagniappe.core.tools.forms.definitions import validate_completion_write

from ..definitions import Fetch, FetchReason
from .base import MutationPlanBuilder, StandardMutation

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..entities.entity import Entity
    from ..entities.types import (
        AIReport,
        Category,
        DeferredJob,
        File,
        Filter,
        Form,
        ModelTask,
        Note,
        Notification,
        Page,
        Task,
        TaskHistory,
        User,
    )


# @testable infrastructure
class PageMutation(StandardMutation["Page"]):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_permission_save_reuses_resolved_collection_owner_keys
    # @matrix permissions mutations : owner-reuse no-extra-read repeated-save
    def plan_save(
        self,
        entity: Page,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        entity.properties.restricted_to.materialize()
        user = entity.user
        if user:
            builder.registry.fetch(user, request=Fetch.direct())

        super().plan_save(
            entity,
            builder,
            reason=reason,
            # Page.required includes its user's current requirements. When both
            # are writes in one plan, prepare the user before deriving the page.
            depends_on=(*depends_on, user) if user else depends_on,
        )
        owners = entity.page_list_owners
        entity._restriction_owner_keys = tuple(sorted({
            owner.urlsafe_key for owner in owners
            if owner.entity_kind in {"category", "project"}
        }))
        for owner in owners:
            builder.touch(owner, reason="page-list-owner")
        if entity.is_public:
            builder.invalidate_public_discovery(reason="public-page-save")


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_category_save_plans_public_discovery_invalidation
# @matrix categories public-directory : invalidation save
class CategoryMutation(StandardMutation["Category"]):
    # @testable infrastructure
    def plan_save(
        self,
        entity: Category,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        builder.invalidate_public_discovery(reason="category-save")


# @testable infrastructure
class TaskMutation(StandardMutation["Task"]):
    # @testable true
    # @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_task_move_updates_all_owned_file_search_permissions
    # @tests tests_unit/test_006_file_properties.py::test_task_move_updates_history_only_file_page_without_consuming_pending_move
    # @matrix permissions search files : task-move ancestor-tags
    # @matrix files : ownership history parent-key retry
    def plan_save(
        self,
        entity: Task,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:

        persisted = builder.registry.fetch_one(entity.key, request=Fetch.root())
        validate_completion_write(entity, persisted.db if persisted is not None else None)
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        if getattr(entity, "_page_changed", False) and not getattr(entity, "_testing", False):
            from ..tools.database import get as database_get
            for stored_file in builder.registry.fetch(*database_get.task_files(entity.key), request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)):
                file = cast("File", stored_file)
                file.properties.task.attach({cast("Key", entity.key): entity})
                file.normalize_owner()
                builder.patch(file, "task_page", "requires", property_updates=("requires", "modified"),
                              reason="task-file-ancestry", depends_on=(entity,))
        for owner in entity.task_list_owners:
            builder.touch(owner, reason="task-list-owner")


# @testable infrastructure
class TaskHistoryMutation(StandardMutation["TaskHistory"]):
    # @testable infrastructure
    def plan_save(
        self,
        entity: TaskHistory,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:

        persisted = builder.registry.fetch_one(entity.key, request=Fetch.root())
        validate_completion_write(entity, persisted.db if persisted is not None else None)
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
class UserMutation(StandardMutation["User"]):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_existing_user_save_does_not_implicitly_mutate_canonical_page
    # @matrix mutations user : canonical-page intent-isolation save
    def plan_save(
        self,
        entity: User,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        # A newly assigned canonical page is an explicit STANDARD intent from
        # UserPage. Ordinary permission/profile saves do not mutate that page.
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )


# @testable infrastructure
class FormMutation(StandardMutation["Form"]):
    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_save_refreshes_content_version_without_archiving_compatible_edits
    # @tests tests_unit/test_022_mutation_contracts.py::test_permission_save_reuses_resolved_collection_owner_keys
    # @matrix permissions mutations : owner-reuse no-extra-read repeated-save
    # @matrix form : relations save content-fingerprint generation
    # @matrix forms mutations : guarded-save publication
    def plan_save(
        self,
        entity: Form,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        entity.properties.restricted_to.materialize()
        from lagniappe.core.tools.forms.drafts import prepare_form_publication

        prepare_form_publication(entity, builder)

        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        owners = [*cast("Iterable[Entity]", entity.groups), *entity.used_by]
        entity._restriction_owner_keys = tuple(sorted({
            owner.urlsafe_key for owner in owners
            if owner.entity_kind in {"category", "project"}
        }))
        for owner in owners:
            builder.touch(owner, reason="form-user-invalidation")


# @testable infrastructure
class FileMutation(StandardMutation["File"]):
    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_save_normalizes_task_page_and_restriction_fingerprint
    # @matrix files : ownership parent-key fingerprint restrictions
    def plan_save(
        self,
        entity: File,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        entity.normalize_owner()
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=(*depends_on, entity.owner) if entity.owner else depends_on,
        )
        if entity.owner:
            builder.touch(entity.owner, reason="file-owner")
            if entity.owner.entity_kind == "task":
                builder.touch(cast("Task", entity.owner).page, reason="file-task-page-owner")


# @testable infrastructure
class ModelMutation(StandardMutation["ModelTask"]):
    # @testable infrastructure
    def plan_save(
        self,
        entity: ModelTask,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
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
class FilterMutation(StandardMutation["Filter"]):
    # @testable infrastructure
    def plan_save(
        self,
        entity: Filter,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        if entity.parent:
            builder.touch(entity.parent, reason="filter-parent-owner")


# @testable infrastructure
class ReportMutation(StandardMutation["AIReport"]):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_report_save_does_not_touch_input_files
    # @matrix ai-report mutations : input-files no-database-read owner-touch
    def plan_save(
        self,
        entity: AIReport,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        owners = cast("tuple[Entity | None, Entity | None]", (entity.parent, entity.user))
        for owner in owners:
            if owner:
                builder.touch(owner, reason="report-list-owner")


# @testable true
# @tests tests_unit/test_002j_notes.py::test_note_save_touches_parent_and_author
# @matrix mutations notes : save owner-invalidation
class NoteMutation(StandardMutation["Note"]):
    # @testable infrastructure
    def plan_save(
        self,
        entity: Note,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        for owner in cast("tuple[Entity | None, Entity | None]", (entity.parent, entity.user)):
            if owner:
                builder.touch(owner, refresh_cache=False, reason="note-list-owner")
                builder.cache_invalidate(owner, reason="note-list-owner")


# @testable infrastructure
class NotificationMutation(StandardMutation["Notification"]):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_notification_save_updates_projection_without_touching_user
    # @matrix notifications : cache-failure-isolation cache-isolation mutation personal-activity
    def plan_save(
        self,
        entity: Notification,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
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
class JobMutation(StandardMutation["DeferredJob"]):
    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_job_save_updates_operation_projection_without_touching_relations
    # @matrix deferred-jobs : cache-isolation mutation redis-projection
    def plan_save(
        self,
        entity: DeferredJob,
        builder: MutationPlanBuilder,
        *,
        reason: str,
        depends_on: Iterable[Entity] = (),
    ) -> None:
        super().plan_save(
            entity,
            builder,
            reason=reason,
            depends_on=depends_on,
        )
        builder.operation_upsert(entity, reason="job-operation-state")
