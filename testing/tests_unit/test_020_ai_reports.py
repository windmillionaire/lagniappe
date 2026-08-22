import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.genai import types as genai_types

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.entities.ai_report import AIReport
from lagniappe.core.entities import entity as entity_module
from lagniappe.core.definitions import (
    Action,
    LARGE_ASSET_BYTES,
    MutationIntent,
    MutationIntentType,
)
from lagniappe.core.tools.ai import (
    ask,
    create,
    organize,
    organize_retrieval,
    references as ai_references,
    report_uploads,
    report_runner,
    summarize,
)
from lagniappe.core.tools.ai.reporting.actions import lifecycle as report_action_lifecycle
from lagniappe.core.tools.ai.reporting import contracts as report_contracts
from lagniappe.core.tools.ai.reporting import organize_completion
from lagniappe.core.tools.ai.reporting import schedules as report_schedules
from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


def _with_validator(generate):
    def wrapped(prompt, *, validator=None):
        result = generate(prompt)
        return validator(result) if validator else result

    return wrapped


class FakeKey:
    def __init__(self, name):
        self.name = name

    def to_legacy_urlsafe(self):
        return self.name.encode("utf-8")

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return getattr(other, "name", other) == self.name


def _patch_fake_keys(monkeypatch):
    counter = {"value": 0}

    def create_key(kind, parent=None):
        counter["value"] += 1
        return FakeKey(f"{kind}-{counter['value']}")

    monkeypatch.setattr(entity_module.database, "create_key", create_key)
    monkeypatch.setattr(
        entity_module.database.get,
        "urlsafe_key",
        lambda key: getattr(key, "name", str(key)),
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.common_entity.cache.check_hash",
        lambda value: False,
    )
    monkeypatch.setattr(
        "lagniappe.core.entities.page.database.get.page_tasks",
        lambda page: [],
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY",
            {"name": "Uncategorized Pages", "hash": "uncategorized"},
        ),
    )
def _test_file(name="scan.pdf", mimetype="application/pdf"):
    file = TestEntities.get(
        "FILE",
        {
            "name": name.rsplit(".", 1)[0],
            "filename": name,
            "mimetype": mimetype,
            "hash": name.replace(".", "-"),
            "assets": {"file": {"type": "file", "path": name}},
        },
    )
    file.filename = name
    file.mimetype = mimetype
    return file


def _patch_task_file_add(monkeypatch):
    def add_task_file(field, attached_file):
        current = list(getattr(field, "_value", []) or [])
        if attached_file not in current:
            current.insert(0, attached_file)
        field._value = current
        field.entity.db[field.id] = [item.key for item in current]

        linked = list(attached_file.db.get("tasks") or [])
        if field.entity.key not in linked:
            linked.insert(0, field.entity.key)
        attached_file.db["tasks"] = linked

        task_links = list(getattr(attached_file.properties.tasks, "_value", []) or [])
        if field.entity not in task_links:
            task_links.insert(0, field.entity)
        attached_file.properties.tasks._value = task_links
        field.entity.add_mutation_intents(
            MutationIntent.patch(
                attached_file,
                "tasks",
                "requires",
                property_updates=("requires", "modified"),
                reason="task-file-mirror",
            )
        )
        return True

    monkeypatch.setattr(
        "lagniappe.core.properties.task_related.TaskFiles.add",
        add_task_file,
    )


def _fetch_one_from(entities):
    def fetch_one(identifier, *, request):
        if hasattr(identifier, "db"):
            return identifier
        return entities.get(identifier)

    return fetch_one


def _test_user(hash_value):
    return TestEntities.get(
        "USER",
        {
            "name": "Owner",
            "hash": hash_value,
            "owner": True,
            "page": {"name": "Owner Page", "hash": f"{hash_value}-page"},
        },
    )


def _permissioned_user(hash_value, permissions):
    return TestEntities.get(
        "USER",
        {
            "name": "Permissioned User",
            "hash": hash_value,
            "permissions": permissions,
            "page": {"name": "Permissioned Page", "hash": f"{hash_value}-page"},
        },
    )


def _prompt_context(prompt, label):
    for block in prompt.context_blocks:
        if block["label"] == label:
            return block["value"]
    raise AssertionError(f"Missing prompt context block: {label}")


def _prompt_context_json(prompt, label):
    value = _prompt_context(prompt, label).strip()
    if value.startswith("```") and value.endswith("```"):
        value = value.split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(value)


def _response_action_schemas(prompt):
    variants = prompt.response_schema["properties"]["actions"]["items"]["anyOf"]
    return {
        variant["properties"]["type"]["enum"][0]: variant
        for variant in variants
    }


def _assert_repair_prompt_contract(prompt, *, invalid_proposal, allowed_actions):
    assert prompt.allowed_actions == tuple(allowed_actions)
    assert prompt.output_format["type"] == "JSON"
    assert _prompt_context(prompt, "Validation Error").strip()
    assert _prompt_context_json(prompt, "Allowed Actions") == list(allowed_actions)
    assert _prompt_context_json(prompt, "Invalid Proposal Json") == invalid_proposal
    assert prompt.response_schema["required"] == [
        "summary",
        "confidence",
        "issues",
        "actions",
    ]
    assert tuple(_response_action_schemas(prompt)) == tuple(allowed_actions)
    assert prompt.audit()["duplicate_headings"] == []


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
# @dimensions create files status delete ask answer-html html-sanitization upload-manifest
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


# @features ai-report direct-upload
# @dimensions upload-manifest validation normalization
@pytest.mark.unit
def test_prepare_report_upload_manifest_normalizes_browser_records():
    manifest = report_uploads.prepare_report_upload_manifest(
        [
            {
                "token": " signed-token ",
                "input_name": "tool-files",
                "filename": " scan.pdf ",
                "content_type": "application/pdf",
                "size": "42",
                "generation": "7",
                "path": "tmp/uploads/scan.pdf",
                "complete": True,
                "file_key": "untrusted-file",
                "unexpected": "discarded",
            }
        ]
    )

    assert manifest == [
        {
            "token": "signed-token",
            "input_name": "tool-files",
            "filename": "scan.pdf",
            "content_type": "application/pdf",
            "size": 42,
            "generation": "7",
            "path": "tmp/uploads/scan.pdf",
        }
    ]

    with pytest.raises(exceptions.ValidationError, match="could not be prepared"):
        report_uploads.prepare_report_upload_manifest(
            [
                {
                    "token": "signed-token",
                    "input_name": "another-input",
                    "filename": "scan.pdf",
                }
            ]
        )

    with pytest.raises(
        exceptions.ValidationError,
        match="Only individual files are supported",
    ):
        report_uploads.prepare_report_upload_manifest(
            [
                {
                    "token": "signed-token",
                    "input_name": "tool-files",
                    "filename": "folder",
                    "size": 0,
                }
            ]
        )

    assert report_uploads.prepare_report_upload_manifest(
        [
            {
                "token": "signed-token",
                "input_name": "tool-files",
                "filename": "oversized.pdf",
                "size": LARGE_ASSET_BYTES + 1,
            }
        ]
    ) == [
        {
            "token": "signed-token",
            "input_name": "tool-files",
            "filename": "oversized.pdf",
            "size": LARGE_ASSET_BYTES + 1,
        }
    ]


# @features ai-report direct-upload
# @dimensions upload-manifest background-finalization resume progress active-request
@pytest.mark.unit
def test_finalize_report_upload_manifest_resumes_and_checkpoints(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("upload-finalizer-owner")
    existing = _test_file("first.pdf")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Staged upload report",
            "input_files": [existing],
            "upload_manifest": [
                {
                    "token": "first-token",
                    "input_name": "tool-files",
                    "filename": "first.pdf",
                    "complete": True,
                    "file_key": existing.urlsafe_key,
                },
                {
                    "token": "second-token",
                    "input_name": "tool-files",
                    "filename": "second.pdf",
                },
            ],
        }
    )
    loaded = []
    cleaned = []
    saved = []
    active_checks = []

    def load_upload(record):
        loaded.append(record["filename"])
        return SimpleNamespace(
            filename=record["filename"],
            content_type="application/pdf",
            size=1024,
        )

    def create_file(*, upload, data):
        assert data == {
            "filename": upload.filename,
            "mimetype": "application/pdf",
        }
        return _test_file(upload.filename)

    def save_entities(*entities):
        saved.append(
            {
                "entities": entities,
                "summary": report.summary,
                "manifest": copy.deepcopy(report.upload_manifest),
            }
        )

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        user,
        save=save_entities,
        upload_loader=load_upload,
        file_factory=create_file,
        upload_cleanup=lambda record: cleaned.append(record["filename"]),
        ensure_active=lambda: active_checks.append(True),
    )

    assert loaded == ["second.pdf"]
    assert cleaned == ["first.pdf", "second.pdf"]
    assert [file.filename for file in finalized] == ["second.pdf"]
    assert [file.filename for file in report.input_files] == [
        "first.pdf",
        "second.pdf",
    ]
    assert saved[0]["summary"] == "Preparing files (2 of 2)..."
    assert saved[0]["manifest"][1]["complete"] is True
    assert saved[0]["manifest"][1]["file_key"] == finalized[0].urlsafe_key
    assert saved[-1]["manifest"] is None
    assert report.upload_manifest is None
    assert report.summary is None
    assert len(active_checks) == 4


# @features ai-report direct-upload
# @dimensions upload-manifest background-finalization checkpoint-failure
@pytest.mark.unit
def test_finalize_report_upload_manifest_retains_source_until_checkpoint(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("upload-finalizer-retry-owner")
    original_manifest = [
        {
            "token": "signed-token",
            "input_name": "tool-files",
            "filename": "retry.pdf",
        }
    ]
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Interrupted staged upload report",
            "upload_manifest": copy.deepcopy(original_manifest),
        }
    )
    source_available = True
    events = []

    def load_upload(record):
        assert source_available
        events.append("load-source")
        return SimpleNamespace(
            filename=record["filename"],
            content_type="application/pdf",
            size=1024,
        )

    def create_file(*, upload, data):
        assert upload.lagniappe_preserve_source is True
        events.append("copy-source")
        return _test_file(data["filename"])

    def interrupted_save(*entities):
        events.append("checkpoint-failed")
        raise RuntimeError("worker interrupted before checkpoint")

    def cleanup_upload(record):
        nonlocal source_available
        events.append("delete-source")
        source_available = False

    with pytest.raises(RuntimeError, match="interrupted before checkpoint"):
        report_uploads.finalize_report_upload_manifest(
            report,
            user,
            save=interrupted_save,
            upload_loader=load_upload,
            file_factory=create_file,
            upload_cleanup=cleanup_upload,
        )

    assert source_available is True
    assert events == ["load-source", "copy-source", "checkpoint-failed"]

    # A Cloud Tasks retry reloads the last persisted report state.
    report.input_files = []
    report.upload_manifest = copy.deepcopy(original_manifest)
    report.summary = None
    events.clear()

    def save_entities(*entities):
        events.append("checkpoint-saved")

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        user,
        save=save_entities,
        upload_loader=load_upload,
        file_factory=create_file,
        upload_cleanup=cleanup_upload,
    )

    assert [file.filename for file in finalized] == ["retry.pdf"]
    assert source_available is False
    assert events == [
        "load-source",
        "copy-source",
        "checkpoint-saved",
        "delete-source",
        "checkpoint-saved",
    ]
    assert report.upload_manifest is None


# @pair ai-report:large-file
# @pair direct-upload:large-file
@pytest.mark.unit
def test_finalize_report_upload_manifest_accepts_actual_oversized_object():
    report = SimpleNamespace(
        upload_manifest=[{"token": "signed", "filename": "oversized.pdf"}],
        input_files=[],
    )
    upload = SimpleNamespace(
        filename="oversized.pdf",
        content_type="application/pdf",
        size=LARGE_ASSET_BYTES + 1,
    )
    file = SimpleNamespace(
        filename="oversized.pdf",
        urlsafe_key="oversized-file",
    )
    saves = []
    cleaned = []

    finalized = report_uploads.finalize_report_upload_manifest(
        report,
        SimpleNamespace(),
        save=lambda *entities: saves.append(entities),
        upload_loader=lambda _record: upload,
        file_factory=lambda **_kwargs: file,
        upload_cleanup=lambda record: cleaned.append(record),
    )

    assert finalized == [file]
    assert report.input_files == [file]
    assert report.upload_manifest is None
    assert upload.lagniappe_preserve_source is True
    assert len(saves) == 2
    assert len(cleaned) == 1


# @features ai-report direct-upload
# @dimensions upload-manifest cleanup partial-progress
@pytest.mark.unit
def test_cleanup_report_upload_manifest_deletes_only_pending_uploads(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("upload-cleanup-owner")
    report = AIReport.create(
        {
            "parent": user,
            "user": user,
            "name": "Upload cleanup report",
            "upload_manifest": [
                {"token": "complete", "filename": "complete.pdf", "complete": True},
                {"token": "pending", "filename": "pending.pdf"},
            ],
        }
    )
    deleted = []

    count = report_uploads.cleanup_report_upload_manifest(
        report,
        delete_upload=lambda record: deleted.append(record["filename"]) or True,
    )

    assert count == 1
    assert deleted == ["pending.pdf"]


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

    report.properties.process.fail(
        "The model is too busy right now. Try again later."
    )
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
    page = TestEntities.get(
        "PAGE", {"name": "Lucy Olive Wright", "hash": "lucy-page"}
    )
    page.model = category
    file = _test_file("Lucy SS.pdf", "application/pdf")
    entity_map = {
        entity.urlsafe_key: entity
        for entity in (category, page)
    }
    monkeypatch.setattr(
        Entities,
        "fetch",
        lambda *refs, request: [
            entity_map[ref] for ref in refs if ref in entity_map
        ],
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
        entity.urlsafe_key: entity
        for entity in (category, form, project, model, page)
    }
    monkeypatch.setattr(
        Entities,
        "fetch",
        lambda *refs, request: [
            entity_map[ref] for ref in refs if ref in entity_map
        ],
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


# @features ai-report
# @dimensions prompt files tools iteration-limit
@pytest.mark.unit
def test_organize_prompt_includes_files_tools_instructions_and_high_limit():
    user = _test_user("prompt-owner")
    file = _test_file("receipt.png", "image/png")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Prompt report",
            "hash": "prompt-report",
            "parent": user,
            "user": user,
            "instructions": "This is probably a receipt.",
            "input_files": [file],
        },
    )

    retrieval_context = {
        "hash:receipt-png": [
            {
                "term": "receipt",
                "candidates": [
                    {
                        "hash": "hash:receipts-category",
                        "kind": "category",
                        "name": "Receipts",
                        "text": "Household purchase records.",
                    }
                ],
            },
            {"term": "store", "candidates": []},
        ]
    }
    prompt = organize.organize_prompt(report, user, retrieval_context)

    assert prompt.max_tool_iterations == organize.ORGANIZE_MAX_TOOL_ITERATIONS
    assert (
        prompt.max_tool_file_parts_per_turn
        == organize.ORGANIZE_MAX_TOOL_FILE_PARTS_PER_TURN
    )
    assert prompt.thinking_budget is None
    assert prompt.service_tier is None
    assert organize.ai_model.create_config(prompt).thinking_config is None
    assert prompt.tools == list(organize.READ_ONLY_CONTEXT_TOOLS)
    assert "get_task_history" not in organize.READ_ONLY_CONTEXT_TOOLS
    assert _prompt_context(prompt, "User Instructions") == (
        "```\nThis is probably a receipt.\n```"
    )
    input_files = _prompt_context_json(prompt, "Report Input Files")
    assert input_files[0] | {
        "display_name": "receipt",
        "filename": "receipt.png",
        "hash": "hash:receipt-png",
        "mimetype": "image/png",
        "report_file_ref": "hash:receipt-png",
    } == input_files[0]
    assert input_files[0]["permissions"] == {
        "can_create": True,
        "can_edit": True,
        "can_view": True,
    }
    assert input_files[0]["workspace_searches"] == retrieval_context[
        "hash:receipt-png"
    ]
    assert "permissions" not in input_files[0]["workspace_searches"][0][
        "candidates"
    ][0]
    assert _prompt_context_json(prompt, "Report Action Permissions")[
        "capabilities"
    ]["can_create_pages"] is True
    preview = prompt.preview()
    assert preview.index("## Instructions") < preview.index("## Context")
    normalized_preview = " ".join(preview.split())
    semantic_preview = normalized_preview.replace("`", "")
    assert "never include internal entity hash tokens" in preview
    assert "Keep hash\ntokens exclusively in executable action data" in preview
    workflow_markers = [
        "1. Establish the evidence",
        "2. Cluster the uploads by stable subject",
        "3. Choose the collection scope",
        "4. Check page candidates for the chosen category",
        "5. Search for any remaining page candidate",
        "6. Choose the page target",
        "7. Decide whether the evidence belongs on the page or on a task",
        "8. Choose structured forms after the page/task target is settled",
        "9. Build the ordered proposal",
    ]
    workflow_positions = [
        semantic_preview.index(marker) for marker in workflow_markers
    ]
    assert workflow_positions == sorted(workflow_positions)
    assert (
        "get_category_pages with that category, compact=true, and limit=10"
        in semantic_preview
    )
    assert "Start with the bounded workspace_searches" in semantic_preview
    assert "list_workspace_resources only when the prefetched candidates" in (
        semantic_preview
    )
    assert "Batch get_entity calls for plausible candidates only" in semantic_preview
    assert 'search_entities with kinds=["page"]' in semantic_preview
    assert "a wording difference does not justify a duplicate" in semantic_preview
    assert "Propose create_page only after steps 4 and 5" in semantic_preview
    assert "something specific was done or needs to be done" in semantic_preview
    assert "set completed: true" in semantic_preview
    assert "solely because the exact date is unknown" in semantic_preview
    assert "If the matching page cannot be edited, use needs_review" in (
        semantic_preview
    )
    assert "no broad category-level catch-all" in semantic_preview
    assert "New page names are concise subject labels" in semantic_preview
    assert "Category default forms appear only" in semantic_preview
    assert (
        "add_category requires both the existing page and the additional existing "
        "category"
    ) in semantic_preview
    assert (
        'add_category: {"page" or "page_action", "category" or '
        '"category_action"}'
    ) in semantic_preview
    assert (
        "Every add_category action has both an executable page/page_action "
        "reference and an executable category/category_action reference"
    ) in semantic_preview
    assert set(prompt.allowed_actions) == {
        "create_form",
        "create_category",
        "create_project",
        "create_model_task",
        "create_page",
        "create_task",
        "add_form_to_page",
        "add_category",
        "update_form_schema",
        "update_submission_fields",
        "attach_file_to_page",
        "attach_file_to_task",
        "delete_page",
        "skip",
        "needs_review",
    }
    assert "summarize_file" not in prompt.allowed_actions
    assert "update_submission_fields" in prompt.allowed_actions
    assert "move_page" not in prompt.allowed_actions
    assert "move_task" not in prompt.allowed_actions
    assert "move_file" not in prompt.allowed_actions
    assert prompt.response_schema["required"] == [
        "summary",
        "confidence",
        "issues",
        "actions",
    ]
    action_schemas = _response_action_schemas(prompt)
    assert tuple(action_schemas) == prompt.allowed_actions
    for action_schema in action_schemas.values():
        data_properties = action_schema["properties"]["data"]["properties"]
        assert "submission" not in data_properties
        assert "submission_empty_reason" not in data_properties
        assert "submission_needed" not in data_properties
        assert "submission_request" not in data_properties
        assert "submission_context" not in data_properties
    assert action_schemas["create_task"]["properties"]["data"]["properties"][
        "completed"
    ] == {
        "type": "boolean"
    }
    assert prompt.output_format["type"] == "JSON"
    assert prompt.output_format["requirements"] is None
    assert {
        block.get("role")
        for block in prompt.instruction_blocks
        if block.get("role")
    } >= {"action_permissions", "tool_use", "action_planning"}
    assert any(
        block.get("title") == "On-demand guidelines"
        for block in prompt.instruction_blocks
    )
    assert 'MUST call get_guidelines("page_form")' in prompt.preview()
    assert 'MUST call get_guidelines("schema_evolution")' in prompt.preview()
    assert "input fields also have an input subtype" in prompt.preview()
    assert "do not say records were created" in prompt.preview()
    assert "Missing schema syntax is not a user decision" in prompt.preview()
    assert prompt.audit()["duplicate_headings"] == []
    assert "get_form_instances" in prompt.tools
    assert prompt.files == []
    assert len(organize.organize_prompt(report, user).preview()) < 20_000
    assert "Completion owns form values" in prompt.preview()


