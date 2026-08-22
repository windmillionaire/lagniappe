"""Deferred-job adapters for the site domain."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    DeferredJobInspection,
    DeferredJobType,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.site import exports as site_export
from lagniappe.core.tools.database import site_exports as export_database

from .base import DeferredJobAdapter


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
        record = export_database.fetch(context.parameters.get("export_id"))
        if record and record.get("status") == "complete":
            return DeferredJobInspection.APPLIED
        if record and record.get("status") in {"queued", "running", "failed"}:
            return DeferredJobInspection.NOT_APPLIED
        return DeferredJobInspection.DRIFTED

    # @testable infrastructure
    def apply(self, context):
        context.ensure_active()
        export_id = context.parameters["export_id"]
        export_database.update(
            export_id,
            {"status": "running", "started": site_export._utc(), "error": None},
        )
        updates = site_export.build_site_export(export_id)
        record = export_database.update(export_id, updates)
        return {
            key: value for key, value in dict(record or {}).items() if key != "type"
        }

    # @testable infrastructure
    def failure(self, context, error):
        export_id = context.parameters.get("export_id")
        if export_id:
            export_database.update(
                export_id,
                {
                    "status": "failed",
                    "completed": site_export._utc(),
                    "error": str(error),
                },
            )
