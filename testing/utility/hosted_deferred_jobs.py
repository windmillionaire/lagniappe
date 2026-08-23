"""Hosted E2E delivery helpers for real App Engine deferred jobs."""

from datetime import datetime, timezone
import math

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS,
    DeferredJobStatus,
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.properties.deferred_job_dispatch import TaskIdentity
from lagniappe.core.tools.services import task_queue


def _ai_diagnostics(job):
    """Return privacy-bounded provider telemetry for one hosted job."""
    telemetry_id = getattr(job, "telemetry_id", None)
    if not telemetry_id:
        return []

    from lagniappe.core.tools.ai.observability import diagnostic_record
    from lagniappe.core.tools.database import analytics

    return [
        diagnostic_record(record)
        for record in analytics.ai_observability_records(limit=1000)
        if record.get("telemetry_id") == telemetry_id
    ]


def wait_for_hosted_job_transition(page, job_key, *, timeout=180_000):
    """Poll through the deployed browser session until a worker attempt settles."""
    state_key = f"__lagniappeHostedJob{job_key[-24:]}"
    page.evaluate(
        """({ key, stateKey }) => {
            const state = { payload: null, error: null, stopped: false };
            window[stateKey] = state;
            const poll = async () => {
                if (state.stopped) return;
                try {
                    const token = document.getElementById("token")?.value || "";
                    const response = await fetch("/l/poll", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": token,
                            "X-Lagniappe-Request": "true",
                        },
                        body: JSON.stringify({
                            version: 1,
                            client_id: `hosted-job-${key.slice(-16)}`,
                            subscriptions: [{
                                id: `operation:${key}`,
                                type: "operation",
                                key,
                                revision: 0,
                            }],
                            closed_documents: [],
                        }),
                    });
                    if (!response.ok) {
                        throw new Error(`Operation poll returned ${response.status}`);
                    }
                    const result = (await response.json()).results?.[0];
                    const payload = result?.payload;
                    if (
                        payload?.terminal === true ||
                        payload?.status === "retry_wait"
                    ) {
                        state.payload = payload;
                        return;
                    }
                } catch (error) {
                    state.error = String(error);
                    return;
                }
                window.setTimeout(poll, 1000);
            };
            void poll();
        }""",
        {"key": job_key, "stateKey": state_key},
    )
    try:
        handle = page.wait_for_function(
            """stateKey => {
                const state = window[stateKey];
                if (state?.error) throw new Error(state.error);
                return state?.payload || false;
            }""",
            arg=state_key,
            polling=250,
            timeout=timeout,
        )
        return handle.json_value()
    finally:
        page.evaluate(
            """stateKey => {
                if (window[stateKey]) window[stateKey].stopped = true;
                delete window[stateKey];
            }""",
            state_key,
        )


def dispatch_hosted_deferred_job(
    page,
    job,
    *,
    attempt_limit=2,
    task_suffix="hosted-e2e",
):
    """Deliver a persisted job through Cloud Tasks and the deployed OIDC route."""
    assert CONFIG.hosted_e2e_runner
    endpoint = f"{str(CONFIG.APP_URL).rstrip('/')}/process/jobs"
    created_tasks = []
    attempts = []
    queue_was_enabled = CONFIG.TASK_QUEUE_ENABLED
    CONFIG.TASK_QUEUE_ENABLED = True
    try:
        current_job = job
        for attempt in range(1, attempt_limit + 1):
            delay_seconds = 0
            if current_job.status == DeferredJobStatus.RETRY_WAIT.value:
                delay_seconds = max(
                    math.ceil(
                        (
                            current_job.next_attempt_at
                            - datetime.now(timezone.utc)
                        ).total_seconds()
                    ),
                    0,
                )
            task_identity = task_queue.create_task(
                endpoint,
                {"job_key": job.urlsafe_key},
                delay_seconds=delay_seconds,
                task_id=TaskIdentity.create(
                    job,
                    attempt,
                    suffix=task_suffix,
                ),
                dispatch_deadline_seconds=DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS,
            )
            assert task_identity
            created_tasks.append(task_identity)
            transition = wait_for_hosted_job_transition(page, job.urlsafe_key)
            current_job = Entities.fetch_one(
                job.urlsafe_key,
                request=Fetch.direct(),
            )
            error = current_job.error or {}
            progress = current_job.progress or {}
            attempt_record = {
                "attempt": current_job.attempt,
                "status": current_job.status,
                "phase": (
                    transition.get("phase")
                    or progress.get("phase")
                    or current_job.status
                ),
                "error": {
                    key: error[key]
                    for key in ("type", "message", "retryable", "attempt")
                    if error.get(key) is not None
                },
            }
            if current_job.status == DeferredJobStatus.FAILED.value:
                attempt_record["ai_generations"] = _ai_diagnostics(current_job)
            attempts.append(attempt_record)
            if current_job.status != DeferredJobStatus.RETRY_WAIT.value:
                break
        return current_job, attempts
    finally:
        for task_identity in created_tasks:
            task_queue.delete_task(task_identity)
        CONFIG.TASK_QUEUE_ENABLED = queue_was_enabled
