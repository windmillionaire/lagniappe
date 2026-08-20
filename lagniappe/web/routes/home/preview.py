from flask import g, request
from flask_login import current_user

from lagniappe.core.tools import link_preview
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import internal


# @testable false
# @covered-by lagniappe/core/tools/link_preview.py::preview_for_url
# @reason route wrapper delegates preview resolution and safety checks to core helper
@internal.route("/preview")
@logged_in
def preview():
    g.NO_CACHE = True

    try:
        data = link_preview.preview_for_url(
            request.args.get("url"),
            user=current_user,
            base_url=request.host_url,
        )
    except link_preview.PreviewError as error:
        return responses.json_response({"error": str(error)}, status=error.status)

    return responses.json_response(data)