# @features ai-report search
# @dimensions summary-terms redis-search kinds limits fallback
@pytest.mark.unit
def test_prepare_organize_retrieval_context_searches_bounded_structure_candidates(
    monkeypatch,
):
    user = _test_user("retrieval-context-owner")
    first = _test_file("john-writing.pdf", "application/pdf")
    second = _test_file("garden-notes.pdf", "application/pdf")
    first.summary = "John's creative writing and short stories."
    second.summary = "Notes about tomatoes in the family garden."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Retrieval context",
            "hash": "retrieval-context-report",
            "parent": user,
            "user": user,
            "input_files": [first, second],
        },
    )
    first.properties.summarize.retrieval_terms = ["john", "writing"]
    second.properties.summarize.retrieval_terms = ["garden", "tomatoes"]
    search_calls = []

    def execute_search(args, actor):
        assert actor is user
        search_calls.append(args)
        return [
            {
                "hash": f"hash:{args['query']}-candidate",
                "kind": "page",
                "name": args["query"].title(),
                "text": f"Matching snippet for {args['query']}.",
            }
        ]

    monkeypatch.setattr(organize_retrieval, "execute_search", execute_search)

    context = organize_retrieval.prepare_organize_retrieval_context(report, user)

    assert [call["query"] for call in search_calls] == [
        "john",
        "writing",
        "garden",
        "tomatoes",
    ]
    assert all(
        call["kinds"] == ["category", "page", "form"]
        and call["limit"] == 5
        for call in search_calls
    )
    assert context["hash:john-writing-pdf"][0] == {
        "term": "john",
        "candidates": [
            {
                "hash": "hash:john-candidate",
                "kind": "page",
                "name": "John",
                "text": "Matching snippet for john.",
            }
        ],
    }
    assert [row["term"] for row in context["hash:garden-notes-pdf"]] == [
        "garden",
        "tomatoes",
    ]


# @features ai-report
# @dimensions summary-prepass quota search-opt-in active-request
@pytest.mark.unit
def test_summarize_report_input_files_saves_missing_summaries(monkeypatch):
    user = _test_user("summary-prepass-owner")
    first = _test_file("first.pdf", "application/pdf")
    office = _test_file(
        "agenda.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    second = _test_file("second.pdf", "application/pdf")
    existing = _test_file("existing.pdf", "application/pdf")
    unsupported = _test_file("archive.zip", "application/zip")
    existing.summary = "Already summarized."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Summary prepass",
            "hash": "summary-prepass-report",
            "parent": user,
            "user": user,
            "input_files": [first, office, existing, unsupported, second],
        },
    )
    generated = []
    saved = []
    active_checks = []

    def fake_generate_summary(file, raise_quota=False):
        assert raise_quota is True
        generated.append(file.filename)
        file.summary = f"Summary for {file.filename}"
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", fake_generate_summary)

    summarized = organize.summarize_report_input_files(
        report,
        save=saved.append,
        ensure_active=lambda: active_checks.append(True),
    )

    assert summarized == [first, office, second]
    assert saved == [first, office, second]
    assert generated == ["first.pdf", "agenda.docx", "second.pdf"]
    assert first.properties.summarize.enabled is True
    assert first.properties.summarize.search is True
    assert first.properties.summarize.complete is True
    assert office.properties.summarize.enabled is True
    assert office.properties.summarize.search is True
    assert office.properties.summarize.complete is True
    assert second.properties.summarize.enabled is True
    assert second.properties.summarize.search is True
    assert second.properties.summarize.complete is True
    assert existing.summary == "Already summarized."
    assert unsupported.summary is None
    assert len(active_checks) == 8

    unindexed = _test_file("unindexed.pdf", "application/pdf")
    unindexed_report = TestEntities.get(
        "REPORT",
        {
            "name": "Summary prepass without search",
            "hash": "summary-prepass-unindexed-report",
            "parent": user,
            "user": user,
            "input_files": [unindexed],
        },
    )

    def no_quota_summary(file, raise_quota=False):
        assert raise_quota is False
        file.summary = "Unindexed summary."
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", no_quota_summary)

    summarized = organize.summarize_report_input_files(
        unindexed_report, search=False, raise_quota=False
    )

    assert summarized == [unindexed]
    assert unindexed.summary == "Unindexed summary."
    assert unindexed.properties.summarize.enabled is True
    assert unindexed.properties.summarize.search is False
    assert unindexed.properties.summarize.complete is True

    third = _test_file("third.pdf", "application/pdf")
    fourth = _test_file("fourth.pdf", "application/pdf")
    quota_report = TestEntities.get(
        "REPORT",
        {
            "name": "Summary prepass quota",
            "hash": "summary-prepass-quota-report",
            "parent": user,
            "user": user,
            "input_files": [third, fourth],
        },
    )
    quota_saved = []

    def quota_after_first(file, raise_quota=False):
        if file is fourth:
            raise exceptions.AIQuotaError("quota busy")
        file.summary = "Third summary."
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", quota_after_first)

    with pytest.raises(exceptions.AIQuotaError):
        organize.summarize_report_input_files(quota_report, save=quota_saved.append)

    assert quota_saved == [third]
    assert third.summary == "Third summary."
    assert third.properties.summarize.enabled is True
    assert third.properties.summarize.search is True
    assert third.properties.summarize.complete is True
    assert fourth.summary is None


# @features ai-report
# @dimensions summary-prepass large-file fallback
@pytest.mark.unit
def test_summarize_report_input_files_falls_back_for_large_files(monkeypatch):
    user = _test_user("large-summary-owner")
    supported = _test_file("large-source.pdf", "application/pdf")
    unsupported = _test_file("large-source.zip", "application/zip")
    small = _test_file("small-source.zip", "application/zip")
    supported.test_spec["asset_sizes"] = {"file": LARGE_ASSET_BYTES + 1}
    unsupported.test_spec["asset_sizes"] = {"file": LARGE_ASSET_BYTES + 1}
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Large summary fallback",
            "hash": "large-summary-report",
            "parent": user,
            "user": user,
            "input_files": [supported, unsupported, small],
        },
    )
    generated = []
    saved = []

    def no_summary(file, raise_quota=False):
        assert raise_quota is True
        generated.append(file.filename)
        file.properties.summarize.error = "Provider did not return a summary."
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", no_summary)

    summarized = organize.summarize_report_input_files(report, save=saved.append)

    assert generated == ["large-source.pdf"]
    assert summarized == [supported, unsupported]
    assert saved == [supported, unsupported]
    assert supported.summary == organize.OVERSIZED_REPORT_SUMMARY
    assert unsupported.summary == organize.OVERSIZED_REPORT_SUMMARY
    assert small.summary is None
    assert supported.properties.summarize.error is None
    assert supported.properties.summarize.complete is True
    assert unsupported.properties.summarize.complete is True

    prompt_files = _prompt_context_json(
        organize.organize_prompt(report, user),
        "Report Input Files",
    )
    by_filename = {item["filename"]: item for item in prompt_files}
    assert by_filename["large-source.pdf"]["summary"] == (
        organize.OVERSIZED_REPORT_SUMMARY
    )
    assert by_filename["large-source.pdf"]["large"] is True
    assert by_filename["large-source.zip"]["display_name"] == "large-source"


# @features ai-report
# @dimensions summary-prepass unreadable-pdf persistence issue
@pytest.mark.unit
def test_unreadable_pdf_is_saved_skipped_and_reported(monkeypatch):
    user = _test_user("unreadable-pdf-owner")
    file = _test_file("locked-policy.pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Unreadable PDF report",
            "hash": "unreadable-pdf-report",
            "parent": user,
            "user": user,
            "input_files": [file],
        },
    )
    generated = []
    saved = []

    def unreadable_summary(target, raise_quota=False):
        assert raise_quota is True
        generated.append(target.filename)
        target.properties.summarize.status = "PDF could not be read."
        target.properties.summarize.error = summarize.UNREADABLE_PDF_SUMMARY_ERROR
        return target.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", unreadable_summary)

    summarized = organize.summarize_report_input_files(report, save=saved.append)
    retried = organize.summarize_report_input_files(report, save=saved.append)

    assert summarized == []
    assert retried == []
    assert generated == ["locked-policy.pdf"]
    assert saved == [file]

    prompt_files = _prompt_context_json(
        organize.organize_prompt(report, user),
        "Report Input Files",
    )
    warning = (
        "Could not read locked-policy.pdf. The PDF may be encrypted or "
        "password-protected."
    )
    assert prompt_files[0]["summary_warning"] == warning

    completed = organize.complete_organize_submissions(
        {
            "summary": "Organize the readable evidence.",
            "confidence": 0.5,
            "issues": [],
            "actions": [],
        },
        report,
        user,
    )

    assert completed["issues"] == [warning]


# @features ai-report
# @dimensions revision feedback proposal context
@pytest.mark.unit
def test_revise_organize_prompt_includes_feedback_and_current_proposal():
    user = _test_user("revision-owner")
    file = _test_file("article.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Revision report",
            "hash": "revision-report",
            "parent": user,
            "user": user,
            "instructions": "I'd like to read these.",
            "input_files": [file],
            "proposal": {
                "summary": "Use the Books category.",
                "confidence": 0.7,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "display_label": "Book page",
                        "data": {
                            "name": "Book page",
                            "category": (
                                "ahBsYWduaWFwcGUtNDU5MTAwchYLEglpbnN0YW5jZXMYgICA"
                                "A2MHHkwoM"
                            ),
                        },
                    }
                ],
            },
        },
    )

    prompt = organize.revise_organize_prompt(
        report,
        user,
        "These are articles, not books.",
    )

    assert prompt.max_tool_iterations == organize.ORGANIZE_MAX_TOOL_ITERATIONS
    assert (
        prompt.max_tool_file_parts_per_turn
        == organize.ORGANIZE_MAX_TOOL_FILE_PARTS_PER_TURN
    )
    assert prompt.tools == list(organize.READ_ONLY_CONTEXT_TOOLS)
    assert "get_task_history" not in organize.READ_ONLY_CONTEXT_TOOLS
    assert _prompt_context(prompt, "User Feedback") == (
        "```\nThese are articles, not books.\n```"
    )
    assert _prompt_context_json(prompt, "Current Proposal Json") == report.proposal
    assert _prompt_context(prompt, "User Instructions") == (
        "```\nI'd like to read these.\n```"
    )
    assert _prompt_context_json(prompt, "Report Input Files")[0]["filename"] == (
        "article.pdf"
    )
    assert prompt.response_schema["required"] == [
        "summary",
        "confidence",
        "issues",
        "actions",
    ]
    assert any(
        block.get("role") == "revision_task"
        for block in prompt.instruction_blocks
    )
    assert prompt.audit()["duplicate_headings"] == []
    assert prompt.files == []


# @features ai-report
# @dimensions create prompt search tools actions
@pytest.mark.unit
def test_create_prompt_builds_creation_proposal_without_file_actions():
    user = _test_user("create-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Create report",
            "hash": "create-report",
            "parent": user,
            "user": user,
            "tool": "create",
            "instructions": "Build a new set of workspace records.",
            "input_files": [],
        },
    )

    prompt = create.create_prompt(report, user)

    assert prompt.search is True
    assert prompt.max_tool_iterations == create.CREATE_MAX_TOOL_ITERATIONS
    assert prompt.tools == list(organize.READ_ONLY_CONTEXT_TOOLS)
    assert prompt.allowed_actions == (
        "create_form",
        "create_category",
        "create_project",
        "create_model_task",
        "create_page",
        "create_task",
        "needs_review",
    )
    assert _prompt_context(prompt, "User Request") == (
        "```\nBuild a new set of workspace records.\n```"
    )
    assert prompt.response_schema["required"] == [
        "summary",
        "confidence",
        "actions",
    ]
    assert tuple(_response_action_schemas(prompt)) == prompt.allowed_actions
    assert "attach_file_to_page" not in prompt.allowed_actions
    assert "summarize_file" not in prompt.allowed_actions
    assert prompt.audit()["duplicate_headings"] == []
    assert "Category default forms are exceptional" in prompt.preview()


# @features ai-report
# @dimensions create revision feedback proposal context
@pytest.mark.unit
def test_revise_create_prompt_includes_feedback_and_current_proposal():
    user = _test_user("create-revision-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Create revision report",
            "hash": "create-revision-report",
            "parent": user,
            "user": user,
            "tool": "create",
            "instructions": "Build supporting records.",
            "input_files": [],
            "proposal": {
                "summary": "Create one page.",
                "confidence": 0.7,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "display_label": "Support page",
                        "data": {"name": "Support page"},
                    }
                ],
            },
        },
    )

    prompt = create.revise_create_prompt(
        report,
        user,
        "Add a reusable category too.",
    )

    assert _prompt_context(prompt, "User Feedback") == (
        "```\nAdd a reusable category too.\n```"
    )
    assert _prompt_context_json(prompt, "Current Proposal Json") == report.proposal
    assert _prompt_context(prompt, "User Request") == (
        "```\nBuild supporting records.\n```"
    )
    assert tuple(_response_action_schemas(prompt)) == prompt.allowed_actions
    assert prompt.audit()["duplicate_headings"] == []


# @features ai-report
# @dimensions structured-output schema allowed-actions
@pytest.mark.unit
def test_report_prompts_attach_provider_json_schema():
    user = _permissioned_user(
        "schema-output-user",
        {
            "cat-readable": "VIEW",
            "cat-editable": "EDIT",
        },
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Structured output report",
            "hash": "structured-output-report",
            "parent": user,
            "user": user,
            "instructions": "Save this.",
            "input_files": [],
        },
    )

    with MockRestrictions().patch_cache():
        organize_prompt = organize.organize_prompt(report, user)
        ask_prompt = ask.ask_prompt(report, user)
        create_prompt = create.create_prompt(report, user)

    organize_schema = organize_prompt.response_schema
    organize_actions = _response_action_schemas(organize_prompt)
    create_actions = _response_action_schemas(create_prompt)
    all_actions = _response_action_schemas(
        SimpleNamespace(
            response_schema=organize.report_proposal_response_schema(
                organize.ACTION_ORDER,
                include_submission_fields=False,
            )
        )
    )
    full_actions = _response_action_schemas(
        SimpleNamespace(
            response_schema=organize.report_proposal_response_schema(
                organize.ACTION_ORDER,
            )
        )
    )
    organize_action_data = all_actions["create_form"]["properties"]["data"]
    organize_action_properties = all_actions["create_form"]["properties"]
    assert organize_schema["required"] == [
        "summary",
        "confidence",
        "issues",
        "actions",
    ]
    assert organize_schema["additionalProperties"] is False
    assert "answer_html" not in organize_schema["properties"]
    assert tuple(organize_actions) == organize_prompt.allowed_actions
    assert "display_label" in organize_action_properties
    assert "title" not in organize_action_properties
    assert all(
        action["additionalProperties"] is False
        and action["properties"]["data"]["additionalProperties"] is False
        for action in organize_actions.values()
    )
    assert organize_action_data["properties"]["name"] == {"type": "string"}
    assert organize_action_data["properties"]["form_type"]["enum"] == [
        "page",
        "task",
    ]
    field_schema = organize_action_data["properties"]["schema"]["items"]
    assert field_schema["required"] == ["id", "type", "title"]
    assert field_schema["additionalProperties"] is False
    assert field_schema["properties"]["options"]["items"]["required"] == [
        "value",
        "label",
    ]
    assert field_schema["properties"]["columns"]["items"]["required"] == [
        "id",
        "type",
        "title",
    ]
    update_form_data = all_actions["update_form_schema"]["properties"]["data"]
    operation_schemas = {
        variant["properties"]["op"]["enum"][0]: variant
        for variant in update_form_data["properties"]["operations"]["items"][
            "anyOf"
        ]
    }
    assert operation_schemas["add_field"]["required"] == ["op", "field"]
    assert operation_schemas["add_field"]["properties"]["field"]["required"] == [
        "id",
        "type",
        "title",
    ]
    assert operation_schemas["add_select_option"]["required"] == [
        "op",
        "schema_id",
        "option",
    ]
    assert operation_schemas["add_select_option"]["properties"]["option"][
        "required"
    ] == [
        "value",
        "label",
    ]
    update_data = full_actions["update_submission_fields"]["properties"]["data"]
    update_schema = update_data["properties"]["updates"]["items"]
    assert update_schema["required"] == ["schema_id", "new_value"]
    assert update_schema["properties"]["page"] == {"type": "string"}
    assert update_schema["properties"]["task"] == {"type": "string"}
    assert update_schema["properties"]["schema_id"] == {"type": "string"}
    assert update_schema["properties"]["new_value"] == {}
    assert "anyOf" not in update_schema
    organize_update_data = all_actions["update_submission_fields"]["properties"][
        "data"
    ]
    assert set(organize_update_data["properties"]) == {
        "page",
        "page_name",
        "task",
        "task_name",
    }
    assert "updates" not in organize_update_data["properties"]
    add_category_data = organize_actions["add_category"]["properties"]["data"]
    assert set(add_category_data["properties"]) == {
        "page",
        "page_action",
        "page_name",
        "category",
        "category_action",
        "category_name",
    }
    assert "anyOf" not in add_category_data
    assert "completed" not in add_category_data["properties"]
    assert "updates" not in add_category_data["properties"]
    assert organize_action_data["propertyOrdering"][:2] == [
        "name",
        "form_type",
    ]
    assert "submission" not in organize_action_data["properties"]
    assert "submission_empty_reason" not in organize_action_data["properties"]
    assert "submission" not in organize_action_data["propertyOrdering"]
    assert "submission_needed" not in organize_action_data["propertyOrdering"]
    assert "submission_request" not in organize_action_data["propertyOrdering"]
    assert "submission_context" not in organize_action_data["propertyOrdering"]
    assert "submission_empty_reason" not in organize_action_data["propertyOrdering"]

    ask_schema = ask_prompt.response_schema
    assert "answer_html" in ask_schema["properties"]
    assert "issues" not in ask_schema["required"]
    assert ask_prompt.allowed_actions == ()
    assert ask_schema["properties"]["actions"] == {
        "type": "array",
        "items": {"type": "object"},
        "maxItems": 0,
    }

    assert "move_page" not in create_actions
    assert tuple(create_actions) == create_prompt.allowed_actions


# @features ai-report
# @dimensions structured-output schema provider-validation
@pytest.mark.unit
def test_report_response_schema_uses_provider_compatible_any_of_nodes():
    """Gemini requires anyOf to be the only field at its schema node."""
    schemas = [
        organize.report_proposal_response_schema(
            organize.ACTION_ORDER,
            include_submission_fields=include_submission_fields,
        )
        for include_submission_fields in (False, True)
    ]

    def provider_schema_errors(value, path="schema"):
        errors = []
        if isinstance(value, dict):
            if "anyOf" in value and set(value) != {"anyOf"}:
                errors.append(f"{path}: anyOf has sibling fields")
            required = value.get("required")
            if isinstance(required, list) and required:
                properties = value.get("properties")
                if not properties:
                    errors.append(f"{path}: required fields without properties")
                else:
                    missing = set(required) - set(properties)
                    if missing:
                        errors.append(
                            f"{path}: required fields missing properties: "
                            f"{sorted(missing)}"
                        )
            for key, child in value.items():
                errors.extend(provider_schema_errors(child, f"{path}.{key}"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                errors.extend(provider_schema_errors(child, f"{path}[{index}]"))
        return errors

    assert [
        error
        for schema in schemas
        for error in provider_schema_errors(schema)
    ] == []
    for schema in schemas:
        genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )


# @features ai-report
# @dimensions action-capabilities permissions
@pytest.mark.unit
def test_report_prompts_filter_actions_by_user_permissions():
    user = _permissioned_user(
        "category-editor",
        {
            "cat-readable": "VIEW",
            "cat-editable": "EDIT",
        },
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Scoped report",
            "hash": "scoped-report",
            "parent": user,
            "user": user,
            "instructions": "Save this.",
            "input_files": [],
        },
    )

    with MockRestrictions().patch_cache():
        organize_prompt = organize.organize_prompt(report, user)
        ask_prompt = ask.ask_prompt(report, user)
        create_prompt = create.create_prompt(report, user)

    assert organize_prompt.allowed_actions == (
        "create_page",
        "create_task",
        "add_form_to_page",
        "add_category",
        "update_submission_fields",
        "attach_file_to_page",
        "attach_file_to_task",
        "skip",
        "needs_review",
    )
    assert ask_prompt.allowed_actions == ()
    assert create_prompt.allowed_actions == (
        "create_page",
        "create_task",
        "needs_review",
    )

    assert tuple(_response_action_schemas(organize_prompt)) == (
        organize_prompt.allowed_actions
    )
    permissions = _prompt_context_json(
        organize_prompt,
        "Report Action Permissions",
    )
    capabilities = permissions["capabilities"]
    assert capabilities == {
        "can_create_forms": False,
        "can_create_categories": False,
        "can_create_projects": False,
        "can_create_model_tasks": False,
        "can_create_pages": True,
        "can_create_tasks": True,
        "can_attach_files_to_pages": True,
        "can_add_forms_to_pages": True,
        "can_attach_files_to_tasks": True,
        "can_add_page_categories": True,
        "can_update_form_schemas": False,
        "can_update_submissions": True,
        "can_delete_pages": False,
    }
    assert permissions["allowed_actions"] == list(organize_prompt.allowed_actions)


