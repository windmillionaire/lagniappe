"""One resumable form change with deterministic or prepared AI conversion batches."""

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
from lagniappe.core.tools.forms import changes, contracts, definitions, population
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
        contracts.check_size({**form.db, contracts.PENDING: pending})
        form.db[contracts.PENDING] = json.dumps(pending)
        form.db.pop("form_change_rejection", None)
        return ((form, (contracts.PENDING, "form_change_rejection")),), (
            (form.key, source),
        )

    def authorize(self, context):
        if self.inspect(context) == DeferredJobInspection.APPLIED:
            from lagniappe.core.definitions import Action

            form = Entities.fetch_one(context.input("form").key, request=Fetch.direct())
            if not form.allowed(Action.EDIT, user=context.actor):
                raise ValidationError(
                    "You no longer have permission to update this Form."
                )
            return
        _form, change = changes.owned_change(context)
        if change.get("report"):
            self.report_candidates(context, change)

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
        form, change = changes.owned_change(context)
        if not context.checkpoint and change.get("resume_checkpoint"):
            context.checkpoint_stage("resuming", change["resume_checkpoint"])
        self.verify_scope(context, form, change)
        cursor = context.checkpoint.get("check_cursor")
        count = context.checkpoint.get("checked", 0)
        while True:
            form, change = changes.owned_change(context)
            batch = population.target_batch(form, cursor)
            for raw in batch:
                context.ensure_active()
                target = population.load_target(raw)
                if target and target.db.get(contracts.RECEIPT) != change["id"]:
                    if target.generation != change["source_generation"]:
                        raise ValidationError(
                            "A submission has an unexpected form generation and needs repair."
                        )
                    placeholders = {
                        item["id"]: {"unresolved_reason": "preflight"}
                        for item in change["operations"]
                        if item["rule"] == "ai"
                    }
                    if change.get("report"):
                        placeholders = {
                            item["schema_id"]: item
                            for item in self.report_candidates(context, change)
                            if item["entity"] == target.urlsafe_key
                        }
                    changes.prepare_target(target, change, ai_values=placeholders)
            count += len(batch)
            cursor = batch.next_cursor
            context.checkpoint_stage(
                "checking",
                {
                    **context.checkpoint,
                    "check_cursor": cursor,
                    "checked": count,
                    "validated": not cursor,
                },
                phase="validating",
                completed=count,
            )
            if not cursor:
                return context.checkpoint

    # @testable false
    # @covered-by lagniappe/core/tools/deferred_jobs/adapters/form_change.py::FormChangeAdapter
    # @reason validate the complete scope again after a checkpoint resume, before the first write
    def verify_scope(self, context, form, change):
        if change.get("require_visibility") and not change["applied"]:
            from lagniappe.core.tools.forms.schema_updates import (
                inspect_scope,
                validate_candidates,
                STALE_MESSAGE,
            )

            scope = inspect_scope(
                form,
                change["operations"],
                context.actor,
                ensure_active=context.ensure_active,
            )
            if (
                change.get("scope_fingerprint")
                and scope["scope_fingerprint"] != change["scope_fingerprint"]
            ):
                raise ValidationError(STALE_MESSAGE)
            if change.get("report"):
                validate_candidates(
                    self.report_candidates(context, change), scope, change["operations"]
                )

    def inspect(self, context):
        form = Entities.fetch_one(context.input("form").key, request=Fetch.root())
        receipt = contracts.json_value(form.db, "form_draft_receipt") if form else {}
        return (
            DeferredJobInspection.APPLIED
            if receipt.get("id") == context.parameters["change_id"]
            and not form.db.get(contracts.PENDING)
            else DeferredJobInspection.NOT_APPLIED
        )

    def apply(self, context):
        from lagniappe.core.mutations import execute_mutation
        from lagniappe.core.mutations.base import RootMutation

        form, change = changes.owned_change(context)
        self.verify_scope(context, form, change)
        if not change["applied"]:
            expected = form.db[contracts.PENDING]
            change.update(applied=True, phase="applying")
            form.db[contracts.PENDING] = json.dumps(change)
            form._form_change_write = True
            execute_mutation(
                RootMutation.plan(form, property_mask=(contracts.PENDING,)),
                guards=[
                    (form.key, {contracts.PENDING: expected}),
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
                batch = population.target_batch(form, cursor)
                for raw in batch:
                    target = population.load_target(raw)
                    if target is None:
                        continue
                    prepared = self.prepare_ai_target(context, change, target)
                    changes.apply_target(context, raw, ai_values=prepared)
                    if context.checkpoint.get("ai_batch"):
                        checkpoint = dict(context.checkpoint)
                        checkpoint.pop("ai_batch", None)
                        context.checkpoint_stage(
                            "applying", checkpoint, phase="applying"
                        )
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

    # @testable true
    # @tests tests_unit/test_004l_form_schema_updates.py::test_worker_checkpoints_ai_before_write_and_external_execution_is_provider_free
    # @matrix form-migration : ai-checkpoint external-provider-free retry
    # @pair form-migration:ai-telemetry
    def prepare_ai_target(self, context, change, target):
        from lagniappe.core.tools.forms import schema_updates as updates
        from lagniappe.core.tools.ai.form_conversion import generate_conversions
        from lagniappe.core.tools.ai.observability import ai_execution_context

        if target.db.get(contracts.RECEIPT) == change["id"]:
            return {}
        if change.get("report"):
            self.report_candidates(context, change)
        values = contracts.json_value(target.db, "submission")
        needed = [
            item
            for item in change["operations"]
            if item["rule"] == "ai" and contracts.needs_ai_value(values.get(item["id"]))
        ]
        if not needed:
            return {}
        updates.require_visible(target, context.actor)
        hashes = {
            item["id"]: updates.value_fingerprint(target, item, values)
            for item in needed
        }
        saved = context.checkpoint.get("ai_batch") or {}
        if saved.get("entity") == target.urlsafe_key and saved.get("sources") == hashes:
            return saved["values"]
        if change.get("report"):
            prepared = {
                item["schema_id"]: item
                for item in self.report_candidates(context, change)
                if item["entity"] == target.urlsafe_key
            }
            for field_id, source_hash in hashes.items():
                if prepared.get(field_id, {}).get("source_fingerprint") != source_hash:
                    raise ValidationError(updates.STALE_MESSAGE)
        else:
            requests = [
                {
                    "id": item["id"],
                    "source": item["source"],
                    "target": item["target"],
                    "value": values[item["id"]],
                    "instructions": change.get("instructions", {}).get(item["id"], ""),
                }
                for item in needed
            ]
            with ai_execution_context(
                job_type=context.job.job_type,
                attempt=context.job.attempt,
                contract_version=context.job.job_version,
                telemetry_id=getattr(context.job, "telemetry_id", None),
                execution_control=context.execution_control,
            ):
                try:
                    prepared = generate_conversions(requests, context.actor)
                except ValidationError as error:
                    error.context = {
                        **(getattr(error, "context", None) or {}),
                        "form_conversion_target": target.urlsafe_key,
                    }
                    raise
        # One target's fields are one synchronous provider batch. Only that
        # batch is retained, so checkpoints do not grow with the Form population.
        changes.prepare_target(target, change, ai_values=prepared)
        context.checkpoint_stage(
            "converted",
            {
                **context.checkpoint,
                "ai_batch": {
                    "entity": target.urlsafe_key,
                    "sources": hashes,
                    "values": prepared,
                },
            },
            phase="applying",
        )
        return prepared

    # @testable false
    # @covered-by lagniappe/core/tools/deferred_jobs/adapters/form_change.py::FormChangeAdapter.prepare_ai_target
    # @reason prepared output is loaded only from the immutable approved report
    def report_candidates(self, context, change):
        from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint

        report = Entities.fetch_one(change.get("report"), request=Fetch.direct())
        if not report or proposal_fingerprint(report.proposal) != change.get(
            "report_fingerprint"
        ):
            raise ValidationError(
                "The approved schema update report changed or is unavailable."
            )
        action = next(
            (
                item
                for item in report.proposal["actions"]
                if item.get("id") == change["action_id"]
            ),
            None,
        )
        if not action:
            raise ValidationError("The approved schema update action is unavailable.")
        return action["data"].get("conversions", [])

    def publish(self, context):
        from lagniappe.core.mutations import execute_mutation, plan_mutation
        from lagniappe.core.tools.forms import drafts as form_drafts

        form, change = changes.owned_change(context)
        target = definitions.target_definition(form, change)
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
        pending = contracts.json_value(form.db, contracts.PENDING) if form else {}
        if pending.get("job") == job.urlsafe_key and pending.get("applied"):
            raise ValidationError(
                "Some submissions may already be updated. Retry this change to finish it."
            )

    # @testable true
    # @tests tests_unit/test_004l_form_schema_updates.py::test_preflight_rejection_releases_only_unapplied_change
    # @matrix form-migration : permissions preflight ownership
    def failure(self, context, error):
        from lagniappe.core.tools.forms.schema_updates import (
            RESTRICTED_MESSAGE,
            STALE_MESSAGE,
        )
        from lagniappe.core.mutations import execute_mutation
        from lagniappe.core.mutations.base import RootMutation
        from lagniappe.core.tools.database.assets import cleanup_rejected_attempt

        if str(error) not in {RESTRICTED_MESSAGE, STALE_MESSAGE}:
            return
        form = Entities.fetch_one(context.input("form").key, request=Fetch.root())
        pending = contracts.json_value(form.db, contracts.PENDING) if form else {}
        if pending.get("job") != context.job.urlsafe_key or pending.get("applied"):
            return
        expected = form.db.pop(contracts.PENDING)
        form.db["form_change_rejection"] = json.dumps(
            {"id": pending["id"], "error": str(error)}
        )
        form._form_change_write = True
        execute_mutation(
            RootMutation.plan(
                form, property_mask=(contracts.PENDING, "form_change_rejection")
            ),
            guards=[
                (form.key, {contracts.PENDING: expected}),
                (
                    context.job.key,
                    {"lease_token": context.job.lease_token, "status": "running"},
                ),
            ],
        )
        form._form_attempt_assets = pending.get("attempt_assets", [])
        cleanup_rejected_attempt(form)

    def cleanup(self, context, *, terminal):
        # A failed/expired job does not release ownership of partially converted values.
        from lagniappe.core.tools.database import deferred_jobs

        form = Entities.fetch_one(context.input("form").key, request=Fetch.root())
        if form and not form.db.get(contracts.PENDING):
            from lagniappe.core.tools import cache

            cache.update(form)
            deferred_jobs.release_deferred_job_lock(
                deferred_job_lock_key(form, "form-change"), context.job.urlsafe_key
            )
