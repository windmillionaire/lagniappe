import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    AI,
    Action,
    Fetch,
)
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Groups, SitePages, Submissions, Users
from testing.definitions.user_definitions import UserDefinition
from testing.resources import Page
from testing.elements import (
    Buttons,
    FormElements,
    Modal,
    Select,
    SpinnerButtons,
    Tabs,
)
from testing.utility.network import browser_fetch
from testing.utility.user_settings import (
    go_to_my_page,
    open_user_settings,
    user_settings_field_order,
)

pytestmark = pytest.mark.e2e


def _assert_single_user_settings_field_set(settings_panel):
    expect(settings_panel.locator(FormElements.NAME)).to_have_count(1)
    expect(settings_panel.locator(FormElements.EMAIL)).to_have_count(1)


def _assert_sign_out_button_in_user_header(settings_panel):
    user_header = settings_panel.locator("[data-role='user-card'] > header")
    user_actions = user_header.locator("[data-role='user-actions']")
    sign_out_button = user_actions.locator("button[data-action='logout']")
    expect(sign_out_button).to_be_visible()
    expect(sign_out_button).to_have_attribute(
        "data-route", re.compile(r"/users/logout$")
    )
    expect(sign_out_button).to_contain_text("Sign out")
    user_fields_actions = settings_panel.locator(
        "[data-role='user-fields'] [data-role='user-actions']"
    )
    expect(user_fields_actions).to_have_count(0)


def _tabs_controls(user):
    return user.locate("#tabs [data-role='controls']")


def _create_user_page_reassign_target(owner, name):
    category = Categories.test_create_page.get(owner)
    page = Entities.PAGE.create(
        {
            "name": name,
            "model": category.entity,
        }
    )
    page.save()
    return page


def _select_page_option(select, page):
    panel = select.open()
    select.input.fill(page.name)
    expect(panel).to_be_visible()
    option = panel.locator(f"[role='option'][data-id='{page.urlsafe_key}']")
    expect(option).to_be_visible()
    option.click()


def _submit_user_settings_and_wait_for_reload(user, settings_panel):
    with user.page.expect_response("**/pages/*/update") as response_info:
        SpinnerButtons.UPDATE.click(settings_panel)
    assert response_info.value.ok
    user.page.wait_for_load_state("load")
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")


def _submission_payload(submission):
    return {field.id: field.submission_value for field in submission}


def _session_page_key(user):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=CONFIG.SECRET_KEY)
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie = next(
        cookie for cookie in user.page.context.cookies() if cookie["name"] == "session"
    )
    return serializer.loads(cookie["value"])[CONFIG.LOGIN_USER_PAGE_KEY]


# @matrix notification-email : default-daily user-setting
# @matrix user-settings : field-order group-selector-hidden personal-page readonly-email sign-out
# @template pages/info.html::user_settings
def test_user_settings_panel_opens_from_my_page(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    user = get_user(Users.create_user, creator=owner)
    user.go(SitePages.HOME)

    go_to_my_page(user)
    expect(user.page).to_have_title(re.compile(user.name))

    user_page = Page(user=user, definition=user.definition)
    info_tab = Tabs(user).info
    expect(info_tab).to_be_visible()

    settings_panel = open_user_settings(user, user_page)
    expect(info_tab.locator(user_page.INFO_FORM)).to_have_count(1)
    expect(settings_panel).to_have_attribute("data-title", "User Info")
    expect(
        settings_panel.locator("[data-role='user-card'] > header").first
    ).to_contain_text("Settings")

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).to_have_attribute("readonly", "")

    expect(settings_panel.locator("[data-role='user-groups']")).to_have_count(0)
    expect(settings_panel.locator("input[name='ai_access']")).to_have_count(0)
    notification_options = settings_panel.locator(
        "input[name='notification_email_mode']"
    )
    expect(notification_options).to_have_count(3)
    expect(
        settings_panel.locator("input[name='notification_email_mode'][value='DAILY']")
    ).to_be_checked()
    expect(
        settings_panel.locator("fieldset[data-role='notification-email']")
    ).to_be_visible()
    assert user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "notification-email",
        "api-key-settings",
    ]

    settings_panel.locator(
        "input[name='notification_email_mode'][value='IMMEDIATE']"
    ).check()
    with user.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)
    assert Entities.USER.load(user.email).notification_email_mode == "IMMEDIATE"

    update_path = f"/pages/{user.entity.page.urlsafe_key}/update"
    with browser_failures.expect_http_error(user, status=403, path=update_path):
        forged = browser_fetch(
            user,
            update_path,
            method="PUT",
            data={
                "role": "user-settings",
                "name": user.name,
                "ai_access": "CREATE",
            },
        )
    assert forged["status"] == 403
    assert Entities.USER.load(user.email).ai_access == "NONE"

    _assert_sign_out_button_in_user_header(settings_panel)

    controls = _tabs_controls(user)
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_have_attribute(
        "lp-close", "info:PageInfo"
    )


