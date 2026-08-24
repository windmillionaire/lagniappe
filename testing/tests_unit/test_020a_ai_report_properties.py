"""Focused AI-report characterization coverage."""

import pytest

from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.entities.ai_report import AIReport
from lagniappe.core.tools.ai.reporting.contracts.actions import ALLOWED_ACTIONS
from lagniappe.core.tools.ai.reporting.display.registry import ACTION_DISPLAY_REGISTRY
from testing.utility.ai_report_fakes import (
    _patch_fake_keys,
    _permissioned_user,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities


# @features ai-report permissions
# @dimensions creator owner unrelated-user delete view
@pytest.mark.unit
def test_ai_report_permissions_follow_creator_ownership():
    creator = _permissioned_user("report-creator", {})
    unrelated = _permissioned_user("unrelated-report-user", {})
    owner = _test_user("report-site-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Creator-owned report",
            "hash": "creator-owned-report",
            "parent": creator,
            "user": creator,
        },
    )

    assert report.allowed(Action.VIEW, user=creator)
    assert report.allowed(Action.DELETE, user=creator)
    assert not report.allowed(Action.PUBLISH, user=creator)
    assert report.allowed(Action.DELETE, user=owner)
    assert not report.allowed(Action.VIEW, user=unrelated)


# @features ai-report
# @dimensions create files status delete ask answer-html html-sanitization upload-manifest proposal
@pytest.mark.unit
def test_ai_report_create_and_file_cleanup(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("owner")
    file = _test_file()
    upload_manifest = [
        {
            "token": "signed-upload",
            "input_name": "tool-files",
            "filename": "scan.pdf",
        }
    ]

    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Inbox report",
            "instructions": "Sort the uploaded scan.",
            "input_files": [file],
            "upload_manifest": upload_manifest,
        }
    )

    assert report.kind == "report"
    assert report.parent is user
    assert report.user is user
    assert report.tool == "organize"
    assert report.instructions == "Sort the uploaded scan."
    assert report.input_files == [file]
    assert report.upload_manifest == upload_manifest
    assert report.status == "pending"
    assert report.pending is True
    assert report.note == "Analyzing files..."

    ask_report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Ask report",
            "tool": "ask",
            "instructions": "Has Leo been vaccinated for pertussis?",
        }
    )
    assert ask_report.kind == "report"
    assert ask_report.tool == "ask"
    assert ask_report.input_files == []
    assert ask_report.note == "Thinking..."
    ask_report.proposal = {
        "summary": "Read the Shfl task.",
        "answer_html": (
            '<p>Read <a href="/tasks/task-1">Dance-Punk</a>.</p>'
            "<script>alert('bad')</script>"
        ),
        "actions": [],
    }
    assert '<a href="/tasks/task-1" rel="noopener noreferrer" target="_blank">' in (
        ask_report.properties.proposal.answer_html
    )
    assert "<script" not in ask_report.properties.proposal.answer_html

    create_report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Create report",
            "tool": "create",
            "instructions": "Draft a new workspace structure.",
        }
    )
    assert create_report.note == "Planning creation..."

    assert [f for f in report.input_files if not f.has_references] == [file]
    file.db["pages"] = ["existing-page"]
    assert [f for f in report.input_files if not f.has_references] == []


