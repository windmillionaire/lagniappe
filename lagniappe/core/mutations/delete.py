"""Kind-routed delete cascades and property-masked survivor repairs."""
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import messaging as database_messaging
from lagniappe.core.tools.database.utility import ExactEntityState

from ..definitions import (
    Fetch,
    FetchReason,
    MutationEffectType,
    MutationOperation,
    Restriction,
)
from .base import MutationPlanBuilder
from .registry import planner_for

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..definitions import MutationPlan
    from ..entities import EntityRegistry
    from ..entities.entity import Entity
    from ..entities.types import (
        Category,
        File,
        Form,
        MessageConversation,
        ModelTask,
        Note,
        Page,
        Project,
        Task,
        TaskHistory,
        User,
    )
    from ..mixins.related import RelatedEntityListMixin
    from ..properties.page_related import PageUser


@dataclass
class Survivor:
    entity: Entity
    properties: set[str] = field(default_factory=set)
    property_updates: set[str] = field(default_factory=lambda: {"modified"})
    reasons: set[str] = field(default_factory=set)
    refresh_cache: bool = True


class DeleteCollector:
    def __init__(
        self, registry: EntityRegistry, *, preserve_user_pages: bool = False
    ) -> None:
        self.entities = registry
        self.preserve_user_pages = preserve_user_pages
        self.to_delete: list[Entity] = []
        self.survivors: list[Survivor] = []
        self.search_deletes: list[tuple[str, Entity]] = []
        self._message_conversations: dict[Key | None, MessageConversation] = {}
        self._message_users: set[Key | None] = set()

    def delete(self, entity: Entity | None) -> None:
        if entity:
            self.to_delete.append(entity)

    def repair(
        self,
        entity: Entity | None,
        *properties: str,
        property_updates: Iterable[str] = ("modified",),
        refresh_cache: bool = True,
        reason: str,
    ) -> None:
        if entity:
            self.survivors.append(
                Survivor(
                    entity,
                    set(properties),
                    set(property_updates),
                    {reason},
                    refresh_cache,
                )
            )

    def preserve_user_page(self, user: User, page: Page) -> None:
        users_model = (
            page.model if isinstance(page.model, self.entities.USERS) else None
        )

        page.user = None
        if users_model:
            page.properties.categories.remove(users_model)

        self.delete(user)
        self.repair(
            page,
            "categories",
            "model",
            "requires",
            "user",
            property_updates=("requires", "modified"),
            reason="user-delete-page-preservation",
        )
        self.repair(users_model, reason="user-delete-page-preservation")
        self.search_deletes.append(("user", page))

    def _page_user(self, page: Page) -> User | None:
        user_relation = cast("PageUser | None", page.properties.get("user"))
        if not user_relation:
            return None
        user = user_relation.value if user_relation.is_set else None
        if user:
            return cast("User", user)
        user_key = user_relation.key
        return (
            cast("User | None", self.entities.fetch_one(user_key, request=Fetch.direct()))
            if user_key
            else None
        )

    def page(self, page: Page, *, force: bool = False) -> None:
        if force or not page.categories:
            self.page_notes(page)
            page_user = self._page_user(page)
            self.user_messages(page_user)
            self.delete(page_user)
            self.delete(page)
            self.page_tasks(page)
            self.page_files(page)
        else:
            self.repair(
                page,
                "categories",
                "model",
                "requires",
                property_updates=("requires", "modified"),
                reason="category-delete-page-unlink",
            )

    def page_files(self, page: Page) -> None:
        files = [
            entity
            for entity in self.entities.fetch(
                *database_get.page_files(page.key),
                request=Fetch.direct(),
            )
            if isinstance(entity, self.entities.FILE)
        ]
        for file in files:
            self.delete(file)
            self.file_tasks(file)

    def page_tasks(self, page: Page) -> None:
        tasks = [
            entity
            for entity in self.entities.fetch(
                *database_get.page_tasks_with_history(page),
                request=Fetch.direct(),
            )
            if isinstance(entity, (self.entities.TASK, self.entities.TASK_HISTORY))
        ]
        for task in tasks:
            self.delete(task)
            self.task_files(task)

    def task_files(self, task: Task | TaskHistory) -> None:
        if task.entity_kind == "task_history":
            return
        for file in self.entities.fetch(*database_get.task_files(task.key), request=Fetch.direct()):
            self.delete(file)
            self.file_tasks(cast("File", file))

    def file_tasks(self, file: File) -> None:
        tasks = [
            entity
            for entity in self.entities.fetch(
                *database_get.file_references(file.key),
                request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
            )
            if isinstance(entity, (self.entities.TASK, self.entities.TASK_HISTORY))
        ]
        for task in tasks:
            if not task.properties.files.remove(file):
                continue

            is_history = isinstance(task, self.entities.TASK_HISTORY)
            self.repair(
                task,
                "files",
                property_updates=() if is_history else ("modified",),
                reason="file-delete-task-unlink",
            )
            owners = (
                [task.task, task.page, *task.linked_pages]
                if isinstance(task, self.entities.TASK_HISTORY)
                else cast("Task", task).task_list_owners
            )
            for owner in owners:
                self.repair(owner, reason="file-delete-task-list-owner")

    def task_owners(self, task: Task | TaskHistory) -> None:
        owners = getattr(task, "task_list_owners", None)
        if owners is None:
            owners = []
            for name in ("page", "project", "assigned_to"):
                if task.properties.get(name):
                    owner = getattr(task, name, None)
                    if owner:
                        owners.append(owner)
            if task.properties.get("linked_pages"):
                owners.extend(page for page in task.linked_pages if page)
        for owner in owners:
            self.repair(owner, reason="task-delete-list-owner")

    def note(self, note: Note) -> None:
        self.delete(note)
        owners = {
            owner.key: owner
            for owner in cast("tuple[Entity | None, Entity | None]", (note.parent, note.user))
            if owner
        }
        for owner in owners.values():
            self.repair(owner, refresh_cache=False, reason="note-delete-list-owner")

    def page_notes(self, page: Page) -> None:
        notes = self.entities.fetch(
            *database_get.page_notes(page),
            request=Fetch.direct(),
        )
        for note in notes:
            if isinstance(note, self.entities.NOTE):
                self.note(note)

    def user_notes(self, user: User) -> None:
        notes = self.entities.fetch(
            *database_get.notes_by_user(user),
            request=Fetch.direct(),
        )
        for note in notes:
            if isinstance(note, self.entities.NOTE):
                self.note(note)

    def user_messages(self, user: User | None) -> None:
        if not user or user.key in self._message_users:
            return
        self._message_users.add(user.key)
        conversations = self.entities.fetch(
            *database_messaging.message_conversation_keys(user),
            request=Fetch.direct(),
        )
        for conversation in conversations:
            if isinstance(conversation, self.entities.MESSAGE_CONVERSATION):
                self._message_conversations[conversation.key] = conversation

    def finalize_message_conversations(self) -> None:
        deleting_users = {
            entity.key
            for entity in self.to_delete
            if isinstance(entity, self.entities.USER)
        }
        for conversation in self._message_conversations.values():
            participants = set(cast("Iterable[Key]", conversation.db.get("participants") or ()))
            existing_users = {
                entity.key
                for entity in self.entities.fetch(
                    *participants,
                    request=Fetch.direct(),
                )
                if isinstance(entity, self.entities.USER)
            }
            survivors = existing_users - deleting_users
            if survivors:
                conversation.db["visible_to"] = [
                    key
                    for key in cast("Iterable[Key]", conversation.db.get("visible_to") or ())
                    if key in survivors
                ]
                self.repair(
                    conversation,
                    "visible_to",
                    reason="user-delete-message-history-preservation",
                )
                continue

            self.delete(conversation)
            for message_key in database_messaging.message_keys(conversation):
                self.delete(self.entities.MESSAGE(message_key))

    def project_models(self, project: Project) -> None:
        models = list(project.model_tasks)
        for model in models:
            self.delete(model)
        for form in self.model_forms(*models):
            self.delete(form)

    def model_forms(self, *models: ModelTask) -> list[Form]:
        forms = {model.form.key: model.form for model in models if model.form}
        model_keys = {model.key for model in models}
        form_users = list(database_get.form_users(*forms.values()))
        used_by = {
            form_key: [
                model.key for model in form_users if model.get("form") == form_key
            ]
            for form_key in forms
        }
        return [
            form
            for form_key, form in forms.items()
            if set(used_by[form_key]) == model_keys
        ]

    def filters(self, entity: Entity) -> None:
        for filter_key in database_get.filters(entity):
            self.delete(self.entities.FILTER(filter_key))

    def category_pages(self, category: Category) -> None:
        if category.key is None:
            return
        pages_in_category = database_get.pages(
            category.key,
            limit=None,
            hashes=Restriction.UNRESTRICTED,
        ).results
        entities = [*pages_in_category, category]
        pages = [
            page
            for page in self.entities.fetch(*entities, request=Fetch.direct())
            if isinstance(page, self.entities.PAGE)
        ]
        for page in pages:
            if any(owner.key != category.key for owner in page.categories):
                page.properties.categories.remove(category)
                self.page(page)
            else:
                self.page(page, force=True)

    def collect(self, entity: Entity) -> None:
        delete_planner_for(entity).collect(entity, self)


