import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import (
    AI,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai
from testing.definitions import SitePages, Uploads, Users
from testing.elements import Buttons, List, Modal
from testing.resources import Report

pytestmark = pytest.mark.e2e


def _suffix():
    return uuid4().hex[:8]


def _owner(user):
    return Entities.USER.load(user.email)


def _tool_route_status(user, path):
    return user.page.evaluate(
        """async (path) => {
            const send = async () => {
                const body = new FormData();
                body.set("role", "explain");
                body.set("instructions", "Explain the generated prompt.");
                return fetch(path, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "X-CSRFToken":
                            document.getElementById("token")?.value || "",
                        "X-Lagniappe-Request": "true",
                    },
                    body,
                });
            };

            let response = await send();
            if (response.status === 400) {
                const token = await (await fetch("/token")).text();
                const tokenElt = document.getElementById("token");
                if (tokenElt) tokenElt.value = token;
                response = await send();
            }
            return response.status;
        }""",
        path,
    )


def _ready_report(user):
    owner = _owner(user)
    suffix = _suffix()
    category_name = f"test-organize-category-{suffix}"
    page_name = f"test-organize-page-{suffix}"
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"test-organize-ready-report-{suffix}",
            "status": "ready",
            "pending": False,
            "summary": "Ready seeded organize proposal.",
            "proposal": {
                "summary": "Create a category and page.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "category",
                        "type": "create_category",
                        "data": {"name": category_name},
                    },
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {
                            "name": page_name,
                            "category_action": "category",
                        },
                    },
                    {
                        "id": "cleanup",
                        "type": "delete_page",
                        "depends_on": ["page"],
                        "data": {"page_action": "page"},
                    },
                ],
            },
        }
    )
    Entities.save(report, owner)
    return report, category_name, page_name


def _recoverable_failed_report(user):
    owner = _owner(user)
    suffix = _suffix()
    project = Entities.PROJECT.create({"name": f"partial-project-{suffix}"})
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"test-recoverable-report-{suffix}",
            "status": "failed",
            "pending": False,
            "error": "Injected action failure.",
            "proposal": {
                "summary": "Partially completed proposal.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "first",
                        "type": "create_project",
                        "data": {"name": f"partial-project-{suffix}"},
                    },
                    {
                        "id": "second",
                        "type": "create_project",
                        "data": {"name": f"retry-project-{suffix}"},
                    },
                ],
            },
            "result": {
                "ledger_version": ai.REPORT_LEDGER_VERSION,
                "proposal_fingerprint": "display-only-ledger",
                "status": "failed",
                "failed_at": 2,
                "actions": [
                    {
                        "id": "first",
                        "type": "create_project",
                        "status": "complete",
                        "idempotency_key": "first-display-key",
                        "attempts": 1,
                        "created": True,
                        "entity": {
                            "id": project.urlsafe_key,
                            "kind": "project",
                            "name": project.name,
                        },
                        "note": "Created the first project.",
                    },
                    {
                        "id": "second",
                        "type": "create_project",
                        "status": "failed",
                        "idempotency_key": "second-display-key",
                        "attempts": 1,
                        "error": "Injected action failure.",
                    },
                ],
            },
        }
    )
    Entities.save(project, report, owner)
    return report, project


def _dependency_report(user):
    owner = _owner(user)
    suffix = _suffix()
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"test-organize-skip-report-{suffix}",
            "status": "ready",
            "pending": False,
            "summary": "Ready seeded skip proposal.",
            "proposal": {
                "summary": "Create and attach.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "category",
                        "type": "create_category",
                        "display_label": "Create Category",
                        "data": {"name": f"skip-category-{suffix}"},
                    },
                    {
                        "id": "page",
                        "type": "create_page",
                        "display_label": "Create Page",
                        "data": {
                            "name": f"skip-page-{suffix}",
                            "category_action": "category",
                        },
                    },
                    {
                        "id": "review",
                        "type": "needs_review",
                        "display_label": "Review Later",
                        "data": {},
                    },
                ],
            },
        }
    )
    Entities.save(report, owner)
    return report


