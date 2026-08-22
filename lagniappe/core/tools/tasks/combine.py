import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from ...definitions import Action, Fetch, FetchReason
from ...entities import Entities
from ...exceptions import ValidationError
from .. import database
from .ordering import page_task_roots


_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/tasks/combine.py::combine_tasks
# @reason immutable result only carries the persisted combine outcome
@dataclass(frozen=True)
class TaskCombineResult:
    main: object
    removed: tuple
    histories: tuple


# @testable false
# @covered-by lagniappe/core/tools/tasks/combine.py::compatible_tasks
# @covered-by lagniappe/core/tools/tasks/combine.py::combine_tasks
# @reason exact page/model identity is exercised through both public combine boundaries
def _compatible(source, candidate, page):
    if not isinstance(source, Entities.TASK) or not isinstance(
        candidate, Entities.TASK
    ):
        return False
    if not isinstance(page, Entities.PAGE):
        return False
    if source.key == candidate.key:
        return False

    candidate_page_key = candidate.properties.page.key
    if not candidate_page_key or candidate_page_key != page.key:
        return False

    return source.properties.model.key == candidate.properties.model.key


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_combine_selects_completed_then_modified_main
# @features task-combine
# @dimensions winner completed-on modified deterministic-tie
def select_main_task(tasks):
    """Choose the task whose current state remains after a combination."""
    tasks = tuple(task for task in tasks if isinstance(task, Entities.TASK))
    if not tasks:
        raise ValidationError("No tasks were selected for combination")

    completed = tuple(task for task in tasks if task.completed_on is not None)
    candidates = completed or tasks
    if completed:
        return max(
            candidates,
            key=lambda task: (
                task.completed_on or _MIN_DATETIME,
                task.modified or _MIN_DATETIME,
                task.urlsafe_key,
            ),
        )

    return max(
        candidates,
        key=lambda task: (
            task.modified or _MIN_DATETIME,
            task.urlsafe_key,
        ),
    )


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
# @pairs task-combine:compatible task-combine:same-page
# @pairs task-combine:same-model task-combine:no-model
# @pairs task-combine:view-page task-combine:linked-page
def compatible_tasks(task, page, user):
    """Return delete-permitted peers owned by the page displaying ``task``."""
    if not isinstance(task, Entities.TASK) or not isinstance(page, Entities.PAGE):
        return ()

    ordered_roots = page_task_roots(page)
    if not any(root.key == task.key for root in ordered_roots):
        return ()

    loaded = {
        candidate.key: candidate
        for candidate in Entities.fetch(*ordered_roots, request=Fetch.direct())
        if isinstance(candidate, Entities.TASK)
    }
    return tuple(
        candidate
        for root in ordered_roots
        if (candidate := loaded.get(root.key))
        and _compatible(task, candidate, page)
        and candidate.allowed(Action.DELETE, user=user)
    )


# @testable false
# @covered-by lagniappe/core/tools/tasks/combine.py::combine_tasks
# @reason stable destination identities make the public two-phase combine retry-safe
def _history_key(main, source):
    source_key = source.urlsafe_key.encode("utf-8")
    digest = hashlib.sha256(source_key).hexdigest()
    identifier = f"combined-{source.entity_kind}-{digest}"
    return database.create_named_key("task_history", identifier, parent=main)


# @testable false
# @covered-by lagniappe/core/tools/tasks/combine.py::combine_tasks
# @reason source history expansion is part of the public migration operation
def _source_histories(tasks):
    keys = [
        history_key
        for task in tasks
        for history_key in database.get.task_history(task)
    ]
    if not keys:
        return ()
    return tuple(
        history
        for history in Entities.fetch(
            *keys,
            request=Fetch.nested(because=FetchReason.TASK_COMBINE_REQUIREMENTS),
        )
        if isinstance(history, Entities.TASK_HISTORY)
    )


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
# @pairs task-combine:migrate-history task-combine:current-snapshot
# @pairs task-combine:existing-history task-combine:attachments
# @pairs task-combine:delete task-combine:winner task-combine:completed-on
def combine_tasks(task, selected_keys, page, user):
    """Combine ``task`` with selected compatible peers and return the outcome."""
    selected_keys = tuple(selected_keys or ())
    if not selected_keys:
        raise ValidationError("Select at least one compatible task")
    if any(not isinstance(key, str) or not key for key in selected_keys):
        raise ValidationError("One or more selected tasks can no longer be combined")
    if (
        len(set(selected_keys)) != len(selected_keys)
        or task.urlsafe_key in selected_keys
    ):
        raise ValidationError("One or more selected tasks can no longer be combined")

    loaded = Entities.fetch(
        task.urlsafe_key,
        *selected_keys,
        request=Fetch.nested(because=FetchReason.TASK_COMBINE_REQUIREMENTS),
    )
    loaded_by_key = {
        candidate.urlsafe_key: candidate
        for candidate in loaded
        if isinstance(candidate, Entities.TASK)
    }
    current = loaded_by_key.get(task.urlsafe_key)
    selected = tuple(loaded_by_key.get(key) for key in selected_keys)
    if not current or any(candidate is None for candidate in selected):
        raise ValidationError("One or more selected tasks can no longer be combined")

    if not isinstance(page, Entities.PAGE) or not any(
        root.key == current.key for root in page_task_roots(page)
    ):
        raise ValidationError("One or more selected tasks can no longer be combined")

    combined = (current, *selected)
    if not current.allowed(Action.DELETE, user=user) or any(
        not _compatible(current, candidate, page)
        or not candidate.allowed(Action.DELETE, user=user)
        for candidate in selected
    ):
        raise ValidationError("One or more selected tasks can no longer be combined")

    main = select_main_task(combined)
    removed = tuple(candidate for candidate in combined if candidate.key != main.key)
    old_histories = _source_histories(removed)
    migrated = []

    for source in (*removed, *old_histories):
        migrated.append(
            main.create_history_entry(
                history_key=_history_key(main, source),
                source=source,
            )
        )

    main.save()
    Entities.delete(*removed, *old_histories)
    return TaskCombineResult(main, removed, tuple(migrated))
