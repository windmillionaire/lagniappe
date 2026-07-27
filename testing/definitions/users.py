"""
Test user definitions for authentication and user creation.

This enum is the central catalog for all test users in the suite. Currently
provides three foundational user types, but is designed to be extended as
tests require users with specific permissions, group memberships, or other
attributes.

Related Files:
    Application:
        - lagniappe/core/entities/user.py: User entity
        - lagniappe/web/routes/users/main.py: User routes, login

    Test Framework:
        - testing/definitions/user_definitions.py: UserDefinition dataclasses
        - testing/resources/user.py: User resource (login, go, locate)
        - testing/conftest.py: get_user fixture creates browser contexts

    Configuration:
        - config/dev_config.yaml: test_settings.ADMIN_EMAIL, ADMIN_NAME

Authentication Flow:
    1. get_user(Users.OWNER) called in test
    2. Users.get() ensures OWNER entity exists in database
    3. User.login() navigates to /users/login?test_user={email}
    4. Server creates session, context.storage_state() captures cookies
    5. Subsequent tests reuse stored auth state (no re-login needed)

Extending with New Users:
    To add a user for permission testing, group membership, etc.:

    1. Define in user_definitions.py:
        viewer_only = UserDefinition(
            name="Viewer User",
            permissions=Permissions.VIEWER,
            groups=[Groups.PUBLIC],
        )

    2. Add enum member here:
        VIEWER_ONLY = User(definition=viewer_only)

    3. Use in tests:
        viewer = get_user(Users.VIEWER_ONLY, creator=admin_user)

Usage:
    # Authenticated admin user
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    # Unauthenticated user (for testing login, errors, public pages)
    anon = get_user(Users.ANONYMOUS)
    anon.go(SitePages.LOGIN_PAGE)
"""

from enum import Enum

from ..resources import User

from . import user_definitions as ud
from .base import ResourceEnumMixin


class Users(ResourceEnumMixin, Enum):
    """
    Enum of test users with different authentication states.

    This enum catalogs all users available to the test suite. Add new members
    as tests require users with specific permissions, group memberships, or
    other attributes (e.g., VIEWER_ONLY, GROUP_ADMIN, RESTRICTED_USER).

    """

    OWNER = User(definition=ud.owner)
    ANONYMOUS = User(definition=ud.anonymous)

    create_user = User(definition=ud.create_user)
    create_user_from_index = User(definition=ud.create_user_from_index)

    user_one_category = User(definition=ud.user_one_category)
    user_no_access = User(definition=ud.user_no_access)
    admin = User(definition=ud.admin_users)
    admin_cannot_create_users = User(definition=ud.admin_cannot_create_users)
    general_models_view_only = User(definition=ud.general_models_view_only)
    general_forms_view_only = User(definition=ud.general_forms_view_only)
    models_forms_view_only = User(definition=ud.models_forms_view_only)
    general_users_view_only = User(definition=ud.general_users_view_only)
    models_create_forms_none = User(definition=ud.models_create_forms_none)
    two_categories_edit_and_delete = User(definition=ud.two_categories_edit_and_delete)
    page_acl_one_visible = User(definition=ud.page_acl_one_visible)
    single_category_create = User(definition=ud.single_category_create)
    assignable_user = User(definition=ud.assignable_user)
    specific_user_assigner = User(definition=ud.specific_user_assigner)

    def get(self, user, create=True):
        if self is Users.ANONYMOUS:
            return self.value
        return super().get(user, create=create)
