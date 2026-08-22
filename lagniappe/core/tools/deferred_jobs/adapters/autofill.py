"""Deferred-job adapters for the autofill domain."""

from copy import deepcopy
import hashlib

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
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database, dates
from lagniappe.core.tools.database import assets as storage_assets

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
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
    dependency_message = "Waiting for attached file summaries before autofilling..."
    mutation_inputs = ()

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_upload_checkpoint_records_durable_attachment
    # @features deferred-jobs ai files
    # @dimensions autofill upload checkpoint resume
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
    # @pairs deferred-jobs:form-revision ai:autofill
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
    # @pairs deferred-jobs:form-lock ai:autofill
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
    # @pairs deferred-jobs:status ai:collaboration
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

    # @testable infrastructure
    def load(self, context):
        super().load(context)
        target = context.input("target")
        if isinstance(target, Entities.TASK):
            context.inputs["target"] = Entities.fetch_one(
                target,
                request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
            )
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
    # @pairs deferred-jobs:form-revision deferred-jobs:form-lock ai:autofill
    def validate_apply(self, context):
        target = context.input("target")
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
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_prepare_waits_for_attached_file_summaries
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_upload_checkpoint_records_durable_attachment
    # @features deferred-jobs ai files
    # @dimensions autofill summary-dependency pending failed upload checkpoint
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
        existing_checkpoint = getattr(context, "checkpoint", None) or {}
        prepared_submission = existing_checkpoint.get("submission")
        if "submission" not in existing_checkpoint:
            dependencies = ai.autofill_summary_dependencies(
                context.input("target"),
                context.actor,
            )
            if dependencies["failed"]:
                raise DeferredJobDependencyFailedError(
                    "An attached file summary failed. Fix or remove that file, then "
                    "run autofill again."
                )
            if dependencies["pending"]:
                complete = len(dependencies["complete"])
                total = complete + len(dependencies["pending"])
                context.set_phase(
                    DeferredJobPhase.SUMMARIZING,
                    completed=complete,
                    total=total,
                )
                raise DeferredJobDependencyPendingError(
                    "Attached file summaries are still processing."
                )

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
            prompt_data = ai.autofill_prompt_data(
                context.input("target"),
                context.actor,
                user_context=context.parameters.get("user_context"),
                file=upload,
                mimetype=context.parameters.get("mimetype"),
            )
            prompt = ai.form_autofill_prompt(**prompt_data)
            context.set_phase(DeferredJobPhase.GENERATING)
            prepared_submission = ai.generate_autofilled_submission(prompt)

        checkpoint = {"submission": prepared_submission}
        if upload:
            identity = hashlib.sha256(
                str(context.job.urlsafe_key).encode("utf-8")
            ).hexdigest()
            file_key = database.create_named_key("file", f"autofill-{identity}")
            checkpoint["attachment"] = {
                "key": database.get.urlsafe_key(file_key),
                "name": f"{dates.user_today(context.actor):%Y-%m-%d}-autofill",
                "filename": upload.filename,
                "mimetype": upload.content_type,
            }
        return checkpoint

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_uploaded_file_is_attached_to_target
    # @features deferred-jobs ai files pages tasks
    # @dimensions autofill upload attachment idempotency inspection
    def inspect(self, context):
        target = context.input("target")
        current = target.properties.submission.value
        if current != context.checkpoint.get("submission"):
            return DeferredJobInspection.NOT_APPLIED

        attachment = context.checkpoint.get("attachment")
        if not attachment:
            return DeferredJobInspection.APPLIED

        file = Entities.fetch_one(attachment.get("key"), request=Fetch.direct())
        if not isinstance(file, Entities.FILE):
            return DeferredJobInspection.NOT_APPLIED
        if isinstance(target, Entities.PAGE):
            attached = target.key in file.properties.pages.keys
        else:
            attached = (
                file.key in target.properties.files.keys
                and target.key in file.properties.tasks.keys
            )
        return (
            DeferredJobInspection.APPLIED
            if attached
            else DeferredJobInspection.NOT_APPLIED
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_uploaded_file_is_attached_to_target
    # @features deferred-jobs ai files pages tasks
    # @dimensions autofill upload attachment naming idempotency
    def apply(self, context):
        context.ensure_active()
        target = context.input("target")
        attachment = context.checkpoint.get("attachment")
        attached_file = None
        if attachment:
            record = context.parameters.get("upload_record")
            if not record:
                raise exceptions.ValidationError(
                    "The autofill attachment metadata is missing."
                )
            attached_file = Entities.fetch_one(
                attachment.get("key"),
                request=Fetch.direct(),
            )
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
                file_key = database.get.datastore_key(attachment.get("key"))
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
                attached_file.properties.pages.add(target)
            else:
                target.properties.files.add(attached_file)

        target.ai_submission(deepcopy(context.checkpoint["submission"]))
        if attached_file:
            Entities.save(attached_file, target)
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
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_terminal_cleanup_releases_target_lock
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_page_operation_reference_is_persisted_and_compare_cleared
    # @pairs deferred-jobs:terminal-cleanup deferred-jobs:form-lock
    # @pair deferred-jobs:compare-and-delete
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
                database.release_deferred_job_lock(lock_key, operation)
            if target_key and operation:
                current = Entities.fetch_one(target_key, request=Fetch.direct())
                if (
                    isinstance(current, Entities.PAGE)
                    and (current.deferred_job or {}).get("key") == operation
                ):
                    current.deferred_job = None
                    Entities.save_root(current, property_mask=("deferred_job",))
        if terminal and record:
            storage_assets.delete_direct_upload(record)

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        target = context.input("target")
        label = "Task" if isinstance(target, Entities.TASK) else "Page"
        if succeeded:
            return f"{label} autofill is ready."
        return f"Autofill failed. {str(error or '').strip()}".strip()
