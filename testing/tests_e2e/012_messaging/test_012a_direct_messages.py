"""End-to-end managed-user direct-message workflows."""

import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Action
from testing.definitions import Groups, Projects, SitePages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.elements.combobox import Dropdown
from testing.utility import expect_poll_result


pytestmark = pytest.mark.e2e


def _managed_definition(label):
    suffix = uuid4().hex
    return UserDefinition(
        name=f"{label} {suffix[:8]}",
        email=f"messaging-{label.lower()}-{suffix}@example.test",
        groups=[Groups.assignable_users],
    )


def _restricted_definition(label):
    suffix = uuid4().hex
    return UserDefinition(
        name=f"{label} {suffix[:8]}",
        email=f"messaging-{label.lower()}-{suffix}@example.test",
    )


def _go_messages(user):
    response = user.page.goto(
        f"{SETTINGS.test_config['BASE_URL']}/messages",
        wait_until="load",
    )
    assert response and response.status == 200
    view = user.locate("[lp-view][data-kind='messages']")
    expect(view).to_have_attribute("initialized", "")
    return view


def _send_from_modal(user, recipient, body):
    user.locate("[data-action='compose-message']").click()
    dialog = user.locate("[data-role='message-composer']")
    expect(dialog).to_be_visible()
    recipient_input = dialog.locator("input[data-permission='message']")
    textarea = dialog.locator("textarea[name='body']")
    expect(recipient_input).to_have_attribute("data-kind", "user")
    expect(textarea).to_have_attribute("data-kind", "user")
    recipient_input.fill(recipient.name)
    results = user.page.locator(
        "[role='listbox'][data-visible='true'][data-kind='user']"
    )
    option = results.locator("[role='option']").filter(
        has_text=recipient.name
    )
    expect(option).to_be_visible()
    option.click()
    expect(textarea).to_be_focused()
    textarea.fill(body)
    with user.page.expect_response(
        lambda response: (
            response.url.endswith("/l/messages")
            and response.request.method == "POST"
        )
    ) as response_info:
        dialog.get_by_role("button", name="Send", exact=True).click()
    response = response_info.value
    assert response.status == 201
    expect(dialog).to_be_hidden()
    return response.json()


def _fetch(user, path, method="GET", data=None):
    return user.page.evaluate(
        """async ({path, method, data}) => {
            const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);
            const send = async () => {
                const headers = {"X-Lagniappe-Request": "true"};
                if (mutating.has(method)) {
                    headers["X-CSRFToken"] =
                        document.getElementById("token")?.value || "";
                }
                let body;
                if (data) {
                    body = new FormData();
                    Object.entries(data).forEach(([key, value]) =>
                        body.set(key, value),
                    );
                }
                return fetch(path, {
                    method,
                    credentials: "include",
                    headers,
                    body,
                });
            };
            let response = await send();
            if (response.status === 400 && mutating.has(method)) {
                const token = await (await fetch("/l/token")).text();
                const field = document.getElementById("token");
                if (field) field.value = token;
                response = await send();
            }
            let payload = null;
            try { payload = await response.json(); } catch {}
            return {status: response.status, payload};
        }""",
        {"path": path, "method": method, "data": data},
    )


