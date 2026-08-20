"""
Task definitions enum (page tasks and personal / home tasks).

Page tasks are created on pages, so each page-task member that uses a
Pages-based definition requires a matching TestPages member with the same
name where applicable.

Maps to:
- Entity: lagniappe/core/entities/task.py
- Routes: lagniappe/web/routes/tasks/
- Templates: lagniappe/web/templates/pages/tasks.html, home/tasks.html
- View: src/script/views/page.mjs, home.mjs

Test Framework:
- testing/definitions/task_definitions.py: TaskDefinition dataclass
- testing/resources/task.py: Task resource (programmatic create)
- testing/resources/home.py: HomePage.create_personal_task for UI creation

Additional page-task scenarios (project, model task, assignee, due date, file placeholder)
are defined in ``task_definitions.py`` and exposed as ``Tasks.test_create_page_task_*`` members.
"""

from enum import Enum

from ..resources import Task

from . import task_definitions as td
from .base import ResourceEnumMixin


class Tasks(ResourceEnumMixin, Enum):
    test_create_page_task = Task(definition=td.create_page_task)
    test_create_page_task_with_form = Task(definition=td.page_task_with_form)
    test_task_autofill = Task(definition=td.page_task_autofill)
    test_complete_page_task = Task(definition=td.page_task_to_complete)
    test_create_personal_task_due_today = Task(definition=td.today_task)
    test_complete_recurring_task_from_home_page = Task(
        definition=td.recurring_home_task
    )
    test_create_personal_task_due_in_four_days = Task(definition=td.four_days_task)
    test_complete_task_from_home_page = test_create_personal_task_due_today
    test_postpone_task_due_date_to_tomorrow = Task(
        definition=td.postpone_task_due_date_to_tomorrow
    )
    test_postpone_task_due_date_to_this_week = Task(
        definition=td.postpone_task_due_date_to_this_week
    )
    test_postpone_task_due_date_to_next_week = Task(
        definition=td.postpone_task_due_date_to_next_week
    )
    test_postpone_task_due_date_to_no_due_date = Task(
        definition=td.postpone_task_due_date_to_no_due_date
    )
    test_create_page_task_with_project = Task(definition=td.page_task_with_project)
    test_create_page_task_with_model_task = Task(
        definition=td.page_task_with_model_from_multi
    )
    test_create_page_task_with_assigned_to = Task(definition=td.page_task_with_assignee)
    test_create_page_task_with_file = Task(definition=td.page_task_with_file)
    test_create_page_task_with_due_date = Task(definition=td.page_task_with_due)
    test_page_task_add_due_date = Task(definition=td.page_task_add_due_date)
    test_page_task_remove_due_date = Task(definition=td.page_task_remove_due_date)
    test_page_task_due_today = Task(definition=td.page_task_due_today)
    test_page_task_move_pages = Task(definition=td.page_task_move_pages)
    test_page_task_repeats_when_completed = Task(
        definition=td.page_task_recurring_completion
    )
    test_page_task_add_schedule = Task(definition=td.page_task_scheduled)
    test_page_task_remove_schedule = Task(definition=td.page_task_remove_schedule)
    test_page_task_add_recurring = Task(definition=td.page_task_add_recurring)
    test_update_page_task_settings = Task(definition=td.page_task_update_settings)
    test_delete_page_task_from_page = Task(definition=td.page_task_delete_from_page)
    test_task_index_delete_from_index = Task(
        definition=td.task_index_delete_from_index
    )
    test_submit_attached_task_form = Task(definition=td.page_task_attached_submission)
    test_task_update_preserves_open_widget = Task(
        definition=td.page_task_update_state_submission
    )
    test_task_revision_review = Task(
        definition=td.page_task_revision_review_submission
    )
    test_completed_task_readonly_form = Task(
        definition=td.page_task_completed_readonly_form
    )
    test_completed_partial_task_readonly_form = Task(
        definition=td.page_task_partial_completed_readonly_form
    )
    test_create_while_open_existing = Task(
        definition=td.page_task_create_while_open_existing
    )
    test_create_while_open_new = Task(definition=td.page_task_create_while_open_new)
    test_page_task_refresh_create_dedupe = Task(
        definition=td.page_task_refresh_create_dedupe
    )
    test_signature_submission = Task(definition=td.page_task_signature_submission)
    test_task_index_personal_today = Task(definition=td.task_index_personal_today)
    test_task_index_page_active = Task(definition=td.task_index_page_active)
    test_task_index_due_future = Task(definition=td.task_index_due_future)
    test_task_index_assigned = Task(definition=td.task_index_assigned)
    test_task_index_project_linked = Task(definition=td.task_index_project_linked)
    test_task_index_model_form = Task(definition=td.task_index_model_form)
    test_task_index_form_submission = Task(definition=td.task_index_form_submission)
    test_task_index_completed = Task(definition=td.task_index_completed)
    test_page_review_active = Task(definition=td.page_review_active_task)
    test_page_review_due = Task(definition=td.page_review_due_task)
    test_page_review_assigned = Task(definition=td.page_review_assigned_task)
    test_page_review_project = Task(definition=td.page_review_project_task)
    test_page_review_form = Task(definition=td.page_review_form_task)
    test_page_review_completed = Task(definition=td.page_review_completed_task)

    # Project filter tests
    test_filter_by_task_name = Task(definition=td.project_filter_task)
    test_filter_permission_visible = Task(
        definition=td.project_filter_permission_visible
    )
    test_filter_permission_hidden = Task(
        definition=td.project_filter_permission_hidden
    )
    test_filter_by_due_date = Task(definition=td.filter_task_with_due_date)
    test_filter_by_completed = Task(definition=td.filter_task_completed)
    test_filter_by_model_task = Task(definition=td.filter_task_with_model)
    test_status_filter_completed = Task(definition=td.status_filter_task_completed)
    test_status_filter_in_progress = Task(definition=td.status_filter_task_in_progress)
    test_filter_by_assigned_user = Task(definition=td.filter_task_assigned)
    test_filter_by_attached_form_match = Task(
        definition=td.filter_task_attached_form_match
    )
    test_filter_by_attached_form_nonmatch = Task(
        definition=td.filter_task_attached_form_nonmatch
    )
    test_filter_by_has_status_active = Task(definition=td.filter_task_status_active)
    test_filter_by_has_status_inactive = Task(definition=td.filter_task_status_inactive)
    test_view_only_page_task = Task(definition=td.view_only_page_task)
    test_completed_only_page_task = Task(definition=td.completed_only_page_task)
    test_view_only_page_task_with_empty_form = Task(
        definition=td.view_only_page_task_with_empty_form
    )
    test_home_view_only_page_task = Task(definition=td.home_view_only_page_task)
    test_assigned_permission_task = Task(definition=td.assigned_permission_task)
    test_assigned_due_permission_task = Task(
        definition=td.assigned_due_permission_task
    )
    test_mobile_index_task = Task(definition=td.mobile_index_task)
    test_history_task = Task(definition=td.history_task)
    test_history_form_task = Task(definition=td.history_form_task)
    test_history_fill_task = Task(definition=td.history_fill_task)
    test_history_table_task = Task(definition=td.history_table_task)
