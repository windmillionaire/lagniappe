"""Tests for the shared successful-network-wait contract."""

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from testing.utility.network import (
    assert_lagniappe_error_response,
    expect_successful_response,
    multipart_form_fields,
    scoped_browser_route,
)
from testing.utility import offline, polling, reconnect


pytestmark = pytest.mark.tooling


class FakePage:
    def __init__(self):
        self.pending = None

    def wait_for_function(self, _expression):
        return None

    @contextmanager
    def expect_response(self, predicate, **_options):
        response_info = SimpleNamespace(value=None)
        self.pending = (predicate, response_info)
        try:
            yield response_info
        finally:
            self.pending = None
            assert response_info.value is not None, "No response satisfied the wait"

    def respond(self, response):
        predicate, response_info = self.pending
        if predicate(response):
            response_info.value = response


class FakeRoutingTarget:
    def __init__(self):
        self.events = []

    def route(self, pattern, handler):
        self.events.append(("route", pattern, handler))

    def unroute(self, pattern, handler):
        self.events.append(("unroute", pattern, handler))


class FakeResponse:
    def __init__(
        self,
        *,
        method="POST",
        url="http://test.local/tasks/page/create",
        post_data="",
        status=200,
        headers=None,
        body="",
        payload=None,
    ):
        self.request = SimpleNamespace(method=method, post_data=post_data)
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.payload = payload

    @property
    def ok(self):
        return 200 <= self.status < 300

    def text(self):
        return self.body

    def json(self):
        return self.payload


def _revisions(*keys):
    return {
        "x-lagniappe-entity-revisions": json.dumps(
            [{"key": key} for key in keys]
        )
    }


def test_lagniappe_error_response_contract():
    response = SimpleNamespace(
        status_code=403,
        headers={
            "content-type": "text/html; charset=utf-8",
            "x-lagniappe-error": "Error 403",
        },
        text="<h1>Error 403</h1>",
    )

    assert_lagniappe_error_response(response, status=403)

    invalid_responses = [
        SimpleNamespace(**{**response.__dict__, "status_code": 404}),
        SimpleNamespace(
            **{
                **response.__dict__,
                "headers": {
                    **response.headers,
                    "content-type": "application/json",
                },
            }
        ),
        SimpleNamespace(
            **{
                **response.__dict__,
                "headers": {
                    **response.headers,
                    "x-lagniappe-error": "Error 404",
                },
            }
        ),
        SimpleNamespace(**{**response.__dict__, "text": "Access denied"}),
        SimpleNamespace(
            **{
                **response.__dict__,
                "headers": {
                    **response.headers,
                    "x-lagniappe-entity-revisions": "[]",
                },
            }
        ),
    ]
    for invalid in invalid_responses:
        with pytest.raises(AssertionError):
            assert_lagniappe_error_response(invalid, status=403)

    playwright_response = SimpleNamespace(
        status=400,
        headers={
            "content-type": "text/html; charset=utf-8",
            "x-lagniappe-error": "Error 400",
        },
        text=lambda: "<h1>Error 400</h1>",
    )
    assert_lagniappe_error_response(playwright_response, status=400)


def test_scoped_browser_route_always_removes_handler():
    target = FakeRoutingTarget()
    handler = object()

    with scoped_browser_route(target, "**/ping", handler):
        assert target.events == [("route", "**/ping", handler)]

    assert target.events[-1] == ("unroute", "**/ping", handler)

    with pytest.raises(RuntimeError, match="route body failed"):
        with scoped_browser_route(target, "**/sync", handler):
            raise RuntimeError("route body failed")

    assert target.events[-1] == ("unroute", "**/sync", handler)


def test_multipart_form_fields_preserves_values_and_filenames():
    boundary = "----lagniappe-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        "Generate a bright image\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="tag"\r\n\r\n'
        "first\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="tag"\r\n\r\n'
        "second\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="upload"; '
        'filename="sample.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
        "file bytes\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    request = SimpleNamespace(
        header_value=lambda name: (
            f"multipart/form-data; boundary={boundary}"
            if name == "content-type"
            else None
        ),
        post_data_buffer=body,
    )

    assert multipart_form_fields(request) == [
        ("prompt", "Generate a bright image"),
        ("tag", "first"),
        ("tag", "second"),
        ("upload", "sample.png"),
    ]


