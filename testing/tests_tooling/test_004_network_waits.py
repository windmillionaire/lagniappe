"""Tests for the shared successful-network-wait contract."""

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from testing.utility.network import expect_successful_response
from testing.utility import reconnect


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
            self.page.respond(FakeResponse(url="http://test.local/refresh"))


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

    assert response_info.value.url == "http://test.local/refresh"
    assert events == [
        "expect-offline",
        "offline=True",
        "visible=[data-role='offline']",
        "offline=False",
        "hidden=[data-role='offline']",
    ]
