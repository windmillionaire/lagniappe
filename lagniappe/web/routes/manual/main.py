from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import abort

from lagniappe.core.definitions.manual import (
    MANUAL_SECTIONS,
    VALID_MANUAL_SECTIONS,
)
from lagniappe.web.auth import manual_permission
from lagniappe.web import responses

from . import manual


@manual.route("/", methods=["GET"])
@manual.route("/<section>", methods=["GET"])
@manual_permission()
def index(section: str | None = None) -> ResponseReturnValue:
    if section and section not in VALID_MANUAL_SECTIONS:
        abort(404)

    key = section if section in VALID_MANUAL_SECTIONS else "overview"
    return responses.manual_index(key, MANUAL_SECTIONS)


@manual.route("/section/<section>", methods=["GET"])
@manual_permission()
def content(section: str) -> ResponseReturnValue:
    if section not in VALID_MANUAL_SECTIONS:
        abort(404)

    return responses.manual_content(section)
