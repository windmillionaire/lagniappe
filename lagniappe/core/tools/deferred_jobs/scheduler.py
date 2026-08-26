"""Cloud Scheduler state convergence for durable deferred-job recovery."""

import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from config import constants
from lagniappe import CONFIG
from lagniappe.core.tools.database import deferred_jobs as database_deferred_jobs


SCHEDULER_API_ROOT = "https://cloudscheduler.googleapis.com/v1"
SCHEDULER_REQUEST_TIMEOUT_SECONDS = 10
SCHEDULER_SYNC_LEASE_SECONDS = 60
SCHEDULER_SYNC_WAIT_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0)
SCHEDULER_SYNC_MAX_TRANSITIONS = 8
SCHEDULER_STATES = {"enabled", "paused"}


class DeferredJobSchedulerError(RuntimeError):
    """The recovery Scheduler job could not converge to durable intent."""


# @testable infrastructure
# @covered-by lagniappe/core/tools/deferred_jobs/scheduler.py::synchronize_deferred_job_reconciler
def _utc():
    return datetime.now(timezone.utc)


# @testable true
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_provider_pause_and_resume_use_exact_job_resource
# @matrix cloud-scheduler deferred-jobs : exact-resource provider-api
def scheduler_job_url(config=CONFIG):
    """Return the exact Cloud Scheduler REST resource owned by this app."""
    project = str(getattr(config, "GOOGLE_CLOUD_PROJECT", None) or "").strip()
    region = str(getattr(config, "RESOURCE_REGION", None) or "").strip()
    if not project or not region:
        raise DeferredJobSchedulerError(
            "Cloud Scheduler requires GOOGLE_CLOUD_PROJECT and RESOURCE_REGION."
        )
    name = constants.DEFAULT_DEFERRED_JOB_RECONCILER_NAME
    resource = "/".join(
        (
            "projects",
            quote(project, safe=""),
            "locations",
            quote(region, safe=""),
            "jobs",
            quote(name, safe=""),
        )
    )
    return f"{SCHEDULER_API_ROOT}/{resource}"


# @testable infrastructure
# @covered-by lagniappe/core/tools/deferred_jobs/scheduler.py::set_scheduler_state
def _response_state(response):
    response.raise_for_status()
    try:
        state = str((response.json() or {}).get("state") or "").lower()
    except (TypeError, ValueError) as error:
        raise DeferredJobSchedulerError(
            "Cloud Scheduler returned an invalid job response."
        ) from error
    if state not in SCHEDULER_STATES:
        raise DeferredJobSchedulerError(
            f"Cloud Scheduler returned unsupported job state {state!r}."
        )
    return state


# @testable infrastructure
# @covered-by lagniappe/core/tools/deferred_jobs/scheduler.py::set_scheduler_state
def _request_state(session, method, url):
    try:
        response = session.request(
            method,
            url,
            timeout=SCHEDULER_REQUEST_TIMEOUT_SECONDS,
        )
        return _response_state(response)
    except DeferredJobSchedulerError:
        raise
    except Exception as error:
        raise DeferredJobSchedulerError(
            "Cloud Scheduler job state could not be read or changed."
        ) from error


# @testable true
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_provider_pause_and_resume_use_exact_job_resource
# @matrix cloud-scheduler deferred-jobs : idempotency pause provider-api resume
def set_scheduler_state(desired_state, *, session, config=CONFIG):
    """Read and, when necessary, move the Scheduler job to one exact state."""
    if desired_state not in SCHEDULER_STATES:
        raise ValueError(f"Unsupported desired Scheduler state: {desired_state!r}")
    url = scheduler_job_url(config)
    actual_state = _request_state(session, "GET", url)
    if actual_state == desired_state:
        return actual_state

    action = "resume" if desired_state == "enabled" else "pause"
    try:
        return _request_state(session, "POST", f"{url}:{action}")
    except DeferredJobSchedulerError:
        # A manual or delayed provider mutation may have won between GET and POST.
        # Confirm the resulting state before treating the conditional API call as
        # a failure.
        actual_state = _request_state(session, "GET", url)
        if actual_state == desired_state:
            return actual_state
        raise


# @testable infrastructure
# @covered-by lagniappe/core/tools/deferred_jobs/scheduler.py::synchronize_deferred_job_reconciler
def _control_converged(control):
    return bool(
        control.get("applied_state") == control.get("desired_state")
        and int(control.get("applied_generation") or 0)
        == int(control.get("generation") or 0)
    )


# @testable true
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_sync_serializes_state_changes_and_converges_latest_generation
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_sync_releases_lease_after_provider_failure
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_sync_uses_committed_control_hint_when_current
# @matrix cloud-scheduler deferred-jobs : convergence datastore-read-isolation
# @pair deferred-jobs:provider-failure
def synchronize_deferred_job_reconciler(
    *,
    force=False,
    initial_control=None,
    config=CONFIG,
    session=None,
    now_fn=_utc,
    sleep=time.sleep,
):
    """Converge provider state to the latest serialized Datastore intent."""
    if not bool(getattr(config, "production", False)):
        return {
            "synchronized": False,
            "reason": "local-environment",
            "control": None,
        }

    initial = (
        initial_control
        if initial_control is not None
        else database_deferred_jobs.get_deferred_job_scheduler_control()
    )
    if not force and _control_converged(initial):
        return {"synchronized": True, "reason": "current", "control": initial}

    lease_token = uuid.uuid4().hex
    acquired = None
    for delay in (*SCHEDULER_SYNC_WAIT_DELAYS, None):
        acquired = database_deferred_jobs.acquire_deferred_job_scheduler_sync(
            lease_token,
            now_fn(),
            lease_seconds=SCHEDULER_SYNC_LEASE_SECONDS,
        )
        if acquired.get("acquired"):
            break
        control = acquired.get("control") or {}
        if not force and _control_converged(control):
            return {
                "synchronized": True,
                "reason": "concurrent",
                "control": control,
            }
        if delay is not None:
            sleep(delay)
    if not acquired or not acquired.get("acquired"):
        raise DeferredJobSchedulerError(
            "Cloud Scheduler synchronization is already in progress."
        )

    try:
        provider_session = session or AuthorizedSession(config.google_credentials)
        control = acquired["control"]
        for _attempt in range(SCHEDULER_SYNC_MAX_TRANSITIONS):
            actual_state = set_scheduler_state(
                control["desired_state"],
                session=provider_session,
                config=config,
            )
            recorded = database_deferred_jobs.record_deferred_job_scheduler_sync(
                lease_token,
                actual_state,
                now_fn(),
                lease_seconds=SCHEDULER_SYNC_LEASE_SECONDS,
            )
            if not recorded.get("recorded"):
                raise DeferredJobSchedulerError(
                    "Cloud Scheduler synchronization lease was lost."
                )
            control = recorded["control"]
            if _control_converged(control):
                return {
                    "synchronized": True,
                    "reason": "updated",
                    "control": control,
                }
        raise DeferredJobSchedulerError(
            "Cloud Scheduler intent changed too frequently to converge."
        )
    finally:
        database_deferred_jobs.release_deferred_job_scheduler_sync(lease_token, now_fn())
