"""
Category definitions enum.

Maps to:
- Entity: lagniappe/core/entities/category.py
- Routes: lagniappe/web/routes/categories/
- Templates: lagniappe/web/templates/categories/
- View: src/script/views/category.mjs
"""

from enum import Enum

from ..resources import Category

from . import category_definitions as cd
from .base import ResourceEnumMixin


class Categories(ResourceEnumMixin, Enum):
    # Home page category tests
    test_create_category_manual_mode = Category(definition=cd.create_category)
    test_navigate_to_category = test_create_category_manual_mode
    test_star_category = Category(definition=cd.starred_category)
    test_delete_category = Category(definition=cd.delete_category)
    test_create_category_ai_mode = Category(definition=cd.ai_generated)
    test_create_category_with_form = Category(definition=cd.category_with_form)

    # Categories for page tests (pages are created within categories)
    test_create_page = Category(definition=cd.category_for_pages)
    test_create_page_task = Category(definition=cd.category_for_page_tasks)
    test_create_page_submission = Category(definition=cd.page_submission)

    # Categories for submission tests (each has a different form/schema)
    test_basic_inputs_submission = Category(definition=cd.basic_inputs_submission)
    test_selection_types_submission = Category(definition=cd.selection_types_submission)
    test_link_external_submission = Category(definition=cd.link_external_submission)

    test_empty_category = Category(definition=cd.empty_category)
    test_category_info_update = Category(definition=cd.category_info_update)
    test_category_readonly_settings = Category(
        definition=cd.category_readonly_settings
    )
    test_category_filter_pages = Category(definition=cd.category_filter_pages)
    test_category_table_pages = Category(definition=cd.category_table_pages)
    test_category_filter_extra = Category(definition=cd.category_filter_extra)
    test_category_filter_related_form_registration = Category(
        definition=cd.category_filter_related_form_registration
    )
    test_sync_form_pages = Category(definition=cd.sync_form_pages)

    acl_two_pages_lab = Category(definition=cd.acl_two_pages_lab)
    acl_create_allowed = Category(definition=cd.acl_create_allowed)
    acl_create_denied = Category(definition=cd.acl_create_denied)
    test_page_access_restrictions = Category(
        definition=cd.page_access_restrictions
    )
