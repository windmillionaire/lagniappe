"""Form saves update inherited search access without descendant content saves."""
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
    destination.properties.restricted_to.materialize(admin_only=True)
    Entities.save(source, destination)
    task = Entities.TASK.create({"page": source, "name": "Moving Task"})
    task.save()
    current = Entities.FILE.create(data={"name": "Current attachment"})
    archived = Entities.FILE.create(data={"name": "Earlier attachment"})
    task.files = [current]
    archived.task = task
    Entities.save(task, current, archived)
    assert archived.key not in task.properties.files.keys

    for target, previous, restriction in ((destination, source, "admin"), (source, destination, None)):
        task.page = target
        task.save()
        for file in (current, archived):
            stored = Entities.fetch_one(file.key, request=Fetch.root())
            assert stored.properties.task.key == task.key
            assert stored.properties.page.key is None
            assert stored.properties.task_page.key == target.key
            assert {task.hash, target.hash} <= set(stored.requires)
            assert previous.hash not in stored.requires
            assert cache.hget(Search.file.key(file), "restricted_to_page") == restriction


# @matrix permissions search : reconciliation removal local-restrictions source-clauses source-save
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
    category = Entities.CATEGORY.create({"name": f"{token} Category"})
    category.save()
    page = Entities.PAGE.create({"name": f"{token} Page", "model": category,
                                 "form": form.entity if form_type == "page" else None})
    page.save()
    task = Entities.TASK.create({"page": page, "name": f"{token} Task", "form": form.entity if form_type == "task" else None})
    task.save()
    page_file = Entities.FILE.create(page=page, data={"name": f"{token} PageFile"})
    task_file = Entities.FILE.create(data={"name": f"{token} TaskFile"})
    task.files = [task_file]
    Entities.save(task, task_file, page_file)
    local_entities = []
    if form_type == "page":
        local_page = Entities.PAGE.create({"name": f"{token} Local", "form": form.entity,
                                             "model": Entities.fetch_one(page.model, request=Fetch.direct())})
        local_page.groups = [group.entity]
        local_page.save()
        local_task = Entities.TASK.create({"page": local_page, "name": f"{token} LocalTask"})
        local_task.save()
        local_file = Entities.FILE.create(data={"name": f"{token} LocalFile"})
        local_task.files = [local_file]
        Entities.save(local_task, local_file)
        local_entities = [local_page, local_task, local_file]
    affected = [task, task_file, *local_entities] + ([page, page_file] if form_type == "page" else [])
    baseline = {entity.key: Entities.fetch_one(entity.key, request=Fetch.root()).modified for entity in affected}
    local_groups = {entity.key: list(entity.db.get("restricted_to") or []) for entity in affected}

    viewer.go(SitePages.HOME)
    builder = form.builder
    restrictions = builder.restrictions()
    requests = []
    owner.page.on("request", lambda request: requests.append(request) if request.method == "PUT" and request.url.endswith("/restrictions") else None)

    def search_visible(expected):
        # Hosted reconciliation finishes asynchronously. Observe its public
        # search result before issuing the visible header-search query.
        viewer.page.wait_for_function("""async ({query, affected, expected}) => {
                const response = await fetch(`/l/search-bar?${new URLSearchParams({q: query})}`, {cache: "no-store"});
                if (!response.ok) throw new Error(`Search returned ${response.status}`);
                const html = new DOMParser().parseFromString((await response.json()).results, "text/html");
                const urls = new Set([...html.querySelectorAll("[data-url]")].map(item => item.dataset.url));
                return affected.every(url => urls.has(url) === expected);
            }""", arg={
                "query": token,
                "affected": [f"/{entity.entity_kind}s/{entity.urlsafe_key}" for entity in affected],
                "expected": expected,
            }, polling=250, timeout=30_000)
        viewer.locate("[lp-search] input[name='q']").fill("")
        search = HeaderSearch(viewer)
        search.search(token)
        for entity in affected:
            result = search.panel.locator(f"[data-url='/{entity.entity_kind}s/{entity.urlsafe_key}']")
            if expected:
                expect(result).to_be_visible()
            else:
                expect(result).to_have_count(0)

    search_visible(True)
    checkbox = restrictions.locator("input[name='admin']")
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
        assert list(current.db.get("restricted_to") or []) == local_groups[entity.key]

    if form_type == "task":
        # Page membership cannot override the Task Form restriction. Each source
        # save must reconcile the existing File with both source clauses.
        checkbox.check()
        builder.save_restrictions()
        search_visible(False)
        current_page = Entities.fetch_one(page.key, request=Fetch.direct())
        current_page.groups = [group.entity]
        current_page.save()
        search_visible(False)
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
    payload = {"source_key": "form", "owner_keys": ["category"]}
    remaining = {**payload, "cursor": "next", "offset": 0}
    received = []
    queued = []

    def continue_batch(**payload):
        received.append(payload)
        return remaining

    monkeypatch.setattr(worker, "reconcile_batch", continue_batch)
    monkeypatch.setattr(worker, "enqueue", queued.append)
    response = client.post("/process/reconcile-restrictions", headers=headers, json=payload)
    assert response.status_code == 200 and response.json == {"success": True}
    assert received == [payload]
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
    form.properties.restricted_to.materialize(admin_only=True)
    form.save()
    for entity in (page, task, *files):
        assert worker.cache.redis.hget(Search[entity.kind].key(entity), "restricted_to_page_form") == b"admin"
    form.properties.restricted_to.materialize(admin_only=False)
    form.save()
    for entity in (page, task, *files):
        assert worker.cache.redis.hget(Search[entity.kind].key(entity), "restricted_to_page_form") is None


