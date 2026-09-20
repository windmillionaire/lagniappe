"""Unified report discovery, output, upload intent, and format boundaries."""

from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import AI
from lagniappe.core.tools.ai import planner
from lagniappe.core.tools.ai.function_definitions.get_guidelines import (
    execute_get_guidelines,
)
from testing.utility.ai_report_fakes import _test_user
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


def _report(user, **values):
    return TestEntities.get(
        "REPORT",
        {
            "name": "AI report",
            "hash": "report123456",
            "parent": user,
            "user": user,
            "instructions": "Answer and create a task",
            "status": "pending",
            **values,
        },
    )


# @matrix ai-report : prompt permissions tools
def test_report_prompt_uses_shared_tools_and_selected_schemas(monkeypatch):
    user = _test_user("planner-owner")
    monkeypatch.setattr(type(user), "access", lambda self, access: True)
    prompt = planner.report_prompt(_report(user), user)
    assert prompt.tools == list(planner.REPORT_READ_TOOLS)
    assert {"get_help", "get_guidelines", "get_task_history", "query_workspace_filter"} <= set(prompt.tools)
    assert len(prompt.tools) == len(set(prompt.tools))
    assert prompt.search
    assert {"create_page", "create_task", "move_file", "update_page"} <= set(
        prompt.allowed_actions
    )
    assert len(json.dumps(prompt.response_schema)) < 1500
    assert "anyOf" not in json.dumps(prompt.response_schema)
    schema = execute_get_guidelines(
        {"task": "report_actions", "actions": ["create_task", "move_file"]}, user
    )
    assert {
        entry["properties"]["type"]["enum"][0]
        for entry in schema["action_schema"]["anyOf"]
    } == {"create_task", "move_file"}
    assert "error" in execute_get_guidelines({"task": "report_actions"}, user)
    assert "error" in execute_get_guidelines(
        {"task": "report_actions", "actions": []}, user
    )
    monkeypatch.setattr(type(user), "access", lambda self, access: access == AI.ASK)
    answer_prompt = planner.report_prompt(_report(user), user)
    assert answer_prompt.allowed_actions == ()
    assert '"allowed_actions": []' in answer_prompt.build()


# @matrix ai-report : permissions
@pytest.mark.parametrize("feedback", [None, "Put this on my personal Page instead."])
def test_native_and_external_plans_share_personal_page_guidance(monkeypatch, feedback):
    from lagniappe.core.tools.ai import external_api

    user = _test_user("personal-context")
    monkeypatch.setattr(type(user), "access", lambda self, access: True)
    report = _report(user, format_version=2)
    prompt = planner.report_prompt(report, user, feedback=feedback).build()
    contract = external_api.plan_contract(
        report, user, submit_url="https://example.test/submit"
    )
    personal_rule = next(
        rule for rule in contract["workflow_rules"]
        if rule.startswith("personal_page is ")
    )
    assert "guaranteed editable Page" in personal_rule
    assert "does not appear in workspace search" in personal_rule
    assert personal_rule in prompt
    assert contract["personal_page"]["hash"] == "hash:personal-context-page"
    assert contract["personal_page"]["hash"] in prompt
    assert contract["personal_page"]["can_edit"] is True
    if feedback:
        assert feedback in prompt


# @matrix ai-report : validation file-placement
def test_file_usage_requires_exact_coverage_and_files_only_filing():
    usage = [{"file": "hash:receipt12345", "usage": "evidence"}]
    validated = planner.validate_file_usage(usage, ["hash:receipt12345"])
    assert validated == usage
    assert validated is not usage
    for invalid in (
        None,
        [],
        usage * 2,
        [{"file": "unknown", "usage": "evidence"}],
        [{"file": "hash:receipt12345", "usage": "archive"}],
    ):
        with pytest.raises(exceptions.AIException):
            planner.validate_file_usage(invalid, ["hash:receipt12345"])
    with pytest.raises(exceptions.AIException, match="must be organized"):
        planner.validate_file_usage(
            usage, ["hash:receipt12345"], require_organization=True
        )
    usage[0]["usage"] = "organize"
    assert validated == [{"file": "hash:receipt12345", "usage": "evidence"}]
    with pytest.raises(exceptions.AIException, match="Answer-only"):
        planner.validate_file_usage(usage, ["hash:receipt12345"], read_only=True)


