from typing import TYPE_CHECKING, TypedDict, cast

import hashlib

from flask_login import UserMixin

from lagniappe import CONFIG

from ..definitions import AI, Action, Fetch, FetchReason, MutationIntent, Resource
from ..properties import (
    common_entity,
    user_related,
    user_permissions,
    user_restrictions,
    user_entity,
)
from ..mixins import AssetMixin
from lagniappe.core.tools.database import get as database_get
from ..tools.auth.context import current_context_user
from .entity import Entity
from . import Entities


if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..mixins.field_host import FieldUser
    from . import property_types
    from .group import UserGroup
    from .page import Page


class UserCreationData(TypedDict, total=False):
    name: str | None
    email: str | None
    page: Page | None
    groups: list[UserGroup]
    picture: str | None
    ai_access: str | None
    admin: bool
    is_public: bool
    test_user: bool


class User(AssetMixin, UserMixin, Entity):
    if TYPE_CHECKING:
        notification_email_mode: str
        email: str | None
        groups: list[UserGroup]
        permissions: dict[str, str]
        @property
        def ai_access(self) -> str: ...

        @ai_access.setter
        def ai_access(self, value: str | None) -> None: ...

        is_public: bool
        is_owner: bool
        is_admin: bool
        allow_auto_execute: bool
        invalidate_cache: bool

        @property
        def page(self) -> Page: ...

        @page.setter
        def page(self, page: Page | None) -> None: ...

        @property
        def properties(self) -> property_types.UserProperties: ...

    entity_kind = "user"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset(
            {
                "ai_access",
                "admin",
                "permissions",
                "photo",
                "allow_messages_and_mentions",
                "allow_task_assignments",
                "allow_auto_execute",
                "notification_email_mode",
                "notification_email_opt_out_epoch",
                "cache_invalidation_revision",
            }
        )

    @property
    def to_cache(self) -> dict[str, object]:
        return {}

    @property
    def required(self) -> list[str]:
        return ["users", *[g.hash for g in self.groups]]

    def allowed(self, action: Action, user: FieldUser = None) -> bool:
        """Authorize user rows from their own Users/group permission scope."""
        viewer = current_context_user(user)
        if (
            self.is_admin
            and viewer
            and viewer.is_authenticated
            and not viewer.is_owner
            and action.value > Action.VIEW.value
        ):
            return False
        return bool(
            viewer and viewer.is_authenticated and viewer.has_permission(self, action)
        )

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "page": user_related.UserPage,
                "email": user_entity.Email,
                "last_login": user_entity.LastLogin,
                "groups": user_related.Groups,
                "permissions": user_permissions.UserPermissions,
                "photo": user_entity.ProfilePhoto,
                "starred": user_related.Starred,
                "invalidate_cache": user_entity.InvalidateCache,
                "ai_access": user_entity.AIAccess,
                "restrictions": user_restrictions.Restrictions,
                "is_public": common_entity.IsPublic,
                "is_owner": user_entity.IsOwner,
                "is_admin": user_entity.IsAdmin,
                "allow_messages_and_mentions": user_entity.AllowMessagesAndMentions,
                "allow_task_assignments": user_entity.AllowTaskAssignments,
                "allow_site_email": user_entity.AllowSiteEmail,
                "allow_auto_execute": user_entity.AllowAutoExecute,
                "notification_email_mode": user_entity.NotificationEmailPreference,
            }
        )
        return properties

    @property
    def is_authenticated(self) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride] -- Flask-Login infers a constant for its default.
        return bool(self._db)

    @property
    def is_anonymous(self) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride] -- A missing user row represents an anonymous session.
        return not self.is_authenticated

    @property
    def permissions_fingerprint(self) -> str:
        permissions = "" if self.is_admin else self.db.get("permissions", "{}")
        # Permission maps are persisted as JSON strings by Permissions.value.
        return hashlib.md5(cast(str, permissions).encode("utf-8")).hexdigest()

    def access(self, required: AI) -> bool:
        """Check this user's independent AI entitlement."""
        if (
            not getattr(CONFIG, "AI_ENABLED", True)
            or not self.is_authenticated
            or not isinstance(required, AI)
            or required is AI.NONE
        ):
            return False
        return AI[self.ai_access].implies(required)

    @property
    def authorization_fingerprint(self) -> str:
        role = "owner" if self.is_owner else "admin" if self.is_admin else "user"
        groups = ",".join(sorted(set(self.requires) - {"users"}))
        value = (
            f"{role}:{self.permissions_fingerprint}:{self.ai_access}:"
            f"{getattr(CONFIG, 'AI_ENABLED', True)}:"
            f"{getattr(CONFIG, 'EXTERNAL_AI_ENABLED', True)}:"
            f"{self.allow_auto_execute}:{groups}"
        )
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @property
    def is_test_user(self) -> bool:
        return cast(bool, self.db.get("test_user", False))

    @is_test_user.setter
    def is_test_user(self, value: bool) -> None:
        self.db["test_user"] = value

    def has_permission(self, resource: Entity | Resource, action: Action = Action.ALL) -> bool:
        if isinstance(resource, Entity):
            required, permissions = resource.requires, self.permissions
            return self.is_admin or any(
                Action[a].implies(action)
                for a in (permissions.get(r, Action.NONE.name) for r in required)
            )
        elif isinstance(resource, Resource):
            return resource.allowed(action, user=self)

        return False

    def get_id(self) -> str:
        # Entity.__init__ initializes even a temporary user with a mapping.
        if self._db is None:
            raise KeyError("email")
        return str(self._db["email"])

    @classmethod
    def create(
        cls, data: UserCreationData, *, adopt_public: bool = False, key: Key | None = None
    ) -> User:
        name = data.get("name")
        email = data.get("email")
        if not name:
            raise ValueError("name is required")
        if not email:
            raise ValueError("email is required")

        exists = database_get.user(email)
        adopting_public = bool(exists and adopt_public and exists.get("public", False))
        if exists and not adopting_public:
            return cls(exists)

        previous_page = None
        if adopting_public:
            # The user-kind query supplied a loaded record.
            new_user = cast("User", Entities.fetch_one(
                exists,
                request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
            ))
            previous_page = new_user.page
        else:
            new_user = cls(key) if key is not None else cls()

        new_user.kind = cls.entity_kind
        new_user.name = name
        new_user.is_public = data.get("is_public", False)
        new_user.page = data.get("page")

        new_user.email = email
        new_user.db["photo"] = data.get("picture")
        new_user.is_test_user = data.get("test_user", False)

        if (
            str(new_user.db.get("email") or "").casefold()
            == str(CONFIG.ADMIN_EMAIL or "").casefold()
        ):
            new_user.is_owner = True

        if data.get("admin", False):
            new_user.is_admin = True

        new_user.ai_access = data.get(
            "ai_access",
            AI.CREATE.name if new_user.is_owner else AI.NONE.name,
        )
        new_user.groups = (
            [Entities.PUBLIC_GROUP.get()]
            if new_user.is_public
            else data.get("groups", [])
        )
        new_user.properties.permissions.create()

        # Setting page to None created a personal page in UserPage.value.
        if previous_page and previous_page.key != cast("Page", new_user.page).key:
            users_model = Entities.USERS.get()
            previous_page.user = None
            previous_page.properties.categories.remove(users_model)
            previous_page.add_mutation_intents(
                MutationIntent.touch(
                    users_model,
                    reason="user-public-adoption-previous-users-owner",
                ),
                MutationIntent.delete_from_search(
                    "user",
                    previous_page,
                    reason="user-public-adoption-search-removal",
                ),
            )
            new_user.add_mutation_intents(
                MutationIntent.standard(
                    previous_page,
                    reason="user-public-adoption-previous-page",
                )
            )

        if not adopting_public:
            new_user.invalidate_cache = False
        return new_user

    def save(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride] -- User.save refreshes only this user.
        if self.db.get("photo") and not self.get_asset("photo"):
            self.properties.photo.save_google_photo()
        super().save()

    @classmethod
    def load(cls, email: str) -> User | None:
        user = database_get.user(email)
        if user:
            # The email lookup queries only user records.
            return cast("User | None", Entities.fetch_one(user, request=Fetch.direct()))
        return None
