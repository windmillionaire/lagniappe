"""Kind-routed delete cascades and property-masked survivor repairs."""

from dataclasses import dataclass, field

from ..definitions import Fetch, MutationEffectType, MutationOperation, Restriction
from ..tools import database
from .base import MutationPlanBuilder


# @testable infrastructure
@dataclass
class Survivor:
    entity: object
    properties: set[str] = field(default_factory=set)
    property_updates: set[str] = field(default_factory=lambda: {"modified"})
    reasons: set[str] = field(default_factory=set)


# @testable infrastructure
class DeleteCollector:
    # @testable infrastructure
    def __init__(self, registry, *, preserve_user_pages=False):
        self.entities = registry
        self.preserve_user_pages = preserve_user_pages
        self.to_delete = []
        self.survivors = []
        self.search_deletes = []
        self._message_conversations = {}
        self._message_users = set()

    # @testable infrastructure
    def delete(self, entity):
        if entity:
            self.to_delete.append(entity)

    # @testable infrastructure
    def repair(
        self,
        entity,
        *properties,
        property_updates=("modified",),
        reason,
    ):
        if entity:
            self.survivors.append(
                Survivor(
                    entity,
                    set(properties),
                    set(property_updates),
                    {reason},
                )
            )

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_collect_user_delete_can_preserve_page
    # @tests tests_e2e/008_users/test_008a_user_index.py::test_delete_user_can_preserve_page
    # @pairs entities:delete entities:preserve-page entities:user-unlink
    # @pairs entities:category-fallback entities:search-cache users:delete
    # @pairs users:preserve-page users:user-unlink users:category-fallback
    # @pairs users:search-cache pages:delete pages:preserve-page
    # @pairs pages:user-unlink pages:category-fallback pages:search-cache
    def preserve_user_page(self, user, page):
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

    # @testable infrastructure
    def _page_user(self, page):
        user_relation = page.properties.get("user")
        if not user_relation:
            return None
        user = user_relation.value if user_relation.is_set else None
        if user:
            return user
        user_key = user_relation.key
        return (
            self.entities.fetch_one(user_key, request=Fetch.direct())
            if user_key
            else None
        )

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_collect_entities_deletes_user_and_page_together
    # @features entities
    # @dimensions delete cascade user-page
    def page(self, page, *, force=False):
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
                "requires",
                property_updates=("requires", "modified"),
                reason="category-delete-page-unlink",
            )

    # @testable infrastructure
    def page_files(self, page):
        files = [
            entity
            for entity in self.entities.fetch(
                *database.get.page_files(page.key),
                request=Fetch.direct(),
            )
            if isinstance(entity, self.entities.FILE)
        ]
        for file in files:
            file.properties.pages.remove(page)
            if not file.pages:
                self.delete(file)
            else:
                self.repair(
                    file,
                    "pages",
                    "requires",
                    property_updates=("requires", "modified"),
                    reason="page-delete-file-unlink",
                )

    # @testable infrastructure
    def page_tasks(self, page):
        tasks = [
            entity
            for entity in self.entities.fetch(
                *database.get.page_tasks_with_history(page),
                request=Fetch.direct(),
            )
            if isinstance(entity, (self.entities.TASK, self.entities.TASK_HISTORY))
        ]
        for task in tasks:
            self.delete(task)
            self.task_files(task)

    # @testable infrastructure
    def task_files(self, task):
        for file in task.files:
            file.properties.tasks.remove(task)
            if file.has_references:
                self.repair(
                    file,
                    "tasks",
                    "requires",
                    property_updates=("requires", "modified"),
                    reason="task-delete-file-unlink",
                )
            else:
                self.delete(file)

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_collect_task_delete_updates_task_list_owners
    # @features entities tasks
    # @dimensions delete cascade list-owner-fingerprint
    def task_owners(self, task):
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

    # @testable true
    # @tests tests_unit/test_002j_notes.py::test_note_delete_repairs_owners_and_parent_cascades
    # @features notes mutations
    # @dimensions delete owner-invalidation page-cascade user-cascade
    def note(self, note):
        self.delete(note)
        owners = {owner.key: owner for owner in (note.parent, note.user) if owner}
        for owner in owners.values():
            self.repair(owner, reason="note-delete-list-owner")

    # @testable false
    # @covered-by lagniappe/core/mutations/delete.py::DeleteCollector.note
    # @reason relation loading delegates each attached note to the tested note collector
    def page_notes(self, page):
        notes = self.entities.fetch(
            *database.get.page_notes(page),
            request=Fetch.direct(),
        )
        for note in notes:
            if isinstance(note, self.entities.NOTE):
                self.note(note)

    # @testable false
    # @covered-by lagniappe/core/mutations/delete.py::DeleteCollector.note
    # @reason relation loading delegates each authored note to the tested note collector
    def user_notes(self, user):
        notes = self.entities.fetch(
            *database.get.notes_by_user(user),
            request=Fetch.direct(),
        )
        for note in notes:
            if isinstance(note, self.entities.NOTE):
                self.note(note)

    # @testable true
    # @tests tests_unit/test_027b_messaging_service.py::test_user_delete_preserves_or_purges_message_history_by_survivor
    # @pairs messaging:deleted-peer messaging:history-retention
    def user_messages(self, user):
        if not user or user.key in self._message_users:
            return
        self._message_users.add(user.key)
        conversations = self.entities.fetch(
            *database.message_conversation_keys(user),
            request=Fetch.direct(),
        )
        for conversation in conversations:
            if isinstance(conversation, self.entities.MESSAGE_CONVERSATION):
                self._message_conversations[conversation.key] = conversation

    # @testable true
    # @tests tests_unit/test_027b_messaging_service.py::test_user_delete_preserves_or_purges_message_history_by_survivor
    # @pairs messaging:history-retention messaging:orphan-purge
    def finalize_message_conversations(self):
        deleting_users = {
            entity.key
            for entity in self.to_delete
            if isinstance(entity, self.entities.USER)
        }
        for conversation in self._message_conversations.values():
            participants = set(conversation.db.get("participants") or ())
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
                    for key in conversation.db.get("visible_to") or ()
                    if key in survivors
                ]
                self.repair(
                    conversation,
                    "visible_to",
                    reason="user-delete-message-history-preservation",
                )
                continue

            self.delete(conversation)
            for message_key in database.message_keys(conversation):
                self.delete(self.entities.MESSAGE(message_key))

    # @testable infrastructure
    def project_models(self, project):
        models = list(project.model_tasks)
        for model in models:
            self.delete(model)
        for form in self.model_forms(*models):
            self.delete(form)

    # @testable infrastructure
    def model_forms(self, *models):
        forms = {model.form.key: model.form for model in models if model.form}
        model_keys = {model.key for model in models}
        form_users = list(database.get.form_users(*forms.values()))
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

    # @testable infrastructure
    def filters(self, entity):
        for filter_key in database.get.filters(entity):
            self.delete(self.entities.FILTER(filter_key))

    # @testable infrastructure
    def category_pages(self, category):
        entities = database.get.pages(
            category.key,
            limit=None,
            hashes=Restriction.UNRESTRICTED,
        ).results
        entities.append(category)
        pages = [
            page
            for page in self.entities.fetch(*entities, request=Fetch.direct())
            if isinstance(page, self.entities.PAGE)
        ]
        for page in pages:
            page.properties.categories.remove(category)
            self.page(page)

    # @testable infrastructure
    def collect(self, entity):
        delete_planner_for(entity).collect(entity, self)


