"""Shared deferred orchestration for page and task form autofill."""

import hashlib
import json

from flask import g, url_for
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI, Action, Fetch, FileConsumerLimitError,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.forms import review
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.deferred_jobs.autofill import start_autofill_job
from lagniappe.core.tools.database.assets import DirectUploadError
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobLockedError
from lagniappe.core.tools.deferred_jobs.locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    deferred_job_lock_descriptor,
    deferred_job_lock_descriptors,
)
from lagniappe.core.properties.deferred_job_lock import Operation
from lagniappe.web import direct_uploads, responses


# @testable false
# @covered-by lagniappe/web/deferred_autofill.py::locked_response
# @reason browser projection wrapper delegates to the durable lock resolver
def active_lock(entity):
    """Return the browser-safe active autofill descriptor for ``entity``."""
    return deferred_job_lock_descriptor(entity)


# @testable true
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @matrix deferred-jobs : conflict form-lock
def locked_response(entity, form=None):
    """Schema writers fence saves; an autofill reservation fences only AI starts."""
    form = form or {}
    descriptor = active_lock(entity)
    if not descriptor:
        return None
    starting = (form.get("role") == "autofill-submit"
                or form.get("explain") == "autofill"
                or form.get("input_name") == "autofill-file")
    if descriptor["scope"] != "form-change" and not starting:
        return None
    return responses.json_response(
        {
            "deferred": True,
            "already_running": True,
            **descriptor,
            "message": ("This Form is being updated. These changes were not saved; try again when the update finishes."
                        if descriptor["scope"] == "form-change" else "Autofill is already running. These changes were not saved."),
        },
        status=409,
    )


# @testable infrastructure
def prepare_form_states(entities, user):
    """Batch operation lookups for a rendered task list, including initial HTML."""
    targets = [entity for entity in entities if not getattr(entity, "completed", False)
               and entity.allowed(Action.EDIT, user=user)]
    if not targets:
        return
    active = deferred_job_lock_descriptors(targets)
    descriptors = g.setdefault("autofill_bootstrap_locks", {})
    for target in targets:
        descriptor = active.get(target.urlsafe_key)
        descriptors[target.urlsafe_key] = Operation.descriptor(*descriptor) if descriptor else None
    keys = list(dict.fromkeys(filter(None, (
        (descriptors[target.urlsafe_key] or {}).get("operation") or (target.deferred_job or {}).get("key")
        for target in targets
    ))))
    statuses = g.setdefault("autofill_bootstrap_statuses", {})
    for index in range(0, len(keys), 50):
        statuses.update({status["key"]: status for status in DeferredJobs.statuses(keys[index:index + 50], user)})


# @testable true
# @pair ai:autofill
# @matrix ai tasks : autofill reload
def form_state(entity, user=None):
    """Bootstrap the same editor state used by subsequent operation polling."""
    user = user or current_user
    if not entity.allowed(Action.EDIT, user=user) or getattr(entity, "completed", False):
        return {}
    cache = g.setdefault("autofill_form_states", {})
    # Do not reuse a pre-save projection when a route returns the accepted draft.
    cache_key = (entity.urlsafe_key, entity.autofill_revision, entity.db.get(review.REVIEWS), user.urlsafe_key)
    if cache_key in cache:
        return cache[cache_key]
    descriptors = g.get("autofill_bootstrap_locks", {})
    descriptor = descriptors[entity.urlsafe_key] if entity.urlsafe_key in descriptors else active_lock(entity)
    key = descriptor.get("operation") if descriptor else (entity.deferred_job or {}).get("key")
    cached_status = g.get("autofill_bootstrap_statuses", {}).get(key)
    statuses = [dict(cached_status)] if cached_status else DeferredJobs.statuses([key], user) if key else []
    status = statuses[0] if statuses else None
    if status and descriptor:
        status.update(scope=descriptor["scope"], blocks_edit=descriptor.get("blocks_edit", False))
    result = {
        "revision": entity.autofill_revision,
        "operation": status,
        "reviews": review.review_projection(entity, user),
        "migration": review.migration_review(entity),
        "refine_url": url_for("tools.refine_autofill", key=entity.urlsafe_key) if user.access(AI.CREATE) else None,
    }
    if status and status["type"] == "autofill":
        result["cancel_url"] = url_for("tools.cancel_generation", job_key=key)
        if status["status"] in {"failed", "cancelled"}:
            job = Entities.fetch_one(key, request=Fetch.direct())
            if job and job.actor.key == user.key and (job.parameters or {}).get("mode") != "revise":
                result["retry_operation"] = key
    cache[cache_key] = result
    return result


