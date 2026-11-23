from datetime import datetime, UTC
from typing import TYPE_CHECKING, Self, TypedDict, cast

from flask import url_for

from ..definitions import Action, Fetch, FetchReason, MutationIntent, NotificationEmailMode
from ..entities import Entities
from ..mixins import AssetMixin, SubmitterMixin
from ..properties import (
    common_assets,
    common_entity,
    common_related,
    form_submission,
    page_assets,
    page_public,
    page_related,
)
from lagniappe.core.tools.database import get as database_get
from ..tools.auth.context import current_context_user
from ..tools.tasks.ordering import sort_tasks
from .category import UNCATEGORIZED_PAGES_NAME
from .entity import Entity, EntityProperties


if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..definitions.asset import AssetUpload, ImageAsset
    from ..mixins.field_host import FieldUser
    from . import property_types
    from .category import Category
    from .form import Form
    from .group import UserGroup as UserGroup
    from .file import File
    from .user import User
    from .task import Task


PageData = TypedDict(
    "PageData",
    {
        "user": "User | None",
        "categories": "list[Category]",
        "model": "Category | None",
        "form": "Form | None",
        "name": str | None,
        "description": str | None,
        "submission": object,
        "groups": "list[UserGroup]",
        "email": str | None,
        "reassign-page": "Page | None",
        "remove-user": bool,
        "ai_access": str | None,
        "notification_email_mode": str | None,
        "allow_site_email": bool,
        "allow_auto_execute": bool,
        "allow_messages_and_mentions": bool,
        "allow_task_assignments": bool,
    },
    total=False,
)


