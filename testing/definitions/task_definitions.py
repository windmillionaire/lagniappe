"""
Page task definitions for testing.

Page tasks are tasks created on a specific page (vs quick tasks from home).

Maps to:
- Entity: lagniappe/core/entities/task.py
- Routes: lagniappe/web/routes/tasks/
- Templates: lagniappe/web/templates/pages/tasks.html
- View: src/script/views/page.mjs (task widget)
"""

from dataclasses import dataclass
from typing import Literal, Optional

from .due_date import DueDates
from .files import Files
from .forms import Forms
from .model_tasks import ModelTasks
from .pages import Pages
from .projects import Projects
from .site_pages import SitePages
from .submissions import Submissions
from .users import Users
from .submission_fields import SubmissionFields


@dataclass
class TaskDefinition:
    name: str
    origin: Literal[SitePages.HOME] | Pages
    description: str = ""
    due_date: Optional[DueDates] = None
    form: Optional[Forms] = None
    project: Optional[Projects] = None
    model_task: Optional[ModelTasks] = None
    assigned_to: Optional[Users] = None
    file: Optional[Files] = None
    submission: Optional[list[SubmissionFields]] = None


_task_history_fields = {
    field.id: field for field in Forms.test_task_history_form.value.definition.schema
}


create_page_task = TaskDefinition(
    name="Test Page Task",
    description="A task created on a page.",
    origin=Pages.test_create_page_task,
)

page_task_with_form = TaskDefinition(
    name="Page Task with Form",
    form=Forms.test_create_task_form,
    origin=Pages.test_create_page_task,
)

page_task_autofill = TaskDefinition(
    name="Autofill Evidence Task",
    description="Fill this task from evidence attached to its page.",
    form=Forms.test_task_history_form,
    origin=Pages.test_page_autofill,
)

page_task_to_complete = TaskDefinition(
    name="Complete This Task",
    origin=Pages.test_create_page_task,
)

today_task = TaskDefinition(
    name="Today Task",
    origin=SitePages.HOME,
    due_date=DueDates.personal_task_due_today,
)

recurring_home_task = TaskDefinition(
    name="Recurring Home Task",
    origin=SitePages.HOME,
    due_date=DueDates.personal_task_due_today,
)

four_days_task = TaskDefinition(
    name="Four Days Task",
    origin=SitePages.HOME,
    due_date=DueDates.personal_task_due_in_four_days,
)

postpone_task_due_date_to_tomorrow = TaskDefinition(
    name="Postpone Task Due Date to Tomorrow",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_today,
)

postpone_task_due_date_to_this_week = TaskDefinition(
    name="Postpone Task Due Date to This Week",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_today,
)

postpone_task_due_date_to_next_week = TaskDefinition(
    name="Postpone Task Due Date to Next Week",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_today,
)

postpone_task_due_date_to_no_due_date = TaskDefinition(
    name="Postpone Task Due Date to No Due Date",
    origin=SitePages.HOME,
    due_date=DueDates.personal_task_due_today,
)

page_task_with_project = TaskDefinition(
    name="Task With Project",
    description="Links a project from the create form (project combobox).",
    origin=Pages.test_create_page_task_with_project,
    project=Projects.test_create_project_manual_mode,
)

page_task_with_model_from_multi = TaskDefinition(
    name="Task From Multi Model Picker",
    description="Created by picking a model task from a project search.",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_multi_model_beta_with_form,
)

page_task_with_assignee = TaskDefinition(
    name="Assigned Page Task",
    origin=Pages.test_create_page_task,
)

page_task_with_due = TaskDefinition(
    name="Due Page Task",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_in_four_days,
)

page_task_move_pages = TaskDefinition(
    name="Move Between Pages Task",
    description="A task moved between page task lists with the pages selector.",
    origin=Pages.test_task_pages_move_source,
)

page_task_add_due_date = TaskDefinition(
    name="Add Due Date Page Task",
    origin=Pages.test_create_page_task,
)

page_task_remove_due_date = TaskDefinition(
    name="Remove Due Date Page Task",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_in_four_days,
)

