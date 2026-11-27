from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import UserCreationData
    from flask import Request
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from flask import abort, request
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core.entities import Entities, index
from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.tools.services import identity_platform
from lagniappe.web.auth import permission
from lagniappe.web.pagination import pagination_options
from lagniappe.web import responses

from . import users


@users.route("/index", methods=["GET"])
@permission(Resource.USERS, Action.RESTRICTED)
def user_index() -> ResponseReturnValue:
    user_index = index.UserIndex()

    return responses.index("users", user_index)


@users.route("/rows", methods=["GET"])
@permission(Resource.USERS, Action.VIEW)
def rows() -> ResponseReturnValue:
    user_index = index.UserIndex(mode=request.args.get("mode"), **pagination_options())
    users = user_index.users

    return responses.rows(users, user_index)


def user_data(request: Request) -> UserCreationData:
    if "ai_access" in request.form and not current_user.is_admin:
        abort(403)

    selected_page = request.form.get("page")
    page = Entities.fetch_one(selected_page, request=Fetch.direct()) if selected_page else None
    if page is not None and not isinstance(page, Entities.PAGE):
        raise ValueError("Selected page is unavailable.")
    data: UserCreationData = {
        "name": request.form.get("name"),
        "email": request.form.get("email"),
        "page": page,
        "groups": [Entities.USER_GROUP(g) for g in request.form.getlist("group") if g],
    }
    if "ai_access" in request.form:
        data["ai_access"] = request.form.get("ai_access")
    return data


def _delete_identity_login_account(user):
    if not user or CONFIG.testing or getattr(user, "is_test_user", False):
        return

    email = str(getattr(user, "email", "") or "").strip().lower()
    if not email:
        return

    identity_platform.delete_account_by_email(email)


@users.route("/create", methods=["POST"])
@permission(Resource.USERS, Action.CREATE)
def create() -> ResponseReturnValue:
    requested_email = str(request.form.get("email") or "").strip().casefold()
    owner_email = str(CONFIG.ADMIN_EMAIL or "").strip().casefold()
    if requested_email and requested_email == owner_email:
        return responses.error(
            "The site owner's email address cannot be used to create a new user."
        )
    try:
        new_user = Entities.USER.create(
            user_data(request),
            adopt_public=current_user.is_admin,
        )
    except (TypeError, ValueError) as error:
        return responses.error(str(error))

    new_user.save()

    return responses.rows(new_user, index.UserIndex())


@users.route("<key>/delete", methods=["DELETE"])
@permission(Resource.USERS, Action.DELETE)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.User | models.Page]]
) -> ResponseReturnValue:
    entity = kwargs["entity"]
    if not entity:
        return responses.not_found("User not found")

    page = entity.page if isinstance(entity, Entities.USER) else entity
    if not isinstance(page, Entities.PAGE):
        return responses.not_found("User not found")

    user = entity if isinstance(entity, Entities.USER) else page.user
    if user and user.is_owner:
        abort(403)
    if user and user.is_admin and not current_user.is_owner:
        abort(403)
    try:
        _delete_identity_login_account(user)
    except Exception as e:
        return responses.error(
            "Could not delete the user's login account. Please try again.",
            exception=e,
        )

    options = request.get_json(silent=True) or {}
    if options.get("delete-page", True) is False:
        if user is None:
            return responses.not_found("User not found")
        Entities.delete(user, preserve_user_pages=True)
    else:
        Entities.delete(page)

    return responses.ok()


@users.route("<key>/add-groups", methods=["PUT"])
@permission(Resource.USER, Action.PERMISSIONS)
def add_groups(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    groups = [Entities.USER_GROUP(g) for g in request.form.getlist("group") if g]
    user = page.user
    if user is None:
        return responses.not_found("User not found")
    user.groups = groups
    user.properties.permissions.create()
    user.save()

    return responses.ok()
