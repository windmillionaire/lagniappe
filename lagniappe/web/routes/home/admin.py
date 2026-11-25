from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from lagniappe.core.definitions import Resource
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import home


@home.route("/admin", methods=["GET"])
@permission(Resource.SITE, no_store=True)
def admin() -> ResponseReturnValue:
    return responses.admin_page()
