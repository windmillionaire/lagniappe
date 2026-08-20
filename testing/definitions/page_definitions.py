"""
Page entity definitions for testing.

Maps to:
- Entity: lagniappe/core/entities/page.py
- Routes: lagniappe/web/routes/pages/
- Templates: lagniappe/web/templates/pages/
- View: src/script/views/page.mjs
"""

from dataclasses import dataclass, field
from typing import Optional

from .categories import Categories
from .forms import Forms
from .submissions import Submissions


@dataclass
class PageDefinition:
    name: str
    category: Categories
    description: str = ""
    form: Optional[Forms] = None
    submission: Optional[Submissions] = None
    attributes: list = field(
        default_factory=lambda: [
            "tasks",
            "document",
            "notes",
            "files",
            "photo",
        ]
    )

    @property
    def defaults(self):
        return ["tasks", "document", "notes", "files", "photo"]


create_page = PageDefinition(
    name="Test Page",
    description="A test page created from category index.",
    category=Categories.test_create_page,
)

page_with_form = PageDefinition(
    name="Page with Form",
    form=Forms.test_create_page_form,
    category=Categories.test_create_page,
)

page_for_tasks = PageDefinition(
    name="Page for Tasks",
    description="A page used for testing task creation.",
    attributes=["tasks"],
    category=Categories.test_create_page_task,
)

empty_page_task_list = PageDefinition(
    name="Empty Page Task List",
    description="A page reserved for testing the empty task-list state.",
    attributes=["tasks"],
    category=Categories.test_create_page_task,
)

page_for_tasks_with_project = PageDefinition(
    name="Attach Project to Task",
    description="A page used for testing task creation with a project.",
    attributes=["tasks"],
    category=Categories.test_create_page_task,
)

task_pages_move_source = PageDefinition(
    name="Task Pages Source",
    description="A page used for moving a task between page task lists.",
    attributes=["tasks"],
    category=Categories.test_create_page_task,
)

task_pages_move_target = PageDefinition(
    name="Task Pages Target",
    description="A page that receives a task from another page.",
    attributes=["tasks"],
    category=Categories.test_create_page_task,
)


page_to_delete = PageDefinition(
    name="Deletable Page",
    description="A page created for testing deletion.",
    category=Categories.test_create_page,
)

default_category_form_page = PageDefinition(
    name="Submission Test Page",
    description="A page for testing page form submissions with default category form.",
    category=Categories.test_create_page_submission,
)

basic_inputs_page = PageDefinition(
    name="Basic Inputs Page",
    category=Categories.test_basic_inputs_submission,
)

autofill_page = PageDefinition(
    name="Autofill Evidence Page",
    description="A page with attached evidence for deferred autofill tests.",
    category=Categories.test_basic_inputs_submission,
    attributes=["tasks", "files"],
)

page_review_workspace = PageDefinition(
    name="Page Review Workspace",
    description=(
        "Seeded page for exploratory browser review with form data, page tabs, "
        "and related tasks."
    ),
    category=Categories.test_basic_inputs_submission,
    submission=Submissions.basic_inputs,
)

selection_types_page = PageDefinition(
    name="Selection Types Page",
    category=Categories.test_selection_types_submission,
)

link_external_page = PageDefinition(
    name="External Link Page",
    category=Categories.test_link_external_submission,
)

table_submission_page = PageDefinition(
    name="Table Submission Page",
    category=Categories.test_category_table_pages,
    submission=Submissions.category_table,
)

category_table_expansion_page = PageDefinition(
    name="Category Table Expansion Page",
    category=Categories.test_category_table_pages,
    submission=Submissions.category_table,
)

acl_lab_visible = PageDefinition(
    name="ACL Visible Page",
    description="Page the page-ACL user can see.",
    category=Categories.acl_two_pages_lab,
)

acl_lab_document = PageDefinition(
    name="ACL Document Page",
    description="Page the page-ACL user can read when document content exists.",
    category=Categories.acl_two_pages_lab,
)

