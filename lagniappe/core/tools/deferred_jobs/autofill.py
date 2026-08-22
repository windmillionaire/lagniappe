"""Deferred autofill contracts independent of HTTP response handling."""

from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    FileConsumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs


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
# @pairs ai:autofill ai:deferred pages:autofill tasks:autofill
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
            "upload_record": upload_record,
            "lock_target": bool(lock_target),
        },
        notification_body=f"Autofilling {'task' if isinstance(entity, Entities.TASK) else 'page'}...",
        notification_target=entity,
        client=client,
    )


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_autofill_upload_is_validated_before_job_start
# @pairs ai:autofill ai:deferred notifications:autofill
def start_autofill_job(entity, user, form, *, upload_record=None, **options):
    """Validate any direct upload before creating a job or notification."""
    if upload_record:
        storage_assets.direct_upload_file(
            upload_record,
            consumer=FileConsumer.AI_INLINE,
        )
    spec = autofill_job_spec(
        entity,
        user,
        form,
        upload_record=upload_record,
        **options,
    )
    return DeferredJobs.start(spec)
