"""Persisted input and origin fields for AI reports."""

from .base_db import DBProperty

# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_create_and_file_cleanup
# @features ai-report
# @dimensions upload-manifest
class UploadManifest(DBProperty):
    """Signed direct-upload records awaiting background finalization."""

    _id = "upload_manifest"
    json = True


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_shape_preserves_safe_inbound_display_fields
# @features ai-email ai-report
# @dimensions origin legacy-default
class Origin(DBProperty):
    """How the initial report was submitted; legacy reports are web-origin."""

    _id = "origin"

    @property
    def value(self):
        return DBProperty.value.fget(self) or "web"

    @value.setter
    def value(self, value):
        normalized = str(value or "web").strip().casefold()
        if normalized not in {"web", "email"}:
            raise ValueError("AI report origin must be web or email")
        DBProperty.value.fset(self, normalized)


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_shape_preserves_safe_inbound_display_fields
# @features ai-email ai-report
# @dimensions inbound-manifest privacy
class InboundManifest(DBProperty):
    """Safe normalized email fields displayed with an email-origin report."""

    _id = "inbound_manifest"
    json = True