# @features ai-report
# @dimensions process-state canonical-storage
@pytest.mark.unit
def test_ai_report_process_state_stores_report_metadata(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("process-state-owner")
    proposal = {"summary": "Ready to review.", "actions": []}
    result = {"status": "complete", "actions": []}

    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Process report",
            "status": "ready",
            "pending": False,
            "summary": "Ready to review.",
            "proposal": proposal,
            "result": result,
            "deferred_job": {
                "key": "active-job-key",
                "idempotency_key": "active-idempotency-key",
            },
        }
    )

    assert report.status == "ready"
    assert report.pending is False
    assert report.proposal is proposal
    assert report.result is result
    assert report.deferred_job == {
        "key": "active-job-key",
        "idempotency_key": "active-idempotency-key",
    }
    assert report.properties.process.section == {
        "status": "ready",
        "summary": "Ready to review.",
        "proposal": proposal,
        "result": result,
        "deferred-job": {
            "key": "active-job-key",
            "idempotency_key": "active-idempotency-key",
        },
    }
    for key in [
        "status",
        "pending",
        "summary",
        "proposal",
        "result",
        "error",
        "deferred_job",
    ]:
        assert key not in report.db

    report.properties.process.retry(
        "AI quota is busy; retrying shortly...",
        result={"quota_retry": {"attempt": 1}},
    )
    assert report.status == "pending"
    assert report.pending is True
    assert report.error == "AI quota is busy; retrying shortly..."
    assert report.note == "AI quota is busy; retrying shortly..."
    assert report.result == {"quota_retry": {"attempt": 1}}

    report.properties.process.fail("The model is too busy right now. Try again later.")
    assert report.status == "failed"
    assert report.pending is False
    assert report.note == "The model is too busy right now. Try again later."

    report.properties.process.revise()
    assert report.status == "revising"
    assert report.pending is True
    assert report.proposal == proposal

    report.properties.process.revision_failed("Model returned no text content.")
    assert report.status == "ready"
    assert report.pending is False
    assert report.proposal == proposal
    assert report.summary == proposal["summary"]
    assert report.result is None
    assert report.error == "Model returned no text content."
    assert report.note == "Model returned no text content."

    ask_report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Ask process report",
            "tool": "ask",
        }
    )
    ask_report.properties.process.set_proposal(
        {"summary": "Answer only.", "actions": []},
        status="complete",
    )
    ask_report.properties.process.revise()
    ask_report.properties.process.revision_failed("Model returned no text content.")
    assert ask_report.status == "complete"
    assert ask_report.pending is False
    assert ask_report.note == "Model returned no text content."


# @features ai-report
# @dimensions display-registry action-contracts
@pytest.mark.unit
def test_ai_report_display_registry_covers_action_contracts():
    assert set(ACTION_DISPLAY_REGISTRY) == ALLOWED_ACTIONS


