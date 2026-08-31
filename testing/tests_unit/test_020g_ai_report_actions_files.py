"""Focused AI-report characterization coverage."""

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.ai.reporting.execution import undo as report_undo
from lagniappe.core.tools.ai.reporting.execution.actions import (
    references as report_references,
)
from testing.utility.ai_report_fakes import (
    _fetch_one_from,
    _patch_fake_keys,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities


# @matrix ai-report : deterministic-run exact-id file-summary report-file-reference
# @matrix files : deterministic-run exact-id report-file-reference
@pytest.mark.unit
def test_run_report_resolves_report_file_by_exact_url_and_file_prefix(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-file-ref-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Pettis Remodeling & Garage Project", "hash": "pettis-page"},
    )
    file = _test_file("Pettis Proposal.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "File label run report",
            "hash": "runner-file-ref-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Attach and summarize a proposal document.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "attachment",
                        "type": "attach_file_to_page",
                        "data": {
                            "page": "pettis-page",
                            "file": f"/files/{file.urlsafe_key}",
                        },
                    },
                    {
                        "id": "summary",
                        "type": "summarize_file",
                        "data": {
                            "file": f"file:{file.urlsafe_key}",
                            "summary": "Proposal for the Pettis remodeling work.",
                            "retrieval_terms": ["Pettis", "remodeling"],
                        },
                    },
                ],
            },
        },
    )

    monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"pettis-page": page}),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert [action["status"] for action in result["actions"]] == [
        "complete",
        "complete",
    ]
    assert result["actions"][0]["entity"]["name"] == "Pettis Proposal"
    assert result["actions"][0]["target"]["name"] == (
        "Pettis Remodeling & Garage Project"
    )
    assert file.db["pages"] == [page.key]
    assert file.summary == "Proposal for the Pettis remodeling work."
    assert file.properties.summarize.retrieval_terms == ["Pettis", "remodeling"]




# @matrix ai-report files : deterministic-run manual-cleanup move-file undo
@pytest.mark.unit
def test_run_report_moves_file_and_records_manual_page_cleanup_with_undo(monkeypatch):
    user = _test_user("runner-file-move-owner")
    source_page = TestEntities.get(
        "PAGE",
        {"name": "Old Family Records", "hash": "old-family-records"},
    )
    target_page = TestEntities.get(
        "PAGE",
        {"name": "Family Records", "hash": "family-records"},
    )
    file = _test_file("richardson-family.pdf", "application/pdf")
    file.properties.pages.add(source_page)
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Family records cleanup",
            "hash": "runner-file-move-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Move family records to one page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "move_file",
                        "type": "move_file",
                        "data": {
                            "file": file.urlsafe_key,
                            "from_page": source_page.urlsafe_key,
                            "to_page": target_page.urlsafe_key,
                        },
                    },
                    {
                        "id": "delete_old_page",
                        "type": "delete_page",
                        "depends_on": ["move_file"],
                        "data": {"page": source_page.urlsafe_key},
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (source_page, target_page, file)
    }
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert [action["type"] for action in result["actions"]] == [
        "move_file",
        "delete_page",
    ]
    assert file.db["pages"] == [target_page.key]
    assert result["actions"][0]["moved"]["from"]["id"] == source_page.urlsafe_key
    assert result["actions"][0]["moved"]["to"]["id"] == target_page.urlsafe_key
    cleanup = result["actions"][1]
    assert cleanup["entity"]["id"] == source_page.urlsafe_key
    assert cleanup["entity"]["fingerprint"] == source_page.fingerprint
    assert cleanup["manual"]["type"] == "delete_page"
    assert cleanup["manual"]["action"] == "delete"
    assert cleanup["note"] == "Manual cleanup suggested."
    assert report.properties.result.grouped_actions[-1]["type"] == "delete_page"

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert file.db["pages"] == [source_page.key]
    assert undo["actions"][0]["type"] == "delete_page"
    assert undo["actions"][0]["note"] == (
        "Manual cleanup suggestion; nothing was executed."
    )
    assert undo["actions"][1]["type"] == "move_file"
    assert undo["actions"][1]["note"] == "Restored previous file attachment."
    assert saved




# @matrix ai-report files : deterministic-run move-file readable-file-fallback
@pytest.mark.unit
def test_run_report_moves_file_by_exact_source_attachment_name(monkeypatch):
    user = _test_user("runner-file-move-name-owner")
    source_page = TestEntities.get(
        "PAGE",
        {"name": "Old Family Records", "hash": "old-family-records-by-name"},
    )
    target_page = TestEntities.get(
        "PAGE",
        {"name": "Family Records", "hash": "family-records-by-name"},
    )
    file = _test_file("richardson-family.pdf", "application/pdf")
    file.properties.pages.add(source_page)
    source_page.properties.files._value = [file]
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Family records cleanup",
            "hash": "runner-file-move-by-name-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Move family records to one page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "type": "move_file",
                        "data": {
                            "file": "richardson-family",
                            "display_name": "richardson-family",
                            "from_page": source_page.urlsafe_key,
                            "to_page": target_page.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (source_page, target_page)
    }
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["type"] == "move_file"
    assert file.db["pages"] == [target_page.key]
    assert result["actions"][0]["moved"]["from"]["id"] == source_page.urlsafe_key
    assert result["actions"][0]["moved"]["to"]["id"] == target_page.urlsafe_key
    assert saved




