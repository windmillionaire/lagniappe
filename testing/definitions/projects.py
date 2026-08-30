from enum import Enum

from ..resources import Project

from . import project_definitions as pd
from .base import ResourceEnumMixin


class Projects(ResourceEnumMixin, Enum):
    test_create_project_manual_mode = Project(definition=pd.create_project)
    test_navigate_to_project = test_create_project_manual_mode
    test_toolbar_loads = test_create_project_manual_mode
    test_star_project = test_create_project_manual_mode
    test_create_model_task = test_create_project_manual_mode
    test_create_model_task_with_form = test_create_project_manual_mode
    test_delete_project = Project(definition=pd.delete_project)
    test_create_project_ai_mode = Project(definition=pd.ai_generated)
    test_create_project_without_tasks = Project(definition=pd.without_tasks)
    test_create_project_without_document = Project(definition=pd.without_document)
    test_project_info_form = Project(definition=pd.edit_project_info)
    test_page_tasks_multi_model = Project(definition=pd.multi_model_project)
    test_filter_project = Project(definition=pd.filter_project)
    test_attach_project_to_task = Project(definition=pd.attach_project_to_task)
    test_document_history_created = Project(definition=pd.document_history_created)
    test_document_history_restore = Project(definition=pd.document_history)
    test_document_history_pinned = Project(definition=pd.document_history_pinned)
    test_readonly_document_visibility = Project(
        definition=pd.readonly_document_visibility
    )
    test_readonly_document_content = Project(
        definition=pd.readonly_document_content
    )
    test_untouched_document = Project(definition=pd.untouched_document)
    test_editor_markdown_table_paste = Project(definition=pd.editor_markdown_table)
    test_editor_plain_html_paste = Project(definition=pd.editor_plain_html_paste)
    test_editor_common_markdown_paste = Project(
        definition=pd.editor_common_markdown_paste
    )
    test_editor_markdown_source_paste = Project(
        definition=pd.editor_markdown_source_paste
    )
    test_editor_task_list = Project(definition=pd.editor_task_list)
    test_sync_document_collaboration = Project(
        definition=pd.sync_document_collaboration
    )
    test_sync_document_presence = Project(definition=pd.sync_document_presence)
    test_sync_document_contract = Project(definition=pd.sync_document_contract)
    test_offline_document_replay = Project(definition=pd.offline_document_replay)
    test_offline_document_retry = Project(definition=pd.offline_document_retry)
    test_offline_document_reload = Project(definition=pd.offline_document_reload)
    test_offline_document_concurrent_replay = Project(
        definition=pd.offline_document_concurrent_replay
    )

    # Editor tests (005c, 005e, 005f) - reuse existing project with document
    test_formatting_persists = test_create_project_manual_mode
    test_toolbar_buttons_visible = test_create_project_manual_mode
    test_editor_forms = test_create_project_manual_mode
