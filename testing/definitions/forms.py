from enum import Enum

from ..resources import Form

from . import form_definitions as fd


class Forms(Enum):
    test_create_category_with_form = Form(definition=fd.basic_page_form)
    test_create_page_form = Form(definition=fd.create_page_form)
    test_create_task_form = Form(definition=fd.basic_task_form)
    test_alternate_task_form = Form(definition=fd.alternate_task_form)
    test_add_inputs_to_form = Form(definition=fd.add_inputs)
    test_add_fields_to_form = Form(definition=fd.add_fields)
    test_delete_components = Form(definition=fd.builder_delete_components)
    test_change_select_options = Form(definition=fd.builder_select_options)
    test_field_visibility = Form(definition=fd.builder_field_visibility)
    test_field_visibility_select_multiple_values = Form(
        definition=fd.builder_select_visibility
    )
    test_table_column_condition_editor = Form(definition=fd.builder_table_columns)
    test_status_message_condition_editor = Form(definition=fd.builder_status_messages)
    test_signature_field_builder_unique_component = Form(
        definition=fd.builder_signature_unique
    )
    test_html_field = Form(definition=fd.builder_html_field)
    test_drag_component = Form(definition=fd.builder_drag_component)
    test_preview_panel = Form(definition=fd.preview_panel_form)
    test_page_with_default_category_form = Form(definition=fd.page_submission_test)
    test_basic_inputs_form = Form(definition=fd.basic_inputs_form)
    test_selection_types_form = Form(definition=fd.selection_types_form)
    test_link_external_form = Form(definition=fd.link_external_form)
    test_owner_restricted_form = Form(definition=fd.owner_restricted_form)
    test_group_restricted_form = Form(definition=fd.group_restricted_form)
    test_index_restricted_form = Form(definition=fd.index_restricted_form)
    test_task_history_form = Form(definition=fd.task_history_form)
    test_task_signature_form = Form(definition=fd.task_signature_form)
    test_task_status_form = Form(definition=fd.task_status_form)
    test_task_history_table_form = Form(definition=fd.task_history_table_form)
    test_project_filter_task_form = Form(definition=fd.project_filter_task_form)
    test_category_filter_page_form = Form(definition=fd.category_filter_page_form)
    test_category_table_page_form = Form(definition=fd.category_table_page_form)
    test_sync_page_form = Form(definition=fd.sync_page_form)

    def get(self, user=None, create=True):
        self.value.user = user
        if not self.value.entity and create:
            return self.value.create()
        return self.value