def _schema_section_report(user):
    owner = _owner(user)
    suffix = _suffix()
    form = Entities.FORM.create(
        {
            "name": f"test-invoice-schema-form-{suffix}",
            "form-type": "page",
            "schema": [
                {
                    "id": "select-status",
                    "type": "select",
                    "title": "Status",
                    "options": [{"value": "due", "label": "Due"}],
                },
                {
                    "id": "input-note",
                    "type": "input",
                    "input": "text",
                    "title": "Note",
                },
            ],
        }
    )
    category = Entities.CATEGORY.create(
        {
            "name": f"test-invoice-schema-category-{suffix}",
            "form": form,
        }
    )
    page = Entities.PAGE.create(
        {
            "name": f"test-invoice-schema-page-{suffix}",
            "model": category,
            "form": form,
            "submission": {
                "select-status": "due",
                "input-note": "unpaid",
            },
        }
    )
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"test-schema-section-report-{suffix}",
            "status": "ready",
            "pending": False,
            "summary": "Ready seeded schema section proposal.",
            "proposal": {
                "summary": "Add a paid option and mark the invoice note paid.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "schema",
                        "type": "update_form_schema",
                        "display_label": "Add paid invoice option",
                        "data": {
                            "form": form.urlsafe_key,
                            "operations": [
                                {
                                    "op": "add_select_option",
                                    "schema_id": "select-status",
                                    "option": {
                                        "value": "paid",
                                        "label": "Paid",
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "id": "update_note",
                        "type": "update_submission_fields",
                        "display_label": "Mark invoice note paid",
                        "depends_on": ["schema"],
                        "data": {
                            "updates": [
                                {
                                    "page": page.urlsafe_key,
                                    "schema_id": "input-note",
                                    "new_value": "paid",
                                }
                            ]
                        },
                    },
                ],
            },
        }
    )
    Entities.save(form, category, page, report, owner)
    return report, form, page


def _create_ready_report(user):
    owner = _owner(user)
    suffix = _suffix()
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"test-create-ready-report-{suffix}",
            "tool": "create",
            "status": "ready",
            "pending": False,
            "summary": "Ready seeded create proposal.",
            "proposal": {
                "summary": "Create a category and starter page.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "category",
                        "type": "create_category",
                        "display_label": "Create Category",
                        "data": {"name": f"create-category-{suffix}"},
                    },
                    {
                        "id": "page",
                        "type": "create_page",
                        "display_label": "Create Page",
                        "data": {
                            "name": f"create-page-{suffix}",
                            "category_action": "category",
                        },
                    },
                ],
            },
        }
    )
    Entities.save(report, owner)
    return report


def _ask_answer_report(user):
    owner = _owner(user)
    question = (
        "Can you create a page in Johanna for family records and move all the "
        "family record files there so I can review the remaining duplicate pages?"
    )
    short_name = f"Ask: {question[:80]}..."
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": short_name,
            "tool": "ask",
            "instructions": question,
            "status": "complete",
            "pending": False,
            "summary": "The Dance-Punk task exists.",
            "proposal": {
                "summary": "The Dance-Punk task exists.",
                "confidence": 0.9,
                "answer_html": (
                    '<p>Yes. The <a href="/tasks/dance-punk">Dance-Punk</a> '
                    "task exists in the workspace.</p><script>alert('bad')</script>"
                ),
                "actions": [],
            },
        }
    )
    Entities.save(report, owner)
    return report


def _needs_review_report(user):
    owner = _owner(user)
    suffix = _suffix()
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"test-organize-needs-review-{suffix}",
            "tool": "organize",
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "The intended destination needs confirmation.",
                "confidence": 0.4,
                "issues": ["The workspace reference was unclear."],
                "actions": [
                    {
                        "id": "review_organization_plan",
                        "type": "needs_review",
                        "display_label": "Organization plan",
                        "reason": ("This plan could not be made safe automatically."),
                        "data": {
                            "note": "Choose the intended destination.",
                            "questions": ["Where should these files be organized?"],
                        },
                    }
                ],
            },
        }
    )
    Entities.save(report, owner)
    return report


