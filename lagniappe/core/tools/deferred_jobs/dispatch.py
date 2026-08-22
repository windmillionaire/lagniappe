"""Cloud Tasks and local-provider dispatch for durable deferred jobs."""

import threading

from flask import current_app, url_for

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS,
    DEFERRED_JOB_FEEDBACK_DELAY_SECONDS,
)
from lagniappe.core.properties.deferred_job_dispatch import TaskIdentity
from lagniappe.core.properties.deferred_job_lifecycle import ACTIVE_STATUSES
from lagniappe.core.tools.services import task_queue

from .errors import DeferredJobInfrastructureError


_task_id = TaskIdentity.create
_feedback_task_id = TaskIdentity.feedback


# @testable infrastructure
class DeferredJobDispatch:
    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_production_dispatch_rejects_disabled_task_queue
    # @pair deferred-jobs:dispatch
    # @pair deferred-jobs:disabled-queue
    # @pair deferred-jobs:task-identity
    def dispatch(self, job, *, attempt, delay_seconds=0, task_suffix=None):
        adapter = self.adapter(job.job_type)
        if CONFIG.production:
            endpoint = url_for("process.deferred_job_process", _external=True)
            task_identity = task_queue.create_task(
                endpoint,
                {"job_key": job.urlsafe_key},
                delay_seconds,
                task_id=_task_id(job, attempt, suffix=task_suffix),
                dispatch_deadline_seconds=DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS,
            )
            if not task_identity:
                raise DeferredJobInfrastructureError(
                    "Deferred job dispatch did not return a task identity."
                )
            return task_identity
        if CONFIG.testing and adapter.synchronous_testing:
            return self.run(job.urlsafe_key)
        if CONFIG.development:
            app = current_app._get_current_object()

            def run_local():
                with app.app_context():
                    self.run(job.urlsafe_key)

            if delay_seconds:
                timer = threading.Timer(delay_seconds, run_local)
                timer.daemon = True
                timer.start()
                return None
            threading.Thread(target=run_local, daemon=True).start()
        return None

    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_long_running_feedback_dispatch_is_delayed_and_deterministic
    # @features deferred-jobs notifications
    # @dimensions long-running feedback scheduling
    def dispatch_feedback(self, job):
        """Schedule a bounded user-facing update for unusually long work."""
        if (
            not CONFIG.production
            or job.notification is None
            or job.status not in ACTIVE_STATUSES
        ):
            return None
        endpoint = url_for("process.deferred_job_feedback", _external=True)
        return task_queue.create_task(
            endpoint,
            {"job_key": job.urlsafe_key},
            DEFERRED_JOB_FEEDBACK_DELAY_SECONDS,
            task_id=_feedback_task_id(job),
        )