# @features ai-report
# @dimensions generate validate
@pytest.mark.unit
def test_generate_organize_report_validates_ai_output(monkeypatch):
    proposal = {
        "summary": "Skip unsupported input.",
        "confidence": 0.6,
        "actions": [{"type": "skip", "reason": "Nothing to organize."}],
    }

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(lambda prompt: proposal),
    )

    assert organize.generate_organize_plan(object()) == proposal


# @features ai-report
# @dimensions generate validate repair
@pytest.mark.unit
def test_generate_organize_report_repairs_invalid_action_type_once(monkeypatch):
    invalid = {
        "summary": "Attach the file.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "attach_file",
                "type": "attach_file_page",
                "data": {"page": "page-id", "file": "file-id"},
            }
        ],
    }
    repaired = {
        "summary": "Attach the file.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "attach_file",
                "type": "attach_file_to_page",
                "data": {"page": "page-id", "file": "file-id"},
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["type"] == "attach_file_to_page"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    assert calls[1].thinking_budget is None


# @features ai-report
# @dimensions repair file-placement
@pytest.mark.unit
def test_generate_organize_report_repairs_missing_file_attachments(monkeypatch):
    invalid = {
        "summary": "Create two record pages.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "school_logs",
                "type": "create_page",
                "data": {"name": "School Logs"},
            },
            {
                "id": "school_resources",
                "type": "create_page",
                "data": {"name": "School Resources"},
            },
        ],
    }
    repaired = {
        **invalid,
        "summary": "Create two record pages and attach their source files.",
        "actions": [
            *invalid["actions"],
            {
                "id": "attach_log",
                "type": "attach_file_to_page",
                "data": {"page_action": "school_logs", "file": "file-log-id"},
            },
            {
                "id": "attach_resource",
                "type": "attach_file_to_page",
                "data": {
                    "page_action": "school_resources",
                    "file": "file-resource-id",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
        context_blocks=[
            {
                "label": "Report Input Files",
                "value": (
                    "```\n"
                    '[{"report_file_ref": "file-log-id"}, '
                    '{"report_file_ref": "file-resource-id"}]'
                    "\n```"
                ),
            }
        ],
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["data"]["file"] for action in result["actions"][2:]] == [
        "file-log-id",
        "file-resource-id",
    ]
    assert len(calls) == 2
    assert "attach every report input file" in _prompt_context(
        calls[1], "Validation Error"
    )
    repair_text = calls[1].preview()
    assert "Every exact report_file_ref must appear" in repair_text
    assert "Creating a page or task" in repair_text


# @features ai-report
# @dimensions fallback file-placement
@pytest.mark.unit
def test_generate_organize_report_reviews_files_missing_after_repair(monkeypatch):
    incomplete = {
        "summary": "Create the records page.",
        "confidence": 0.6,
        "issues": [],
        "actions": [
            {
                "id": "records",
                "type": "create_page",
                "data": {"name": "Records"},
            }
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return incomplete

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(context),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
        context_blocks=[
            {
                "label": "Report Input Files",
                "value": '```\n[{"report_file_ref": "missing-file-id"}]\n```',
            }
        ],
    )

    result = organize.generate_organize_plan(prompt)

    assert len(calls) == 2
    assert result["actions"][0]["type"] == "needs_review"
    assert result["confidence"] == 0
    assert captured == []


# @features ai-report
# @dimensions repair references
@pytest.mark.unit
def test_generate_organize_report_repairs_invalid_action_references_once(monkeypatch):
    invalid = {
        "summary": "Record the invoice.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_task_sousa_doors_final_invoice",
                "type": "create_task",
                "data": {
                    "name": "Sousa Doors Final Invoice",
                    "page_action": (
                        "2,000.00 deposit paid on Jan 27, 2021 via check 1096. "
                        "Remaining $2,250.00 balance due by Feb 26, 2021."
                    ),
                },
            }
        ],
    }
    repaired = {
        "summary": "Record the invoice.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_sousa_doors_page",
                "type": "create_page",
                "data": {"name": "Sousa Doors"},
            },
            {
                "id": "create_task_sousa_doors_final_invoice",
                "type": "create_task",
                "data": {
                    "name": "Sousa Doors Final Invoice",
                    "page_action": "create_sousa_doors_page",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_page", "create_task", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][1]["data"]["page_action"] == "create_sousa_doors_page"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )


# @features ai-report
# @dimensions repair references
@pytest.mark.unit
def test_generate_organize_report_repairs_category_used_as_page_reference(monkeypatch):
    invalid = {
        "summary": "File the attendance form.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "attach_attendance",
                "type": "attach_file_to_page",
                "data": {
                    "page": "hash:abc123def456",
                    "page_name": "Homeschool",
                    "file": "hash:def456abc789",
                },
            }
        ],
    }
    repaired = {
        "summary": "File the attendance form.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "create_administration_page",
                "type": "create_page",
                "data": {
                    "name": "Administration",
                    "category": "hash:abc123def456",
                },
            },
            {
                "id": "attach_attendance",
                "type": "attach_file_to_page",
                "data": {
                    "page_action": "create_administration_page",
                    "file": "hash:def456abc789",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "abc123def456": {
                "id": "category-id",
                "kind": "category",
                "name": "Homeschool",
            },
            "def456abc789": {
                "id": "file-id",
                "kind": "file",
                "name": "attendanceform",
            },
        },
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "attach_file_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert len(calls) == 2
    assert result["actions"][0]["data"]["category"] == "category-id"
    assert result["actions"][1]["data"]["page_action"] == (
        "create_administration_page"
    )
    assert result["actions"][1]["data"]["file"] == "file-id"
    assert "uses category 'Homeschool' as its page reference" in _prompt_context(
        calls[1], "Validation Error"
    )


# @features ai-report
# @dimensions repair required-data
@pytest.mark.unit
def test_generate_organize_report_repairs_invalid_action_data_shape(monkeypatch):
    invalid = {
        "summary": "Centralize family files.",
        "confidence": 0.7,
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
                    "display_name": "Richardson Family Records.pdf",
                    "to_page_action": "create_family_records_page",
                },
            },
        ],
    }
    repaired = {
        "summary": "Centralize family files.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "create_family_records_page",
                "type": "create_page",
                "data": {"name": "Family Records"},
            },
            {
                "id": "move_file_richardson",
                "type": "move_file",
                "data": {
                    "file": "richardson-file-id",
                    "display_name": "Richardson Family Records.pdf",
                    "from_page": "richardson-source-page-id",
                    "from_page_name": "Richardson Records",
                    "to_page_action": "create_family_records_page",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    captured_repairs = []
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured_repairs.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_page", "move_file", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="ask report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["data"]["name"] == "Family Records"
    assert result["actions"][1]["data"]["from_page"] == "richardson-source-page-id"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    assert captured_repairs == []


# @features ai-report
# @dimensions repair add-category required-data
@pytest.mark.unit
def test_generate_organize_report_repairs_missing_add_category_target(monkeypatch):
    invalid = {
        "summary": "Add Sheik Orthodontics to Lucy.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "add_sheik_ortho_to_lucy",
                "type": "add_category",
                "data": {
                    "page": "lucy-page-id",
                    "page_name": "Lucy",
                    "category_name": "Sheik Orthodontics",
                },
            }
        ],
    }
    repaired = {
        "summary": "Add Sheik Orthodontics to Lucy.",
        "confidence": 0.7,
        "issues": [
            (
                "The Sheik Orthodontics category could not be identified from "
                "the proposal."
            )
        ],
        "actions": [
            {
                "id": "review_sheik_ortho_category",
                "type": "needs_review",
                "data": {
                    "note": (
                        "Choose the Sheik Orthodontics category before adding "
                        "it to Lucy."
                    ),
                    "questions": [
                        "Which existing category should be added to Lucy?",
                    ],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("add_category", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["type"] == "needs_review"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )


# @features ai-report
# @dimensions validate submission
@pytest.mark.unit
def test_generate_organize_plan_leaves_form_submission_for_completion(monkeypatch):
    invalid = {
        "summary": "Create a pharmacy page.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_cvs_pharmacy",
                "type": "create_page",
                "data": {
                    "name": "CVS Pharmacy",
                    "form": "business-form-id",
                    "form_name": "Business",
                },
            }
        ],
    }
    repaired = {
        "summary": "Create a pharmacy page.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_cvs_pharmacy",
                "type": "create_page",
                "data": {
                    "name": "CVS Pharmacy",
                    "form": "business-form-id",
                    "form_name": "Business",
                    "submission": {
                        "input-business-name": "CVS Pharmacy",
                    },
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert "submission" not in result["actions"][0]["data"]
    assert len(calls) == 1


# @features ai-report
# @dimensions repair empty-form capture
@pytest.mark.unit
def test_generate_organize_report_repairs_empty_form_schema_without_capture(monkeypatch):
    invalid = {
        "summary": "Create a record form.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "record_form",
                "type": "create_form",
                "data": {
                    "name": "Record Form",
                    "form_type": "page",
                    "schema": [],
                },
            }
        ],
    }
    repaired = {
        "summary": "Create a record form.",
        "confidence": 0.7,
        "actions": [
            {
                "id": "record_form_review",
                "type": "needs_review",
                "data": {
                    "note": "No useful structured fields were identified.",
                    "questions": ["What fields should the form collect?"],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid if len(calls) == 1 else repaired

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    captured_repairs = []
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured_repairs.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_form", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["type"] == "needs_review"
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    assert 'get_guidelines("page_form")' in calls[1].preview()
    assert "Do not merely claim a schema was corrected" in calls[1].preview()
    assert "Do not replace a form action with needs_review merely" in (
        calls[1].preview()
    )
    assert captured_repairs == []


# @features ai-report
# @dimensions deterministic-repair schema-field-id
@pytest.mark.unit
def test_generate_organize_report_repairs_create_form_field_missing_id(monkeypatch):
    invalid = {
        "summary": "Create an orthodontist form.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_orthodontist_form",
                "type": "create_form",
                "data": {
                    "name": "Orthodontist",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-practice-name",
                            "type": "input",
                            "title": "Practice Name",
                        },
                        {
                            "type": "textarea",
                            "title": "Treatment Notes",
                        },
                    ],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return invalid

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )

    prompt = SimpleNamespace(
        allowed_actions=("create_form", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    fields = result["actions"][0]["data"]["schema"]
    assert [field["id"] for field in fields] == [
        "input-practice-name",
        "textarea-treatment-notes",
    ]
    assert fields[0]["input"] == "text"
    assert len(calls) == 1


# @pair ai-report:deterministic-repair
# @pair ai-report:schema-update
# @pair form-schema:deterministic-repair
# @pair form-schema:schema-update
@pytest.mark.unit
def test_generate_organize_report_completes_additive_schema_field(monkeypatch):
    proposal = {
        "summary": "Add a payment reference field.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "add_payment_reference",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {
                            "op": "add_field",
                            "field": {
                                "type": "input",
                                "label": "Payment Reference",
                            },
                        }
                    ],
                },
            }
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return proposal

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("update_form_schema", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    field = result["actions"][0]["data"]["operations"][0]["field"]
    assert field == {
        "id": "input-payment-reference",
        "type": "input",
        "input": "text",
        "label": "Payment Reference",
        "title": "Payment Reference",
    }
    assert len(calls) == 1


# @pair ai-report:deterministic-repair
# @pair ai-report:form-type
# @pair form-schema:form-type
@pytest.mark.unit
def test_generate_organize_report_infers_create_form_type_from_usage(monkeypatch):
    proposal = {
        "summary": "Propose a record category and form.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "create_record_form",
                "type": "create_form",
                "data": {
                    "name": "Record Form",
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
                "id": "create_record_category",
                "type": "create_category",
                "data": {
                    "name": "Records",
                    "form_action": "create_record_form",
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return proposal

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_form", "create_category", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][0]["data"]["form_type"] == "page"
    assert len(calls) == 1


# @features ai-report
# @dimensions deterministic-repair page-form references
@pytest.mark.unit
def test_generate_organize_report_infers_unambiguous_add_form_reference(monkeypatch):
    proposal = {
        "summary": "Use the property-tax form on the existing Toft page.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "create_property_tax_form",
                "type": "create_form",
                "data": {
                    "name": "Property Tax Record",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-apn",
                            "type": "input",
                            "input": "text",
                            "title": "Assessor Parcel Number",
                        }
                    ],
                },
            },
            {
                "id": "create_payment_form",
                "type": "create_form",
                "data": {
                    "name": "Payment Record",
                    "form_type": "task",
                    "schema": [
                        {
                            "id": "date-paid-on",
                            "type": "date",
                            "title": "Paid On",
                        }
                    ],
                },
            },
            {
                "id": "add_form_to_toft",
                "type": "add_form_to_page",
                "display_label": "Apply Property Tax Form to Toft Property Tax Page",
                "data": {"page": "toft-property-tax-page"},
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return proposal

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_form", "add_form_to_page", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["actions"][2]["data"] == {
        "page": "toft-property-tax-page",
        "form_action": "create_property_tax_form",
    }
    assert "form_action" not in proposal["actions"][2]["data"]
    assert len(calls) == 1


# @features ai-report
# @dimensions needs-review references page-form per-action-fallback fallback
@pytest.mark.unit
def test_generate_organize_report_reviews_ambiguous_missing_add_form_reference(
    monkeypatch,
):
    invalid = {
        "summary": "Prepare the property-tax records.",
        "confidence": 0.6,
        "issues": [],
        "actions": [
            {
                "id": "create_property_tax_form",
                "type": "create_form",
                "data": {
                    "name": "Property Tax Record",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-apn",
                            "type": "input",
                            "input": "text",
                            "title": "Assessor Parcel Number",
                        }
                    ],
                },
            },
            {
                "id": "create_property_summary_form",
                "type": "create_form",
                "data": {
                    "name": "Property Summary",
                    "form_type": "page",
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
                "id": "add_form_to_toft",
                "type": "add_form_to_page",
                "display_label": "Apply a Form to Toft Property Tax Page",
                "data": {"page": "toft-property-tax-page"},
            },
            {
                "id": "keep_source_summary",
                "type": "skip",
                "data": {"note": "The source summary is already retained."},
            },
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )
    prompt = SimpleNamespace(
        allowed_actions=(
            "create_form",
            "add_form_to_page",
            "skip",
            "needs_review",
        ),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["type"] for action in result["actions"]] == [
        "create_form",
        "create_form",
        "needs_review",
        "skip",
    ]
    review = result["actions"][2]
    assert review["id"] == "add_form_to_toft"
    assert review["display_label"] == "Apply a Form to Toft Property Tax Page"
    assert review["data"]["questions"] == [
        "Which existing or proposed form should this action use?"
    ]
    assert "workspace reference was unclear" in result["issues"][-1]
    assert result["summary"] == invalid["summary"]
    assert len(calls) == 2
    _assert_repair_prompt_contract(
        calls[1],
        invalid_proposal=invalid,
        allowed_actions=prompt.allowed_actions,
    )
    repair_text = calls[1].preview()
    assert "add_form_to_page actions must include both" in repair_text
    assert "data.form/data.form_action" in repair_text
    assert captured == []


# @features ai-report
# @dimensions needs-review references per-action-fallback
@pytest.mark.unit
def test_generate_organize_report_reviews_unresolved_references_after_failed_repair(
    monkeypatch,
):
    invalid = {
        "summary": "Record the legal payment.",
        "confidence": 0.6,
        "issues": [],
        "actions": [
            {
                "id": "keep_summary",
                "type": "skip",
                "data": {"note": "The source file is already summarized."},
            },
            {
                "id": "create_task_legal_payment",
                "type": "create_task",
                "data": {
                    "name": "Legal Retainer Payment",
                    "page_action": (
                        "$1,500.00 credit card transaction for legal "
                        "representation retainer."
                    ),
                },
            },
        ],
    }
    calls = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_task", "skip", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["type"] for action in result["actions"]] == [
        "skip",
        "needs_review",
    ]
    review = result["actions"][1]
    assert review["display_label"] == "Legal Retainer Payment"
    assert "could not be linked safely" in review["reason"]
    assert "needs review" in result["issues"][-1]
    assert len(calls) == 2
    assert "Do not mention validation errors" in calls[1].preview()


# @features ai-report
# @dimensions needs-review per-action-fallback malformed-data
@pytest.mark.unit
def test_generate_organize_report_downgrades_malformed_action_after_failed_repair(
    monkeypatch,
):
    invalid = {
        "summary": "Create a divorce form.",
        "confidence": 0.5,
        "actions": [
            {
                "id": "create_divorce_form",
                "type": "create_form",
                "data": {
                    "name": "Divorce",
                    "schema": [{"type": "textarea", "title": "Notes"}],
                },
            }
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_form", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert result["summary"] == "Create a divorce form."
    assert result["confidence"] == 0.5
    assert [action["type"] for action in result["actions"]] == ["needs_review"]
    assert result["actions"][0]["display_label"] == "Divorce"
    assert result["actions"][0]["data"]["questions"] == [
        "What exact workspace record and values should this action use?"
    ]
    assert "Divorce needs review because its action data was incomplete." in result[
        "issues"
    ]
    assert len(calls) == 2
    assert captured == []


# @features ai-report
# @dimensions needs-review references per-action-fallback
@pytest.mark.unit
def test_generate_organize_report_downgrades_missing_category_without_sentry_capture(
    monkeypatch,
):
    invalid = {
        "summary": "Organize the comic book drawer plans.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "create_comic_drawers_page",
                "type": "create_page",
                "display_label": "Create page for Comic Book Drawers Plan",
                "data": {"name": "Comic Book Drawers Plan"},
            },
            {
                "id": "add_comics_category_to_drawers",
                "type": "add_category",
                "display_label": "Add Comics category to Comic Book Drawers",
                "data": {
                    "completed": False,
                    "completed_on": None,
                    "due_date": None,
                    "note": None,
                    "page_action": "create_comic_drawers_page",
                    "questions": [],
                    "to_page": None,
                    "to_task": None,
                    "updates": [],
                },
            },
        ],
    }
    calls = []
    captured = []

    def fake_generate(prompt):
        calls.append(prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(fake_generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )
    prompt = SimpleNamespace(
        allowed_actions=("create_page", "add_category", "needs_review"),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
    )

    result = organize.generate_organize_plan(prompt)

    assert [action["type"] for action in result["actions"]] == [
        "create_page",
        "needs_review",
    ]
    assert result["actions"][1]["id"] == "add_comics_category_to_drawers"
    assert result["actions"][1]["data"]["questions"] == [
        "Which existing or proposed category should this action use?"
    ]
    assert len(calls) == 2
    assert captured == []


# @features ai-report form-schema
# @dimensions proposal validation schema-update
@pytest.mark.unit
def test_validate_proposal_rejects_unsafe_schema_update_operations():
    proposal = {
        "summary": "Delete an existing form field.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "delete_payment_reference",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {"op": "delete_field", "schema_id": "input-reference"}
                    ],
                },
            }
        ],
    }

    with pytest.raises(exceptions.AIException, match="unsupported op"):
        organize.validate_proposal(proposal)


# @features ai-report
# @dimensions proposal validation move-references
@pytest.mark.unit
@pytest.mark.parametrize(
    ("action_type", "data", "missing"),
    [
        ("move_page", {"category": "medical"}, "page"),
        ("move_page", {"page": "eyes"}, "category"),
        ("move_task", {"page": "lucy-eyes"}, "task"),
        pytest.param(
            "move_task",
            {"task": "specialist-consultation"},
            "to_page",
            id="move_task-data3-page",
        ),
    ],
)
def test_validate_proposal_requires_move_entity_references(
    action_type,
    data,
    missing,
):
    proposal = {
        "summary": "Move an existing workspace record.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "move_record",
                "type": action_type,
                "data": data,
            }
        ],
    }

    with pytest.raises(exceptions.AIException, match=rf"requires data\.{missing}"):
        organize.validate_proposal(proposal)