# @features ai-report
# @dimensions upload-form multi-file instructions explain-button ask create tool-switcher
# @template home/tools.html::create_report
def test_tools_create_form_has_expected_controls(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.CREATE_TOOL_REPORT_TOGGLE).click()
    form = user.locate(home.CREATE_TOOL_REPORT_FORM)

    expect(form).to_be_visible()
    expect(form.locator("[data-role='title']")).to_have_text("AI Tools")
    help_button = form.locator("[lp-help='ai_tools']")
    expect(help_button).to_be_visible()
    help_button.click()
    expect(user.page.get_by_text("What This Panel Does")).to_be_visible()
    expect(user.page.get_by_text("Available Tools")).to_be_visible()
    expect(user.page.get_by_text("Ask a question about your workspace")).to_be_visible()
    Modal(user.page).close()
    expect(form.locator("[lp-close='tools']")).to_be_visible()
    switcher = form.locator("[data-role='tool-switcher']")
    expect(switcher).to_contain_text("Organize")
    expect(switcher).to_contain_text("Ask")
    expect(switcher).to_contain_text("Create")
    expect(form.locator("h3", has_text="Context")).not_to_be_attached()
    dropzone = form.locator("[data-role='dropzone']")
    expect(dropzone).to_contain_text("Drop files")
    instructions = form.locator("textarea[name='instructions']")
    expect(instructions).to_be_visible()
    explain_button = form.locator(Buttons.EXPLAIN)
    expect(
        explain_button.locator(":scope > span:not([data-icon])")
    ).to_have_text("Initial Prompt")
    expect(explain_button).not_to_be_visible()
    instructions.fill("Sort this into the right place.")
    expect(explain_button).to_be_visible()
    expect(explain_button).to_have_accessible_name("Initial Prompt")
    explain_button.click()
    expect(user.page.get_by_text("Organize Planning Output")).to_be_visible()
    Modal(user.page).close()
    switcher.get_by_role("button", name="Ask").click()
    expect(dropzone).not_to_be_visible()
    expect(instructions).to_have_attribute(
        "placeholder", "Ask a question about your workspace..."
    )
    with user.page.expect_response("**/tools/ask"):
        explain_button.click()
    expect(user.page.get_by_text("Answer the user's question directly")).to_be_visible()
    Modal(user.page).close()
    switcher.get_by_role("button", name="Create").click()
    expect(dropzone).not_to_be_visible()
    expect(instructions).to_have_attribute(
        "placeholder", "Describe what you want Lagniappe to create..."
    )
    with user.page.expect_response("**/tools/create"):
        explain_button.click()
    expect(user.page.get_by_text("Create Report Output Requirements")).to_be_visible()
    Modal(user.page).close()
    switcher.get_by_role("button", name="Organize").click()
    expect(dropzone).to_be_visible()
    expect(form.get_by_role("button", name="Start")).to_be_visible()


# @features ai-access
# @dimensions authentication route-gate
# @pair cache:invalidation-acknowledgement
# @template home/home.html::main
# @template home/tools.html::create_report
def test_ai_access_tiers_gate_tool_routes(get_user):
    owner = get_user(Users.OWNER)
    user = get_user(Users.ai_access_tiers, creator=owner)

    for tier, expected_statuses, visible_tools in (
        (AI.NONE, (403, 403, 403), ()),
        (AI.ASK, (403, 200, 403), ("Ask",)),
        (AI.CREATE, (200, 200, 200), ("Organize", "Ask", "Create")),
    ):
        entity = Entities.USER.load(user.email)
        if entity.ai_access != tier.name:
            entity.ai_access = tier
            entity.save()
            assert entity.invalidate_cache is True
            user.entity = entity

            with user.page.context.expect_event(
                "response",
                predicate=lambda response: (
                    response.url.endswith("/validate-user")
                    and response.request.method == "POST"
                ),
            ) as validation_info:
                home = user.go(SitePages.HOME)

            validation = validation_info.value
            assert validation.status == 200
            assert validation.json()["cacheCleared"] is True
            assert Entities.USER.load(user.email).invalidate_cache is False
        else:
            home = user.go(SitePages.HOME)

        toggle = user.locate(home.CREATE_TOOL_REPORT_TOGGLE)
        if tier is AI.NONE:
            expect(toggle).to_have_count(0)
        else:
            expect(toggle).to_be_visible()
            toggle.click()
            form = user.locate(home.CREATE_TOOL_REPORT_FORM)
            expect(form).to_be_visible()
            switcher = form.locator("[data-role='tool-switcher']")
            for tool in ("Organize", "Ask", "Create"):
                button = switcher.get_by_role("button", name=tool, exact=True)
                expect(button).to_have_count(1 if tool in visible_tools else 0)

        statuses = tuple(
            _tool_route_status(user, path)
            for path in ("/tools/organize", "/tools/ask", "/tools/create")
        )
        assert statuses == expected_statuses


# @pair ai-access:report-read
# @pair cache:invalidation-acknowledgement
def test_ask_access_can_read_create_report_without_create_actions(get_user):
    owner = get_user(Users.OWNER)
    user = get_user(Users.ai_access_report_reader, creator=owner)
    report = _create_ready_report(user)

    entity = Entities.USER.load(user.email)
    entity.ai_access = AI.ASK
    entity.save()
    assert entity.invalidate_cache is True
    user.entity = entity

    with user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        report_page = user.go(Report.for_entity(user, report))

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(user.email).invalidate_cache is False

    expect(report_page.title_element).to_have_text(report.name)
    expect(user.page.get_by_role("heading", name="Proposal")).to_be_visible()
    expect(report_page.proposal_actions).to_have_count(1)
    expect(report_page.execute_button).to_have_count(0)
    expect(user.page.get_by_role("button", name="Revise Plan")).to_have_count(0)
    expect(
        report_page.proposal_actions.locator("[data-role='skip-action']")
    ).to_have_count(0)