def test_wait_matches_exact_method_path_query_and_request_payload():
    page = FakePage()

    with expect_successful_response(
        page,
        method="POST",
        path="/tasks/page/create",
        query={"source": "task-form"},
        entity_key="page",
        request_payload_contains=("name", "Created task"),
    ) as response_info:
        page.respond(
            FakeResponse(
                method="PUT",
                url="http://test.local/tasks/page/create?source=task-form",
                post_data="name=Created task",
                headers=_revisions("page"),
            )
        )
        page.respond(
            FakeResponse(
                url="http://test.local/tasks/other/create?source=task-form",
                post_data="name=Created task",
                headers=_revisions("page"),
            )
        )
        page.respond(
            FakeResponse(
                url="http://test.local/tasks/page/create?source=other",
                post_data="name=Created task",
                headers=_revisions("page"),
            )
        )
        page.respond(
            FakeResponse(
                url="http://test.local/tasks/page/create?source=task-form",
                post_data="name=Other task",
                headers=_revisions("page"),
            )
        )
        expected = FakeResponse(
            url="http://test.local/tasks/page/create?source=task-form",
            post_data="name=Created task",
            headers=_revisions("page"),
        )
        page.respond(expected)

    assert response_info.value is expected


def test_wait_reports_matching_http_failure_without_timing_out():
    page = FakePage()

    with pytest.raises(AssertionError) as error:
        with expect_successful_response(
            page,
            method="PUT",
            path="/tasks/task/update",
        ):
            page.respond(
                FakeResponse(
                    method="PUT",
                    url="http://test.local/tasks/task/update",
                    status=422,
                    body="Task name is required",
                )
            )

    message = str(error.value)
    assert "PUT /tasks/task/update" in message
    assert "HTTP 422" in message
    assert "Task name is required" in message


def test_wait_validates_entity_revisions_and_response_payload():
    page = FakePage()

    with pytest.raises(AssertionError, match="did not acknowledge entity 'task'"):
        with expect_successful_response(
            page,
            method="PUT",
            path="/tasks/task/update",
            entity_key="task",
        ):
            page.respond(
                FakeResponse(
                    method="PUT",
                    url="http://test.local/tasks/task/update",
                    headers=_revisions("page"),
                )
            )

    with expect_successful_response(
        page,
        method="POST",
        path="/reports",
        expected_status=201,
        response_check=lambda response: assert_deferred(response),
    ) as response_info:
        page.respond(
            FakeResponse(
                url="http://test.local/reports",
                status=201,
                payload={"deferred": True},
            )
        )

    assert response_info.value.status == 201


def assert_deferred(response):
    assert response.json()["deferred"] is True


def test_poll_wait_matches_subscription_and_validates_result():
    page = FakePage()
    subscription_id = "edit:task-key"

    with polling.expect_poll_result(
        page,
        subscription_id=subscription_id,
    ) as response_info:
        page.respond(
            FakeResponse(
                url="http://test.local/l/poll",
                post_data='{"subscriptions":[{"id":"edit:other-task"}]}',
                payload={
                    "version": 1,
                    "results": [{"id": "edit:other-task", "status": "changed"}],
                },
            )
        )
        expected = FakeResponse(
            url="http://test.local/l/poll",
            post_data=(
                '{"subscriptions":[{"id":"edit:task-key",'
                '"type":"entity"}]}'
            ),
            payload={
                "version": 1,
                "results": [{"id": subscription_id, "status": "changed"}],
            },
        )
        page.respond(expected)

    assert response_info.value is expected


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"version": 1, "results": []},
            "did not return subscription 'view:entity:file-key'",
        ),
        (
            {
                "version": 1,
                "results": [
                    {"id": "view:entity:file-key", "status": "unchanged"}
                ],
            },
            "expected 'changed'",
        ),
    ],
)
def test_poll_wait_reports_missing_or_unexpected_result(payload, message):
    page = FakePage()

    with pytest.raises(AssertionError, match=message):
        with polling.expect_poll_result(
            page,
            subscription_id="view:entity:file-key",
        ):
            page.respond(
                FakeResponse(
                    url="http://test.local/l/poll",
                    post_data=(
                        '{"subscriptions":[{"id":"view:entity:file-key"}]}'
                    ),
                    payload=payload,
                )
            )


class FakeJavaScriptHandle:
    def __init__(self, value):
        self.value = value
        self.disposed = False

    def json_value(self):
        return self.value

    def dispose(self):
        self.disposed = True


class FakeOfflinePage:
    def __init__(self, rows, *, timeout=False):
        self.rows = rows
        self.timeout = timeout
        self.wait = None
        self.evaluation = None
        self.handle = None

    def wait_for_function(self, expression, *, arg, timeout=None):
        self.wait = (expression, arg, timeout)
        if self.timeout:
            raise PlaywrightTimeoutError("Offline record wait timed out")
        self.handle = FakeJavaScriptHandle(self.rows)
        return self.handle

    def evaluate(self, expression, *, arg):
        self.evaluation = (expression, arg)
        return self.rows


