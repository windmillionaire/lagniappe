"""E2E coverage for homepage activity, notifications, and offline replay."""

from uuid import uuid4

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.web.routes.process.main import _create_notification
from testing.definitions import DueDates, Pages, SitePages, Users
from testing.definitions.task_definitions import TaskDefinition
from testing.elements import Buttons, FormElements, List, Modal
from testing.resources import Task
from testing.utility import TestFile as _TestFile, trigger_poll
from testing.utility.local_time import local_date_from_utc_datetime

pytestmark = pytest.mark.e2e


def _unique(label):
    return f"{label} {uuid4().hex[:8]}"


def _activity_item(home, text):
    return home.user.locate(home.NOTE_LIST).locator("li").filter(has_text=text).first


def _task_item(home, text):
    return home.user.locate(home.TASK_LIST).locator("li").filter(has_text=text).first


def _loaded_activity_list(home):
    activity_list = List(home.user.locate(home.NOTE_LIST))
    assert activity_list.is_loaded
    return activity_list


def _loaded_task_list(home):
    task_list = List(home.user.locate(home.TASK_LIST))
    assert task_list.is_loaded
    return task_list


def _save_note(user, body, visibility="private"):
    note = Entities.NOTE.create(
        {
            "parent": user.entity,
            "user": user.entity,
            "body": body,
            "visibility": visibility,
            "scope": "home",
        }
    )
    Entities.save(note)
    return note


def _save_notification(user, body, target=None, pending=False):
    notification = Entities.NOTIFICATION.create(
        {
            "parent": user.entity,
            "target": target,
            "body": body,
            "pending": pending,
        }
    )
    Entities.save(notification, user.entity)
    return notification


def _save_personal_task(user, name):
    task = Task(
        user=user,
        definition=TaskDefinition(
            name=name,
            origin=SitePages.HOME,
            due_date=DueDates.personal_task_due_today,
        ),
    )
    return task.create()


def _user_key(user):
    return user.entity.urlsafe_key


def _create_text_note_from_home(
    user, home, body, expect_network=True, visible_text=None, visibility=None
):
    home.user.locate(home.CREATE_NOTE_TOGGLE).click()
    form = home.user.locate(home.CREATE_NOTE_FORM)
    expect(form).to_be_visible()
    form.locator("textarea[name='body']").fill(body)
    if visibility:
        form.locator(
            f"input[name='visibility'][value='{visibility}']"
        ).check()
    else:
        expect(
            form.locator("input[name='visibility'][value='private']")
        ).to_be_checked()

    if expect_network:
        with user.page.expect_response("**/activity/notes"):
            form.locator("button[type='submit']").click()
    else:
        form.locator("button[type='submit']").click()

    item = _activity_item(home, visible_text or body)
    expect(item).to_be_visible()
    return item


def _create_photo_note_from_home(user, home, body, visibility="private"):
    home.user.locate(home.CREATE_NOTE_TOGGLE).click()
    form = home.user.locate(home.CREATE_NOTE_FORM)
    expect(form).to_be_visible()
    form.locator("textarea[name='body']").fill(body)
    form.locator(
        f"input[name='visibility'][value='{visibility}']"
    ).check()

    with user.page.expect_file_chooser() as chooser_info:
        form.locator("[data-action='add-photo']").click()
    chooser_info.value.set_files(_TestFile("editor_test_image.jpeg").path)
    expect(form.locator("textarea[name='body']")).to_be_visible()
    expect(form.locator("textarea[name='body']")).to_have_value(body)
    expect(form.locator("[data-role='photo-preview']")).to_be_visible()

    with user.page.expect_response("**/activity/notes"):
        form.locator("button[type='submit']").click()

    item = _activity_item(home, body)
    expect(item).to_be_visible()
    expect(item.locator("img")).to_be_attached()
    return item


def _create_task_from_home(home, name, expect_network=True):
    home.user.locate(home.CREATE_TASK_TOGGLE).click()
    form = home.user.locate(home.CREATE_TASK_FORM)
    expect(form).to_be_visible()

    form.locator(FormElements.NAME).fill(name)
    form.locator('button[data-action="schedule"]').click()
    expect(form.locator('input[name="due-date"]')).to_be_visible()
    DueDates.personal_task_due_today.set(form)

    if expect_network:
        with home.user.page.expect_response("**/personal"):
            form.locator("button[type='submit']").click()
    else:
        form.locator("button[type='submit']").click()

    item = _task_item(home, name)
    expect(item).to_be_visible()
    return item


