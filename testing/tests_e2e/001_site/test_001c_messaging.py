from types import SimpleNamespace
from uuid import uuid4

from playwright.sync_api import expect

from lagniappe.core.definitions import Levels, Site
from lagniappe.core.entities import Entities
from testing.definitions import Forms, SitePages, Users
from testing.elements import Modal
from testing.resources import SitePage


def _force_production_messaging_mode(page):
    page.add_init_script(
        """
        Object.defineProperty(window, "__TESTING__", {
            configurable: true,
            get: () => false,
            set: () => {},
        });
        """
    )


def _force_default_notification_permission(page):
    page.add_init_script(
        """
        if (window.Notification) {
            try {
                Object.defineProperty(window.Notification, "permission", {
                    configurable: true,
                    get: () => "default",
                });
            } catch {}
            window.Notification.requestPermission = () => new Promise(() => {});
        }
        """
    )


def _assert_messaging_disabled(user):
    expect(user.locate("meta[name='messaging-disabled']")).to_have_attribute(
        "content",
        "true",
    )
    assert user.page.evaluate(
        """() => document.querySelector("[lp-view]")?._lp_view?.messagingDisabled === true"""
    )
    assert user.page.evaluate(
        """() => {
            const manager = document.querySelector("[lp-view]")?._lp_view?.SyncManager;
            return Boolean(manager) && manager.token === null && manager._registered === false;
        }"""
    )


# @features browser-protocol
# @dimensions single-recipient multicast producer version
def test_browser_message_producers_add_protocol_version(monkeypatch):
    from lagniappe.web import responses

    messages = []
    multicasts = []
    monkeypatch.setattr(responses.messaging, "send", messages.append)
    monkeypatch.setattr(
        responses.messaging,
        "send_each_for_multicast",
        multicasts.append,
    )

    responses.send_message(
        {"type": "notification", "html": "<li>Ready</li>"},
        "browser-token",
    )
    responses.send_multicast_message(
        "server-change",
        {"type": "delete", "key": "entity-key"},
        ["viewer-token"],
    )

    assert messages[0].data["protocol"] == "lagniappe-browser"
    assert messages[0].data["protocol_version"] == "2"
    assert messages[0].fid == "browser-token"
    assert multicasts[0].data["protocol"] == "lagniappe-browser"
    assert multicasts[0].data["protocol_version"] == "2"
    assert multicasts[0].fids == ["viewer-token"]


# @features messaging
# @dimensions stale-token
def test_multicast_message_discards_permanently_invalid_tokens(monkeypatch):
    from lagniappe.web import responses

    batch = SimpleNamespace(
        responses=[
            SimpleNamespace(
                exception=responses.messaging.UnregisteredError("expired token")
            ),
            SimpleNamespace(
                exception=responses.messaging.SenderIdMismatchError("wrong sender")
            ),
            SimpleNamespace(exception=RuntimeError("transient provider failure")),
            SimpleNamespace(exception=None),
        ]
    )
    discarded = []
    monkeypatch.setattr(
        responses.messaging,
        "send_each_for_multicast",
        lambda _message: batch,
    )
    monkeypatch.setattr(
        responses.cache,
        "discard_viewer_tokens",
        discarded.extend,
    )

    result = responses.send_multicast_message(
        "server-change",
        {"type": "delete", "key": "entity-key"},
        ["expired", "wrong-sender", "transient", "accepted"],
    )

    assert result is batch
    assert discarded == ["expired", "wrong-sender"]


# @pair messaging:expected-provider-failure
# @pair observability:span-filtering
def test_sentry_filter_removes_only_fcm_not_found_spans():
    from lagniappe.web import _filter_expected_fcm_not_found_spans

    fcm_not_found = {
        "description": (
            "POST https://fcm.googleapis.com/v1/projects/"
            "lagniappe-459100/messages:send"
        ),
        "data": {"http.response.status_code": 404},
    }
    fcm_unavailable = {
        **fcm_not_found,
        "data": {"http.response.status_code": 503},
    }
    unrelated_not_found = {
        "description": "GET https://example.test/missing",
        "data": {"http.response.status_code": 404},
    }
    event = {
        "transaction": "tasks.combine",
        "spans": [fcm_not_found, fcm_unavailable, unrelated_not_found],
    }

    filtered = _filter_expected_fcm_not_found_spans(event, {})

    assert filtered is not event
    assert event["spans"] == [fcm_not_found, fcm_unavailable, unrelated_not_found]
    assert filtered["spans"] == [fcm_unavailable, unrelated_not_found]


