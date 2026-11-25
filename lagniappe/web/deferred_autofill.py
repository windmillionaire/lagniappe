"""Shared deferred orchestration for page and task form autofill."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Unpack
    from lagniappe.core.tools.deferred_jobs.autofill import AutofillJobOptions
    from collections.abc import Iterable
    from flask import Response
    from google.cloud.datastore import Key
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from werkzeug.datastructures import MultiDict

import hashlib
import json
from uuid import uuid4

from flask import abort, g, request, url_for
from collections.abc import Mapping
from lagniappe.web.auth import authenticated_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI, Action, Fetch, FileConsumer, FileConsumerLimitError,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.forms import review
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.deferred_jobs.autofill import start_autofill_job
from lagniappe.core.tools.database.assets import DirectUploadError
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.polling import task_lists
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobLockedError
from lagniappe.core.tools.deferred_jobs.locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    deferred_job_lock_descriptor,
    deferred_job_lock_descriptors,
)
from lagniappe.core.properties.deferred_job_lock import Operation
from lagniappe.web import direct_uploads, responses


def active_lock(entity: Entity) -> dict[str, object] | None:
    """Return the browser-safe active autofill descriptor for ``entity``."""
    return deferred_job_lock_descriptor(entity)


def locked_response(
    entity: Entity, form: Mapping[str, object] | None = None
) -> tuple[Response, int] | None:
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


def prepare_form_states(
    entities: Iterable[models.Task | models.Page], user: models.User
) -> None:
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
    keys = []
    for target in targets:
        descriptor = descriptors[target.urlsafe_key] or {}
        job = target.deferred_job
        key = descriptor.get("operation") or (job.get("key") if isinstance(job, dict) else None)
        if isinstance(key, str) and key not in keys:
            keys.append(key)
    statuses = g.setdefault("autofill_bootstrap_statuses", {})
    for index in range(0, len(keys), 50):
        statuses.update({status["key"]: status for status in DeferredJobs.statuses(keys[index:index + 50], user)})


def form_state(
    entity: models.Page | models.Task, user: models.User | None = None
) -> dict[str, object]:
    """Bootstrap the same editor state used by subsequent operation polling."""
    user = user or authenticated_user()
    if not entity.allowed(Action.EDIT, user=user) or (
        isinstance(entity, Entities.TASK) and entity.completed
    ):
        return {}
    cache = g.setdefault("autofill_form_states", {})
    # Do not reuse a pre-save projection when a route returns the accepted draft.
    cache_key = (entity.urlsafe_key, entity.autofill_revision, entity.db.get(review.REVIEWS), user.urlsafe_key)
    if cache_key in cache:
        return cache[cache_key]
    descriptors = g.get("autofill_bootstrap_locks", {})
    descriptor = descriptors[entity.urlsafe_key] if entity.urlsafe_key in descriptors else active_lock(entity)
    last_job = entity.deferred_job
    key = descriptor.get("operation") if descriptor else last_job.get("key") if isinstance(last_job, dict) else None
    if not isinstance(key, str):
        key = None
    cached_status = g.get("autofill_bootstrap_statuses", {}).get(key)
    statuses = [dict(cached_status)] if cached_status else DeferredJobs.statuses([key], user) if key else []
    status = dict(statuses[0]) if statuses else None
    if status and descriptor:
        status.update(scope=descriptor["scope"], blocks_edit=descriptor.get("blocks_edit", False))
    reviews = review.review_projection(entity, user)
    # The entity retains its last job key after an ordinary save acknowledges
    # the review. A consumed success is history, not an active form operation.
    stale_autofill = False
    if (status and status["type"] == "autofill" and status["status"] == "succeeded"
            and not any(candidate["operation"] == key for candidate in reviews)):
        job = Entities.fetch_one(key, request=Fetch.direct())
        if isinstance(job, Entities.DEFERRED_JOB) and ((job.parameters or {}).get("mode") != "revise" or (job.actor is not None and job.actor.key == user.key)):
            snapshot = (job.parameters or {}).get("snapshot")
            stale_autofill = bool(snapshot) and (not isinstance(snapshot, dict) or not review.snapshot_matches_form(snapshot, entity))
        status = None
    result = {
        "revision": entity.autofill_revision,
        "operation": status,
        "reviews": reviews,
        "stale_autofill": stale_autofill,
        "refine_url": url_for("tools.refine_autofill", key=entity.urlsafe_key) if user.access(AI.CREATE) else None,
    }
    if status and status["type"] == "autofill":
        result["cancel_url"] = url_for("tools.cancel_generation", job_key=key)
        if status["status"] in {"failed", "cancelled"}:
            job = Entities.fetch_one(key, request=Fetch.direct())
            if isinstance(job, Entities.DEFERRED_JOB) and job.actor is not None and job.actor.key == user.key and (job.parameters or {}).get("mode") != "revise":
                result["retry_operation"] = key
    cache[cache_key] = result
    return result


def form_fingerprint(entity: models.Page | models.Task, user: models.User) -> str:
    """Operation revisions invalidate initial-form HTTP caches, not answer revisions."""
    state = form_state(entity, user)
    operation = state.get("operation")
    if not isinstance(operation, Mapping):
        operation = {}
    return hashlib.sha256(json.dumps([
        entity.fingerprint, operation.get("key"), operation.get("revision"),
        entity.db.get(review.REVIEWS),
    ], default=str).encode()).hexdigest()


def page_tasks_fingerprint(page: models.Page, user: models.User) -> str:
    """Validate proven quiet fragments before loading their Task graph."""
    from lagniappe.web.auth import _etag_fingerprint
    from lagniappe.core.tools.polling.projections import page_tasks_revision
    if not page.allowed(Action.VIEW, user=user):
        return page.fingerprint
    snapshot = task_lists.quiet_snapshot(g.get("request_context_records"))
    fingerprint = None
    if snapshot is not None:
        fingerprint = task_lists.quiet_fingerprint(snapshot, page, user)
        if request.if_none_match.contains_weak(_etag_fingerprint(fingerprint, user)):
            # Only a fully rendered and checked response can issue this ETag.
            # The permission wrapper still checks authorization and Range.
            g.task_list_snapshot = snapshot
            return fingerprint
    prepare_form_states(page.tasks, user)
    g.task_list_prepared = True
    if fingerprint is not None and snapshot is not None and not (
        task_lists.has_operation_dependencies([*page.tasks, *page.completed_tasks])
        or any(g.get("autofill_bootstrap_locks", {}).values())
        or g.get("autofill_bootstrap_statuses")
    ):
        g.task_list_snapshot = snapshot
        return fingerprint
    operations = sorted((key, status["revision"]) for key, status in g.get("autofill_bootstrap_statuses", {}).items())
    return hashlib.sha256(json.dumps(["full-task-list-v1", page_tasks_revision(page, user), user.urlsafe_key, operations]).encode()).hexdigest()


def finish_task_list_validation(page: models.Page) -> None:
    """Do not label a raced render as reusable quiet HTML."""
    snapshot = g.get("task_list_snapshot")
    if snapshot is None:
        return
    if (
        task_lists.has_operation_dependencies([*page.tasks, *page.completed_tasks])
        or any(g.get("autofill_bootstrap_locks", {}).values())
        or g.get("autofill_bootstrap_statuses")
        or task_lists.quiet_snapshot() != snapshot
    ):
        g.pop("fingerprint", None)
        g.NO_CACHE = True


def conflict_response(entity: models.Page | models.Task) -> tuple[Response, int]:
    """Return fresh typed values for the shared online/offline review flow."""
    loaded = Entities.fetch_one(entity.key, request=Fetch.direct())
    if isinstance(loaded, Entities.TASK):
        response = responses.page_task(loaded, conflict=True)
    elif isinstance(loaded, Entities.PAGE):
        response = responses.page_info(loaded, conflict=True)
    else:
        abort(404)
    if isinstance(response, tuple):
        return response[0], 409
    response.status_code = 409
    return response


def staged_upload_for_update(
    entity: models.Page | models.Task, actor: models.User, form: MultiDict[str, str]
) -> tuple[models.File | None, list[dict[str, object]]]:
    """Prepare an accepted AI upload; defer deletion until the form save commits."""
    reviewed = set(form.getlist("reviewed-operation"))
    used = set(form.getlist("used-autofill-operation"))
    if not used.issubset(reviewed):
        raise exceptions.ValidationError("Review the autofill values before saving its file.")
    references = set(review.review_references(entity).values())
    if not used.issubset(references):
        raise exceptions.ValidationError("This autofill review is no longer available.")
    if used:
        available = {candidate["operation"] for candidate in review.review_projection(entity, actor)}
        if not used.issubset(available):
            raise exceptions.ValidationError("The form changed. Run autofill again before using its suggestions.")
        if entity.form and entity.form.key is not None:
            guards: list[tuple[Key, database_utility.ExactEntityState]] = list(getattr(entity, "_form_additional_guards", ()))
            guards.append((entity.form.key, database_utility.ExactEntityState(dict(entity.form.db))))
            entity._form_additional_guards = guards

    candidates = set(reviewed & references)
    last_job = entity.deferred_job
    current_key = last_job.get("key") if isinstance(last_job, dict) else None
    if isinstance(current_key, str) and current_key:
        candidates.add(current_key)
    jobs = Entities.fetch(*candidates, request=Fetch.direct()) if candidates else ()
    file = None
    cleanup = []
    for job in jobs:
        if (not isinstance(job, Entities.DEFERRED_JOB)
                or job.job_type != "autofill"
                or ((job.inputs or {}).get("target") or {}).get("id") != entity.urlsafe_key):
            continue
        snapshot = (job.parameters or {}).get("snapshot")
        stale = bool(snapshot) and (not isinstance(snapshot, dict) or not review.snapshot_matches_form(snapshot, entity))
        record = (job.parameters or {}).get("upload_record")
        if not isinstance(record, dict) or not record:
            continue
        # Private prompt-only refinements build on the shared suggestion. A
        # selected refinement still uses the original evidence from that review.
        accepted = job.urlsafe_key in reviewed and bool(used) and job.status == "succeeded" and not stale
        discarded = job.urlsafe_key in reviewed and not accepted
        abandoned = (job.urlsafe_key == current_key and (job.status in {"failed", "cancelled"} or (job.status == "succeeded" and stale))
                     and job.actor is not None and job.actor.key == actor.key)
        if not (accepted or discarded or abandoned):
            continue
        if accepted:
            if file is not None:
                raise exceptions.ValidationError("Save one autofill attachment at a time.")
            upload = storage_assets.verify_direct_upload(
                record, max_age=None, consumer=FileConsumer.AI_INLINE,
            )
            file_key = database_utility.create_named_key(
                "file", f"autofill-{hashlib.sha256(job.urlsafe_key.encode()).hexdigest()}",
            )
            file = Entities.fetch_one(file_key, request=Fetch.direct())
            if file is None:
                upload.lagniappe_preserve_source = True
                # Each save attempt owns its copy; a rejected save can clean it
                # without blocking a retry or deleting another attempt's blob.
                upload.lagniappe_asset_nonce = uuid4().hex
                file = Entities.FILE.create(
                    upload=upload,
                    data={"name": upload.filename, "filename": upload.filename,
                          "mimetype": upload.content_type},
                    key=file_key,
                )
                storage_assets.record_attempt_asset(file, dict(file.assets["file"]))
                file.move_to(entity)
            elif not isinstance(file, Entities.FILE) or getattr(file.owner, "key", None) != entity.key:
                raise exceptions.ValidationError("This autofill attachment belongs to another form.")
        cleanup.append(record)
    if isinstance(current_key, str) and current_key:
        current = next((job for job in jobs if job.urlsafe_key == current_key), None)
        parameters = current.parameters if isinstance(current, Entities.DEFERRED_JOB) else None
        snapshot = (parameters or {}).get("snapshot")
        if current_key in reviewed or (
            isinstance(current, Entities.DEFERRED_JOB) and (current.status in {"failed", "cancelled"}
                         or (current.status == "succeeded" and snapshot
                             and (not isinstance(snapshot, dict) or not review.snapshot_matches_form(snapshot, entity))))
            and current.actor is not None and current.actor.key == actor.key
        ):
            entity.deferred_job = None
            review.acknowledge_reviews(entity, actor, [current_key])
    return file, cleanup


def cleanup_staged_uploads(records: Iterable[Mapping[str, object]]) -> None:
    for record in records:
        if not storage_assets.delete_direct_upload(record):
            exceptions.capture(
                exceptions.ValidationError("Staged autofill upload cleanup was incomplete."),
                context={"operation": "autofill_upload_cleanup"}, level="warning",
            )


def start_deferred_autofill(
    entity: models.Page | models.Task,
    user: models.User,
    form: Mapping[str, str | None],
    *,
    multipart_file: bool = False,
    **options: Unpack[AutofillJobOptions],
) -> Response | tuple[Response, int]:
    """Create the pending notification and enqueue one persisted autofill job."""
    if multipart_file:
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    upload_records = direct_uploads.direct_upload_records(
        form, input_name="autofill-file"
    )
    upload_record = upload_records[0] if upload_records else None
    trusted_retry_upload = False
    try:
        retry = form.get("autofill-retry")
        if isinstance(retry, str) and retry:
            previous = Entities.fetch_one(retry, request=Fetch.direct())
            if (not isinstance(previous, Entities.DEFERRED_JOB) or previous.job_type != "autofill" or previous.actor is None
                    or previous.actor.key != user.key or previous.status not in {"failed", "cancelled"}
                    or ((previous.inputs or {}).get("target") or {}).get("id") != entity.urlsafe_key):
                return responses.error("This autofill retry is no longer available.")
            parameters = previous.parameters or {}
            context = parameters.get("user_context")
            file_key = parameters.get("file_key")
            form = {**form, "autofill-description": context if isinstance(context, str) else None}
            options["file_key"] = file_key if isinstance(file_key, str) else None
            if not upload_record:
                saved_record = parameters.get("upload_record")
                if saved_record is not None and not isinstance(saved_record, dict):
                    return responses.error("This autofill attachment is no longer available.")
                upload_record = saved_record
                trusted_retry_upload = bool(upload_record)
        job, notification = start_autofill_job(
            entity,
            user,
            form,
            upload_record=upload_record,
            trusted_retry_upload=trusted_retry_upload,
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
        "notification": responses.notification_item(notification) if notification is not None else None,
    }
    if options.get("lock_target", True):
        result.update({"locked": True, "blocks_edit": False, "scope": AUTOFILL_FORM_LOCK_SCOPE})
    return responses.json_response(result)