def _open_and_close_create_form(home, toggle_selector, form_selector):
    home.user.locate(toggle_selector).click()
    form = home.user.locate(form_selector)
    expect(form).to_be_visible()
    form.locator(Buttons.LP_CLOSE).click()
    expect(form).to_be_hidden()


def _warm_offline_create_widgets(home, *, note=True, task=True):
    if note:
        _open_and_close_create_form(
            home,
            home.CREATE_NOTE_TOGGLE,
            home.CREATE_NOTE_FORM,
        )
    if task:
        _open_and_close_create_form(
            home,
            home.CREATE_TASK_TOGGLE,
            home.CREATE_TASK_FORM,
        )


# @features activity notes notifications
# @dimensions load cached-response notes-only
# @template home/notes.html::list
# @template home/notes.html::note_item
def test_home_notes_exclude_notifications(get_user):
    user = get_user(Users.OWNER)
    note_body = _unique("Activity note load")
    notification_body = _unique("Activity notification load")
    _save_note(user, note_body)
    _save_notification(user, notification_body)

    home = user.go(SitePages.HOME)
    activity_list = home.activity_list.list

    expect(activity_list).to_contain_text(note_body)
    expect(activity_list).not_to_contain_text(notification_body)
    expect(_activity_item(home, notification_body)).not_to_be_attached()


