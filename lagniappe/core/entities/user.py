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
from ..tools import database
from ..tools.user_context import current_context_user
from .entity import Entity
from . import Entities


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_entity_create_save_load_owner_page_and_groups
# @features user
# @dimensions entity-lifecycle
class User(AssetMixin, UserMixin, Entity):
    entity_kind = "user"

    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "ai_access",
                "permissions",
                "photo",
                "allow_messages_and_mentions",
                "allow_task_assignments",
                "notification_email_mode",
                "notification_email_opt_out_epoch",
            }
        )

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_entity_create_save_load_owner_page_and_groups
    # @features user
    # @dimensions search-cache page-canonical
    @property
    def to_cache(self):
        return {}

    @property
    def required(self):
        return ["users", *[g.hash for g in self.groups]]

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_user_visibility_uses_users_and_group_permissions_without_page_restrictions
    # @pairs users:owner users:users-view users:group-view
    # @pair users:restriction-independence
    def allowed(self, action, user=None):
        """Authorize user rows from their own Users/group permission scope."""
        viewer = current_context_user(user)
        return bool(
            viewer
            and viewer.is_authenticated
            and viewer.has_permission(self, action)
        )

    # @testable false
    # @covered-by lagniappe/core/properties/user_entity.py::Email
    # @covered-by lagniappe/core/properties/user_entity.py::LastLogin
    # @covered-by lagniappe/core/properties/user_entity.py::IsOwner
    # @covered-by lagniappe/core/properties/user_entity.py::ProfilePhoto
    # @covered-by lagniappe/core/properties/user_related.py::UserPage
    # @covered-by lagniappe/core/properties/user_related.py::Groups
    # @covered-by lagniappe/core/properties/user_permissions.py::UserPermissions
    # @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions
    # @reason property registry wires behavior owned by concrete user property classes
    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "page": user_related.UserPage,
                "email": user_entity.Email,
                "last_login": user_entity.LastLogin,
                "restricted_to": common_entity.RestrictedTo,
                "groups": user_related.Groups,
                "permissions": user_permissions.UserPermissions,
                "photo": user_entity.ProfilePhoto,
                "starred": user_related.Starred,
                "invalidate_cache": user_entity.InvalidateCache,
                "ai_access": user_entity.AIAccess,
                "restrictions": user_restrictions.Restrictions,
                "is_public": common_entity.IsPublic,
                "is_owner": user_entity.IsOwner,
                "allow_messages_and_mentions": user_entity.AllowMessagesAndMentions,
                "allow_task_assignments": user_entity.AllowTaskAssignments,
                "allow_site_email": user_entity.AllowSiteEmail,
                "notification_email_mode": user_entity.NotificationEmailPreference,
            }
        )
        return properties

    @property
    def is_authenticated(self):
        return True if self._db else False

    @property
    def is_anonymous(self):
        return not self.is_authenticated

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_user_permissions_fingerprint_tracks_permissions_and_owner_state
    # @features permissions cache
    # @dimensions stored-permissions fingerprint owner empty-permissions
    @property
    def permissions_fingerprint(self):
        permissions = "" if self.is_owner else self.db.get("permissions", "{}")
        return hashlib.md5(permissions.encode("utf-8")).hexdigest()

    # @testable true
    # @tests tests_unit/test_009f_user_ai_access.py::test_user_access_is_independent_hierarchical_and_fail_closed
    # @features ai-access
    # @dimensions authentication hierarchy permissions-independent owner-no-bypass
    def access(self, required):
        """Check this user's independent AI entitlement."""
        if (
            not self.is_authenticated
            or not isinstance(required, AI)
            or required is AI.NONE
        ):
            return False
        return AI[self.ai_access].implies(required)

    # @testable true
    # @tests tests_unit/test_009f_user_ai_access.py::test_authorization_fingerprint_tracks_ai_access
    # @features ai-access cache
    # @dimensions authorization-fingerprint permissions entitlement
    @property
    def authorization_fingerprint(self):
        value = f"{self.permissions_fingerprint}:{self.ai_access}"
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @property
    def is_test_user(self):
        return self.db.get("test_user", False)

    @is_test_user.setter
    def is_test_user(self, value):
        self.db["test_user"] = value

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_unit/test_009b_user_permissions.py::test_entity_permissions
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_one_category_permissions
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_category_home_rows_only_offer_star_controls
    # @features permissions
    # @dimensions global-resources, resource-gates, owner, entity-resources, requires
    def has_permission(self, resource, action=Action.ALL):
        if isinstance(resource, Entity):
            required, permissions = resource.requires, self.permissions
            return self.is_owner or any(
                Action[a].implies(action)
                for a in (permissions.get(r) for r in required)
            )
        elif isinstance(resource, Resource):
            return resource.allowed(action, user=self)

        return False

    def get_id(self):
        return str(self._db["email"])

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_entity_create_save_load_owner_page_and_groups
    # @tests tests_unit/test_009a_user.py::test_user_create_does_not_leave_initial_cache_invalidation
    # @tests tests_unit/test_009a_user.py::test_user_create_public_user_assigns_public_group
    # @tests tests_unit/test_009f_user_ai_access.py::test_user_create_defaults_non_owner_to_none
    # @tests tests_e2e/008_users/test_008a_user_index.py::test_owner_create_adopts_public_user_and_resets_form
    # @pairs user:create user:owner user:page user:groups user:cache-invalidation
    # @pairs user:public-user user:public-group user:personal-page user:limited-attrs
    # @pair user:new-user-default
    # @pairs user:public-adoption user:submitted-create-data user:page-reassign
    # @pairs public-users:create public-users:public-user public-users:public-group
    # @pairs public-users:personal-page public-users:limited-attrs
    @classmethod
    def create(cls, data, *, adopt_public=False):
        if not data.get("name"):
            raise ValueError("name is required")
        if not data.get("email"):
            raise ValueError("email is required")

        exists = database.get.user(data.get("email"))
        adopting_public = bool(
            exists and adopt_public and exists.get("public", False)
        )
        if exists and not adopting_public:
            return cls(exists)

        previous_page = None
        if adopting_public:
            new_user = Entities.fetch_one(
                exists,
                request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
            )
            previous_page = new_user.page
        else:
            new_user = cls()

        new_user.kind = cls.entity_kind
        new_user.name = data.get("name")
        new_user.is_public = data.get("is_public", False)
        new_user.page = data.get("page")

        new_user.email = data.get("email")
        new_user.db["photo"] = data.get("picture")
        new_user.is_test_user = data.get("test_user", False)

        if new_user.db.get("email") == CONFIG.ADMIN_EMAIL:
            new_user.is_owner = True

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

        if previous_page and previous_page.key != new_user.page.key:
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

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_entity_create_save_load_owner_page_and_groups
    # @features user
    # @dimensions save page
    def save(self):
        if self.db.get("photo") and not self.get_asset("photo"):
            self.properties.photo.save_google_photo()
        super().save()

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_entity_create_save_load_owner_page_and_groups
    # @features user
    # @dimensions load
    @classmethod
    def load(cls, email):
        user = database.get.user(email)
        if user:
            return Entities.fetch_one(user, request=Fetch.direct())
        return None
