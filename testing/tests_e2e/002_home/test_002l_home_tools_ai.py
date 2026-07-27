"""Live-AI Organize completion stories backed by the synthetic eval corpus."""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai.core import ai_model
from lagniappe.core.tools.ai.organize import complete_organize_submissions
from testing.definitions import Users
from testing.resources import Report
from testing.utility.organize_submission_eval import (
    load_cases,
    usability_failures,
)


pytestmark = [pytest.mark.e2e, pytest.mark.ai]
CASES = load_cases()


def _owner(user):
    return Entities.USER.load(user.email)


def _case_slug(case):
    return f"test-organize-{case['name']}-{uuid4().hex[:8]}"


def _create_form_entities(case, slug):
    forms = {}
    for definition in case["context"]["forms"]:
        form = Entities.FORM.create(
            {
                "name": f"{slug}-{definition['name']}",
                "form-type": definition["type"],
                "schema": definition["schema"],
            }
        )
        forms[definition["form_ref"]] = form
    Entities.save(*forms.values())
    return forms


def _create_evidence_files(case):
    files = {}
    for evidence in case["context"]["evidence_files"]:
        filename = evidence.get("filename") or evidence["file_ref"]
        file = Entities.FILE.create(
            data={
                "name": filename,
                "summary": evidence.get("summary"),
            }
        )
        file.filename = filename
        file.mimetype = evidence.get("mimetype") or "text/plain"
        files[evidence["file_ref"]] = file
    Entities.save(*files.values())
    return files


def _record_structures(case, slug, forms):
    categories = {}
    task_pages = {}
    for record in case["context"]["records"]:
        action_id = record["action_id"]
        form = forms[record["form_ref"]]
        if record["type"] == "page":
            category = Entities.CATEGORY.create(
                {
                    "name": record.get("category_name") or f"{slug}-{action_id}",
                    "form": form,
                }
            )
            categories[action_id] = category
            continue

        page = Entities.PAGE.create(
            {
                "name": record.get("page_name") or f"{slug}-{action_id}-page",
                "model": Entities.CATEGORY.get_uncategorized_pages(),
            }
        )
        task_pages[action_id] = page
    Entities.save(*categories.values(), *task_pages.values())
    return categories, task_pages


def _structural_proposal(case, forms, files, categories, task_pages):
    actions = []
    for record in case["context"]["records"]:
        action_id = record["action_id"]
        form = forms[record["form_ref"]]
        data = {
            "name": record["name"],
            "form": form.urlsafe_key,
        }
        if record["type"] == "page":
            data["category"] = categories[action_id].urlsafe_key
            action_type = "create_page"
        else:
            data["page"] = task_pages[action_id].urlsafe_key
            action_type = "create_task"
            if record.get("completed_on"):
                data["completed_on"] = record["completed_on"]

        actions.append(
            {
                "id": action_id,
                "type": action_type,
                "display_label": record["name"],
                "data": data,
            }
        )
        for index, file_ref in enumerate(record.get("supporting_file_refs", []), 1):
            target_key = "page_action" if record["type"] == "page" else "task_action"
            attachment_type = (
                "attach_file_to_page"
                if record["type"] == "page"
                else "attach_file_to_task"
            )
            actions.append(
                {
                    "id": f"{action_id}-attachment-{index}",
                    "type": attachment_type,
                    "depends_on": [action_id],
                    "data": {
                        "file": files[file_ref].urlsafe_key,
                        target_key: action_id,
                    },
                }
            )

    return {
        "summary": case["context"]["proposal_summary"],
        "confidence": 1,
        "issues": [],
        "actions": actions,
    }


def _create_case_report(owner, case):
    slug = _case_slug(case)
    forms = _create_form_entities(case, slug)
    files = _create_evidence_files(case)
    categories, task_pages = _record_structures(case, slug, forms)
    proposal = _structural_proposal(
        case,
        forms,
        files,
        categories,
        task_pages,
    )
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": slug,
            "tool": "organize",
            "instructions": case["context"]["report_intent"],
            "input_files": list(files.values()),
            "status": "pending",
            "pending": True,
        }
    )
    Entities.save(report, owner)
    return report, proposal, files


def _proposal_completion_result(proposal):
    return {
        "submissions": [
            {
                "action_id": action["id"],
                "submission": (action.get("data") or {}).get("submission") or {},
            }
            for action in proposal["actions"]
            if action["type"] in {"create_page", "create_task"}
        ]
    }


def _result_actions(report):
    return {
        action["id"]: action
        for action in report.result["actions"]
        if action.get("id")
    }


def _persisted_completion_result(case, result_actions):
    submissions = []
    entities = {}
    for record in case["context"]["records"]:
        action_id = record["action_id"]
        entity_ref = result_actions[action_id]["entity"]["id"]
        entity = Entities.fetch_one(entity_ref, request=Fetch.direct())
        entities[action_id] = entity
        submissions.append(
            {
                "action_id": action_id,
                "submission": entity.submission,
            }
        )
    return {"submissions": submissions}, entities


def _assert_attachments(case, files, entities):
    for record in case["context"]["records"]:
        entity = entities[record["action_id"]]
        for file_ref in record.get("supporting_file_refs", []):
            file = Entities.fetch_one(
                files[file_ref].urlsafe_key, request=Fetch.direct()
            )
            relation = file.properties.pages if record["type"] == "page" else file.properties.tasks
            assert entity.key in relation.keys


# @features ai-report
# @dimensions submission-completion live-provider execute persistence attachments
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_organize_completion_corpus_executes_usable_submissions(
    get_user,
    request,
    case,
):
    user = get_user(Users.OWNER)
    owner = _owner(user)
    report, proposal, files = _create_case_report(owner, case)
    ai_report = request.node.ai_results

    def generate(prompt):
        result = ai_model.generate_content(prompt)
        ai_report.record("provider_completion_result", result)
        return result

    ai_model.initialize()
    completed = complete_organize_submissions(
        proposal,
        report,
        owner,
        generate=generate,
    )
    completion_result = _proposal_completion_result(completed)
    failures = usability_failures(case, completion_result)

    ai_report.record("corpus_case", case)
    ai_report.record("completed_proposal", completed)
    ai_report.record("pre_execution_usability_failures", failures)
    assert not failures, "\n".join(failures)

    report.properties.process.set_proposal(completed)
    Entities.save(report, owner)

    report_page = user.go(Report.for_entity(user, report))
    expect(report_page.execute_button).to_be_visible()
    report_page.execute(timeout=90000)

    expect(user.page.get_by_text("Work done.")).to_be_visible()
    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    assert saved_report.status == "complete"

    result_actions = _result_actions(saved_report)
    persisted_result, entities = _persisted_completion_result(case, result_actions)
    persisted_failures = usability_failures(case, persisted_result)
    ai_report.record("execution_result", saved_report.result)
    ai_report.record("persisted_submissions", persisted_result)
    ai_report.record("persisted_usability_failures", persisted_failures)

    assert not persisted_failures, "\n".join(persisted_failures)
    _assert_attachments(case, files, entities)
