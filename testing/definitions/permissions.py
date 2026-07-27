from enum import Enum

from . import permission_definitions as pd


class Permissions(Enum):
    test_set_general = pd.set_general
    test_set_entity_specific = pd.set_entity_specific
    test_user_one_category = pd.user_one_category
    test_all_create = pd.all_create
    test_admin_cannot_create_users = pd.admin_cannot_create_users
    test_general_models_view_only = pd.general_models_view_only
    test_general_forms_view_only = pd.general_forms_view_only
    test_models_forms_view_only = pd.models_forms_view_only
    test_general_users_view_only = pd.general_users_view_only
    test_models_create_forms_none = pd.models_create_forms_none
    test_two_categories_edit_and_delete = pd.two_categories_edit_and_delete
    test_page_acl_one_visible = pd.page_acl_one_visible
    test_single_category_create = pd.single_category_create
    test_specific_user_assigner = pd.specific_user_assigner

    def get(self, user):
        if self.value.initialized:
            return self.value

        self.value.initialize(user)
        return self.value