# @features ai-report
# @dimensions proposal details classification feedback
@pytest.mark.unit
def test_ai_report_proposal_display_actions_show_decision_details(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-detail-owner")
    file = _test_file("rhythm.pdf", "application/pdf")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Proposal detail report",
            "input_files": [file],
            "proposal": {
                "summary": "Use Reading with the Articles form.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "article_form",
                        "type": "create_form",
                        "data": {
                            "name": "Articles",
                            "form_type": "page",
                            "schema": [
                                {
                                    "id": "input-title",
                                    "type": "input",
                                    "title": "Title",
                                }
                            ],
                        },
                    },
                    {
                        "id": "reading",
                        "type": "create_category",
                        "data": {"name": "Reading", "form_action": "article_form"},
                    },
                    {
                        "id": "page",
                        "type": "create_page",
                        "display_label": "Rhythm in Language",
                        "data": {
                            "name": "Rhythm in Language",
                            "category_action": "reading",
                            "form_action": "article_form",
                        },
                    },
                    {
                        "id": "attachment",
                        "type": "attach_file_to_page",
                        "data": {"page_action": "page", "file": "rhythm.pdf"},
                    },
                    {
                        "id": "summary",
                        "type": "summarize_file",
                        "display_label": "Summarize for search",
                        "data": {
                            "file": "rhythm.pdf",
                            "summary": "Psycholinguistic article about rhythm and language processing.",
                            "search": True,
                        },
                    },
                    {
                        "id": "task_form",
                        "type": "create_form",
                        "data": {
                            "name": "Reading Task",
                            "form_type": "task",
                            "schema": [
                                {
                                    "id": "textarea-notes",
                                    "type": "textarea",
                                    "title": "Notes",
                                }
                            ],
                        },
                    },
                    {
                        "id": "read_task",
                        "type": "create_task",
                        "display_label": "Read Rhythm",
                        "data": {
                            "page_action": "page",
                            "form_action": "task_form",
                            "submission": {"status": "ready"},
                        },
                    },
                    {
                        "id": "existing",
                        "type": "create_page",
                        "data": {
                            "name": "Existing category page",
                            "category": "ahBSYWduaWFwcGUtNDU5MTAwchMLEgZtb2RlbBgYgICA2M",
                            "category_name": "Reading",
                            "form": "ahBSYWduaWFwcGUtNDU5MTAwchMLEgRmb3JtGICAgN",
                            "form_name": "Book",
                        },
                    },
                    {
                        "id": "raw_only",
                        "type": "create_task",
                        "data": {
                            "name": "Raw reference task",
                            "page": "ahBSYWduaWFwcGUtNDU5MTAwchILEgRwYWdlGICAgM",
                            "project": "ahBSYWduaWFwcGUtNDU5MTAwchILEgdwcm9qZWN0GICAgN",
                            "completed": True,
                        },
                    },
                    {
                        "id": "cleanup",
                        "type": "delete_page",
                        "data": {
                            "page": "ahBSYWduaWFwcGUtNDU5MTAwchILEgRwYWdlGICAgM",
                            "page_name": "Raw source page",
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["display_label"] for action in actions] == [
        "Page: Rhythm in Language (new)",
        "Page: Existing category page (new)",
        "Task: Raw reference task (new)",
    ]
    assert actions[0]["action_index"] == 3
    assert actions[0]["group_action_indexes"] == [1, 2, 3, 4, 5, 6, 7]
    assert actions[0]["details"] == [
        {"label": "Category", "value": "Reading (new)", "kind": "category"},
        {"label": "Form", "value": "Articles (new)", "kind": "form"},
        {"label": "Submission", "value": "missing", "kind": "default"},
    ]
    assert actions[0]["support"] == [
        {
            "label": "Attached File",
            "value": "rhythm",
            "kind": "file",
            "details": [],
            "support": [
                {
                    "label": "Summary",
                    "value": "Psycholinguistic article about rhythm and language processing.",
                    "kind": "file",
                    "details": [],
                    "support": [],
                    "skip": None,
                    "action_index": 5,
                    "group_action_indexes": [5],
                }
            ],
            "skip": None,
            "action_index": 4,
            "group_action_indexes": [4],
        },
        {
            "label": "Task",
            "value": "Read Rhythm (new)",
            "kind": "task",
            "details": [
                {"label": "Form", "value": "Reading Task (new)", "kind": "form"},
                {"label": "Submission", "value": "created", "kind": "default"},
            ],
            "support": [],
            "skip": None,
            "action_index": 7,
            "group_action_indexes": [7],
        },
    ]
    assert actions[1]["details"] == [
        {"label": "Category", "value": "Reading", "kind": "category"},
        {"label": "Form", "value": "Book", "kind": "form"},
        {"label": "Submission", "value": "missing", "kind": "default"},
    ]
    assert actions[2]["details"] == [
        {
            "label": "Page",
            "value": "ahBSYWduaWFwcGUtNDU5MTAwchILEgRwYWdlGICAgM",
            "kind": "page",
        },
        {
            "label": "Project",
            "value": "ahBSYWduaWFwcGUtNDU5MTAwchILEgdwcm9qZWN0GICAgN",
            "kind": "project",
        },
        {"label": "Status", "value": "Completed", "kind": "default"},
    ]


# @pair ai-report:proposal
# @pair ai-report:details
# @pair ai-report:rename
@pytest.mark.unit
def test_ai_report_proposal_display_actions_show_rename_entity_details():
    user = _test_user("proposal-rename-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Rename display report",
            "parent": user,
            "user": user,
            "proposal": {
                "summary": "Rename Orthodontics to Teeth.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "rename_page",
                        "type": "rename_entity",
                        "data": {
                            "entity": {"name": "Orthodontics"},
                            "name": "Teeth",
                        },
                    }
                ],
            },
        },
    )

    actions = report.properties.proposal.display_actions

    assert actions[0]["display_label"] == "Rename: Teeth"
    assert actions[0]["details"] == [
        {"label": "Entity", "value": "Orthodontics", "kind": "default"},
        {"label": "New Name", "value": "Teeth", "kind": "default"},
    ]


