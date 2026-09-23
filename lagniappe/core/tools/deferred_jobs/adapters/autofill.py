"""Deferred-job adapters for the autofill domain."""

from copy import deepcopy
import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobType,
    Fetch,
    FetchReason,
    FileConsumer,
    MutationOperation,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import dates
from lagniappe.core.tools.ai import autofill as ai_autofill
from lagniappe.core.tools.database import deferred_jobs as database_deferred_jobs
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.forms import review as form_review
from lagniappe.core.tools.forms import changes as form_changes
from lagniappe.core.mutations import (
    plan_mutation, plan_root, prepare_durable_writes, execute_mutation,
    execute_post_commit, consume_mutation_intents,
)

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDriftError,
)
from ..locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    active_deferred_job_lock,
    deferred_job_lock_key,
)


# @testable infrastructure
class AutofillAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.AUTOFILL
    required_ai_access = AI.CREATE
    queued_message = "Autofilling form..."
    retry_message = "AI is temporarily busy; retrying autofill shortly..."
    mutation_inputs = ()
    max_lifetime_seconds = 120
    cancellable_provider = True

    # @testable true
    # @pair ai:autofill
    def committed_result(self, job):
        if job.db.get(form_review.RECEIPT):
            return form_review.json_value(job.db, form_review.RECEIPT)
        return None

    # @testable true
    # @pair ai:autofill
    def start_writes(self, spec, job):
        if not spec.parameters.get("snapshot"):
            return (), ()
        target = spec.inputs["target"]
        target.deferred_job = {
            "key": job.urlsafe_key,
            "idempotency_key": job.idempotency_key,
            "revision": int(job.status_revision or 0),
        }
        roots = getattr(target, "_autofill_start_entities", (target,))
        plan = plan_mutation(MutationOperation.SAVE, *roots)
        writes = prepare_durable_writes(plan)
        guards = list(getattr(target, "_form_additional_guards", ()))
        file_guard = getattr(target, "_autofill_file_guard", None)
        if file_guard:
            guards.append(file_guard)
        guards.extend(form_changes.mutation_guards(writes, []))
        target._autofill_start_plan = plan
        return [(effect.entity, effect.property_mask) for effect in writes], guards

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_upload_checkpoint_records_durable_attachment
    # @matrix ai deferred-jobs files : autofill checkpoint resume upload
    def checkpoint_ready(self, context):
        if not super().checkpoint_ready(context):
            return False
        return not context.parameters.get("upload_record") or isinstance(
            context.checkpoint.get("attachment"),
            dict,
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_page_operation_reference_is_persisted_and_compare_cleared
    # @pairs deferred-jobs:active-operation pages:create-autofill
    def started(self, context):
        target = context.input("target")
        if context.parameters.get("snapshot"):
            plan = getattr(target, "_autofill_start_plan", None)
            if plan is not None:
                consume_mutation_intents(plan)
                try:
                    execute_post_commit(plan)
                except Exception as error:
                    exceptions.capture(error, context={"operation": "autofill_start_post_commit"})
            else:
                from lagniappe.core.tools import cache
                cache.update(target)
            return
        if not isinstance(target, Entities.PAGE):
            return
        target = Entities.fetch_one(target.urlsafe_key, request=Fetch.direct())
        if not isinstance(target, Entities.PAGE):
            raise exceptions.ValidationError("Deferred autofill page is missing.")
        context.inputs["target"] = target
        target.deferred_job = {
            "key": context.job.urlsafe_key,
            "idempotency_key": context.job.idempotency_key,
            "revision": int(getattr(context.job, "status_revision", 0) or 0),
        }
        Entities.save_root(target, property_mask=("deferred_job",))

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_revision_tracks_only_form_apply_state
    # @pairs ai:autofill deferred-jobs:form-revision
    def authorization(self, spec):
        authorization = super().authorization(spec)
        target = spec.inputs.get("target")
        authorization["form_revision"] = getattr(
            target,
            "autofill_revision",
            None,
        )
        return authorization

    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_autofill_start_acquires_one_target_lock
    # @tests tests_unit/test_024_autofill_form_state.py::test_autofill_explicit_lock_opt_out_skips_target_lock
    # @pairs ai:autofill deferred-jobs:form-lock
    def start_lock(self, spec, job):
        if spec.parameters.get("lock_target", True) is False:
            return None
        target = spec.inputs.get("target")
        if target is None:
            return None
        key = deferred_job_lock_key(target)
        if key is None:
            raise exceptions.ValidationError("Deferred autofill target is invalid.")
        return Entities.DEFERRED_JOB_LOCK.create(
            {
                "key": key,
                "scope": AUTOFILL_FORM_LOCK_SCOPE,
                "target": target.urlsafe_key,
                "operation": job.urlsafe_key,
                "idempotency_key": job.idempotency_key,
            }
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_status_is_visible_to_target_editor
    # @pairs ai:collaboration deferred-jobs:status
    def can_view_status(self, job, actor):
        try:
            target = (job.inputs or {}).get("target")
            target = Entities.fetch_one(
                target.get("id"),
                request=Fetch.nested(
                    because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION
                ),
            )
        except (AttributeError, exceptions.ValidationError):
            return False
        return bool(
            isinstance(target, (Entities.PAGE, Entities.TASK))
            and target.allowed(Action.EDIT, user=actor)
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_uploaded_file_is_attached_to_target
    # @pairs files:attachment deferred-jobs:loaded-input
    def load(self, context):
        super().load(context)
        target = context.input("target")
        if isinstance(target, Entities.TASK):
            context.inputs["target"] = Entities.fetch_one(
                target,
                request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
            )
        attachment = context.checkpoint.get("attachment")
        context.inputs["attachment"] = Entities.fetch_one(
            attachment.get("key"),
            request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
        ) if attachment else None
        return context

    # @testable infrastructure
    def authorize(self, context):
        super().authorize(context)
        target = context.input("target")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred autofill user is invalid.")
        if not isinstance(target, (Entities.PAGE, Entities.TASK)):
            raise exceptions.ValidationError("Deferred autofill target is invalid.")
        if not target.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to autofill this form."
            )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_revision_tracks_only_form_apply_state
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_autofill_lock_cleanup_is_compare_and_delete
    # @tests tests_unit/test_024_autofill_form_state.py::test_lockless_autofill_keeps_revision_drift_guard
    # @matrix deferred-jobs : form-lock form-revision
    # @pair ai:autofill
    def validate_apply(self, context):
        target = context.input("target")
        if context.parameters.get("snapshot"):
            # Schema and answer drift becomes a review, not lost generation work.
            # Ownership and lease are checked inside the application transaction.
            context.ensure_active()
            return
        if context.parameters.get("lock_target", True):
            active = active_deferred_job_lock(target)
            if active is None or active[1].urlsafe_key != context.job.urlsafe_key:
                raise DeferredJobDriftError(
                    "Autofill no longer owns this form. Run autofill again."
                )
        expected = (context.job.authorization or {}).get("form_revision")
        if expected != getattr(target, "autofill_revision", None):
            raise DeferredJobDriftError(
                "The form changed while autofill was running. Run autofill again."
            )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_prepare_does_not_wait_for_attached_file_summaries
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_upload_checkpoint_records_durable_attachment
    # @matrix ai deferred-jobs files : autofill checkpoint failed pending upload summary-dependency
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
        if context.parameters.get("snapshot"):
            return self.prepare_snapshot(context)
        existing_checkpoint = getattr(context, "checkpoint", None) or {}
        prepared_submission = existing_checkpoint.get("submission")
        record = context.parameters.get("upload_record")
        upload = (
            storage_assets.direct_upload_file(
                record,
                consumer=FileConsumer.AI_INLINE,
            )
            if record
            else None
        )
        if "submission" not in existing_checkpoint:
            prompt_data = ai_autofill.autofill_prompt_data(
                context.input("target"),
                context.actor,
                user_context=context.parameters.get("user_context"),
                file=upload,
                mimetype=context.parameters.get("mimetype"),
            )
            prompt = ai_autofill.form_autofill_prompt(**prompt_data)
            context.set_phase(DeferredJobPhase.GENERATING)
            prepared_submission = ai_autofill.generate_autofilled_submission(
                prompt, entity=context.input("target"), user=context.actor
            )

        checkpoint = {"submission": prepared_submission}
        if upload:
            identity = hashlib.sha256(
                str(context.job.urlsafe_key).encode("utf-8")
            ).hexdigest()
            file_key = database_utility.create_named_key("file", f"autofill-{identity}")
            checkpoint["attachment"] = {
                "key": database_get.urlsafe_key(file_key),
                "name": f"{dates.user_today(context.actor):%Y-%m-%d}-autofill",
                "filename": upload.filename,
                "mimetype": upload.content_type,
            }
        return checkpoint

    # @testable true
    # @pair ai:autofill
    def prepare_snapshot(self, context):
        snapshot = context.parameters["snapshot"]
        prompt_data = deepcopy(snapshot["prompt"])
        prompt_data["user"] = context.actor
        file_key = context.parameters.get("file_key")
        if file_key:
            file = Entities.fetch_one(file_key, request=Fetch.nested(
                because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
            ))
            if not isinstance(file, Entities.FILE) or not file.allowed(Action.VIEW, user=context.actor):
                raise exceptions.ValidationError("The supplied autofill file is no longer available.")
            prompt_data["original_files"] = [file]
        prompt = ai_autofill.form_autofill_prompt(**prompt_data)
        context.set_phase(DeferredJobPhase.GENERATING)
        submission = ai_autofill.generate_autofilled_submission(
            prompt, entity=context.input("target"), user=context.actor,
            schema=prompt_data["schema"],
        )
        context.set_phase(DeferredJobPhase.VALIDATING)
        proposal = form_review.prepare_proposal(
            prompt_data["schema"], submission, context.input("target"), context.actor,
        )
        return {"submission": submission, "proposal": proposal}

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_uploaded_file_is_attached_to_target
    # @matrix ai deferred-jobs files pages tasks : attachment autofill idempotency inspection upload
    def inspect(self, context):
        if context.parameters.get("snapshot"):
            return (DeferredJobInspection.APPLIED if context.job.db.get(form_review.RECEIPT)
                    else DeferredJobInspection.NOT_APPLIED)
        target = context.input("target")
        current = target.properties.submission.value
        if current != context.checkpoint.get("submission"):
            return DeferredJobInspection.NOT_APPLIED

        attachment = context.checkpoint.get("attachment")
        if not attachment:
            return DeferredJobInspection.APPLIED

        file = context.input("attachment")
        if not isinstance(file, Entities.FILE):
            return DeferredJobInspection.NOT_APPLIED
        if isinstance(target, Entities.PAGE):
            attached = not file.properties.task.key and target.key == file.properties.page.key
        else:
            attached = (
                file.key in target.properties.files.keys
                and target.key == file.properties.task.key
            )
        return (
            DeferredJobInspection.APPLIED
            if attached
            else DeferredJobInspection.NOT_APPLIED
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_uploaded_file_is_attached_to_target
    # @matrix ai deferred-jobs files pages tasks : attachment autofill idempotency naming upload
    def apply(self, context):
        context.ensure_active()
        if context.parameters.get("snapshot"):
            return self.apply_proposal(context)
        target = context.input("target")
        attachment = context.checkpoint.get("attachment")
        attached_file = None
        if attachment:
            record = context.parameters.get("upload_record")
            if not record:
                raise exceptions.ValidationError(
                    "The autofill attachment metadata is missing."
                )
            attached_file = context.input("attachment")
            if attached_file is not None and not isinstance(
                attached_file,
                Entities.FILE,
            ):
                raise exceptions.ValidationError(
                    "The autofill attachment could not be saved."
                )
            if attached_file is None:
                upload = storage_assets.direct_upload_file(
                    record,
                    consumer=FileConsumer.AI_INLINE,
                )
                upload.lagniappe_preserve_source = True
                file_key = database_get.datastore_key(attachment.get("key"))
                if file_key is None:
                    raise exceptions.ValidationError(
                        "The autofill attachment key is invalid."
                    )
                attached_file = Entities.FILE.create(
                    page=target if isinstance(target, Entities.PAGE) else None,
                    upload=upload,
                    data={
                        "name": attachment.get("name"),
                        "filename": attachment.get("filename"),
                        "mimetype": attachment.get("mimetype"),
                    },
                    key=file_key,
                )

            if isinstance(target, Entities.PAGE):
                attached_file.move_to(target)
            else:
                target.properties.files.add(attached_file)

        target.ai_submission(
            deepcopy(context.checkpoint["submission"]), actor=context.actor,
            preserve_existing=True,
        )
        if attached_file:
            Entities.save(attached_file, target)
            context.inputs["attachment"] = attached_file
        else:
            target.save()
        result = {
            "target_key": target.urlsafe_key,
            "target_kind": target.entity_kind,
        }
        if attached_file:
            result["file_key"] = attached_file.urlsafe_key
        return result

    # @testable true
    # @pair ai:autofill
    # @matrix ai tasks : autofill conflicts review private-refinement
    def apply_proposal(self, context):
        snapshot = context.parameters["snapshot"]
        private = context.parameters.get("mode") == "revise"
        for attempt in range(3):
            context.ensure_active()
            target = Entities.fetch_one(context.input("target").key, request=Fetch.nested(
                because=FetchReason.TASK_SAVE_REQUIREMENTS,
            ))
            if not target or not target.allowed(Action.EDIT, user=context.actor):
                raise exceptions.ValidationError("This form is no longer available for autofill.")
            if isinstance(target, Entities.TASK) and target.completed:
                raise exceptions.ValidationError("This task was completed while autofill was running.")
            source = database_utility.ExactEntityState(deepcopy(dict(target.db)))
            current = target.properties.submission.value or {}
            schema_changed = (
                target.generation != snapshot["generation"]
                or target.submission_schema != snapshot["prompt"]["schema"]
                or getattr(target.form, "urlsafe_key", None) != snapshot["form"]
            )
            context_changed = any(
                value not in (None, "", [], {}) and current.get(key) != value
                for key, value in snapshot["answers"].items()
            )
            context_changed = context_changed or any(
                value not in (None, "") and getattr(target, key, None) != value
                for key, value in snapshot["prompt"].get("target", {}).items()
                if key in {"name", "description"}
            )
            pending = bool(target.form and target.form.db.get("pending_form_change"))
            review_only = private or schema_changed or context_changed or pending
            merged, conflicts, applied = form_review.merge_proposal(
                snapshot["answers"], current, context.checkpoint["proposal"]["answers"],
                review_only=review_only,
            )
            if applied:
                notice = target.db.get("pre_migration")
                target.properties.submission.value = merged
                target.save_submission()
                # AI completion is not a human acknowledgement of migration losses.
                if notice:
                    target.db["pre_migration"] = notice
            form_review.remember_review(target, context.job, private=private)
            result = {
                "target_key": target.urlsafe_key,
                "target_kind": target.entity_kind,
                "applied_fields": applied,
                "conflicting_fields": sorted(conflicts),
                "review_only": review_only,
                "snapshot_revision": snapshot["revision"],
            }
            context.job.db[form_review.RECEIPT] = json.dumps(result)
            context.job.result = result
            plan = (
                plan_mutation(MutationOperation.SAVE, target) if applied else
                plan_root(target, property_mask=(form_review.REVIEWS, "modified"), property_updates=("modified",))
            )
            if not applied:
                from lagniappe.core.mutations.base import MutationPlanBuilder
                builder = MutationPlanBuilder(MutationOperation.SAVE, (target,))
                builder.cache_refresh(target, reason="autofill-review")
                plan.effects.extend(builder.build().effects)
            plan.effects.extend(plan_root(
                context.job, property_mask=(form_review.RECEIPT, "result"),
            ).effects)
            guards = [
                (target.key, source),
                (context.job.key, {"status": "running", "lease_token": context.job.lease_token, form_review.RECEIPT: None}),
            ]
            if context.parameters.get("lock_target", True):
                guards.append((deferred_job_lock_key(target), {"operation": context.job.urlsafe_key}))
            try:
                execute_mutation(plan, guards=guards)
                context.inputs["target"] = target
                return result
            except exceptions.MutationConflict:
                context.ensure_active()
                persisted = Entities.fetch_one(context.job.key, request=Fetch.direct())
                if persisted and persisted.db.get(form_review.RECEIPT):
                    return form_review.json_value(persisted.db, form_review.RECEIPT)
                if attempt == 2:
                    raise

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_terminal_cleanup_releases_target_lock
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_page_operation_reference_is_persisted_and_compare_cleared
    # @matrix deferred-jobs : compare-and-delete form-lock terminal-cleanup
    def cleanup(self, context, *, terminal):
        record = context.parameters.pop("upload_record", None)
        context.job.parameters = context.parameters
        if terminal:
            target = context.input("target")
            target_reference = (getattr(context.job, "inputs", None) or {}).get(
                "target",
                {},
            )
            if not isinstance(target_reference, dict):
                target_reference = {}
            target_key = getattr(target, "urlsafe_key", None) or target_reference.get(
                "id"
            )
            operation = getattr(context.job, "urlsafe_key", None)
            if context.parameters.get("lock_target", True) and target_key and operation:
                lock_key = deferred_job_lock_key(target_key)
                database_deferred_jobs.release_deferred_job_lock(lock_key, operation)
            if target_key and operation:
                current = Entities.fetch_one(target_key, request=Fetch.direct())
                if (
                    isinstance(current, Entities.PAGE)
                    and (current.deferred_job or {}).get("key") == operation
                    and not context.parameters.get("snapshot")
                ):
                    current.deferred_job = None
                    Entities.save_root(current, property_mask=("deferred_job",))
        if terminal and record:
            storage_assets.delete_direct_upload(record)

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        if getattr(context.job, "status", None) in {"cancelled", "superseded"}:
            return "Autofill cancelled. Your saved answers and files were kept."
        target = context.input("target")
        label = "Task" if isinstance(target, Entities.TASK) else "Page"
        if succeeded:
            return f"{label} autofill is ready."
        return f"Autofill failed. {str(error or '').strip()}".strip()
