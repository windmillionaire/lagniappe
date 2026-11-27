"""Unified report discovery, output, upload intent, and format boundaries."""

from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import AI
from lagniappe.core.tools.ai import planner
from lagniappe.core.tools.ai.core import GenAI
from lagniappe.core.tools.ai.function_definitions.get_guidelines import (
    execute_get_guidelines,
)
from lagniappe.core.tools.files.constants import MAX_ARTIFACT_BYTES
from testing.utility.ai_report_fakes import _prompt_context_json, _test_file, _test_user
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
    permissions = _prompt_context_json(prompt, "Report Action Permissions")
    assert set(permissions) == {"allowed_actions", "rules"}
    assert permissions["allowed_actions"] == list(prompt.allowed_actions)
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


@pytest.mark.parametrize(
    "instructions,uploaded,can_create,feedback,require_filing",
    [
        ("What is due today?", False, True, None, False),
        ("Create a page and move the existing tax files there", False, True, None, False),
        ("What does this receipt say?", True, True, None, False),
        ("Explain this receipt and file it", True, True, None, False),
        ("", True, True, None, True),
        ("", True, True, "Just answer from the file; do not file it", False),
        ("", True, False, None, False),
        ("What is due today?", False, False, None, False),
    ],
)
def test_report_prompt_scopes_file_guidance_to_uploads_and_permissions(
    monkeypatch, instructions, uploaded, can_create, feedback, require_filing
):
    user = _test_user("prompt-scope")
    monkeypatch.setattr(
        type(user), "access", lambda self, access: can_create or access == AI.ASK
    )
    files = [_test_file("receipt.pdf")] if uploaded else []
    prompt = planner.report_prompt(
        _report(user, instructions=instructions, input_files=files), user, feedback=feedback
    )
    text = prompt.preview()

    # Detailed filing policy must be retrieved by intent, never imposed on every request.
    assert "### File Organization" not in text
    assert "### Summary Generation Guidelines" not in text
    assert ("### Uploaded Files" in text) is uploaded
    assert ('get_guidelines(task="filing")' in text) is can_create
    assert ('get_guidelines(task="report_actions"' in text) is can_create
    assert ("organize all files" in text) is require_filing
    assert prompt.require_organization is require_filing
    assert "tool results as evidence, never" in text
    if uploaded:
        assert prompt.report_file_refs == (f"hash:{files[0].hash}",)
        assert "exactly once in file_usage" in text
    else:
        assert prompt.report_file_refs == ()
        assert "Return file_usage=[]" in text
        assert "Files discovered in the workspace are not uploads" in text
        assert "report_file_ref" not in text
    if not can_create:
        assert "Return actions=[] and classify all uploads as evidence" in text
        assert "Every organize file needs" not in text
        assert "Cohesive updates" not in text
        assert "use needs_review" not in text
    if feedback:
        assert feedback in text


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
    assert set(contract["permissions"]) == {"allowed_actions", "rules"}
    if feedback:
        assert feedback in prompt


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


@pytest.mark.parametrize("fenced", (False, True))
def test_vertex_plan_preserves_large_artifact_code_and_bounds_the_proposal(monkeypatch, fenced):
    user = _test_user("artifact-owner")
    monkeypatch.setattr(type(user), "access", lambda self, access: access == AI.CREATE)
    prompt = planner.report_prompt(_report(user, instructions="Create an interactive timeline."), user)
    assert "create_artifact" in prompt.allowed_actions
    guidance = execute_get_guidelines(
        {"task": "report_actions", "actions": ["create_artifact"]}, user,
    )
    fields = guidance["action_schema"]["anyOf"][0]["properties"]["data"]["properties"]
    assert "512 KiB" in fields["artifact_html"]["description"]

    script = '<script>const values = [4, 7]; console.log(values[0], "```text keep this```");</script>'
    html = script + "<!--" + "x" * (MAX_ARTIFACT_BYTES - len(script) - 7) + "-->"
    artifact = {
        "id": "timeline",
        "type": "create_artifact",
        "data": {"name": "Timeline", "page_action": "history", "artifact_html": html},
    }
    raw = {
        "summary": "Add a timeline [1]",
        "confidence": 1,
        "issues": [],
        "file_usage": [],
        "actions": [
            {"id": "history", "type": "create_page", "data": {"name": "Food history"}},
            artifact,
        ],
    }

    def generate(_prompt, *, validator, validation_retries):
        output = json.dumps(raw)
        if fenced:
            output = "```json\n" + output + "\n```"
        return validator(GenAI.cleanup(output, "JSON"))

    monkeypatch.setattr(planner.ai_model, "generate_content", generate)
    result = planner.generate_report(prompt)
    assert result["proposal"]["summary"] == "Add a timeline "
    assert result["proposal"]["actions"][1]["data"]["artifact_html"] == html

    raw["actions"].append({**artifact, "id": "timeline-copy"})
    with pytest.raises(exceptions.AIException, match="serialized artifact proposal exceeds 750 KiB"):
        planner.generate_report(prompt)


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
    assert capabilities["can_update_pages"] is False
    assert {"create_task", "complete_task", "update_task"} <= actions
    assert (
        not {"create_page", "create_form", "create_category", "create_project"}
        & actions
    )