# @features ai-report
# @dimensions proposal validation rename canonical-target legacy-target
@pytest.mark.unit
def test_validate_proposal_accepts_rename_and_move_task_target_aliases():
    proposal = {
        "summary": "Rename a page and consolidate its tasks.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "rename_page",
                "type": "rename_entity",
                "data": {"entity": "orthodontics-page", "name": "Teeth"},
            },
            {
                "id": "canonical_move",
                "type": "move_task",
                "data": {
                    "task": "invisalign-task",
                    "to_page": "orthodontics-page",
                },
            },
            {
                "id": "legacy_move",
                "type": "move_task",
                "data": {
                    "task": "sealants-task",
                    "page": "orthodontics-page",
                },
            },
        ],
    }

    assert organize.validate_proposal(proposal) == proposal

    for data, missing in (
        ({"name": "Teeth"}, "entity"),
        ({"entity": "orthodontics-page"}, "name"),
    ):
        invalid = copy.deepcopy(proposal)
        invalid["actions"] = [
            {"id": "rename_page", "type": "rename_entity", "data": data}
        ]
        with pytest.raises(
            exceptions.AIException,
            match=rf"rename_page \(rename_entity\) requires data\.{missing}",
        ):
            organize.validate_proposal(invalid)


# @features ai-report
# @dimensions create generate validate
@pytest.mark.unit
def test_generate_create_report_validates_non_empty_actions(monkeypatch):
    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(
            lambda prompt: {
                "summary": "No actions.",
                "confidence": 0.5,
                "actions": [],
            }
        ),
    )

    with pytest.raises(exceptions.AIException, match="at least one action"):
        create.generate_create_report(object())

    proposal = {
        "summary": "Create a page.",
        "confidence": 0.8,
        "actions": [{"type": "create_page", "data": {"name": "Generated"}}],
    }
    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(lambda prompt: proposal),
    )

    assert create.generate_create_report(object()) == proposal


# @features ai-report
# @dimensions proposal validation explicit-task-identity
@pytest.mark.unit
def test_validate_proposal_requires_completed_root_task_targets():
    with pytest.raises(
        exceptions.AIException,
        match="target an existing task only for a completed occurrence",
    ):
        organize.validate_proposal(
            {
                "summary": "Invalid active task target.",
                "actions": [
                    {
                        "id": "active_task",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": "prescriptions-page",
                            "task": "lisinopril-task",
                        },
                    }
                ],
            }
        )

    proposal = {
        "summary": "Record two occurrences of one prescription.",
        "actions": [
            {
                "id": "lisinopril_current",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": "prescriptions-page",
                    "completed_on": "2025-03-01",
                },
            },
            {
                "id": "lisinopril_prior",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": "prescriptions-page",
                    "task_action": "lisinopril_current",
                    "completed_on": "2024-03-01",
                },
            },
        ],
    }
    assert organize.validate_proposal(copy.deepcopy(proposal))["issues"] == []

    proposal["actions"].append(
        {
            "id": "lisinopril_chained",
            "type": "create_task",
            "data": {
                "name": "Lisinopril Prescription",
                "page": "prescriptions-page",
                "task_action": "lisinopril_prior",
                "completed": True,
            },
        }
    )
    with pytest.raises(
        exceptions.AIException,
        match="earlier untargeted completed create_task",
    ):
        organize.validate_proposal(proposal)


# @features ai-report
# @dimensions proposal validation dependencies
@pytest.mark.unit
def test_validate_proposal_rejects_unknown_actions_and_bad_dependencies(monkeypatch):
    hash_lookups = []

    def fake_get_details_by_hash(hashes):
        hash_lookups.append(list(hashes))
        return {
            "abc123def456": {"id": "page-id"},
            "def456abc789": {"id": "file-id"},
        }

    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        fake_get_details_by_hash,
    )

    with pytest.raises(exceptions.AIException, match="Unknown organize action"):
        organize.validate_proposal(
            {"summary": "Nope", "confidence": 0.1, "actions": [{"type": "dance"}]}
        )

    with pytest.raises(exceptions.AIException, match="depends on unknown"):
        organize.validate_proposal(
            {
                "summary": "Bad dependency",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {
                            "name": "Bad Reference Page",
                            "category_action": "later",
                        },
                    },
                    {"id": "later", "type": "create_category", "data": {}},
                ],
            }
        )

    cleaned_dependencies = organize.validate_proposal(
        {
            "summary": "Bad explicit dependency note",
            "confidence": 0.5,
            "actions": [
                {"id": "page", "type": "create_page", "data": {"name": "Page"}},
                {
                    "id": "create_task_sousa_doors_final_invoice",
                    "type": "create_task",
                    "depends_on": [
                        "$page",
                        (
                            "2,000.00 deposit paid on Jan 27, 2021 via check 1096. "
                            "Remaining $2,250.00 balance due by Feb 26, 2021."
                        ),
                    ],
                    "data": {"name": "Sousa Doors Final Invoice"},
                },
            ],
        }
    )
    assert cleaned_dependencies["actions"][1]["depends_on"] == ["$page"]
    assert cleaned_dependencies["issues"] == []

    with pytest.raises(exceptions.AIException, match="not allowed"):
        organize.validate_proposal(
            {
                "summary": "Forbidden",
                "confidence": 0.1,
                "actions": [{"type": "create_category", "data": {}}],
            },
            allowed_actions={"skip", "needs_review"},
        )

    with pytest.raises(exceptions.AIException, match="issues"):
        organize.validate_proposal(
            {
                "summary": "Bad issues",
                "confidence": 0.1,
                "issues": "Nope",
                "actions": [],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"create_page\) requires data.name",
    ):
        organize.validate_proposal(
            {
                "summary": "Nameless page",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "create_morrissey_compton_page",
                        "type": "create_page",
                        "display_label": (
                            "Create Morrissey-Compton Educational Center Page"
                        ),
                        "data": {},
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"create_form\) requires at least one data.schema field",
    ):
        organize.validate_proposal(
            {
                "summary": "Blank form",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "empty_form",
                        "type": "create_form",
                        "data": {
                            "name": "Empty Form",
                            "form_type": "page",
                            "schema": [],
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"data.schema\[1\] requires title",
    ):
        organize.validate_proposal(
            {
                "summary": "Bad form field",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "bad_form",
                        "type": "create_form",
                        "data": {
                            "name": "Bad Form",
                            "form_type": "page",
                            "schema": [{"id": "input-name", "type": "input"}],
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        organize.validate_proposal(
            {
                "summary": "Page form without submission",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "cvs_pharmacy_page",
                        "type": "create_page",
                        "data": {
                            "name": "CVS Pharmacy",
                            "form_name": "Business",
                        },
                    },
                ],
            }
        )

    pending_submission = organize.validate_proposal(
        {
            "summary": "Page form with pending completion",
            "confidence": 0.8,
            "actions": [
                {
                    "id": "cvs_pharmacy_page",
                    "type": "create_page",
                    "data": {
                        "name": "CVS Pharmacy",
                        "form_name": "Business",
                    },
                },
            ],
        },
        allow_pending_submissions=True,
    )
    assert "submission" not in pending_submission["actions"][0]["data"]
    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        organize.validate_proposal(
            pending_submission,
            allow_pending_submissions=False,
        )

    empty_completed_submission = organize.validate_proposal(
        {
            "summary": "Page form with completed empty submission pass",
            "confidence": 0.8,
            "actions": [
                {
                    "id": "cvs_pharmacy_page",
                    "type": "create_page",
                    "data": {
                        "name": "CVS Pharmacy",
                        "form_name": "Business",
                        "submission": {},
                        "submission_empty_reason": (
                            "No submission fields were filled from the available evidence."
                        ),
                    },
                },
            ],
        },
        allow_pending_submissions=False,
    )
    assert empty_completed_submission["actions"][0]["data"][
        "submission_empty_reason"
    ] == "No submission fields were filled from the available evidence."

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        organize.validate_proposal(
            {
                "summary": "Task form with empty submission",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "screening_task",
                        "type": "create_task",
                        "data": {
                            "name": "Athletic Screening",
                            "page": "julie-page-id",
                            "form": "doctor-appointment-form-id",
                            "submission": {},
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"move_file\) requires exactly one source",
    ):
        organize.validate_proposal(
            {
                "summary": "Missing move source",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "family_records",
                        "type": "create_page",
                        "data": {"name": "Family Records"},
                    },
                    {
                        "id": "move_file_richardson",
                        "type": "move_file",
                        "data": {
                            "file": "richardson-file-id",
                            "display_name": "Richardson Family Records.pdf",
                            "to_page_action": "family_records",
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"add_category\) requires data.page",
    ):
        organize.validate_proposal(
            {
                "summary": "Missing page category add",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "add_records_category",
                        "type": "add_category",
                        "data": {"category": "records-category-id"},
                    },
                ],
            }
        )
    with pytest.raises(
        exceptions.AIException,
        match=r"update_submission_fields\) requires at least one data.updates row",
    ):
        organize.validate_proposal(
            {
                "summary": "Empty submission update",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "empty_submission_update",
                        "type": "update_submission_fields",
                        "data": {"updates": []},
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"data.updates\[1\] requires exactly one page or task",
    ):
        organize.validate_proposal(
            {
                "summary": "Malformed submission update",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "bad_submission_update",
                        "type": "update_submission_fields",
                        "data": {
                            "updates": [
                                {
                                    "schema_id": "select-rank",
                                    "new_value": "white-belt",
                                }
                            ]
                        },
                    },
                ],
            }
        )

    recoverable_file_reference_proposal = organize.validate_proposal(
        {
            "summary": "Recoverable file reference problems",
            "confidence": 0.1,
            "issues": [
                "Some file references were readable labels instead of executable refs."
            ],
            "actions": [
                {
                    "id": "create_pettis_remodeling_design_page",
                    "type": "create_page",
                    "data": {"name": "Pettis Remodeling Design"},
                },
                {
                    "id": "attachment",
                    "type": "attach_file_to_page",
                    "data": {
                        "page": "existing-page",
                        "file_name": "Pettis Proposal",
                    },
                },
                {
                    "id": "completed_task_display_file",
                    "type": "create_task",
                    "data": {
                        "page": "existing-page",
                        "completed_on": "2023-06-24",
                        "file_label": "Pettis Proposal",
                    },
                },
                {
                    "id": "completed_task_no_file",
                    "type": "create_task",
                    "display_label": "ToDo's? All Done! Service Agreement",
                    "data": {
                        "name": "Robbyn Willebeek-LeMair PM Agreement",
                        "page": "$create_pettis_remodeling_design_page",
                        "completed_on": "2014-06-09",
                        "model": "project-management-design-model",
                    },
                },
            ],
        }
    )
    assert recoverable_file_reference_proposal["summary"] == (
        "Recoverable file reference problems"
    )
    assert recoverable_file_reference_proposal["issues"] == [
        "Some file references were readable labels instead of executable refs."
    ]

    with pytest.raises(exceptions.AIException, match="attach_file_to_task"):
        organize.validate_proposal(
            {
                "summary": "Invalid task attachment shape",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "completed_task_with_file",
                        "type": "create_task",
                        "data": {
                            "page": "existing-page",
                            "completed_on": "2023-06-24",
                            "file": "registration.pdf",
                        },
                    },
                ],
            }
        )

    proposal = organize.validate_proposal(
        {
            "summary": "OK",
            "confidence": 0.9,
            "actions": [
                {
                    "id": "form",
                    "type": "create_form",
                    "data": {
                        "name": "Record Form",
                        "form_type": "page",
                        "schema": [
                            {
                                "id": "input-name",
                                "type": "input",
                                "input": "text",
                                "title": "Name",
                            }
                        ],
                    },
                },
                {
                    "id": "category",
                    "type": "create_category",
                    "data": {"form_action": "form"},
                },
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {"page": "existing-page"},
                },
                {
                    "id": "completed_task",
                    "type": "create_task",
                    "data": {
                        "page": "existing-page",
                        "completed_on": "2023-06-24",
                    },
                },
                {
                    "id": "completed_task_attachment",
                    "type": "attach_file_to_task",
                    "data": {
                        "task_action": "completed_task",
                        "file": "registration.pdf",
                    },
                },
            ],
        }
    )
    assert proposal["summary"] == "OK"
    assert proposal["issues"] == []

    normalized = organize.validate_proposal(
        {
            "summary": "Normalize hash refs",
            "confidence": 0.9,
            "actions": [
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {
                        "page": "hash:abc123def456",
                        "description": "Unknown hash:000000000000 stays visible.",
                        "submission": {
                            "input-abc123def456": "Schema ids are not references."
                        },
                    },
                },
                {
                    "id": "attach_task_file",
                    "type": "attach_file_to_task",
                    "data": {
                        "task_action": "task",
                        "file": "hash:def456abc789",
                    },
                },
            ],
        }
    )

    assert set(hash_lookups[0]) == {
        "abc123def456",
        "def456abc789",
        "000000000000",
    }
    assert normalized["actions"][0]["data"]["page"] == "page-id"
    assert normalized["actions"][1]["data"]["file"] == "file-id"
    assert normalized["actions"][0]["data"]["description"] == (
        "Unknown hash:000000000000 stays visible."
    )
    assert normalized["actions"][0]["data"]["submission"] == {
        "input-abc123def456": "Schema ids are not references."
    }


# @features ai-report
# @dimensions proposal validation submission action-reference-namespace
@pytest.mark.unit
def test_validate_proposal_treats_action_like_submission_fields_as_content():
    proposal = {
        "summary": "Record contract and compensation details.",
        "issues": [],
        "actions": [
            {
                "id": "contracts_page",
                "type": "create_page",
                "data": {"name": "Contracts"},
            },
            {
                "id": "contract_task",
                "type": "create_task",
                "data": {
                    "name": "Nate Patrin 2021 contract",
                    "page_action": "contracts_page",
                    "submission": {
                        "action": (
                            "4,175.00 in nonemployee compensation. No federal "
                            "or state income tax withholding was reported."
                        ),
                        "payment_action": (
                            "2500 total payment for 100 capsule album reviews."
                        ),
                    },
                },
            },
        ],
    }

    validated = organize.validate_proposal(copy.deepcopy(proposal))

    assert validated["actions"][1]["data"]["submission"] == proposal["actions"][1][
        "data"
    ]["submission"]


# @features ai-report
# @dimensions proposal validation file-placement
@pytest.mark.unit
def test_validate_proposal_requires_every_report_file_attachment():
    proposal = {
        "summary": "Attach one of two files.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "attach_first",
                "type": "attach_file_to_page",
                "data": {"page": "existing-page", "file": "first-file-id"},
            },
            {
                "id": "unresolved_second",
                "type": "attach_file_to_page",
                "data": {"file": "second-file-id"},
            },
        ],
    }

    with pytest.raises(
        exceptions.AIException,
        match=r"Missing report_file_ref values: second-file-id",
    ):
        organize.validate_proposal(
            proposal,
            required_file_refs=("first-file-id", "second-file-id"),
        )

    proposal["actions"][1]["data"]["task"] = "existing-task"
    proposal["actions"][1]["type"] = "attach_file_to_task"

    assert organize.validate_proposal(
        proposal,
        required_file_refs=("first-file-id", "second-file-id"),
    )["actions"] == proposal["actions"]


# @features ai-report
# @dimensions validation page-form no-category
@pytest.mark.unit
def test_validate_proposal_accepts_add_form_to_page_without_category():
    proposal = {
        "summary": "Create a property-tax form and add it to the existing page.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "property_tax_form",
                "type": "create_form",
                "data": {
                    "name": "Property Tax Record",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-apn",
                            "type": "input",
                            "input": "text",
                            "title": "Assessor Parcel Number",
                        }
                    ],
                },
            },
            {
                "id": "add_property_tax_form",
                "type": "add_form_to_page",
                "depends_on": ["property_tax_form"],
                "data": {
                    "page": "existing-property-tax-page",
                    "form_action": "property_tax_form",
                },
            },
        ],
    }

    assert organize.validate_proposal(proposal) is proposal


# @pair ai-report:submission-completion
# @pair ai-report:generate
# @pair ai-report:pipeline
# @pair form-schema:structured-output
# @pair submission:focused-prompt
# @pair submission:evidence-mapping
@pytest.mark.unit
def test_generate_organize_report_completes_planned_submissions(monkeypatch):
    user = _test_user("complete-pipeline-owner")
    file = _test_file("pipeline-receipt.pdf", "application/pdf")
    file.summary = "Receipt from Acme dated 2026-07-10 for $42.00."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Complete pipeline report",
            "hash": "complete-pipeline-report",
            "parent": user,
            "user": user,
            "instructions": "Save this receipt.",
            "input_files": [file],
        },
    )
    planned = {
        "summary": "Create a receipt record.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "receipt_form",
                "type": "create_form",
                "data": {
                    "name": "Receipt",
                    "form_type": "page",
                    "schema": [
                        {"id": "input-merchant", "type": "input", "title": "Merchant"}
                    ],
                },
            },
            {
                "id": "receipt_category",
                "type": "create_category",
                "data": {"name": "Receipts", "form_action": "receipt_form"},
            },
            {
                "id": "receipt_page",
                "type": "create_page",
                "data": {"name": "Acme Receipt", "category_action": "receipt_category"},
            },
            {
                "id": "attach_receipt",
                "type": "attach_file_to_page",
                "data": {"page_action": "receipt_page", "file": file.urlsafe_key},
            },
        ],
    }
    calls = []

    def generate(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return planned
        return {
            "submissions": [
                {
                    "action_id": "receipt_page",
                    "submission": {"input-merchant": "Acme"},
                }
            ]
        }

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(generate),
    )
    prompt = SimpleNamespace(
        allowed_actions=(
            "create_form",
            "create_category",
            "create_page",
            "attach_file_to_page",
            "needs_review",
        ),
        output_format={"type": "JSON", "description": "Return report JSON."},
        prompt_type="organize report",
        user=None,
        tools=None,
        max_tool_iterations=None,
        max_tool_file_parts_per_turn=None,
    )

    result = organize.generate_organize_report(prompt, report, user)

    assert len(calls) == 2
    assert calls[1].prompt_type == "organize submission completion"
    assert result["actions"][2]["data"]["submission"] == {
        "input-merchant": "Acme"
    }


# @features ai-report
# @dimensions submission-completion focused-prompt evidence-mapping json-output prompt validation partial
@pytest.mark.unit
def test_complete_organize_submissions_uses_one_focused_prompt(
    monkeypatch,
    get_schema,
):
    user = _test_user("focused-completion-owner")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Medical Providers", "hash": "focused-medical"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Provider", "hash": "focused-provider-form"},
    )
    form.form_type = "page"
    form.schema = get_schema("text_input_only")
    category.db["form"] = form.key
    first = _test_file("visit-summary.pdf", "application/pdf")
    first.summary = (
        "Patient Lucy visited Stanford Children's Health on 2024-08-20; "
        "the provider was Dr. Rivera."
    )
    second = _test_file("provider-card.png", "image/png")
    second.summary = "Provider address is 725 Welch Road, Palo Alto."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Focused completion report",
            "hash": "focused-completion-report",
            "parent": user,
            "user": user,
            "instructions": "Save the provider and supporting visit records.",
            "input_files": [first, second],
        },
    )
    proposal = {
        "summary": "Create the provider record.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "provider_page",
                "type": "create_page",
                "reason": "The files support one provider record.",
                "data": {
                    "name": "Stanford Children's Health",
                    "category": category.urlsafe_key,
                },
            },
            {
                "id": "attach_visit",
                "type": "attach_file_to_page",
                "data": {"page_action": "provider_page", "file": first.urlsafe_key},
            },
            {
                "id": "attach_card",
                "type": "attach_file_to_page",
                "data": {"page_action": "provider_page", "file": second.urlsafe_key},
            },
        ],
    }
    entities = {
        category.urlsafe_key: category,
        category.key: category,
        form.urlsafe_key: form,
        form.key: form,
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return {
            "submissions": [
                {
                    "action_id": "provider_page",
                    "submission": {
                        "input-textab12": "Stanford Children's Health",
                        "Provider Name": "ignored label",
                    },
                }
            ]
        }

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=generate,
        service_tier="priority",
    )

    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.prompt_type == "organize submission completion"
    assert prompt.model_tier == "primary"
    assert prompt.thinking_budget is None
    assert prompt.service_tier == "priority"
    assert prompt.build().index("## Instructions") < prompt.build().index(
        "## Context"
    )
    assert prompt.search is False
    assert prompt.tools is None
    assert prompt.response_schema is None
    assert prompt.output_format["type"] == "JSON"
    context = _prompt_context_json(prompt, "Completion Context")
    assert context["report_intent"] == report.instructions
    assert len(context["forms"]) == 1
    assert len(context["records"]) == 1
    assert context["records"][0]["action_id"] == "provider_page"
    assert context["records"][0]["supporting_file_refs"] == [
        first.urlsafe_key,
        second.urlsafe_key,
    ]
    assert [item["summary"] for item in context["evidence_files"]] == [
        first.summary,
        second.summary,
    ]
    assert completed["actions"][0]["data"]["submission"] == {
        "input-textab12": "Stanford Children's Health"
    }
    assert "submission_empty_reason" not in completed["actions"][0]["data"]