# @testable infrastructure
class StandardDeleteMutation:
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.delete(entity)


# @testable infrastructure
class PageDeleteMutation(StandardDeleteMutation):
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.page(entity, force=True)


# @testable infrastructure
class UserDeleteMutation(StandardDeleteMutation):
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.user_notes(entity)
        collector.user_messages(entity)
        if entity.properties.page.exists:
            if collector.preserve_user_pages:
                collector.preserve_user_page(entity, entity.page)
            else:
                collector.page(entity.page, force=True)
        else:
            collector.delete(entity)


# @testable infrastructure
class TaskDeleteMutation(StandardDeleteMutation):
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.delete(entity)
        collector.task_owners(entity)
        collector.task_files(entity)


# @testable false
# @covered-by lagniappe/core/mutations/delete.py::DeleteCollector.note
# @reason planner dispatch delegates note behavior to the tested collector
class NoteDeleteMutation(StandardDeleteMutation):
    def collect(self, entity, collector):
        collector.note(entity)


# @testable infrastructure
class ProjectDeleteMutation(StandardDeleteMutation):
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.delete(entity)
        collector.filters(entity)
        collector.project_models(entity)


# @testable infrastructure
class ModelDeleteMutation(StandardDeleteMutation):
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.delete(entity)
        for form in collector.model_forms(entity):
            collector.delete(form)