# @matrix agent-api : copy-control
# @matrix user-settings : field-order group-selector-hidden owner-own-page readonly-email sign-out
# @pair notification-email:default-daily
# @template pages/info.html::user_settings
def test_owner_settings_hides_group_selector_on_own_page(get_user):
    owner = get_user(Users.OWNER)
    owner.go(SitePages.HOME)

    go_to_my_page(owner)
    expect(owner.page).to_have_title(re.compile(owner.name))

    owner_page = Page(user=owner, definition=owner.definition)
    info_tab = Tabs(owner).info
    expect(info_tab).to_be_visible()

    settings_panel = open_user_settings(owner, owner_page)
    expect(info_tab.locator(owner_page.INFO_FORM)).to_have_count(1)

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).to_have_attribute("readonly", "")

    expect(settings_panel.locator("[data-role='user-groups']")).to_have_count(0)
    expect(settings_panel).to_have_attribute("data-can-edit-ai", "true")
    expect(settings_panel.locator("input[name='ai_access']")).to_have_count(3)
    expect(
        settings_panel.locator("input[name='notification_email_mode']")
    ).to_have_count(3)
    expect(
        settings_panel.locator("input[name='notification_email_mode'][value='DAILY']")
    ).to_be_checked()
    api_key_settings = settings_panel.locator("[data-role='api-key-settings']")
    expect(api_key_settings).to_be_visible()
    expect(api_key_settings.locator("[data-role='api-key-status']")).to_have_text(
        "No active API key."
    )
    expect(
        api_key_settings.locator("[data-role='manual-command-shell']")
    ).to_have_count(1)
    expect(
        api_key_settings.locator("[data-role='manual-command-copy']")
    ).to_have_attribute("aria-label", "Copy API key")
    api_key_actions = api_key_settings.locator("[data-role='api-key-actions']")
    expect(api_key_actions).to_have_class(re.compile(r"\bflex-col\b"))
    expect(api_key_actions).to_have_class(re.compile(r"\bsm:flex-row\b"))
    issue_button = api_key_actions.locator("[data-action='issue-api-key']")
    revoke_button = api_key_actions.locator("[data-action='revoke-api-key']")
    expect(issue_button).to_have_class(re.compile(r"\baction-button\b"))
    expect(revoke_button).to_have_class(re.compile(r"\baction-button\b"))
    expect(revoke_button).to_have_attribute("data-kind", "delete")
    assert user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "ai-access",
        "notification-email",
        "api-key-settings",
        "owner-inbound",
    ]

    _assert_sign_out_button_in_user_header(settings_panel)
    controls = _tabs_controls(owner)
    expect(controls.locator("button[lp-help='user_settings']")).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()


