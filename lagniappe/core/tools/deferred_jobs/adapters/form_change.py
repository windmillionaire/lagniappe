"""One resumable deterministic form change; no provider or report dependency."""

from copy import deepcopy
import json

from lagniappe.core.definitions import (
    DeferredJobInspection,
    DeferredJobType,
    Fetch,
    MutationOperation,
)
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools import form_changes as changes
from lagniappe.core.tools.database.utility import ExactEntityState

from .base import DeferredJobAdapter
from ..locks import deferred_job_lock_key


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_adapter_checks_all_values_before_applying
# @matrix form-migration : preflight batch-job publication recovery
class FormChangeAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.FORM_CHANGE
    required_ai_access = None
    synchronous_testing = True
    queued_message = "Updating form submissions..."
    success_message = "Form submissions updated."
    failure_prefix = "The form update needs attention."

    def start_lock(self, spec, job):
        form = spec.inputs["form"]
        return Entities.DEFERRED_JOB_LOCK.create(
            {
                "key": deferred_job_lock_key(form, "form-change"),
                "scope": "form-change",
                "target": form.urlsafe_key,
                "operation": job.urlsafe_key,
                "idempotency_key": job.idempotency_key,
            }
        )

    def start_writes(self, spec, job):
        form = spec.inputs["form"]
        pending = deepcopy(form._starting_form_change)
        source = ExactEntityState(deepcopy(dict(form.db)))
        pending["job"] = job.urlsafe_key
        form.db[changes.PENDING] = json.dumps(pending)
        return ((form, (changes.PENDING,)),), ((form.key, source),)

    def authorize(self, context):
        if self.inspect(context) == DeferredJobInspection.APPLIED:
            from lagniappe.core.definitions import Action

            form = Entities.fetch_one(context.input("form").key, request=Fetch.direct())
            if not form.allowed(Action.EDIT, user=context.actor):
                raise ValidationError(
                    "You no longer have permission to update this Form."
                )
            return
        changes.owned_change(context)

    def started(self, context):
        from lagniappe.core.tools import cache

        cache.update(context.input("form"))

    def can_view_status(self, job, actor):
        from lagniappe.core.definitions import Action

        form = Entities.fetch_one(
            (job.inputs.get("form") or {}).get("id"), request=Fetch.direct()
        )
        return bool(form and form.allowed(Action.EDIT, user=actor))

    def notification_target(self, context):
        return context.input("form")

    def checkpoint_ready(self, context):
        return bool(context.checkpoint.get("validated"))

    def prepare(self, context):
        cursor = context.checkpoint.get("check_cursor")
        count = context.checkpoint.get("checked", 0)
        while True:
            form, change = changes.owned_change(context)
            batch = changes.target_batch(form, cursor)
            for raw in batch:
                context.ensure_active()
                target = changes.load_target(raw)
                if target and target.db.get(changes.RECEIPT) != change["id"]:
                    if target.generation != change["source_generation"]:
                        raise ValidationError(
                            "A submission has an unexpected form generation and needs repair."
                        )
                    changes.prepare_target(target, change)
            count += len(batch)
            cursor = batch.next_cursor
            context.checkpoint_stage(
                "checking",
                {"check_cursor": cursor, "checked": count, "validated": not cursor},
                phase="validating",
                completed=count,
            )
            if not cursor:
                return context.checkpoint

    def inspect(self, context):
        form = Entities.fetch_one(context.input("form").key, request=Fetch.root())
        receipt = changes.json_value(form.db, "form_draft_receipt") if form else {}
        return (
            DeferredJobInspection.APPLIED
            if receipt.get("id") == context.parameters["change_id"]
            and not form.db.get(changes.PENDING)
            else DeferredJobInspection.NOT_APPLIED
        )

    def apply(self, context):
        from lagniappe.core.mutations import execute_mutation
        from lagniappe.core.mutations.base import RootMutation

        form, change = changes.owned_change(context)
        if not change["applied"]:
            expected = form.db[changes.PENDING]
            change.update(applied=True, phase="applying")
            form.db[changes.PENDING] = json.dumps(change)
            form._form_change_write = True
            execute_mutation(
                RootMutation.plan(form, property_mask=(changes.PENDING,)),
                guards=[
                    (form.key, {changes.PENDING: expected}),
                    (
                        context.job.key,
                        {"lease_token": context.job.lease_token, "status": "running"},
                    ),
                ],
            )
        cursor = context.checkpoint.get("apply_cursor")
        count = context.checkpoint.get("processed", 0)
        if not context.checkpoint.get("applied_all"):
            while True:
                form, _change = changes.owned_change(context)
                batch = changes.target_batch(form, cursor)
                for raw in batch:
                    changes.apply_target(context, raw)
                count += len(batch)
                cursor = batch.next_cursor
                context.checkpoint_stage(
                    "applying",
                    {
                        "validated": True,
                        "apply_cursor": cursor,
                        "processed": count,
                        "applied_all": not cursor,
                    },
                    phase="applying",
                    completed=count,
                )
                if not cursor:
                    break
        self.publish(context)
        return {"form": form.urlsafe_key, "processed": count}

    def publish(self, context):
        from lagniappe.core.mutations import execute_mutation, plan_mutation
        from lagniappe.core.tools import form_drafts

        form, change = changes.owned_change(context)
        target = changes.target_definition(form, change)
        target._form_change_write = True
        target._form_change_publication = change["id"]
        target._form_save_guard = (form.key, ExactEntityState(dict(form.db)))
        plan = plan_mutation(MutationOperation.SAVE, target, registry=Entities)
        target.db["form_draft_receipt"] = json.dumps(
            {
                "id": change["id"],
                "digest": change["digest"],
                "version": target.version,
                "baseline": form_drafts.builder_draft(target)["baseline"],
                "image_urls": change["image_urls"],
            }
        )
        context.ensure_active()
        outcome = execute_mutation(
            plan,
            guards=[
                (
                    context.job.key,
                    {"lease_token": context.job.lease_token, "status": "running"},
                ),
            ],
        )
        if not outcome.post_commit_complete:
            raise RuntimeError(
                "The Form was updated; its display refresh needs retrying."
            )

    def before_cancel(self, job):
        form = Entities.fetch_one(
            (job.inputs.get("form") or {}).get("id"), request=Fetch.root()
        )
        pending = changes.json_value(form.db, changes.PENDING) if form else {}
        if pending.get("job") == job.urlsafe_key and pending.get("applied"):
            raise ValidationError(
                "Some submissions may already be updated. Retry this change to finish it."
            )

    def cleanup(self, context, *, terminal):
        # A failed/expired job does not release ownership of partially converted values.
        from lagniappe.core.tools.database import deferred_jobs

        form = Entities.fetch_one(context.input("form").key, request=Fetch.root())
        if form and not form.db.get(changes.PENDING):
            from lagniappe.core.tools import cache

            cache.update(form)
            deferred_jobs.release_deferred_job_lock(
                deferred_job_lock_key(form, "form-change"), context.job.urlsafe_key
            )
