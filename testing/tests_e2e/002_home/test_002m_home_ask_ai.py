"""Live-AI Ask stories grounded in seeded workspace evidence."""

from html import unescape
import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    DeferredJobStatus,
    Fetch,
    FetchReason,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai.core import ai_model
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from testing.definitions import SitePages, Users
from testing.elements import List
from testing.resources import Report
from testing.utility import expect_successful_response
from testing.utility.hosted_deferred_jobs import dispatch_hosted_deferred_job
from testing.utility.organize_submission_eval import load_cases


pytestmark = [pytest.mark.e2e, pytest.mark.ai]
ASK_JOB_ATTEMPT_LIMIT = 2
RECEIPT_CASE = next(case for case in load_cases() if case["name"] == "receipt-fields")
MEDICAL_CASE = next(
    case for case in load_cases() if case["name"] == "medical-role-separation"
)


def _owner(user):
    return Entities.USER.load(user.email)


def _slug(label):
    return f"test-ask-{label}-{uuid4().hex[:8]}"


def _start_ask_report(user, question):
    home = user.go(SitePages.HOME)
    user.locate(home.CREATE_TOOL_REPORT_TOGGLE).click()
    form = user.locate(home.CREATE_TOOL_REPORT_FORM)
    form.locator("[data-role='tool-switcher']").get_by_role(
        "button", name="Ask"
    ).click()
    form.locator("textarea[name='instructions']").fill(question)

    with expect_successful_response(
        user.page,
        method="POST",
        path="/tools/ask",
    ) as response_info:
        form.get_by_role("button", name="Start").click()

    payload = response_info.value.json()
    operation = payload["operation"]
    match = re.search(r'data-key="([^"]+)"', payload["html"])
    assert match, "Ask response did not include a report data-key"
    report_key = match.group(1)
    report_list = List(user.locate(home.TOOL_REPORT_LIST))
    assert report_list.is_loaded
    item = report_list.list.locator(f"li[data-key='{report_key}']")
    expect(item).to_be_visible()
    expect(item.locator("[data-role='report-stage']")).to_have_text(
        "Answer pending"
    )
    expect(item).to_have_attribute("data-operation", operation)

    report = Entities.fetch_one(report_key, request=Fetch.direct())
    job = Entities.fetch_one(operation, request=Fetch.direct())
    assert report.tool == "ask"
    assert report.instructions == question
    assert report.status == "pending"
    assert report.pending is True
    assert job.status == DeferredJobStatus.QUEUED.value
    assert job.inputs == {
        "report": {
            "kind": "report",
            "id": report.urlsafe_key,
        }
    }
    return item, report, job


def _run_ask_job(page, report, job, ai_results):
    """Run Ask with one bounded, production-classified provider retry."""
    attempt_records = []
    if CONFIG.hosted_e2e_runner:
        current_job, attempt_records = dispatch_hosted_deferred_job(
            page,
            job,
            attempt_limit=ASK_JOB_ATTEMPT_LIMIT,
        )
    else:
        from lagniappe.web import app as web_app

        ai_model.initialize()
        current_job = job
        for _ in range(ASK_JOB_ATTEMPT_LIMIT):
            run_at = (
                current_job.next_attempt_at
                if current_job.status == DeferredJobStatus.RETRY_WAIT.value
                else None
            )
            with web_app.test_request_context("/"):
                DeferredJobs.run(job.urlsafe_key, now=run_at)
            current_job = Entities.fetch_one(job.urlsafe_key, request=Fetch.direct())
            error = current_job.error or {}
            attempt_records.append(
                {
                    "attempt": current_job.attempt,
                    "status": current_job.status,
                    "error": {
                        key: error[key]
                        for key in ("type", "retryable", "attempt")
                        if error.get(key) is not None
                    },
                }
            )
            if current_job.status != DeferredJobStatus.RETRY_WAIT.value:
                break

    saved_job = current_job
    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    response = saved_report.proposal
    ai_results.record("validated_ask_response", response)
    ai_results.record("deferred_job_checkpoint", saved_job.checkpoint)
    ai_results.record("deferred_job_attempts", attempt_records)
    assert saved_job.status == DeferredJobStatus.SUCCEEDED.value, attempt_records
    assert saved_job.checkpoint == {
        "proposal": response,
        "status": saved_report.status,
    }
    assert saved_report.status in {"ready", "complete"}
    assert not saved_report.pending
    return response, saved_report


def _answer_text(response):
    text = f"{response.get('summary') or ''} {response.get('answer_html') or ''}"
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _answer_usability_failures(
    response,
    *,
    required_terms,
    forbidden_terms=(),
    require_no_actions=True,
):
    failures = []
    answer = _answer_text(response).casefold()
    if not answer:
        failures.append("answer is empty")
    for term in required_terms:
        if term.casefold() not in answer:
            failures.append(f"answer is missing required value: {term}")
    for term in forbidden_terms:
        if term.casefold() in answer:
            failures.append(f"answer contains unrelated value: {term}")
    if require_no_actions and response.get("actions"):
        failures.append(
            "answer proposed actions even though the question requested none"
        )
    return failures


def _receipt_workspace(owner, case, slug):
    form_definition = case["context"]["forms"][0]
    record = case["context"]["records"][0]
    evidence = case["context"]["evidence_files"][0]
    form = Entities.FORM.create(
        {
            "name": f"{slug}-{form_definition['name']}",
            "form-type": form_definition["type"],
            "schema": form_definition["schema"],
        }
    )
    category = Entities.CATEGORY.create(
        {
            "name": f"{slug}-{record['category_name']}",
            "form": form,
        }
    )
    page = Entities.PAGE.create(
        {
            "name": f"{slug}-{record['name']}",
            "model": category,
            "form": form,
            "submission": case["expected"][record["action_id"]],
        }
    )
    file = Entities.FILE.create(
        page=page,
        data={
            "name": f"{slug}-{evidence['filename']}",
            "summary": evidence["summary"],
        },
    )
    file.filename = evidence["filename"]
    file.mimetype = evidence["mimetype"]
    Entities.save(form, category, page, file)
    return page, file


