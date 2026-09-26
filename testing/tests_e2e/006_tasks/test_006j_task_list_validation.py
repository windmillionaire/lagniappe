"""HTTP task-list reuse retains live authorization and current form HTML."""

from uuid import uuid4

from google.cloud.datastore import Entity
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.polling import task_lists
from lagniappe.web import app, responses
from lagniappe import CONFIG
from testing.definitions import Groups, Users


pytestmark = pytest.mark.e2e


@pytest.fixture
def quiet_control(monkeypatch):
    """Control only job timing; all entity/revision reads and saves remain real."""
    datastore = task_lists.DATA.datastore
    control = Entity(datastore.key(task_lists.KINDS.site.value, "deferred-jobs-control"))
    control.update(schema_version=2, tracked_jobs=[], active_jobs=0, desired_state="paused", generation=40)
    original = datastore.get_multi

    def get_multi(keys, **kwargs):
        if control.key not in keys:
            return original(keys, **kwargs)
        rows = original([key for key in keys if key != control.key], **kwargs)
        return [*rows, control]

    monkeypatch.setattr(datastore, "get_multi", get_multi)
    # New/empty installations are deliberately ineligible until all revisions
    # exist. This test needs a fully initialized site.
    database_utility.site_fingerprints(tuple(f"/{name}/index" for name in task_lists.CONTENT_CHANNELS))
    return control


def _client(user):
    client = app.test_client()
    for cookie in user.page.context.cookies():
        client.set_cookie(cookie["name"], cookie["value"])
    return client


def _fixture():
    page = Entities.PAGE.create({"name": f"Conditional Tasks {uuid4().hex[:8]}"})
    Entities.save(page)
    form = Entities.FORM.create({"name": "Task form before", "form-type": "task"})
    Entities.save(form)
    task = Entities.TASK.create({"name": "Task before", "page": page, "form": form})
    Entities.save(task)
    return page, task, form


# @source lagniappe/web/routes/pages/main.py::tasks
# @matrix tasks cache : conditional-response durable-revision viewer-scope
def test_unchanged_task_list_skips_loading_and_invalidates_on_save(get_user, monkeypatch, quiet_control):
    owner = get_user(Users.OWNER)
    page, task, form = _fixture()
    client = _client(owner)
    path = f"/pages/{page.urlsafe_key}/tasks"
    before = client.get(path)
    assert before.status_code == 200
    assert b"Task before" in before.data
    etag = before.headers["ETag"]

    def forbidden_task_query(*args, **kwargs):
        pytest.fail("Unchanged task list queried its Tasks before returning 304")

    with monkeypatch.context() as no_tasks:
        no_tasks.setattr(database_get, "page_tasks", forbidden_task_query)
        unchanged = client.get(path, headers={"If-None-Match": etag})
        assert unchanged.status_code == 304 and unchanged.data == b""

    forced_body = client.get(path, headers={"If-None-Match": etag, "Range": "bytes=0-"})
    assert forced_body.status_code == 200 and b"Task before" in forced_body.data

    task.name = "Task after"
    Entities.save(task)
    after = client.get(path, headers={"If-None-Match": etag})
    assert after.status_code == 200 and b"Task after" in after.data
    assert after.headers["ETag"] != etag
    etag = after.headers["ETag"]
    form.name = "Task form after"
    Entities.save(form)
    after_form = client.get(path, headers={"If-None-Match": etag})
    assert after_form.status_code == 200
    assert b"Task form after" in after_form.data
    assert after_form.headers["ETag"] != etag

    # A cached authorized response never bypasses a fresh access decision.
    blocked = _client(get_user(Users.user_no_access))
    denied = blocked.get(path, headers={"If-None-Match": after_form.headers["ETag"]})
    assert denied.status_code == 403
    assert b"Task after" not in denied.data