# @features ai-report
# @dimensions proposal details submission-empty-reason
@pytest.mark.unit
def test_ai_report_proposal_display_actions_show_empty_submission_reason():
    user = _test_user("proposal-empty-submission-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Empty submission display report",
            "hash": "proposal-empty-submission-report",
            "parent": user,
            "user": user,
            "proposal": {
                "summary": "Create provider page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {
                            "name": "Provider",
                            "form_name": "Doctor",
                            "submission": {},
                            "submission_needed": False,
                            "submission_empty_reason": (
                                "No submission fields were filled from the available evidence."
                            ),
                        },
                    },
                ],
            },
        },
    )

    actions = report.properties.proposal.display_actions

    assert actions[0]["details"] == [
        {"label": "Form", "value": "Doctor", "kind": "form"},
        {
            "label": "Submission",
            "value": "No submission fields were filled from the available evidence.",
            "kind": "default",
        },
    ]


# @features ai-report files
# @dimensions proposal details move-file grouped-display
@pytest.mark.unit
def test_ai_report_proposal_display_actions_group_move_files_under_target_page(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-move-file-owner")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Move file proposal",
            "proposal": {
                "summary": "Move existing family record files to one page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "family_records",
                        "type": "create_page",
                        "data": {"name": "Family Records"},
                    },
                    {
                        "id": "move_richardson",
                        "type": "move_file",
                        "data": {
                            "file": "existing-file-1",
                            "display_name": "Richardson Family Records.pdf",
                            "from_page": "old-page-1",
                            "from_page_name": "Old Family Records",
                            "to_page_action": "family_records",
                        },
                    },
                    {
                        "id": "move_strathdee",
                        "type": "move_file",
                        "data": {
                            "file": "existing-file-2",
                            "file_name": "Strathdee Family Records.pdf",
                            "source_page": "old-page-2",
                            "source_page_name": "Archived Records",
                            "to_page": "$family_records",
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["display_label"] for action in actions] == [
        "Page: Family Records (new)"
    ]
    assert actions[0]["group_action_indexes"] == [1, 2, 3]
    assert actions[0]["support"] == [
        {
            "label": "Move File",
            "value": "Richardson Family Records.pdf",
            "kind": "file",
            "details": [
                {"label": "From Page", "value": "Old Family Records", "kind": "page"}
            ],
            "support": [],
            "skip": None,
            "action_index": 2,
            "group_action_indexes": [2],
        },
        {
            "label": "Move File",
            "value": "Strathdee Family Records.pdf",
            "kind": "file",
            "details": [
                {"label": "From Page", "value": "Archived Records", "kind": "page"}
            ],
            "support": [],
            "skip": None,
            "action_index": 3,
            "group_action_indexes": [3],
        },
    ]


# @features ai-report files
# @dimensions proposal details fallback-labels
@pytest.mark.unit
def test_ai_report_proposal_display_actions_humanize_generated_action_ids(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-humanized-action-owner")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Rough move proposal",
            "proposal": {
                "summary": "Move family records.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "create_family_records_page",
                        "type": "create_page",
                        "data": {},
                    },
                    {
                        "id": "move_file_richardson",
                        "type": "move_file",
                        "data": {
                            "file": "richardson-file-id",
                            "from_page": "old-page-id",
                            "from_page_name": "Old Family Records",
                            "to_page_action": "create_family_records_page",
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["display_label"] for action in actions] == [
        "Page: Family Records (new)"
    ]
    assert actions[0]["support"][0]["value"] == "Richardson"


# @features ai-report categories
# @dimensions proposal details grouped-display add-category
@pytest.mark.unit
def test_ai_report_proposal_display_actions_groups_added_categories_under_page(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-add-category-owner")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Add category proposal",
            "proposal": {
                "summary": "Create the page and also file it with family records.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {"name": "Richardson Records"},
                    },
                    {
                        "id": "add_family_records",
                        "type": "add_category",
                        "data": {
                            "page_action": "page",
                            "category": "family-records-category",
                            "category_name": "Family Records",
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["display_label"] for action in actions] == [
        "Page: Richardson Records (new)"
    ]
    assert actions[0]["support"] == [
        {
            "label": "Add Category",
            "value": "Family Records",
            "kind": "category",
            "details": [],
            "support": [],
            "skip": None,
            "action_index": 2,
            "group_action_indexes": [2],
        }
    ]


# @features ai-report categories files
# @dimensions proposal details existing-page-category attachment-grouping
@pytest.mark.unit
def test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-existing-page-category-owner")
    category = TestEntities.get(
        "CATEGORY", {"name": "School Records", "hash": "school-records-category"}
    )
    page = TestEntities.get("PAGE", {"name": "Lucy Olive Wright", "hash": "lucy-page"})
    page.model = category
    file = _test_file("Lucy SS.pdf", "application/pdf")
    entity_map = {entity.urlsafe_key: entity for entity in (category, page)}
    monkeypatch.setattr(
        Entities,
        "fetch",
        lambda *refs, request: [entity_map[ref] for ref in refs if ref in entity_map],
    )
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Existing page category proposal",
            "input_files": [file],
            "proposal": {
                "summary": "Attach the scan to an existing school page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "attach_lucy_ss",
                        "type": "attach_file_to_page",
                        "data": {
                            "page": page.urlsafe_key,
                            "file": file.urlsafe_key,
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["display_label"] for action in actions] == [
        "Page: Lucy Olive Wright"
    ]
    assert actions[0]["details"] == [
        {"label": "Category", "value": "School Records", "kind": "category"},
    ]
    assert actions[0]["support"] == [
        {
            "label": "Attached File",
            "value": "Lucy SS",
            "kind": "file",
            "details": [],
            "support": [],
            "skip": None,
            "action_index": 1,
            "group_action_indexes": [1],
        }
    ]


# @features ai-report
# @dimensions proposal details normalized-references display-labels
@pytest.mark.unit
def test_ai_report_proposal_display_actions_resolve_normalized_entity_refs(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-normalized-ref-owner")
    category = TestEntities.get(
        "CATEGORY", {"name": "Pettis", "hash": "pettis-category"}
    )
    form = TestEntities.get("FORM", {"name": "Contractor", "hash": "contractor-form"})
    project = TestEntities.get(
        "PROJECT", {"name": "Home Remodeling", "hash": "home-remodeling-project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Invoices", "hash": "invoice-model"},
        project=project,
    )
    page = TestEntities.get("PAGE", {"name": "Landscape Pros", "hash": "pros-page"})
    page.model = category
    entity_map = {
        entity.urlsafe_key: entity for entity in (category, form, project, model, page)
    }
    monkeypatch.setattr(
        Entities,
        "fetch",
        lambda *refs, request: [entity_map[ref] for ref in refs if ref in entity_map],
    )
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Normalized refs",
            "proposal": {
                "summary": "Use existing structure.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {
                            "name": "Landscape Nirvana",
                            "category": category.urlsafe_key,
                            "form": form.urlsafe_key,
                        },
                    },
                    {
                        "id": "task",
                        "type": "create_task",
                        "data": {
                            "name": "Invoice 1420",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert actions[0]["details"] == [
        {"label": "Category", "value": "Pettis", "kind": "category"},
        {"label": "Form", "value": "Contractor", "kind": "form"},
        {"label": "Submission", "value": "missing", "kind": "default"},
    ]
    assert actions[1]["display_label"] == "Page: Landscape Pros"
    assert actions[1]["details"] == [
        {"label": "Category", "value": "Pettis", "kind": "category"},
    ]
    assert actions[1]["support"] == [
        {
            "label": "Task",
            "value": "Invoice 1420 (new)",
            "kind": "task",
            "details": [
                {"label": "Project", "value": "Home Remodeling", "kind": "project"},
                {"label": "Model Task", "value": "Invoices", "kind": "model"},
            ],
            "support": [],
            "skip": None,
            "action_index": 2,
            "group_action_indexes": [2],
        }
    ]


# @features ai-report
# @dimensions proposal completed-task grouped-display
@pytest.mark.unit
def test_ai_report_proposal_display_actions_group_completed_task_events(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-history-owner")
    file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Task history proposal",
            "input_files": [file],
            "proposal": {
                "summary": "Track the Jeep registration as a completed task.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "jeep",
                        "type": "create_page",
                        "data": {"name": "Jeep"},
                    },
                    {
                        "id": "registration_event",
                        "type": "create_task",
                        "display_label": "Record completed registration",
                        "data": {
                            "name": "Registration",
                            "page_action": "jeep",
                            "completed_on": "2023-06-24",
                        },
                    },
                    {
                        "id": "attach_registration_scan",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_event",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                    {
                        "id": "existing_history",
                        "type": "create_task",
                        "display_label": "Existing oil change history",
                        "data": {
                            "name": "Oil Change",
                            "page": "page-existing",
                            "page_name": "Jeep",
                            "task": "oil-change-task",
                            "task_name": "Oil Change",
                            "completed_on": "2023-01-12",
                        },
                    },
                    {
                        "id": "attach_oil_change_scan",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "existing_history",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["display_label"] for action in actions] == [
        "Page: Jeep (new)",
        "Page: Jeep",
    ]
    task_support = actions[0]["support"][0]
    assert task_support["label"] == "Task"
    assert task_support["value"] == "Registration (new)"
    assert {"label": "Completed On", "value": "2023-06-24", "kind": "default"} in (
        task_support["details"]
    )
    assert task_support["support"][0]["label"] == "Attached File"
    assert task_support["support"][0]["value"] == "2023-06-24 jeep registration"
    assert {1, 2}.issubset(set(actions[0]["group_action_indexes"]))
    existing_task_support = actions[1]["support"][0]
    assert existing_task_support["label"] == "Task"
    assert existing_task_support["value"] == "Oil Change (existing task)"
    assert {"label": "Task", "value": "Oil Change", "kind": "task"} in (
        existing_task_support["details"]
    )
    assert {"label": "Completed On", "value": "2023-01-12", "kind": "default"} in (
        existing_task_support["details"]
    )
    assert existing_task_support["support"][0]["label"] == "Attached File"
    assert existing_task_support["support"][0]["value"] == (
        "2023-06-24 jeep registration"
    )


# @features ai-report form-schema
# @dimensions proposal details schema-section skip-grouping
@pytest.mark.unit
def test_ai_report_proposal_display_actions_group_schema_updates_separately(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("proposal-schema-update-owner")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Schema update proposal",
            "proposal": {
                "summary": "Add the missing invoice status and update rows.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "schema",
                        "type": "update_form_schema",
                        "data": {
                            "form": "invoice-form",
                            "form_name": "Invoice",
                            "operations": [
                                {
                                    "op": "add_select_option",
                                    "schema_id": "select-status",
                                    "option": {
                                        "value": "paid",
                                        "label": "Paid",
                                    },
                                },
                                {
                                    "op": "add_field",
                                    "field": {
                                        "id": "input-payment-reference",
                                        "type": "input",
                                        "input": "text",
                                        "title": "Payment Reference",
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "id": "updates",
                        "type": "update_submission_fields",
                        "depends_on": ["schema"],
                        "data": {
                            "updates": [
                                {
                                    "task": "invoice-task",
                                    "task_name": "July invoice",
                                    "schema_id": "select-status",
                                    "new_value": "paid",
                                }
                            ]
                        },
                    },
                ],
            },
        }
    )

    actions = report.properties.proposal.display_actions

    assert [action["type"] for action in actions] == [
        "schema_update_group",
        "update_submission_fields",
    ]
    schema_group = actions[0]
    assert schema_group["display_label"] == "Schema Updates"
    assert schema_group["skip_dependencies"] is False
    assert schema_group["action_index"] == 1
    assert schema_group["group_action_indexes"] == [1]
    assert schema_group["support"] == [
        {
            "label": "Schema Update",
            "value": "schema",
            "kind": "form",
            "details": [
                {"label": "Form", "value": "Invoice", "kind": "form"},
                {"label": "Updates", "value": "2 schema changes", "kind": "default"},
            ],
            "support": [],
            "skip": None,
            "action_index": 1,
            "group_action_indexes": [1],
        }
    ]
    assert actions[1]["display_label"] == "Submission Update: updates"
    assert actions[1]["details"] == [
        {"label": "Updates", "value": "1 field update", "kind": "default"}
    ]
    assert actions[1]["group_action_indexes"] == [1, 2]