# @testable true
# @pair ai:autofill
def form_fingerprint(entity, user):
    """Operation revisions invalidate initial-form HTTP caches, not answer revisions."""
    state = form_state(entity, user)
    operation = state.get("operation") or {}
    return hashlib.sha256(json.dumps([
        entity.fingerprint, operation.get("key"), operation.get("revision"),
        entity.db.get(review.REVIEWS),
    ], default=str).encode()).hexdigest()


# @testable infrastructure
def page_tasks_fingerprint(page, user):
    """A cached task-list fragment must not seed an obsolete operation state."""
    from lagniappe.core.tools.polling.projections import page_tasks_revision
    if not page.allowed(Action.VIEW, user=user):
        return page.fingerprint
    prepare_form_states(page.tasks, user)
    operations = sorted((key, status["revision"]) for key, status in g.get("autofill_bootstrap_statuses", {}).items())
    return hashlib.sha256(json.dumps([page_tasks_revision(page, user), operations]).encode()).hexdigest()


# @testable infrastructure
def conflict_response(entity):
    """Return fresh typed values for the shared online/offline review flow."""
    entity = Entities.fetch_one(entity.key, request=Fetch.direct())
    response = responses.page_task(entity, conflict=True) if isinstance(entity, Entities.TASK) else responses.page_info(entity, conflict=True)
    if isinstance(response, tuple):
        return response[0], 409
    response.status_code = 409
    return response


# @testable true
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
# @matrix ai notifications pages tasks : autofill deferred
# @pair deferred-jobs:hosted-e2e
def start_deferred_autofill(
    entity,
    user,
    form,
    *,
    multipart_file=False,
    key=None,
    source_widget=None,
    destination=None,
    lock_target=True,
    **options,
):
    """Create the pending notification and enqueue one persisted autofill job."""
    if multipart_file:
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    upload_records = direct_uploads.direct_upload_records(
        form, input_name="autofill-file"
    )
    try:
        retry = form.get("autofill-retry")
        if retry:
            previous = Entities.fetch_one(retry, request=Fetch.direct())
            if (not isinstance(previous, Entities.DEFERRED_JOB) or previous.job_type != "autofill"
                    or previous.actor.key != user.key or previous.status not in {"failed", "cancelled"}
                    or ((previous.inputs or {}).get("target") or {}).get("id") != entity.urlsafe_key):
                return responses.error("This autofill retry is no longer available.")
            form = dict(form)
            form["autofill-description"] = (previous.parameters or {}).get("user_context")
            options["file_key"] = (previous.parameters or {}).get("file_key")
        job, notification = start_autofill_job(
            entity,
            user,
            form,
            upload_record=upload_records[0] if upload_records else None,
            key=key,
            source_widget=source_widget,
            destination=destination,
            lock_target=lock_target,
            **options,
        )
    except (DirectUploadError, FileConsumerLimitError) as error:
        return responses.error(str(error))
    except DeferredJobLockedError as error:
        return responses.json_response(
            {
                "deferred": True,
                "locked": True,
                "blocks_edit": False,
                "already_running": True,
                "scope": AUTOFILL_FORM_LOCK_SCOPE,
                "operation": error.job.urlsafe_key,
                "revision": int(error.job.status_revision or 0),
                "message": "Autofill is already running. These changes were not saved.",
            },
            status=409,
        )
    except exceptions.MutationConflict:
        return conflict_response(entity)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    except Exception as error:
        exceptions.capture(
            error,
            context={
                "operation": "queue_autofill",
                "target_key": entity.urlsafe_key,
                "target_kind": entity.entity_kind,
            },
        )
        return responses.error("Autofill could not be queued. Please try again.")

    result = {
        "deferred": True,
        "operation": job.urlsafe_key,
        "revision": int(job.status_revision or 0),
        "form_revision": entity.autofill_revision,
        "form_state": form_state(entity, user),
        "submission": entity.properties.submission.form_value,
        "schema": entity.submission_schema,
        "name": entity.name,
        "description": entity.description,
        "status": DeferredJobs.statuses([job.urlsafe_key], user)[0],
        "notification": responses.notification_item(notification),
    }
    if lock_target:
        result.update({"locked": True, "blocks_edit": False, "scope": AUTOFILL_FORM_LOCK_SCOPE})
    return responses.json_response(result)