# @source lagniappe/web/auth.py::_load_session_user_context
# @source lagniappe/web/auth.py::_load_request_context
# @source lagniappe/web/auth.py::permission
# @source lagniappe/web/routes/pages/main.py::tasks
# @matrix auth : batch-load session-preload fallback
# @matrix tasks cache : conditional-response
def test_task_list_batches_validation_with_session_context(get_user, monkeypatch, quiet_control):
    owner = get_user(Users.OWNER)
    page, task, form = _fixture()
    client = _client(owner)
    path = f"/pages/{page.urlsafe_key}/tasks"
    etag = client.get(path).headers["ETag"]
    calls = []
    original = task_lists.DATA.datastore.get_multi

    def record_lookup(keys, **kwargs):
        calls.append(set(keys))
        return original(keys, **kwargs)

    monkeypatch.setattr(task_lists.DATA.datastore, "get_multi", record_lookup)
    unchanged = client.get(path, headers={"If-None-Match": etag})
    assert unchanged.status_code == 304 and unchanged.data == b""
    # Round-trip count is the optimization's contract, not an incidental call
    # sequence: roots/revisions together, then authorization relations.
    assert len(calls) == 2
    validation_keys = set(task_lists.snapshot_keys())
    assert {page.key, owner.entity.key, owner.entity.page.key} | validation_keys <= calls[0]
    assert not validation_keys & calls[1]

    calls.clear()
    assert client.get(f"/pages/{page.urlsafe_key}/info/replace").status_code == 200
    assert all(not validation_keys & keys for keys in calls)

    # A stale session still resolves the canonical identity through Flask-Login;
    # it must discard the failed preload and read validation state afresh.
    with client.session_transaction() as session:
        session[CONFIG.LOGIN_USER_PAGE_KEY] = page.urlsafe_key
    calls.clear()
    fallback = client.get(path, headers={"If-None-Match": etag})
    assert fallback.status_code == 200 and b"Task before" in fallback.data
    assert validation_keys in calls
    with client.session_transaction() as session:
        assert session[CONFIG.LOGIN_USER_PAGE_KEY] == owner.entity.page.urlsafe_key
    # Recovery may rebuild a different attached authorization graph. Seed the
    # next normal-session response before testing its reuse.
    etag = client.get(path).headers["ETag"]
    calls.clear()
    assert client.get(path, headers={"If-None-Match": etag}).status_code == 304
    assert len(calls) == 2


# @source lagniappe/web/routes/pages/main.py::tasks
# @matrix experiments : task-list-comparison
# @matrix tasks cache : conditional-response
def test_experiments_compare_task_list_paths_without_changing_content_or_access(
    get_user, monkeypatch, quiet_control,
):
    owner = get_user(Users.OWNER)
    blocked = _client(get_user(Users.user_no_access))
    page, task, form = _fixture()
    client = _client(owner)
    path = f"/pages/{page.urlsafe_key}/tasks"
    header = "X-Lagniappe-Experiments-Task-List"
    calls = []
    original = task_lists.DATA.datastore.get_multi

    def record_lookup(keys, **kwargs):
        calls.append(set(keys))
        return original(keys, **kwargs)

    monkeypatch.setattr(task_lists.DATA.datastore, "get_multi", record_lookup)
    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", True)
    batched = client.get(path, headers={header: "batched"})
    unbatched = client.get(path, headers={header: "unbatched"})
    assert batched.status_code == unbatched.status_code == 200
    assert b"Task before" in batched.data
    assert batched.data == unbatched.data
    assert batched.headers["ETag"] == unbatched.headers["ETag"]
    etag = batched.headers["ETag"]

    # Cross-path reuse is intentional: the selector changes scheduling only.
    for enabled, variant, expected_calls in (
        (True, "unbatched", 3), (True, "batched", 2),
        (True, "unknown", 2), (False, "unbatched", 2),
    ):
        monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", enabled)
        calls.clear()
        response = client.get(path, headers={header: variant, "If-None-Match": etag})
        assert response.status_code == 304 and response.data == b""
        assert len(calls) == expected_calls

    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", True)
    for variant in ("batched", "unbatched"):
        denied = blocked.get(path, headers={header: variant, "If-None-Match": etag})
        assert denied.status_code == 403 and b"Task before" not in denied.data


# @source lagniappe/web/auth.py::_load_session_user_context
# @source lagniappe/web/deferred_autofill.py::finish_task_list_validation
# @source lagniappe/web/routes/pages/main.py::tasks
# @matrix auth : batch-load
# @matrix tasks cache : conditional-response concurrent-render
def test_task_list_detects_change_after_batched_root_read(get_user, monkeypatch, quiet_control):
    owner = get_user(Users.OWNER)
    page, task, form = _fixture()
    client = _client(owner)
    original = task_lists.DATA.datastore.get_multi
    raced = False

    def change_after_roots(keys, **kwargs):
        nonlocal raced
        rows = original(keys, **kwargs)
        if not raced and page.key in keys and set(task_lists.snapshot_keys()) <= set(keys):
            raced = True
            form.name = "Changed after batched root read"
            Entities.save(form)
        return rows

    with monkeypatch.context() as race:
        race.setattr(task_lists.DATA.datastore, "get_multi", change_after_roots)
        response = client.get(f"/pages/{page.urlsafe_key}/tasks")
    assert raced and response.status_code == 200
    assert b"Changed after batched root read" in response.data
    assert "ETag" not in response.headers
    assert response.headers["Cache-Control"] == "no-store"
    settled = client.get(f"/pages/{page.urlsafe_key}/tasks")
    assert settled.status_code == 200 and settled.headers.get("ETag")