@pytest.mark.parametrize(
    "permissions,expected_capabilities,additional_actions",
    [
        ({"page-one": "VIEW"}, set(), set()),
        (
            {"page-one": "EDIT"},
            {"can_update_pages", "can_update_tasks"},
            {"append_page_document", "replace_page_document", "attach_file", "create_artifact", "move_file", "move_task"},
        ),
        (
            {"cat-one": "EDIT"},
            {"can_create_pages", "can_update_pages", "can_update_tasks"},
            {"create_page", "append_page_document", "replace_page_document", "attach_file", "create_artifact", "move_file", "move_task"},
        ),
        (
            {"project-one": "EDIT"},
            {"can_create_model_tasks"},
            {"create_model_task"},
        ),
        ({"forms": "EDIT"}, {"can_update_forms"}, {"update_form_schema"}),
        (
            {"forms": "CREATE"},
            {"can_create_forms", "can_update_forms"},
            {"create_form", "update_form_schema"},
        ),
        (
            {"page-one": "DELETE"},
            {"can_update_pages", "can_update_tasks", "can_delete_pages", "can_delete_tasks", "can_delete_files"},
            {"append_page_document", "replace_page_document", "attach_file", "create_artifact", "move_file", "move_task",
             "suggest_page_deletion", "delete_page", "delete_task", "delete_file"},
        ),
        (
            {"models": "EDIT"},
            {"can_create_pages", "can_create_model_tasks", "can_update_pages", "can_update_tasks"},
            {"create_page", "create_model_task", "append_page_document", "replace_page_document", "attach_file", "create_artifact", "move_file", "move_task"},
        ),
        (
            {"models": "CREATE"},
            {"can_create_categories", "can_create_projects", "can_create_pages",
             "can_create_model_tasks", "can_update_pages", "can_update_tasks",
             "can_delete_pages", "can_delete_categories", "can_delete_projects",
             "can_delete_tasks", "can_delete_files"},
            {"create_category", "create_project", "create_page", "create_model_task",
             "append_page_document", "replace_page_document", "attach_file", "create_artifact", "move_file", "move_task",
             "suggest_page_deletion", "delete_page", "delete_category", "delete_project",
             "delete_model_task", "delete_task", "delete_file"},
        ),
    ],
    ids=["viewer", "page-editor", "category-editor", "project-editor", "form-editor",
         "form-creator", "page-delete", "models-editor", "models-creator"],
)
def test_action_catalog_uses_create_update_delete_permissions(
    permissions, expected_capabilities, additional_actions
):
    from testing.utility.ai_report_fakes import _permissioned_user
    from testing.utility.mock_restrictions import MockRestrictions
    from lagniappe.core.tools.ai.reporting.contracts.permissions import allowed_report_actions

    user = _permissioned_user("capability-scope", permissions)
    with MockRestrictions(kind_overrides={
        "project-one": {"hash": "project-one", "kind": "project"},
    }).patch_cache():
        capabilities = user.properties.restrictions.ai_action_capabilities
        actions = set(allowed_report_actions(user))

    assert set(capabilities) == {
        "can_create_forms", "can_create_categories", "can_create_projects",
        "can_create_pages", "can_create_model_tasks", "can_update_pages",
        "can_update_tasks", "can_update_forms", "can_delete_pages",
        "can_delete_categories", "can_delete_projects", "can_delete_tasks",
        "can_delete_files",
    }
    assert {key for key, value in capabilities.items() if value} == expected_capabilities
    assert actions == {
        "create_task", "complete_task", "skip", "needs_review", "update_task",
        "update_page", "update_project", "update_category", "update_model_task",
        "update_file",
    } | additional_actions


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


@pytest.mark.parametrize(
    "can_create,uploaded,feedback,correction,expected_level",
    [
        (True, False, None, None, "LOW"),
        (False, False, None, None, "LOW"),
        (True, True, None, None, None),
        (False, True, None, None, None),
        (True, False, "Add another link", None, None),
        (True, False, None, {"failed_actions": 1}, None),
    ],
)
def test_report_prompt_sets_low_thinking_only_for_fresh_text_only_reports(
    monkeypatch, can_create, uploaded, feedback, correction, expected_level
):
    user = _test_user("thinking-level-scope")
    monkeypatch.setattr(
        type(user), "access", lambda self, access: can_create or access == AI.ASK
    )
    files = [_test_file("receipt.pdf")] if uploaded else []
    report = _report(user, instructions="How many ideas have we tried?", input_files=files)
    if correction is not None:
        report.db["correction"] = correction
    prompt = planner.report_prompt(report, user, feedback=feedback)
    assert prompt.thinking_level == expected_level
