"""Shared deferred orchestration for page and task form autofill."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    FileConsumerLimitError,
)
from lagniappe.core.tools.autofill_jobs import start_autofill_job
from lagniappe.core.tools.database.assets import DirectUploadError
from lagniappe.core.tools.deferred_jobs import (
    AUTOFILL_FORM_LOCK_SCOPE,
    DeferredJobLockedError,
    deferred_job_lock_descriptor,
)
from lagniappe.web import direct_uploads, responses


# @testable false
# @covered-by lagniappe/web/deferred_autofill.py::locked_response
# @reason browser projection wrapper delegates to the durable lock resolver
def active_lock(entity):
    """Return the browser-safe active autofill descriptor for ``entity``."""
    return deferred_job_lock_descriptor(entity)


# @testable true
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @pairs deferred-jobs:form-lock deferred-jobs:conflict
def locked_response(entity, form=None):
    """Return a structured conflict response when autofill owns the form."""
    del form
    descriptor = active_lock(entity)
    if not descriptor:
        return None
    return responses.json_response(
        {
            "deferred": True,
            **descriptor,
            "message": "Autofill is already running. These changes were not saved.",
        },
        status=409,
    )


# @testable true
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
# @pairs ai:autofill ai:deferred
# @pairs pages:autofill pages:deferred tasks:autofill tasks:deferred
# @pairs notifications:autofill notifications:deferred
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
        job, notification = start_autofill_job(
            entity,
            user,
            form,
            upload_record=upload_records[0] if upload_records else None,
            key=key,
            source_widget=source_widget,
            destination=destination,
            lock_target=lock_target,
        )
    except (DirectUploadError, FileConsumerLimitError) as error:
        return responses.error(str(error))
    except DeferredJobLockedError as error:
        return responses.json_response(
            {
                "deferred": True,
                "locked": True,
                "scope": AUTOFILL_FORM_LOCK_SCOPE,
                "operation": error.job.urlsafe_key,
                "revision": int(error.job.status_revision or 0),
                "message": "Autofill is already running. These changes were not saved.",
            },
            status=409,
        )
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
        "notification": responses.notification_item(notification),
    }
    if lock_target:
        result.update({"locked": True, "scope": AUTOFILL_FORM_LOCK_SCOPE})
    return responses.json_response(result)
