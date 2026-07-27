"""Focused contracts for the Ask report pipeline."""

import copy
import json

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import ask, organize
from testing.utility.test_entities import TestEntities


def _with_validator(generate):
    def wrapped(prompt, *, validator=None):
        result = generate(prompt)
        return validator(result) if validator else result

    return wrapped


def _user(hash_value="ask-owner"):
    return TestEntities.get(
        "USER",
        {
            "name": "Ask Owner",
            "hash": hash_value,
            "owner": True,
            "page": {"name": "Ask Owner Page", "hash": f"{hash_value}-page"},
        },
    )


def _report(user, **updates):
    data = {
        "name": "Ask report",
        "hash": "ask-report",
        "parent": user,
        "user": user,
        "tool": "ask",
        "instructions": "Has Leo been vaccinated for pertussis?",
        "input_files": [],
    }
    data.update(updates)
    return TestEntities.get("REPORT", data)


def _context(prompt, label):
    block = next(
        (item for item in prompt.context_blocks if item["label"] == label),
        None,
    )
    assert block, f"Missing prompt context: {label}"
    return block["value"]


def _json_context(prompt, label):
    value = _context(prompt, label).strip()
    if value.startswith("```") and value.endswith("```"):
        value = value.split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(value)


# @features ai-report
# @dimensions ask prompt search tool-context actions
@pytest.mark.unit
def test_ask_prompt_prioritizes_answers_and_exposes_read_tools():
    user = _user()
    prompt = ask.ask_prompt(_report(user), user)

    assert prompt.search is True
    assert prompt.max_tool_iterations == ask.ASK_MAX_TOOL_ITERATIONS
    assert {
        "search_entities",
        "get_entity",
        "get_file",
        "get_task_history",
        "get_filter_schema",
        "query_workspace_filter",
    }.issubset(prompt.tools)
    assert "attach_file_to_page" not in prompt.allowed_actions
    assert "attach_file_to_task" not in prompt.allowed_actions
    assert _context(prompt, "User Question") == (
        "```\nHas Leo been vaccinated for pertussis?\n```"
    )
    assert prompt.response_schema["required"] == [
        "summary",
        "confidence",
        "actions",
    ]
    assert prompt.response_schema["properties"]["answer_html"] == {
        "type": "string"
    }
    permissions = _json_context(prompt, "Report Action Permissions")
    assert permissions["capabilities"]["can_attach_files_to_pages"] is False
    assert permissions["capabilities"]["can_attach_files_to_tasks"] is False
    assert prompt.audit()["duplicate_headings"] == []
    assert prompt.files == []
    assert "Never\n  display them in `summary` or `answer_html`" in prompt.build()
    assert "never as guaranteed future changes" in prompt.build()


# @features ai-report
# @dimensions ask revision feedback proposal context
@pytest.mark.unit
def test_revise_ask_prompt_preserves_question_and_adds_review_context():
    user = _user("ask-revision-owner")
    report = _report(
        user,
        hash="ask-revision-report",
        instructions="What records mention Dance-Punk?",
        proposal={
            "summary": "The Dance-Punk task exists.",
            "confidence": 0.9,
            "answer_html": "<p>The Dance-Punk task exists.</p>",
            "actions": [],
        },
    )

    prompt = ask.revise_ask_prompt(report, user, "Make the answer shorter.")

    assert _context(prompt, "User Feedback") == (
        "```\nMake the answer shorter.\n```"
    )
    assert _json_context(prompt, "Current Response Json") == report.proposal
    assert _context(prompt, "User Question") == (
        "```\nWhat records mention Dance-Punk?\n```"
    )
    assert prompt.audit()["duplicate_headings"] == []


# @features ai-report
# @dimensions ask validation usable-answer
@pytest.mark.unit
@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"summary": ""}, "non-empty summary"),
        ({"confidence": 1.5}, "number from 0 to 1"),
        ({"answer_html": ["not html"]}, "must be a string"),
    ],
    ids=("summary", "confidence", "answer-html"),
)
def test_validate_ask_response_requires_a_usable_answer(updates, message):
    response = {
        "summary": "A grounded answer.",
        "confidence": 0.8,
        "actions": [],
        **updates,
    }

    with pytest.raises(exceptions.AIException, match=message):
        ask.validate_ask_response(response)


# @features ai-report
# @dimensions ask generate validate repair usable-answer
@pytest.mark.unit
def test_generate_ask_report_repairs_unusable_answers(monkeypatch):
    user = _user("ask-repair-owner")
    prompt = ask.ask_prompt(_report(user, hash="ask-repair-report"), user)
    responses = [
        {"summary": "", "confidence": 0.6, "actions": []},
        {
            "summary": "Leo's record mentions pertussis.",
            "confidence": 0.8,
            "actions": [],
        },
    ]
    calls = []

    def generate(candidate_prompt):
        calls.append(candidate_prompt)
        return responses.pop(0)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(generate),
    )

    response = ask.generate_ask_report(prompt)

    assert response["summary"] == "Leo's record mentions pertussis."
    assert len(calls) == 2
    assert _context(calls[1], "User Question") == (
        "```\nHas Leo been vaccinated for pertussis?\n```"
    )
    assert _context(calls[1], "Validation Error").strip()


