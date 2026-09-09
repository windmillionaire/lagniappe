"""Form saves must change existing search results without descendant saves."""
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import Groups, SitePages, Users
from testing.definitions.form_definitions import FormDefinition
from testing.resources.form import Form
from testing.elements import HeaderSearch, Select

pytestmark = pytest.mark.e2e


# @matrix permissions search files : task-move ancestor-tags
def test_task_move_updates_all_owned_file_search_permissions():
    from lagniappe.core.tools.cache.core import cache
    from lagniappe.core.tools.cache.keys import Search

    category = Entities.CATEGORY.create({"name": f"Move permissions {uuid4().hex}"})
    category.save()
    source = Entities.PAGE.create({"name": "Open source", "model": category})
    destination = Entities.PAGE.create({"name": "Restricted destination", "model": category})
    destination.properties.restricted_to.materialize(owner_only=True)
    Entities.save(source, destination)
    task = Entities.TASK.create({"page": source, "name": "Moving Task"})
    task.save()
    current = Entities.FILE.create(data={"name": "Current attachment"})
    archived = Entities.FILE.create(data={"name": "Earlier attachment"})
    task.files = [current]
    archived.task = task
    Entities.save(task, current, archived)
    assert archived.key not in task.properties.files.keys

    for target, previous, restriction in ((destination, source, "owner"), (source, destination, None)):
        task.page = target
        task.save()
        for file in (current, archived):
            stored = Entities.fetch_one(file.key, request=Fetch.root())
            assert stored.properties.task.key == task.key
            assert not stored.properties.page.key
            assert {task.hash, target.hash} <= set(stored.requires)
            assert previous.hash not in stored.requires
            assert cache.hget(Search.file.key(file), "restricted_to") == restriction


