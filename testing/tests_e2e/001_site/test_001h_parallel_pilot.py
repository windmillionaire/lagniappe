"""Opt-in worker stories; run through `run.py test --experiments`."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from runner.e2e_parallel import await_worker_file
from testing.definitions.user_definitions import UserDefinition
from testing.resources import Page
from testing.utility.e2e_worker import context
from testing.utility.network import expect_successful_response


pytestmark = [pytest.mark.e2e, pytest.mark.skipif(
    not os.environ.get("LAGNIAPPE_E2E_WORKER_CONTEXT"),
    reason="Explicit coordinated pilot only: run.py test --experiments",
)]


def _publish(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


# @matrix testing : parallel-e2e
# @template pages/info.html::info_form
@pytest.mark.parametrize("case", ["independent-a", "independent-b", "shared-a", "shared-b", "exclusive"])
def test_worker_page_and_task(get_user, case, results):
    record = context()
    assert record["batch"] == case
    artifacts = Path(record["artifacts"])
    root = artifacts.parent
    identity = f"pilot-{record['attempt']}-{case}"
    user = get_user(UserDefinition(name=identity, email=f"{identity}@example.test", admin=True))
    assert user.entity.is_admin and not user.entity.is_owner

    if case == "exclusive":
        records = [await_worker_file(root / name / "fixtures.json") for name in
                   ("independent-a", "independent-b", "shared-a", "shared-b")]
        assert len({row["user"] for row in records}) == 4
        assert len({row["page"] for row in records[:2]}) == 2
        for row in records:
            assert Entities.fetch_one(row["user"], request=Fetch.direct()).is_admin
            assert Entities.fetch_one(row["task"], request=Fetch.direct()).name == row["task_name"]
        entity = Entities.fetch_one(record["fixtures"]["shared_page"], request=Fetch.direct())
        page = Page(user=user)
        page.entity = entity
        user.go(page)
        expect(user.locate(Page.PAGE_DESCRIPTION)).to_have_text("Pilot saved by shared-b")
        results.record("verified_worker_fixtures", records)
        return

    if case.startswith("independent"):
        _publish(artifacts / "ready.json", {"ready": True})
        peer = "independent-b" if case == "independent-a" else "independent-a"
        await_worker_file(root / peer / "ready.json")
        if case == "independent-b":
            # A's session teardown has finished; B must still be able to read,
            # mutate, and render its own records on the same live server.
            outcome = await_worker_file(root / peer / "outcomes.json")
            assert outcome["exit_status"] == 0
        entity = Entities.PAGE.create({"name": f"Page for {identity}"})
        entity.save()
    else:
        entity = Entities.fetch_one(record["fixtures"]["shared_page"], request=Fetch.direct())
        if case == "shared-b":
            assert entity.description == "Pilot saved by shared-a"

    # Establish fixture metadata before the initial browser read. Empty-note
    # discovery currently competes with Page's whole-row form-save guard.
    entity.remember_empty_notes()
    page = Page(user=user)
    page.entity = entity
    user.go(page)
    form = page.info_form
    field = form.locator(Page.INFO_DESCRIPTION)
    control = field.locator("textarea")
    if not control.is_visible():
        field.locator("[data-role='label']").click()
    description = f"Pilot saved by {case}"
    control.fill(description)
    with expect_successful_response(user.page, method="PUT", path=f"/pages/{page.key}/update"):
        form.get_by_role("button", name="Update Page", exact=True).click()
    expect(user.locate(Page.PAGE_DESCRIPTION)).to_have_text(description)

    task_name = f"Task for {identity}"
    create = page.create_task_form
    create.locator("input[name='name']").fill(task_name)
    with expect_successful_response(user.page, method="POST", path=f"/tasks/{page.key}/create"):
        create.get_by_role("button", name="Create Task", exact=True).click()
    item = page.task_list.locator("[data-key]").filter(has_text=task_name)
    expect(item).to_have_count(1)
    task_key = item.get_attribute("data-key")
    user.reload(page)
    expect(page.task_list).to_contain_text(task_name)
    fixtures = {"user": user.entity.urlsafe_key, "page": page.key, "task": task_key,
                "task_name": task_name}
    _publish(artifacts / "fixtures.json", fixtures)
    results.record("private_worker_fixtures", fixtures)