# @features ai-report
# @dimensions submission-completion explicit-task-identity inherited-form
@pytest.mark.unit
def test_complete_organize_submissions_uses_target_task_form(
    monkeypatch,
    get_schema,
):
    user = _test_user("targeted-task-completion-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Prescriptions", "hash": "targeted-prescriptions-page"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Prescription", "hash": "targeted-prescription-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {"name": "Lisinopril Prescription", "hash": "targeted-lisinopril-task"},
        page=page,
    )
    task.form = form
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Targeted prescription completion",
            "hash": "targeted-prescription-report",
            "parent": user,
            "user": user,
            "input_files": [],
        },
    )
    proposal = {
        "summary": "Record a Lisinopril occurrence.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "lisinopril_completion",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": page.urlsafe_key,
                    "task": task.urlsafe_key,
                    "completed": True,
                },
            }
        ],
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                task.urlsafe_key: task,
                form.urlsafe_key: form,
                form.key: form,
            }
        ),
    )

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=lambda prompt: {
            "submissions": [
                {
                    "action_id": "lisinopril_completion",
                    "submission": {"input-textab12": "10 mg daily"},
                }
            ]
        },
    )

    data = completed["actions"][0]["data"]
    assert data["form"] == form.urlsafe_key
    assert data["submission"] == {"input-textab12": "10 mg daily"}


# @features ai-report
# @dimensions submission-completion existing-task partial-update evidence-mapping
@pytest.mark.unit
def test_complete_organize_submissions_updates_existing_task_submission(
    monkeypatch,
    get_schema,
):
    user = _test_user("existing-task-completion-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Accounts Payable", "hash": "existing-invoice-page"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Invoice", "hash": "existing-invoice-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {"name": "Acme invoice", "hash": "existing-invoice-task"},
        page=page,
    )
    task.form = form
    task.submission = {"input-textab12": "Pending"}
    file = _test_file("acme-paid.pdf", "application/pdf")
    file.summary = "Acme invoice paid. Confirmation number 834921."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Update invoice confirmation",
            "hash": "existing-invoice-report",
            "parent": user,
            "user": user,
            "instructions": "Add the payment confirmation to the existing invoice.",
            "input_files": [file],
        },
    )
    proposal = {
        "summary": "Update the invoice and retain its confirmation.",
        "confidence": 0.95,
        "issues": [],
        "actions": [
            {
                "id": "update_invoice",
                "type": "update_submission_fields",
                "display_label": "Update Acme invoice",
                "data": {"task": task.urlsafe_key},
            },
            {
                "id": "attach_confirmation",
                "type": "attach_file_to_task",
                "data": {"task": task.urlsafe_key, "file": file.urlsafe_key},
            },
        ],
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                task.urlsafe_key: task,
                form.urlsafe_key: form,
                form.key: form,
            }
        ),
    )
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return {
            "submissions": [
                {
                    "action_id": "update_invoice",
                    "submission": {
                        "input-textab12": "Confirmation 834921",
                    },
                }
            ]
        }

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=generate,
    )

    context = _prompt_context_json(prompts[0], "Completion Context")
    assert context["records"][0]["existing_submission"] == {
        "input-textab12": "Pending"
    }
    assert context["records"][0]["supporting_file_refs"] == [file.urlsafe_key]
    assert completed["actions"][0]["data"]["updates"] == [
        {
            "task": task.urlsafe_key,
            "schema_id": "input-textab12",
            "new_value": "Confirmation 834921",
        }
    ]
    assert completed["actions"][1]["type"] == "attach_file_to_task"


# @features ai-report form-schema submission
# @dimensions submission-completion empty preservation issue
@pytest.mark.unit
def test_complete_organize_submissions_preserves_empty_form_records(
    monkeypatch,
    get_schema,
):
    user = _test_user("empty-focused-completion-owner")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Providers", "hash": "empty-focused-category"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Provider", "hash": "empty-focused-form"},
    )
    form.form_type = "page"
    form.schema = get_schema("text_input_only")
    category.db["form"] = form.key
    file = _test_file("unclear-provider.pdf", "application/pdf")
    file.summary = "A provider document with no matching form values."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Empty focused completion report",
            "hash": "empty-focused-completion-report",
            "parent": user,
            "user": user,
            "input_files": [file],
        },
    )
    proposal = {
        "summary": "Keep the provider record and its evidence.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "provider_page",
                "type": "create_page",
                "display_label": "Create provider",
                "data": {"name": "Unknown Provider", "category": category.urlsafe_key},
            },
            {
                "id": "attach_provider",
                "type": "attach_file_to_page",
                "data": {"page_action": "provider_page", "file": file.urlsafe_key},
            },
        ],
    }
    entities = {
        category.urlsafe_key: category,
        category.key: category,
        form.key: form,
    }
    monkeypatch.setattr(
        organize.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    completed = organize.complete_organize_submissions(
        proposal,
        report,
        user,
        generate=lambda _prompt: {
            "submissions": [
                {
                    "action_id": "provider_page",
                    "submission": {},
                    "empty_reason": "The assigned summary supports no form fields.",
                }
            ]
        },
    )

    assert completed["actions"][0]["type"] == "create_page"
    assert completed["actions"][1]["type"] == "attach_file_to_page"
    assert completed["actions"][0]["data"]["submission"] == {}
    assert completed["actions"][0]["data"]["submission_empty_reason"] == (
        "The assigned summary supports no form fields."
    )
    assert completed["issues"] == [
        "Create provider: The assigned summary supports no form fields."
    ]


# @features ai-report
# @dimensions proposal skip dependencies
@pytest.mark.unit
def test_skip_proposal_actions_marks_dependencies():
    proposal = {
        "summary": "Create then attach.",
        "confidence": 0.9,
        "actions": [
            {"id": "category", "type": "create_category", "data": {}},
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "Scanned Page", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file_to_page",
                "data": {"page_action": "page", "file": "scan.pdf"},
            },
            {"id": "other", "type": "needs_review", "data": {}},
        ],
    }

    skipped = organize.skip_proposal_actions(proposal, 0)

    assert skipped == [1, 2, 3]
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]


# @features ai-report
# @dimensions proposal skip grouped-display restore dependencies
@pytest.mark.unit
def test_toggle_proposal_action_skip_restores_dependencies():
    proposal = {
        "summary": "Create then attach.",
        "confidence": 0.9,
        "actions": [
            {"id": "category", "type": "create_category", "data": {}},
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "Scanned Page", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file_to_page",
                "data": {"page_action": "page", "file": "scan.pdf"},
            },
            {"id": "other", "type": "needs_review", "data": {}},
        ],
    }

    skipped = organize.toggle_proposal_action_skip(proposal, 0)

    assert skipped == {"changed": [1, 2, 3], "skipped": [1, 2, 3]}
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]

    restored = organize.toggle_proposal_action_skip(proposal, 0)

    assert restored == {"changed": [1, 2, 3], "skipped": []}
    assert [action.get("skip") for action in proposal["actions"]] == [
        None,
        None,
        None,
        None,
    ]

    grouped = organize.toggle_proposal_action_indexes(proposal, 1, [0, 1])

    assert grouped == {"changed": [1, 2, 3], "skipped": [1, 2, 3]}
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]


# @features ai-report
# @dimensions proposal skip grouped-display exact-indexes schema-section
@pytest.mark.unit
def test_toggle_proposal_action_indexes_can_skip_exact_indexes_without_dependencies():
    proposal = {
        "summary": "Schema change plus exact field patches.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "schema",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {
                            "op": "add_select_option",
                            "schema_id": "select-status",
                            "option": {"value": "paid", "label": "Paid"},
                        }
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
                            "schema_id": "select-status",
                            "new_value": "paid",
                        }
                    ]
                },
            },
        ],
    }

    skipped = organize.toggle_proposal_action_indexes(
        proposal,
        0,
        [0],
        include_dependencies=False,
    )

    assert skipped == {"changed": [1], "skipped": [1]}
    assert [action.get("skip") for action in proposal["actions"]] == [True, None]


# @features ai-report
# @dimensions action-registry contract
@pytest.mark.unit
def test_report_action_registry_matches_proposal_contracts():
    adapters = report_runner.REPORT_ACTION_ADAPTERS

    assert set(adapters) == set(report_contracts.REPORT_ACTION_DATA_CONTRACTS)
    assert set(adapters) == set(report_contracts.ALLOWED_ACTIONS)
    assert all(action_type == adapter.action_type for action_type, adapter in adapters.items())


# @pair ai-report:cancellation
# @pair ai-report:deterministic-run
@pytest.mark.unit
def test_run_report_checks_deferred_execution_guard(monkeypatch):
    report = SimpleNamespace(
        urlsafe_key="guarded-report",
        proposal={"summary": "No changes", "actions": []},
        result=None,
        status="ready",
        pending=False,
        error=None,
    )
    checks = []
    saved = []
    monkeypatch.setattr(
        report_runner,
        "validate_proposal",
        lambda proposal, **_kwargs: proposal,
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(
        report,
        SimpleNamespace(),
        ensure_active=lambda: checks.append("active"),
    )

    assert result["status"] == "complete"
    assert report.status == "complete"
    assert len(checks) == 3
    assert saved == [(report,), (report,)]


# @pair ai-report:cancellation
# @pair ai-report:deterministic-run
@pytest.mark.unit
def test_run_report_propagates_deferred_control_stop(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.errors import DeferredJobDeadlineError

    report = SimpleNamespace(
        urlsafe_key="interrupted-report",
        proposal={
            "summary": "One guarded change",
            "actions": [{"id": "guarded", "type": "skip"}],
        },
        result=None,
        status="ready",
        pending=False,
        error=None,
    )
    saved = []
    checks = []
    adapter = SimpleNamespace(prepare=lambda *_args: None)
    monkeypatch.setattr(
        report_runner,
        "validate_proposal",
        lambda proposal, **_kwargs: proposal,
    )
    monkeypatch.setitem(report_runner.REPORT_ACTION_ADAPTERS, "skip", adapter)
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    def ensure_active():
        checks.append("active")
        if len(checks) == 4:
            raise DeferredJobDeadlineError("execution attempt stopped")

    with pytest.raises(
        DeferredJobDeadlineError,
        match="execution attempt stopped",
    ):
        report_runner.run_report(
            report,
            SimpleNamespace(),
            ensure_active=ensure_active,
        )

    assert report.status == "running"
    assert report.result["status"] == "running"
    assert report.result["actions"][0]["status"] == "pending"
    assert saved == [(report,)]


# @pairs ai-report:deterministic-run ai-report:create-order ai-report:partial-result
# @pairs ai-report:skip-action ai-report:default-category ai-report:result
# @pairs ai-report:grouping ai-report:attachments ai-report:file-summary
# @pairs ai-report:execute ai-report:persistence
@pytest.mark.unit
def test_run_report_creates_form_category_page_and_project_chain(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-owner")
    file = _test_file("july-receipt.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Run report",
            "hash": "runner-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
        },
    )
    report.proposal = {
        "summary": "Create a small workspace chain.",
        "confidence": 0.92,
        "actions": [
            {
                "id": "page_form",
                "type": "create_form",
                "data": {
                    "name": "Record Form",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-vendor",
                            "type": "input",
                            "input": "text",
                            "title": "Vendor",
                        }
                    ],
                },
            },
            {
                "id": "category",
                "type": "create_category",
                "data": {"name": "Receipts", "form_action": "page_form"},
            },
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "July Receipt", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file_to_page",
                "data": {"page_action": "page", "file": "july-receipt.pdf"},
            },
            {
                "id": "summary",
                "type": "summarize_file",
                "data": {
                    "file": "july-receipt.pdf",
                    "summary": "Receipt for July house supplies.",
                    "search": True,
                },
            },
            {
                "id": "uncategorized_page",
                "type": "create_page",
                "data": {"name": "Loose scan"},
            },
            {
                "id": "skipped_page",
                "type": "create_page",
                "skip": True,
                "data": {"name": "Intentionally skipped"},
            },
            {
                "id": "project",
                "type": "create_project",
                "data": {"name": "House Admin"},
            },
            {
                "id": "task_form",
                "type": "create_form",
                "data": {
                    "name": "Follow-up Form",
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
                "id": "model",
                "type": "create_model_task",
                "data": {
                    "name": "Review receipt",
                    "project_action": "project",
                    "form_action": "task_form",
                },
            },
        ],
    }
    saved_batches = []
    saved_entities = []

    def save_entities(*entities):
        saved_entities.extend(entities)
        saved_batches.append([getattr(entity, "kind", None) for entity in entities])

    monkeypatch.setattr(report_runner.Entities, "save", save_entities)
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        lambda key, request: None,
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY", {"name": "Uncategorized Pages", "hash": "uncategorized"}
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert report.status == "complete"
    assert report.pending is False
    created_kinds = [
        action["entity"]["kind"] for action in result["actions"] if action.get("entity")
    ]
    assert created_kinds == [
        "form",
        "category",
        "page",
        "file",
        "file",
        "page",
        "project",
        "form",
        "model",
    ]
    assert result["actions"][5]["entity"]["name"] == "Loose scan"
    loose_page = next(
        entity
        for entity in saved_entities
        if getattr(entity, "entity_kind", None) == "page"
        and entity.name == "Loose scan"
    )
    assert loose_page.model.name == "Uncategorized Pages"
    assert result["actions"][6]["status"] == "skipped"
    assert result["actions"][9]["entity"]["parent"]["name"] == "House Admin"
    assert result["actions"][3]["target"]["kind"] == "page"
    assert result["actions"][3]["target"]["name"] == "July Receipt"
    assert result["actions"][4]["type"] == "summarize_file"
    assert result["actions"][4]["entity"]["kind"] == "file"
    assert result["actions"][4]["file_summary"] == {
        "enabled": True,
        "complete": True,
        "present": True,
        "status": "Summary saved from report.",
    }
    assert file.summary == "Receipt for July house supplies."
    assert file.properties.summarize.search is True
    grouped = report.properties.result.grouped_actions
    assert [action["type"] for action in grouped] == [
        "create_form",
        "create_category",
        "create_page",
        "create_page",
        "create_page",
        "create_project",
        "create_form",
        "create_model_task",
    ]
    assert grouped[2]["attachments"][0]["entity"]["name"] == "july-receipt"
    assert grouped[2]["attachments"][0]["file_summary"]["complete"] is True
    assert saved_batches[0] == ["report"]
    assert saved_batches[-1] == ["report"]


# @features ai-report form-schema submission
# @dimensions deterministic-run validation stale-proposal
@pytest.mark.unit
def test_run_report_rejects_saved_pending_submissions_before_execution():
    user = _test_user("runner-pending-submission-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Stale pending submission report",
            "hash": "runner-pending-submission-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Create a dental page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "create_dental_page",
                        "type": "create_page",
                        "skip": True,
                        "data": {
                            "name": "Pediatric Dentistry",
                            "form_name": "Business",
                            "submission_needed": True,
                        },
                    }
                ],
            },
        },
    )

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        report_runner.run_report(report, user)


# @pair ai-report:deterministic-run
# @pairs ai-report:submission-completion ai-report:persistence
@pytest.mark.unit
def test_run_report_uses_category_form_from_stored_key_for_page_submission(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-page-form-owner")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Medical Providers", "hash": "medical-providers"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Provider", "hash": "provider-form"},
    )
    form.form_type = "page"
    form.schema = get_schema("text_input_only")
    category.db["form"] = form.key
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Page submission report",
            "hash": "runner-page-submission-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Create a provider page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "provider_page",
                        "type": "create_page",
                        "data": {
                            "name": "Lucile Packard Children's Hospital Stanford",
                            "category": category.urlsafe_key,
                            "submission": {
                                "input-textab12": "Pediatric hospital provider.",
                                "unknown-field": "must not persist",
                            },
                        },
                    }
                ],
            },
        },
    )
    saved = []
    entities = {
        category.urlsafe_key: category,
        form.urlsafe_key: form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    pages = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "page"
    ]
    assert result["status"] == "complete"
    assert len(pages) == 1
    assert pages[0].form is form
    assert pages[0].submission == {
        "input-textab12": "Pediatric hospital provider."
    }
    assert result["actions"][0]["submission"] == {"created": True, "field_count": 1}


# @pairs ai-report:deterministic-run ai-report:task-attachment ai-report:created-task
# @pairs ai-report:submission-completion ai-report:persistence
# @pairs tasks:task-attachment files:task-attachment
@pytest.mark.unit
def test_run_report_attach_file_to_task_targets_created_task(monkeypatch, get_schema):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-task-file-owner")
    page = TestEntities.get("PAGE", {"name": "Medical", "hash": "medical-page"})
    form = TestEntities.get(
        "FORM",
        {"name": "Review", "hash": "review-task-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    file = _test_file("sports-physical.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Task attachment report",
            "hash": "runner-task-attachment-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Create a follow-up task.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "review_physical",
                        "type": "create_task",
                        "data": {
                            "name": "Review sports physical",
                            "description": "Review the uploaded sports physical.",
                            "page": page.urlsafe_key,
                            "form": form.urlsafe_key,
                            "submission": {
                                "input-textab12": "Physical reviewed.",
                                "unknown-field": "must not persist",
                            },
                        },
                    },
                    {
                        "id": "attach_physical",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "review_physical",
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
        "fetch_one",
        _fetch_one_from({
            page.urlsafe_key: page,
            form.urlsafe_key: form,
        }),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete", result
    assert result["actions"][0]["type"] == "create_task"
    assert "attachments" not in result["actions"][0]
    attach_action = result["actions"][1]
    assert attach_action["type"] == "attach_file_to_task"
    assert attach_action["entity"]["id"] == file.urlsafe_key
    assert attach_action["target"]["kind"] == "task"
    tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    ]
    assert tasks[0].files == [file]
    assert tasks[0].submission == {"input-textab12": "Physical reviewed."}


# @features ai-report task-scheduling
# @dimensions structured-output recurring scheduled periodic validation normalization
@pytest.mark.unit
def test_report_task_schedule_contract_validates_supported_patterns():
    schema = report_contracts.report_proposal_response_schema(("create_task",))
    create_task_data = schema["properties"]["actions"]["items"]["anyOf"][0][
        "properties"
    ]["data"]
    assert create_task_data["properties"]["schedule"] == (
        report_schedules.task_schedule_response_schema()
    )
    assert create_task_data["properties"]["schedule"]["properties"]["days"][
        "items"
    ] == {"type": "integer"}
    assert report_schedules.validate_task_schedule(
        {"kind": "recurring", "interval": 2, "unit": "week"}
    ) == {"kind": "recurring", "interval": 2, "unit": "week"}
    assert report_schedules.validate_task_schedule(
        {
            "kind": "scheduled",
            "mode": "monthly",
            "pattern_type": "ordinal_weekday",
            "ordinal": -1,
            "weekday": 4,
            "description": "last Friday of the month",
        }
    ) == {
        "kind": "scheduled",
        "mode": "monthly",
        "pattern_type": "ordinal_weekday",
        "ordinal": -1,
        "weekday": 4,
        "description": "last Friday of the month",
        "user_prompt": "last Friday of the month",
    }
    with pytest.raises(exceptions.AIException, match="weekday"):
        report_schedules.validate_task_schedule(
            {"kind": "scheduled", "mode": "weekly", "days": [7]}
        )


# @features ai-report task-scheduling
# @dimensions persistence recurring
@pytest.mark.unit
def test_run_report_creates_task_with_reviewed_schedule(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-scheduled-task-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Household", "hash": "scheduled-task-page"},
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Recurring filter reminder",
            "hash": "runner-scheduled-task-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Create a recurring reminder.",
                "confidence": 0.95,
                "actions": [
                    {
                        "id": "replace_filter",
                        "type": "create_task",
                        "data": {
                            "name": "Replace HVAC filter",
                            "page": page.urlsafe_key,
                            "schedule": {
                                "kind": "recurring",
                                "interval": 3,
                                "unit": "month",
                            },
                        },
                    }
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page}),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )

    result = report_runner.run_report(report, user)

    task = next(
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    )
    assert task.processes["schedule"]["recurring"] == {
        "interval": 3,
        "unit": "month",
        "complete": True,
    }
    assert result["actions"][0]["schedule"] == {
        "kind": "recurring",
        "interval": 3,
        "unit": "month",
        "complete": True,
    }


# @features ai-report files
# @dimensions deterministic-run report-file-reference exact-id
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


