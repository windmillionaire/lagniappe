from dataclasses import dataclass
from typing import Optional


@dataclass
class GroupDefinition:
    name: str = ""
    public: Optional[bool] = False
    permission_definition: Optional[str] = None


set_general = GroupDefinition(
    name="Model View Group",
    public=False,
)

set_entity_specific = GroupDefinition(
    name="Entity Specific Group",
    public=False,
)

delete_group_refreshes_navigation = GroupDefinition(
    name="Delete Flow Group",
    public=False,
)

user_one_category = GroupDefinition(
    name="User One Category",
    public=False,
    permission_definition="test_user_one_category",
)

all_create = GroupDefinition(
    name="All Create",
    public=False,
    permission_definition="test_all_create",
)

admin_cannot_create_users = GroupDefinition(
    name="Admin Cannot Create Users",
    public=False,
    permission_definition="test_admin_cannot_create_users",
)

general_models_view_only = GroupDefinition(
    name="General Models View Only",
    public=False,
    permission_definition="test_general_models_view_only",
)

general_forms_view_only = GroupDefinition(
    name="General Forms View Only",
    public=False,
    permission_definition="test_general_forms_view_only",
)

models_forms_view_only = GroupDefinition(
    name="Models And Forms View Only",
    public=False,
    permission_definition="test_models_forms_view_only",
)

general_users_view_only = GroupDefinition(
    name="General Users View Only",
    public=False,
    permission_definition="test_general_users_view_only",
)

models_create_forms_none = GroupDefinition(
    name="Models Create Forms None",
    public=False,
    permission_definition="test_models_create_forms_none",
)

two_categories_edit_and_delete = GroupDefinition(
    name="Two Categories Edit And Delete",
    public=False,
    permission_definition="test_two_categories_edit_and_delete",
)

page_acl_one_visible = GroupDefinition(
    name="Page ACL One Visible",
    public=False,
    permission_definition="test_page_acl_one_visible",
)

single_category_create = GroupDefinition(
    name="Single Category Create",
    public=False,
    permission_definition="test_single_category_create",
)

assignable_users = GroupDefinition(
    name="Assignable Users",
    public=False,
)

specific_user_assigner = GroupDefinition(
    name="Specific User Assigner",
    public=False,
    permission_definition="test_specific_user_assigner",
)
