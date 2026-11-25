from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from flask import request

from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.web.auth import permission
from lagniappe.web import responses

from . import users


@users.route("/create-group", methods=["POST"])
@permission(Resource.USER_GROUPS, Action.CREATE)
def create_group() -> ResponseReturnValue:
    name = request.form.get("name")
    if not name:
        return responses.error("A group name is required.")
    group = Entities.USER_GROUP.create(name)
    Entities.save(group)

    return responses.create_group(group)


@users.route("/public-permissions", methods=["GET", "PUT"])
@permission(Resource.SITE)
def public_permissions() -> ResponseReturnValue:
    public_group = Entities.PUBLIC_GROUP.get()

    if request.method == "PUT":
        public_group.save_permissions(request.form)

    return responses.group_permissions(public_group, public=True)


@users.route("/group-permissions/<key>", methods=["PUT", "GET"])
@permission(Resource.USER_GROUPS, Action.EDIT)
def group_permissions(
    key: str, **kwargs: Unpack[EntityContext[models.UserGroup]]
) -> ResponseReturnValue:
    group = kwargs["entity"]

    if request.method == "PUT":
        if "name" in request.form:
            name = request.form["name"].strip()
            if not name:
                return responses.error("Name this group before saving.")
            if name == "public":
                return responses.error("public is a reserved group name")
            group.name = name

        group.save_permissions(request.form)

    return responses.group_permissions(group)


@users.route("/delete-group/<key>", methods=["DELETE"])
@permission(Resource.USER_GROUPS, Action.DELETE)
def delete_group(
    key: str, **kwargs: Unpack[EntityContext[models.UserGroup]]
) -> ResponseReturnValue:
    group = kwargs["entity"]

    users_in_group = database_get.users(group=group.key, limit=None)
    users = [user for user in Entities.fetch(*users_in_group.results, request=Fetch.direct()) if isinstance(user, Entities.USER)]
    for user in users:
        user.properties.groups.remove(group)
        user.properties.permissions.create()

    Entities.delete(group)
    Entities.save(*users)

    return responses.ok()