# @matrix permissions cache : concurrent-save deleted-row preserved-fields fingerprint reconciliation
@pytest.mark.parametrize("change", ["move", "task-form", "delete"])
def test_restriction_reconciliation_repairs_concurrent_changes(monkeypatch, change):
    import json

    from lagniappe.core.tools import cache as entity_cache
    from lagniappe.core.tools.auth.restrictions import RESTRICTION_SOURCES, restriction_fields
    from lagniappe.core.tools.cache import restrictions as worker
    from lagniappe.core.tools.cache.keys import Keys, Search

    token = uuid4().hex
    source = Entities.FORM.create({"name": f"Source {token}", "form-type": "page"})
    source.properties.restricted_to.materialize(admin_only=True)
    source.save()
    task_form = Entities.FORM.create({"name": f"Task Form {token}", "form-type": "task"})
    task_form.save()
    category = Entities.CATEGORY.create({"name": f"Concurrent permissions {token}"})
    category.save()
    page = Entities.PAGE.create({"name": "Original Page", "form": source, "model": category})
    destination = Entities.PAGE.create({"name": "Restricted destination", "model": category})
    destination.properties.restricted_to.materialize(admin_only=True)
    Entities.save(page, destination)
    task = Entities.TASK.create({"name": "Original Task", "page": page, "form": task_form})
    task.save()
    file = Entities.FILE.create(data={"name": "Original attachment"})
    task.files = [file]
    Entities.save(task, file)
    initial_modified = Entities.fetch_one(file.key, request=Fetch.root()).modified
    search_key = Search.file.key(file)
    client = worker.cache.redis
    queued = []
    monkeypatch.setattr(worker, "enqueue", queued.append)
    source.properties.restricted_to.materialize(admin_only=False)
    source.save()
    payload = next(payload for payload in queued if payload["source_key"] == source.urlsafe_key)

    write_projections = worker._write_projections
    update_cache = entity_cache.update
    delete_cache = entity_cache.delete
    injected = False

    def write_then_change(details, rows, projections):
        nonlocal injected
        result = write_projections(details, rows, projections)
        if injected or file.hash not in rows:
            return result
        injected = True
        current = Entities.fetch_one(file.key, request=Fetch.nested(
            because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
        ))
        if change == "task-form":
            # Another Form save changes the computed File fingerprint without
            # changing the File's durable modified value or running its worker.
            task_form.properties.restricted_to.materialize(admin_only=True)
            task_form.save()
        else:
            # Hold only this File's post-commit cache publication so verification
            # observes a real durable save/delete with the old projected row.
            with monkeypatch.context() as pending_publication:
                if change == "move":
                    pending_publication.setattr(entity_cache, "update", lambda *entities, **kwargs: update_cache(
                        *(entity for entity in entities if entity.key != file.key), **kwargs,
                    ))
                    target = Entities.fetch_one(destination.key, request=Fetch.nested(
                        because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
                    ))
                    current.move_to(target)
                    current.name = "Moved attachment"
                    current.save()
                else:
                    pending_publication.setattr(entity_cache, "delete", lambda entities: delete_cache(
                        [entity for entity in entities if entity.key != file.key],
                    ))
                    Entities.delete(current)
        assert client.hexists(Keys.ENTITY_HASHES.value, file.hash)
        return result

    monkeypatch.setattr(worker, "_write_projections", write_then_change)
    while payload is not None:
        payload = worker.reconcile_batch(**payload)
    assert injected

    current = Entities.fetch_one(file.key, request=Fetch.nested(
        because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
    ))
    if change == "delete":
        assert current is None
        assert not client.hexists(Keys.ENTITY_HASHES.value, file.hash)
        assert not client.exists(search_key)
        return

    details = json.loads(client.hget(Keys.ENTITY_HASHES.value, file.hash))
    assert details["fingerprint"] == current.fingerprint
    expected = {"page" if change == "move" else "task_form": ["admin"]}
    assert details.get("restricted_to", {}) == current.restricted_to == expected
    assert details["parent_key"] == current.owner.hash
    assert details["name"] == current.name
    fields = restriction_fields(current.restricted_to)
    for source_name in RESTRICTION_SOURCES:
        field = f"restricted_to_{source_name}"
        stored = client.hget(search_key, field)
        assert (stored.decode() if stored else None) == fields.get(field)
    assert client.hget(search_key, "name").decode() == current.name
    if change == "move":
        assert current.owner.key == destination.key
        assert current.name == "Moved attachment"
    else:
        assert current.modified == initial_modified
