"""Focused AI-report characterization coverage."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.genai import types as genai_types

from lagniappe.core import exceptions
from lagniappe.core.definitions import LARGE_ASSET_BYTES
from lagniappe.core.tools.ai import ask, create, organize, organize_retrieval, summarize
from lagniappe.core.tools.ai.reporting.completion import files as organize_completion
from testing.utility.ai_report_fakes import (
    _permissioned_user,
    _prompt_context,
    _prompt_context_json,
    _response_action_schemas,
    _test_file,
    _test_user,
)
from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities

# @matrix ai-report : files iteration-limit prompt tools
@pytest.mark.unit
def test_organize_prompt_includes_files_tools_instructions_and_high_limit(monkeypatch):
    monkeypatch.setattr(
        organize.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
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
    assert _prompt_context(prompt, "Current Date") == "```\n2026-08-31\n```"
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
    assert (
        "list_workspace_resources only when the prefetched candidates are absent"
        in (semantic_preview)
    )
    assert "Batch get_entity calls for plausible candidates only" in semantic_preview
    assert 'search_entities with kinds=["page"]' in semantic_preview
    assert "a wording difference does not justify a duplicate" in semantic_preview
    assert "Propose create_page only after steps 4 and 5" in semantic_preview
    assert "something specific was done or needs to be done" in semantic_preview
    assert "set completed: true" in semantic_preview
    assert "solely because the exact date is unknown" in semantic_preview
    assert "Future-dated work is not complete" in semantic_preview
    assert "If the matching page cannot be edited, use needs_review" in (
        semantic_preview
    )
    assert "no broad category-level catch-all" in semantic_preview
    assert "New page names are concise subject labels" in semantic_preview
    assert "Review/skip may supplement but never replace" in semantic_preview
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




# @matrix ai-report search : fallback kinds limits redis-search summary-terms
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




# @matrix ai-report : active-request quota search-opt-in summary-prepass
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




# @matrix ai-report : fallback large-file summary-prepass
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




# @matrix ai-report : issue persistence summary-prepass unreadable-pdf
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




# @matrix ai-report : context feedback proposal revision
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




# @matrix ai-report : actions create prompt search tools
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




# @matrix ai-report : context create feedback proposal revision
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




# @matrix ai-report : allowed-actions schema structured-output
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
    external_summary_actions = _response_action_schemas(
        SimpleNamespace(
            response_schema=organize.report_proposal_response_schema(
                ("summarize_file",),
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
    assert "content_markdown" in field_schema["properties"]
    assert "html" not in field_schema["properties"]
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
    assert "earlier action in this proposal" in update_schema["properties"][
        "page_action"
    ]["description"]
    assert "not a workspace hash" in update_schema["properties"]["task_action"][
        "description"
    ]
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
    assert "exact id of an earlier action" in add_category_data["properties"][
        "page_action"
    ]["description"].casefold()
    create_page_data = full_actions["create_page"]["properties"]["data"]
    submission_description = create_page_data["properties"]["submission"][
        "description"
    ]
    assert "creates a new submission" in submission_description
    assert "not a reference to an existing submission" in submission_description
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
    summary_data = external_summary_actions["summarize_file"]["properties"]["data"]
    assert set(summary_data["properties"]) == {
        "file",
        "summary",
        "retrieval_terms",
        "search",
    }
    assert summary_data["properties"]["retrieval_terms"] == {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 2,
        "maxItems": 2,
    }

    ask_schema = ask_prompt.response_schema
    assert "answer_markdown" in ask_schema["properties"]
    assert "answer_html" not in ask_schema["properties"]
    assert "issues" not in ask_schema["required"]
    assert ask_prompt.allowed_actions == ()
    assert ask_schema["properties"]["actions"] == {
        "type": "array",
        "items": {"type": "object"},
        "maxItems": 0,
    }

    create_page_data = create_actions["create_page"]["properties"]["data"]
    assert "document_markdown" in create_page_data["properties"]
    assert "document" not in create_page_data["properties"]

    assert "move_page" not in create_actions
    assert tuple(create_actions) == create_prompt.allowed_actions




# @matrix ai-report : provider-validation schema structured-output
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




# @matrix ai-report : action-capabilities permissions
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
        "can_attach_files_to_pages": True,
        "can_add_forms_to_pages": True,
        "can_attach_files_to_tasks": True,
        "can_add_page_categories": True,
        "can_update_form_schemas": False,
        "can_update_submissions": True,
        "can_delete_pages": False,
    }
    assert permissions["allowed_actions"] == list(organize_prompt.allowed_actions)


# @pairs ai-report:action-capabilities permissions:own-page
@pytest.mark.unit
def test_report_prompts_always_allow_tasks_on_the_personal_page():
    user = _permissioned_user("personal-page-only", {})
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Personal task report",
            "hash": "personal-task-report",
            "parent": user,
            "user": user,
            "instructions": "Add a task to my personal page.",
            "input_files": [],
        },
    )

    with MockRestrictions().patch_cache():
        prompt = create.create_prompt(report, user)

    assert prompt.allowed_actions == ("create_task", "needs_review")
    permissions = _prompt_context_json(prompt, "Report Action Permissions")
    assert "can_create_tasks" not in permissions["capabilities"]
    assert any(
        "editable target" in rule for rule in permissions["rules"]
    )
