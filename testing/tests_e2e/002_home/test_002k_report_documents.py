"""Reviewed document appends reach an open editor and undo without a reset."""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.document_crdt import append_fragment
from lagniappe.core.tools.database import assets as database_assets, get as database_get
from testing.definitions import Users
from testing.resources import Page, Report

pytestmark = pytest.mark.e2e


# @source lagniappe/core/tools/ai/reporting/execution/actions/documents.py::_append_page_document
# @source lagniappe/core/tools/ai/reporting/execution/actions/documents.py::_undo_page_document
# @source lagniappe/web/routes/home/sync.py::sync
# @source lagniappe/core/mixins/assets.py::AssetMixin.copy_asset
# @matrix ai-report editor sync : document append browser-review persistence source-attribution undo
# @matrix asset-storage : copy metadata visibility
# @template tools/report.html::proposal_action_item
def test_reviewed_document_append_updates_open_editor_and_undo(get_user):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    actor = Entities.USER.load(owner.email)
    suffix = uuid4().hex[:8]
    category = Entities.CATEGORY.create({"name": f"test-document-category-{suffix}"})
    page = Entities.PAGE.create(
        {"name": f"test-document-page-{suffix}", "model": category}
    )
    html = "<p>Keep the original notes.</p>"
    snapshot, _ = append_fragment(None, html, "seed")
    page.properties.document.save(html=html, ydoc=snapshot)
    Entities.save(category, page)
    before_document = page.get_asset("document")
    before_snapshot = page.get_asset("snapshot")
    report = Entities.REPORT.create(
        {
            "name": f"test-document-append-{suffix}",
            "parent": actor,
            "user": actor,
            "tool": "organize",
            "origin": "api",
            "status": "ready",
            "pending": False,
            "agent_manifest": {"source": "remote_mcp"},
            "proposal": {
                "summary": "Append the requested implementation note.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "append",
                        "type": "append_page_document",
                        "data": {
                            "page": page.urlsafe_key,
                            "document_markdown": "Added **reviewed** notes.",
                        },
                    }
                ],
            },
        }
    )
    Entities.save(report)
    collaborator_page = Page(user=collaborator)
    collaborator_page.entity = page
    collaborator.go(collaborator_page)
    editor = collaborator_page.editor
    expect(editor.text_entry).to_contain_text("Keep the original notes.")
    report_page = owner.go(Report.for_entity(owner, report))
    expect(report_page.proposal_actions).to_contain_text("Added **reviewed** notes.")
    report_page.execute()
    expect(owner.page.get_by_text("Work done.")).to_be_visible()
    expect(report_page.result).to_contain_text("Page Document Updated:")
    expect(
        report_page.result.get_by_role("link", name=page.name, exact=True)
    ).to_have_attribute("href", f"/pages/{page.urlsafe_key}")
    expect(editor.text_entry).to_contain_text("Added reviewed notes.", timeout=15000)
    expect(editor.text_entry).to_contain_text("Keep the original notes.")
    expect(editor.text_entry.locator("blockquote")).to_contain_text("UTC · Remote MCP")
    saved = Entities.fetch_one(page.urlsafe_key, request=Fetch.direct())
    assert "Added <strong>reviewed</strong> notes." in saved.properties.document.html
    assert saved.properties.document.ydoc
    versions = Entities.fetch(*database_get.document_history(saved), request=Fetch.root())
    assert len(versions) == 1
    assert versions[0].pinned and versions[0].name.startswith("Before report append")
    version_asset = versions[0].get_asset("document")
    assert version_asset.get() == html
    assert version_asset.generation and version_asset.path != before_document.path
    assert version_asset.visibility == before_document.visibility
    # The old live pair is retired, but a generation-pinned in-flight reader
    # still works under the configured backup/versioning policy.
    for old_asset in (before_document, before_snapshot):
        assert not database_assets.DATA.private_bucket.blob(old_asset.path).exists()
    assert before_document.get() == html
    assert before_snapshot.get() == snapshot
    with owner.page.expect_response("**/tools/reports/*/undo"):
        owner.page.get_by_role("button", name="Undo Report").click()
    expect(owner.page.get_by_text("Work undone.")).to_be_visible(timeout=10000)
    expect(editor.text_entry).not_to_contain_text(
        "Added reviewed notes.", timeout=15000
    )
    expect(editor.text_entry).to_contain_text("Keep the original notes.")
    collaborator.go(collaborator_page)
    expect(collaborator_page.editor.text_entry).to_have_text("Keep the original notes.")