# @pair activity:create
# @pair activity:body
# @pair activity:photo
# @pair activity:parent
# @pair activity:visibility
# @pair activity:scope
# @pair activity:asset-lifecycle
# @pair activity:html-stripping
# @pair notes:create
# @pair notes:body
# @pair notes:photo
# @pair notes:parent
# @pair notes:visibility
# @pair notes:scope
# @pair notes:asset-lifecycle
# @pair notes:html-stripping
# @pair notes:private-default
# @template home/notes.html::add_note_form
# @template notes.html::note_item
def test_create_note_body_and_photo_from_home(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    raw_body = f"<strong>{_unique('Activity body note')}</strong>"
    visible_body = raw_body.replace("<strong>", "").replace("</strong>", "")
    text_item = _create_text_note_from_home(
        user, home, raw_body, visible_text=visible_body
    )
    text_key = text_item.get_attribute("data-key")
    text_note = Entities.fetch_one(text_key, request=Fetch.direct())

    assert text_note.body == visible_body
    assert text_note.visibility == "private"
    assert text_note.properties.parent.key == user.entity.key
    assert text_note.properties.user.key == user.entity.key
    expect(text_item).to_contain_text(visible_body)
    expect(text_item).not_to_contain_text("<strong>")

    photo_body = _unique("Activity photo note")
    photo_item = _create_photo_note_from_home(
        user, home, photo_body, visibility="everyone"
    )
    photo_note = Entities.fetch_one(
        photo_item.get_attribute("data-key"), request=Fetch.direct()
    )

    assert photo_note.body == photo_body
    assert photo_note.visibility == "everyone"
    assert photo_note.scope == "home"
    assert "photo" in photo_note.assets
    expect(photo_item).to_contain_text("Everyone")


# @pairs activity:owner-only-shared notes:owner-only-shared permissions:owner-only-shared
# @template home/home.html::create
# @template notes.html::composer
def test_home_note_shared_visibility_is_owner_only(get_user):
    user = get_user(Users.create_user)
    home = user.go(SitePages.HOME)

    expect(user.locate(home.CREATE_NOTE_TOGGLE)).to_be_visible()
    user.locate(home.CREATE_NOTE_TOGGLE).click()
    form = user.locate(home.CREATE_NOTE_FORM)
    expect(form).to_be_visible()
    expect(
        form.locator("input[name='visibility'][value='everyone']")
    ).not_to_be_attached()
    expect(
        form.locator("input[name='visibility'][value='private']")
    ).to_be_checked()

    private_body = _unique("Private Home note")
    form.locator("textarea[name='body']").fill(private_body)
    with user.page.expect_response("**/activity/notes"):
        form.locator("button[type='submit']").click()
    private_item = _activity_item(home, private_body)
    expect(private_item).to_be_visible()
    expect(private_item).to_contain_text("Private")

    cookies = {
        cookie["name"]: cookie["value"] for cookie in user.page.context.cookies()
    }
    response = requests.post(
        f"{SETTINGS.test_config['BASE_URL']}/activity/notes",
        data={"body": _unique("Forbidden Home note"), "visibility": "everyone"},
        cookies=cookies,
        headers={
            "X-CSRFToken": user.locate("#token").input_value(),
            "X-Lagniappe-Request": "true",
        },
        allow_redirects=False,
        timeout=10,
    )

    assert response.status_code == 403


# @pair activity:delete
# @pair activity:ownership
# @pair notes:delete
# @pair notes:ownership
# @pair notifications:delete
# @pair notifications:ownership
# @template notes.html::note_item
def test_delete_activity_item_from_home(get_user):
    user = get_user(Users.OWNER)
    other_user = get_user(Users.create_user, creator=user)
    own_body = _unique("Activity note delete")
    remote_body = _unique("Activity polling delete")
    other_body = _unique("Other user activity note")
    own_note = _save_note(user, own_body)
    remote_note = _save_note(user, remote_body)
    _save_note(other_user, other_body)

    home = user.go(SitePages.HOME)
    activity_list = home.activity_list.list

    own_item = _activity_item(home, own_body)
    expect(own_item).to_be_visible()
    own_item.locator(Buttons.LP_DELETE).click()
    modal = Modal(user.page)
    expect(modal.element).to_contain_text("Delete Note")
    modal.element.get_by_role("button", name="Cancel").click()
    expect(modal.element).to_be_hidden()
    expect(own_item).to_be_visible()

    own_item.locator(Buttons.LP_DELETE).click()
    with user.page.expect_response(
        lambda response: response.request.method == "DELETE"
        and response.url.endswith(f"/activity/{own_note.urlsafe_key}")
    ):
        modal.delete()
    expect(own_item).not_to_be_visible()

    remote_item = _activity_item(home, remote_body)
    expect(remote_item).to_be_visible()
    Entities.delete(remote_note)
    trigger_poll(user)
    expect(remote_item).not_to_be_visible()
    expect(activity_list).to_contain_text(other_body)


# @pair activity:home
# @pair activity:shared
# @pair activity:private
# @pair activity:owner
# @pair notes:home
# @pair notes:shared
# @pair notes:private
# @pair notes:owner
# @pair permissions:home
# @pair permissions:shared
# @pair permissions:private
# @pair permissions:owner
# @template notes.html::note_item
def test_home_note_visibility_across_users(get_user):
    owner = get_user(Users.OWNER)
    author = get_user(Users.create_user, creator=owner)
    viewer = get_user(Users.create_user_from_index, creator=owner)
    shared_body = _unique("Shared Home note")
    private_body = _unique("Private Home note")
    _save_note(author, shared_body, visibility="everyone")
    _save_note(author, private_body, visibility="private")

    viewer_home = viewer.go(SitePages.HOME)
    viewer_home.activity_list
    expect(_activity_item(viewer_home, shared_body)).to_be_visible()
    expect(_activity_item(viewer_home, private_body)).not_to_be_attached()

    author_home = author.go(SitePages.HOME)
    author_home.activity_list
    expect(_activity_item(author_home, shared_body)).to_be_visible()
    expect(_activity_item(author_home, private_body)).to_be_visible()

    owner_home = owner.go(SitePages.HOME)
    owner_home.activity_list
    expect(_activity_item(owner_home, private_body)).to_be_visible()


# @pairs activity:create activity:body activity:parent activity:task-queue
# @pairs activity:html-stripping activity:notes-exclusion activity:load
# @pairs activity:cached-response activity:notes-only
# @pairs notes:load notes:cached-response notes:notes-only
# @pairs notifications:create notifications:body notifications:parent
# @pairs notifications:task-queue notifications:html-stripping
# @template notifications.html::item
def test_process_notification_uses_menu_not_home_notes(get_user):
    user = get_user(Users.OWNER)
    note_body = _unique("Process notification control note")
    raw_body = f"<em>{_unique('Process notification complete')}</em>"
    visible_body = raw_body.replace("<em>", "").replace("</em>", "")

    _save_note(user, note_body)
    _create_notification(
        {"user_key": _user_key(user)},
        raw_body,
    )

    home = user.go(SitePages.HOME)
    home.activity_list
    expect(_activity_item(home, note_body)).to_be_visible()
    expect(_activity_item(home, visible_body)).not_to_be_attached()

    notifications = user.locate("[data-role='notifications']")
    expect(notifications).to_be_visible(timeout=15000)
    notifications.click()
    panel = user.page.locator("[role='listbox'][data-visible='true']")
    option = panel.locator("[role='option']").filter(has_text=visible_body)
    expect(option).to_be_visible()
    expect(option).not_to_contain_text("<em>")


# @features notifications
# @dimensions dropdown-refresh target target-link pending long-text-wrap
# @template notifications.html::item
def test_notification_menu_renders_target_and_preserves_pending_state(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_create_page.get(user)
    body = f"{_unique('Notification target pending')} Error:{'x' * 240}"
    notification = _save_notification(user, body, target=page.entity, pending=True)
    report_summary = _unique("Create a category and sort the uploaded files")
    report = Entities.REPORT.create(
        {
            "parent": user.entity,
            "user": user.entity,
            "name": "Organize: 3 files",
            "tool": "organize",
            "status": "ready",
            "pending": False,
            "summary": report_summary,
        }
    )
    report_body = _unique("Organize report is ready")
    Entities.save(report, user.entity)
    _save_notification(user, report_body, target=report)
    assert notification.pending is True
    assert (
        Entities.fetch_one(notification.urlsafe_key, request=Fetch.direct()).pending
        is True
    )

    user.go(SitePages.HOME)
    notifications = user.locate("[data-role='notifications']")
    expect(notifications).to_be_visible(timeout=15000)
    notifications.click()

    panel = user.page.locator("[role='listbox'][data-visible='true']")
    option = panel.locator("[role='option']").filter(has_text=body)
    expect(option).to_be_visible()
    panel_box = panel.bounding_box()
    option_box = option.bounding_box()
    assert panel_box and panel_box["width"] <= 400
    assert option_box and option_box["width"] <= panel_box["width"] + 1

    target = option.locator("[data-role='target']")
    expect(target).to_be_visible()
    expect(target).to_have_attribute("data-kind", "page")
    expect(target).to_contain_text(page.name)

    report_option = panel.locator("[role='option']").filter(has_text=report_body)
    expect(report_option).to_be_visible()
    report_target = report_option.locator("[data-role='target']")
    expect(report_target).to_have_attribute(
        "href", f"/tools/reports/{report.urlsafe_key}"
    )
    expect(report_target).to_have_text("Organize 3 files")
    expect(report_target.locator("[data-role='report-tool']")).to_have_css(
        "font-weight", "400"
    )
    expect(report_target.locator("[data-role='report-title']")).to_have_css(
        "font-weight", "600"
    )
    expect(report_option.locator("[data-role='report-summary']")).to_have_text(
        report_summary
    )
    expect(
        report_option.locator("[data-action='delete-notification']")
    ).to_have_css("float", "right")


# @features notifications
# @dimensions delete clear-all menu-open ownership dropdown-refresh
def test_notification_menu_deletes_and_clears(get_user):
    user = get_user(Users.OWNER)
    first_body = _unique("Notification delete one")
    second_body = _unique("Notification clear rest")
    starting_count = len(Entities.NOTIFICATION.keys_for_parent(user.entity))
    first = _save_notification(user, first_body)
    second = _save_notification(user, second_body)

    user.go(SitePages.HOME)
    notifications = user.locate("[data-role='notifications']")
    expect(notifications).to_be_visible(timeout=15000)
    expect(notifications).to_have_attribute(
        "aria-label", f"Notifications: {starting_count + 2}"
    )

    notifications.click()
    panel = user.page.locator("[role='listbox'][data-visible='true']")
    expect(panel).to_be_visible()

    clear_all = panel.locator("[data-action='clear-notifications']")
    expect(clear_all).to_be_visible()
    expect(clear_all).to_have_css("border-radius", "0px")
    expect(panel.locator("[role='option']").first).to_have_attribute(
        "data-action", "clear-notifications"
    )

    first_option = panel.locator("[role='option']").filter(has_text=first_body)
    expect(first_option).to_be_visible()
    with user.page.expect_response(f"**/activity/{first.urlsafe_key}"):
        first_option.locator("[data-action='delete-notification']").click()

    expect(panel).to_be_visible()
    expect(first_option).not_to_be_attached()
    expect(panel).to_contain_text(second_body)
    expect(notifications).to_have_attribute(
        "aria-label", f"Notifications: {starting_count + 1}"
    )

    with user.page.expect_response(
        lambda response: response.request.method == "DELETE"
        and response.url.endswith("/notifications")
    ):
        clear_all.click()

    expect(panel).to_be_hidden()
    expect(notifications).to_have_attribute("data-visible", "false")
    expect(notifications).to_have_attribute("aria-label", "Notifications: 0")
    assert Entities.fetch_one(first.urlsafe_key, request=Fetch.root()) is None
    assert Entities.fetch_one(second.urlsafe_key, request=Fetch.root()) is None


# @features offline
# @dimensions queue-create reload
# @template home/notes.html::note_item
# @template home/tasks.html::task
def test_offline_home_create_mutations_persist_after_reload(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    home = home.reload()

    note_body = _unique("Offline activity note")
    task_name = _unique("Offline activity task")

    _warm_offline_create_widgets(home)

    user.offline = True
    expect(user.locate("[data-role='offline']")).to_be_visible()

    note_item = _create_text_note_from_home(user, home, note_body, expect_network=False)
    task_item = _create_task_from_home(home, task_name, expect_network=False)
    expect(note_item).to_have_attribute("data-offline", "true")
    expect(task_item).to_have_attribute("data-offline", "true")

    home = home.reload()

    home.activity_list
    home.task_list
    expect(_activity_item(home, note_body)).to_be_visible()
    expect(_task_item(home, task_name)).to_be_visible()


# @features offline
# @dimensions cached-overlay
# @template home/notes.html::list
# @template home/tasks.html::list
def test_offline_home_mutation_overlay_hides_deleted_items(get_user):
    user = get_user(Users.OWNER)
    note_body = _unique("Offline cached note")
    task_name = _unique("Offline cached task")
    _save_personal_task(user, task_name)

    home = user.go(SitePages.HOME)
    home = home.reload()
    home.task_list
    task_item = _task_item(home, task_name)
    expect(task_item).to_be_visible()

    _warm_offline_create_widgets(home, task=False)

    user.offline = True
    note_item = _create_text_note_from_home(
        user, home, note_body, expect_network=False
    )
    expect(note_item).to_have_attribute("data-offline", "true")
    note_item.locator("[data-action='delete-activity']").click()
    task_item.locator("input[data-role='complete']").check()
    expect(note_item).not_to_be_attached()
    expect(task_item).not_to_be_attached()

    home = home.reload()

    _loaded_activity_list(home)
    _loaded_task_list(home)
    expect(_activity_item(home, note_body)).not_to_be_attached()
    expect(_task_item(home, task_name)).not_to_be_attached()


# @features offline
# @dimensions replay queue-clear
# @template home/notes.html::note_item
def test_offline_home_mutations_replay_when_online(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    note_body = _unique("Offline replay note")

    _warm_offline_create_widgets(home, task=False)

    user.offline = True
    expect(user.locate("[data-role='offline']")).to_be_visible()
    optimistic_item = _create_text_note_from_home(
        user, home, note_body, expect_network=False
    )
    optimistic_key = optimistic_item.get_attribute("data-key")
    assert optimistic_key.startswith("offline:")

    with user.page.expect_response("**/activity/notes", timeout=15000):
        user.offline = False

    replayed_item = _activity_item(home, note_body)
    expect(replayed_item).to_be_visible()
    expect(replayed_item).not_to_have_attribute("data-offline", "true")
    replayed_key = replayed_item.get_attribute("data-key")
    assert not replayed_key.startswith("offline:")
    assert Entities.fetch_one(replayed_key, request=Fetch.direct()).body == note_body


# @features tasks
# @dimensions complete offline-queue
# @template home/tasks.html::task
def test_offline_task_complete_persists_after_reload(get_user):
    user = get_user(Users.OWNER)
    task_name = _unique("Offline complete task")
    task = _save_personal_task(user, task_name)
    expected_due_date = local_date_from_utc_datetime(
        task.entity.due_date
    ).date().isoformat()

    home = user.go(SitePages.HOME)
    home = home.reload()
    home.task_list
    task_item = _task_item(home, task_name)
    expect(task_item).to_have_attribute("data-due-date", expected_due_date)

    user.offline = True
    task_item.locator("input[data-role='complete']").check()
    expect(task_item).not_to_be_attached()

    home = home.reload()
    _loaded_task_list(home)
    expect(_task_item(home, task_name)).not_to_be_attached()