def test_offline_sync_wait_uses_browser_condition_and_returns_records():
    rows = [{"save": True, "html": "First offline edit\nSecond offline edit"}]
    page = FakeOfflinePage(rows)
    user = SimpleNamespace(page=page)

    result = offline.wait_for_offline_sync_records(
        user,
        minimum=1,
        saved_html_contains=("First offline edit", "Second offline edit"),
    )

    assert result == rows
    assert page.wait[1] == {
        "storeName": "sync",
        "minimum": 1,
        "exact": None,
        "savedHtmlContains": ["First offline edit", "Second offline edit"],
        "recordKey": "sync_id",
        "recordValue": None,
    }
    assert page.wait[2] is None
    assert page.handle.disposed is True


def test_offline_sync_wait_scopes_records_and_accepts_a_longer_bound():
    rows = []
    page = FakeOfflinePage(rows)

    result = offline.wait_for_offline_sync_records(
        SimpleNamespace(page=page),
        sync_id="project:document",
        exact=0,
        timeout=30000,
    )

    assert result == rows
    assert page.wait[1]["recordKey"] == "sync_id"
    assert page.wait[1]["recordValue"] == "project:document"
    assert page.wait[2] == 30000


class FakeOfflineReplayPage:
    def __init__(self):
        self.listener = None
        self.evaluation = None

    def on(self, event, listener):
        assert event == "response"
        self.listener = listener

    def remove_listener(self, event, listener):
        assert event == "response"
        assert listener is self.listener
        self.listener = None

    def evaluate(self, expression):
        self.evaluation = expression
        return True

    def respond(self, response):
        self.listener(response)


def test_offline_sync_replay_waits_for_manager_and_exact_matching_response():
    page = FakeOfflineReplayPage()
    user = SimpleNamespace(page=page)
    expected = FakeResponse(
        url="http://test.local/l/sync",
        post_data='{"updates":["offline edit","remote edit"]}',
    )

    with offline.expect_offline_sync_replay(
        user,
        request_payload_contains=("offline edit", "remote edit"),
    ) as responses:
        page.respond(
            FakeResponse(
                url="http://test.local/l/sync",
                post_data='{"updates":["unrelated"]}',
            )
        )
        page.respond(expected)

    assert responses == [expected]
    assert "await view?.syncReady" in page.evaluation
    assert "await manager.ready" in page.evaluation
    assert page.listener is None


def test_offline_record_wait_validates_conditions_and_reports_current_rows():
    user = SimpleNamespace(page=FakeOfflinePage([]))

    with pytest.raises(ValueError, match="require a count or saved HTML"):
        offline.wait_for_offline_sync_records(user)
    with pytest.raises(ValueError, match="either minimum or exact"):
        offline.wait_for_offline_sync_records(user, minimum=1, exact=1)
    with pytest.raises(ValueError, match="must be non-negative"):
        offline.wait_for_offline_mutations(user, exact=-1)

    rows = [{"save": True, "html": "Different edit"}]
    page = FakeOfflinePage(rows, timeout=True)
    with pytest.raises(AssertionError) as error:
        offline.wait_for_offline_sync_records(
            SimpleNamespace(page=page),
            exact=0,
            saved_html_contains=("Expected edit",),
            sync_id="expected:document",
        )

    message = str(error.value)
    assert "offline sync store" in message
    assert "exactly 0 record(s)" in message
    assert "saved HTML containing ('Expected edit',)" in message
    assert "sync_id='expected:document'" in message
    assert "0 matching record(s) out of 1 total" in message
    assert page.evaluation[1] == "sync"

    unreadable = FakeOfflinePage(None, timeout=True)
    with pytest.raises(AssertionError, match="IndexedDB read failed"):
        offline.wait_for_offline_sync_records(
            SimpleNamespace(page=unreadable),
            exact=0,
        )


class FakeBrowserFailures:
    def __init__(self, events):
        self.events = events

    @contextmanager
    def expect_offline(self, _user):
        self.events.append("expect-offline")
        yield


class FakeUser:
    def __init__(self, page, events):
        self.page = page
        self.events = events
        self._offline = False

    def locate(self, selector):
        return selector

    @property
    def offline(self):
        return self._offline

    @offline.setter
    def offline(self, value):
        self._offline = value
        self.events.append(f"offline={value}")
        if not value:
            self.page.respond(FakeResponse(url="http://test.local/l/refresh"))


def test_reconnect_wait_uses_native_offline_state_and_requires_refresh(monkeypatch):
    page = FakePage()
    events = []
    user = FakeUser(page, events)

    class FakeExpectation:
        def __init__(self, target):
            self.target = target

        def to_be_visible(self):
            events.append(f"visible={self.target}")

        def to_be_hidden(self):
            events.append(f"hidden={self.target}")

    monkeypatch.setattr(reconnect, "expect", FakeExpectation)

    with reconnect.expect_reconnect_refresh(
        user,
        FakeBrowserFailures(events),
    ) as response_info:
        user.offline = False

    assert response_info.value.url == "http://test.local/l/refresh"
    assert events == [
        "expect-offline",
        "offline=True",
        "visible=[data-role='offline']",
        "offline=False",
        "hidden=[data-role='offline']",
    ]
