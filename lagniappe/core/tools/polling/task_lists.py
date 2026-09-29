"""Conservative HTTP validators for quiet, unchanged Page task lists."""

import hashlib
import json

from lagniappe.core.tools.database.core import DATA, KINDS
from lagniappe.core.tools.database import deferred_jobs


CONTENT_CHANNELS = ("categories", "projects", "pages", "tasks", "forms", "users")


# @testable true
# @tests tests_unit/test_024b_task_list_validation.py::test_snapshot_requires_complete_quiet_durable_state
# @tests tests_unit/test_024b_task_list_validation.py::test_snapshot_reuses_supplied_records_without_reading
# @matrix tasks cache : conditional-response durable-revision job-lifecycle
def snapshot_keys():
    """Known revision keys can share the request's initial entity lookup."""
    return (
        *(DATA.datastore.key("site", channel) for channel in CONTENT_CHANNELS),
        DATA.datastore.key(KINDS.site.value, deferred_jobs.DEFERRED_JOB_SCHEDULER_CONTROL_ID),
    )


# @testable true
# @tests tests_unit/test_024b_task_list_validation.py::test_snapshot_requires_complete_quiet_durable_state
# @tests tests_unit/test_024b_task_list_validation.py::test_snapshot_reuses_supplied_records_without_reading
# @matrix tasks cache : conditional-response durable-revision job-lifecycle
def quiet_snapshot(records=None):
    """Read existing revisions in one batch; unknown or busy state cannot shortcut.

    Scheduler membership includes terminal delivery, not just running providers.
    Its generation also detects a job that started and ended between requests.
    These are durable reads, never cached permission or content authorities.
    """
    *keys, control_key = snapshot_keys()
    if records is None:
        records = {row.key: row for row in DATA.datastore.get_multi([*keys, control_key])}
    control = records.get(control_key, {})
    if (
        control.get("schema_version") != deferred_jobs.DEFERRED_JOB_SCHEDULER_CONTROL_SCHEMA_VERSION
        or control.get("tracked_jobs") != []
        or control.get("active_jobs") != 0
        or control.get("desired_state") != "paused"
        or type(control.get("generation")) is not int
    ):
        return None
    revisions = [records.get(key, {}).get("fingerprint") for key in keys]
    if not all(isinstance(value, str) and value for value in revisions):
        return None
    return (*revisions, control["generation"])


# @testable true
# @tests tests_unit/test_024b_task_list_validation.py::test_validator_covers_viewer_and_preloaded_context
# @matrix tasks cache : conditional-response viewer-scope concurrent-load
def quiet_fingerprint(snapshot, page, user):
    """Bind the validator to the loaded auth graph, without new I/O."""
    roots = (page, user, user.page)
    context = {}
    for entity in roots:
        context[entity.urlsafe_key] = entity.fingerprint
        for related in entity.related_entities.values():
            context[related.urlsafe_key] = related.fingerprint
    payload = ["quiet-task-list-v1", snapshot, user.urlsafe_key, sorted(context.items())]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


# @testable true
# @tests tests_unit/test_024b_task_list_validation.py::test_operation_references_prevent_quiet_validator
# @matrix tasks cache : conditional-response operation-retention form-migration
def has_operation_dependencies(tasks):
    """Retained jobs/reviews can change or be purged without content revisions."""
    return any(
        task.deferred_job or task.db.get("autofill_reviews")
        or (task.form and task.form.db.get("pending_form_change"))
        for task in tasks
    )
