"""E2E coverage for offline PageInfo submissions and replay."""

from dataclasses import replace
import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Users
from testing.elements import Tabs
from testing.resources import Page
from testing.utility import expect_successful_response, wait_for_offline_mutations


pytestmark = pytest.mark.e2e

OFFLINE_INDICATOR = "[data-role='offline']"


def _unique(label):
    return f"{label} {uuid4().hex[:8]}"


def _main_submit(form):
    return form.locator("button[type='submit']:not([data-role])")


def _fill_form_element(form, selector, value):
    field = form.locator(selector)
    field_input = field.locator("input, textarea").first
    if not field_input.is_visible():
        field.locator("[data-role='label']").click()
    expect(field_input).to_be_visible()
    field_input.fill(value)


# @pairs offline:queue-submit offline:replay offline:notification
# @pairs offline:dropdown-refresh offline:target-link pages:lp-offline
# @template pages/info.html::info_form
# @template pages/document.html::document_settings
# @template notifications.html::list
def test_page_info_lp_offline_submit_replays_and_notifies(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = owner.go(Pages.test_offline_sync_form_page)
    mutation_id = f"update:page:{page.key}"
    updated_name = _unique("Offline page info")

    info_form = page.info_form
    expect(_main_submit(info_form)).to_contain_text("Update Page")

    page.document_tab
    owner.locate(Page.DOCUMENT_SETTINGS_TOGGLE).click()
    document_settings = owner.locate(Page.DOCUMENT_SETTINGS_FORM)
    expect(document_settings).to_be_visible()

    with browser_failures.expect_offline(owner):
        owner.offline = True
        expect(owner.locate(OFFLINE_INDICATOR)).to_be_visible()

        blocked_submit = _main_submit(document_settings)
        expect(blocked_submit).to_be_disabled()
        expect(blocked_submit).to_contain_text("Server Offline")
        expect(blocked_submit.locator("[data-icon='offline']")).to_be_visible()
        expect(blocked_submit).to_have_class(re.compile("opacity-75"))

        Tabs(owner).info
        info_form = page.info_form
        _fill_form_element(info_form, Page.INFO_NAME, updated_name)
        owner.page.keyboard.press("Tab")
        info_submit = _main_submit(info_form)
        expect(info_submit.locator("[data-icon='builder.unsaved']")).to_be_visible()
        info_submit.click()
        expect(info_submit).to_contain_text("Queued Sync")
        expect(info_submit.locator("[data-icon='offline']")).to_be_visible()
        wait_for_offline_mutations(owner, record_id=mutation_id, exact=1)

    with owner.page.expect_response("**/pages/*/update", timeout=15000):
        owner.offline = False
    wait_for_offline_mutations(owner, record_id=mutation_id, exact=0)
    expect(info_submit.locator("[data-icon='offline']")).to_have_count(0)
    expect(info_submit).to_contain_text("Update Page")

    saved_page = Entities.fetch_one(page.key, request=Fetch.direct())
    assert saved_page.name == updated_name

    notifications = owner.locate("[data-role='notifications']")
    expect(notifications).to_be_visible(timeout=15000)

    notifications.click()
    option = owner.page.locator(
        "[role='listbox'][data-visible='true'] [role='option']"
    ).filter(has_text="Offline page update synced.")
    expect(option).to_be_visible()
    expect(option.locator("[data-role='target']")).to_contain_text(updated_name)

    with owner.page.expect_response("**/l/activity/*"):
        option.locator("[data-action='delete-notification']").click()
    expect(option).not_to_be_attached()


# @pairs offline:queue-submit offline:reload offline:replay-reconciliation
# @pairs pages:lp-offline edited-entity-notice:replayed-response
# @pairs polling:freshness
# @template pages/info.html::info_form
def test_page_info_replay_reconciles_after_reload(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = owner.go(Pages.test_offline_sync_form_page)
    page = page.reload()
    mutation_id = f"update:page:{page.key}"
    updated_submission = _unique("Reloaded offline submission")

    info_form = page.info_form
    submission = info_form.locator("[id^='sync-text-renderer-']")
    original_submission = submission.locator("input").input_value()
    _fill_form_element(info_form, "[id^='sync-text-renderer-']", updated_submission)

    with browser_failures.expect_http_error(
        owner,
        status=503,
        path="/analytics/track",
    ):
        with browser_failures.expect_offline(
            owner,
            ping_count=2,
            max_ping_count=3,
        ):
            owner.offline = True
            info_submit = _main_submit(info_form)
            info_submit.click()
            expect(info_submit).to_contain_text("Queued Sync")
            wait_for_offline_mutations(owner, record_id=mutation_id, exact=1)

            page = page.reload()
            expect(owner.locate(OFFLINE_INDICATOR)).to_be_visible()

            current_form = page.info_form
            current_submission = current_form.locator("[id^='sync-text-renderer-']")
            expect(current_submission.locator("input")).to_have_value(
                original_submission
            )
            current_submit = _main_submit(current_form)
            expect(current_submit).to_contain_text("Update Page")
            expect(current_submit.locator("[data-icon='offline']")).to_have_count(0)

            with owner.page.expect_response("**/pages/*/update", timeout=15000):
                owner.offline = False
            wait_for_offline_mutations(owner, record_id=mutation_id, exact=0)

    marker = current_form.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.locator("[data-role='edited-message']")).to_contain_text(
        "Saved values changed elsewhere"
    )
    marker.locator("[data-role='edited-reset']").click()
    modal = owner.page.locator("#modal")
    expect(modal).to_be_visible()
    expect(modal.get_by_text(updated_submission, exact=True)).to_be_visible()
    saved_choice = modal.locator("[data-revision-source='server']").filter(
        has_text=updated_submission
    )
    expect(saved_choice).to_have_attribute("aria-checked", "true")
    modal.get_by_role("button", name="Update values").click()
    expect(modal).not_to_be_attached()
    expect(current_form.locator("input[name='sync-text']")).to_have_value(
        updated_submission
    )

    saved_page = Entities.fetch_one(page.key, request=Fetch.direct())
    assert saved_page.properties.submission.form_value["sync-text"] == (
        updated_submission
    )


# @pairs forms:submission-choice forms:queued-conflict
# @template controls.html::edited_marker
# @template pages/info.html::info_form
def test_offline_submission_conflict_keeps_queue_until_choice(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    page = Page(
        user=owner,
        definition=replace(
            Pages.test_offline_sync_form_page.value.definition,
            name=_unique("Offline conflict page"),
        ),
    ).create()
    page = owner.go(page)
    mutation_id = f"update:page:{page.key}"
    queued_value = _unique("Queued conflict value")
    saved_value = _unique("Intervening saved value")

    info = page.info_form
    _fill_form_element(info, "[id^='sync-text-renderer-']", queued_value)
    with browser_failures.expect_offline(owner):
        owner.offline = True
        _main_submit(info).click()
        expect(_main_submit(info)).to_contain_text("Queued Sync")
        wait_for_offline_mutations(owner, record_id=mutation_id, exact=1)

    collaborator.page.goto(page.url)
    expect(collaborator.locate("[lp-view]")).to_have_attribute("initialized", "")
    collaborator_info = collaborator.locate(Page.INFO_FORM)
    expect(collaborator_info).to_have_attribute("rendered", "")
    _fill_form_element(
        collaborator_info,
        "[id^='sync-text-renderer-']",
        saved_value,
    )
    with expect_successful_response(
        collaborator.page,
        method="PUT",
        path=f"/pages/{page.key}/update",
        entity_key=page.key,
    ):
        _main_submit(collaborator_info).click()
    expect(collaborator_info.locator("input[name='sync-text']")).to_have_value(
        saved_value
    )

    with owner.page.expect_response("**/pages/*/update", timeout=15000):
        owner.offline = False

    marker = info.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.locator("[data-role='edited-message']")).to_contain_text(
        "Saved values changed elsewhere"
    )
    wait_for_offline_mutations(owner, record_id=mutation_id, exact=1)

    marker.locator("[data-role='edited-reset']").click()
    modal = owner.page.locator("#modal")
    expect(modal).to_be_visible()
    expect(modal.get_by_text(queued_value, exact=True)).to_be_visible()
    expect(modal.get_by_text(saved_value, exact=True)).to_be_visible()
    saved_choice = modal.locator("[data-revision-source='server']").filter(
        has_text=saved_value
    )
    expect(saved_choice).to_have_attribute("aria-checked", "true")
    modal.get_by_role("button", name="Update values").click()

    expect(modal).not_to_be_attached()
    wait_for_offline_mutations(owner, record_id=mutation_id, exact=0)
    expect(info.locator("input[name='sync-text']")).to_have_value(saved_value)