# @matrix agent-api user-settings : confirmation-modal entitlement-independent revoke rotate shown-once
# @template pages/info.html::user_settings
def test_user_without_provider_access_can_manage_external_agent_api_key(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    user = get_user(
        UserDefinition(
            name=f"External Agent None {suffix}",
            email=f"external-agent-none-{suffix}@example.test",
            ai_access=AI.NONE,
        ),
        creator=owner,
    )
    assert user.entity.ai_access == AI.NONE.name
    user.go(SitePages.HOME)

    go_to_my_page(user)
    user_page = Page(user=user, definition=user.definition)
    settings_panel = open_user_settings(user, user_page)

    expect(settings_panel).to_have_attribute(
        "data-api-key-route",
        re.compile(r"/users/me/api-key$"),
    )
    api_key_settings = settings_panel.locator("[data-role='api-key-settings']")
    expect(api_key_settings).to_be_visible()
    expect(api_key_settings.locator("[data-role='api-key-status']")).not_to_have_text(
        "Loading API key status..."
    )

    issue = api_key_settings.locator("[data-action='issue-api-key']")
    revoke = api_key_settings.locator("[data-action='revoke-api-key']")
    secret = api_key_settings.locator("[data-role='api-key-secret']")
    value = api_key_settings.locator("[data-role='api-key-value']")

    with user.page.expect_response("**/users/me/api-key") as issued_response:
        issue.click()
    assert issued_response.value.ok
    expect(issue).to_have_text("Regenerate API key")
    expect(secret).to_be_visible()
    expect(value).not_to_be_empty()
    first_token = value.text_content()

    modal = Modal(user.page).open(issue)
    expect(
        modal.element.get_by_role("heading", name="Regenerate API key")
    ).to_be_visible()
    expect(modal.element).to_contain_text("The current key will stop working immediately.")
    modal.click("Cancel")
    expect(issue).to_have_text("Regenerate API key")

    modal.open(issue)
    with user.page.expect_response("**/users/me/api-key") as rotated_response:
        modal.click("Regenerate API key")
    assert rotated_response.value.ok
    expect(value).not_to_have_text(first_token)

    modal.open(revoke)
    expect(modal.element.get_by_role("heading", name="Revoke API key")).to_be_visible()
    expect(modal.element).to_contain_text("This key will stop working immediately.")
    modal.click("Cancel")
    expect(revoke).to_be_visible()

    modal.open(revoke)
    with user.page.expect_response("**/users/me/api-key") as revoked_response:
        modal.click("Revoke API key")
    assert revoked_response.value.ok
    expect(api_key_settings.locator("[data-role='api-key-status']")).to_have_text(
        "No active API key."
    )
    expect(revoke).to_be_hidden()


# @matrix ai : access-gate batch-summary provider-boundary
def test_page_editor_without_ai_create_is_rejected_before_batch_summary(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    user = get_user(Users.create_user, creator=owner)
    page = user.entity.page
    assert page.allowed(Action.EDIT, user=user.entity)
    assert not user.entity.access(AI.CREATE)
    user.go(SitePages.HOME)
    path = f"/files/{page.urlsafe_key}/upload"

    with browser_failures.expect_http_error(user, status=403, path=path):
        result = user.page.evaluate(
            """async (path) => {
                const body = new FormData();
                body.append("summarize", "on");
                body.append("file-upload", new File(["one"], "one.txt"));
                body.append("file-upload", new File(["two"], "two.txt"));
                const response = await fetch(path, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "X-CSRFToken": document.getElementById("token")?.value,
                        "X-Lagniappe-Request": "true",
                    },
                    body,
                });
                return response.status;
            }""",
            path,
        )

    assert result == 403


# @matrix user-settings : ai-access edit-groups editable-email field-order group-selector owner-other-page
# @pairs cache:invalidation-acknowledgement notification-email:user-only
# @template pages/info.html::user_settings
def test_owner_can_edit_user_settings_on_other_user_page(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    created_user = get_user(
        UserDefinition(
            name=f"User Settings AI Access {suffix}",
            email=f"user-settings-ai-access-{suffix}@example.test",
            ai_access=AI.NONE,
        ),
        creator=owner,
    )
    created_user_page_key = created_user.entity.page.urlsafe_key

    owner.go(SitePages.USER_INDEX)
    target_row = owner.locate(f"#table tr[data-key='{created_user.key}']")
    expect(target_row).to_be_visible()
    with owner.page.expect_navigation():
        target_row.get_by_role("link", name=created_user.name, exact=True).click()
    expect(owner.page).to_have_title(re.compile(created_user.name))
    assert created_user_page_key in owner.page.url

    created_user_page = Page(user=owner, definition=created_user.definition)
    info_tab = Tabs(owner).info
    expect(info_tab).to_be_visible()

    settings_panel = open_user_settings(owner, created_user_page)
    _assert_single_user_settings_field_set(settings_panel)
    expect(info_tab.locator(created_user_page.INFO_FORM)).to_have_count(1)

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).not_to_have_attribute("readonly", re.compile(".+"))

    expect(settings_panel).to_have_attribute("data-can-edit-groups", "true")
    expect(settings_panel.locator("[data-role='user-groups']")).to_be_visible()
    expect(settings_panel).to_have_attribute("data-can-edit-ai", "true")
    ai_options = settings_panel.locator("input[name='ai_access']")
    expect(ai_options).to_have_count(3)
    expect(
        settings_panel.locator("input[name='ai_access'][value='NONE']")
    ).to_be_checked()
    expect(
        settings_panel.locator("input[name='notification_email_mode']")
    ).to_have_count(0)
    user_page_group = settings_panel.locator("fieldset[data-role='user-page']")
    expect(user_page_group).to_be_visible()
    expect(user_page_group.locator("legend")).to_have_text("User Page")
    assert user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "user-groups",
        "ai-access",
        "user-page",
    ]

    expect(settings_panel.locator("button[data-action='logout']")).to_have_count(0)

    controls = _tabs_controls(owner)
    expect(controls.locator("button[lp-help='user_settings']")).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()
    expect(settings_panel.locator("[data-role='restrict-access']")).to_be_visible()
    expect(settings_panel.locator("[data-role='visible-to']")).to_be_visible()

    restrictions_help = controls.locator(Buttons.LP_HELP)
    restrictions_close = controls.locator(Buttons.LP_CLOSE)
    expect(restrictions_help).to_be_visible()
    expect(restrictions_help).to_have_attribute("lp-help", "user_settings")
    expect(restrictions_close).to_be_visible()
    expect(restrictions_close).to_have_attribute("lp-close", "info:PageInfo")
    help_modal = Modal(owner.page).open(restrictions_help)
    expect(help_modal.element).to_contain_text("User Settings")
    help_modal.close()

    settings_panel.locator("input[name='ai_access'][value='ASK']").check()
    with owner.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)
    saved_user = Entities.USER.load(created_user.email)
    assert saved_user.ai_access == "ASK"
    assert saved_user.invalidate_cache is True

    restrictions_close.click()
    expect(settings_panel).not_to_be_visible()
    expect(info_tab.locator(created_user_page.INFO_FORM)).to_be_visible()

    with created_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        created_user.navigate(SitePages.HOME.get(created_user).url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(created_user.email).invalidate_cache is False
    expect(created_user.page).to_have_title("Home")


# @matrix user-settings : group-selector preload relation-loading
# @template pages/info.html::user_settings
def test_user_settings_preloads_existing_groups(get_user):
    owner = get_user(Users.OWNER)
    created_user = get_user(Users.user_settings_group_preload, creator=owner)
    first_group = Groups.general_users_view_only.get(owner)
    second_group = Groups.test_user_one_category.get(owner)

    user_page = Page(user=owner, definition=created_user.definition)
    user_page.entity = created_user.entity.page
    owner.go(user_page)

    settings_panel = open_user_settings(owner, user_page)
    groups = settings_panel.locator("[data-role='user-groups']")
    group_select = Select(groups)
    expected_group_ids = {
        first_group.entity.urlsafe_key,
        second_group.entity.urlsafe_key,
    }

    preload_element = groups.locator("[lp-select]")
    expect(preload_element).to_have_attribute("data-preload", re.compile(r"\S+"))
    preload_attribute = preload_element.get_attribute("data-preload")
    preload = json.loads(preload_attribute)
    assert {group["id"] for group in preload} == expected_group_ids
    selected_options = groups.locator("select[name='group'] option:checked")
    expect(selected_options).to_have_count(len(expected_group_ids))
    for group_id in expected_group_ids:
        expect(
            groups.locator(f"select[name='group'] option[value='{group_id}']:checked")
        ).to_have_count(1)
    for group_name in (
        first_group.definition.name,
        second_group.definition.name,
    ):
        expect(group_select.input).to_have_attribute(
            "placeholder", re.compile(re.escape(group_name))
        )


# @matrix user-settings : owner-other-page page-reassign page-remove
# @pairs auth:canonical-page cache:invalidation-acknowledgement
# @template pages/info.html::user_settings
def test_owner_can_reassign_and_remove_user_from_page(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    created_user = get_user(
        UserDefinition(
            name=f"User Page Reassignment {suffix}",
            email=f"user-page-reassignment-{suffix}@example.test",
        ),
        creator=owner,
    )
    source_page_key = created_user.entity.page.key
    target_page_entity = _create_user_page_reassign_target(
        owner,
        f"User Reassign Target {suffix}",
    )
    target_page_key = target_page_entity.key

    source_page = Page(
        user=owner,
        definition=SimpleNamespace(name=created_user.entity.page.name),
    )
    source_page.entity = created_user.entity.page
    owner.go(source_page)

    settings_panel = open_user_settings(owner, source_page)
    expect(settings_panel.locator("[data-role='remove-page']")).to_be_visible()
    page_select = Select(settings_panel.locator("[data-role='page-select']"))
    _select_page_option(page_select, target_page_entity)
    _submit_user_settings_and_wait_for_reload(owner, settings_panel)

    saved_user = Entities.USER.load(created_user.email)
    saved_source_page = Entities.fetch_one(source_page_key, request=Fetch.direct())
    saved_target_page = Entities.fetch_one(target_page_key, request=Fetch.direct())
    assert saved_source_page.user is None
    assert saved_user.page.key == target_page_key
    assert saved_target_page.user.email == created_user.email

    target_page = Page(
        user=owner,
        definition=SimpleNamespace(name=saved_target_page.name),
    )
    target_page.entity = saved_target_page
    owner.go(target_page)

    settings_panel = open_user_settings(owner, target_page)
    settings_panel.locator("input[name='remove-user']").check()
    _submit_user_settings_and_wait_for_reload(owner, settings_panel)

    saved_user = Entities.USER.load(created_user.email)
    replacement_page = saved_user.page
    saved_target_page = Entities.fetch_one(target_page_key, request=Fetch.direct())
    assert saved_target_page.user is None
    assert replacement_page.key not in {source_page_key, target_page_key}
    assert replacement_page.user.email == created_user.email
    assert saved_user.invalidate_cache is True

    with created_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        created_user.navigate(SitePages.HOME.get(created_user).url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(created_user.email).invalidate_cache is False
    expect(created_user.page).to_have_title("Home")
    assert _session_page_key(created_user) == replacement_page.urlsafe_key


# @matrix user-settings : attached-form categories restrictions submit-boundary
# @pair cache:invalidation-acknowledgement
def test_user_settings_submit_preserves_attached_form_and_categories(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.test_basic_inputs_submission.get(owner)
    form = category.definition.form.get(owner)
    restriction_group = Groups.test_user_one_category.get(owner)
    membership_group = Groups.general_users_view_only.get(owner)
    initial_submission = Submissions.basic_inputs.get()
    suffix = uuid4().hex

    page_entity = Entities.PAGE.create(
        {
            "name": f"Attached User Settings Page {suffix}",
            "model": category.entity,
            "form": form.entity,
            "submission": _submission_payload(initial_submission),
        }
    )
    page_entity.groups = [restriction_group.entity]
    page_entity.save()

    attached_user = Entities.USER.create(
        {
            "name": f"Attached Settings User {suffix}",
            "email": f"attached-settings-user-{suffix}@example.test",
            "page": page_entity,
            "test_user": True,
        }
    )
    attached_user.save()

    user_page = Page(
        user=owner,
        definition=SimpleNamespace(name=page_entity.name),
    )
    user_page.entity = page_entity
    owner.go(user_page)

    info_form = user_page.info_form
    expect(info_form).to_be_visible()
    assert user_page.verify_submission(initial_submission)

    category_keys = {c.key for c in page_entity.categories}
    form_key = page_entity.form.key
    restriction_keys = {g.key for g in page_entity.groups}

    settings_panel = open_user_settings(owner, user_page)
    updated_name = f"Updated Settings User {suffix}"
    updated_email = f"updated-settings-user-{suffix}@example.test"
    settings_panel.locator("input[name='name']").fill(updated_name)
    settings_panel.locator("input[name='email']").fill(updated_email)
    Select(settings_panel.locator("[data-role='user-groups']")).select_by_name(
        membership_group.definition.name
    )

    with owner.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)

    saved_page = Entities.fetch_one(user_page.key, request=Fetch.direct())
    saved_user = Entities.fetch_one(saved_page.user, request=Fetch.direct())
    assert saved_user.name == updated_name
    assert saved_user.email == updated_email
    assert {g.key for g in saved_user.groups} == {membership_group.entity.key}
    assert saved_user.invalidate_cache is True
    assert saved_page.form.key == form_key
    assert {c.key for c in saved_page.categories} == category_keys
    assert {g.key for g in saved_page.groups} == restriction_keys

    affected_user = get_user(Users.ANONYMOUS)
    login_page = affected_user.go(SitePages.LOGIN_PAGE)
    login_url = login_page.login_url(updated_email)
    with affected_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        affected_user.page.goto(login_url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(updated_email).invalidate_cache is False
    expect(affected_user.page).to_have_title("Home")

    user_page.reload()
    info_form = user_page.info_form
    expect(info_form).to_be_visible()
    assert user_page.verify_submission(initial_submission)
    categories = info_form.locator("[data-role='categories']")
    expect(categories).to_be_visible()
    expect(Select(categories).input).to_have_attribute(
        "placeholder", re.compile(re.escape(category.definition.name))
    )
    expect(info_form.locator("[data-role='form-select']")).to_contain_text(
        form.definition.name
    )

    settings_panel = open_user_settings(owner, user_page)
    expect(settings_panel.locator("input[name='name']")).to_have_value(updated_name)
    expect(settings_panel.locator("input[name='email']")).to_have_value(updated_email)
    settings_groups = settings_panel.locator("[data-role='user-groups']")
    expect(
        settings_groups.locator(
            "select[name='group'] "
            f"option[value='{membership_group.entity.urlsafe_key}']:checked"
        )
    ).to_have_count(1)
    expect(Select(settings_groups).input).to_have_attribute(
        "placeholder", re.compile(re.escape(membership_group.definition.name))
    )
    expect(
        settings_panel.locator(Page.PAGE_RESTRICTED_GROUP_LIST).filter(
            has_text=restriction_group.definition.name
        )
    ).to_be_visible()

    _tabs_controls(owner).locator(Buttons.LP_CLOSE).click()
    expect(settings_panel).not_to_be_visible()
    assert user_page.verify_submission(initial_submission)

    updated_submission = Submissions.basic_inputs.get()
    updated_submission[0].submission_value = f"PageInfo still saves {suffix}"
    user_page.set_submission(updated_submission)
    user_page.submit_and_verify_submission(updated_submission)
