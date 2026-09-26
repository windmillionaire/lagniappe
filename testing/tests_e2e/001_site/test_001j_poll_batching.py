"""Polling retains fresh authorization while sharing independent durable reads."""

from uuid import uuid4

import pytest

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import utility
from lagniappe.web import app
from testing.definitions import Groups, Users


pytestmark = pytest.mark.e2e


@pytest.fixture
def polling_client(get_user, monkeypatch):
    # CSRF is covered at its own HTTP boundary; this story isolates read order.
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    user = get_user(Users.admin)
    client = app.test_client()
    for cookie in user.page.context.cookies():
        client.set_cookie(cookie["name"], cookie["value"])
    assert client.get("/").status_code == 200
    page = Entities.PAGE.create({"name": f"Poll batching {uuid4().hex[:8]}"})
    Entities.save(page)
    yield client, user, page
    if remaining := Entities.fetch_one(page.key, request=Fetch.direct()):
        Entities.delete(remaining)


def _payload(page):
    return {
        "version": 1, "client_id": "poll-batching-check", "closed_documents": [],
        "subscriptions": [
            {"id": "page", "type": "entity", "key": page.urlsafe_key, "revision": page.fingerprint},
            {"id": "tasks", "type": "channel", "channel": "tasks", "revision": None},
        ],
    }


# @source lagniappe/web/auth.py::_load_session_user_context
# @source lagniappe/web/auth.py::_load_request_context
# @source lagniappe/web/auth.py::logged_in
# @source lagniappe/web/routes/home/poll.py::poll
# @matrix polling auth : batching session-preload fallback validation
def test_poll_batches_auth_entities_and_channels(polling_client, monkeypatch):
    client, user, page = polling_client
    payload = _payload(page)
    utility.site_fingerprints(["/tasks/index"])
    calls = []
    original = utility.DATA.datastore.get_multi

    def lookup(keys, **kwargs):
        calls.append(set(keys))
        return original(keys, **kwargs)

    monkeypatch.setattr(utility.DATA.datastore, "get_multi", lookup)
    candidate = client.post("/l/poll", json=payload)
    assert candidate.status_code == 200
    # One auth/root/revision batch, then its shared direct relations. Nested
    # task/file authorization, where needed, remains an independent boundary.
    assert len(calls) == 2
    assert {user.entity.key, user.entity.page.key, page.key, utility.DATA.datastore.key("site", "tasks")} <= calls[0]
    assert candidate.json["results"][0]["status"] == "unchanged"
    assert candidate.json["results"][1]["status"] == "changed"
    payload["subscriptions"][1]["revision"] = candidate.json["results"][1]["revision"]
    unchanged = client.post("/l/poll", json=payload)
    assert all(result["status"] == "unchanged" for result in unchanged.json["results"])

    page.name = "Changed between polls"
    Entities.save(page)
    changed = client.post("/l/poll", json=payload)
    assert changed.json["results"][0]["status"] == "changed"
    assert changed.json["results"][0]["revision"] != payload["subscriptions"][0]["revision"]


# @source lagniappe/web/auth.py::_load_session_user_context
# @source lagniappe/web/auth.py::_load_request_context
# @source lagniappe/web/auth.py::logged_in
# @source lagniappe/web/routes/home/poll.py::poll
# @matrix polling auth : batching session-preload fallback validation
def test_poll_batching_preserves_validation_and_stale_session_recovery(polling_client, monkeypatch):
    client, user, page = polling_client
    payload = _payload(page)
    with client.session_transaction() as session:
        session[CONFIG.LOGIN_USER_PAGE_KEY] = page.urlsafe_key
    assert client.post("/l/poll", json=payload).status_code == 200
    with client.session_transaction() as session:
        assert session[CONFIG.LOGIN_USER_PAGE_KEY] == user.entity.page.urlsafe_key
    assert client.post("/l/poll", json={}).status_code == 422
    anonymous = app.test_client().post(
        "/l/poll", json={}, headers={"X-Lagniappe-Request": "true"},
    )
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].endswith("/users/login")

    Entities.delete(page)
    missing = client.post("/l/poll", json=payload)
    assert missing.json["results"][0]["status"] == "unavailable"


# @source lagniappe/web/auth.py::_load_session_user_context
# @source lagniappe/web/routes/home/poll.py::poll
# @matrix polling permissions : batching authorization
# @matrix auth : session-preload
@pytest.mark.parametrize("restriction", ["page", "page-form", "task-form", "user"])
def test_batched_poll_rechecks_permissions(polling_client, get_user, restriction):
    client, user, page = polling_client
    owner = get_user(Users.OWNER)
    group = Groups.general_forms_view_only.get(owner).entity
    page_form = Entities.FORM.create({"name": "Poll Page access", "form-type": "page"})
    task_form = Entities.FORM.create({"name": "Poll Task access", "form-type": "task"})
    Entities.save(page_form, task_form)
    page.form = page_form
    Entities.save(page)
    task = Entities.TASK.create({"name": "Poll nested Task", "page": page, "form": task_form})
    Entities.save(task)
    original_groups = list(user.entity.groups)
    try:
        payload = _payload(page)
        payload["subscriptions"].append({
            "id": "task", "type": "entity", "key": task.urlsafe_key, "revision": None,
        })
        before = client.post("/l/poll", json=payload)
        assert before.status_code == 200
        assert all(result["status"] != "unavailable" for result in before.json["results"])
        source = {"page": page, "page-form": page_form, "task-form": task_form, "user": user.entity}[restriction]
        source.groups = [] if restriction == "user" else [group]
        Entities.save(source)
        after = client.post("/l/poll", json=payload)
        assert after.status_code == 200
        results = {result["id"]: result for result in after.json["results"]}
        assert results["task"]["status"] == "unavailable"
        if restriction != "task-form":
            assert results["page"]["status"] == "unavailable"
    finally:
        if restriction == "user":
            user.entity.groups = original_groups
            Entities.save(user.entity)
        Entities.delete(task)
        page.form = None
        Entities.save(page)
        Entities.delete(page_form, task_form)
