"""Server contracts for document-only sync and marker-owned form operations."""

from copy import deepcopy
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Tasks, Users
from testing.utility import expect_poll_result, expect_successful_response


pytestmark = pytest.mark.e2e


# @pairs sync:document-only forms:no-live-sync
def test_live_sync_rejects_form_widget_payloads(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    owner.go(Pages.test_sync_form_page)

    with browser_failures.expect_http_error(owner, status=422, path="/sync"):
        result = owner.page.evaluate(
            """async () => {
                const response = await fetch("/sync", {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": document.getElementById("token")?.value,
                        "X-Lagniappe-Request": "true",
                    },
                    body: JSON.stringify({
                        client_id: "form-contract-test",
                        updates: [{
                            key: "page-key",
                            sync_id: "page-hash:form-hash:form",
                            update: "encoded-state",
                            save: false,
                        }],
                    }),
                });
                return {status: response.status, text: await response.text()};
            }"""
        )

    assert result["status"] == 422
    assert "Only identified document widgets may use live sync" in result["text"]


# @pairs offline:replay-precondition forms:conflict-review tasks:no-mutation
def test_task_offline_replay_rejects_a_stale_origin_fingerprint(get_user):
    owner = get_user(Users.OWNER)
    task = Tasks.test_task_revision_review.get(owner)
    owner.go(task)
    current = Entities.fetch_one(
        task.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    original_name = current.name
    original_fingerprint = current.fingerprint
    path = f"/tasks/{task.key}/update"

    result = owner.page.evaluate(
        """async ({path, name}) => {
            const body = new FormData();
            body.set("offline", "True");
            body.set("offline-fingerprint", "stale-origin-fingerprint");
            body.set("name", name);
            const response = await fetch(path, {
                method: "PUT",
                credentials: "include",
                headers: {
                    "X-CSRFToken": document.getElementById("token")?.value,
                    "X-Lagniappe-Request": "true",
                },
                body,
            });
            return {status: response.status, data: await response.json()};
        }""",
        {"path": path, "name": "This stale replay must not be saved"},
    )

    assert result["status"] == 200
    assert result["data"]["conflict"] is True
    saved = Entities.fetch_one(
        task.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    assert saved.name == original_name
    assert saved.fingerprint == original_fingerprint


def _fill_form_field(form, field_prefix, value):
    field = form.locator(f"[id^='{field_prefix}-']")
    field.locator("[data-role='label']").click()
    field.locator("input, textarea").first.fill(value)


# @pairs edited-entity-notice:submission-choice forms:submission-choice
# @pairs forms:latest-schema forms:readonly-preview
# @pairs reconnect-refresh:dirty-form-preservation form-schema:notice
# @template controls.html::edited_marker
# @template pages/info.html::info_form
def test_form_submission_reconciliation_uses_latest_schema(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    page = owner.go(Pages.test_offline_sync_form_page)
    first = owner.page
    info = page.info_form
    suffix = uuid4().hex[:8]
    local_value = f"Local value awaiting reconciliation {suffix}"
    server_value = f"Saved value from another tab {suffix}"
    added_value = f"Value from the new schema field {suffix}"
    added_id = f"reconcile-added-field-{suffix}"

    _fill_form_field(info, "sync-text-renderer", local_value)
    first.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
    with browser_failures.expect_offline(owner):
        owner.offline = True
        expect(owner.locate("[data-role='offline']")).to_be_visible()

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

        other = collaborator.page
        other.goto(first.url)
        other_info = other.locator("[data-widget='PageInfo']")
        expect(other_info).to_have_attribute("rendered", "")
        _fill_form_field(other_info, "sync-text-renderer", server_value)
        _fill_form_field(other_info, added_id, added_value)
        with expect_successful_response(
            other,
            method="PUT",
            path=f"/pages/{page.key}/update",
            entity_key=page.key,
        ):
            other_info.locator('button[type="submit"]:not([data-role])').click()

        replacement_requests = []

        def record_replacement(request):
            if request.method == "GET" and request.url.endswith(
                f"/pages/{page.key}/info/replace"
            ):
                replacement_requests.append(request)

        first.on("request", record_replacement)
        try:
            with expect_poll_result(
                first,
                subscription_id=f"view:entity:{page.key}",
            ):
                with expect_successful_response(
                    first,
                    method="GET",
                    path=f"/pages/{page.key}/info/replace",
                    entity_key=page.key,
                ):
                    owner.offline = False
        finally:
            first.remove_listener("request", record_replacement)

        assert len(replacement_requests) == 1
        expect(owner.locate("[data-role='offline']")).to_be_hidden()

        info = first.locator("[data-widget='PageInfo']")
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
                "button[type='submit']:not([data-role]) [data-icon='builder.unsaved']"
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
    with expect_poll_result(
        owner.page,
        subscription_id=f"edit:{task.key}",
        status=None,
        timeout=25000,
    ):
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
        with expect_poll_result(
            owner.page,
            subscription_id=f"edit:{task.key}",
            timeout=25000,
        ):
            saved_task.form_submission(submission)
            saved_task.save()

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