def _medical_project(owner, case, slug):
    form_definition = case["context"]["forms"][0]
    record = case["context"]["records"][0]
    expected = case["expected"][record["action_id"]]
    form = Entities.FORM.create(
        {
            "name": f"{slug}-{form_definition['name']}",
            "form-type": form_definition["type"],
            "schema": form_definition["schema"],
        }
    )
    project = Entities.PROJECT.create(
        {
            "name": f"{slug}-Pediatric Visits",
            "description": "Structured visit records used by the Ask E2E.",
            "attributes": ["tasks"],
        }
    )
    model = Entities.MODEL_TASK.create(
        project,
        {"name": f"{slug}-{form_definition['name']}", "form": form},
    )
    match_name = f"{slug}-Maria Rivera Sports Physical"
    distractor_name = f"{slug}-Other Provider Sports Physical"
    matching = Entities.TASK.create(
        {
            "name": match_name,
            "page": owner.page,
            "model": model,
            "form": form,
            "submission": expected,
        }
    )
    distractor = Entities.TASK.create(
        {
            "name": distractor_name,
            "page": owner.page,
            "model": model,
            "form": form,
            "submission": {
                **expected,
                "input-provider": "Dr. Other Provider",
            },
        }
    )
    Entities.fetch(
        matching,
        distractor,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    Entities.save(form, project, model, matching, distractor)
    return project, matching, distractor


# @pairs ai-report:ask ai-report:live-provider ai-report:workspace-tools
# @pairs ai-report:usable-answer ai-report:async ai-report:persistence
# @pairs deferred-jobs:process-route deferred-jobs:versioned-envelope
# @pairs deferred-jobs:cloud-tasks deferred-jobs:oidc
# @pairs deferred-jobs:provider-delivery deferred-jobs:hosted-e2e
# @pairs polling:operation polling:owner polling:progress polling:timing
def test_ask_answers_from_attached_corpus_receipt(get_user, request):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    slug = _slug("receipt")
    page, file = _receipt_workspace(owner, RECEIPT_CASE, slug)
    question = (
        f"Use workspace tools to inspect the page named {page.name} and its "
        "attached receipt. What merchant, purchase date, and total does the "
        "receipt show? Return those exact values and no suggested actions."
    )
    item, report, job = _start_ask_report(user, question)

    response, report = _run_ask_job(
        user.page,
        report,
        job,
        request.node.ai_results,
    )
    failures = _answer_usability_failures(
        response,
        required_terms=("Acme Hardware", "2026-07-10", "42"),
    )
    request.node.ai_results.record("corpus_case", RECEIPT_CASE)
    request.node.ai_results.record(
        "source_file",
        {"name": file.name, "hash": file.hash, "summary": file.summary},
    )
    request.node.ai_results.record("ask_response", response)
    request.node.ai_results.record("usability_failures", failures)
    assert not failures, "\n".join(failures)
    assert report.status == "complete"
    expect(item.locator("[data-role='report-stage']")).to_have_text(
        "Answer ready",
        timeout=45_000,
    )

    report_page = user.go(Report.for_entity(user, report))
    expect(report_page.answer).to_be_visible()
    expect(report_page.answer).to_contain_text("Acme Hardware")
    expect(report_page.answer).to_contain_text("2026-07-10")
    expect(report_page.answer).to_contain_text(re.compile(r"\$?42(?:\.00)?"))
    expect(report_page.execute_button).not_to_be_visible()


# @pairs ai-report:ask ai-report:live-provider ai-report:workspace-tools
# @pairs ai-report:structured-filter ai-report:usable-answer ai-report:async
# @pair ai-report:persistence
# @pairs deferred-jobs:process-route deferred-jobs:versioned-envelope
# @pairs deferred-jobs:cloud-tasks deferred-jobs:oidc
# @pairs deferred-jobs:provider-delivery deferred-jobs:hosted-e2e
# @pairs polling:operation polling:owner polling:progress polling:timing
def test_ask_uses_structured_filter_for_form_submission_query(
    get_user,
    request,
):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    slug = _slug("filter")
    project, matching, distractor = _medical_project(owner, MEDICAL_CASE, slug)
    question = (
        f"In the project named {project.name}, use get_filter_schema and "
        "query_workspace_filter to find tasks whose Doctor Visit Provider is "
        "exactly Dr. Maria Rivera. Return the exact matching task names and no "
        "suggested actions."
    )
    item, report, job = _start_ask_report(user, question)

    response, report = _run_ask_job(
        user.page,
        report,
        job,
        request.node.ai_results,
    )
    failures = _answer_usability_failures(
        response,
        required_terms=(matching.name,),
        forbidden_terms=(distractor.name,),
    )
    request.node.ai_results.record("ask_response", response)
    request.node.ai_results.record("usability_failures", failures)
    assert not failures, "\n".join(failures)
    assert report.status == "complete"
    expect(item.locator("[data-role='report-stage']")).to_have_text(
        "Answer ready",
        timeout=45_000,
    )

    report_page = user.go(Report.for_entity(user, report))
    expect(report_page.answer).to_be_visible()
    expect(report_page.answer).to_contain_text(matching.name)
    expect(report_page.answer).not_to_contain_text(distractor.name)
    expect(report_page.execute_button).not_to_be_visible()