page_task_due_today = TaskDefinition(
    name="Due Today Page Task",
    origin=Pages.test_create_page_task,
)

page_task_recurring_completion = TaskDefinition(
    name="Recurring Completion Page Task",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_today,
)

page_task_scheduled = TaskDefinition(
    name="Scheduled Page Task",
    origin=Pages.test_create_page_task,
)

page_task_remove_schedule = TaskDefinition(
    name="Remove Schedule Page Task",
    origin=Pages.test_create_page_task,
)

page_task_add_recurring = TaskDefinition(
    name="Add Recurring Page Task",
    origin=Pages.test_create_page_task,
)

page_task_update_settings = TaskDefinition(
    name="Task Settings Before",
    description="Original task settings description.",
    origin=Pages.test_create_page_task,
)

page_task_delete_from_page = TaskDefinition(
    name="Delete Page Task From Page",
    description="Page task deleted from the page task row.",
    origin=Pages.test_create_page_task,
)

task_index_delete_from_index = TaskDefinition(
    name="Delete Task From Task Index",
    description="Page task deleted from the global task index row.",
    origin=Pages.test_create_page_task,
)

page_task_attached_submission = TaskDefinition(
    name="Attached Task Form Submission",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
    submission=[
        SubmissionFields.INPUT.get(
            _task_history_fields["input-textab12"], "Task form text"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-datecd34"], "2026-06-15"
        ),
        SubmissionFields.INPUT.get(_task_history_fields["input-timeef56"], "14:30"),
        SubmissionFields.INPUT.get(_task_history_fields["input-numgh78"], "128"),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-emlij90"], "task-form@example.com"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-telkl12"], "5551234567"
        ),
    ],
)

page_task_update_state_submission = TaskDefinition(
    name="Task Update State Submission",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
    submission=[
        SubmissionFields.INPUT.get(
            _task_history_fields["input-textab12"], "Task update state text"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-datecd34"], "2026-06-16"
        ),
        SubmissionFields.INPUT.get(_task_history_fields["input-timeef56"], "10:45"),
        SubmissionFields.INPUT.get(_task_history_fields["input-numgh78"], "42"),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-emlij90"], "task-state@example.com"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-telkl12"], "5559876543"
        ),
    ],
)

page_task_completed_readonly_form = TaskDefinition(
    name="Completed Readonly Form Task",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
)

page_task_partial_completed_readonly_form = TaskDefinition(
    name="Completed Partial Readonly Form Task",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
    submission=Submissions.partial_task_history.get(),
)

page_task_create_while_open_existing = TaskDefinition(
    name="Open Task Before Creating Another",
    description="Existing task stays unambiguous while a new task is created.",
    origin=Pages.test_create_page_task,
)

page_task_create_while_open_new = TaskDefinition(
    name="Created While Another Task Is Open",
    description="New task created while another row is expanded.",
    origin=Pages.test_create_page_task,
)

page_task_refresh_create_dedupe = TaskDefinition(
    name="Refresh Create Dedupe Task",
    description=(
        "Task row remains unique when refresh and create reconciliation overlap."
    ),
    origin=Pages.test_create_page_task,
)

page_task_signature_submission = TaskDefinition(
    name="Signature Submission Task",
    description="Task form stores a signature image as an asset.",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_signature_form,
)

task_index_personal_today = TaskDefinition(
    name="Task Index Personal Today",
    description="Personal task due today for the global task index.",
    origin=SitePages.HOME,
    due_date=DueDates.personal_task_due_today,
)

task_index_page_active = TaskDefinition(
    name="Task Index Page Active",
    description="Undated page task for active task index rows.",
    origin=Pages.test_create_page_task,
)

task_index_due_future = TaskDefinition(
    name="Task Index Future Due",
    description="Future due-date task for task index ordering.",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_in_four_days,
)

task_index_assigned = TaskDefinition(
    name="Task Index Assigned",
    description="Assigned task for task index assignee columns.",
    origin=Pages.test_create_page_task,
    assigned_to=Users.create_user,
)