# @features ai-report
# @dimensions deterministic-run moves batch-field-patch schema-update undo
@pytest.mark.unit
def test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo(
    monkeypatch,
):
    user = _test_user("runner-edit-owner")
    old_category = TestEntities.get(
        "CATEGORY",
        {"name": "Open Invoices", "hash": "open-invoices"},
    )
    paid_category = TestEntities.get(
        "CATEGORY",
        {"name": "Paid Invoices", "hash": "paid-invoices"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Invoice Form", "hash": "invoice-form"},
    )
    form.form_type = "task"
    form.schema = [
        {
            "id": "select-status",
            "type": "select",
            "title": "Status",
            "options": [{"value": "due", "label": "Due"}],
        }
    ]
    page = TestEntities.get(
        "PAGE",
        {"name": "Sousa Doors", "hash": "invoice-page"},
    )
    page.model = old_category
    page.form = form
    page.properties.submission.value = {"select-status": "due"}
    task_target_page = TestEntities.get(
        "PAGE",
        {"name": "Paid Archive", "hash": "paid-archive-page"},
    )
    task_target_page.model = paid_category
    task = TestEntities.get(
        "TASK",
        {"name": "July invoice", "hash": "invoice-task"},
        page=page,
    )
    task.form = form
    task.properties.submission.value = {"select-status": "due"}

    report = TestEntities.get(
        "REPORT",
        {
            "name": "Invoice edit report",
            "hash": "runner-edit-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Mark paid invoices and move them.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "schema",
                        "type": "update_form_schema",
                        "data": {
                            "form": "invoice-form",
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
                                        "required": True,
                                        "visibility": [
                                            {
                                                "id": "select-status",
                                                "value": "paid",
                                            }
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "id": "field_updates",
                        "type": "update_submission_fields",
                        "depends_on": ["schema"],
                        "data": {
                            "updates": [
                                {
                                    "page": "invoice-page",
                                    "schema_id": "select-status",
                                    "new_value": "paid",
                                },
                                {
                                    "task": "invoice-task",
                                    "schema_id": "select-status",
                                    "new_value": "paid",
                                },
                                {
                                    "task": "invoice-task",
                                    "schema_id": "input-missing",
                                    "new_value": "kept only if schema exists",
                                },
                            ]
                        },
                    },
                    {
                        "id": "move_page",
                        "type": "move_page",
                        "data": {
                            "page": "invoice-page",
                            "category": "paid-invoices",
                        },
                    },
                    {
                        "id": "move_task",
                        "type": "move_task",
                        "data": {
                            "task": "invoice-task",
                            "to_page": "paid-archive-page",
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (
            old_category,
            paid_category,
            form,
            page,
            task_target_page,
            task,
        )
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
    assert [action["status"] for action in result["actions"]] == [
        "complete",
        "complete",
        "complete",
        "complete",
    ]
    status_field = next(field for field in form.schema if field["id"] == "select-status")
    assert {"value": "paid", "label": "Paid"} in status_field["options"]
    payment_field = next(
        field for field in form.schema if field["id"] == "input-payment-reference"
    )
    assert payment_field["required"] is False
    assert "visibility" not in payment_field
    assert page.submission == {"select-status": "paid"}
    assert task.submission == {"select-status": "paid"}
    assert page.model is None
    assert "model" not in page.db
    assert page.categories == [paid_category]
    assert page.db["categories"] == [paid_category.key]
    assert task.page is task_target_page
    assert result["actions"][0]["schema_updates"]["applied"] == [
        {
            "index": 1,
            "op": "add_select_option",
            "schema_id": "select-status",
            "value": "paid",
            "label": "Paid",
        },
        {
            "index": 2,
            "op": "add_field",
            "schema_id": "input-payment-reference",
            "label": "Payment Reference",
        },
    ]
    assert result["actions"][1]["updates"]["applied"] == [
        {
            "index": 1,
            "entity": {
                "id": "invoice-page",
                "kind": "page",
                "name": "Sousa Doors",
                "url": "/test/page/invoice-page",
            },
            "schema_id": "select-status",
        },
        {
            "index": 2,
            "entity": {
                "id": "invoice-task",
                "kind": "task",
                "name": "July invoice",
                "url": "/test/task/invoice-task",
            },
            "schema_id": "select-status",
        },
    ]
    assert result["actions"][1]["updates"]["skipped"][0]["schema_id"] == "input-missing"
    assert result["actions"][1]["previous"] == [
        {
            "index": 1,
            "entity": {
                "id": "invoice-page",
                "kind": "page",
                "name": "Sousa Doors",
                "url": "/test/page/invoice-page",
            },
            "schema_id": "select-status",
            "had_value": True,
            "previous_value": "due",
        },
        {
            "index": 2,
            "entity": {
                "id": "invoice-task",
                "kind": "task",
                "name": "July invoice",
                "url": "/test/task/invoice-task",
            },
            "schema_id": "select-status",
            "had_value": True,
            "previous_value": "due",
        },
    ]
    assert result["actions"][2]["moved"]["from"]["id"] == "open-invoices"
    assert result["actions"][2]["moved"]["to"]["id"] == "paid-invoices"
    assert result["actions"][3]["moved"]["from"]["id"] == "invoice-page"
    assert result["actions"][3]["moved"]["to"]["id"] == "paid-archive-page"

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert report.status == "ready"
    assert report.pending is False
    assert report.result["status"] == "undone"
    assert report.result["undone"] is True
    assert form.schema == [
        {
            "id": "select-status",
            "type": "select",
            "title": "Status",
            "options": [{"value": "due", "label": "Due"}],
        }
    ]
    assert page.submission == {"select-status": "due"}
    assert task.submission == {"select-status": "due"}
    assert page.model is old_category
    assert page.db["model"] == old_category.key
    assert page.categories == [old_category]
    assert task.page is page
    assert saved


# @pair ai-report:deterministic-run
# @pair ai-report:rename
# @pair ai-report:undo
@pytest.mark.unit
def test_run_report_renames_entity_without_submission_and_undoes(monkeypatch):
    user = _test_user("runner-rename-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Orthodontics", "hash": "orthodontics-page"},
    )
    assert page.form is None
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Rename page report",
            "hash": "runner-rename-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Rename Orthodontics to Teeth.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "rename_page",
                        "type": "rename_entity",
                        "data": {
                            "entity": page.urlsafe_key,
                            "name": " Teeth ",
                        },
                    }
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page}),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert page.name == "Teeth"
    assert result["actions"][0]["entity"]["name"] == "Teeth"
    assert result["actions"][0]["before"]["name"] == "Orthodontics"
    assert result["actions"][0]["expected"]["name"] == "Teeth"

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert page.name == "Orthodontics"
    assert saved


# @features ai-report submission
# @dimensions deterministic-run empty-update recoverable continue
@pytest.mark.unit
def test_run_report_skips_empty_submission_update_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-empty-submission-update-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Empty submission update report",
            "hash": "runner-empty-submission-update-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Skip the no-op update and keep building.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "empty_submission_update",
                        "type": "update_submission_fields",
                        "display_label": "Submission Update: Rank",
                        "data": {"updates": []},
                    },
                    {
                        "id": "built_page",
                        "type": "create_page",
                        "data": {"name": "Kung Fu"},
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

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "skipped"
    assert result["actions"][0]["error"] == report_runner.SUBMISSION_UPDATE_ROWS_ERROR
    assert result["actions"][0]["note"] == (
        "Skipped because no executable submission field updates were provided."
    )
    assert result["actions"][1]["status"] == "complete"
    assert result["actions"][1]["entity"]["name"] == "Kung Fu"
    assert report.status == "complete"
    assert saved


# @features ai-report categories
# @dimensions deterministic-run add-category idempotent undo
@pytest.mark.unit
def test_run_report_adds_page_category_without_changing_primary_with_undo(
    monkeypatch,
):
    user = _test_user("runner-add-category-owner")
    primary = TestEntities.get(
        "CATEGORY", {"name": "Primary Records", "hash": "primary-records"}
    )
    extra = TestEntities.get(
        "CATEGORY", {"name": "Family Records", "hash": "family-records-category"}
    )
    page = TestEntities.get(
        "PAGE", {"name": "Richardson Records", "hash": "richardson-records-page"}
    )
    page.model = primary
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Add page category",
            "hash": "runner-add-category-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Also file the page under Family Records.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "add_family_records",
                        "type": "add_category",
                        "data": {
                            "page": page.urlsafe_key,
                            "category": extra.urlsafe_key,
                        },
                    },
                    {
                        "id": "add_family_records_again",
                        "type": "add_category",
                        "data": {
                            "page": page.urlsafe_key,
                            "category": extra.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (primary, extra, page)
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
        "add_category",
        "add_category",
    ]
    assert page.model is primary
    assert page.categories == [primary, extra]
    assert result["actions"][0]["target"]["id"] == extra.urlsafe_key
    assert result["actions"][0]["previous"] == {"had_category": False}
    assert result["actions"][1]["previous"] == {"had_category": True}
    assert result["actions"][1]["note"] == "Page already had this category."

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert page.model is primary
    assert page.categories == [primary]
    assert undo["actions"][0]["note"] == "Category was already present; nothing removed."
    assert undo["actions"][1]["note"] == "Removed added page category."
    assert saved


# @features ai-report
# @dimensions deterministic-run page-form idempotent undo
@pytest.mark.unit
def test_run_report_adds_form_to_existing_page_with_undo(monkeypatch):
    user = _test_user("runner-add-page-form-owner")
    category = TestEntities.get(
        "CATEGORY", {"name": "Property Tax", "hash": "property-tax-category"}
    )
    old_form = TestEntities.get(
        "FORM", {"name": "General Record", "hash": "general-record-form"}
    )
    old_form.form_type = "page"
    property_tax_form = TestEntities.get(
        "FORM", {"name": "Property Tax Record", "hash": "property-tax-form"}
    )
    property_tax_form.form_type = "page"
    page = TestEntities.get(
        "PAGE", {"name": "Toft Property Taxes", "hash": "toft-property-taxes"}
    )
    page.model = category
    page.form = old_form
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Add property-tax form",
            "hash": "runner-add-page-form-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Use the property-tax form on the existing page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "add_property_tax_form",
                        "type": "add_form_to_page",
                        "data": {
                            "page": page.urlsafe_key,
                            "form": property_tax_form.urlsafe_key,
                        },
                    },
                    {
                        "id": "add_property_tax_form_again",
                        "type": "add_form_to_page",
                        "data": {
                            "page": page.urlsafe_key,
                            "form": property_tax_form.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (category, old_form, property_tax_form, page)
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

    grouped = report.properties.proposal.display_actions
    assert grouped[0]["type"] == "page_group"
    assert grouped[0]["support"][0]["label"] == "Add Form"
    assert grouped[0]["support"][0]["value"] == property_tax_form.urlsafe_key

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert page.form is property_tax_form
    assert property_tax_form in category.forms
    assert result["actions"][0]["target"]["id"] == property_tax_form.urlsafe_key
    assert result["actions"][0]["previous"] == {
        "form": report_runner._entity_result(old_form),
        "had_form": False,
    }
    assert result["actions"][1]["previous"] == {
        "form": report_runner._entity_result(property_tax_form),
        "had_form": True,
    }
    assert result["actions"][1]["note"] == "Page already had this form."

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert page.form is old_form
    assert undo["actions"][0]["note"] == (
        "Page already had this form; nothing changed."
    )
    assert undo["actions"][1]["note"] == "Restored previous page form."
    assert saved


# @features ai-report files
# @dimensions deterministic-run move-file manual-cleanup undo
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

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert file.db["pages"] == [source_page.key]
    assert undo["actions"][0]["type"] == "delete_page"
    assert undo["actions"][0]["note"] == (
        "Manual cleanup suggestion; nothing was executed."
    )
    assert undo["actions"][1]["type"] == "move_file"
    assert undo["actions"][1]["note"] == "Restored previous file attachment."
    assert saved


# @features ai-report files
# @dimensions deterministic-run move-file readable-file-fallback
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


# @features ai-report form-schema
# @dimensions deterministic-run permission-failure schema-update
@pytest.mark.unit
def test_run_report_rejects_schema_update_without_form_edit_permission(monkeypatch):
    user = _permissioned_user(
        "runner-schema-denied-user",
        {
            "page-editable": "EDIT",
        },
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Restricted Invoice Form", "hash": "restricted-invoice-form"},
    )
    form.schema = []
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Denied schema update report",
            "hash": "runner-schema-denied-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Try to add a field.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "schema",
                        "type": "update_form_schema",
                        "data": {
                            "form": "restricted-invoice-form",
                            "operations": [
                                {
                                    "op": "add_field",
                                    "field": {
                                        "id": "input-note",
                                        "type": "input",
                                        "input": "text",
                                        "title": "Note",
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        },
    )

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"restricted-invoice-form": form}),
    )
    monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)

    result = report_runner.run_report(report, user)

    assert result["status"] == "failed"
    assert report.status == "failed"
    assert result["actions"][0]["status"] == "failed"
    assert result["actions"][0]["error"] == (
        "You do not have permission to update this form schema."
    )
    assert form.schema == []


# @features ai-report tasks task-completion
# @dimensions completed-task older-event name description attachments submission
@pytest.mark.unit
def test_run_report_records_older_completed_event_without_mutating_live_task(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-runner-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    form = TestEntities.get(
        "FORM",
        {"name": "Vehicle Service Form", "hash": "vehicle-service-form"},
    )
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {
            "name": "Registration",
            "hash": "registration-task",
        },
        page=page,
    )
    task.form = form
    live_attachment = _test_file("current-task-note.pdf", "application/pdf")
    task.files = [live_attachment]
    task.completed = True
    task.completed_on = datetime(2024, 1, 1, tzinfo=timezone.utc)
    task.due_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    task.description = "Current registration details."
    page._completed = [task]
    file_one = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    file_two = _test_file("dmv receipt.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Task history run report",
            "hash": "history-runner-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_one, file_two],
            "proposal": {
                "summary": "Record Jeep registration history.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_history",
                        "type": "create_task",
                        "display_label": "Record Jeep registration",
                        "data": {
                            "name": "Registration",
                            "description": "Archived registration renewal.",
                            "page": "jeep-page",
                            "task": "registration-task",
                            "completed_on": "2023-06-24",
                            "submission": {
                                "input-textab12": "Registration renewed at DMV."
                            },
                        },
                    },
                    {
                        "id": "attach_registration_scan",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_history",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                    {
                        "id": "attach_dmv_receipt",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_history",
                            "file": "dmv receipt.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []

    def save_entities(*entities):
        saved.append(entities)

    monkeypatch.setattr(report_runner.Entities, "save", save_entities)
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"jeep-page": page, "registration-task": task}),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    assert result["status"] == "complete"
    assert len(histories) == 1
    history = histories[0]
    assert history.task is task
    assert history.page is page
    assert history.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert history.db["completed_on"] == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert "completed" not in history.db
    assert history.name == "Registration"
    assert history.description == "Archived registration renewal."
    assert set(history.files) == {file_one, file_two}
    assert live_attachment not in history.files
    assert set(file_one.db["tasks"]) == {history.key}
    assert set(file_two.db["tasks"]) == {history.key}
    assert file_one.linked_tasks == [task]
    assert file_two.linked_tasks == [task]
    assert history.form is form
    assert history.submission == {
        "input-textab12": "Registration renewed at DMV."
    }
    assert task.completed is True
    assert task.completed_on == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert task.due_date == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert task.name == "Registration"
    assert task.description == "Current registration details."
    assert task.files == [live_attachment]
    assert task.db["history"] is True
    assert any(
        intent.intent is MutationIntentType.STANDARD and intent.entity is history
        for intent in task.mutation_intents
    )
    assert {
        intent.entity
        for intent in history.mutation_intents
        if intent.intent is MutationIntentType.PATCH
    } == {file_one, file_two}
    action = result["actions"][0]
    assert action["type"] == "create_task"
    assert action["entity"]["kind"] == "task_history"
    assert action["target"]["name"] == "Registration"
    assert action["submission"] == {"created": True, "field_count": 1}
    attachment_actions = result["actions"][1:3]
    assert [a["type"] for a in attachment_actions] == [
        "attach_file_to_task",
        "attach_file_to_task",
    ]
    assert [a["target"]["kind"] for a in attachment_actions] == [
        "task_history",
        "task_history",
    ]
    assert [a["entity"]["name"] for a in attachment_actions] == [
        "2023-06-24 jeep registration",
        "dmv receipt",
    ]
    assert [a["file_summary"]["present"] for a in attachment_actions] == [
        False,
        False,
    ]
    grouped = report.properties.result.grouped_actions
    assert grouped[0]["type"] == "page_group"
    assert grouped[0]["entity"]["name"] == "Jeep"
    grouped_task = grouped[0]["tasks"][0]
    assert grouped_task["created"] is False
    assert grouped_task["entity"]["name"] == "Registration"
    grouped_history_attachments = grouped_task["histories"][0]["attachments"]
    assert [a["entity"]["name"] for a in grouped_history_attachments] == [
        "2023-06-24 jeep registration",
        "dmv receipt",
    ]


# @features ai-report
# @dimensions completed-task attachments
@pytest.mark.unit
def test_run_report_records_dateless_historical_task_completion(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("dateless-completion-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Community Service", "hash": "community-service-page"},
    )
    file = _test_file("volunteer certificate.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Dateless historical task report",
            "hash": "dateless-historical-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Record the completed volunteer service.",
                "confidence": 0.9,
                "issues": [],
                "actions": [
                    {
                        "id": "volunteer_service",
                        "type": "create_task",
                        "data": {
                            "name": "Volunteer Service",
                            "description": "Historical volunteer service event.",
                            "page": "community-service-page",
                            "completed": True,
                        },
                    },
                    {
                        "id": "attach_certificate",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "volunteer_service",
                            "file": "volunteer certificate.pdf",
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
        _fetch_one_from({"community-service-page": page}),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    tasks = {
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    }
    assert result["status"] == "complete"
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert task.completed is True
    assert task.completed_on is None
    assert task.files == [file]
    assert file.db["tasks"] == [task.key]
    assert result["actions"][0]["note"] == (
        "Recorded as the task's current completion."
    )
    assert result["actions"][1]["target"]["id"] == task.urlsafe_key


# @features ai-report tasks task-completion
# @dimensions completed-task newest-completion history-name live-task
@pytest.mark.unit
def test_run_report_promotes_newer_completed_event_to_live_task(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-newest-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-newest-page"})
    form = TestEntities.get(
        "FORM",
        {"name": "Vehicle Registration Form", "hash": "registration-newest-form"},
    )
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {"name": "Registration", "hash": "registration-newest-task"},
        page=page,
    )
    task.form = form
    old_file = _test_file("2020-06-24 jeep registration.pdf", "application/pdf")
    task.files = [old_file]
    task.completed = True
    task.completed_on = datetime(2020, 6, 24, tzinfo=timezone.utc)
    task.description = "Previous registration details."
    task.ai_submission({"input-textab12": "Previous registration."})
    page._completed = [task]
    new_file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Newer task history report",
            "hash": "history-newest-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [new_file],
            "proposal": {
                "summary": "Record newer registration history.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_history",
                        "type": "create_task",
                        "display_label": "Record newer Jeep registration",
                        "data": {
                            "name": "Registration",
                            "page": "jeep-newest-page",
                            "task": "registration-newest-task",
                            "completed_on": "2023-06-24",
                            "submission": {
                                "input-textab12": "Registration renewed again."
                            },
                        },
                    },
                    {
                        "id": "attach_registration_scan",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_history",
                            "file": "2023-06-24 jeep registration.pdf",
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
        _fetch_one_from(
            {
                "jeep-newest-page": page,
                "registration-newest-task": task,
            }
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    assert result["status"] == "complete"
    assert len(histories) == 1
    history = histories[0]
    assert history.task is task
    assert history.completed_on == datetime(2020, 6, 24, tzinfo=timezone.utc)
    assert history.name == "Registration"
    assert history.description == "Previous registration details."
    assert history.files == [old_file]
    assert history.submission == {"input-textab12": "Previous registration."}
    assert set(old_file.db["tasks"]) == {history.key}
    assert task.completed is True
    assert task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert task.due_date is None
    assert task.files == [new_file]
    assert task.submission == {"input-textab12": "Registration renewed again."}
    assert set(new_file.db["tasks"]) == {task.key}
    action = result["actions"][0]
    assert action["entity"]["kind"] == "task"
    assert action["created"] is False
    assert action["target"]["id"] == task.urlsafe_key
    assert action["submission"] == {"created": True, "field_count": 1}
    assert action["note"] == "Moved the previous completion to history."
    attach_action = result["actions"][1]
    assert attach_action["type"] == "attach_file_to_task"
    assert attach_action["entity"]["id"] == new_file.urlsafe_key
    assert attach_action["target"]["id"] == task.urlsafe_key
    assert attach_action["file_summary"]["present"] is False


# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity duplicate-task-prevention
@pytest.mark.unit
def test_run_report_reuses_one_created_task_for_multiple_completed_events(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-cache-owner")
    file_one = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    file_two = _test_file("2018_06_07 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Duplicate task history report",
            "hash": "history-cache-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_one, file_two],
            "proposal": {
                "summary": "Record registration history without duplicate tasks.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "jeep",
                        "type": "create_page",
                        "data": {"name": "Jeep"},
                    },
                    {
                        "id": "maintenance",
                        "type": "create_project",
                        "data": {"name": "Maintenance"},
                    },
                    {
                        "id": "registration_form",
                        "type": "create_form",
                        "data": {
                            "name": "Registration Form",
                            "form_type": "task",
                            "schema": get_schema("text_input_only"),
                        },
                    },
                    {
                        "id": "registration_model",
                        "type": "create_model_task",
                        "data": {
                            "name": "Vehicle Registration",
                            "project_action": "maintenance",
                            "form_action": "registration_form",
                        },
                    },
                    {
                        "id": "registration_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Registration",
                            "page_action": "jeep",
                            "project_action": "maintenance",
                            "model_action": "registration_model",
                            "description": "Vehicle registration renewal payment.",
                            "completed_on": "2023-06-24",
                            "submission": {"input-textab12": "2023 event"},
                        },
                    },
                    {
                        "id": "attach_registration_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2023",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                    {
                        "id": "registration_2018",
                        "type": "create_task",
                        "data": {
                            "name": "Registration",
                            "page_action": "jeep",
                            "task_action": "registration_2023",
                            "project_action": "maintenance",
                            "model_action": "registration_model",
                            "description": "Vehicle registration renewal payment.",
                            "completed_on": "2018-06-07",
                            "submission": {"input-textab12": "2018 event"},
                        },
                    },
                    {
                        "id": "attach_registration_2018",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2018",
                            "file": "2018_06_07 jeep registration.pdf",
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
        report_runner.Entities, "fetch_one", lambda key, request: None
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY", {"name": "Uncategorized Pages", "hash": "uncategorized"}
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    forms = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "form"
    ]
    assert result["status"] == "complete"
    assert len(histories) == 1
    tracker_task = histories[0].task
    assert tracker_task.name == "Registration"
    assert tracker_task.description == "Vehicle registration renewal payment."
    assert tracker_task.form is forms[0]
    assert histories[0].form is forms[0]
    assert tracker_task.completed is True
    assert tracker_task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert tracker_task.due_date is None
    assert tracker_task.files == [file_one]
    assert tracker_task.submission == {"input-textab12": "2023 event"}
    assert histories[0].completed_on == datetime(2018, 6, 7, tzinfo=timezone.utc)
    assert histories[0].name == "Registration"
    assert histories[0].description == "Vehicle registration renewal payment."
    assert histories[0].submission == {"input-textab12": "2018 event"}

    first_task_action = result["actions"][4]
    first_attach_action = result["actions"][5]
    second_task_action = result["actions"][6]
    second_attach_action = result["actions"][7]
    assert first_task_action["type"] == "create_task"
    assert first_task_action["created"] is True
    assert first_task_action["entity"]["name"] == "Registration"
    assert first_attach_action["type"] == "attach_file_to_task"
    assert first_attach_action["target"]["id"] == first_task_action["entity"]["id"]
    assert second_task_action["type"] == "create_task"
    assert second_task_action["created"] is True
    assert second_task_action["target"]["id"] == first_task_action["entity"]["id"]
    assert second_task_action["target"]["name"] == "Registration"
    assert second_task_action["entity"]["kind"] == "task_history"
    assert second_task_action["entity"]["id"].startswith("task_history-")
    assert second_task_action["submission"] == {"created": True, "field_count": 1}
    assert second_attach_action["type"] == "attach_file_to_task"
    assert second_attach_action["target"]["id"] == second_task_action["entity"]["id"]


# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity distinct-task same-model
@pytest.mark.unit
def test_run_report_keeps_untargeted_same_model_tasks_distinct(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("distinct-prescriptions-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Prescriptions", "hash": "distinct-prescriptions-page"},
    )
    project = TestEntities.get(
        "PROJECT",
        {"name": "Health", "hash": "distinct-health-project"},
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Prescription", "hash": "distinct-prescription-model"},
        project=project,
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Distinct prescriptions report",
            "hash": "distinct-prescriptions-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record two distinct prescriptions.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "lisinopril",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2025-03-01",
                        },
                    },
                    {
                        "id": "atorvastatin",
                        "type": "create_task",
                        "data": {
                            "name": "Atorvastatin Prescription",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2025-03-02",
                        },
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
    }
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    tasks = {
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    }
    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert len(tasks) == 2
    assert histories == []
    assert {task.name for task in tasks.values()} == {
        "Lisinopril Prescription",
        "Atorvastatin Prescription",
    }
    assert (
        result["actions"][0]["target"]["id"]
        != result["actions"][1]["target"]["id"]
    )


# @features ai-report tasks task-completion
# @dimensions completed-task model-form lazy-load submission
@pytest.mark.unit
def test_run_report_loads_model_task_form_from_stored_key_for_history(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-model-form-owner")
    page = TestEntities.get("PAGE", {"name": "Pool", "hash": "pool-page"})
    project = TestEntities.get(
        "PROJECT", {"name": "Maintenance", "hash": "model-form-project"}
    )
    form = TestEntities.get(
        "FORM", {"name": "Invoice Form", "hash": "model-form-invoice-form"}
    )
    form.schema = get_schema("text_input_only")
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Invoices", "hash": "model-form-invoices-model"},
        project=project,
    )
    model.db["form"] = form.key
    file_new = _test_file("2024-03-01 pool invoice.pdf", "application/pdf")
    file_old = _test_file("2023-03-01 pool invoice.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Lazy model form report",
            "hash": "history-model-form-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_new, file_old],
            "proposal": {
                "summary": "Record pool invoice history.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "invoice_2024",
                        "type": "create_task",
                        "data": {
                            "name": "Invoice",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2024-03-01",
                            "submission": {"input-textab12": "2024 invoice"},
                        },
                    },
                    {
                        "id": "attach_invoice_2024",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "invoice_2024",
                            "file": file_new.urlsafe_key,
                        },
                    },
                    {
                        "id": "invoice_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Invoice",
                            "page": page.urlsafe_key,
                            "task_action": "invoice_2024",
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2023-03-01",
                            "submission": {"input-textab12": "2023 invoice"},
                        },
                    },
                    {
                        "id": "attach_invoice_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "invoice_2023",
                            "file": file_old.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
        form.urlsafe_key: form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    assert result["status"] == "complete"
    assert len(histories) == 1
    task = histories[0].task
    assert task.name == "Invoice"
    assert task.form is form
    assert task.submission == {"input-textab12": "2024 invoice"}
    assert histories[0].form is form
    assert histories[0].name == "Invoice"
    assert histories[0].submission == {"input-textab12": "2023 invoice"}
    assert result["actions"][0]["project"]["name"] == "Maintenance"
    assert result["actions"][0]["model"]["name"] == "Invoices"
    assert result["actions"][0]["model"]["parent"]["name"] == "Maintenance"
    assert result["actions"][0]["form"]["name"] == "Invoice Form"
    assert result["actions"][0]["page"]["name"] == "Pool"
    assert result["actions"][1]["type"] == "attach_file_to_task"
    assert result["actions"][2]["project"]["name"] == "Maintenance"
    assert result["actions"][2]["model"]["name"] == "Invoices"
    assert result["actions"][2]["model"]["parent"]["name"] == "Maintenance"
    assert result["actions"][2]["form"]["name"] == "Invoice Form"
    assert result["actions"][2]["page"]["name"] == "Pool"
    assert result["actions"][2]["submission"] == {"created": True, "field_count": 1}
    assert result["actions"][3]["type"] == "attach_file_to_task"


# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity existing-task
@pytest.mark.unit
def test_run_report_reuses_existing_task_for_completed_event(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-existing-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    task = TestEntities.get(
        "TASK",
        {"name": "Registration", "hash": "registration-task"},
        page=page,
    )
    page._tasks = [task]
    page._completed = []
    file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Existing task history report",
            "hash": "history-existing-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Record registration history on the existing task.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Jeep Registration - Jun 2023",
                            "page": "jeep-page",
                            "task": "registration-task",
                            "description": "Event-specific receipt text.",
                            "completed_on": "2023-06-24",
                            "submission": {"input-textab12": "event"},
                        },
                    },
                    {
                        "id": "attach_registration_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2023",
                            "file": "2023-06-24 jeep registration.pdf",
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
        _fetch_one_from({"jeep-page": page, "registration-task": task}),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert result["actions"][0]["created"] is False
    assert result["actions"][0]["entity"]["id"] == "registration-task"
    assert result["actions"][0]["target"]["id"] == "registration-task"
    assert result["actions"][1]["type"] == "attach_file_to_task"
    assert result["actions"][1]["target"]["id"] == "registration-task"
    assert len(histories) == 0
    assert task.completed is True
    assert task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert task.files == [file]
    assert set(file.db["tasks"]) == {task.key}
    assert file.linked_tasks == [task]
    assert task.name == "Registration"
    assert task.description == "Event-specific receipt text."
    assert task.due_date is None
    assert task.submission == {}


# @features ai-report tasks task-completion
# @dimensions completed-task automatic-task-family period-name same-report
@pytest.mark.unit
def test_run_report_automatically_reuses_dated_completed_task_family(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("property-tax-history-owner")
    page = TestEntities.get(
        "PAGE", {"name": "Property Tax", "hash": "property-tax-page"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Finances", "hash": "finances-project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Payments", "hash": "payments-model"},
        project=project,
    )
    task = TestEntities.get(
        "TASK", {"name": "Pay Property Tax", "hash": "property-tax-task"},
        page=page,
    )
    task.model = model
    task.project = project
    page._tasks = [task]
    page._completed = []
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Property tax installments",
            "hash": "property-tax-history-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record property-tax payments.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "property_tax_2026",
                        "type": "create_task",
                        "data": {
                            "name": "Pay Property Tax - April 2026 Installment",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2026-04-01",
                        },
                    },
                    {
                        "id": "property_tax_2024",
                        "type": "create_task",
                        "data": {
                            "name": "Pay Property Tax - July 2024 installment",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2024-07-01",
                        },
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
    }
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert result["actions"][0]["created"] is False
    assert result["actions"][0]["target"]["id"] == task.urlsafe_key
    assert result["actions"][1]["target"]["id"] == task.urlsafe_key
    assert task.name == "Pay Property Tax"
    assert task.completed_on == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert len(histories) == 1
    assert histories[0].task is task
    assert histories[0].name == "Pay Property Tax"
    assert histories[0].completed_on == datetime(2024, 7, 1, tzinfo=timezone.utc)


# @features ai-report tasks task-completion
# @dimensions completed-task automatic-task-family ambiguity
@pytest.mark.unit
def test_run_report_keeps_ambiguous_completed_task_families_distinct(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("ambiguous-property-tax-owner")
    page = TestEntities.get(
        "PAGE", {"name": "Property Tax", "hash": "ambiguous-property-tax-page"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Finances", "hash": "ambiguous-finances-project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Payments", "hash": "ambiguous-payments-model"},
        project=project,
    )
    first = TestEntities.get(
        "TASK", {"name": "Pay Property Tax", "hash": "property-tax-first"},
        page=page,
    )
    second = TestEntities.get(
        "TASK", {"name": "Pay Property Tax", "hash": "property-tax-second"},
        page=page,
    )
    first.model = model
    second.model = model
    page._tasks = [first, second]
    page._completed = []
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Ambiguous property tax payment",
            "hash": "ambiguous-property-tax-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record a payment without selecting a duplicate.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "property_tax_2026",
                        "type": "create_task",
                        "data": {
                            "name": "Pay Property Tax - April 2026 Installment",
                            "page": page.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2026-04-01",
                        },
                    }
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page, model.urlsafe_key: model}),
    )

    result = report_runner.run_report(report, user)

    created_tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
        and entity.key not in {first.key, second.key}
    ]
    assert result["status"] == "complete"
    assert result["actions"][0]["created"] is True
    assert result["actions"][0]["target"]["id"] not in {
        first.urlsafe_key,
        second.urlsafe_key,
    }
    assert len(created_tasks) == 1
    assert first.completed is False
    assert second.completed is False


# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity page-validation
@pytest.mark.unit
def test_run_report_rejects_completed_task_target_from_another_page(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-page-mismatch-owner")
    prescriptions = TestEntities.get(
        "PAGE",
        {"name": "Prescriptions", "hash": "prescriptions-target-page"},
    )
    appointments = TestEntities.get(
        "PAGE",
        {"name": "Appointments", "hash": "appointments-action-page"},
    )
    task = TestEntities.get(
        "TASK",
        {"name": "Lisinopril Prescription", "hash": "lisinopril-target-task"},
        page=prescriptions,
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Mismatched task target report",
            "hash": "mismatched-task-target-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Invalid cross-page completion.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "lisinopril_completion",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": appointments.urlsafe_key,
                            "task": task.urlsafe_key,
                            "completed": True,
                        },
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                appointments.urlsafe_key: appointments,
                task.urlsafe_key: task,
            }
        ),
    )
    monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "skipped"
    assert "does not belong to the referenced page" in (
        result["actions"][0]["error"]
    )
    assert task.completed is False


# @features ai-report tasks task-completion
# @dimensions completed-task task-form missing-submission continue
@pytest.mark.unit
def test_run_report_warns_but_continues_when_task_form_submission_missing(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("missing-task-submission-owner")
    page = TestEntities.get("PAGE", {"name": "Paul Mitrani, M.D.", "hash": "doctor"})
    project = TestEntities.get("PROJECT", {"name": "Medical", "hash": "medical"})
    form = TestEntities.get(
        "FORM",
        {"name": "Specialist Consultations", "hash": "specialist-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Specialist Consultations", "hash": "specialist-model"},
        project=project,
    )
    model.form = form
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Missing completed task submission report",
            "hash": "missing-completed-task-submission-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record a completed screening without confident fields.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "create_completed_cdi2",
                        "type": "create_task",
                        "display_label": "Record CDI-2 Depression Screen",
                        "data": {
                            "name": "CDI-2 Depression Screen",
                            "page": page.urlsafe_key,
                            "page_name": page.name,
                            "project": project.urlsafe_key,
                            "project_name": project.name,
                            "model": model.urlsafe_key,
                            "model_name": model.name,
                            "completed_on": "2021-10-23",
                        },
                    }
                ],
            },
        },
    )
    saved = []
    captured = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
        form.urlsafe_key: form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["submission"] == {
        "created": False,
        "field_count": 0,
    }
    assert report.status == "complete"
    assert captured == [
        {
            "error": "AI report create_task used a task form but omitted submission data.",
            "level": "warning",
            "context": {
                "ai_report_runner": {
                    "operation": "create_task_missing_submission",
                    "report": report_runner._diagnostic_entity(report),
                    "action": {
                        "id": "create_completed_cdi2",
                        "type": "create_task",
                        "display_label": "Record CDI-2 Depression Screen",
                        "data_keys": [
                            "completed_on",
                            "model",
                            "model_name",
                            "name",
                            "page",
                            "page_name",
                            "project",
                            "project_name",
                        ],
                        "completed_on": "2021-10-23",
                        "submission_key_present": False,
                    },
                    "page": report_runner._diagnostic_entity(page),
                    "project": report_runner._diagnostic_entity(project),
                    "model": report_runner._diagnostic_entity(model),
                    "form": report_runner._diagnostic_entity(form),
                    "form_schema": report_runner._diagnostic_schema(form),
                    "files": [],
                }
            },
        }
    ]