# @matrix ai-report files : attachment exact-page-name page-reference repair
@pytest.mark.unit
def test_run_report_resolves_attachment_page_by_exact_page_name_when_reference_missing(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("attachment-page-name-repair-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Fixtures & Materials", "hash": "fixtures-materials-page"},
    )
    file = _test_file("368 Pettis - Grading & Drainage.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Attachment page name repair report",
            "hash": "attachment-page-name-repair-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Attach a plan set to an existing page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "attach_grading_drainage_plan",
                        "type": "attach_file_to_page",
                        "display_label": "Attach Grading & Drainage Plan",
                        "data": {
                            "page": "almost-the-right-page-key",
                            "page_name": "Fixtures & Materials",
                            "file": file.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page}),
    )
    monkeypatch.setattr(
        report_references.cache,
        "search",
        lambda *args, **kwargs: (
            [
                {
                    "id": page.urlsafe_key,
                    "kind": "page",
                    "name": "Fixtures & Materials",
                }
            ],
            1,
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["target"]["id"] == page.urlsafe_key
    assert result["actions"][0]["entity"]["id"] == file.urlsafe_key
    assert file.db["pages"] == [page.key]




# @matrix ai-report : attachments continue deterministic-run partial-result recoverable
@pytest.mark.unit
def test_run_report_marks_missing_file_placements_failed_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("missing-file-reference-owner")
    file = _test_file("landscape-card.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Missing file reference report",
            "hash": "missing-file-reference-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Create a page and attach available files.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {"name": "Landscape Nirvana"},
                    },
                    {
                        "id": "attach_card",
                        "type": "attach_file_to_page",
                        "display_label": "Attach Landscape Nirvana Business Card",
                        "data": {
                            "page_action": "page",
                            "file": "landscape-card.pdf",
                        },
                    },
                    {
                        "id": "attach_missing",
                        "type": "attach_file_to_page",
                        "display_label": "Attach Pettis Landscape Plan Set",
                        "data": {
                            "page_action": "page",
                            "file": "almost-the-right-file-key",
                        },
                    },
                    {
                        "id": "attach_missing_target",
                        "type": "attach_file_to_page",
                        "display_label": "Attach Grading & Drainage Plan",
                        "data": {
                            "page": "almost-the-right-page-key",
                            "file": "landscape-card.pdf",
                        },
                    },
                    {
                        "id": "record_downpayment_task",
                        "type": "create_task",
                        "display_label": "Record Initial Project Down Payment",
                        "data": {
                            "name": "Down Payment: Landscape Renovation",
                            "page_action": "page",
                            "completed_on": "2021-10-27",
                            "description": (
                                "Initial project deposit of $5,000 paid to "
                                "commence landscape construction."
                            ),
                        },
                    },
                    {
                        "id": "summary",
                        "type": "summarize_file",
                        "data": {
                            "file": "landscape-card.pdf",
                            "summary": "Landscape contractor business card.",
                        },
                    },
                ],
            },
        },
    )
    saved = []
    captured = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities, "fetch_one", lambda key, request: None
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY", {"name": "Uncategorized Pages", "hash": "uncategorized"}
        ),
    )
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "failed"
    assert result["failed_at"] == 3
    assert report.status == "failed"
    assert report.error.startswith("One or more files could not be attached")
    assert [action["status"] for action in result["actions"]] == [
        "complete",
        "complete",
        "failed",
        "failed",
        "complete",
        "complete",
    ]
    missing_reference = result["actions"][2]
    assert missing_reference["error"] == "Referenced report file was not found."
    assert missing_reference["note"] == "This required file placement was not completed."
    missing_target = result["actions"][3]
    assert missing_target["error"] == (
        "Referenced entity not found: almost-the-right-page-key"
    )
    assert missing_target["note"] == "This required file placement was not completed."
    completed_without_file = result["actions"][4]
    assert completed_without_file["type"] == "create_task"
    assert completed_without_file["entity"]["kind"] == "task"
    assert "attachments" not in completed_without_file
    assert completed_without_file["note"] == "Recorded as the task's current completion."
    pages = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "page"
    ]
    completed_tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    ]
    assert file.db["pages"] == [pages[0].key]
    assert len(completed_tasks) == 1
    assert completed_tasks[0].completed is True
    assert completed_tasks[0].files == []
    assert file.summary == "Landscape contractor business card."
    assert len(captured) == 2
    assert all(
        event["context"]["ai_report_runner"]["operation"]
        == "required_file_placement_failed"
        for event in captured
    )




# @matrix ai-report : attachments deterministic-run partial-result validation
@pytest.mark.unit
def test_run_report_rejects_category_used_as_attachment_page(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("category-as-page-owner")
    category = TestEntities.get(
        "CATEGORY", {"name": "Homeschool", "hash": "homeschool-category"}
    )
    file = _test_file("attendanceform.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Category used as page report",
            "hash": "category-used-as-page-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "File the attendance form.",
                "confidence": 0.8,
                "actions": [
                    {
                        "id": "attach_attendance",
                        "type": "attach_file_to_page",
                        "display_label": "Attach attendanceform",
                        "data": {
                            "page": category.urlsafe_key,
                            "page_name": category.name,
                            "file": file.urlsafe_key,
                        },
                    }
                ],
            },
        },
    )
    captured = []

    monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({category.urlsafe_key: category}),
    )
    monkeypatch.setattr(
        report_references.cache,
        "search",
        lambda *args, **kwargs: ([], 0),
    )
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(str(error)),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "failed"
    assert report.status == "failed"
    assert result["actions"][0]["status"] == "failed"
    assert result["actions"][0]["error"] == (
        "Homeschool is a category, not a page."
    )
    assert captured == ["Homeschool is a category, not a page."]
    assert file.db.get("pages") in (None, [])
