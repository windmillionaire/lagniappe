from flask import request

from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.web.auth import permission
from lagniappe.web import responses

from . import users


# @testable true
# @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
# @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
# @features user-groups
# @dimensions group-create nav
@users.route("/create-group", methods=["POST"])
@permission(Resource.USER_GROUPS, Action.CREATE)
def create_group():
    group = Entities.USER_GROUP.create(request.form.get("name"))
    Entities.save(group)

    return responses.create_group(group)


# @testable true
# @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_public_permissions
# @tests tests_unit/test_009e_user_groups.py::test_public_permissions
@users.route("/public-permissions", methods=["GET", "PUT"])
@permission(Resource.SITE)
def public_permissions():
    public_group = Entities.PUBLIC_GROUP.get()

    if request.method == "PUT":
        public_group.save_permissions(request.form)

        return responses.group_permissions(public_group, public=True, update=True)

    return responses.group_permissions(public_group, public=True, update=True)


# @testable true
# @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
# @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
# @tests tests_e2e/008_users/test_008b_user_groups.py::test_rename_group
# @features user-groups
# @dimensions permission-update general-permissions entity-permissions rename
@users.route("/group-permissions/<key>", methods=["PUT", "GET"])
@permission(Resource.USER_GROUPS, Action.EDIT)
def group_permissions(key, **kwargs):
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

        return responses.group_permissions(group, update=True)

    return responses.group_permissions(group, update=True)


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_groups_membership_changes_recalculate_permissions
@users.route("/delete-group/<key>", methods=["DELETE"])
@permission(Resource.USER_GROUPS, Action.DELETE)
def delete_group(key, **kwargs):
    group = kwargs["entity"]

    users_in_group = database.get.users(group=group.key, limit=None)
    users = Entities.fetch(*users_in_group.results, request=Fetch.direct())
    for user in users:
        user.properties.groups.remove(group)
        user.properties.permissions.create()

    Entities.delete(group)
    Entities.save(*users)

    return responses.ok()