# @features ai-report tasks forms
# @dimensions deterministic-run mismatched-form recoverable continue
@pytest.mark.unit
def test_run_report_skips_task_that_references_page_form_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("task-page-form-owner")
    page = TestEntities.get("PAGE", {"name": "Client", "hash": "client-page"})
    page_form = TestEntities.get(
        "FORM",
        {"name": "Client Intake", "hash": "client-page-form"},
    )
    page_form.form_type = "page"
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Task page form mismatch report",
            "hash": "task-page-form-mismatch-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Skip the bad task and still create the page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "bad_task",
                        "type": "create_task",
                        "display_label": "Create task with page form",
                        "data": {
                            "name": "Client follow-up",
                            "page": page.urlsafe_key,
                            "form": page_form.urlsafe_key,
                            "submission": {"input-notes": "Follow-up"},
                        },
                    },
                    {
                        "id": "good_page",
                        "type": "create_page",
                        "data": {"name": "Still Built"},
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        page_form.urlsafe_key: page_form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "skipped"
    assert result["actions"][0]["error"] == report_runner.TASK_FORM_TYPE_ERROR
    assert result["actions"][0]["note"] == (
        "Skipped because the action referenced a page form instead of a task form."
    )
    assert result["actions"][1]["status"] == "complete"
    assert result["actions"][1]["entity"]["name"] == "Still Built"
    assert report.status == "complete"


# @features ai-report tasks task-completion
# @dimensions task-history page-reference repair
@pytest.mark.unit
def test_run_report_resolves_task_page_by_exact_page_name_when_reference_is_wrong_kind(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-page-repair-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Wrong page reference report",
            "hash": "history-page-repair-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Record registration history on Jeep.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Jeep Registration - Jun 2023",
                            "page": file.urlsafe_key,
                            "page_name": "Jeep",
                            "completed_on": "2023-06-24",
                        },
                    },
                    {
                        "id": "attach_registration_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2023",
                            "file": "2023-06-24 jeep registration.pdf",
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
        _fetch_one_from(
            {
                file.urlsafe_key: file,
                page.urlsafe_key: page,
            }
        ),
    )
    monkeypatch.setattr(
        report_runner.cache,
        "search",
        lambda *args, **kwargs: (
            [{"id": page.urlsafe_key, "kind": "page", "name": "Jeep"}],
            1,
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    created_tasks = {
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    }
    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert len(created_tasks) == 1
    created_task = next(iter(created_tasks.values()))
    assert created_task.page is page
    assert created_task.name == "Registration"
    assert created_task.completed is True
    assert created_task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert created_task.files == [file]
    assert set(file.db["tasks"]) == {created_task.key}
    assert len(histories) == 0
    assert result["actions"][0]["entity"]["name"] == "Registration"
    assert result["actions"][0]["target"]["id"] == result["actions"][0]["entity"]["id"]
    assert result["actions"][1]["type"] == "attach_file_to_task"
    assert result["actions"][1]["target"]["id"] == result["actions"][0]["entity"]["id"]


# @features ai-report files
# @dimensions attachment page-reference repair prior-task-page
@pytest.mark.unit
def test_run_report_resolves_attachment_page_from_single_prior_task_when_reference_is_file(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("attachment-page-repair-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "368 Pettis Ave Residence", "hash": "pettis-insurance-page"},
    )
    file_2022 = _test_file("2022-01-17 pettis insurance.pdf", "application/pdf")
    file_2023 = _test_file("2023-01-17 Pettis Insurance.pdf", "application/pdf")
    file_2025 = _test_file(
        "2025 homeowners insurance declaration.pdf",
        "application/pdf",
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Insurance renewal report",
            "hash": "insurance-renewal-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_2022, file_2023, file_2025],
            "proposal": {
                "summary": "Track homeowners insurance renewals.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "task_2022_renewal",
                        "type": "create_task",
                        "display_label": "2022 Homeowners Insurance Renewal",
                        "data": {
                            "name": "2022 Homeowners Insurance Renewal",
                            "page": page.urlsafe_key,
                            "completed_on": "2022-01-17",
                        },
                    },
                    {
                        "id": "attach_2022_renewal",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "task_2022_renewal",
                            "file": file_2022.urlsafe_key,
                        },
                    },
                    {
                        "id": "task_2023_renewal",
                        "type": "create_task",
                        "display_label": "2023 Homeowners Insurance Renewal",
                        "data": {
                            "name": "2023 Homeowners Insurance Renewal",
                            "page": page.urlsafe_key,
                            "completed_on": "2023-01-17",
                        },
                    },
                    {
                        "id": "attach_2023_renewal",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "task_2023_renewal",
                            "file": file_2023.urlsafe_key,
                        },
                    },
                    {
                        "id": "attach_2025_file",
                        "type": "attach_file_to_page",
                        "display_label": "Attach 2025 Homeowners Insurance Document",
                        "data": {
                            "page": file_2025.urlsafe_key,
                            "file": file_2025.urlsafe_key,
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
        _fetch_one_from(
            {
                page.urlsafe_key: page,
                file_2022.urlsafe_key: file_2022,
                file_2023.urlsafe_key: file_2023,
                file_2025.urlsafe_key: file_2025,
            }
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert [action["status"] for action in result["actions"]] == [
        "complete",
        "complete",
        "complete",
        "complete",
        "complete",
    ]
    assert result["actions"][4]["type"] == "attach_file_to_page"
    assert result["actions"][4]["target"]["id"] == page.urlsafe_key
    assert result["actions"][4]["entity"]["id"] == file_2025.urlsafe_key
    assert file_2025.db["pages"] == [page.key]
    created_tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    ]
    assert len({task.key for task in created_tasks}) == 2


# @features ai-report files
# @dimensions attachment page-reference repair exact-page-name
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
        report_runner.cache,
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


# @features ai-report
# @dimensions deterministic-run partial-result recoverable continue attachments
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
        report_runner.exceptions,
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


# @features ai-report
# @dimensions deterministic-run validation partial-result attachments
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
        report_runner.cache,
        "search",
        lambda *args, **kwargs: ([], 0),
    )
    monkeypatch.setattr(
        report_runner.exceptions,
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


# @features ai-report
# @dimensions completed-task validation recoverable continue
@pytest.mark.unit
def test_run_report_skips_invalid_completed_task_events_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    cases = [
        (
            {
                "name": "Registration",
                "page": "jeep-page",
                "completed_on": "not-a-date",
            },
            "page",
            "completion date is invalid",
        ),
        (
            {
                "name": "Registration",
                "page": "missing-page",
                "completed_on": "2023-06-24",
            },
            None,
            "Referenced entity not found",
        ),
    ]

    for index, (data, entity, expected_error) in enumerate(cases):
        user = _test_user(f"history-invalid-owner-{index}")
        page = TestEntities.get(
            "PAGE",
            {"name": "Jeep", "hash": f"jeep-invalid-page-{index}"},
        )
        file = _test_file("registration.pdf", "application/pdf")
        report = TestEntities.get(
            "REPORT",
            {
                "name": "Invalid task history report",
                "hash": f"invalid-history-{index}",
                "parent": user,
                "user": user,
                "status": "ready",
                "pending": False,
                "input_files": [file],
                "proposal": {
                    "summary": "Invalid completed task.",
                    "confidence": 0.5,
                    "actions": [
                        {
                            "id": "completed_task",
                            "type": "create_task",
                            "data": data,
                        },
                        {
                            "id": "continued_project",
                            "type": "create_project",
                            "data": {"name": "Still Runs"},
                        },
                    ],
                },
            },
        )

        monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)
        monkeypatch.setattr(
            report_runner.Entities,
            "fetch_one",
            _fetch_one_from({"jeep-page": page} if entity else {}),
        )

        result = report_runner.run_report(report, user)

        assert result["status"] == "complete"
        assert "failed_at" not in result
        assert report.status == "complete"
        assert result["actions"][0]["status"] == "skipped"
        assert expected_error in result["actions"][0]["error"]
        assert result["actions"][0]["note"] == (
            "Skipped because this action could not be completed."
        )
        assert result["actions"][1]["status"] == "complete"
        assert result["actions"][1]["entity"]["name"] == "Still Runs"


def _recovery_store(monkeypatch, *initial):
    stored = {entity.urlsafe_key: entity for entity in initial}
    saves = []

    def save(*entities):
        saves.append(tuple(entities))
        for entity in entities:
            if getattr(entity, "entity_kind", None) != "report":
                stored[entity.urlsafe_key] = entity

    def fetch_one(identifier, *, request):
        if hasattr(identifier, "db"):
            return identifier
        return stored.get(identifier)

    monkeypatch.setattr(report_runner.Entities, "save", save)
    monkeypatch.setattr(report_runner.Entities, "fetch_one", fetch_one)
    return stored, saves


# @features ai-report
# @dimensions deterministic-run recovery create idempotency completed-prefix
@pytest.mark.unit
def test_run_report_retry_resumes_after_completed_create_without_duplicate(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-create-recovery-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Create recovery report",
            "hash": "create-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Create two projects.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "first_project",
                        "type": "create_project",
                        "data": {"name": "First Project"},
                    },
                    {
                        "id": "second_project",
                        "type": "create_project",
                        "data": {"name": "Second Project"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch)
    original_execute = report_action_lifecycle._execute_action
    calls = []
    failed = {"value": False}

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "second_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("injected interruption")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)

    first = report_runner.run_report(report, user)

    assert first["status"] == "failed"
    assert [record["status"] for record in first["actions"]] == [
        "complete",
        "failed",
    ]
    assert all(record.get("idempotency_key") for record in first["actions"])
    first_key = first["actions"][0]["entity"]["id"]
    assert first_key in stored

    recovered = report_runner.run_report(report, user)

    assert recovered["status"] == "complete"
    assert [record["status"] for record in recovered["actions"]] == [
        "complete",
        "complete",
    ]
    assert calls == ["first_project", "second_project", "second_project"]
    assert recovered["actions"][0]["entity"]["id"] == first_key
    assert len(
        [entity for entity in stored.values() if entity.entity_kind == "project"]
    ) == 2


# @features ai-report
# @dimensions deterministic-run recovery permissions completed-prefix
@pytest.mark.unit
def test_run_report_retry_stops_when_completed_prefix_permission_is_revoked(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-recovery-permission-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Permission recovery report",
            "hash": "permission-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Create two projects.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "first_project",
                        "type": "create_project",
                        "data": {"name": "First Project"},
                    },
                    {
                        "id": "second_project",
                        "type": "create_project",
                        "data": {"name": "Second Project"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch)
    original_execute = report_action_lifecycle._execute_action
    calls = []

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "second_project":
            raise RuntimeError("injected interruption")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)
    first = report_runner.run_report(report, user)
    project = stored[first["actions"][0]["entity"]["id"]]
    monkeypatch.setattr(
        type(project),
        "allowed",
        lambda self, action, user=None: False,
    )

    recovered = report_runner.run_report(report, user)

    assert recovered["status"] == "failed"
    assert recovered["actions"][0]["status"] == "failed"
    assert "state has changed" in recovered["actions"][0]["error"]
    assert calls == ["first_project", "second_project"]


# @features ai-report
# @dimensions deterministic-run recovery post-commit-checkpoint idempotency
@pytest.mark.unit
def test_run_report_reconciles_applying_create_when_output_already_exists(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-applying-recovery-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Applying recovery report",
            "hash": "applying-recovery-report",
            "parent": user,
            "user": user,
            "status": "failed",
            "proposal": {
                "summary": "Create one project.",
                "confidence": 1,
                "issues": [],
                "actions": [
                    {
                        "id": "project",
                        "type": "create_project",
                        "data": {"name": "Recovered Project"},
                    }
                ],
            },
        },
    )
    fingerprint = report_runner._proposal_fingerprint(report.proposal)
    ledger = report_runner._new_report_ledger(report, report.proposal, fingerprint)
    output_key = entity_module.database.create_key("project", None)
    output_id = entity_module.database.get.urlsafe_key(output_key)
    project = TestEntities.get(
        "PROJECT", {"name": "Recovered Project", "hash": "recovered-project"}
    )
    project.db["hash"] = output_id
    ledger["status"] = "failed"
    ledger["actions"][0].update(
        {
            "prepared": True,
            "status": "applying",
            "attempts": 1,
            "output_key": output_id,
        }
    )
    report.result = ledger
    stored, _saves = _recovery_store(monkeypatch, project)
    monkeypatch.setattr(
        report_runner,
        "_execute_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reconciled action should not execute again")
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["entity"]["id"] == output_id
    assert list(stored) == [output_id]


# @features ai-report
# @dimensions deterministic-run recovery moves batch-field-patch completed-prefix
@pytest.mark.parametrize("first_action", ["move", "update"])
@pytest.mark.unit
def test_run_report_retry_validates_completed_move_and_update_prefix(
    monkeypatch,
    first_action,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user(f"report-{first_action}-recovery-owner")
    old_category = TestEntities.get(
        "CATEGORY", {"name": "Old", "hash": f"{first_action}-old-category"}
    )
    new_category = TestEntities.get(
        "CATEGORY", {"name": "New", "hash": f"{first_action}-new-category"}
    )
    page = TestEntities.get(
        "PAGE", {"name": "Recovery Page", "hash": f"{first_action}-page"}
    )
    page.model = old_category
    form = TestEntities.get(
        "FORM", {"name": "Recovery Form", "hash": f"{first_action}-form"}
    )
    form.form_type = "page"
    form.schema = [
        {
            "id": "input-state",
            "type": "input",
            "input": "text",
            "title": "State",
        }
    ]
    page.form = form
    page.properties.submission.value = {"input-state": "old"}
    action = (
        {
            "id": "move_page",
            "type": "move_page",
            "data": {
                "page": page.urlsafe_key,
                "category": new_category.urlsafe_key,
            },
        }
        if first_action == "move"
        else {
            "id": "update_page",
            "type": "update_submission_fields",
            "data": {
                "updates": [
                    {
                        "page": page.urlsafe_key,
                        "schema_id": "input-state",
                        "new_value": "new",
                    }
                ]
            },
        }
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": f"{first_action.title()} recovery report",
            "hash": f"{first_action}-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Apply one mutation, then create a project.",
                "confidence": 1,
                "actions": [
                    action,
                    {
                        "id": "finish_project",
                        "type": "create_project",
                        "data": {"name": "Finish Recovery"},
                    },
                ],
            },
        },
    )
    _stored, _saves = _recovery_store(
        monkeypatch,
        old_category,
        new_category,
        page,
        form,
    )
    original_execute = report_action_lifecycle._execute_action
    calls = []
    failed = {"value": False}

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "finish_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("injected second-action failure")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)

    assert report_runner.run_report(report, user)["status"] == "failed"
    assert report_runner.run_report(report, user)["status"] == "complete"

    assert calls == [action["id"], "finish_project", "finish_project"]
    if first_action == "move":
        assert page.model is None
        assert page.categories == [new_category]
    else:
        assert page.submission == {"input-state": "new"}


# @features ai-report
# @dimensions deterministic-run compensation failed-prefix idempotency
@pytest.mark.unit
def test_undo_report_compensates_completed_prefix_of_failed_report(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-prefix-undo-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Prefix undo report",
            "hash": "prefix-undo-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Create projects with an interruption.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "kept_project",
                        "type": "create_project",
                        "data": {"name": "Temporary Project"},
                    },
                    {
                        "id": "failed_project",
                        "type": "create_project",
                        "data": {"name": "Never Created"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch)
    original_execute = report_action_lifecycle._execute_action

    def interrupted(action, *args, **kwargs):
        if action["id"] == "failed_project":
            raise RuntimeError("stop after prefix")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)
    deleted = []

    def delete(*entities):
        for entity in entities:
            deleted.append(entity)
            stored.pop(entity.urlsafe_key, None)

    monkeypatch.setattr(report_runner.Entities, "delete", delete)

    result = report_runner.run_report(report, user)
    created_id = result["actions"][0]["entity"]["id"]
    assert result["status"] == "failed"
    assert created_id in stored

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert created_id not in stored
    assert len(deleted) == 1
    assert report.result["status"] == "undone"
    with pytest.raises(exceptions.ValidationError, match="already been undone"):
        report_runner.undo_report(report, user)


# @features ai-report
# @dimensions deterministic-run recovery completed-task reuse compensation
@pytest.mark.unit
def test_completed_task_retry_and_undo_restore_reused_task(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-completed-task-recovery-owner")
    page = TestEntities.get(
        "PAGE", {"name": "Vehicle", "hash": "completed-task-recovery-page"}
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Registration",
            "description": "Before report",
            "hash": "completed-task-recovery-task",
        },
    )
    task.page = page
    task.description = "Before report"
    task.completed = False
    task.submission = {"status": "pending"}
    page._tasks = [task]
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Completed task recovery report",
            "hash": "completed-task-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Record completion, then create a project.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "registration_completion",
                        "type": "create_task",
                        "data": {
                            "page": page.urlsafe_key,
                            "task": task.urlsafe_key,
                            "name": "Registration",
                            "description": "After report",
                            "completed_on": "2026-05-01",
                            "submission": {"status": "complete"},
                        },
                    },
                    {
                        "id": "finish_project",
                        "type": "create_project",
                        "data": {"name": "Recovery Finished"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch, page, task)
    original_execute = report_action_lifecycle._execute_action
    calls = []
    failed = {"value": False}

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "finish_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("stop after task mutation")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)

    first = report_runner.run_report(report, user)

    assert first["status"] == "failed"
    assert first["actions"][0]["created"] is False
    assert task.completed is True
    assert task.description == "After report"

    recovered = report_runner.run_report(report, user)

    assert recovered["status"] == "complete"
    assert calls == [
        "registration_completion",
        "finish_project",
        "finish_project",
    ]

    def delete(*entities):
        for entity in entities:
            stored.pop(entity.urlsafe_key, None)

    monkeypatch.setattr(report_runner.Entities, "delete", delete)
    report_runner.undo_report(report, user)

    assert task.completed is False
    assert task.description == "Before report"
    assert task.submission == {"status": "pending"}
    assert report.result["status"] == "undone"


# @features ai-report
# @dimensions result grouping completed-task-history
@pytest.mark.unit
def test_grouped_result_actions_groups_page_files_tasks_and_summaries():
    user = _test_user("page-result-owner")
    page = {
        "id": "page-utilities",
        "kind": "page",
        "name": "Utilities",
        "url": "/pages/page-utilities",
    }
    task = {
        "id": "task-backflow",
        "kind": "task",
        "name": "Backflow Inspection",
        "url": "/tasks/task-backflow",
    }
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Page grouped result report",
            "hash": "page-grouped-result-report",
            "parent": user,
            "user": user,
            "result": {
                "status": "complete",
                "actions": [
                    {
                        "id": "attach_plan",
                        "type": "attach_file_to_page",
                        "status": "complete",
                        "entity": {
                            "id": "file-plan",
                            "kind": "file",
                            "name": "Utility Plan",
                        },
                        "target": page,
                        "file_summary": {"present": False, "complete": False},
                    },
                    {
                        "id": "task",
                        "type": "create_task",
                        "status": "complete",
                        "created": True,
                        "entity": task,
                        "page": page,
                        "project": {
                            "id": "project-home",
                            "kind": "project",
                            "name": "Home Remodeling",
                        },
                        "model": {
                            "id": "model-plumbing",
                            "kind": "model",
                            "name": "Plumbing Work",
                        },
                        "form": {
                            "id": "form-plumbing",
                            "kind": "form",
                            "name": "Plumbing Work",
                        },
                        "submission": {"created": True, "field_count": 2},
                        "attachments": [
                            {
                                "entity": {
                                    "id": "file-water",
                                    "kind": "file",
                                    "name": "Water Photo",
                                },
                                "summary": {"present": True, "complete": False},
                            }
                        ],
                    },
                    {
                        "id": "attach_invoice",
                        "type": "attach_file_to_task",
                        "status": "complete",
                        "entity": {
                            "id": "file-invoice",
                            "kind": "file",
                            "name": "Plumbing Invoice",
                        },
                        "target": task,
                        "file_summary": {"present": False, "complete": False},
                    },
                    {
                        "id": "summary_invoice",
                        "type": "summarize_file",
                        "status": "complete",
                        "entity": {
                            "id": "file-invoice",
                            "kind": "file",
                            "name": "Plumbing Invoice",
                        },
                        "file_summary": {"present": True, "complete": True},
                    },
                    {
                        "id": "summary_orphan",
                        "type": "summarize_file",
                        "status": "complete",
                        "entity": {
                            "id": "file-not-attached",
                            "kind": "file",
                            "name": "Loose Summary",
                        },
                        "file_summary": {"present": True, "complete": True},
                    },
                ],
            },
        },
    )

    grouped = report.properties.result.grouped_actions

    assert [action["type"] for action in grouped] == ["page_group", "summarize_file"]
    page_group = grouped[0]
    assert page_group["created"] is False
    assert page_group["entity"]["name"] == "Utilities"
    assert page_group["attachments"][0]["entity"]["name"] == "Utility Plan"
    assert page_group["tasks"][0]["entity"]["name"] == "Backflow Inspection"
    assert page_group["tasks"][0]["submission"] == {"created": True, "field_count": 2}
    assert page_group["tasks"][0]["attachments"][0]["entity"]["name"] == "Water Photo"
    assert page_group["tasks"][0]["attachments"][1]["entity"]["name"] == (
        "Plumbing Invoice"
    )
    assert page_group["tasks"][0]["attachments"][1]["file_summary"] == {
        "present": True,
        "complete": True,
    }
    assert grouped[1]["entity"]["name"] == "Loose Summary"


