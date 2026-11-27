"""Cloud Tasks and local-provider dispatch for durable deferred jobs."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.deferred_job import DeferredJob
    from lagniappe.core.definitions import DeferredJobResult

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    # Dispatch, recovery, and execution are composed by the same service.
    from .service import DeferredJobService

import threading

from flask import Flask, current_app, has_request_context, request, url_for
from werkzeug.local import LocalProxy

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


class DeferredJobDispatch:
    def dispatch(self, job: DeferredJob, *, attempt: int, delay_seconds: int = 0, task_suffix: str | None = None) -> str | DeferredJobResult | None:
        service = cast("DeferredJobService", self)
        adapter = service.adapter(job.job_type)
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
            return service.run(job.urlsafe_key)
        if CONFIG.development:
            app = cast("LocalProxy[Flask]", current_app)._get_current_object()
            base_url = request.host_url if has_request_context() else None

            def run_local():
                request_context = (
                    app.test_request_context(base_url=base_url)
                    if base_url
                    else app.test_request_context("/")
                )
                with request_context:
                    service.run(job.urlsafe_key)

            if delay_seconds:
                timer = threading.Timer(delay_seconds, run_local)
                timer.daemon = True
                timer.start()
                return None
            threading.Thread(target=run_local, daemon=True).start()
        return None

    def dispatch_feedback(self, job: DeferredJob) -> str | None:
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
