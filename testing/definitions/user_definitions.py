"""
User definition dataclasses for test user configuration.

Defines the properties for test users. These are used by the User resource
class to create users in the database or via UI.

Related Files:
    - testing/definitions/users.py: Users enum that uses these definitions
    - testing/resources/user.py: User.create() uses definition properties
    - config/dev_config.yaml: test_settings.ADMIN_EMAIL, ADMIN_NAME
"""

from dataclasses import dataclass, field
from typing import Optional

from config import SETTINGS
from lagniappe.core.definitions import AI

from .groups import Groups
from .pages import Pages


@dataclass
class UserDefinition:
    """
    Configuration for a test user.

    Attributes:
        name: Display name for the user
        email: Email address (used for auth). If None, generates from name.
        groups: List of groups to add user to (not yet implemented)
        user_page: Existing page to link as user's page (not yet implemented)
        ai_access: Explicit AI entitlement for permission-focused test users.
    """

    name: str = ""
    email: Optional[str] = None
    groups: Optional[list[Groups]] = field(default_factory=list)
    user_page: Optional[Pages] = None
    ai_access: Optional[AI] = None


owner = UserDefinition(
    name=SETTINGS.test_config["ADMIN_NAME"],
    email=SETTINGS.test_config["ADMIN_EMAIL"],
)

# Unauthenticated user - no email means no login step
anonymous = UserDefinition(
    name="Anonymous",
)

create_user = UserDefinition(
    name="Create User",
    email="create_user@test.com",
)

create_user_from_index = UserDefinition(
    name="User from Index",
    email="create_user_from_index@test.com",
)

user_no_access = UserDefinition(
    name="User No Access",
    email="user_no_access@test.com",
)

user_one_category = UserDefinition(
    name="User One Category",
    email="user_one_category@test.com",
    groups=[Groups.test_user_one_category],
)

admin_users = UserDefinition(
    name="All Create Permissions",
    email="all_create_permissions@test.com",
    groups=[Groups.all_create],
    ai_access=AI.CREATE,
)

admin_ask = UserDefinition(
    name="All Create Permissions With Ask",
    email="all_create_permissions_ask@test.com",
    groups=[Groups.all_create],
    ai_access=AI.ASK,
)

admin_cannot_create_users = UserDefinition(
    name="Admin Cannot Create",
    email="admin_cannot_create_users@test.com",
    groups=[Groups.admin_cannot_create_users],
)

general_models_view_only = UserDefinition(
    name="General Models View Only",
    email="general_models_view_only@test.com",
    groups=[Groups.general_models_view_only],
)

general_forms_view_only = UserDefinition(
    name="General Forms View Only",
    email="general_forms_view_only@test.com",
    groups=[Groups.general_forms_view_only],
)

models_forms_view_only = UserDefinition(
    name="Models And Forms View Only",
    email="models_forms_view_only@test.com",
    groups=[Groups.models_forms_view_only],
)

general_users_view_only = UserDefinition(
    name="General Users View Only",
    email="general_users_view_only@test.com",
    groups=[Groups.general_users_view_only],
)

models_create_forms_none = UserDefinition(
    name="Models Create Forms None",
    email="models_create_forms_none@test.com",
    groups=[Groups.models_create_forms_none],
)

two_categories_edit_and_delete = UserDefinition(
    name="Two Categories Edit And Delete",
    email="two_categories_edit_and_delete@test.com",
    groups=[Groups.two_categories_edit_and_delete],
)

page_acl_one_visible = UserDefinition(
    name="Page ACL One Visible",
    email="page_acl_one_visible@test.com",
    groups=[Groups.page_acl_one_visible],
)

single_category_create = UserDefinition(
    name="Single Category Create",
    email="single_category_create@test.com",
    groups=[Groups.single_category_create],
    ai_access=AI.CREATE,
)

assignable_user = UserDefinition(
    name="Assignable User",
    email="assignable_user@test.com",
    groups=[Groups.assignable_users],
)

specific_user_assigner = UserDefinition(
    name="Specific User Assigner",
    email="specific_user_assigner@test.com",
    groups=[Groups.specific_user_assigner],
)
