from flask import abort, request, g

from flask_login import current_user
from lagniappe.core.definitions import AI, Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.properties.activity import NOTE_VISIBILITIES
from lagniappe.web.auth import home_permission, logged_in, require_ai_access
from lagniappe.web import responses

from . import home


# @testable true
# @tests tests_e2e/002_home/test_002a_home.py::test_home_mobile_dashboard_smoke
# @features home
# @dimensions load layout mobile
@home.route("/")
@home_permission()
def home_page():
    home = Entities.HOME()
    return responses.home_page(home)


# @testable true
# @tests tests_e2e/002_home/test_002a_home.py::test_tasks_prefetch
# @tests tests_e2e/002_home/test_002a_home.py::test_model_lists_load_on_toggle
# @features home
# @dimensions prefetch lazy-load task-list task-count project-list category-list
@home.route("/get/<kind>")
@home_permission()
def get(kind):
    if kind == "tools":
        require_ai_access(AI.ASK)
    home = Entities.HOME()
    section = home.section(kind, **request.args)

    return responses.home_section(section)


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_notes_exclude_notifications
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_channel_uses_menu_not_home_notes
# @features activity notes
# @dimensions load cached-response notes-only
# @pair activity:notes-exclusion
@home.route("/activity")
@home_permission()
def activity():
    home = Entities.HOME()
    return responses.activity(home.section("notes"))


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
# @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
# @pair notifications:dropdown-refresh
# @pair notifications:target-link
# @pair offline:dropdown-refresh
# @pair offline:target-link
@home.route("/notifications")
@logged_in
def notifications():
    notification_keys = Entities.NOTIFICATION.keys_for_parent(current_user)
    notifications = Entities.fetch(*notification_keys, request=Fetch.direct())
    g.NO_CACHE = True
    return responses.notifications(notifications)


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_deletes_and_clears
# @features notifications
# @dimensions clear-all ownership
@home.route("/notifications", methods=["DELETE"])
@logged_in
def clear_notifications():
    notification_keys = Entities.NOTIFICATION.keys_for_parent(current_user)
    notifications = Entities.fetch(*notification_keys, request=Fetch.root())
    Entities.delete(*notifications)
    Entities.advance_notifications(current_user)

    return responses.ok()


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_create_note_body_and_photo_from_home
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_note_shared_visibility_is_owner_only
# @features activity notes
# @dimensions create body photo parent visibility scope
# @pair activity:create
# @pair activity:body
# @pair activity:photo
# @pair activity:parent
# @pair activity:visibility
# @pair activity:scope
# @pair activity:owner-only-shared
# @pair notes:create
# @pair notes:body
# @pair notes:photo
# @pair notes:parent
# @pair notes:visibility
# @pair notes:scope
# @pair notes:owner-only-shared
# @pair notes:private-default
# @pair permissions:owner-only-shared
@home.route("/activity/notes", methods=["POST"])
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
# @features activity notes notifications
# @dimensions delete ownership
@home.route("/activity/<key>", methods=["DELETE"])
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

    Entities.delete(activity)
    if activity.kind == "notification":
        Entities.advance_notifications(current_user)

    return responses.ok()


# @testable true
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_file
# @features starred
# @dimensions category project page file
@home.route("/toggle-star/<key>", methods=["PATCH"])
@logged_in
def toggle_star(key):
    """Toggle starred status for an entity.

    Returns JSON with the new starred status. Client updates
    the star control state.
    """
    entity = Entities.fetch_one(
        key,
        request=Fetch.direct(),
    )
    user = Entities.fetch_one(current_user, request=Fetch.direct())
    starred = user.properties.starred.toggle_star(entity)
    user.save()

    return responses.json_response({"starred": starred})
