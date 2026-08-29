from ..mixins import RelatedEntityListMixin, RelatedEntityMixin
from .base_db import DBProperty


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_lists_pages_that_reference_it
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_page_shows_linked_page_and_task_badges
# @matrix file : attached-pages badges permissions reverse-links
class AttachedToPages(RelatedEntityListMixin, DBProperty):
    """Pages that a file is attached to (permission-checked on get)."""

    _id = "pages"
    _kind = "page"
    _label = "Pages"
    _icon = "page"


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_file_reverse_task_links_drive_permissions_and_references
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_page_shows_linked_page_and_task_badges
# @matrix file : attached-tasks badges permissions reverse-links
class AttachedToTasks(RelatedEntityListMixin, DBProperty):
    """Tasks and task history entries that reference a file."""

    _id = "tasks"
    _kind = "task"
    _label = "Tasks"
    _icon = "task"
    _touch_members = False


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_file_is_viewable_only_by_submitter_or_owner
# @matrix ai-email files : temporary-view-ownership
class ReportUser(RelatedEntityMixin, DBProperty):
    """Submitting user temporarily allowed to view a report-only email file."""

    _id = "report_user"
    _kind = "user"
