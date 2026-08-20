"""Shared route helpers for direct browser-to-Cloud-Storage uploads."""

import json

from flask import abort, request

from lagniappe.core.definitions import FileConsumerLimitError
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.web import responses


# @testable false
# @covered-by lagniappe/web/direct_uploads.py::direct_upload_response
# @reason request payload normalization is exercised through route helpers
def _request_data():
    return request.get_json(silent=True) or request.form or {}


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report_direct
# @covered-by lagniappe/web/routes/pages/main.py::update_direct
# @reason route response is thin plumbing over tested storage session creation
def direct_upload_response():
    """Create a resumable GCS upload session for the current authorized route."""
    data = _request_data()
    try:
        session = storage_assets.create_direct_upload_session(
            filename=data.get("filename"),
            content_type=data.get("content_type"),
            size=data.get("size"),
            input_name=data.get("input_name"),
            origin=request.headers.get("Origin"),
        )
    except Exception as e:
        return responses.error("Could not start direct upload", exception=e)

    return responses.json_response(session)


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::_report_upload_manifest
# @reason request form parser is route-local glue around direct-upload finalization
def direct_upload_records(form, input_name=None):
    """Return submitted direct-upload metadata records from a request form."""
    raw = form.get("direct_uploads")
    if not raw:
        return []

    try:
        records = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []

    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return []

    records = [record for record in records if isinstance(record, dict)]
    if input_name is None:
        return records

    return [record for record in records if record.get("input_name") == input_name]


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::_autofill_data
# @reason storage validation is covered by database asset helper tests
def direct_upload_files(input_name=None, *, consumer=None):
    """Return verified file-like direct uploads for the current request."""
    uploads = []
    for record in direct_upload_records(request.form, input_name=input_name):
        try:
            uploads.append(
                storage_assets.direct_upload_file(record, consumer=consumer)
            )
        except (storage_assets.DirectUploadError, FileConsumerLimitError) as e:
            abort(422, description=str(e))
    return uploads


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::_autofill_data
# @reason single-file convenience wrapper delegates to the list helper
def direct_upload_file(input_name, *, consumer=None):
    """Return the first verified direct upload for a named field."""
    uploads = direct_upload_files(input_name=input_name, consumer=consumer)
    return uploads[0] if uploads else None


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::_autofill_data
# @reason best-effort temp cleanup is exercised through page/task autofill routes
def cleanup_direct_uploads(form, input_name=None):
    """Best-effort delete submitted direct-upload temp objects."""
    for record in direct_upload_records(form, input_name=input_name):
        storage_assets.delete_direct_upload(record)
