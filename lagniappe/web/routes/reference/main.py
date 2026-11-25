from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import abort, g

from config import read_saved_app_settings
from lagniappe.core.definitions import Resource
from lagniappe.core.tools.site.recovery import (
    RecoverySnapshotUnavailable,
    load_recovery_snapshot,
)
from lagniappe.web.auth import logged_in, owner_only, permission
from lagniappe.web import responses

from . import reference


@reference.route("/section/<section>")
@logged_in
def section(section: str) -> ResponseReturnValue:
    """Document settings help page."""
    return responses.reference_topic(section)


@reference.route("/environment-variables")
@permission(Resource.SITE)
def environment_variables() -> ResponseReturnValue:
    """Return environment variables as YAML formatted HTML."""
    env_data = read_saved_app_settings()

    return responses.reference_environment_variables(env_data)


@reference.route("/download-settings")
@owner_only
def download_settings() -> ResponseReturnValue:
    """Download the complete canonical recovery snapshot."""
    g.NO_CACHE = True
    try:
        env_vars = load_recovery_snapshot(read_saved_app_settings())
    except RecoverySnapshotUnavailable as error:
        abort(503, error.public_message)

    return responses.reference_environment_variables(env_vars, download=True)
