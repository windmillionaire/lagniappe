from dataclasses import dataclass

from .forms import Forms
from typing import Optional


@dataclass
class CategoryDefinition:
    name: str = ""
    form: Optional[Forms] = None
    description_for_ai: str = ""


create_category = CategoryDefinition(
    name="Test Category",
)

category_with_form = CategoryDefinition(
    name="Category with Form",
    form=Forms.test_create_category_with_form,
)

delete_category = CategoryDefinition(
    name="Deletable Category",
)

ai_generated = CategoryDefinition(
    description_for_ai="Create a category for keeping track of my books.",
)

starred_category = CategoryDefinition(
    name="Starred Category",
)

category_for_pages = CategoryDefinition(
    name="Category for Pages",
)

category_for_page_tasks = CategoryDefinition(
    name="Category for Page Tasks",
)

page_submission = CategoryDefinition(
    name="Page Submission Tests",
    form=Forms.test_page_with_default_category_form,
)

basic_inputs_submission = CategoryDefinition(
    name="Basic Inputs Submission",
    form=Forms.test_basic_inputs_form,
)

selection_types_submission = CategoryDefinition(
    name="Selection Types Submission",
    form=Forms.test_selection_types_form,
)

link_external_submission = CategoryDefinition(
    name="External Link Submission",
    form=Forms.test_link_external_form,
)

empty_category = CategoryDefinition(
    name="Empty Category",
)

category_info_update = CategoryDefinition(
    name="Category Info Update",
)

category_readonly_settings = CategoryDefinition(
    name="Category Readonly Settings",
    form=Forms.test_create_page_form,
)

category_filter_pages = CategoryDefinition(
    name="Category Filter Pages",
    form=Forms.test_category_filter_page_form,
)

category_table_pages = CategoryDefinition(
    name="Category Table Pages",
    form=Forms.test_category_table_page_form,
)

category_filter_extra = CategoryDefinition(
    name="Category Filter Extra",
)

category_filter_related_form_registration = CategoryDefinition(
    name="Category Filter Related Form Registration",
)

sync_form_pages = CategoryDefinition(
    name="Sync Form Pages",
    form=Forms.test_sync_page_form,
)

acl_two_pages_lab = CategoryDefinition(
    name="ACL Two Pages Lab",
)

acl_create_allowed = CategoryDefinition(
    name="ACL Create Allowed Cat",
)

acl_create_denied = CategoryDefinition(
    name="ACL Create Denied Cat",
)

page_access_restrictions = CategoryDefinition(
    name="Page Access Restrictions",
)
