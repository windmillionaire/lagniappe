"""
Tests for authoritative file reconciliation after processing completes.

Verified against:
- src/script/shared/editWatcher.mjs
- src/script/widgets/fileInfo.mjs
- src/script/views/file.mjs
- lagniappe/web/routes/files/main.py
- lagniappe/web/routes/process/main.py
"""

from playwright.sync_api import expect
import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Uploads, Users
from testing.resources import File
from testing.utility.polling import trigger_poll

pytestmark = pytest.mark.e2e


# @features file
# @dimensions summarize polling status summary active-reset
def test_file_summary_completion_stages_authoritative_info_until_reset(get_user):
    user = get_user(Users.OWNER)
    file = File.upload_from_page(
        user,
        Pages.test_file_upload_page,
        Uploads.csv_file_input,
    )
    summary = "Summary loaded from authoritative file state."

    user.go(file)
    info_form = file.info_form
    info_form.evaluate("form => { form.dataset.originalRevision = 'true'; }")

    saved_file = Entities.fetch_one(file.key, request=Fetch.direct())
    saved_file.summary = summary
    saved_file.properties.summarize.enabled = True
    saved_file.properties.summarize.status = "Summary generated successfully."
    saved_file.properties.summarize.complete = True
    saved_file.save()

    with user.page.expect_response("**/files/*/info/replace"):
        trigger_poll(user)

    marker = info_form.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.get_by_role("button", name="Reset form")).to_be_visible()
    expect(info_form).to_have_attribute("data-original-revision", "true")

    marker.get_by_role("button", name="Reset form").click()

    info_form = file.info_form
    expect(info_form).not_to_have_attribute("data-original-revision", "true")
    expect(info_form.locator(file.INFO_DESCRIPTION)).to_have_value(summary)
    expect(info_form.locator("[data-role='summarize']")).to_contain_text(
        "Summary generated successfully."
    )


# @features file
# @dimensions extract polling reload text-tab active-reset
def test_file_extract_completion_prompts_reload_for_text_tab_after_reset(get_user):
    user = get_user(Users.OWNER)
    file = File.upload_from_page(
        user,
        Pages.test_file_upload_page,
        Uploads.csv_file_input,
    )

    user.go(file)
    file.info_form
    user.page.evaluate(
        """() => {
            document.querySelector("#text")?.remove();
            document
                .querySelectorAll("button[lp-show='text:active']")
                .forEach((button) => button.remove());
        }"""
    )
    expect(user.locate(file.TEXT_CONTENT)).not_to_be_attached()
    expect(user.locate(file.EXTRACT_RELOAD_NOTICE)).to_be_hidden()

    summary = "File metadata refreshed after extraction."
    saved_file = Entities.fetch_one(file.key, request=Fetch.direct())
    saved_file.summary = summary
    saved_file.properties.extract.enabled = True
    saved_file.properties.extract.status = "Text extraction complete."
    saved_file.properties.extract.complete = True
    saved_file.save()

    with user.page.expect_response("**/files/*/info/replace"):
        trigger_poll(user)

    marker = file.info_form.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.get_by_role("button", name="Reset form")).to_be_visible()
    expect(user.locate(file.EXTRACT_RELOAD_NOTICE)).to_be_hidden()

    marker.get_by_role("button", name="Reset form").click()

    expect(file.info_form.locator(file.INFO_DESCRIPTION)).to_have_value(summary)
    expect(user.locate(file.EXTRACT_RELOAD_NOTICE)).to_be_visible()
    expect(user.locate(file.EXTRACT_RELOAD_NOTICE)).to_contain_text(
        "Text extraction complete."
    )
    expect(user.locate(file.EXTRACT_RELOAD_BUTTON)).to_be_visible()
    expect(user.locate(file.TEXT_CONTENT)).not_to_be_attached()

    with user.page.expect_navigation():
        user.locate(file.EXTRACT_RELOAD_BUTTON).click()

    text_content = file.text_content
    expect(text_content).to_contain_text("alice.johnson@example.com")
