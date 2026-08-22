"""Administrator site export routes."""

from flask import get_template_attribute, request
from flask_login import current_user

from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import site_exports as export_database
from lagniappe.core.tools.site import exports as site_export
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import internal


# @testable false
# @covered-by lagniappe/web/routes/home/exports.py::site_export_widget
# @reason template rendering is exercised through the admin export widget route
def _site_export_html():
    template = get_template_attribute("home/export.html", "site_export")
    return template(export_database.recent())


# @testable true
# @tests tests_e2e/001_site/test_001f_site_export.py::test_owner_can_start_html_export
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_additional_admin_cannot_access_owner_configuration
# @pairs export:admin-only export:start-export
@internal.route("/site-export", methods=["GET"])
@permission(Resource.SITE)
def site_export_widget():
    return _site_export_html(), 200


# @testable true
# @tests tests_e2e/001_site/test_001f_site_export.py::test_owner_can_start_html_export
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_additional_admin_cannot_access_owner_configuration
# @pairs export:admin-only export:owner-only export:start-export export:notification
@internal.route("/site-export", methods=["POST"])
@permission(Resource.SITE)
def create_site_export():
    body = request.get_json(silent=True) or request.form
    record = site_export.create_export_record()
    job, notification = DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.SITE_EXPORT,
            actor=current_user._get_current_object(),
            idempotency_key=body.get("operation_id"),
            inputs={},
            parameters={"export_id": record["id"]},
            notification_body="Building HTML export archive...",
            client={
                "source_widget": "SiteExport",
                "destination": "exports:SiteExport",
            },
        )
    )

    notification = (
        Entities.fetch_one(notification.urlsafe_key, request=Fetch.direct())
        or notification
    )
    return responses.json_response(
        {
            "deferred": True,
            "operation": job.urlsafe_key,
            "notification": responses.notification_item(notification),
            "html": _site_export_html(),
        }
    )
