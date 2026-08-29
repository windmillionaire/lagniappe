from flask import abort, request
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core.entities import Entities, index
from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.tools.services import identity_platform
from lagniappe.web.auth import permission
from lagniappe.web import responses

from . import users


# @testable true
# @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
# @matrix users : index-mode-toggle refresh table-row
@users.route("/index", methods=["GET"])
@permission(Resource.USERS, Action.RESTRICTED)
def user_index():
    user_index = index.UserIndex()

    return responses.index("users", user_index)


# @testable true
# @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
# @tests tests_unit/test_009_user_index.py::test_user_index_loads_users_groups_public_group_and_append_cursor
# @matrix users : index-mode-toggle refresh table-row
# @pair user-index:public-group
@users.route("/rows", methods=["GET"])
@permission(Resource.USERS, Action.VIEW)
def rows():
    user_index = index.UserIndex(**request.values)
    users = user_index.users

    return responses.rows(users, user_index)


# @testable false
# @covered-by lagniappe/web/routes/users/main.py::create
# @reason form parsing helper owned by user create route
def user_data(request):
    if "ai_access" in request.form and not current_user.is_admin:
        abort(403)

    data = {
        "name": request.form.get("name"),
        "email": request.form.get("email"),
        "page": (
            Entities.fetch_one(request.form.get("page"), request=Fetch.direct())
            if request.form.get("page")
            else None
        ),
        "groups": [Entities.USER_GROUP(g) for g in request.form.getlist("group") if g],
    }
    if "ai_access" in request.form:
        data["ai_access"] = request.form.get("ai_access")
    return data


# @testable false
# @manual true
# @covered-by lagniappe/web/routes/users/main.py::delete
# @reason Identity Platform cleanup is provider-facing route glue; missing accounts are a valid no-op
def _delete_identity_login_account(user):
    if not user or CONFIG.testing or getattr(user, "is_test_user", False):
        return

    email = str(getattr(user, "email", "") or "").strip().lower()
    if not email:
        return

    identity_platform.delete_account_by_email(email)


# @testable true
# @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_from_index
# @tests tests_e2e/008_users/test_008a_user_index.py::test_owner_create_adopts_public_user_and_resets_form
# @tests tests_e2e/008_users/test_008a_user_index.py::test_non_owner_cannot_set_ai_access_when_creating_user
# @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_attached_to_existing_page_preserves_page_info_form
# @matrix users : ai-access attach-existing-page create-submit created-row owner-only page-form-preserved public-user-adoption submitted-form-data
@users.route("/create", methods=["POST"])
@permission(Resource.USERS, Action.CREATE)
def create():
    requested_email = str(request.form.get("email") or "").strip().casefold()
    owner_email = str(CONFIG.ADMIN_EMAIL or "").strip().casefold()
    if requested_email and requested_email == owner_email:
        abort(403)
    try:
        new_user = Entities.USER.create(
            user_data(request),
            adopt_public=current_user.is_admin,
        )
    except (TypeError, ValueError) as error:
        return responses.error(str(error))

    new_user.save()

    return responses.rows(new_user, index.UserIndex())


# @testable true
# @tests tests_e2e/008_users/test_008a_user_index.py::test_delete_user_can_preserve_page
# @matrix pages users : category-fallback default-cascade delete preserve-page
@users.route("<key>/delete", methods=["DELETE"])
@permission(Resource.USERS, Action.DELETE)
def delete(key, **kwargs):
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
        Entities.delete(user, preserve_user_pages=True)
    else:
        Entities.delete(page)

    return responses.ok()


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
# @tests tests_unit/test_009a_user.py::test_user_groups_membership_changes_recalculate_permissions
# @pairs user-groups:membership-change user-settings:owner-other-page
@users.route("<key>/add-groups", methods=["PUT"])
@permission(Resource.USER, Action.PERMISSIONS)
def add_groups(key, **kwargs):
    page = kwargs["entity"]

    groups = [Entities.USER_GROUP(g) for g in request.form.getlist("group") if g]
    page.user.groups = groups
    page.user.properties.permissions.create()
    page.user.save()

    return responses.ok()
