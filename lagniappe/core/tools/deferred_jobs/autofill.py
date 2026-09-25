"""Deferred autofill contracts independent of HTTP response handling."""

from uuid import uuid4

from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    FileConsumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.forms.review import launch_snapshot


# @testable false
# @covered-by lagniappe/core/tools/deferred_jobs/autofill.py::autofill_job_spec
# @reason entity-specific destination projection is asserted through the public job spec
def _destination(entity):
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
# @tests tests_unit/test_024_autofill_form_state.py::test_autofill_job_spec_contains_only_durable_inputs
# @matrix ai : autofill deferred
# @matrix pages tasks : autofill
def autofill_job_spec(
    entity,
    user,
    form,
    *,
    upload_record=None,
    key=None,
    source_widget=None,
    destination=None,
    lock_target=True,
    mode="fill",
    submission=None,
    prompt_submission=None,
    target_context=None,
    review_context=None,
    file_key=None,
):
    """Build the durable contract for one page/task autofill job."""
    client = _destination(entity)
    client.update(
        {
            "key": key or client["key"],
            "source_widget": source_widget or client["source_widget"],
            "destination": destination or client["destination"],
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
            "upload_record": None if file_key else upload_record,
            "lock_target": bool(lock_target),
            "mode": mode,
            "snapshot": launch_snapshot(
                entity, user, instructions=form.get("autofill-description"),
                submission=submission, prompt_submission=prompt_submission,
                target_context=target_context, review_context=review_context,
            ),
            "file_key": file_key,
        },
        notification_body=f"Autofilling {'task' if isinstance(entity, Entities.TASK) else 'page'}...",
        notification_target=entity,
        client=client,
    )


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_autofill_upload_is_validated_before_job_start
# @matrix ai : autofill deferred
# @matrix ai tasks : attachment current-answers
# @pair notifications:autofill
def start_autofill_job(entity, user, form, *, upload_record=None, trusted_retry_upload=False, **options):
    """Validate any direct upload before creating a job or notification."""
    form = dict(form)
    form["operation-id"] = form.get("operation-id") or str(uuid4())
    if upload_record:
        storage_assets.verify_direct_upload(
            upload_record, max_age=None if trusted_retry_upload else storage_assets.DIRECT_UPLOAD_TOKEN_MAX_AGE,
            consumer=FileConsumer.AI_INLINE,
        )
    spec = autofill_job_spec(
        entity, user, form, upload_record=upload_record, **options,
    )
    return DeferredJobs.start(spec)