# @features ai-report
# @dimensions create async persistence title-truncation
# @template home/tools.html::create_report
def test_create_tool_starts_pending_report(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    instructions = (
        f"Create {_suffix()} a household inventory tracker with rooms, warranties, "
        "purchase dates, serial numbers, and replacement values"
    )

    user.locate(home.CREATE_TOOL_REPORT_TOGGLE).click()
    form = user.locate(home.CREATE_TOOL_REPORT_FORM)
    form.locator("[data-role='tool-switcher']").get_by_role(
        "button", name="Create"
    ).click()
    form.locator("textarea[name='instructions']").fill(instructions)

    with user.page.expect_response("**/tools/create"):
        form.get_by_role("button", name="Start").click()

    report_list = List(user.locate(home.TOOL_REPORT_LIST))
    report_name = f"Create: {instructions[:80]}..."
    item = report_list.new_item(report_name, flash=False)
    expect(item.locator("[data-role='report-stage']")).to_have_text("Proposal pending")
    expect(item).to_have_attribute("data-operation", re.compile(".+"))
    expect(item.locator("[data-role='deferred-phase']")).to_have_text(
        "Waiting to start"
    )
    expect(form).to_have_attribute("data-deferred-status", "false")
    expect(form).not_to_have_attribute("data-operation", re.compile(".+"))
    expect(form.locator("[data-role='deferred-progress']")).not_to_be_attached()

    report = Entities.fetch_one(item.get_attribute("data-key"), request=Fetch.direct())
    assert report.name == report_name
    assert report.tool == "create"
    assert report.instructions == instructions
    assert report.input_files == []
    assert report.status == "pending"
    assert report.pending is True


# @features ai-report
# @dimensions list lazy-load status-reconciliation
# @template home/tools.html::report_item
def test_lazy_report_list_reconciles_active_job_status(get_user):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    suffix = _suffix()
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": f"Recovering organize report {suffix}",
            "tool": "organize",
            "status": "pending",
            "pending": True,
            "summary": "Summarized 6 file(s).",
        }
    )
    job = Entities.DEFERRED_JOB.create(
        {
            "actor": owner,
            "job_type": DeferredJobType.REPORT_ORGANIZE.value,
            "idempotency_key": f"recovering-report-{suffix}",
            "status": DeferredJobStatus.RETRY_WAIT.value,
            "dispatch_state": "dispatched",
            "status_revision": 4,
            "inputs": {},
            "client": {
                "source_widget": "CreateToolReport",
                "destination": "tools:ToolReportList",
            },
            "progress": {"phase": DeferredJobPhase.USING_TOOLS.value},
        }
    )
    report.deferred_job = {
        "key": job.urlsafe_key,
        "idempotency_key": job.idempotency_key,
    }
    Entities.save(job, report, owner)

    home = user.go(SitePages.HOME)
    user.locate(home.TOOL_REPORT_LIST_TOGGLE).click()
    report_list = List(user.locate(home.TOOL_REPORT_LIST))
    assert report_list.is_loaded
    item = report_list.list.locator(f"li[data-key='{report.urlsafe_key}']")

    expect(item).to_be_visible()
    expect(item).to_contain_text("Summarized 6 file(s).")
    expect(item).to_have_attribute("data-operation-status", "retry_wait")
    expect(item).to_have_attribute("data-operation-phase", "using_tools")
    expect(item.locator("[data-role='deferred-phase']")).to_have_text(
        "Checking context. Automatic recovery is active."
    )


