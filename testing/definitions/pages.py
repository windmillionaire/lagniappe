"""
Page entity definitions enum.

Pages are created within categories, so each PageEntities member requires
a matching Categories member with the same name.

Maps to:
- Entity: lagniappe/core/entities/page.py
- Routes: lagniappe/web/routes/pages/
- Templates: lagniappe/web/templates/pages/
- View: src/script/views/page.mjs
"""

from enum import Enum

from ..resources import Page

from . import page_definitions as pd
from .base import ResourceEnumMixin


class Pages(ResourceEnumMixin, Enum):
    test_create_page = Page(definition=pd.create_page)
    test_page_loads = test_create_page
    test_delete_page = Page(definition=pd.page_to_delete)
    test_navigate_to_page = test_create_page
    test_star_page = test_create_page
    test_create_page_task = Page(definition=pd.page_for_tasks)
    test_empty_page_task_list = Page(definition=pd.empty_page_task_list)
    test_create_page_task_with_project = Page(definition=pd.page_for_tasks_with_project)
    test_task_pages_move_source = Page(definition=pd.task_pages_move_source)
    test_task_pages_move_target = Page(definition=pd.task_pages_move_target)
    test_complete_page_task = test_create_page_task
    test_page_with_default_category_form = Page(
        definition=pd.default_category_form_page
    )
    test_switch_page_form = Page(definition=pd.switch_page_form)

    # Submission tests by field type
    test_basic_input_submission = Page(definition=pd.basic_inputs_page)
    test_page_autofill = Page(definition=pd.autofill_page)
    test_page_review = Page(definition=pd.page_review_workspace)
    test_selection_submission = Page(definition=pd.selection_types_page)
    test_link_submission = Page(definition=pd.link_external_page)
    test_table_submission = Page(definition=pd.table_submission_page)
    test_category_table_expansion = Page(
        definition=pd.category_table_expansion_page
    )

    acl_lab_visible = Page(definition=pd.acl_lab_visible)
    acl_lab_document = Page(definition=pd.acl_lab_document)
    acl_lab_hidden = Page(definition=pd.acl_lab_hidden)
    test_owner_restricted_page = Page(definition=pd.owner_restricted_page)
    test_group_restricted_page = Page(definition=pd.group_restricted_page)
    test_document_visibility_page = Page(definition=pd.document_visibility_page)
    test_file_upload_page = Page(definition=pd.file_upload_page)
    test_category_edit_page = Page(definition=pd.category_edit_page)
    test_image_page = Page(definition=pd.image_page)
    test_generated_image_page = Page(definition=pd.generated_image_page)
    test_document_generation_page = Page(definition=pd.document_generation_page)
    test_document_generation_selection_page = Page(
        definition=pd.document_generation_selection_page
    )
    test_category_filter_match_page = Page(
        definition=pd.category_filter_match_page
    )
    test_category_filter_nonmatch_page = Page(
        definition=pd.category_filter_nonmatch_page
    )
    test_category_filter_permission_visible = Page(
        definition=pd.category_filter_permission_visible
    )
    test_category_filter_permission_hidden = Page(
        definition=pd.category_filter_permission_hidden
    )
    test_category_filter_public_document_page = Page(
        definition=pd.category_filter_public_document_page
    )
    test_category_filter_related_form_registration_page = Page(
        definition=pd.category_filter_related_form_registration_page
    )
    test_category_sort_zebra_page = Page(definition=pd.category_sort_zebra_page)
    test_category_sort_alpha_page = Page(definition=pd.category_sort_alpha_page)
    test_category_sort_mango_page = Page(definition=pd.category_sort_mango_page)
    test_sync_form_page = Page(definition=pd.sync_form_page)
    test_sync_form_submit_page = Page(definition=pd.sync_form_submit_page)
    test_offline_sync_form_page = Page(definition=pd.offline_sync_form_page)
