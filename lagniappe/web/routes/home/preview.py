from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import g, request

from lagniappe.core.tools.links import preview as link_preview
from lagniappe.web import responses
from lagniappe.web.auth import authenticated_user, logged_in

from . import internal


# @testable false
# @covered-by lagniappe/core/tools/links/preview.py::preview_for_url
# @reason route wrapper delegates preview resolution and safety checks to core helper
@internal.route("/preview")
@logged_in
def preview() -> ResponseReturnValue:
    g.NO_CACHE = True

    try:
        data = link_preview.preview_for_url(
            request.args.get("url"),
            user=authenticated_user(),
            base_url=request.host_url,
        )
    except link_preview.PreviewError as error:
        return responses.json_response({"error": str(error)}, status=error.status)

    return responses.json_response(data)
