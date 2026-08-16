"""Focused contracts for the Ask report pipeline."""

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
# @dimensions ask prompt search tool-context answer-only structured-output provider-validation
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
    assert prompt.allowed_actions == ()
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
    assert set(prompt.response_schema["properties"]) == {
        "summary",
        "answer_html",
        "confidence",
        "actions",
    }
    assert prompt.response_schema["properties"]["actions"] == {
        "type": "array",
        "items": {"type": "object"},
        "maxItems": 0,
    }
    assert "schedule" not in json.dumps(prompt.response_schema)
    assert not any(
        block["label"] == "Report Action Permissions"
        for block in prompt.context_blocks
    )
    assert prompt.audit()["duplicate_headings"] == []
    assert prompt.files == []
    assert "Never\n  display them in `summary` or `answer_html`" in prompt.build()
    assert "Create handles new work" in prompt.build()


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
# @dimensions ask answer-only action-discard
@pytest.mark.unit
def test_generate_ask_report_discards_workspace_actions(monkeypatch):
    user = _user("ask-answer-only-owner")
    prompt = ask.ask_prompt(_report(user, hash="ask-answer-only-report"), user)
    calls = []

    def generate(candidate_prompt):
        calls.append(candidate_prompt)
        return {
            "summary": "The records identify the next follow-up.",
            "answer_html": "<p>The records identify the next follow-up.</p>",
            "confidence": 0.9,
            "actions": [
                {
                    "type": "create_task",
                    "data": {"name": "Follow up"},
                }
            ],
        }

    monkeypatch.setattr(
        organize.ai_model,
        "generate_content",
        _with_validator(generate),
    )

    response = ask.generate_ask_report(prompt)

    assert response["summary"] == "The records identify the next follow-up."
    assert response["actions"] == []
    assert len(calls) == 1


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
