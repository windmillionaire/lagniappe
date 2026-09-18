"""Live-AI Ask stories grounded in seeded workspace evidence."""

from html import escape, unescape
import json
import re
from uuid import uuid4

import pytest
from flask_login import login_user
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    DeferredJobStatus,
    Fetch,
    FetchReason,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai.core import ai_model
from lagniappe.core.tools.ai.references import normalize_hash_references
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.web import app as web_app
from testing.definitions import SitePages, Users
from testing.elements import List
from testing.resources import Report
from testing.utility.network import expect_successful_response
from testing.utility import hosted_deferred_jobs
from testing.utility.live_ai import (
    ProviderQuotaBlocked, inject_quota_fallback_checkpoint, quota_blocked_job, run_live_ai,
)
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
    form.locator("textarea[name='instructions']").fill(question)

    with expect_successful_response(
        user.page,
        method="POST",
        path="/tools/ai",
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
        "Proposal pending"
    )
    expect(item).to_have_attribute("data-operation", operation)

    report = Entities.fetch_one(report_key, request=Fetch.direct())
    job = Entities.fetch_one(operation, request=Fetch.direct())
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


def _deliver_ask_job(user, job):
    if CONFIG.hosted_e2e_runner:
        return hosted_deferred_jobs.dispatch_hosted_deferred_job(
            user.page, job, attempt_limit=ASK_JOB_ATTEMPT_LIMIT,
        )
    from concurrent.futures import ThreadPoolExecutor

    def worker(current):
        # Playwright owns an event loop on the test thread. The real synchronous
        # worker needs its own thread for the generation-owned provider loop.
        ai_model.initialize()
        records = []
        for _ in range(ASK_JOB_ATTEMPT_LIMIT):
            run_at = current.next_attempt_at if current.status == DeferredJobStatus.RETRY_WAIT.value else None
            with web_app.test_request_context("/"):
                DeferredJobs.run(current.urlsafe_key, now=run_at)
            current = Entities.fetch_one(current.urlsafe_key, request=Fetch.direct())
            records.append({"attempt": current.attempt, "status": current.status, "error": current.error})
            if current.status != DeferredJobStatus.RETRY_WAIT.value:
                break
        return current, records

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(worker, job).result()


def _retry_ask_report(user, report, failed_job):
    user.go(Report.for_entity(user, report))
    view = user.locate(Report.VIEW)
    expect(view).to_have_attribute("data-pending", "false")
    path = f"/tools/reports/{report.urlsafe_key}/retry-generation"
    with user.page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(path)) as response:
        view.get_by_role("button", name="Retry generation", exact=True).click()
    assert response.value.status == 302
    expect(user.locate(Report.VIEW)).to_have_attribute("data-pending", "true")
    saved = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    job = Entities.fetch_one(saved.deferred_job["key"], request=Fetch.direct())
    assert job.key != failed_job.key
    assert job.status == DeferredJobStatus.QUEUED.value
    home = user.go(SitePages.HOME)
    user.locate(home.TOOL_REPORT_LIST_TOGGLE).click()
    assert List(user.locate(home.TOOL_REPORT_LIST)).is_loaded
    return job


def _run_ask_job(user, report, job, ai_results, *, quota_fallback):
    """Use a real UI retry; persistent quota can verify a grounded answer instead."""
    current_job = job
    attempt_records = []

    def deliver():
        nonlocal current_job
        current_job, records = _deliver_ask_job(user, current_job)
        attempt_records.extend({**record, "operation": current_job.urlsafe_key} for record in records)
        ai_results.record("deferred_job_attempts", list(attempt_records))
        return current_job

    def attempt(number):
        nonlocal current_job
        if number > 1:
            current_job = _retry_ask_report(user, report, current_job)
        deliver()
        if quota_blocked_job(current_job):
            raise ProviderQuotaBlocked((current_job.error or {}).get("message", "AIQuotaError"))
        assert current_job.status == DeferredJobStatus.SUCCEEDED.value, attempt_records
        return current_job

    def fallback():
        nonlocal current_job
        # The callback must verify the actual workspace tools before supplying
        # the known answer. A wrong lookup still fails instead of being hidden.
        proposal = quota_fallback()
        failed_job = current_job
        current_job = _retry_ask_report(user, report, failed_job)
        checkpoint = inject_quota_fallback_checkpoint(current_job, proposal, failed_job=failed_job)
        ai_results.record("provider_quota_fallback", {"used": True, "checkpoint": checkpoint})
        deliver()
        assert current_job.status == DeferredJobStatus.SUCCEEDED.value, attempt_records
        return current_job

    saved_job = run_live_ai(attempt, results=ai_results, fallback=fallback)
    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    response = saved_report.proposal
    ai_results.record("validated_ask_response", response)
    ai_results.record("deferred_job_checkpoint", saved_job.checkpoint)
    assert saved_job.checkpoint == {
        "schema_version": 1,
        "stage": "ready_to_apply",
        "proposal": response,
        "file_usage": [],
        "status": saved_report.status,
    }
    assert not saved_report.file_usage
    assert saved_report.status in {"ready", "complete"}
    assert not saved_report.pending
    return response, saved_report


