from enum import Enum

from ..resources import Group

from . import group_definitions as gd
from .base import ResourceEnumMixin


class Groups(ResourceEnumMixin, Enum):
    test_set_general_permissions = Group(definition=gd.set_general)
    test_set_entity_specific_permissions = Group(
        definition=gd.set_entity_specific
    )
    delete_group_refreshes_navigation = Group(
        definition=gd.delete_group_refreshes_navigation
    )
    test_user_one_category = Group(definition=gd.user_one_category)
    all_create = Group(definition=gd.all_create)
    admin_cannot_create_users = Group(definition=gd.admin_cannot_create_users)
    general_models_view_only = Group(definition=gd.general_models_view_only)
    general_forms_view_only = Group(definition=gd.general_forms_view_only)
    models_forms_view_only = Group(definition=gd.models_forms_view_only)
    general_users_view_only = Group(definition=gd.general_users_view_only)
    models_create_forms_none = Group(definition=gd.models_create_forms_none)
    two_categories_edit_and_delete = Group(definition=gd.two_categories_edit_and_delete)
    page_acl_one_visible = Group(definition=gd.page_acl_one_visible)
    single_category_create = Group(definition=gd.single_category_create)
    assignable_users = Group(definition=gd.assignable_users)
    specific_user_assigner = Group(definition=gd.specific_user_assigner)