# @matrix permissions search : reconciliation removal page-override page-precedence source-save
# @matrix forms : access-restrictions explicit-submit group-restricted owner-restricted
# @template forms/restrictions.html::restrict_access
# @template nav.html::search_results
@pytest.mark.parametrize("form_type", ["page", "task"])
def test_form_restrictions_reconcile_existing_descendants(get_user, browser_failures, form_type):
    owner = get_user(Users.OWNER)
    viewer = get_user(Users.general_models_view_only)
    group = Groups.general_models_view_only.get(owner)
    other_group = Groups.general_forms_view_only.get(owner)
    token = f"permission{uuid4().hex[:12]}"
    form = Form(user=owner, definition=FormDefinition(name=f"{token} Form", form_type=form_type)).create()
    page = Entities.PAGE.create({"name": f"{token} Page", "form": form.entity if form_type == "page" else None})
    page.save()
    task = Entities.TASK.create({"page": page, "name": f"{token} Task", "form": form.entity if form_type == "task" else None})
    task.save()
    page_file = Entities.FILE.create(page=page, data={"name": f"{token} PageFile"})
    task_file = Entities.FILE.create(data={"name": f"{token} TaskFile"})
    task.files = [task_file]
    Entities.save(task, task_file, page_file)
    overrides = []
    if form_type == "page":
        override_page = Entities.PAGE.create({"name": f"{token} Override", "form": form.entity,
                                             "model": Entities.fetch_one(page.model, request=Fetch.direct())})
        override_page.groups = [group.entity]
        override_page.save()
        override_task = Entities.TASK.create({"page": override_page, "name": f"{token} OverrideTask"})
        override_task.save()
        override_file = Entities.FILE.create(data={"name": f"{token} OverrideFile"})
        override_task.files = [override_file]
        Entities.save(override_task, override_file)
        overrides = [override_page, override_task, override_file]
    affected = [task, task_file] + ([page, page_file] if form_type == "page" else [])
    baseline = {entity.key: Entities.fetch_one(entity.key, request=Fetch.root()).modified for entity in affected}

    viewer.go(SitePages.HOME)
    builder = form.builder
    restrictions = builder.restrictions()
    requests = []
    owner.page.on("request", lambda request: requests.append(request) if request.method == "PUT" and request.url.endswith("/restrictions") else None)

    def search_visible(expected):
        # Hosted reconciliation finishes asynchronously. Observe its public
        # search result before issuing the visible header-search query.
        viewer.page.wait_for_function("""async ({query, affected, overrides, expected}) => {
                const response = await fetch(`/l/search-bar?${new URLSearchParams({q: query})}`, {cache: "no-store"});
                if (!response.ok) throw new Error(`Search returned ${response.status}`);
                const html = new DOMParser().parseFromString((await response.json()).results, "text/html");
                const urls = new Set([...html.querySelectorAll("[data-url]")].map(item => item.dataset.url));
                return overrides.every(url => urls.has(url)) &&
                    affected.every(url => urls.has(url) === expected);
            }""", arg={
                "query": token,
                "affected": [f"/{entity.entity_kind}s/{entity.urlsafe_key}" for entity in affected],
                "overrides": [f"/{entity.entity_kind}s/{entity.urlsafe_key}" for entity in overrides],
                "expected": expected,
            }, polling=250, timeout=30_000)
        viewer.locate("[lp-search] input[name='q']").fill("")
        search = HeaderSearch(viewer)
        search.search(token)
        for entity in overrides:
            expect(search.panel.locator(f"[data-url='/{entity.entity_kind}s/{entity.urlsafe_key}']")).to_be_visible()
        for entity in affected:
            result = search.panel.locator(f"[data-url='/{entity.entity_kind}s/{entity.urlsafe_key}']")
            if expected:
                expect(result).to_be_visible()
            else:
                expect(result).to_have_count(0)

    search_visible(True)
    checkbox = restrictions.locator("input[name='owner']")
    checkbox.check()
    # A draft must neither issue a save nor hide existing search results.
    assert requests == []
    search_visible(True)
    builder.save_restrictions()
    assert len(requests) == 1
    for entity in affected:
        path = f"/{entity.entity_kind}s/{entity.urlsafe_key}"
        with browser_failures.expect_http_error(viewer, status=403, path=path):
            status = viewer.page.evaluate("async url => (await fetch(url, {cache: 'no-store'})).status", path)
            assert status == 403
    search_visible(False)

    checkbox.uncheck()
    Select(restrictions.locator(builder.RESTRICT_GROUP_INPUT)).select_by_key(group.key, query=group.definition.name)
    assert len(requests) == 1
    builder.save_restrictions()
    search_visible(True)

    # Replacing a permitted group must hide the same records for this viewer.
    restrictions.locator("button[data-role='remove-restriction']").click()
    Select(restrictions.locator(builder.RESTRICT_GROUP_INPUT)).select_by_key(other_group.key, query=other_group.definition.name)
    builder.save_restrictions()
    search_visible(False)

    # Removing all restrictions must restore the same already-indexed entities.
    restrictions.locator("button[data-role='remove-restriction']").click()
    builder.save_restrictions()
    search_visible(True)
    assert len(requests) == 4
    for entity in affected:
        current = Entities.fetch_one(entity.key, request=Fetch.root())
        assert current.modified == baseline[entity.key]
        assert not current.db.get("restricted_to")

    if form_type == "task":
        # A Page's local restriction takes precedence; clearing it exposes the
        # Task Form again. Each source save must reconcile the existing File.
        checkbox.check()
        builder.save_restrictions()
        search_visible(False)
        current_page = Entities.fetch_one(page.key, request=Fetch.direct())
        current_page.groups = [group.entity]
        current_page.save()
        search_visible(True)
        current_page.groups = []
        current_page.save()
        search_visible(False)
        current_task = Entities.fetch_one(task.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
        current_task.form = None
        current_task.save()
        search_visible(True)
        assert Entities.fetch_one(task_file.key, request=Fetch.root()).modified == baseline[task_file.key]


# @matrix permissions search : reconciliation queue retry continuation authentication
def test_restriction_worker_retries_and_continues(monkeypatch):
    from google.oauth2 import id_token

    from lagniappe import CONFIG
    from lagniappe.core import exceptions
    from lagniappe.core.tools.cache import restrictions as worker
    from lagniappe.web import app

    client = app.test_client()
    assert client.post("/process/reconcile-restrictions", json={"source_key": "form"}).status_code == 401

    def verify_token(token, request, audience):
        assert token == "restriction-worker-test"
        assert audience.endswith("/process/reconcile-restrictions")
        return {
            "iss": "https://accounts.google.com",
            "email": CONFIG.INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL,
        }

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify_token)
    headers = {"Authorization": "Bearer restriction-worker-test"}
    assert client.post("/process/reconcile-restrictions", headers=headers, json={"offset": 0}).status_code == 400
    remaining = {"source_key": "form", "cursor": "next", "offset": 0}
    queued = []
    monkeypatch.setattr(worker, "reconcile_batch", lambda **payload: remaining)
    monkeypatch.setattr(worker, "enqueue", queued.append)
    response = client.post("/process/reconcile-restrictions", headers=headers, json={"source_key": "form"})
    assert response.status_code == 200 and response.json == {"success": True}
    assert queued == [remaining]

    def unavailable(**payload):
        raise RuntimeError("Cache unavailable")

    monkeypatch.setattr(worker, "reconcile_batch", unavailable)
    monkeypatch.setattr(exceptions, "capture", lambda *args, **kwargs: None)
    response = client.post("/process/reconcile-restrictions", headers=headers, json={"source_key": "form"})
    assert response.status_code == 503 and response.json == {"success": False, "retry": True}


# @matrix permissions search : reconciliation batching duplicate-names
def test_restriction_reconciliation_visits_every_indexed_batch(monkeypatch):
    from lagniappe.core.tools.cache import restrictions as worker
    from lagniappe.core.tools.cache.keys import Search

    form = Entities.FORM.create({"name": f"Batch {uuid4().hex}", "form-type": "page"})
    form.save()
    category = Entities.CATEGORY.create({"name": f"Batch Category {uuid4().hex}"})
    category.save()
    page = Entities.PAGE.create({"name": "Batch Page", "form": form, "model": category})
    page.save()
    task = Entities.TASK.create({"name": "Batch Task", "page": page})
    task.save()
    files = [Entities.FILE.create(data={"name": "Same file name"}) for _ in range(7)]
    task.files = files
    Entities.save(task, *files)
    monkeypatch.setattr(worker, "BATCH_SIZE", 2)
    form.properties.restricted_to.materialize(owner_only=True)
    form.save()
    for entity in (page, task, *files):
        assert worker.cache.redis.hget(Search[entity.kind].key(entity), "restricted_to") == b"owner"
    form.properties.restricted_to.materialize(owner_only=False)
    form.save()
    for entity in (page, task, *files):
        assert worker.cache.redis.hget(Search[entity.kind].key(entity), "restricted_to") is None