def _answer_text(response):
    text = f"{response.get('summary') or ''} {response.get('answer_html') or ''}"
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _quota_fallback_answer(answer):
    """Return a recorded provider substitute for quota-only E2E recovery."""
    return {
        "summary": answer,
        "confidence": 1,
        "answer_html": f"<p>{escape(answer)}</p>",
        "actions": [],
    }


def _receipt_fallback(owner, page, file, results):
    from lagniappe.core.tools.ai.function_definitions.get_page_details import execute_get_page_details

    details = execute_get_page_details(normalize_hash_references({"id": f"hash:{page.hash}", "exclude_tasks": True}), owner)
    assert "error" not in details, details
    evidence = next(item for item in details["files"] if item["hash"] == f"hash:{file.hash}")
    text = json.dumps(evidence)
    assert all(value in text for value in ("Acme Hardware", "2026-07-10", "42")), evidence
    results.record("independent_workspace_verification", evidence)
    return _quota_fallback_answer(
        "The attached receipt shows merchant Acme Hardware, purchase date 2026-07-10, and total $42.00."
    )


def _filter_fallback(owner, project, matching, distractor, results):
    from lagniappe.core.tools.ai.function_definitions.workspace_filter import (
        execute_get_filter_schema, execute_query_workspace_filter,
    )

    saved = Entities.fetch_one(matching.key, request=Fetch.nested(because=FetchReason.AI_FILTER_RESULT_SERIALIZATION))
    assert saved.submission["input-provider"] == "Dr. Maria Rivera", dict(saved.db)
    assert saved.properties.project.key == project.key, dict(saved.db)
    fixture_index = saved.to_filter_index(owner)
    results.record("filter_fixture", fixture_index)
    schema = execute_get_filter_schema(normalize_hash_references({"id": f"hash:{project.hash}"}), owner)
    assert "error" not in schema, schema
    fields = [field for field in schema["fields"] if field["field"] == "input-provider"]
    assert len(fields) == 1, schema
    field = fields[0]
    assert "eq" in field["comparators"]
    query = normalize_hash_references({
        "id": f"hash:{project.hash}",
        "conditions": [{"source_id": field["source"]["hash"], "field": field["field"],
                        "comparator": "eq", "values": ["Dr. Maria Rivera"]}],
    })
    queried = execute_query_workspace_filter(query, owner)
    assert "error" not in queried and not queried.get("incomplete"), queried
    assert queried["matched"] == 1 and not queried["truncated"], {"query": queried, "fixture": fixture_index}
    names = [item["task_name"] for item in queried["results"]]
    assert names == [matching.name] and distractor.name not in names, queried
    results.record("independent_workspace_verification", queried)
    return _quota_fallback_answer(f"The exact matching task is {names[0]}.")


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


# @matrix ai-report : ask async live-provider persistence usable-answer workspace-tools
# @matrix deferred-jobs : cloud-tasks hosted-e2e oidc process-route provider-delivery versioned-envelope
# @matrix polling : operation owner progress timing
@pytest.mark.parametrize("live_ai_job_quota", [False, True], indirect=True, ids=["live", "quota-fallback"])
def test_ask_answers_from_attached_corpus_receipt(get_user, request, live_ai_job_quota):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    slug = _slug("receipt")
    page, file = _receipt_workspace(owner, RECEIPT_CASE, slug)
    with web_app.test_request_context("/"):
        login_user(owner)
        verified_answer = _receipt_fallback(owner, page, file, request.node.ai_results)
    question = (
        f"Use workspace tools to inspect the page named {page.name} and its "
        "attached receipt. What merchant, purchase date, and total does the "
        "receipt show? Return those exact values and no suggested actions."
    )
    item, report, job = _start_ask_report(user, question)

    response, report = _run_ask_job(
        user,
        report,
        job,
        request.node.ai_results,
        quota_fallback=lambda: verified_answer,
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


# @matrix ai-report : ask async live-provider persistence structured-filter usable-answer workspace-tools
# @matrix deferred-jobs : cloud-tasks hosted-e2e oidc process-route provider-delivery versioned-envelope
# @matrix polling : operation owner progress timing
@pytest.mark.parametrize("live_ai_job_quota", [False, True], indirect=True, ids=["live", "quota-fallback"])
def test_ask_uses_structured_filter_for_form_submission_query(
    get_user, request, live_ai_job_quota,
):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    slug = _slug("filter")
    project, matching, distractor = _medical_project(owner, MEDICAL_CASE, slug)
    with web_app.test_request_context("/"):
        login_user(owner)
        verified_answer = _filter_fallback(owner, project, matching, distractor, request.node.ai_results)
    question = (
        f"In the project named {project.name}, use get_filter_schema and "
        "query_workspace_filter to find tasks whose Doctor Visit Provider is "
        "exactly Dr. Maria Rivera. Return the exact matching task names and no "
        "suggested actions."
    )
    item, report, job = _start_ask_report(user, question)

    response, report = _run_ask_job(
        user,
        report,
        job,
        request.node.ai_results,
        quota_fallback=lambda: verified_answer,
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