# @features ai-report
# @dimensions ask generate validate repair needs-review references per-action-fallback fallback
@pytest.mark.unit
def test_generate_ask_report_reviews_invalid_actions_after_failed_repair(
    monkeypatch,
):
    user = _user("ask-action-fallback-owner")
    prompt = ask.revise_ask_prompt(
        _report(user, hash="ask-action-fallback-report"),
        user,
        "The Eyes task should be on Lucy's Eyes page.",
    )
    invalid = {
        "summary": "The page and task should be reorganized.",
        "answer_html": "<p>The task belongs on Lucy's Eyes page.</p>",
        "confidence": 0.9,
        "actions": [
            {
                "id": "add_site_to_medical",
                "type": "add_category",
                "display_label": "Add Site for Sore Eyes to Medical",
                "data": {
                    "page": "site-for-sore-eyes-page",
                    "category_name": "Medical",
                },
            },
            {
                "id": "move_specialist_consultation",
                "type": "move_task",
                "display_label": "Move Specialist Consultation",
                "data": {
                    "task_name": "Specialist Consultation",
                    "page": "lucy-eyes-page",
                },
            },
        ],
    }
    calls = []
    captured = []

    def generate(candidate_prompt):
        calls.append(candidate_prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(generate),
    )
    monkeypatch.setattr(
        organize.exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    response = ask.generate_ask_report(prompt)

    assert response["summary"] == (
        "Some suggested workspace changes need review before they can be applied."
    )
    assert response["answer_html"].endswith(invalid["answer_html"])
    assert "Action review required" in response["answer_html"]
    assert "suggestions only" in response["answer_html"]
    assert [action["type"] for action in response["actions"]] == [
        "needs_review",
        "needs_review",
    ]
    assert response["actions"][0]["id"] == "add_site_to_medical"
    assert response["actions"][0]["data"]["questions"] == [
        "Which existing or proposed category should this action use?"
    ]
    assert "suggested change" in response["actions"][0]["data"]["note"]
    assert response["actions"][1]["id"] == "move_specialist_consultation"
    assert response["actions"][1]["data"]["questions"] == [
        "Which existing or proposed task should this action use?"
    ]
    assert "workspace reference was unclear" in response["issues"][-1]
    assert len(calls) == 2
    assert "Keep internal entity hash tokens" in calls[1].build()
    assert captured == []


# @features ai-report
# @dimensions ask generate validate repair per-action-fallback malformed-data canonical-target
@pytest.mark.unit
def test_generate_ask_report_preserves_valid_actions_after_malformed_repair(
    monkeypatch,
):
    user = _user("ask-shape-fallback-owner")
    prompt = ask.revise_ask_prompt(
        _report(user, hash="ask-shape-fallback-report"),
        user,
        "Rename Orthodontics to Teeth and consolidate its tasks.",
    )
    invalid = {
        "summary": "The dental records can be consolidated.",
        "answer_html": "<p>Consolidate the dental records under Teeth.</p>",
        "confidence": 0.9,
        "actions": [
            {
                "id": "rename_page",
                "type": "update_submission_fields",
                "display_label": "Rename Orthodontics page to Teeth",
                "data": {"updates": [{}]},
            },
            {
                "id": "move_invisalign",
                "type": "move_task",
                "display_label": "Move Invisalign task to Teeth",
                "data": {
                    "task": "invisalign-task",
                    "to_page": "orthodontics-page",
                },
            },
            {
                "id": "delete_redundant_page",
                "type": "delete_page",
                "display_label": "Delete redundant orthodontic page",
                "data": {"page": "redundant-page"},
            },
        ],
    }
    calls = []

    def generate(candidate_prompt):
        calls.append(candidate_prompt)
        return copy.deepcopy(invalid)

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(generate),
    )
    monkeypatch.setattr(organize.exceptions, "capture", lambda *args, **kwargs: None)

    response = ask.generate_ask_report(prompt)

    assert [action["type"] for action in response["actions"]] == [
        "needs_review",
        "move_task",
        "delete_page",
    ]
    assert response["actions"][0]["id"] == "rename_page"
    assert response["actions"][1]["data"]["to_page"] == (
        "orthodontics-page"
    )
    assert "action data was incomplete" in response["issues"][-1]
    assert "Action review required" in response["answer_html"]
    assert len(calls) == 2


# @features ai-report
# @dimensions ask pipeline create revision status
@pytest.mark.unit
def test_complete_ask_report_owns_prompt_generation_and_report_state():
    user = _user("ask-pipeline-owner")
    report = _report(user, hash="ask-pipeline-report", result={"old": True})
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return {
            "summary": "No follow-up work is needed.",
            "confidence": 0.9,
            "actions": [],
        }

    response = ask.complete_ask_report(report, user, generate=answer)

    assert response is report.proposal
    assert report.status == "complete"
    assert report.result is None
    assert _context(prompts[0], "User Question").strip()

    def revise(prompt):
        prompts.append(prompt)
        return {
            "summary": "A human should confirm the ambiguous match.",
            "confidence": 0.5,
            "actions": [
                {
                    "id": "review",
                    "type": "needs_review",
                    "data": {"note": "Confirm the matching record."},
                }
            ],
        }

    ask.complete_ask_report(
        report,
        user,
        feedback="Call out the ambiguity.",
        generate=revise,
    )

    assert report.status == "ready"
    assert _context(prompts[1], "User Feedback") == (
        "```\nCall out the ambiguity.\n```"
    )
    assert _json_context(prompts[1], "Current Response Json")["actions"] == []


# @features ai-report
# @dimensions ask title-truncation
@pytest.mark.unit
def test_ask_report_name_is_compact_and_marks_truncation():
    question = (
        "Can you create a page in Johanna for family records and move all the "
        "family record files there so I can review the remaining duplicate pages?"
    )

    name = ask.ask_report_name(question)

    assert name.startswith("Ask: Can you create a page in Johanna")
    assert name.endswith("...")
    assert len(name) == len("Ask: ") + 80 + 3
    assert ask.ask_report_name("Short question?") == "Ask: Short question?"