# @pairs mentions:floating-menu mentions:empty-results mentions:profile-link
# @pairs mentions:node-attributes mentions:mouse
# @pairs mentions:link-popover mentions:unlink
# @pairs mentions:recipient-search mentions:document-view
# @source src/script/elements/editor/extensions/mention.mjs::LagniappeMention
# @source src/script/elements/editor/extensions/mention.mjs::MentionSuggestions
# @source lagniappe/core/tools/collaboration.py::collaboration_user_results
# @source lagniappe/core/tools/mentions.py::deliver_mentions
def test_document_mentions_use_anchored_menu_and_profile_links(get_user):
    owner = get_user(Users.OWNER)
    recipient = get_user(Users.admin, creator=owner)
    inaccessible_recipient = get_user(
        _restricted_definition("Mention No Access"), creator=owner
    )
    project = Projects.test_sync_document_contract.get(owner)
    assert not project.entity.allowed(Action.VIEW, user=inaccessible_recipient.entity)
    owner.go(project)
    editor = project.editor
    editor.clear_text()

    popup = owner.locate("[data-role='mention-suggestions']")
    absent_query = f"absent{uuid4().hex}"
    with owner.page.expect_response(
        lambda response: (
            "/l/search-index/user?" in response.url
            and "permission=mention" in response.url
            and response.request.method == "GET"
        )
    ) as empty_response:
        editor.type_text(f"@{absent_query}")
    assert empty_response.value.status == 200
    expect(popup).to_be_visible()
    expect(popup).to_have_attribute("data-visible", "true")
    expect(popup).to_have_attribute("data-kind", "user")
    expect(popup.get_by_role("option", name="No Results")).to_be_visible()

    editor.clear_text()
    expect(popup).to_be_hidden()
    inaccessible_page_key = inaccessible_recipient.entity.page.urlsafe_key
    with owner.page.expect_response(
        lambda response: (
            "/l/search-index/user?" in response.url
            and "permission=mention" in response.url
            and response.request.method == "GET"
        )
    ) as inaccessible_response:
        editor.type_text(f"@{inaccessible_recipient.name}")
    assert inaccessible_response.value.status == 200

    inaccessible_option = popup.locator(
        f"[role='option'][data-id='{inaccessible_page_key}']"
    )
    expect(inaccessible_option).to_be_visible()
    inaccessible_option.click()
    expect(
        editor.text_entry.locator(
            "a[data-type='lagniappe-mention']"
            f"[data-profile-page='{inaccessible_page_key}']"
        )
    ).to_be_visible()
    editor.blur()

    inaccessible_recipient.go(SitePages.HOME)
    expect(
        inaccessible_recipient.locate("[data-role='notifications']")
    ).to_have_attribute(
        "aria-label",
        "Notifications: 0",
        timeout=15000,
    )

    editor.clear_text()
    expect(popup).to_be_hidden()
    page_key = recipient.entity.page.urlsafe_key
    with owner.page.expect_response(
        lambda response: (
            "/l/search-index/user?" in response.url
            and "permission=mention" in response.url
            and response.request.method == "GET"
        )
    ) as result_response:
        editor.type_text(f"@{recipient.name}")
    assert result_response.value.status == 200

    option = popup.locator(f"[role='option'][data-id='{page_key}']")
    expect(option).to_be_visible()
    expect(popup).to_have_attribute("data-visible", "true")
    owner.page.wait_for_function(
        "panel => Boolean(panel.style.left && panel.style.top)",
        arg=popup.element_handle(),
    )
    option.click()

    mention = editor.text_entry.locator(
        f"a[data-type='lagniappe-mention'][data-profile-page='{page_key}']"
    )
    expect(mention).to_have_text(f"@{recipient.name}")
    expect(mention).to_have_attribute("href", f"/pages/{page_key}")
    expect(mention).to_have_attribute(
        "data-recipient", recipient.entity.urlsafe_key
    )
    expect(mention).to_have_class(re.compile(r"(?:^|\s)bg-user-bg(?:\s|$)"))
    expect(popup).to_be_hidden()
    expect(popup).to_have_attribute("data-visible", "false")

    document_url = owner.page.url
    mention.click()
    expect(owner.page).to_have_url(document_url)
    link_popover = owner.locate(
        "[data-role='editor-link-popover'][data-link-type='mention']"
    )
    expect(link_popover).to_be_visible()
    expect(link_popover.get_by_role("button", name="Open", exact=True)).to_be_visible()
    expect(link_popover.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    remove = link_popover.get_by_role("button", name="Remove", exact=True)
    expect(remove).to_be_visible()
    remove.click()
    expect(editor.text_entry.locator("a[data-type='lagniappe-mention']")).to_have_count(0)
    expect(editor.text_entry).to_contain_text(f"@{recipient.name}")


# @pairs messaging:compose-modal messaging:conversation-page messaging:history-page
# @pairs messaging:read-race messaging:unread-count messaging:per-copy-delete
# @pairs messaging:clear-horizon messaging:new-after-clear messaging:permission
# @pairs messaging:polling-revision messaging:active-polling
# @pairs notifications:aggregate-count notifications:exact-count
# @source lagniappe/core/tools/messages.py::send_message
# @source lagniappe/core/tools/messages.py::conversations
# @source lagniappe/core/tools/messages.py::conversation_history
# @source lagniappe/core/tools/messages.py::mark_read
# @source lagniappe/core/tools/messages.py::hide_message
# @source lagniappe/core/tools/messages.py::clear_conversation
# @source lagniappe/core/tools/collaboration.py::recipient_allowed
# @source src/script/elements/messageComposer.mjs::MessageComposer
# @source src/script/elements/notifications.mjs::Notifications
# @source src/script/views/messages.mjs::Messages
def test_direct_message_lifecycle_is_private_and_restores_after_clear(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    sender = get_user(_managed_definition("Sender"), creator=owner)
    recipient = get_user(_managed_definition("Recipient"), creator=owner)

    recipient.go(SitePages.HOME)
    recipient.locate("button[lp-show='directory:DirectoryList']").click()
    expect(recipient.page.get_by_role("link", name="Messages", exact=True)).to_be_visible()
    notifications = recipient.locate("[data-role='notifications']")
    notification_count = recipient.locate("[data-role='notification-count']")
    expect(notification_count).not_to_have_text("...", timeout=15000)
    starting_count = int(notification_count.text_content())
    notifications.click()
    initial_menu = recipient.page.locator("[role='listbox'][data-visible='true']")
    message_user = initial_menu.locator("[data-action='message-user']")
    expect(message_user).to_be_visible()
    expect(initial_menu.locator("[role='option']")).to_have_count(1)
    expect(message_user).not_to_have_class(re.compile(r"(?:^|\s)border-b(?:\s|$)"))
    message_user.click()
    composer = recipient.locate("[data-role='message-composer']")
    expect(composer).to_be_visible()
    close_button = composer.get_by_role("button", name="Close", exact=True)
    expect(close_button).to_be_visible()
    close_button.click()
    expect(composer).to_be_hidden()

    _go_messages(sender)
    first_body = f"First durable message {uuid4().hex}"
    sent = _send_from_modal(sender, recipient, first_body)
    conversation_id = sent["conversation"]["id"]
    message_id = sent["message"]["id"]
    expect(sender.locate("[data-role='message-history']")).to_contain_text(
        first_body
    )

    recipient.go(SitePages.HOME)
    expect(notifications).to_have_attribute(
        "aria-label", f"Notifications: {starting_count + 1}", timeout=15000
    )
    notifications.click()
    menu = recipient.page.locator("[role='listbox'][data-visible='true']")
    aggregate = menu.locator("[role='option']").filter(
        has_text="1 new message"
    )
    expect(aggregate).to_be_visible()
    with recipient.page.expect_navigation():
        aggregate.locator("a[href='/messages']").click()

    recipient_view = recipient.locate("[lp-view][data-kind='messages']")
    expect(recipient_view).to_have_attribute("initialized", "")
    history = recipient.locate("[data-role='message-history']")
    expect(history).to_contain_text(first_body)
    expect(recipient.locate("[data-role='notifications']")).to_have_attribute(
        "aria-label", f"Notifications: {starting_count}", timeout=15000
    )

    poll_subscription = "view:channel:messages"
    with expect_poll_result(
        recipient.page,
        subscription_id=poll_subscription,
        status="changed",
    ):
        recipient.page.evaluate(
            """subscription =>
                document.querySelector("[lp-view]")._lp_view
                    .PollingCoordinator.trigger(subscription)
            """,
            poll_subscription,
        )

    live_body = f"Live message {uuid4().hex}"
    _send_from_modal(sender, recipient, live_body)
    with expect_poll_result(
        recipient.page,
        subscription_id=poll_subscription,
        status="changed",
    ):
        recipient.page.evaluate(
            """subscription =>
                document.querySelector("[lp-view]")._lp_view
                    .PollingCoordinator.trigger(subscription)
            """,
            poll_subscription,
        )
    expect(history).to_contain_text(live_body)

    message = history.locator(f"[data-message='{message_id}']")
    with recipient.page.expect_response(
        lambda response: (
            response.url.endswith(f"/l/messages/{message_id}")
            and response.request.method == "DELETE"
        )
    ):
        message.locator("[data-action='delete-message']").click(force=True)
    expect(message).not_to_be_attached()

    _go_messages(sender)
    expect(sender.locate("[data-role='message-history']")).to_contain_text(
        first_body
    )

    recipient.page.goto(
        f"{SETTINGS.test_config['BASE_URL']}/messages?with={conversation_id}",
        wait_until="load",
    )
    expect(recipient.locate("[lp-view][data-kind='messages']")).to_have_attribute(
        "initialized", ""
    )
    conversation_row = recipient.locate(
        f"[data-role='conversation-list'] [data-conversation-row='{conversation_id}']"
    )
    clear_control = conversation_row.get_by_role(
        "button", name=f"Clear conversation with {sender.name}"
    )
    expect(clear_control).to_be_visible()
    expect(
        recipient.locate("[data-role='message-header']").get_by_role(
            "button", name="Clear conversation"
        )
    ).to_have_count(0)
    clear_control.click()
    delete_modal = recipient.locate("#modal")
    expect(delete_modal).to_be_visible()
    expect(
        delete_modal.get_by_role("heading", name="Clear Conversation")
    ).to_be_visible()
    expect(delete_modal).to_contain_text(
        f"clear your conversation with {sender.name} from your message history"
    )
    clear_button = delete_modal.locator("[data-role='delete']")
    expect(clear_button.locator("#spinner[data-role='icon']")).to_have_count(1)
    with recipient.page.expect_response(
        lambda response: (
            response.url.endswith(f"/l/messages/conversations/{conversation_id}")
            and response.request.method == "DELETE"
        )
    ):
        clear_button.click()
    expect(delete_modal).not_to_be_attached()
    expect(
        recipient.locate("[data-role='conversation-list'] [data-conversation-row]")
    ).to_have_count(0)

    second_body = f"Message after clear {uuid4().hex}"
    _send_from_modal(sender, recipient, second_body)
    _go_messages(recipient)
    expect(recipient.locate("[data-role='message-history']")).to_contain_text(
        second_body
    )
    expect(recipient.locate("[data-role='message-history']")).not_to_contain_text(
        first_body
    )

    owner.go(SitePages.HOME)
    denied_path = f"/l/messages/conversations/{conversation_id}"
    with browser_failures.expect_http_error(
        owner, status=404, path=denied_path
    ):
        denied = _fetch(owner, denied_path)
    assert denied["status"] == 404


# @pairs messaging:responsive-peer-selector messaging:inline-reply
# @pairs messaging:selection-race messaging:preserve-selection
# @pair messaging:unread-peer
# @source src/script/views/messages.mjs::Messages
def test_messages_page_uses_mobile_peer_selector_with_inline_reply(get_user):
    owner = get_user(Users.OWNER)
    user = get_user(_managed_definition("Mobile"), creator=owner, has_touch=True)
    peer = get_user(_managed_definition("Mobile Peer"), creator=owner)
    other_peer = get_user(_managed_definition("Other Mobile Peer"), creator=owner)

    user.mobile = True
    empty_view = _go_messages(user)
    expect(empty_view.locator("[data-role='conversation-selector']")).to_be_hidden()
    expect(empty_view.locator("[data-action='compose-message']")).to_be_visible()

    peer_body = f"Mobile selector {uuid4().hex}"
    _send_from_modal(user, peer, peer_body)
    view = empty_view

    expect(view.locator("[data-role='message-history']")).to_contain_text(peer_body)

    selector = view.locator("[data-role='conversation-selector']")
    expect(selector).to_be_visible()
    expect(selector).to_have_attribute("role", "combobox")
    expect(selector).to_have_attribute("aria-expanded", "false")
    expect(selector).to_contain_text(peer.name)
    expect(view.locator("select[data-role='conversation-selector']")).to_have_count(0)

    other_body = f"Other mobile selector {uuid4().hex}"
    _send_from_modal(user, other_peer, other_body)
    expect(selector).to_contain_text(peer.name)
    expect(view.locator("[data-role='message-history']")).to_contain_text(peer_body)
    expect(view.locator("[data-role='message-history']")).not_to_contain_text(
        other_body
    )

    Dropdown(selector).select_by_name(other_peer.name)
    expect(view.locator("[data-role='message-history']")).to_contain_text(other_body)
    expect(selector).to_contain_text(other_peer.name)
    Dropdown(selector).select_by_name(peer.name)
    expect(view.locator("[data-role='message-history']")).to_contain_text(
        peer_body,
        timeout=15000,
    )
    expect(selector).to_contain_text(peer.name)

    _go_messages(other_peer)
    incoming_other = f"Incoming other peer {uuid4().hex}"
    _send_from_modal(other_peer, user, incoming_other)
    expect(selector).to_contain_text(peer.name)
    expect(view.locator("[data-role='message-history']")).to_contain_text(peer_body)
    expect(view.locator("[data-role='message-history']")).not_to_contain_text(
        incoming_other
    )
    selector_dropdown = Dropdown(selector)
    selector_panel = selector_dropdown.open()
    other_option = selector_panel.get_by_role("option").filter(has_text=other_peer.name)
    expect(other_option).to_contain_text("1 unread", timeout=15000)
    selector.press("Escape")
    expect(selector_panel).to_be_hidden()

    view = _go_messages(user)
    selector = view.locator("[data-role='conversation-selector']")
    expect(selector).to_contain_text(peer.name)
    expect(view.locator("[data-role='conversation-list']")).to_be_hidden()
    expect(view.locator("[data-role='message-header']")).to_be_hidden()
    expect(view.locator("[data-role='message-reply']")).to_have_count(1)
    expect(view.locator("[data-role='message-reply']")).to_be_visible()

    clear_control = view.get_by_role(
        "button", name=f"Clear conversation with {peer.name}"
    )
    expect(clear_control).to_be_visible()
    clear_control.click()
    delete_modal = user.locate("#modal")
    expect(delete_modal).to_be_visible()
    expect(
        delete_modal.get_by_role("heading", name="Clear Conversation")
    ).to_be_visible()
    expect(delete_modal).to_contain_text(
        f"clear your conversation with {peer.name} from your message history"
    )
    delete_modal.get_by_role("button", name="Cancel").click()
    expect(delete_modal).not_to_be_attached()


# @pairs messaging:compose-eligibility messaging:reply-permission
# @pairs messaging:inline-reply notifications:menu-open
# @source lagniappe/core/tools/collaboration.py::can_initiate_messages
# @source lagniappe/core/tools/messages.py::send_message
# @source src/script/views/messages.mjs::Messages
def test_inbound_message_allows_reply_without_compose_permission(get_user):
    owner = get_user(Users.OWNER)
    recipient = get_user(_restricted_definition("Reply Only"), creator=owner)

    _go_messages(owner)
    incoming = f"Inbound message {uuid4().hex}"
    _send_from_modal(owner, recipient, incoming)

    recipient.go(SitePages.HOME)
    notifications = recipient.locate("[data-role='notifications']")
    notifications.click()
    menu = recipient.page.locator("[role='listbox'][data-visible='true']")
    expect(menu.locator("[data-action='message-user']")).to_have_count(0)
    aggregate = menu.locator("[role='option']").filter(has_text="1 new message")
    expect(aggregate).to_be_visible()
    with recipient.page.expect_navigation():
        aggregate.locator("a[href='/messages']").click()

    view = recipient.locate("[lp-view][data-kind='messages']")
    expect(view).to_have_attribute("initialized", "")
    expect(view.locator("[data-action='compose-message']")).to_have_count(0)
    expect(view).not_to_contain_text("Messaging unavailable")
    reply = view.locator("[data-role='message-reply']")
    expect(reply).to_be_visible()
    expect(reply).not_to_contain_text("Reply to")
    textarea = reply.get_by_label("Reply", exact=True)
    expect(textarea).to_have_attribute("data-kind", "user")
    response_body = f"Reply message {uuid4().hex}"
    textarea.fill(response_body)
    with recipient.page.expect_response(
        lambda response: (
            response.url.endswith("/l/messages")
            and response.request.method == "POST"
        )
    ) as response_info:
        reply.get_by_role("button", name="Reply", exact=True).click()
    assert response_info.value.status == 201
    expect(view.locator("[data-role='message-history']")).to_contain_text(
        response_body
    )

    _go_messages(owner)
    expect(owner.locate("[data-role='message-history']")).to_contain_text(
        response_body
    )