class StandardDeleteMutation[Target: Entity = Entity]:
    def collect(self, entity: Target, collector: DeleteCollector) -> None:
        collector.delete(entity)


class PageDeleteMutation(StandardDeleteMutation["Page"]):
    def collect(self, entity: Page, collector: DeleteCollector) -> None:
        collector.page(entity, force=True)


class UserDeleteMutation(StandardDeleteMutation["User"]):
    def collect(self, entity: User, collector: DeleteCollector) -> None:
        collector.user_notes(entity)
        collector.user_messages(entity)
        if entity.properties.page.exists:
            if collector.preserve_user_pages:
                collector.preserve_user_page(entity, entity.page)
            else:
                collector.page(entity.page, force=True)
        else:
            collector.delete(entity)


class TaskDeleteMutation(StandardDeleteMutation["Task | TaskHistory"]):
    def collect(self, entity: Task | TaskHistory, collector: DeleteCollector) -> None:
        collector.delete(entity)
        collector.task_owners(entity)
        collector.task_files(entity)
        if entity.entity_kind == "task":
            for history in collector.entities.fetch(*database_get.task_history(entity), request=Fetch.direct()):
                collector.delete(history)


class FileDeleteMutation(StandardDeleteMutation["File"]):
    def collect(self, entity: File, collector: DeleteCollector) -> None:
        collector.delete(entity)
        collector.file_tasks(entity)
        if entity.owner:
            collector.repair(entity.owner, reason="file-delete-owner")


