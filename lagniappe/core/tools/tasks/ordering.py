"""Canonical ordering for task collections."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...entities.page import Page
    from ...entities.task import Task

from ...definitions import Fetch
from ...entities import Entities
from lagniappe.core.tools.database import get as database_get


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_sort_tasks
# @pair utility:task-sorting
def sort_tasks(tasks: Sequence[Task]) -> list[Task]:
    """Sort due tasks ascending, then undated tasks by recent modification."""
    with_due_date = [(due, task) for task in tasks if (due := task.due_date)]
    without_due_date = [task for task in tasks if not task.due_date]
    return [task for _, task in sorted(with_due_date, key=lambda pair: pair[0])] + sorted(
        without_due_date,
        key=lambda task: task.modified or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


# @testable false
# @covered-by lagniappe/core/tools/polling/refresh.py::load_refresh_collection
# @covered-by lagniappe/web/responses.py::task_combine_delta
# @reason page-task root ordering is exercised through its collection and delta consumers
def page_task_roots(page: Page) -> list[Task]:
    """Load one page's root tasks in canonical active/completed order."""
    roots = Entities.fetch(
        *database_get.page_tasks(page),
        request=Fetch.root(),
    )
    tasks = [task for task in roots if isinstance(task, Entities.TASK)]
    active = sort_tasks([task for task in tasks if not task.completed])
    completed = sorted(
        [task for task in tasks if task.completed],
        key=lambda task: task.modified or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return active + completed
