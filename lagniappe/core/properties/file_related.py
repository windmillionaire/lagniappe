from ..mixins import RelatedEntityListMixin
from .base_db import DBProperty


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_lists_pages_that_reference_it
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_page_shows_linked_page_and_task_badges
# @features file
# @dimensions attached-pages permissions reverse-links badges
class AttachedToPages(RelatedEntityListMixin, DBProperty):
    """Pages that a file is attached to (permission-checked on get)."""

    _id = "pages"
    _kind = "page"
    _label = "Pages"
    _icon = "page"


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_file_reverse_task_links_drive_permissions_and_references
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_page_shows_linked_page_and_task_badges
# @features file
# @dimensions attached-tasks permissions reverse-links badges
class AttachedToTasks(RelatedEntityListMixin, DBProperty):
    """Tasks and task history entries that reference a file."""

    _id = "tasks"
    _kind = "task"
    _label = "Tasks"
    _icon = "task"
    _touch_members = False
