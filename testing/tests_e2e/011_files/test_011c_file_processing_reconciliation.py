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
from uuid import uuid4

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Uploads, Users
from testing.definitions.page_definitions import PageDefinition
from testing.resources import File, Page
from testing.utility.network import expect_successful_response
from testing.utility.polling import expect_poll_result

pytestmark = pytest.mark.e2e


# @matrix file : active-reset polling status summarize summary
def test_file_summary_completion_stages_authoritative_info_until_reset(
    get_user,
    browser_failures,
):
    user = get_user(Users.OWNER)
    suffix = uuid4().hex
    category = Entities.CATEGORY.create(
        {
            "name": f"File Reconciliation Category {suffix}",
        }
    )
    category.save()
    page_entity = Entities.PAGE.create(
        {
            "name": f"File Reconciliation Page {suffix}",
            "model": category,
        }
    )
    page_entity.save()
    page = Page(
        user=user,
        definition=PageDefinition(
            name=page_entity.name,
            category=Pages.test_file_upload_page.value.definition.category,
        ),
    )
    page.entity = page_entity
    file = File.upload_from_page(
        user,
        page,
        Uploads.csv_file_input,
    )
    summary = "Summary loaded from authoritative file state."

    user.go(file)
    info_form = file.info_form
    user.page.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
    with browser_failures.expect_offline(user):
        user.offline = True
        expect(user.locate("[data-role='offline']")).to_be_visible()

    saved_file = Entities.fetch_one(
        file.key,
        request=Fetch.nested(because=FetchReason.CASCADE_SAVE_REQUIREMENTS),
    )
    saved_file.summary = summary
    saved_file.properties.summarize.enabled = True
    saved_file.properties.summarize.status = "Summary generated successfully."
    saved_file.properties.summarize.complete = True
    saved_file.save()

    with expect_poll_result(
        user.page,
        subscription_id=f"view:entity:{file.key}",
    ):
        with expect_successful_response(
            user.page,
            method="GET",
            path=f"/files/{file.key}/info/replace",
            entity_key=file.key,
        ):
            user.offline = False

    info_form = file.info_form
    marker = info_form.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.get_by_role("button", name="Reset form")).to_be_visible()

    marker.get_by_role("button", name="Reset form").click()

    info_form = file.info_form
    expect(info_form.locator(file.INFO_DESCRIPTION)).to_have_value(summary)
    expect(info_form.locator("[data-role='summarize']")).to_contain_text(
        "Summary generated successfully."
    )
