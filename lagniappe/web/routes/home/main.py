from flask import abort, request, g, make_response

from flask_login import current_user
from lagniappe.core.definitions import AI, Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.properties.notification_aggregate import counts as aggregate_counts
from lagniappe.core.tools import cache, collaboration
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import notifications as database_notifications
from lagniappe.core.tools.notifications import service as notification_service
from lagniappe.core.tools.polling.projections import (
    channel_revisions,
    render_operation_statuses,
)
from lagniappe.core.properties.activity import NOTE_VISIBILITIES
from lagniappe.web.auth import home_permission, logged_in, require_ai_access
from lagniappe.web import responses

from . import home, internal


# @testable true
# @tests tests_e2e/002_home/test_002a_home.py::test_home_mobile_dashboard_smoke
# @matrix home : layout load mobile
@home.route("/")
@home_permission()
def home_page():
    home = Entities.HOME()
    return responses.home_page(home)


# @testable true
# @tests tests_e2e/002_home/test_002a_home.py::test_tasks_prefetch
# @tests tests_e2e/002_home/test_002a_home.py::test_model_lists_load_on_toggle
# @matrix home : category-list lazy-load prefetch project-list task-count task-list
@internal.route("/get/<kind>")
@home_permission()
def get(kind):
    if kind == "tools":
        require_ai_access(AI.ASK)
    home = Entities.HOME()
    section = home.section(kind, **request.args)
    if kind == "tools":
        render_operation_statuses(section.list, current_user)

    response = make_response(responses.home_section(section))
    channel = {
        "notes": "home-notes",
        "tools": "tool-reports",
    }.get(kind, kind)
    revision = channel_revisions((channel,), current_user)[channel]
    response.headers["X-Lagniappe-Poll-Channel"] = channel
    response.headers["X-Lagniappe-Poll-Revision"] = revision
    return response


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_notes_exclude_notifications
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_channel_uses_menu_not_home_notes
# @matrix activity : cached-response load notes-exclusion notes-only
# @matrix notes : cached-response load notes-only
@internal.route("/activity")
@home_permission()
def activity():
    home = Entities.HOME()
    return responses.activity(home.section("notes"))


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
# @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_assigned_to
# @matrix notifications offline : dropdown-refresh target-link
# @pair notifications:assignee-target
@internal.route("/notifications")
@logged_in
def notifications():
    page = database_notifications.notifications_page(
        current_user,
        start_cursor=request.args.get("cursor"),
        limit=25,
    )
    notification_keys = [row.key for row in page]
    aggregate = database_notifications.repair_notification_aggregate(
        current_user,
    )

    try:
        state = cache.seed_notification_state(
            current_user,
            notification_keys=notification_keys,
            aggregate_loader=lambda _user: aggregate,
            repair=True,
        )
        responses.publish_notification_state(state)
    except Exception as error:
        exceptions.capture(error, context={"operation": "notification-state-repair"})
    target_keys = [row.get("target") for row in page if row.get("target")]
    loaded = Entities.fetch(
        *notification_keys,
        *target_keys,
        request=Fetch.direct(),
    )
    notifications = [
        entity for entity in loaded if isinstance(entity, Entities.NOTIFICATION)
    ]
    g.NO_CACHE = True
    return responses.notifications(
        notifications,
        aggregate=aggregate_counts(aggregate),
        cursor=page.next_cursor,
        can_message=collaboration.can_initiate_messages(current_user),
    )


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_deletes_and_clears
# @matrix notifications : clear-all ownership
@internal.route("/notifications", methods=["DELETE"])
@logged_in
def clear_notifications():
    notification_keys = database_notifications.notification_keys(current_user)
    notification_service.clear_ordinary_notifications(current_user, notification_keys)
    aggregate = database_notifications.get_notification_aggregate(current_user)
    notification_service.publish_notification_aggregate(current_user, aggregate)

    return responses.ok()


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_create_note_body_and_photo_from_home
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_note_shared_visibility_is_owner_only
# @matrix activity : body create owner-only-shared parent photo scope visibility
# @matrix notes : body create owner-only-shared parent photo private-default scope visibility
# @pair permissions:owner-only-shared
@internal.route("/activity/notes", methods=["POST"])
@logged_in
def create_note():
    body = (request.form.get("body") or "").strip()
    photo = request.files.get("note-file")
    has_photo = bool(photo and getattr(photo, "filename", None))
    if not body and not has_photo:
        return responses.error("Add a note before saving.")

    visibility = request.form.get("visibility") or "private"
    if visibility not in NOTE_VISIBILITIES:
        return responses.error("Choose who can see this note.")
    if visibility == "everyone" and not Resource.SITE.allowed(Action.EDIT):
        abort(403)

    note_data = {
        "parent": current_user,
        "user": current_user,
        "body": body,
        "photo": photo if has_photo else None,
        "visibility": visibility,
        "scope": "home",
    }

    new_note = Entities.NOTE.create(note_data)
    Entities.save(new_note)

    return responses.new_note(new_note, surface="home")


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_delete_activity_item_from_home
# @matrix activity notes notifications : delete ownership
@internal.route("/activity/<key>", methods=["DELETE"])
@logged_in
def delete_activity(key):
    activity = Entities.fetch_one(key, request=Fetch.direct())
    if not activity or activity.kind not in ("note", "notification"):
        return responses.not_found("Activity item not found")

    if activity.kind == "note" and not activity.allowed(
        Action.DELETE, user=current_user
    ):
        abort(403)
    elif (
        activity.kind == "notification"
        and activity.properties.parent.key != current_user.key
    ):
        abort(403)

    if activity.kind == "notification":
        if activity.notification_type != "ordinary":
            abort(403)
        notification_service.delete_ordinary_notification(current_user, activity.key)
        aggregate = database_notifications.get_notification_aggregate(current_user)
        notification_service.publish_notification_aggregate(current_user, aggregate)
    else:
        Entities.delete(activity)

    return responses.ok()


# @testable true
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_file
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_route_rejects_inaccessible_and_missing_targets
# @matrix starred : add-authorization category file missing-target no-mutation page project unavailable-removal
@internal.route("/toggle-star/<key>", methods=["PATCH"])
@logged_in
def toggle_star(key):
    """Toggle starred status for an entity.

    Removing a stored key mutates only the authenticated user's own starred
    list, so it remains available when the target is inaccessible or missing.
    Adding a key still requires VIEW access to an existing entity.
    """
    stored_key = database_get.datastore_key(key)
    if stored_key in current_user.properties.starred.keys:
        current_user.properties.starred.delete_starred_keys([stored_key])
        starred = False
    else:
        entity = Entities.fetch_one(key, request=Fetch.direct())
        if entity is None:
            abort(404)
        if not entity.allowed(Action.VIEW, user=current_user):
            abort(403)
        starred = current_user.properties.starred.add(entity)

    current_user.save()

    return responses.json_response({"starred": starred})
