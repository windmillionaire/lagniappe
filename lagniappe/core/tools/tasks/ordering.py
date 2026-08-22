"""Canonical ordering for task collections."""

from ...definitions import Fetch
from ...entities import Entities
from .. import database


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_sort_tasks
# @features utility
# @dimensions task-sorting
def sort_tasks(tasks):
    """Sort due tasks ascending, then undated tasks by recent modification."""
    with_due_date = [task for task in tasks if task.due_date]
    without_due_date = [task for task in tasks if not task.due_date]
    return sorted(with_due_date, key=lambda task: task.due_date) + sorted(
        without_due_date,
        key=lambda task: task.modified,
        reverse=True,
    )


# @testable false
# @covered-by lagniappe/core/tools/polling/refresh.py::load_refresh_collection
# @covered-by lagniappe/web/responses.py::task_combine_delta
# @reason page-task root ordering is exercised through its collection and delta consumers
def page_task_roots(page):
    """Load one page's root tasks in canonical active/completed order."""
    roots = Entities.fetch(
        *database.get.page_tasks(page),
        request=Fetch.root(),
    )
    tasks = [task for task in roots if isinstance(task, Entities.TASK)]
    active = sort_tasks([task for task in tasks if not task.completed])
    completed = sorted(
        [task for task in tasks if task.completed],
        key=lambda task: task.modified,
        reverse=True,
    )
    return active + completed