class Page(AssetMixin, SubmitterMixin, Entity):
    if TYPE_CHECKING:
        @property
        def restricted_to(self) -> dict[str, list[str]]: ...

        @property
        def image(self) -> ImageAsset | None: ...
        @image.setter
        def image(self, value: AssetUpload | None) -> None: ...

        @property
        def public_settings(self) -> page_public.PageSettings: ...
        @public_settings.setter
        def public_settings(self, value: object) -> None: ...

        description: str | None
        model: Category | None
        is_public: bool
        @property
        def public_id(self) -> str: ...

        @property
        def categories(self) -> list[Category]: ...
        @categories.setter
        def categories(self, value: list[Category] | None) -> None: ...

        form: Form | None

        @property
        def files(self) -> list[File]: ...
        user: User | None
        deferred_job: dict[str, object] | None

        @property
        def properties(self) -> property_types.PageProperties: ...

    entity_kind = "page"
    retired_fields = frozenset({"attributes"})

    _state: dict[str, object] | None = None

    def __init__(
        self, *args: database_get.Identifier, temporary: bool | None = None,
        testing: bool | None = None, parent: database_get.Identifier = None, **kwargs: object,
    ) -> None:
        super().__init__(*args, temporary=temporary, testing=testing, parent=parent, **kwargs)
        self._tasks: list[Task] | None = None
        self._completed: list[Task] | None = None

    @property
    def exclude_from_index(self) -> frozenset[str]:
        exclude = {
            "submission",
            "pre_migration",
            "form_change_receipt",
            "description",
            "assets",
            "schema_version",
            "deferred_job",
            "autofill_reviews",
            "public_settings",
            "has_notes",
            "notes_checked_revision",
        }
        return frozenset(exclude)

    @property
    def sync_ids(self) -> dict[str, dict[str, str | None]]:
        return {
            "document": {
                "id": self.properties.document.sync_id,
                "fingerprint": self.properties.document.fingerprint,
            },
        }

    def state(self, sync_id: str) -> dict[str, object]:
        if not self.allowed(Action.VIEW):
            return {}
        elif self._state is not None:
            return self._state

        modified = self.modified
        if modified is None:
            raise AttributeError("Page document state requires a modification time")
        self._state = {"timestamp": modified.timestamp()}
        self._state.update(
            {
                "ydoc": self.properties.document.ydoc,
                "fingerprint": self.properties.document.fingerprint,
            }
        )
        if not self._state.get("ydoc") and self.properties.document.html:
            self._state["markup"] = self.properties.document.html
        return self._state

    @property
    def required(self) -> list[str]:
        required = []
        if self.categories:
            required.append("models")

        user = self.user
        if user:
            required.extend(user.requires)

        required.append(self.hash)
        if self.categories:
            required.extend([c.hash for c in self.categories])
        return required

    @property
    def url(self) -> str:
        return url_for("pages.view", key=self.urlsafe_key)

    @property
    def to_cache(self) -> dict[str, object]:
        if self.user and self.user.is_public:
            return {}
        return super().to_cache

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "form": common_related.AttachedForm,
                "description": common_entity.Description,
                "model": page_related.PageModelCategory,
                "categories": page_related.PageCategories,
                "groups": common_related.Groups,
                "user": page_related.PageUser,
                "files": page_related.PageFiles,
                "document": common_assets.Document,
                "image": page_assets.Image,
                "is_public": page_public.PageIsPublic,
                "public_id": common_entity.PublicID,
                "public_settings": page_public.PublicSettings,
                "submission": form_submission.FormSubmission,
                "deferred_job": common_entity.DeferredJobReference,
                "restricted_to": common_entity.RestrictedTo,
            }
        )
        return properties

    def _load_tasks(self) -> None:
        results = database_get.page_tasks(self)
        entities = {
            e.key: e for e in Entities.fetch(
                *results, self,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
        }

        tasks = [
            e
            for e in entities.values()
            if isinstance(e, Entities.TASK) and e.allowed(Action.VIEW)
        ]

        self._completed = [t for t in tasks if t.completed]
        self._completed.sort(key=lambda task: task.modified or datetime.min.replace(tzinfo=UTC), reverse=True)
        self._tasks = sort_tasks([t for t in tasks if not t.completed])

    @property
    def tasks(self) -> list[Task]:
        if self._tasks is None:
            self._load_tasks()
            assert self._tasks is not None
        return self._tasks

    @property
    def completed_tasks(self) -> list[Task]:
        if self._completed is None:
            self._load_tasks()
            assert self._completed is not None
        return self._completed

    @property
    def has_notes(self) -> bool:
        """Unknown or stale presence requires a read; only proven empty skips it."""
        return not (
            self.db.get("has_notes") is False
            and self.modified is not None
            and self.db.get("notes_checked_revision") == self.modified
        )

    def remember_empty_notes(self) -> None:
        """Cache an unfiltered empty query without changing content or revisions."""
        if not self.has_notes or self.modified is None:
            return
        self.db["has_notes"] = False
        self.db["notes_checked_revision"] = self.modified
        # A racing note mutation advances modified. This old observation then
        # cannot suppress its notes, even when this masked write commits last.
        Entities.save_root(self, property_mask=("has_notes", "notes_checked_revision"))

    def allowed(self, action: Action, user: FieldUser = None) -> bool:
        user = current_context_user(user)
        if self.restricted_access(user):
            return False
        if action.value > Action.VIEW.value:
            target_user = self.user
            # Personal workspace content is separate from account management.
            # Keep privileged account deletion and permissions Owner-only.
            if (
                target_user
                and target_user.is_admin
                and user
                and not user.is_owner
                and (
                    target_user.key != user.key
                    or action not in {Action.EDIT, Action.CREATE}
                )
            ):
                return False
        return super().allowed(action, user=user)

    @classmethod
    def create(cls, data: PageData, *, key: Key | None = None) -> Self:
        new_page = cls(key)
        new_page.kind = cls.entity_kind

        new_page.update(data)

        return new_page

    @property
    def page_list_owners(self) -> list[Category | User]:
        owners = [self.user, self.model, *self.categories]
        unique = []
        seen = set()
        for owner in owners:
            key = getattr(owner, "key", None)
            if owner is None or not key or key in seen:
                continue
            seen.add(key)
            unique.append(owner)
        return unique

    def update(self, data: PageData) -> None:
        previous_owners = self.page_list_owners

        if data.get("user"):
            self.user = data.get("user")

        self.categories = data.get("categories", [])
        if data.get("model"):
            self.model = data.get("model")
        self._ensure_category()

        self.form = data.get("form")
        if self.form:
            category_keys = set()
            for category in [self.model, *self.categories]:
                key = getattr(category, "key", None)
                if category is None or not key or key in category_keys:
                    continue
                category_keys.add(key)
                # The fallback category is a grab-bag, not a form registry.
                if category.name == UNCATEGORIZED_PAGES_NAME:
                    continue
                if category.properties.forms.add(self.form):
                    self.add_mutation_intents(
                        MutationIntent.patch(
                            category,
                            "forms",
                            reason="page-category-form-registration",
                        ),
                        MutationIntent.touch(
                            self.form,
                            reason="page-category-form-registration",
                        ),
                    )

        self.name = data.get("name")
        self.description = data.get("description")

        if data.get("submission"):
            self.properties.submission.value = data.get("submission")

        current_owner_keys = {owner.key for owner in self.page_list_owners}
        self.add_mutation_intents(
            *[
                MutationIntent.touch(owner, reason="page-previous-list-owner")
                for owner in previous_owners
                if owner.key not in current_owner_keys
            ]
        )

    def _ensure_category(self) -> None:
        if not self.model and not self.categories:
            self.model = Entities.CATEGORY.get_uncategorized_pages()

    def update_user(self, data: PageData, user: FieldUser = None) -> None:
        user = current_context_user(user)
        target_user = self.user
        if target_user is None:
            raise AttributeError("Page user settings require an attached user")
        is_own_page = bool(
            user
            and user.is_authenticated
            and getattr(getattr(user, "page", None), "key", None) == self.key
        )
        is_owner_viewer = bool(user and user.is_owner)
        is_admin_viewer = bool(user and user.is_admin)
        target_is_privileged = bool(target_user and target_user.is_admin)
        can_manage_target = bool(
            is_admin_viewer and (is_owner_viewer or not target_is_privileged)
        )

        if target_is_privileged and not is_owner_viewer:
            submitted_name = data.get("name")
            if submitted_name is not None and submitted_name != target_user.name:
                raise PermissionError("Only the Owner can edit an Administrator.")
            protected_fields = {
                "ai_access",
                "groups",
                "remove-user",
                "reassign-page",
            }
            if protected_fields.intersection(data):
                raise PermissionError("Only the Owner can edit an Administrator.")
            submitted_email = data.get("email")
            if submitted_email is not None and submitted_email != target_user.email:
                raise PermissionError("Only the Owner can edit an Administrator.")

        ai_access = None
        if "ai_access" in data:
            if not can_manage_target:
                raise PermissionError(
                    "Only the owner or an authorized Administrator can change AI access."
                )
            from ..definitions import AI

            ai_access = AI.name_for(data.get("ai_access"))

        notification_email_mode = None
        if "notification_email_mode" in data:
            if not is_own_page or target_user.is_public:
                raise PermissionError(
                    "Only a managed user can change their own notification email "
                    "preference."
                )
            notification_email_mode = NotificationEmailMode.name_for(
                data.get("notification_email_mode")
            )

        allow_site_email = None
        if "allow_site_email" in data:
            if not is_own_page or not target_user.is_public:
                raise PermissionError(
                    "Only a public user can change their own site email preference."
                )
            allow_site_email = bool(data.get("allow_site_email"))

        allow_auto_execute = None
        if "allow_auto_execute" in data:
            if not is_own_page or target_user.is_public:
                raise PermissionError(
                    "Only a managed user can change their own automatic plan execution preference."
                )
            allow_auto_execute = bool(data.get("allow_auto_execute"))

        if not target_is_privileged or is_owner_viewer:
            target_user.name = data.get("name")
        if ai_access is not None:
            target_user.ai_access = ai_access
        if notification_email_mode is not None:
            target_user.notification_email_mode = notification_email_mode
        if allow_site_email is not None:
            target_user.allow_site_email = allow_site_email
        if allow_auto_execute is not None:
            target_user.allow_auto_execute = allow_auto_execute
        inbound_toggles = {
            key: data.get(key)
            for key in ("allow_messages_and_mentions", "allow_task_assignments")
            if key in data
        }
        if inbound_toggles:
            if not (
                is_owner_viewer and is_own_page and target_user and target_user.is_owner
            ):
                raise PermissionError(
                    "Only the owner can change their inbound collaboration settings."
                )
            for key, value in inbound_toggles.items():
                setattr(target_user, key, value)
        self.add_mutation_intents(
            MutationIntent.standard(target_user, reason="page-user-update")
        )
        if not can_manage_target or is_own_page:
            return

        if "email" in data:
            if target_user.is_owner:
                raise PermissionError("The primary Owner email cannot be changed.")
            target_user.email = data.get("email")
        if "groups" in data:
            target_user.groups = data.get("groups", [])
        if data.get("remove-user"):
            target_user.page = None
        elif (reassigned := data.get("reassign-page")) and reassigned.key != self.key:
            target_user.page = reassigned

        if target_user.page.key != self.key:
            previous_users_category = Entities.USERS.get()
            self.user = None
            self.add_mutation_intents(
                MutationIntent.touch(
                    previous_users_category,
                    reason="page-previous-users-owner",
                ),
                MutationIntent.delete_from_search(
                    "user",
                    self,
                    reason="page-user-search-removal",
                ),
            )
            self.properties.categories.remove(previous_users_category)
            target_user.properties.permissions.create()

    def save_submission(self) -> None:
        super().save_submission()
        self._sync_default_user_form_email()

    def _uses_default_user_form(self) -> bool:
        if not self.user or not isinstance(self.model, Entities.USERS) or not self.form:
            return False
        if not getattr(self.form, "reserved", False):
            return False

        fields = {field.get("id"): field for field in self.form.schema or []}
        return (
            set(fields) == {"name", "email"}
            and fields["name"].get("type") == "input"
            and fields["name"].get("input") == "text"
            and fields["email"].get("type") == "input"
            and fields["email"].get("input") == "email"
        )

    def _sync_default_user_form_email(self) -> None:
        if not self._uses_default_user_form():
            return

        from ..properties.form_inputs import EmailInput
        # The schema check above verifies that the email field is an email input.
        email_field = cast("EmailInput | None", self.properties.submission.fields.get("email"))
        if not email_field:
            return

        user = cast("User", self.user)
        user_email = user.email
        submitted_email = email_field.value

        if not user_email and submitted_email:
            user.email = submitted_email
            user_email = submitted_email

        if user_email and submitted_email != user_email:
            email_field.value = user_email
            self.properties.submission.value = self.properties.submission.db_value