class NoteDeleteMutation(StandardDeleteMutation["Note"]):
    def collect(self, entity: Note, collector: DeleteCollector) -> None:
        collector.note(entity)


class ProjectDeleteMutation(StandardDeleteMutation["Project"]):
    def collect(self, entity: Project, collector: DeleteCollector) -> None:
        collector.delete(entity)
        collector.filters(entity)
        collector.project_models(entity)


class ModelDeleteMutation(StandardDeleteMutation["ModelTask"]):
    def collect(self, entity: ModelTask, collector: DeleteCollector) -> None:
        collector.delete(entity)
        for form in collector.model_forms(entity):
            collector.delete(form)


class FormDeleteMutation(StandardDeleteMutation["Form"]):
    def collect(self, entity: Form, collector: DeleteCollector) -> None:
        collector.delete(entity)
        for owner in entity.used_by:
            collector.repair(owner, reason="form-delete-user-invalidation")


class CategoryDeleteMutation(StandardDeleteMutation["Category"]):
    def collect(self, entity: Category, collector: DeleteCollector) -> None:
        collector.delete(entity)
        collector.filters(entity)
        collector.category_pages(entity)


STANDARD_DELETE = StandardDeleteMutation()
DELETE_PLANNERS = {
    "user": UserDeleteMutation(),
    "project": ProjectDeleteMutation(),
    "model": ModelDeleteMutation(),
    "file": FileDeleteMutation(),
    "ingress": STANDARD_DELETE,
    "form": FormDeleteMutation(),
    "category": CategoryDeleteMutation(),
    "users": CategoryDeleteMutation(),
    "page": PageDeleteMutation(),
    "task": TaskDeleteMutation(),
    "group": STANDARD_DELETE,
    "public_group": STANDARD_DELETE,
    "filter": STANDARD_DELETE,
    "task_history": TaskDeleteMutation(),
    "notification": STANDARD_DELETE,
    "note": NoteDeleteMutation(),
    "form_history": STANDARD_DELETE,
    "document_history": STANDARD_DELETE,
    "job": STANDARD_DELETE,
    "job_lock": STANDARD_DELETE,
    "report": STANDARD_DELETE,
    "message_conversation": STANDARD_DELETE,
    "message": STANDARD_DELETE,
    "mention_marker": STANDARD_DELETE,
}


def delete_planner_for(entity: Entity) -> StandardDeleteMutation[Entity]:
    kind = getattr(entity, "entity_kind", None) or getattr(entity, "kind", None)
    try:
        return cast("StandardDeleteMutation[Entity]", DELETE_PLANNERS[cast(str, kind)])
    except KeyError as error:
        raise ValueError(f"No delete planner registered for kind: {kind}") from error


def _unique_entities(entities: Iterable[Entity]) -> list[Entity]:
    unique = {}
    for entity in entities:
        key = getattr(entity, "key", None)
        if key:
            unique[key] = entity
    return list(unique.values())