task_index_project_linked = TaskDefinition(
    name="Task Index Project Linked",
    description="Task linked to a project for index row navigation review.",
    origin=Pages.test_create_page_task,
    project=Projects.test_create_project_manual_mode,
)

task_index_model_form = TaskDefinition(
    name="Task Index Model Form",
    description="Task created from a model task with an attached form.",
    origin=Pages.test_create_page_task,
    project=Projects.test_page_tasks_multi_model,
    model_task=ModelTasks.test_multi_model_beta_with_form,
)

task_index_form_submission = TaskDefinition(
    name="Task Index Form Submission",
    description="Task with a saved attached-form submission for row navigation.",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
    submission=[
        SubmissionFields.INPUT.get(
            _task_history_fields["input-textab12"], "Task index form text"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-datecd34"], "2026-06-22"
        ),
        SubmissionFields.INPUT.get(_task_history_fields["input-timeef56"], "16:15"),
        SubmissionFields.INPUT.get(_task_history_fields["input-numgh78"], "77"),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-emlij90"], "task-index@example.com"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-telkl12"], "5554441212"
        ),
    ],
)

task_index_completed = TaskDefinition(
    name="Task Index Completed Contrast",
    description="Completed task that should not appear in the active task index.",
    origin=Pages.test_create_page_task,
)

page_review_active_task = TaskDefinition(
    name="Page Review Active Task",
    description="Open this task while reviewing the page task controls.",
    origin=Pages.test_page_review,
)

page_review_due_task = TaskDefinition(
    name="Page Review Due Task",
    description="Dated task for page task ordering and due-date controls.",
    origin=Pages.test_page_review,
    due_date=DueDates.personal_task_due_in_four_days,
)

page_review_assigned_task = TaskDefinition(
    name="Page Review Assigned Task",
    description="Assigned task for page visibility and assignment controls.",
    origin=Pages.test_page_review,
    assigned_to=Users.create_user,
)

page_review_project_task = TaskDefinition(
    name="Page Review Project Task",
    description="Task linked to a project from the page task settings.",
    origin=Pages.test_page_review,
    project=Projects.test_create_project_manual_mode,
)

page_review_form_task = TaskDefinition(
    name="Page Review Form Task",
    description="Task with an attached form submission for task detail review.",
    origin=Pages.test_page_review,
    form=Forms.test_task_history_form,
    submission=[
        SubmissionFields.INPUT.get(
            _task_history_fields["input-textab12"], "Seeded task form text"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-datecd34"], "2026-06-18"
        ),
        SubmissionFields.INPUT.get(_task_history_fields["input-timeef56"], "09:45"),
        SubmissionFields.INPUT.get(_task_history_fields["input-numgh78"], "64"),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-emlij90"], "page-review-task@example.com"
        ),
        SubmissionFields.INPUT.get(
            _task_history_fields["input-telkl12"], "5558675309"
        ),
    ],
)

page_review_completed_task = TaskDefinition(
    name="Page Review Completed Task",
    description="Completed task for the collapsible completed section.",
    origin=Pages.test_page_review,
)

page_task_with_file = TaskDefinition(
    name="Task With File",
    origin=Pages.test_create_page_task,
)


project_filter_task = TaskDefinition(
    name="Project Filter Task",
    origin=Pages.test_create_page_task,
    project=Projects.test_filter_project,
)

project_filter_permission_visible = TaskDefinition(
    name="Permission Filter Visible Task",
    origin=Pages.test_create_page_task,
    project=Projects.test_filter_project,
)

project_filter_permission_hidden = TaskDefinition(
    name="Permission Filter Hidden Task",
    origin=Pages.test_create_page_task,
    project=Projects.test_filter_project,
)

filter_task_with_due_date = TaskDefinition(
    name="Filter Due Date Task",
    origin=Pages.test_create_page_task,
    project=Projects.test_filter_project,
    due_date=DueDates.personal_task_due_in_four_days,
)

filter_task_completed = TaskDefinition(
    name="Filter Completed Task",
    origin=Pages.test_create_page_task,
    project=Projects.test_filter_project,
)

