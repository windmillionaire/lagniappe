"""Deferred-job adapters for the site domain."""

from copy import deepcopy
import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobSpec,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
    Fetch,
    FetchReason,
    FileConsumer,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database, dates, files, site_export
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
class SiteExportAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.SITE_EXPORT
    synchronous_testing = True
    queued_message = "Building HTML export archive..."
    success_message = "HTML export archive is ready."
    failure_prefix = "HTML export failed."

    def checkpoint_ready(self, _context):
        """Site export has no provider preparation; its durable record is the intent."""
        return True

    # @testable infrastructure
    def authorize(self, context):
        if not isinstance(context.actor, Entities.USER) or not Resource.SITE.allowed(
            Action.VIEW,
            user=context.actor,
        ):
            raise exceptions.ValidationError(
                "You do not have permission to export this site."
            )

    # @testable infrastructure
    def inspect(self, context):
        record = database.site_export(context.parameters.get("export_id"))
        if record and record.get("status") == "complete":
            return DeferredJobInspection.APPLIED
        if record and record.get("status") in {"queued", "running", "failed"}:
            return DeferredJobInspection.NOT_APPLIED
        return DeferredJobInspection.DRIFTED

    # @testable infrastructure
    def apply(self, context):
        context.ensure_active()
        export_id = context.parameters["export_id"]
        database.update_site_export(
            export_id,
            {"status": "running", "started": site_export._utc(), "error": None},
        )
        updates = site_export.build_site_export(export_id)
        record = database.update_site_export(export_id, updates)
        return {key: value for key, value in dict(record or {}).items() if key != "type"}

    # @testable infrastructure
    def failure(self, context, error):
        export_id = context.parameters.get("export_id")
        if export_id:
            database.update_site_export(
                export_id,
                {
                    "status": "failed",
                    "completed": site_export._utc(),
                    "error": str(error),
                },
            )
