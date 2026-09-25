"""Trusted external guidance and schedule contracts without provider drift."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

from google.genai import types as genai_types
import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai.external import contracts as external_contracts
from lagniappe.core.tools.ai.external import validation as external_validation
from lagniappe.core.tools.ai import functions
from lagniappe.core.tools.ai.function_definitions import get_guidelines, search
from lagniappe.core.tools.ai.guidelines import REPORT_TASK_SCHEDULING_GUIDELINES
from lagniappe.core.tools.ai.reporting.contracts import schema
from lagniappe.core.tools.ai.reporting.schedules import validate_task_schedule


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_schema_conversion_guidance_is_selected_by_trusted_invocation():
    actor = SimpleNamespace()
    onsite, _ = functions.execute_registered_tool(
        "get_guidelines", {"task": "schema_evolution", "external": True}, actor
    )
    external, _ = functions.execute_registered_tool(
        "get_guidelines",
        {"task": "schema_evolution", "external": False},
        actor,
        external=True,
    )
    assert onsite == external
    assert "include_values=true for scalar before/after evidence" in onsite["guidelines"]
    assert "data.conversions" in external["guidelines"]
    assert "unresolved_reason" in external["guidelines"]
    assert "conversion_instructions" not in external["guidelines"]
    assert "conversion happens after" not in external["guidelines"]
    for result in (onsite, external):
        assert "On-site proposals" not in result["guidelines"]
        assert "For external" not in result["guidelines"]
    native_schema = schema.report_proposal_response_schema(
        allowed_actions=["update_form_schema"]
    )
    public_schema = schema.external_report_proposal_response_schema(
        allowed_actions=["update_form_schema"]
    )
    assert '"conversions"' in json.dumps(native_schema)
    assert '"conversion_instructions"' not in json.dumps(native_schema)
    assert '"conversion_instructions"' not in json.dumps(public_schema)
    assert '"conversions"' in json.dumps(public_schema)


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
@pytest.mark.parametrize("external", [False, True])
def test_schema_guidance_filters_definitions_without_submission_rules(external):
    read = (
        get_guidelines.execute_external_get_guidelines
        if external else get_guidelines.execute_get_guidelines
    )
    actor = SimpleNamespace()
    args = {"field_types": ["textarea", "table", "input", "checkbox"]}
    for task in ("page_form", "task_form", "schema_evolution"):
        result = read({**args, "task": task}, actor)
        text = result["guidelines"]
        assert "#### `table` schema" in text
        assert "#### `input` schema" in text
        assert "#### `checkbox` schema" in text
        assert "#### `signature`" not in text
        assert "#### `location`" not in text
        assert "#### `link`" not in text
        assert "#### `html`" not in text
        assert "Submission Value Guidelines" not in text
        assert "Input element values are strings" not in text
        if task == "schema_evolution":
            assert "scope_fingerprint" in text
            assert "finite JSON numbers" in text
            assert "conversion_instructions" not in text
        else:
            assert "data.conversions" not in text
            assert "conversion_instructions" not in text
        full = read({"task": task}, actor)
        assert result["content_bytes"] < full["content_bytes"]
        if task == "page_form":
            for unsupported in ("todo", "signature", "html"):
                assert f"#### `{unsupported}` schema" not in full["guidelines"]
        elif task == "task_form":
            assert "#### `todo` schema" in full["guidelines"]

    for task in ("category", "project"):
        text = read({"task": task}, actor)["guidelines"]
        assert "Submission Value Guidelines" not in text
        assert "#### `input`" not in text
    text = read({"task": "form_autofill", "field_types": ["input"]}, actor)["guidelines"]
    assert "Number inputs use JSON" in text
    assert "numeric strings" in text
    assert "data.conversions" not in text


# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @matrix agent-api ai-report : external-schema proposal-contract structured-output
@pytest.mark.unit
def test_external_schema_patch_uses_standard_nullable_values():
    public = schema.external_report_proposal_response_schema(
        allowed_actions=["update_form_schema"]
    )
    assert '"nullable"' not in json.dumps(public)
    proposal = {
        "summary": "Clear optional field settings",
        "confidence": 1,
        "actions": [
            {
                "id": "schema",
                "type": "update_form_schema",
                "data": {
                    "form": "hash:form",
                    "operations": [
                        {
                            "op": "update_field",
                            "schema_id": "notes",
                            "patch": {"required": None, "placeholder": None},
                        }
                    ],
                },
            }
        ],
    }
    assert external_validation._schema_errors(proposal, public, public, "$.proposal") == []
    proposal["actions"][0]["data"]["operations"][0]["patch"] = {"title": None}
    assert external_validation._schema_errors(proposal, public, public, "$.proposal")


# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_organize_guidance_is_shared_across_provider_and_external_dispatch():
    actor = SimpleNamespace()
    provider_parts, media = functions.execute_function_calls(
        [
            SimpleNamespace(
                name="get_guidelines", args={"task": "filing", "external": True}
            )
        ],
        actor,
    )
    internal = json.loads(provider_parts[0].function_response.response["result"])
    external, external_media = functions.execute_registered_tool(
        "get_guidelines", {"task": "filing", "external": False}, actor, external=True
    )

    assert media == external_media == []
    assert internal == get_guidelines.execute_get_guidelines(
        {"task": "filing"}, actor
    )
    assert internal == external
    assert "same proposal" in internal["guidelines"]
    assert "uploaded or existing workspace files" in internal["guidelines"]
    assert "Only report uploads belong" in internal["guidelines"]
    assert "Every updates row" not in internal["guidelines"]
    assert "data.changes.submission" in internal["guidelines"]
    assert "Summary Generation Guidelines" not in internal["guidelines"]
    assert "No action contains submission-generation fields" not in internal["guidelines"]
    assert "server performs focused form completion afterward" not in internal["guidelines"]
    assert "/submit" not in internal["guidelines"]
    assert "submit_plan" not in internal["guidelines"]
    assert "exactly one summarize_file action per file" in external["guidelines"]
    assert "summarize_file" not in functions.DECLARATIONS
    for result in (internal, external):
        assert result["content_bytes"] == len(result["guidelines"].encode("utf-8"))
    inputs = functions.tool_catalog(names=["get_guidelines"], transport="rest")[0][
        "input_schema"
    ]
    assert set(inputs["properties"]) == {"task", "field_types", "actions"}

    for external_dispatch in (False, True):
        for action in ("update_task", "summarize_file"):
            guidance, _ = functions.execute_registered_tool(
                "get_guidelines", {"task": "report_actions", "actions": [action]},
                actor, external=external_dispatch,
            )
            assert "Return one complete executable proposal" in guidance["guidelines"]
            assert "File Organization" not in guidance["guidelines"]
            assert ("Summary Generation Guidelines" in guidance["guidelines"]) is (
                action == "summarize_file"
            )

    internal_form, _ = functions.execute_registered_tool(
        "get_guidelines", {"task": "form_autofill"}, actor
    )
    external_form, _ = functions.execute_registered_tool(
        "get_guidelines", {"task": "form_autofill"}, actor, external=True
    )
    assert "Preserve every non-empty value" in internal_form["guidelines"]
    assert "partial submission (if provided) unaltered" in internal_form["guidelines"]
    assert "Preserve every non-empty value" not in external_form["guidelines"]
    assert (
        "partial submission (if provided) unaltered" not in external_form["guidelines"]
    )
    assert "preserve unresolved conflicts for review" in external_form["guidelines"]
    assert "assigned evidence clearly supersedes it" in external_form["guidelines"]
    assert (
        "do not copy unrelated existing values into data.changes.submission"
        in external_form["guidelines"]
    )
    assert "exact schema field ids" in external_form["guidelines"]


# @matrix ai guidelines : action-selection field-type-selection payload-size
@pytest.mark.unit
def test_submission_patch_guidance_is_shared_and_omits_autofill_workflow():
    args = {
        "task": "form_autofill",
        "actions": ["update_task"],
        "field_types": ["input", "textarea"],
    }
    actor = SimpleNamespace()
    internal = get_guidelines.execute_get_guidelines(args, actor)
    external = get_guidelines.execute_external_get_guidelines(args, actor)
    full = get_guidelines.execute_external_get_guidelines(
        {"task": "form_autofill"}, actor
    )
    assert internal == external
    assert external["content_bytes"] < full["content_bytes"] / 2
    text = external["guidelines"]
    assert "omitted fields remain unchanged" in text
    assert "get_schema(include_values=true)" in text
    assert "keep longer detail" in text
    assert "Data Source Priority" not in text
    assert "Attached Files" not in text
    assert "`table` Submission Value Guidelines" not in text
    assert external["filters"] == {key: args[key] for key in ("actions", "field_types")}


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
@pytest.mark.parametrize("task", ["project", "task_form"])
def test_task_form_guidance_preserves_negative_answers_for_both_workflows(task):
    actor = SimpleNamespace()
    internal = get_guidelines.execute_get_guidelines({"task": task}, actor)
    external = get_guidelines.execute_external_get_guidelines({"task": task}, actor)

    assert internal == external
    guidance = internal["guidelines"]
    if task == "project":
        assert "Read task_form guidance" in guidance
        internal = get_guidelines.execute_get_guidelines({"task": "task_form"}, actor)
        external = get_guidelines.execute_external_get_guidelines(
            {"task": "task_form"}, actor
        )
        assert internal == external
        guidance = internal["guidelines"]
    assert "A required checkbox must be checked to complete the task" in guidance
    assert "mandatory affirmative acknowledgements" in guidance
    assert "not questions where No is valid" in guidance
    assert "required Yes/No answer" in guidance
    assert "distinct non-empty string option values" in guidance
    assert "An optional checkbox may remain unchecked" in guidance
    assert "submit_plan" not in guidance
    assert "/submit" not in guidance


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_external_duplicate_check_reuses_evidence_without_a_filename_search_ritual():
    actor = SimpleNamespace()
    external = get_guidelines.execute_external_get_guidelines(
        {"task": "filing"}, actor
    )["guidelines"]
    internal = get_guidelines.execute_get_guidelines({"task": "filing"}, actor)[
        "guidelines"
    ]

    assert "Check each file for duplicate records or occurrences" in external
    assert "already-read destination/task evidence" in external
    assert "One comparison can cover related" in external
    assert "does not require a separate filename search per file" in external
    assert "unresolved identity or occurrence" in external
    assert "similar filename or topic alone as proof of a match" in external
    assert internal == external


# @matrix ai agent-api : guidelines tool-dispatch provider-neutral-schema tool-catalog
# @source lagniappe/core/tools/ai/functions.py::tool_catalog
@pytest.mark.unit
def test_search_dispatch_and_catalog_match_across_ai_entry_points(
    monkeypatch,
):
    calls = []
    actor = SimpleNamespace()

    def lookup(arguments, user, *, candidate_search=False):
        calls.append((arguments, user, candidate_search))
        return [{"name": "Garden", "hash": "hash:abcdefghijkl", "kind": "page"}]

    monkeypatch.setattr(search, "execute_search", lookup)
    monkeypatch.setitem(functions.HANDLERS, "search_entities", lookup)
    arguments = {"query": "garden care", "external": True}
    native, _ = functions.execute_registered_tool("search_entities", arguments, actor)
    public, _ = functions.execute_registered_tool(
        "search_entities", arguments, actor, external=True
    )
    assert native == public
    assert calls == [(arguments, actor, True), (arguments, actor, True)]

    native_definition = deepcopy(functions.tool_catalog(names=["search_entities"])[0])
    external_definition = functions.tool_catalog(
        names=["search_entities"], transport="rest"
    )[0]
    assert external_definition["description"] == search.CANDIDATE_SEARCH_DESCRIPTION
    assert native_definition == external_definition
    assert functions.DECLARATIONS["search_entities"].description == external_definition["description"]
    assert (
        "keyword candidates"
        in external_definition["input_schema"]["properties"]["parent_id"]["description"]
    )
    assert functions.tool_catalog(names=["search_entities"])[0] == native_definition
    assert set(external_definition["input_schema"]["properties"]) == set(
        native_definition["input_schema"]["properties"]
    )


# @matrix agent-api task-scheduling : periodic recurring scheduled structured-output validation
# @source lagniappe/core/tools/ai/external/validation.py::submission_validation_errors
# @matrix agent-api : schema field-path
@pytest.mark.unit
@pytest.mark.parametrize(
    "schedule,valid",
    [
        ({"kind": "scheduled"}, False),
        ({"kind": "scheduled", "mode": "daily"}, True),
        ({"kind": "recurring", "interval": 2, "unit": "week"}, True),
        ({"kind": "recurring", "interval": 0, "unit": "week"}, False),
        ({"kind": "recurring", "interval": 2}, False),
        ({"kind": "periodic", "interval": 3, "unit": "month"}, False),
        (
            {
                "kind": "periodic",
                "interval": 3,
                "unit": "month",
                "description": "Quarterly",
            },
            True,
        ),
        ({"kind": "scheduled", "mode": "weekly", "days": []}, False),
        ({"kind": "scheduled", "mode": "weekly", "days": [0, 0, 2]}, True),
        ({"kind": "scheduled", "mode": "weekly", "days": [7]}, False),
        ({"kind": "scheduled", "mode": "weekly", "days": [True]}, False),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "first_day",
                "description": "Month start",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "specific_day",
                "description": "Monthly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "specific_day",
                "day": 31,
                "description": "Monthly",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "specific_day",
                "day": 32,
                "description": "Monthly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "ordinal_weekday",
                "ordinal": 0,
                "weekday": 1,
                "description": "Monthly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "ordinal_weekday",
                "ordinal": -1,
                "weekday": 1,
                "description": "Monthly",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "yearly",
                "pattern_type": "last_day",
                "description": "Yearly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "yearly",
                "pattern_type": "last_day",
                "month": 12,
                "description": "Yearly",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "yearly",
                "pattern_type": "last_day",
                "month": 13,
                "description": "Yearly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "first_day",
                "description": "",
            },
            False,
        ),
    ],
)
def test_external_schedule_schema_matches_repeating_schedule_requirements(
    schedule, valid, monkeypatch
):
    monkeypatch.setattr(
        external_contracts, "allowed_report_actions", lambda user: ("create_task",)
    )
    errors = external_api.submission_validation_errors(
        {
            "contract_version": external_api.CONTRACT_VERSION, "file_usage": [],
            "proposal": {
                "summary": "Repeat this work.",
                "confidence": 0.9,
                "actions": [
                    {
                        "type": "create_task",
                        "data": {
                            "name": "Water garden",
                            "page": "hash:abcdefghijkl",
                            "schedule": schedule,
                        },
                    },
                ],
            },
        },
        SimpleNamespace(tool="create"),
        SimpleNamespace(),
    )
    assert (not errors) is valid
    assert all(
        error["path"].startswith("$.proposal.actions[0].data.schedule")
        for error in errors
    )
    if valid:
        assert validate_task_schedule(schedule)["kind"] == schedule["kind"]
    else:
        with pytest.raises(exceptions.AIException):
            validate_task_schedule(schedule)


# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @matrix agent-api ai-report : external-schema proposal-contract structured-output
@pytest.mark.unit
def test_external_task_contract_explains_references_without_changing_provider_schema():
    provider = schema.report_proposal_response_schema(("create_task", "create_page"))
    original = deepcopy(provider)
    external = schema.external_report_proposal_response_schema(
        ("create_task", "create_page")
    )
    data = external["$defs"]["create_task"]["properties"]["data"]
    proposal = {
        "summary": "Propose a reminder.",
        "confidence": 0.9,
        "actions": [
            {
                "type": "create_task",
                "data": {
                    "name": "Water garden",
                    "page": "hash:abcdefghijkl",
                    "due_date": "2026-10-02",
                },
            },
        ],
    }
    assert external_validation._schema_errors(proposal, external, external, "$.proposal") == []
    proposal["actions"][0]["data"]["schedule"] = {"kind": "scheduled"}
    assert external_validation._schema_errors(proposal, external, external, "$.proposal") == [
        {
            "code": "required",
            "path": "$.proposal.actions[0].data.schedule.mode",
            "message": "mode is required.",
            "expected": "present",
        }
    ]
    for field in ("task", "task_action"):
        assert "completed" in data["properties"][field]["description"]
    assert "create_model_task" in data["properties"]["model_action"]["description"]
    assert "create_page" in data["properties"]["page_action"]["description"]
    assert (
        provider
        == original
        == schema.report_proposal_response_schema(("create_task", "create_page"))
    )
    for include_values in (False, True):
        genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema.report_proposal_response_schema(
                include_submission_fields=include_values
            ),
        )


# @source lagniappe/core/tools/ai/external/contracts.py::plan_contract
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix agent-api ai-report : proposal-contract
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_external_contract_reuses_known_guidance_and_exposes_canonical_scheduling(
    monkeypatch,
):
    actor = SimpleNamespace(
        page=SimpleNamespace(
            hash="personalpage",
            name="Personal",
            url="/pages/personal",
            allowed=lambda action, user=None: True,
        )
    )
    monkeypatch.setattr(
        external_contracts,
        "allowed_report_actions",
        lambda user: ("create_task", "create_page"),
    )
    monkeypatch.setattr(
        external_contracts,
        "report_action_permission_context",
        lambda user, allowed: {"allowed_actions": list(allowed)},
    )
    monkeypatch.setattr(
        external_contracts.dates,
        "user_today",
        lambda user: datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    for instructions in ("Create a task", "Organize existing records"):
        contract = external_api.plan_contract(
            SimpleNamespace(available=True, instructions=instructions, input_files=[]),
            actor,
            submit_url="https://example.test/api/v1/plans/plan/submit", view="full",
        )
        assert REPORT_TASK_SCHEDULING_GUIDELINES.strip() in contract["workflow_rules"]
        assert "guidelines" not in contract
        assert "already supplied" in contract["guidance_requirements"]["deduplication"]
        action_guidance = next(
            item
            for item in contract["guidance_requirements"]["conditional"]
            if item["request"]["task"] == "report_actions"
        )
        assert action_guidance["when"]["action_guidance_needed"] is True
        schema_guidance = [
            rule for rule in contract["guidance_requirements"]["conditional"]
            if rule["request"]["task"] == "schema_evolution"
        ]
        assert len(schema_guidance) == 1
        type_source = schema_guidance[0]["derived_request_arguments"]["field_types"]["source"]
        assert "source and destination" in type_source
        assert "nested table column types" in type_source

    for external in (False, True):
        public, _ = functions.execute_registered_tool(
            "get_guidelines", {"task": "report_actions", "actions": ["create_task", "complete_task"]},
            actor, external=external,
        )
        assert REPORT_TASK_SCHEDULING_GUIDELINES.strip() in public["guidelines"]
        assert "one source-dated completed occurrence" in public["guidelines"]
        assert "Do not invent a second completion for today" in public["guidelines"]
        assert "current execution time" in public["guidelines"]
        unrelated, _ = functions.execute_registered_tool(
            "get_guidelines", {"task": "report_actions", "actions": ["create_page"]},
            actor, external=external,
        )
        assert "Report Task Scheduling" not in unrelated["guidelines"]
