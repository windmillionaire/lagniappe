"""Server contracts for document-only sync and marker-owned form operations."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.web.routes.home import poll as poll_routes
from lagniappe.web.routes.home import sync as sync_routes
from lagniappe.web.routes.pages import main as page_routes
from lagniappe.web.routes.tasks import main as task_routes
from testing.definitions import Pages, Tasks, Users


pytestmark = pytest.mark.e2e


# @pairs sync:document-only forms:no-live-sync
def test_live_sync_rejects_form_widget_payloads():
    error = sync_routes._validate_sync_payload(
        {
            "client_id": "form-contract-test",
            "updates": [
                {
                    "key": "page-key",
                    "sync_id": "page-hash:form-hash:form",
                    "update": {"field": "draft"},
                }
            ]
        }
    )
    assert error == "Only identified document widgets may use live sync."
    assert (
        sync_routes._validate_sync_payload(
            {
                "client_id": "document-contract-test",
                "updates": [
                    {
                        "key": "page-key",
                        "sync_id": "page-hash:document",
                        "ydoc": "encoded-state",
                        "save": False,
                    }
                ]
            }
        )
        is None
    )


# @pairs deferred-jobs:form-lock polling:revision
def test_poll_form_lock_revision_is_independent_of_entity_fingerprint(monkeypatch):
    class Page:
        urlsafe_key = "page-key"
        fingerprint = "entity-fingerprint"

        def allowed(self, action, user=None):
            return user == "editor"

    monkeypatch.setattr(poll_routes, "current_user", "editor")
    entity = Page()
    active_locks = {
        entity.urlsafe_key: (
            SimpleNamespace(scope="form-autofill"),
            SimpleNamespace(urlsafe_key="operation-key", status_revision=6),
        )
    }
    descriptor = {
        "id": "form-lock:page-key",
        "type": "form-lock",
        "key": entity.urlsafe_key,
        "revision": "operation-key:5",
    }

    assert poll_routes._lock_result(descriptor, entity, active_locks) == {
        "id": "form-lock:page-key",
        "type": "form-lock",
        "status": "changed",
        "revision": "operation-key:6",
        "poll_after_ms": 15000,
        "payload": {
            "key": "page-key",
            "locked": True,
            "scope": "form-autofill",
            "operation": "operation-key",
            "revision": 6,
        },
    }

    entity.fingerprint = "changed-entity-fingerprint"
    assert poll_routes._lock_result(
        {**descriptor, "revision": "operation-key:6"},
        entity,
        active_locks,
    ) == {
        "id": "form-lock:page-key",
        "type": "form-lock",
        "status": "unchanged",
        "revision": "operation-key:6",
        "poll_after_ms": 15000,
    }


# @pairs offline:replay-precondition forms:conflict-review
def test_offline_form_replay_uses_originating_entity_fingerprint():
    entity = SimpleNamespace(fingerprint="current")
    stale = {
        "offline": "True",
        "offline-fingerprint": "originating",
    }
    current = {
        "offline": "True",
        "offline-fingerprint": "current",
    }

    for conflicts in (
        page_routes._offline_replay_conflicts,
        task_routes._offline_replay_conflicts,
    ):
        assert conflicts(entity, stale) is True
        assert conflicts(entity, current) is False
        assert conflicts(entity, {"offline-fingerprint": "originating"}) is False


def _fill_form_field(form, field_prefix, value):
    field = form.locator(f"[id^='{field_prefix}-']")
    field.locator("[data-role='label']").click()
    field.locator("input, textarea").first.fill(value)


# @pairs edited-entity-notice:submission-choice forms:submission-choice
# @pairs forms:latest-schema forms:readonly-preview
# @pairs reconnect-refresh:dirty-form-preservation form-schema:notice
# @template controls.html::edited_marker
# @template pages/info.html::info_form
def test_form_submission_reconciliation_uses_latest_schema(get_user):
    owner = get_user(Users.OWNER)
    page = owner.go(Pages.test_offline_sync_form_page)
    first = owner.page
    info = page.info_form
    suffix = uuid4().hex[:8]
    local_value = f"Local value awaiting reconciliation {suffix}"
    server_value = f"Saved value from another tab {suffix}"
    added_value = f"Value from the new schema field {suffix}"
    added_id = f"reconcile-added-field-{suffix}"

    _fill_form_field(info, "sync-text-renderer", local_value)
    first.evaluate(
        "() => document.querySelector('[lp-view]')._lp_view.sync({ hidden: true })"
    )

    form = page.entity.form
    original_schema = deepcopy(form.schema)
    other = None
    try:
        form.schema = [
            *original_schema,
            {
                "id": added_id,
                "type": "input",
                "input": "text",
                "title": "Reconciliation Added Field",
            },
        ]
        form.save()

        other = first.context.new_page()
        other.goto(first.url)
        other_info = other.locator("[data-widget='PageInfo']")
        expect(other_info).to_have_attribute("rendered", "")
        _fill_form_field(other_info, "sync-text-renderer", server_value)
        _fill_form_field(other_info, added_id, added_value)
        with other.expect_response("**/pages/*/update"):
            other_info.locator(
                'button[type="submit"]:not([data-role])'
            ).click()

        first.bring_to_front()
        first.evaluate(
            """async () => {
                const view = document.querySelector("[lp-view]")._lp_view;
                await view.sync({ hidden: false });
                await view.EditWatcher.check();
            }"""
        )

        marker = info.locator("[lp-edited-marker]")
        expect(marker).to_be_visible()
        expect(marker.locator("[data-role='edited-message']")).to_contain_text(
            "fields and saved values changed"
        )
        marker.locator("[data-role='edited-reset']").click()

        modal = first.locator("#modal")
        expect(modal).to_be_visible()
        expect(modal).to_have_attribute("data-kind", "page")
        expect(modal.get_by_text(local_value, exact=True)).to_be_visible()
        expect(modal.get_by_text(server_value, exact=True)).to_be_visible()
        expect(modal.get_by_text("Schema update:")).to_contain_text("1 added")
        expect(modal.locator("[role='radiogroup']")).to_have_count(1)
        expect(
            modal.get_by_text("Reconciliation Added Field", exact=True)
        ).to_have_count(0)

        local_choice = modal.locator("[data-revision-source='local']").filter(
            has_text=local_value
        )
        saved_choice = modal.locator("[data-revision-source='server']").filter(
            has_text=server_value
        )
        expect(saved_choice).to_have_attribute("aria-checked", "true")
        expect(local_choice).to_have_attribute("aria-checked", "false")

        modal.get_by_role("button", name="Close").click()
        expect(modal).not_to_be_attached()
        expect(info.locator("input[name='sync-text']")).to_have_value(local_value)
        expect(marker).to_be_visible()

        marker.locator("[data-role='edited-reset']").click()
        modal = first.locator("#modal")
        expect(modal).to_be_visible()
        local_choice = modal.locator("[data-revision-source='local']").filter(
            has_text=local_value
        )
        saved_choice = modal.locator("[data-revision-source='server']").filter(
            has_text=server_value
        )
        local_choice.click()
        expect(local_choice).to_have_attribute("aria-checked", "true")
        expect(saved_choice).to_have_attribute("aria-checked", "false")

        modal.get_by_role("button", name="Update values").click()
        expect(modal).not_to_be_attached()

        info = first.locator("[data-widget='PageInfo']")
        expect(info.locator("input[name='sync-text']")).to_have_value(local_value)
        expect(info.locator(f"input[name='{added_id}']")).to_have_value(added_value)
        expect(
            info.locator(
                "button[type='submit']:not([data-role]) "
                "[data-icon='builder.unsaved']"
            )
        ).to_be_visible()
    finally:
        if other:
            other.close()
        form.schema = original_schema
        form.save()


# @pair tasks:active-form-preservation
# @template controls.html::edited_marker
# @template pages/tasks.html::task_form
def test_task_collection_refresh_preserves_active_form_for_revision_review(
    get_user,
):
    owner = get_user(Users.OWNER)
    task = Tasks.test_task_revision_review.get(owner)
    owner.go(task)
    task_form = task.task_form
    field_id = "input-textab12"
    field = task_form.locator(f"input[name='{field_id}']")
    local_value = field.input_value()
    saved_value = f"Saved task value {uuid4().hex[:8]}"
    saved_task = Entities.fetch_one(
        task.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    try:
        submission = dict(saved_task.properties.submission.form_value)
        submission[field_id] = saved_value
        saved_task.form_submission(submission)
        saved_task.save()

        owner.page.evaluate(
            """async () => {
                const view = document.querySelector("[lp-view]")._lp_view;
                await view.PollingCoordinator.trigger();
            }"""
        )

        task_form = task.element.locator(task.TASK_FORM)
        marker = task_form.locator("[lp-edited-marker]")
        expect(marker).to_be_visible()
        expect(field).to_have_value(local_value)
        marker.locator("[data-role='edited-reset']").click()

        modal = owner.page.locator("#modal")
        expect(modal).to_be_visible()
        expect(
            modal.locator("[data-revision-source='local']").get_by_text(
                local_value, exact=True
            )
        ).to_be_visible()
        expect(
            modal.locator("[data-revision-source='server']").get_by_text(
                saved_value, exact=True
            )
        ).to_be_visible()
    finally:
        restored = dict(saved_task.properties.submission.form_value)
        restored[field_id] = local_value
        saved_task.form_submission(restored)
        saved_task.save()