# @testable infrastructure
class FormDeleteMutation(StandardDeleteMutation):
    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_collect_form_delete_updates_form_users
    # @features entities forms
    # @dimensions delete cascade forms list-owner-fingerprint
    def collect(self, entity, collector):
        collector.delete(entity)
        for owner in entity.used_by:
            collector.repair(owner, reason="form-delete-user-invalidation")


# @testable infrastructure
class CategoryDeleteMutation(StandardDeleteMutation):
    # @testable infrastructure
    def collect(self, entity, collector):
        collector.delete(entity)
        collector.filters(entity)
        collector.category_pages(entity)


STANDARD_DELETE = StandardDeleteMutation()
DELETE_PLANNERS = {
    "user": UserDeleteMutation(),
    "project": ProjectDeleteMutation(),
    "model": ModelDeleteMutation(),
    "file": STANDARD_DELETE,
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


# @testable infrastructure
def delete_planner_for(entity):
    kind = getattr(entity, "entity_kind", None) or getattr(entity, "kind", None)
    try:
        return DELETE_PLANNERS[kind]
    except KeyError as error:
        raise ValueError(f"No delete planner registered for kind: {kind}") from error


# @testable infrastructure
def _unique_entities(entities):
    unique = {}
    for entity in entities:
        key = getattr(entity, "key", None)
        if key:
            unique[key] = entity
    return list(unique.values())


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_delete_survivor_merge_combines_relation_removals
# @features mutations
# @dimensions delete plan property-mask mergeable-unlinks overlapping-roots
def _merge_survivors(survivors):
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

            relation = canonical.properties.get(property_name)
            if relation is not None and relation.is_set:
                attached = {
                    getattr(item, "key", None): item
                    for copy in copies
                    for item in (getattr(copy.entity, property_name, None) or [])
                    if getattr(item, "key", None) in kept
                }
                relation.value = [attached[key] for key in ordered if key in attached]
        merged.append(Survivor(canonical, properties, property_updates, reasons))
    return merged


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_delete_accepts_batch_and_dedupes
# @tests tests_unit/test_001_test_general_and_utilities.py::test_collect_user_delete_can_preserve_page
# @tests tests_unit/test_022_mutation_contracts.py::test_job_delete_removes_operation_projection_after_commit
# @pairs mutations:delete mutations:batch mutations:dedupe
# @pair mutations:preserve-user-pages
# @pair deferred-jobs:redis-projection
def plan_delete(*entities, registry, preserve_user_pages=False):
    entities = tuple(entity for entity in entities if entity)
    builder = MutationPlanBuilder(
        MutationOperation.DELETE,
        entities,
        registry=registry,
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
        )
    for kind, entity in collector.search_deletes:
        builder.delete_from_search(
            kind,
            entity,
            reason="user-delete-page-preservation",
        )
    for entity in deleted:
        builder.delete(entity, reason="delete-cascade")
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