# @features error-reporting ai files
# @dimensions expected-provider-failure pdf-page-limit privacy
def test_sentry_filter_drops_only_expected_ai_document_page_limit():
    from lagniappe.web import _filter_expected_sentry_errors

    expected = {
        "exception": {
            "values": [
                {
                    "type": "ClientError",
                    "value": (
                        "The document contains 1203 pages which exceeds the "
                        "supported page limit of 1000."
                    ),
                }
            ]
        }
    }
    unrelated = {
        "exception": {
            "values": [
                {
                    "type": "ClientError",
                    "value": "A different provider request was invalid.",
                }
            ]
        },
        "user": {"email": "private@example.test"},
    }

    assert _filter_expected_sentry_errors(expected, {}) is None
    filtered = _filter_expected_sentry_errors(unrelated, {})
    assert filtered is not None
    assert "user" not in filtered


# @features messaging
# @dimensions permission-modal
def test_allow_messages(get_user):
    user = get_user(Users.OWNER)
    messaging_page = SitePages.CHECK_MESSAGING_PAGE.get(user)
    user.go(messaging_page)

    modal = Modal(user.page)
    modal.click("Allow Messages")
    expect(modal.element).to_be_hidden()


# @features messaging
# @dimensions permission-modal feature-gate
def test_manual_page_does_not_prompt_for_messaging_without_messaging_features(
    get_user,
):
    user = get_user(Users.OWNER)
    _force_production_messaging_mode(user.page)
    _force_default_notification_permission(user.page)
    firebase_config_requests = []
    user.page.on(
        "request",
        lambda request: firebase_config_requests.append(request.url)
        if request.url.endswith("/firebase-config")
        else None,
    )

    user.go(SitePage(url="/manual/", title="Manual"))

    expect(user.locate("[lp-view][data-kind='manual']")).to_have_attribute(
        "initialized",
        "",
    )
    expect(user.locate("#modal")).to_have_count(0)
    assert not firebase_config_requests
    assert user.page.evaluate(
        """() => {
            const view = document.querySelector("[lp-view]")?._lp_view;
            return Boolean(view) &&
                view.fcmToken === null &&
                view.readonly === false &&
                view.SyncManager?.token === null;
        }"""
    )


# @features auth
# @dimensions messaging-disabled session-keys
def test_public_user_suppresses_messaging_permission(get_user):
    owner = get_user(Users.OWNER)
    public_group = Entities.PUBLIC_GROUP.get()
    public_group.properties.permissions.create(
        {Site.PUBLIC.value: Levels.TRUE.name},
        user=owner.entity,
    )
    public_group.save()

    email = f"public-messaging-{uuid4().hex}@example.test"
    public_user = Entities.USER.create(
        {
            "email": email,
            "name": "Public Messaging",
            "is_public": True,
            "test_user": True,
        }
    )
    public_page = public_user.page
    public_page.form = Forms.test_sync_page_form.get(owner).entity
    public_page.submission = {"sync-text": "Initial form sync"}
    public_user.save()

    user = get_user(Users.ANONYMOUS)
    _force_production_messaging_mode(user.page)
    user.go(SitePages.LOGIN_PAGE, query_params={"test_user": email})
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")

    _assert_messaging_disabled(user)

    my_page = user.page.get_by_role("link", name="My Page")
    expect(my_page).to_be_visible()
    with user.page.expect_navigation():
        my_page.click()

    expect(user.page).to_have_title("Public Messaging")
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")
    expect(user.locate("[data-widget='PageInfo']")).to_have_attribute(
        "initialized",
        "",
    )
    expect(user.locate("[data-widget='PageInfo']")).to_contain_text(
        "Initial form sync"
    )
    _assert_messaging_disabled(user)
