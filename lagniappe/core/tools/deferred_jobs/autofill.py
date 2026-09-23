"""Deferred autofill contracts independent of HTTP response handling."""

import hashlib
from uuid import uuid4

from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    FileConsumer,
    Fetch,
    FetchReason,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobLockedError
from lagniappe.core.tools.forms.review import launch_snapshot
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core import exceptions


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
                submission=submission, review_context=review_context,
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
def start_autofill_job(entity, user, form, *, upload_record=None, **options):
    """Validate any direct upload before creating a job or notification."""
    form = dict(form)
    # A stable ID also owns the attached upload and survives delivery retries.
    form["operation-id"] = form.get("operation-id") or str(uuid4())
    attached_file = None
    upload = None
    if upload_record:
        upload = storage_assets.direct_upload_file(
            upload_record,
            consumer=FileConsumer.AI_INLINE,
        )
        identity = hashlib.sha256(
            f"{user.urlsafe_key}:{form['operation-id']}".encode()
        ).hexdigest()
        file_key = database_utility.create_named_key("file", f"autofill-{identity}")
        attached_file = Entities.fetch_one(file_key, request=Fetch.nested(
            because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
        ))
        if attached_file is None:
            upload.lagniappe_preserve_source = True
            attached_file = Entities.FILE.create(
                upload=upload,
                data={"name": upload.filename, "filename": upload.filename, "mimetype": upload.content_type},
                key=file_key,
            )
            if isinstance(entity, Entities.PAGE):
                attached_file.move_to(entity)
            else:
                entity.properties.files.add(attached_file)
            entity._autofill_start_entities = (attached_file, entity)
            entity._autofill_file_guard = (file_key, None)
        elif not isinstance(attached_file, Entities.FILE) or (
            attached_file.properties.page.key != entity.key
            and attached_file.properties.task.key != entity.key
        ):
            raise exceptions.ValidationError("This autofill upload belongs to another form.")
        options["file_key"] = attached_file.urlsafe_key
    try:
        spec = autofill_job_spec(
            entity, user, form, upload_record=upload_record, **options,
        )
        result = DeferredJobs.start(spec)
    except (exceptions.ValidationError, exceptions.MutationConflict, DeferredJobLockedError):
        if attached_file and getattr(upload, "lagniappe_saved_destination", None):
            # A definite rejected start owns only its unique copy, never the
            # source upload or a different delivery's accepted attachment.
            persisted = Entities.fetch_one(attached_file.key, request=Fetch.root())
            saved = upload.lagniappe_saved_destination
            if not persisted or persisted.assets.get("file", {}).get("path") != saved["path"]:
                try:
                    storage_assets.delete_file_generation(saved["path"], saved["visibility"], saved["generation"])
                except Exception as error:
                    exceptions.capture(error, context={"operation": "autofill_rejected_upload_cleanup"}, level="warning")
        for root in getattr(entity, "_autofill_start_entities", (entity,)):
            storage_assets.cleanup_rejected_attempt(root)
        raise
    if upload_record:
        # The durable attachment now owns its copy; cancellation never removes it.
        storage_assets.delete_direct_upload(upload_record)
    return result