# @features ai-report
# @dimensions result grouping completed-task-history
@pytest.mark.unit
def test_grouped_result_actions_groups_completed_task_history_under_created_task():
    user = _test_user("history-result-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "History result report",
            "hash": "history-result-report",
            "parent": user,
            "user": user,
            "result": {
                "status": "complete",
                "actions": [
                    {
                        "id": "task",
                        "type": "create_task",
                        "status": "complete",
                        "entity": {
                            "id": "task-new",
                            "kind": "task",
                            "name": "Registration",
                        },
                    },
                    {
                        "id": "history",
                        "type": "create_task",
                        "status": "complete",
                        "entity": {
                            "id": "history-new",
                            "kind": "task_history",
                            "name": "Task history",
                        },
                        "target": {
                            "id": "task-new",
                            "kind": "task",
                            "name": "Registration",
                        },
                        "attachments": [
                            {
                                "entity": {
                                    "id": "file-one",
                                    "kind": "file",
                                    "name": "Registration receipt",
                                }
                            }
                        ],
                    },
                ],
            },
        },
    )

    grouped = report.properties.result.grouped_actions

    assert len(grouped) == 1
    assert grouped[0]["type"] == "create_task"
    assert grouped[0]["histories"][0]["type"] == "create_task"
    assert grouped[0]["histories"][0]["attachments"][0]["entity"]["name"] == (
        "Registration receipt"
    )


# @features ai-report
# @dimensions deterministic-run undo delete-links report-files created-entities file-links
@pytest.mark.unit
def test_undo_report_deletes_created_entities_and_unlinks_files(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("undo-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    task = TestEntities.get(
        "TASK",
        {"name": "Registration", "hash": "registration-task"},
        page=page,
    )
    file = _test_file("registration.pdf", "application/pdf")
    file.db["pages"] = [page.key]
    history = task.create_history_entry(
        completed_on=datetime(2023, 6, 24, tzinfo=timezone.utc),
        files=[file],
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Undo report",
            "hash": "undo-report",
            "parent": user,
            "user": user,
            "status": "complete",
            "pending": False,
            "input_files": [file],
            "result": {
                "ledger_version": report_runner.REPORT_LEDGER_VERSION,
                "proposal_fingerprint": "test-ledger",
                "status": "complete",
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "status": "complete",
                        "created": True,
                        "entity": {
                            "id": page.urlsafe_key,
                            "kind": "page",
                            "name": "Jeep",
                        },
                    },
                    {
                        "id": "attachment",
                        "type": "attach_file_to_page",
                        "status": "complete",
                        "entity": {
                            "id": file.urlsafe_key,
                            "kind": "file",
                            "name": file.name,
                        },
                        "target": {
                            "id": page.urlsafe_key,
                            "kind": "page",
                            "name": "Jeep",
                        },
                    },
                    {
                        "id": "task",
                        "type": "create_task",
                        "status": "complete",
                        "created": True,
                        "entity": {
                            "id": task.urlsafe_key,
                            "kind": "task",
                            "name": "Registration",
                        },
                    },
                    {
                        "id": "history",
                        "type": "create_task",
                        "status": "complete",
                        "created": True,
                        "entity": {
                            "id": history.urlsafe_key,
                            "kind": "task_history",
                            "name": "Task history",
                        },
                        "target": {
                            "id": task.urlsafe_key,
                            "kind": "task",
                            "name": "Registration",
                        },
                        "attachments": [
                            {
                                "entity": {
                                    "id": file.urlsafe_key,
                                    "kind": "file",
                                    "name": file.name,
                                }
                            }
                        ],
                    },
                ],
            },
        },
    )
    entities = {
        page.urlsafe_key: page,
        task.urlsafe_key: task,
        history.urlsafe_key: history,
        file.urlsafe_key: file,
    }
    saved = []
    deleted = []

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
    monkeypatch.setattr(
        report_runner.Entities,
        "delete",
        lambda *entities: deleted.extend(entities),
    )

    undo = report_runner.undo_report(report, user)

    assert undo["status"] == "complete"
    assert report.status == "ready"
    assert report.pending is False
    assert report.result["status"] == "undone"
    assert report.result["undone"] is True
    assert report.error is None
    assert report.summary is None
    assert history in deleted
    assert task in deleted
    assert page in deleted
    assert file not in deleted
    assert file.db.get("pages") is None
    assert history.key not in file.db.get("tasks", [])
    assert task.key not in file.db.get("tasks", [])
    assert all(action["status"] == "complete" for action in undo["actions"])