filter_task_with_model = TaskDefinition(
    name="Model Filtered Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_filter_by_model_task,
    project=Projects.test_filter_project,
)

status_filter_task_completed = TaskDefinition(
    name="Completed Status Filter Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_status_filter_model_task,
    project=Projects.test_filter_project,
)

status_filter_task_in_progress = TaskDefinition(
    name="In Progress Status Filter Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_status_filter_model_task,
    project=Projects.test_filter_project,
)

filter_task_assigned = TaskDefinition(
    name="Assigned Filter Task",
    origin=Pages.test_create_page_task,
    project=Projects.test_filter_project,
    assigned_to=Users.create_user,
)

filter_task_attached_form_match = TaskDefinition(
    name="Attached Form Match Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_filter_by_attached_form,
    project=Projects.test_filter_project,
    submission=[
        SubmissionFields.INPUT.get("filter-notes", "Urgent permit packet"),
        SubmissionFields.INPUT.get("filter-score", "92"),
        SubmissionFields.CHECKBOX.get("filter-flagged", True),
        SubmissionFields.SELECT.get("filter-decision", "approved"),
        SubmissionFields.TABLE.get(
            "filter-items",
            {"rows": [{"filter-row-note": "Escalated item"}]},
        ),
    ],
)

filter_task_attached_form_nonmatch = TaskDefinition(
    name="Attached Form Nonmatch Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_filter_by_attached_form,
    project=Projects.test_filter_project,
    submission=[
        SubmissionFields.INPUT.get("filter-notes", "Routine archive packet"),
        SubmissionFields.INPUT.get("filter-score", "41"),
        SubmissionFields.CHECKBOX.get("filter-flagged", False),
        SubmissionFields.SELECT.get("filter-decision", "needs-review"),
    ],
)

filter_task_status_active = TaskDefinition(
    name="Status Active Filter Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_filter_by_status_form,
    project=Projects.test_filter_project,
    submission=[
        SubmissionFields.CHECKBOX.get("status-reorder", True),
        SubmissionFields.INPUT.get("status-approved-by", "Supervisor A"),
    ],
)

filter_task_status_inactive = TaskDefinition(
    name="Status Inactive Filter Task",
    origin=Pages.test_create_page_task,
    model_task=ModelTasks.test_filter_by_status_form,
    project=Projects.test_filter_project,
    submission=[
        SubmissionFields.CHECKBOX.get("status-reorder", False),
    ],
)

view_only_page_task = TaskDefinition(
    name="View Only Page Task",
    origin=Pages.acl_lab_visible,
)

view_only_page_task_with_empty_form = TaskDefinition(
    name="View Only Page Form Task",
    origin=Pages.acl_lab_visible,
    form=Forms.test_task_history_form,
)

home_view_only_page_task = TaskDefinition(
    name="Home View Only Page Task",
    origin=Pages.acl_lab_visible,
    due_date=DueDates.personal_task_due_today,
)

assigned_permission_task = TaskDefinition(
    name="Assigned Permission Task",
    origin=Pages.test_create_page_task,
    assigned_to=Users.create_user,
)

mobile_index_task = TaskDefinition(
    name="Mobile Index Task",
    origin=Pages.test_create_page_task,
    due_date=DueDates.personal_task_due_in_four_days,
)

history_task = TaskDefinition(
    name="History Task",
    origin=Pages.test_create_page_task,
)

history_form_task = TaskDefinition(
    name="History Form Task",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
)

history_fill_task = TaskDefinition(
    name="History Fill Task",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_form,
    submission=[
        SubmissionFields.INPUT.get(
            _task_history_fields["input-textab12"], "Historical text value"
        ),
        SubmissionFields.INPUT.get(_task_history_fields["input-numgh78"], "42"),
    ],
)

history_table_task = TaskDefinition(
    name="History Table Task",
    origin=Pages.test_create_page_task,
    form=Forms.test_task_history_table_form,
    submission=[
        SubmissionFields.INPUT.get("headline", "History table headline"),
        SubmissionFields.TABLE.get("items", {"rows": [{"row_note": "History row"}]}),
    ],
)
