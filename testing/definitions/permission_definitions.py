from dataclasses import dataclass, field
from typing import Union
from lagniappe.core.definitions import General, Levels

from . import Pages, Categories, Projects, Groups


@dataclass
class PermissionDefinition:
    definition: list[
        tuple[Union[Pages, Categories, Projects, Groups, General], Levels]
    ] = field(default_factory=list)
    permissions: dict = field(default_factory=dict)
    initialized: bool = False

    def initialize(self, user):
        for d in self.definition:
            if isinstance(d[0], (Pages, Categories, Projects, Groups)):
                resource = d[0].get(user)
                self.permissions[resource.entity.hash] = d[1].value
            elif isinstance(d[0], General):
                self.permissions[d[0].value] = d[1].value
            else:
                raise ValueError(f"Invalid definition: {d}")
        self.initialized = True


set_general = PermissionDefinition(
    definition=[
        (General.MODELS, Levels.VIEW),
        (General.FORMS, Levels.VIEW),
        (General.USERS, Levels.VIEW),
    ]
)

set_entity_specific = PermissionDefinition(
    definition=[
        (Categories.test_create_category_manual_mode, Levels.EDIT),
        (Projects.test_create_project_manual_mode, Levels.PUBLISH),
        (Pages.test_create_page, Levels.EDIT),
        (Groups.test_set_general_permissions, Levels.ASSIGN),
    ]
)

user_one_category = PermissionDefinition(
    definition=[
        (Categories.test_create_category_manual_mode, Levels.EDIT),
    ]
)

all_create = PermissionDefinition(
    definition=[
        (General.USERS, Levels.CREATE),
        (General.MODELS, Levels.CREATE),
        (General.FORMS, Levels.CREATE),
    ]
)

admin_cannot_create_users = PermissionDefinition(
    definition=[
        (General.USERS, Levels.ASSIGN),
        (General.MODELS, Levels.CREATE),
        (General.FORMS, Levels.CREATE),
    ]
)

# Reusable general scopes (directory, nav, other pages)
general_models_view_only = PermissionDefinition(
    definition=[(General.MODELS, Levels.VIEW)],
)

general_forms_view_only = PermissionDefinition(
    definition=[(General.FORMS, Levels.VIEW)],
)

models_forms_view_only = PermissionDefinition(
    definition=[
        (General.MODELS, Levels.VIEW),
        (General.FORMS, Levels.VIEW),
    ],
)

general_users_view_only = PermissionDefinition(
    definition=[(General.USERS, Levels.VIEW)],
)

# Global models CREATE without forms access (e.g. category UI without form picker)
models_create_forms_none = PermissionDefinition(
    definition=[
        (General.MODELS, Levels.CREATE),
        (General.FORMS, Levels.NONE),
    ],
)

# Two categories at different entity levels (e.g. row actions)
two_categories_edit_and_delete = PermissionDefinition(
    definition=[
        (Categories.test_create_category_manual_mode, Levels.EDIT),
        (Categories.test_create_page, Levels.DELETE),
    ],
)

# Category ACL: VIEW on one page only (sibling page in same category has no access).
# Mirror UI-created groups: explicit RESTRICTED on the parent category when the group
# only grants a page (RESTRICTED is excluded from session restriction hashes but is
# stored on the user for permission resolution).
page_acl_one_visible = PermissionDefinition(
    definition=[
        (Categories.acl_two_pages_lab, Levels.RESTRICTED),
        (Pages.acl_lab_visible, Levels.VIEW),
        (Pages.acl_lab_document, Levels.VIEW),
    ],
)

# EDIT on allowed category + VIEW on denied sibling + FORMS VIEW; no global MODELS VIEW
single_category_create = PermissionDefinition(
    definition=[
        (Categories.acl_create_allowed, Levels.EDIT),
        (Categories.acl_create_denied, Levels.VIEW),
        (General.FORMS, Levels.VIEW),
    ],
)

specific_user_assigner = PermissionDefinition(
    definition=[
        (Groups.assignable_users, Levels.ASSIGN),
    ],
)