# @source lagniappe/web/routes/pages/main.py::tasks
# @matrix tasks cache : conditional-response job-lifecycle concurrent-render
def test_task_list_job_boundaries_and_render_race(get_user, monkeypatch, quiet_control):
    owner = get_user(Users.OWNER)
    page, task, form = _fixture()
    client = _client(owner)
    path = f"/pages/{page.urlsafe_key}/tasks"
    before = client.get(path)
    assert before.status_code == 200
    etag = before.headers["ETag"]
    quiet_control["generation"] += 2  # Start and finish between requests.
    after_job = client.get(path, headers={"If-None-Match": etag})
    assert after_job.status_code == 200 and after_job.headers["ETag"] != etag
    etag = after_job.headers["ETag"]

    quiet_control.update(tracked_jobs=["unrelated-job"], active_jobs=1, desired_state="enabled")
    busy = client.get(path, headers={"If-None-Match": etag})
    assert busy.status_code == 200
    calls = []
    original_query = database_get.page_tasks

    def record_query(*args, **kwargs):
        calls.append(True)
        return original_query(*args, **kwargs)

    with monkeypatch.context() as busy_check:
        busy_check.setattr(database_get, "page_tasks", record_query)
        unchanged = client.get(path, headers={"If-None-Match": busy.headers["ETag"]})
        assert unchanged.status_code == 304 and calls

    quiet_control.update(tracked_jobs=[], active_jobs=0, desired_state="paused", generation=44)
    original_render = responses.page_tasks

    def raced_render(page):
        response = original_render(page)
        quiet_control["generation"] += 1
        return response

    with monkeypatch.context() as race:
        race.setattr(responses, "page_tasks", raced_render)
        raced = client.get(path)
        assert raced.status_code == 200
        assert "ETag" not in raced.headers
        assert raced.headers["Cache-Control"] == "no-store"
    settled = client.get(path)
    assert settled.status_code == 200 and settled.headers.get("ETag")
    assert client.get(path, headers={"If-None-Match": settled.headers["ETag"]}).status_code == 304


# @source lagniappe/web/routes/pages/main.py::tasks
# @matrix tasks cache permissions : conditional-response immediate-revocation inherited-restrictions
@pytest.mark.parametrize("restriction", ["page", "page-form", "task-form"])
def test_task_list_rechecks_restrictions_for_cached_viewer(get_user, quiet_control, restriction):
    owner = get_user(Users.OWNER)
    viewer = get_user(Users.models_forms_view_only)
    category = Entities.CATEGORY.create({"name": f"Restriction category {uuid4().hex[:8]}"})
    Entities.save(category)
    page = Entities.PAGE.create({"name": f"Restriction cache {uuid4().hex[:8]}", "model": category})
    page_form = Entities.FORM.create({"name": "Page access", "form-type": "page"})
    task_form = Entities.FORM.create({"name": "Task access", "form-type": "task"})
    Entities.save(page_form, task_form)
    page.form = page_form
    Entities.save(page)
    task = Entities.TASK.create({"name": "Visible until revoked", "page": page, "form": task_form})
    Entities.save(task)
    group = Groups.general_forms_view_only.get(owner).entity
    client = _client(viewer)
    path = f"/pages/{page.urlsafe_key}/tasks"
    before = client.get(path)
    assert before.status_code == 200 and b"Visible until revoked" in before.data
    etag = before.headers["ETag"]
    assert client.get(path, headers={"If-None-Match": etag}).status_code == 304
    source = {"page": page, "page-form": page_form, "task-form": task_form}[restriction]
    source.groups = [group]
    Entities.save(source)
    after = client.get(path, headers={"If-None-Match": etag})
    assert after.status_code == (200 if restriction == "task-form" else 403)
    assert b"Visible until revoked" not in after.data
