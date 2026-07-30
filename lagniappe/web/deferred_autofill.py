"""Shared deferred orchestration for page and task form autofill."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    FileConsumer,
    FileConsumerLimitError,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs import (
    AUTOFILL_FORM_LOCK_SCOPE,
    DeferredJobLockedError,
    DeferredJobs,
    deferred_job_lock_descriptor,
)
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.web import direct_uploads, responses


# @testable false
# @covered-by lagniappe/web/deferred_autofill.py::locked_response
# @reason browser projection wrapper delegates to the durable lock resolver
def active_lock(entity):
    """Return the browser-safe active autofill descriptor for ``entity``."""
    return deferred_job_lock_descriptor(entity)


# @testable true
# @tests tests_e2e/002_home/test_002n_file_consumer_routes.py::test_deferred_autofill_lock_response_blocks_form_mutations
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
# @tests tests_e2e/002_home/test_002n_file_consumer_routes.py::test_deferred_autofill_lock_response_blocks_form_mutations
# @pairs deferred-jobs:form-lock deferred-jobs:quick-edit
def is_form_field(entity, field_id):
    """Return whether a quick-edit field belongs to the locked form surface."""
    return bool(
        field_id
        and getattr(entity, "form", None)
        and any(
            isinstance(field, dict) and field.get("id") == field_id
            for field in (entity.form.schema or ())
        )
    )


# @testable false
# @covered-by lagniappe/web/deferred_autofill.py::autofill_job_spec
# @reason widget destination defaults are serialized and tested through the payload
def _autofill_destination(entity):
    if isinstance(entity, Entities.TASK):
        return {
            "key": entity.page.urlsafe_key,
            "source_widget": "TaskForm",
            "destination": f"{entity.hash}:TaskForm",
        }
    return {
        "key": entity.urlsafe_key,
        "source_widget": "PageInfo",
        "destination": "info:PageInfo",
    }


# @testable true
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
# @tests tests_e2e/002_home/test_002n_file_consumer_routes.py::test_deferred_autofill_returns_422_before_creating_notification
# @pairs ai:autofill ai:deferred
# @pairs pages:autofill pages:deferred tasks:autofill tasks:deferred
# @pairs notifications:autofill notifications:deferred
def autofill_job_spec(
    entity,
    user,
    form,
    *,
    key=None,
    source_widget=None,
    destination=None,
    lock_target=True,
):
    """Build the durable contract for one page/task autofill job."""
    upload_records = direct_uploads.direct_upload_records(
        form, input_name="autofill-file"
    )
    destination_context = _autofill_destination(entity)
    destination_context.update(
        {
            "key": key or destination_context["key"],
            "source_widget": source_widget
            or destination_context["source_widget"],
            "destination": destination or destination_context["destination"],
        }
    )
    return DeferredJobSpec(
        job_type=DeferredJobType.AUTOFILL,
        actor=user,
        idempotency_key=form.get("operation-id"),
        inputs={"target": entity},
        parameters={
            "user_context": form.get("autofill-description"),
            "mimetype": form.get("mimetype"),
            "upload_record": upload_records[0] if upload_records else None,
            "lock_target": bool(lock_target),
        },
        notification_body=f"Autofilling {'task' if isinstance(entity, Entities.TASK) else 'page'}...",
        notification_target=entity,
        client=destination_context,
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
    if upload_records:
        try:
            storage_assets.direct_upload_file(
                upload_records[0],
                consumer=FileConsumer.AI_INLINE,
            )
        except (storage_assets.DirectUploadError, FileConsumerLimitError) as error:
            return responses.error(str(error))

    spec = autofill_job_spec(
        entity,
        user,
        form,
        key=key,
        source_widget=source_widget,
        destination=destination,
        lock_target=lock_target,
    )

    try:
        job, notification = DeferredJobs.start(spec)
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