# @features ai-report
# @dimensions create async text-only ask-fallback
def test_text_only_organize_uses_ask(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    question = f"Where should I record this note? {_suffix()}"

    user.locate(home.CREATE_TOOL_REPORT_TOGGLE).click()
    form = user.locate(home.CREATE_TOOL_REPORT_FORM)
    form.locator("textarea[name='instructions']").fill(question)

    with user.page.expect_response("**/tools/organize"):
        form.get_by_role("button", name="Start").click()

    report_list = List(user.locate(home.TOOL_REPORT_LIST))
    item = report_list.new_item(ai.ask_report_name(question), flash=False)
    expect(item.locator("[data-role='report-stage']")).to_have_text("Answer pending")

    report = Entities.fetch_one(item.get_attribute("data-key"), request=Fetch.direct())
    assert report.tool == "ask"
    assert report.instructions == question
    assert report.input_files == []


def _create_uploaded_report_item(user):
    home = user.go(SitePages.HOME)
    user.locate(home.CREATE_TOOL_REPORT_TOGGLE).click()
    form = user.locate(home.CREATE_TOOL_REPORT_FORM)
    expect(form).to_be_visible()
    form.locator("textarea[name='instructions']").fill(
        f"test organize instructions {_suffix()}"
    )
    Uploads.plain_text_file.set(form)

    with user.page.expect_response("**/tools/organize"):
        form.get_by_role("button", name="Start").click()

    report_list = List(user.locate(home.TOOL_REPORT_LIST))
    assert report_list.is_loaded
    item = report_list.list.locator(
        "li[data-name='Organize: sample_notes.txt'][data-pending='true']"
    )
    expect(item).to_be_visible()
    item = report_list.list.locator(f"li[data-key='{item.get_attribute('data-key')}']")
    report = Entities.fetch_one(item.get_attribute("data-key"), request=Fetch.direct())
    return item, report


# @features ai-report
# @dimensions list create upload async deferred-refresh operation-poll stage-labels
# @template home/tools.html::report_stage_label
# @template home/tools.html::report_item
def test_report_list_item_refreshes_stage_labels(get_user):
    user = get_user(Users.OWNER)
    item, report = _create_uploaded_report_item(user)
    expect(item.locator("[data-role='title']")).to_have_text(
        "Organize: sample_notes.txt"
    )
    expect(item.locator("[data-role='report-stage']")).to_have_text("Proposal pending")
    expect(item).to_contain_text("Analyzing files...")
    expect(item.locator("[lp-delete]")).to_be_visible()

    report_key = item.get_attribute("data-key")

    def reload_item():
        home = user.go(SitePages.HOME)
        user.locate(home.TOOL_REPORT_LIST_TOGGLE).click()
        report_list = List(user.locate(home.TOOL_REPORT_LIST))
        assert report_list.is_loaded
        return report_list.list.locator(f"li[data-key='{report_key}']")

    assert report.input_files == []
    assert len(report.upload_manifest) == 1
    assert report.upload_manifest[0]["filename"] == "sample_notes.txt"
    finalized = ai.finalize_report_upload_manifest(report, _owner(user))
    assert [file.filename for file in finalized] == ["sample_notes.txt"]
    assert [file.filename for file in report.input_files] == ["sample_notes.txt"]
    assert report.upload_manifest is None
    report.status = "ready"
    report.pending = False
    report.summary = "Ready from deferred refresh."
    report.proposal = {
        "summary": "Ready from deferred refresh.",
        "actions": [
            {
                "id": "review",
                "type": "needs_review",
                "display_label": "Review imported notes",
                "data": {},
            },
        ],
    }
    job = Entities.fetch_one(report.deferred_job["key"], request=Fetch.direct())
    job.status = DeferredJobStatus.SUCCEEDED.value
    job.status_revision += 1
    Entities.save(job, report, _owner(user))

    expect(item.locator("[data-role='report-stage']")).to_have_text(
        "Needs review",
        timeout=10_000,
    )
    expect(item).to_contain_text("Ready from deferred refresh.")
    expect(item).not_to_contain_text("Analyzing files...")

    report.tool = "organize"
    report.status = "ready"
    report.proposal = {
        "summary": "Executable proposal.",
        "actions": [
            {"type": "needs_review", "data": {}},
            {"type": "create_page", "data": {}},
        ],
    }
    Entities.save(report, _owner(user))
    item = reload_item()
    expect(item.locator("[data-role='report-stage']")).to_have_text("Proposal ready")

    report.tool = "create"
    report.status = "complete"
    report.proposal = {
        "summary": "Executed proposal.",
        "actions": [{"type": "create_page", "data": {}}],
    }
    Entities.save(report, _owner(user))
    item = reload_item()
    expect(item.locator("[data-role='report-stage']")).to_have_text("Proposal executed")

    report.tool = "ask"
    report.proposal = {
        "summary": "Answer summary.",
        "answer_html": "<p>Answer body.</p>",
        "actions": [],
    }
    Entities.save(report, _owner(user))
    item = reload_item()
    expect(item.locator("[data-role='report-stage']")).to_have_text("Answer ready")


# @features ai-report
# @dimensions list create upload delete-modal file-cleanup
# @template home/tools.html::report_item
def test_report_list_item_delete_removes_report_only_file(get_user):
    user = get_user(Users.OWNER)
    item, report = _create_uploaded_report_item(user)

    finalized = ai.finalize_report_upload_manifest(report, _owner(user))
    assert len(finalized) == 1
    uploaded_file = finalized[0]

    item.locator("[lp-delete]").click()
    modal = Modal(user.page)
    expect(modal.element).to_contain_text("Delete AI Report")

    with user.page.expect_response("**/tools/reports/*"):
        modal.delete()
    expect(item).not_to_be_attached()
    assert Entities.fetch_one(report.urlsafe_key, request=Fetch.root()) is None
    assert Entities.fetch_one(uploaded_file.urlsafe_key, request=Fetch.root()) is None


# @features ai-report
# @dimensions detail deterministic-run result-json delete-modal repeat-run idempotent
def test_report_detail_runs_ready_report(get_user):
    user = get_user(Users.OWNER)
    report, category_name, page_name = _ready_report(user)

    report_page = user.go(Report.for_entity(user, report))
    expect(report_page.execute_button).to_be_visible()
    report_page.execute()

    expect(user.page.get_by_text("Work done.")).to_be_visible()
    expect(report_page.execute_button).not_to_be_visible()
    expect(user.page.get_by_role("link", name=category_name)).to_be_visible()
    page_link = user.page.get_by_role("link", name=page_name).first
    expect(page_link).to_be_visible()
    assert "/pages/" in page_link.get_attribute("href")
    json_panel = report_page.expand_json("Result JSON")
    expect(json_panel).to_contain_text('"status": "complete"')
    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    assert saved_report.status == "complete"
    repeat_run = user.page.evaluate(
        """async (url) => {
            const response = await fetch(url, {
                method: "POST",
                credentials: "include",
                headers: {
                    "X-CSRFToken": document.querySelector("#token").value,
                    "X-Lagniappe-Request": "true",
                },
            });
            return {status: response.status, text: await response.text()};
        }""",
        f"/tools/reports/{report.urlsafe_key}/run",
    )
    assert repeat_run["status"] == 200
    assert (
        "Only ready or recoverable failed reports can be run" not in repeat_run["text"]
    )
    created = {
        action["entity"]["kind"]: action["entity"]["id"]
        for action in saved_report.result["actions"]
        if "entity" in action
    }
    category = Entities.fetch_one(created["category"], request=Fetch.direct())
    page = Entities.fetch_one(created["page"], request=Fetch.direct())
    assert category.name == category_name
    assert page.name == page_name

    user.page.get_by_role("button", name=f"Delete {page_name}").click()
    modal = Modal(user.page)
    expect(modal.element.get_by_role("heading")).to_have_accessible_name(
        "Delete Page"
    )
    delete_button = modal.element.get_by_role("button", name=f"Delete {page_name}")
    expect(delete_button).to_have_attribute(
        "data-route",
        re.compile(rf"/pages/{re.escape(page.urlsafe_key)}/delete$"),
    )
    modal.element.get_by_role("button", name="Cancel").click()


# @features ai-report
# @dimensions detail recovery retry failed-prefix undo deterministic-undo failure reload
def test_failed_report_detail_offers_retry_and_partial_undo(get_user):
    user = get_user(Users.OWNER)
    report, project = _recoverable_failed_report(user)

    user.go(Report.for_entity(user, report))

    run_form = user.page.locator("[data-role='retry-report-form']")
    error = run_form.locator("[data-role='error']")
    expect(error).to_be_visible()
    expect(error).to_have_text("Injected action failure.")
    expect(user.page.get_by_role("button", name="Retry Proposal")).to_be_visible()
    assert (
        error.bounding_box()["y"]
        < user.page.get_by_role("button", name="Retry Proposal").bounding_box()["y"]
    )
    expect(
        user.page.get_by_role("button", name="Undo Completed Actions")
    ).to_be_visible()

    with user.page.expect_response("**/tools/reports/*/undo"):
        user.page.get_by_role("button", name="Undo Completed Actions").click()

    expect(user.page.get_by_text("Work undone.")).to_be_visible(timeout=10000)
    assert Entities.fetch_one(project.urlsafe_key, request=Fetch.root()) is None


# @features ai-report
# @dimensions ask detail answer-html links no-actions completed-state
def test_ask_report_detail_shows_answer_without_duplicate_proposal(get_user):
    user = get_user(Users.OWNER)
    report = _ask_answer_report(user)

    report_page = user.go(Report.for_entity(user, report))

    expect(report_page.title_element).to_have_text(f"Ask: {report.instructions}")
    expect(report_page.title_element).not_to_have_text(report.name)
    expect(user.page.get_by_role("heading", name="Answer")).to_be_visible()
    expect(user.page.get_by_role("heading", name="Status")).not_to_be_visible()
    expect(user.page.get_by_role("heading", name="Proposal")).not_to_be_visible()
    expect(
        user.page.get_by_role("heading", name="Suggested Actions")
    ).not_to_be_visible()
    expect(user.page.get_by_role("button", name="Revise Response")).not_to_be_attached()
    answer = report_page.answer
    expect(answer.get_by_role("link", name="Dance-Punk")).to_have_attribute(
        "href", "/tasks/dance-punk"
    )
    expect(answer.locator("script")).not_to_be_attached()
    expect(report_page.execute_button).not_to_be_visible()


# @features ai-report
# @dimensions revision ready-state completed-state route-guard
def test_report_revision_is_only_available_before_completion(get_user):
    user = get_user(Users.OWNER)
    owner = _owner(user)

    for tool in ("ask", "organize", "create"):
        suffix = _suffix()
        report = Entities.REPORT.create(
            {
                "parent": owner,
                "user": owner,
                "name": f"test-{tool}-revision-state-{suffix}",
                "tool": tool,
                "status": "ready",
                "pending": False,
                "proposal": {
                    "summary": f"Ready {tool} response.",
                    "actions": [
                        {
                            "id": "review",
                            "type": "needs_review",
                            "display_label": "Review response",
                            "data": {},
                        }
                    ],
                },
            }
        )
        Entities.save(report, owner)

        user.go(Report.for_entity(user, report))
        button_name = "Revise Response" if tool == "ask" else "Revise Plan"
        expect(user.page.get_by_role("button", name=button_name)).to_be_visible()

        report.status = "complete"
        Entities.save(report, owner)
        user.page.reload()
        expect(user.page.get_by_role("button", name=button_name)).not_to_be_attached()

        response = user.page.evaluate(
            """async (url) => {
                const response = await fetch(url, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-CSRFToken": document.querySelector("#token").value,
                        "X-Lagniappe-Request": "true",
                    },
                    body: new URLSearchParams({feedback: "Change the response."}),
                });
                return {status: response.status, text: await response.text()};
            }""",
            f"/tools/reports/{report.urlsafe_key}/revise",
        )
        assert response["status"] == 422
        assert "Only reports with saved responses can be revised" in response["text"]


# @features ai-report
# @dimensions detail needs-review no-execute revision
# @template tools/report.html::proposal_action_item
def test_report_detail_shows_review_only_proposal_without_execute(get_user):
    user = get_user(Users.OWNER)
    report = _needs_review_report(user)

    report_page = user.go(Report.for_entity(user, report))

    expect(report_page.proposal_actions).to_have_count(1)
    expect(report_page.proposal_actions).to_contain_text(
        "Needs Review: Organization plan"
    )
    expect(report_page.proposal_actions).to_contain_text(
        "could not be made safe automatically"
    )
    expect(
        report_page.proposal_actions.locator("[data-role='skip-action']")
    ).to_have_count(0)
    expect(report_page.execute_button).not_to_be_visible()
    expect(user.page.get_by_role("button", name="Revise Plan")).to_be_visible()


# @features ai-report
# @dimensions create detail revision skip-action execute
def test_create_report_detail_shows_revision_and_manual_execution(get_user):
    user = get_user(Users.OWNER)
    report = _create_ready_report(user)

    report_page = user.go(Report.for_entity(user, report))

    expect(report_page.title_element).to_have_text(report.name)
    expect(user.page.get_by_role("heading", name="Proposal")).to_be_visible()
    expect(user.page.get_by_role("button", name="Revise Plan")).to_be_visible()
    expect(report_page.execute_button).to_be_visible()
    actions = report_page.proposal_actions
    expect(actions).to_have_count(1)
    expect(actions.nth(0).locator("[data-role='skip-action']")).to_be_visible()
    proposal_json = report_page.expand_json("Proposal JSON")
    expect(proposal_json).to_contain_text('"type": "create_page"')


# @features ai-report
# @dimensions detail organize revision feedback async pending deferred-refresh live-submit
def test_organize_report_detail_refreshes_when_submitted_revision_completes(
    get_user,
):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    report, _category_name, _page_name = _ready_report(user)

    report_page = user.go(Report.for_entity(user, report))
    expect(
        user.page.get_by_text("Create a category and page.", exact=True)
    ).to_be_visible()

    user.page.locator("#report-feedback").fill("Use a review step instead.")
    with user.page.expect_response(f"**/tools/reports/{report.urlsafe_key}/revise"):
        user.page.get_by_role("button", name="Revise Plan").click()

    expect(user.locate(Report.VIEW)).to_have_attribute("data-pending", "true")
    operation = user.locate(Report.VIEW).get_attribute("data-operation")
    assert operation

    report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    job = Entities.fetch_one(operation, request=Fetch.direct())
    assert report.deferred_job["key"] == operation
    assert job is not None
    report.properties.process.set_proposal(
        {
            "summary": "Use the revised plan instead.",
            "confidence": 1,
            "actions": [
                {
                    "id": "review-revision",
                    "type": "needs_review",
                    "display_label": "Review revised plan",
                    "data": {},
                }
            ],
        }
    )
    report.deferred_job = None
    job.status = "succeeded"
    job.dispatch_state = "complete"
    job.status_revision = int(job.status_revision or 0) + 1
    job.progress = {"phase": "complete"}
    Entities.save(report, job, owner)

    expect(
        user.page.get_by_text("Use the revised plan instead.", exact=True)
    ).to_be_visible(timeout=10000)
    report_page.initialize_view()
    expect(user.locate(Report.VIEW)).to_have_attribute("data-pending", "false")
    expect(
        user.page.get_by_text("Create a category and page.", exact=True)
    ).not_to_be_attached()


# @features ai-report
# @dimensions detail skip-action dependencies result-json
def test_report_detail_skips_action_dependencies(get_user):
    user = get_user(Users.OWNER)
    report = _dependency_report(user)

    report_page = user.go(Report.for_entity(user, report))
    actions = report_page.proposal_actions
    expect(actions).to_have_count(2)
    expect(actions.nth(0)).not_to_contain_text("create_category")
    expect(actions.nth(0)).not_to_contain_text("create_page")
    first_toggle = actions.nth(0).locator("[data-role='skip-action']")
    expect(first_toggle).to_have_attribute("data-kind", "delete")
    expect(first_toggle).to_have_attribute("class", re.compile("action-icon-button"))
    expect(first_toggle).to_have_attribute("class", re.compile("opacity-100"))

    with user.page.expect_response("**/tools/reports/*/actions/2/skip"):
        first_toggle.click()

    expect(actions.nth(0)).to_have_attribute("data-skipped", "true")
    expect(actions.nth(1)).to_have_attribute("data-skipped", "false")
    expect(actions.nth(0).locator("[data-role='skipped-label']")).to_have_attribute(
        "data-visible", "true"
    )
    expect(actions.nth(0).locator("[data-role='skip-action']")).to_have_attribute(
        "title", "Restore action"
    )
    expect(first_toggle).to_have_attribute("data-kind", "reset")

    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    assert [action.get("skip") for action in saved_report.proposal["actions"]] == [
        True,
        True,
        None,
    ]

    with user.page.expect_response("**/tools/reports/*/actions/2/skip"):
        actions.nth(0).locator("[data-role='skip-action']").click()

    expect(actions.nth(0)).to_have_attribute("data-skipped", "false")
    expect(actions.nth(0).locator("[data-role='skipped-label']")).to_have_attribute(
        "data-visible", "false"
    )
    expect(actions.nth(0).locator("[data-role='skip-action']")).to_have_attribute(
        "title", "Skip action"
    )
    expect(first_toggle).to_have_attribute("data-kind", "delete")

    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    assert [action.get("skip") for action in saved_report.proposal["actions"]] == [
        None,
        None,
        None,
    ]


# @features ai-report
# @dimensions detail schema-update skip-action deterministic-run batch-field-patch
def test_report_detail_skips_schema_section_and_runs_submission_updates(get_user):
    user = get_user(Users.OWNER)
    report, form, page = _schema_section_report(user)

    report_page = user.go(Report.for_entity(user, report))
    expect(user.page.get_by_role("heading", name="Schema Updates")).to_be_visible()
    actions = report_page.proposal_actions
    expect(actions).to_have_count(2)
    schema_action = actions.nth(0)
    update_action = actions.nth(1)
    expect(schema_action).to_have_attribute("data-skip-dependencies", "false")
    expect(update_action).to_contain_text("Mark invoice note paid")

    with user.page.expect_response("**/tools/reports/*/actions/1/skip"):
        schema_action.locator("[data-role='skip-action']").click()

    expect(schema_action).to_have_attribute("data-skipped", "true")
    expect(update_action).to_have_attribute("data-skipped", "false")
    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    assert [action.get("skip") for action in saved_report.proposal["actions"]] == [
        True,
        None,
    ]

    report_page.execute()

    expect(user.page.get_by_text("Work done.")).to_be_visible()
    expect(user.page.get_by_text("Updated submissions")).to_be_visible()
    expect(user.page.get_by_text("Updates: 1 applied")).to_be_visible()

    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    saved_page = Entities.fetch_one(page.urlsafe_key, request=Fetch.direct())
    saved_form = Entities.fetch_one(form.urlsafe_key, request=Fetch.direct())
    assert [action["status"] for action in saved_report.result["actions"]] == [
        "skipped",
        "complete",
    ]
    assert saved_page.submission["input-note"] == "paid"
    status_field = next(
        field for field in saved_form.schema if field["id"] == "select-status"
    )
    assert {"value": "paid", "label": "Paid"} not in status_field["options"]