acl_lab_hidden = PageDefinition(
    name="ACL Hidden Page",
    description="Page the page-ACL user should not see.",
    category=Categories.acl_two_pages_lab,
)

switch_page_form = PageDefinition(
    name="Switch Page Form",
    description="A page for testing switching page forms.",
    category=Categories.test_create_page_submission,
)

owner_restricted_page = PageDefinition(
    name="Owner Restricted Page",
    description="A page the owner narrows to owner-only access.",
    category=Categories.test_page_access_restrictions,
)

group_restricted_page = PageDefinition(
    name="Group Restricted Page",
    description="A page the owner narrows to a specific user group.",
    category=Categories.test_page_access_restrictions,
)

document_visibility_page = PageDefinition(
    name="Document Visibility Page",
    description="A page used for public/private document visibility tests.",
    category=Categories.test_create_page,
)

file_upload_page = PageDefinition(
    name="File Upload Page",
    description="A page used for testing files tab uploads.",
    category=Categories.test_create_page,
)

category_edit_page = PageDefinition(
    name="Category Edit Page",
    description="A page used for testing category add/remove from page info.",
    category=Categories.test_create_page,
)

image_page = PageDefinition(
    name="Image Page",
    description="A page used for testing page image upload, paste, and remove.",
    category=Categories.test_create_page,
)

generated_image_page = PageDefinition(
    name="Generated Image Page",
    description="A page used for testing AI-generated page images.",
    category=Categories.test_create_page,
)

document_generation_page = PageDefinition(
    name="Document Generation Page",
    description="A page used for testing AI text generation in page documents.",
    category=Categories.test_create_page,
)

document_generation_selection_page = PageDefinition(
    name="Document Generation Selection Page",
    description="A page used for testing AI text generation with selected text.",
    category=Categories.test_create_page,
)

category_filter_match_page = PageDefinition(
    name="Category Filter Urgent Page",
    description="Urgent permit packet ready for review.",
    category=Categories.test_category_filter_pages,
    submission=Submissions.category_filter_match,
)

category_filter_nonmatch_page = PageDefinition(
    name="Category Filter Routine Page",
    description="Routine archive packet ready.",
    category=Categories.test_category_filter_pages,
    submission=Submissions.category_filter_nonmatch,
)

category_filter_permission_visible = PageDefinition(
    name="Category Permission Filter Visible Page",
    description="Page visible to a general category viewer.",
    category=Categories.test_category_filter_pages,
)

category_filter_permission_hidden = PageDefinition(
    name="Category Permission Filter Hidden Page",
    description="Page hidden from a general category viewer.",
    category=Categories.test_category_filter_pages,
)

category_filter_public_document_page = PageDefinition(
    name="Category Filter Public Document Page",
    description="Published memo with a document asset.",
    category=Categories.test_category_filter_pages,
)

category_filter_related_form_registration_page = PageDefinition(
    name="Category Filter Related Form Page",
    description="Page used to register a page-specific form with category filters.",
    category=Categories.test_category_filter_related_form_registration,
    form=Forms.test_category_filter_page_form,
)

category_sort_zebra_page = PageDefinition(
    name="Zebra Page",
    category=Categories.test_create_page,
)

category_sort_alpha_page = PageDefinition(
    name="Alpha Page",
    category=Categories.test_create_page,
)

category_sort_mango_page = PageDefinition(
    name="Mango Page",
    category=Categories.test_create_page,
)

sync_form_page = PageDefinition(
    name="Sync Form Page",
    description="Page used for collaborative form sync tests.",
    category=Categories.test_sync_form_pages,
    submission=Submissions.sync_form_initial,
)

sync_form_submit_page = PageDefinition(
    name="Sync Form Submit Page",
    description="Page used to prove form sync is not a durable submit.",
    category=Categories.test_sync_form_pages,
    submission=Submissions.sync_form_submit_initial,
)

offline_sync_form_page = PageDefinition(
    name="Offline Sync Form Page",
    description="Page used for offline form replay tests.",
    category=Categories.test_sync_form_pages,
    submission=Submissions.offline_sync_form_initial,
)
