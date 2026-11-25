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


class PageMutation(StandardMutation["Page"]):
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


class CategoryMutation(StandardMutation["Category"]):
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


class TaskMutation(StandardMutation["Task"]):
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


class TaskHistoryMutation(StandardMutation["TaskHistory"]):
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


class UserMutation(StandardMutation["User"]):
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


class FormMutation(StandardMutation["Form"]):
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


class FileMutation(StandardMutation["File"]):
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


class ModelMutation(StandardMutation["ModelTask"]):
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


class FilterMutation(StandardMutation["Filter"]):
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


class ReportMutation(StandardMutation["AIReport"]):
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


class NoteMutation(StandardMutation["Note"]):
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


class NotificationMutation(StandardMutation["Notification"]):
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


class JobMutation(StandardMutation["DeferredJob"]):
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