# @source lagniappe/core/tools/ai/references.py::render_ai_markdown
# @pair markdown:html-sanitization
# @pair ai-report:answer-only
# @matrix ai-report : generate validation file-placement
def test_generate_report_validates_answers_actions_and_file_usage(monkeypatch):
    prompt = SimpleNamespace(
        allowed_actions=(),
        report_file_refs=(),
        require_organization=False,
        user=_test_user("answers-owner"),
    )
    raw = {
        "summary": "The answer",
        "answer_markdown": "**Answer** <script>bad()</script>",
        "confidence": 1,
        "issues": [],
        "actions": [],
        "file_usage": [],
    }

    def generate(_prompt, *, validator, validation_retries):
        assert validation_retries == 2
        return validator(deepcopy(raw))

    monkeypatch.setattr(planner.ai_model, "generate_content", generate)
    result = planner.generate_report(prompt)
    assert result["file_usage"] == []
    assert result["proposal"]["actions"] == []
    assert "<strong>Answer</strong>" in result["proposal"]["answer_html"]
    assert "<script>" not in result["proposal"]["answer_html"]
    raw["actions"] = [
        {"type": "create_task", "data": {"name": "Do it", "page": "page"}}
    ]
    with pytest.raises(exceptions.AIException, match="not allowed"):
        planner.generate_report(prompt)
    raw["actions"] = []
    raw["confidence"] = True
    with pytest.raises(exceptions.AIException, match="confidence"):
        planner.generate_report(prompt)


# @matrix ai-report : validation status
def test_report_availability_rejects_old_and_malformed_records():
    user = _test_user("availability-owner")
    report = _report(user)
    report.format_version = 2
    assert report.available
    assert report.output_kind is None
    report.properties.process.set_proposal(
        {"summary": "Answer", "confidence": 1, "actions": []}
    )
    assert report.output_kind == "answer"
    assert report.status == "complete"
    report.format_version = 1
    assert not report.available
    report.format_version = None
    assert not report.available
    assert report.note == "this plan is no longer available"
    report.format_version = 99
    assert not report.available
    report.format_version = 2
    report.proposal = {"summary": "Malformed", "actions": [None]}
    assert not report.available
    assert report.output_kind is None


# @source lagniappe/core/properties/user_restrictions.py::Restrictions.ai_action_capabilities
# @source lagniappe/core/tools/ai/reporting/contracts/permissions.py::allowed_report_actions
# @matrix ai-report : action-capabilities permissions
# @pair permissions:own-page
def test_shared_actions_respect_permissions_and_allow_personal_page_tasks():
    from testing.utility.ai_report_fakes import _permissioned_user
    from testing.utility.mock_restrictions import MockRestrictions
    from lagniappe.core.tools.ai.reporting.contracts.permissions import (
        allowed_report_actions,
    )

    user = _permissioned_user("personal-page-only", {})
    with MockRestrictions().patch_cache():
        capabilities = user.properties.restrictions.ai_action_capabilities
        actions = set(allowed_report_actions(user))
    assert capabilities["can_create_pages"] is False
    assert capabilities["can_create_forms"] is False
    assert capabilities["can_attach_files_to_pages"] is False
    assert {"create_task", "complete_task", "update_task"} <= actions
    assert (
        not {"create_page", "create_form", "create_category", "create_project"}
        & actions
    )


# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::report_proposal_response_schema
# @matrix ai-report : allowed-actions provider-validation schema structured-output
def test_selected_response_schema_keeps_complete_action_values():
    from google.genai import types as genai_types
    from lagniappe.core.tools.ai.reporting.contracts.schema import (
        report_proposal_response_schema,
    )

    schema = report_proposal_response_schema(
        ("create_task", "update_task"), require_issues=True
    )
    variants = schema["properties"]["actions"]["items"]["anyOf"]
    actions = {
        v["properties"]["type"]["enum"][0]: v["properties"]["data"] for v in variants
    }
    assert set(actions) == {"create_task", "update_task"}
    assert "submission" in actions["create_task"]["properties"]
    assert "submission" in actions["update_task"]["properties"]["changes"]["properties"]
    assert all(v["additionalProperties"] is False for v in actions.values())
    assert "answer_markdown" in schema["properties"]
    assert "issues" in schema["required"]
    genai_types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema
    )
    with pytest.raises(ValueError, match="Missing report response schema"):
        report_proposal_response_schema(("invented_action",))