def _merge_survivors(survivors: Iterable[Survivor]) -> list[Survivor]:
    grouped = {}
    for survivor in survivors:
        key = getattr(survivor.entity, "key", None)
        if key:
            grouped.setdefault(key, []).append(survivor)

    merged = []
    relation_lists = {
        "categories",
        "files",
        "forms",
        "groups",
        "linked_pages",
        "pages",
        "tasks",
    }
    for copies in grouped.values():
        canonical = copies[0].entity
        properties = set().union(*(copy.properties for copy in copies))
        property_updates = set().union(*(copy.property_updates for copy in copies))
        reasons = set().union(*(copy.reasons for copy in copies))
        for property_name in relation_lists & properties:
            values = [
                list(getattr(copy.entity, "db", {}).get(property_name) or [])
                for copy in copies
                if property_name in getattr(copy.entity, "db", {})
                or any(
                    property_name in getattr(other.entity, "db", {})
                    for other in copies
                )
            ]
            if not values:
                continue
            kept = set(values[0])
            for value in values[1:]:
                kept.intersection_update(value)
            ordered = [value for value in values[0] if value in kept]
            if ordered:
                canonical.db[property_name] = ordered
            else:
                canonical.db.pop(property_name, None)

            relation = cast("RelatedEntityListMixin[Entity] | None", canonical.properties.get(property_name))
            if relation is not None and relation.is_set:
                attached = {
                    getattr(item, "key", None): item
                    for copy in copies
                    for item in (getattr(copy.entity, property_name, None) or [])
                    if getattr(item, "key", None) in kept
                }
                relation.value = [attached[key] for key in ordered if key in attached]
        merged.append(Survivor(
            canonical, properties, property_updates, reasons,
            any(copy.refresh_cache for copy in copies),
        ))
    return merged


def plan_delete(
    *entities: Entity, registry: EntityRegistry, preserve_user_pages: bool = False
) -> MutationPlan:
    entities = tuple(entity for entity in entities if entity)
    builder = MutationPlanBuilder(
        MutationOperation.DELETE,
        entities,
        registry=registry,
        planner_for=planner_for,
    )
    collector = DeleteCollector(
        registry,
        preserve_user_pages=preserve_user_pages,
    )
    for entity in entities:
        collector.collect(entity)
    collector.finalize_message_conversations()

    deleted = _unique_entities(collector.to_delete)
    delete_keys = {entity.key for entity in deleted}
    survivors = [
        survivor
        for survivor in _merge_survivors(collector.survivors)
        if survivor.entity.key not in delete_keys
    ]

    for survivor in survivors:
        builder.patch(
            survivor.entity,
            *sorted(survivor.properties),
            property_updates=tuple(sorted(survivor.property_updates)),
            reason="+".join(sorted(survivor.reasons)),
            effect=MutationEffectType.UNLINK,
            refresh_cache=survivor.refresh_cache,
        )
        if not survivor.refresh_cache:
            builder.cache_invalidate(survivor.entity, reason="modified-owner")
    for kind, entity in collector.search_deletes:
        builder.delete_from_search(
            kind,
            entity,
            reason="user-delete-page-preservation",
        )
    for entity in deleted:
        kind = getattr(entity, "entity_kind", None)
        if kind == "form":
            # Preserve the last generation at the explicit delete boundary,
            # including Forms that never needed a submission transfer.
            from lagniappe.core.tools.forms.drafts import archive_form_generation

            source = registry.fetch_one(entity.key, request=Fetch.root())
            if source is not None:
                history = archive_form_generation(cast("Form", source))
                history._form_save_guard = (source.key, ExactEntityState(dict(source.db)))
                builder.plan_standard(history, reason="deleted-form-generation")
        builder.delete(entity, reason="delete-cascade")
        if kind == "page" and getattr(entity, "is_public", False):
            builder.invalidate_public_discovery(reason="public-page-delete")
        elif kind == "category":
            builder.invalidate_public_discovery(reason="category-delete")
        if getattr(entity, "entity_kind", None) == "notification":
            entity._notification_count_delta = (
                -1 if entity.notification_type == "ordinary" else 0
            )
            if entity.notification_type == "ordinary":
                builder.notification_delete(
                    entity,
                    reason="notification-delete",
                )
        if getattr(entity, "entity_kind", None) == "job":
            builder.operation_delete(
                entity,
                reason="operation-delete",
            )
        for asset in getattr(entity, "assets", {}).values():
            builder.delete_blob(
                asset.get("path"),
                asset.get("visibility", "private"),
                reason="delete-asset",
            )
    return builder.build()
