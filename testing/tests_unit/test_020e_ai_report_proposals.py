"""Proposal validation and legacy separate-prompt repair characterization.

Native Organize conversation repair is covered with the real GenAI loop below.
"""

import copy
import json

from google.genai import types as genai_types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import planner, references as ai_references
from lagniappe.core.tools.ai.reporting.proposals import selection
from lagniappe.core.tools.ai.reporting.proposals import (
    validation as proposal_validation,
)
from testing.utility.ai_report_fakes import (
    _test_user,
    _fetch_one_from,
)
from testing.utility.test_entities import TestEntities


# @pairs ai-report:proposal ai-report:validation editor:document markdown:html-sanitization
@pytest.mark.unit
def test_validate_proposal_renders_page_document_markdown():
    proposal = {
        "summary": "Create a reference page.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "create-reference",
                "type": "create_page",
                "data": {
                    "name": "Reference",
                    "document_markdown": (
                        "# Heading\n\n| Name | Value |\n| --- | --- |\n"
                        "| Safe | <script>alert('no')</script>Yes |"
                    ),
                },
            }
        ],
    }

    validated = proposal_validation.validate_proposal(proposal)
    data = validated["actions"][0]["data"]

    assert "document_markdown" not in data
    assert "<h1>Heading</h1>" in data["document"]
    assert "<table>" in data["document"]
    assert "<script" not in data["document"]


# @matrix ai-report : proposal validation
@pytest.mark.unit
@pytest.mark.parametrize(
    "form_type,field",
    [
        (
            "task",
            {"id": "notice", "type": "html", "title": "Notice", "html": "<b>raw</b>"},
        ),
        (
            "task",
            {
                "id": "notice",
                "type": "html",
                "title": "Notice",
                "content_markdown": 3,
            },
        ),
        (
            "page",
            {
                "id": "notice",
                "type": "html",
                "title": "Notice",
                "content_markdown": "Notice",
            },
        ),
    ],
)
def test_validate_proposal_rejects_invalid_static_form_content(form_type, field):
    proposal = {
        "summary": "Create a form.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "form",
                "type": "create_form",
                "data": {
                    "name": "Form",
                    "form_type": form_type,
                    "schema": [field],
                },
            }
        ],
    }

    with pytest.raises(exceptions.AIException):
        proposal_validation.validate_proposal(proposal)


# @pairs ai-report:reference-kind permissions:personal-page
@pytest.mark.unit
def test_validate_proposal_accepts_virtual_user_kind_as_personal_page(monkeypatch):
    personal_hash = "abc123def456"
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            personal_hash: {
                "id": "personal-page-key",
                "kind": "user",
                "name": "Personal Page",
            }
        },
    )
    proposal = {
        "summary": "Add the requested personal task.",
        "confidence": 1,
        "issues": [],
        "actions": [
            {
                "id": "personal-task",
                "type": "create_task",
                "data": {
                    "name": "Review API access",
                    "page": f"hash:{personal_hash}",
                },
            }
        ],
    }

    validated = proposal_validation.validate_proposal(
        proposal,
        allowed_actions=("create_task",),
        validate_reference_kinds=True,
    )

    assert validated["actions"][0]["data"]["page"] == "personal-page-key"

    wrong_field = copy.deepcopy(proposal)
    wrong_field["actions"][0]["data"]["project"] = f"hash:{personal_hash}"
    with pytest.raises(exceptions.AIException, match="uses user .* as its project"):
        proposal_validation.validate_proposal(
            wrong_field,
            allowed_actions=("create_task",),
            validate_reference_kinds=True,
        )


# @matrix ai-report : task-page validation
@pytest.mark.unit
def test_validate_proposal_requires_create_task_page_reference():
    proposal = {
        "summary": "Create a task without a destination Page.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "orphan-task",
                "type": "create_task",
                "data": {
                    "name": "Review AI Reports empty state",
                    "page_name": "Lagniappe",
                },
            }
        ],
    }

    with pytest.raises(
        exceptions.AIException,
        match=(
            r"Action orphan-task \(create_task\) requires data\.page "
            r"or data\.page_action\."
        ),
    ):
        proposal_validation.validate_proposal(proposal)


# @matrix ai-report : repair validation
# @matrix ai : tool-loop tool-dispatch
# @source lagniappe/core/tools/ai/planner.py::generate_report
# @source lagniappe/core/tools/ai/core.py::GenAI.generate_content
# @source lagniappe/core/tools/ai/core.py::GenAI._tool_loop
# @source lagniappe/core/tools/ai/planner.py::generate_report
@pytest.mark.unit
@pytest.mark.parametrize(
    "mode", ["valid", "repair", "invalid_json", "exhausted", "empty_exhausted"]
)
def test_organize_conversation_validation_preserves_complete_proposal(
    monkeypatch, mode
):
    from lagniappe.core.tools.ai import core, functions, observability, settings

    user = _test_user("email-travel-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Travel details",
            "parent": user,
            "user": user,
            "origin": "email",
            "tool": "organize",
            "instructions": "Update both bookings, complete both tasks, and append the tour link.",
        },
    )
    report.origin, report.tool = "email", "organize"
    page = TestEntities.get("PAGE", {"name": "College trip"})
    task = TestEntities.get("TASK", {"name": "Book Plane Tickets"}, page=page)
    form = TestEntities.get("FORM", {"name": "Flights"})
    form.form_type = "task"
    form.schema = [
        {
            "id": "table-flights",
            "type": "table",
            "title": "Flights",
            "columns": [
                {
                    "id": "row-flight",
                    "type": "input",
                    "input": "text",
                    "title": "Flight",
                },
                {
                    "id": "row-confirmation",
                    "type": "input",
                    "input": "text",
                    "title": "Confirmation",
                },
            ],
        }
    ]
    task.form = form
    flights = {
        "rows": [
            {"row-flight": "UA1458", "row-confirmation": "PR2FYB"},
            {"row-flight": "B61680", "row-confirmation": "PSDSX9"},
            {"row-flight": "UA1434", "row-confirmation": "PSJLBB"},
        ]
    }
    proposal = {
        "summary": "Update both bookings, complete both tasks, and append the tour link.",
        "confidence": 1,
        "issues": [],
        "file_usage": [],
        "actions": [
            {
                "id": "flights",
                "type": "update_form_values",
                "data": {
                    "updates": [
                        {
                            "task": task.urlsafe_key,
                            "schema_id": "table-flights",
                            "new_value": flights,
                        }
                    ]
                },
            },
            {
                "id": "hotels",
                "type": "update_form_values",
                "data": {
                    "updates": [
                        {
                            "task": "hotel-task-id",
                            "schema_id": "textarea-booking",
                            "new_value": "Confirmed hotel",
                        }
                    ]
                },
            },
            {
                "id": "flight-done",
                "type": "complete_task",
                "depends_on": ["flights"],
                "data": {"task": task.urlsafe_key},
            },
            {
                "id": "hotel-done",
                "type": "complete_task",
                "depends_on": ["hotels"],
                "data": {"task": "hotel-task-id"},
            },
            {
                "id": "tour",
                "type": "append_page_document",
                "data": {
                    "page": page.urlsafe_key,
                    "document_markdown": "[Tour](https://example.com/tour)",
                },
            },
        ],
    }
    invalid = copy.deepcopy(proposal)
    invalid["actions"][0]["data"]["updates"][0]["new_value"] = {
        "rows": ["Flight", "Confirmation"]
    }
    reads, requests, summaries = [], [], []

    def get_schema(args, actor):
        reads.append(args)
        return {"schema": form.schema, "evidence": "All three confirmed flights"}

    def response(value=None, tool=False):
        part = (
            genai_types.Part.from_function_call(
                name="get_schema", args={"id": task.urlsafe_key}
            )
            if tool
            else genai_types.Part.from_text(
                text=value if isinstance(value, str) else json.dumps(value)
            )
        )
        return genai_types.GenerateContentResponse(
            candidates=[
                genai_types.Candidate(
                    content=genai_types.Content(role="model", parts=[part])
                )
            ]
        )

    if mode == "valid":
        responses = [response(tool=True), response(proposal)]
    elif mode in {"exhausted", "empty_exhausted"}:
        failed = "" if mode == "empty_exhausted" else invalid
        responses = [
            response(tool=True),
            response(failed),
            response(failed),
            response(failed),
        ]
    else:
        responses = [
            response(tool=True),
            response("{broken JSON" if mode == "invalid_json" else invalid),
            response(tool=True),
            response(proposal),
        ]

    def generate_content(**kwargs):
        requests.append({**kwargs, "contents": list(kwargs["contents"])})
        return responses[len(requests) - 1]

    monkeypatch.setitem(functions.HANDLERS, "get_schema", get_schema)
    monkeypatch.setattr(
        core.ai_model,
        "_client",
        SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
    )
    monkeypatch.setattr(settings.site_database, "ai", lambda: None)
    monkeypatch.setattr(observability, "prune_old_records", lambda: None)
    monkeypatch.setattr(
        observability,
        "_write_summary",
        lambda summary: summaries.append(summary.payload()),
    )
    monkeypatch.setattr(
        proposal_validation.Entities,
        "fetch_one",
        _fetch_one_from({task.urlsafe_key: task}),
    )
    prompt = planner.report_prompt(report, user)
    prompt.set_max_tool_iterations(2)
    if mode in {"exhausted", "empty_exhausted"}:
        expected_error = (
            "no text content"
            if mode == "empty_exhausted"
            else "must be an object keyed by column ids"
        )
        with pytest.raises(exceptions.AIException, match=expected_error):
            planner.generate_report(prompt)["proposal"]
        assert len(requests) == 4
    else:
        result = planner.generate_report(prompt)["proposal"]
        assert len(result["actions"]) == 5
        assert result["actions"][0]["data"]["updates"][0]["new_value"] == flights
        assert result["actions"][2]["depends_on"] == ["flights"]
        assert result["actions"][3]["depends_on"] == ["hotels"]
        assert "https://example.com/tour" in result["actions"][4]["data"]["document"]
        assert len(requests) == (2 if mode == "valid" else 4)
    assert len(reads) == 1  # The correction's repeated schema read uses the same cache.
    assert len({request["model"] for request in requests}) == 1
    assert all(request["config"].response_schema is None for request in requests)
    assert len(summaries) == 1
    assert summaries[0]["structured_final_used"] is False
    assert summaries[0]["provider_requests"] == len(requests)
    assert summaries[0]["success"] is (mode not in {"exhausted", "empty_exhausted"})
    if mode != "valid":
        history = requests[-1]["contents"]
        text = "\n".join(
            part.text or ""
            for content in history
            if not isinstance(content, str)
            for part in content.parts
        )
        assert "Response validation failed" in text
        assert "complete corrected JSON response" in text
        assert any(
            part.function_response
            for content in history
            if not isinstance(content, str)
            for part in content.parts
        )
        assert len(history) > len(requests[1]["contents"])


# @matrix ai-report form-schema : proposal schema-update validation
@pytest.mark.unit
def test_validate_proposal_rejects_unsafe_schema_update_operations():
    proposal = {
        "summary": "Delete an existing form field.",
        "confidence": 0.8,
        "issues": [],
        "actions": [
            {
                "id": "delete_payment_reference",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {"op": "delete_field", "schema_id": "input-reference"}
                    ],
                },
            }
        ],
    }

    with pytest.raises(exceptions.AIException, match="unsupported op"):
        proposal_validation.validate_proposal(proposal)


# @matrix ai-report : move-references proposal validation
@pytest.mark.unit
@pytest.mark.parametrize(
    ("action_type", "data", "missing"),
    [
        ("move_page", {"category": "medical"}, "page"),
        ("move_page", {"page": "eyes"}, "category"),
        ("move_task", {"page": "lucy-eyes"}, "task"),
        pytest.param(
            "move_task",
            {"task": "specialist-consultation"},
            "to_page",
            id="move_task-data3-page",
        ),
    ],
)
def test_validate_proposal_requires_move_entity_references(
    action_type,
    data,
    missing,
):
    proposal = {
        "summary": "Move an existing workspace record.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "move_record",
                "type": action_type,
                "data": data,
            }
        ],
    }

    with pytest.raises(exceptions.AIException, match=rf"requires data\.{missing}"):
        proposal_validation.validate_proposal(proposal)


# @matrix ai-report : canonical-target legacy-target proposal rename validation
@pytest.mark.unit
def test_validate_proposal_accepts_rename_and_move_task_target_aliases():
    proposal = {
        "summary": "Rename a page and consolidate its tasks.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "rename_page",
                "type": "rename_entity",
                "data": {"entity": "orthodontics-page", "name": "Teeth"},
            },
            {
                "id": "canonical_move",
                "type": "move_task",
                "data": {
                    "task": "invisalign-task",
                    "to_page": "orthodontics-page",
                },
            },
            {
                "id": "legacy_move",
                "type": "move_task",
                "data": {
                    "task": "sealants-task",
                    "page": "orthodontics-page",
                },
            },
        ],
    }

    assert proposal_validation.validate_proposal(proposal) == proposal

    for data, missing in (
        ({"name": "Teeth"}, "entity"),
        ({"entity": "orthodontics-page"}, "name"),
    ):
        invalid = copy.deepcopy(proposal)
        invalid["actions"] = [
            {"id": "rename_page", "type": "rename_entity", "data": data}
        ]
        with pytest.raises(
            exceptions.AIException,
            match=rf"rename_page \(rename_entity\) requires data\.{missing}",
        ):
            proposal_validation.validate_proposal(invalid)


# @matrix ai-report : explicit-task-identity proposal validation
@pytest.mark.unit
def test_validate_proposal_requires_completed_root_task_targets():
    with pytest.raises(
        exceptions.AIException,
        match="target an existing task only for a completed occurrence",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Invalid active task target.",
                "actions": [
                    {
                        "id": "active_task",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": "prescriptions-page",
                            "task": "lisinopril-task",
                        },
                    }
                ],
            }
        )

    proposal = {
        "summary": "Record two occurrences of one prescription.",
        "actions": [
            {
                "id": "lisinopril_current",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": "prescriptions-page",
                    "completed_on": "2025-03-01",
                },
            },
            {
                "id": "lisinopril_prior",
                "type": "create_task",
                "data": {
                    "name": "Lisinopril Prescription",
                    "page": "prescriptions-page",
                    "task_action": "lisinopril_current",
                    "completed_on": "2024-03-01",
                },
            },
        ],
    }
    assert (
        proposal_validation.validate_proposal(copy.deepcopy(proposal))["issues"] == []
    )

    proposal["actions"].append(
        {
            "id": "lisinopril_chained",
            "type": "create_task",
            "data": {
                "name": "Lisinopril Prescription",
                "page": "prescriptions-page",
                "task_action": "lisinopril_prior",
                "completed": True,
            },
        }
    )
    with pytest.raises(
        exceptions.AIException,
        match="earlier untargeted completed create_task",
    ):
        proposal_validation.validate_proposal(proposal)


# @matrix ai-report : completed-task future-date proposal validation
@pytest.mark.unit
def test_validate_proposal_rejects_future_completed_dates(monkeypatch):
    monkeypatch.setattr(
        proposal_validation.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    proposal = {
        "summary": "Record a completed inspection.",
        "actions": [
            {
                "id": "inspection",
                "type": "create_task",
                "data": {
                    "name": "Hive Inspection",
                    "page": "hive-page",
                    "completed_on": "2026-09-01",
                },
            }
        ],
    }

    with pytest.raises(
        exceptions.AIException,
        match="completion date cannot be in the future",
    ):
        proposal_validation.validate_proposal(copy.deepcopy(proposal))

    proposal["actions"][0]["data"]["completed_on"] = "2026-08-31"
    assert proposal_validation.validate_proposal(proposal)["issues"] == []


# @matrix ai-report : dependencies proposal validation
@pytest.mark.unit
def test_validate_proposal_rejects_unknown_actions_and_bad_dependencies(monkeypatch):
    hash_lookups = []

    def fake_get_details_by_hash(hashes):
        hash_lookups.append(list(hashes))
        return {
            "abc123def456": {"id": "page-id"},
            "def456abc789": {"id": "file-id"},
        }

    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        fake_get_details_by_hash,
    )

    with pytest.raises(exceptions.AIException, match="Unknown report action"):
        proposal_validation.validate_proposal(
            {"summary": "Nope", "confidence": 0.1, "actions": [{"type": "dance"}]}
        )

    with pytest.raises(exceptions.AIException, match="depends on unknown"):
        proposal_validation.validate_proposal(
            {
                "summary": "Bad dependency",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "data": {
                            "name": "Bad Reference Page",
                            "category_action": "later",
                        },
                    },
                    {"id": "later", "type": "create_category", "data": {}},
                ],
            }
        )

    cleaned_dependencies = proposal_validation.validate_proposal(
        {
            "summary": "Bad explicit dependency note",
            "confidence": 0.5,
            "actions": [
                {"id": "page", "type": "create_page", "data": {"name": "Page"}},
                {
                    "id": "create_task_sousa_doors_final_invoice",
                    "type": "create_task",
                    "depends_on": [
                        "$page",
                        (
                            "2,000.00 deposit paid on Jan 27, 2021 via check 1096. "
                            "Remaining $2,250.00 balance due by Feb 26, 2021."
                        ),
                    ],
                    "data": {
                        "name": "Sousa Doors Final Invoice",
                        "page_action": "page",
                    },
                },
            ],
        }
    )
    assert cleaned_dependencies["actions"][1]["depends_on"] == ["$page"]
    assert cleaned_dependencies["issues"] == []

    with pytest.raises(exceptions.AIException, match="not allowed"):
        proposal_validation.validate_proposal(
            {
                "summary": "Forbidden",
                "confidence": 0.1,
                "actions": [{"type": "create_category", "data": {}}],
            },
            allowed_actions={"skip", "needs_review"},
        )

    with pytest.raises(exceptions.AIException, match="issues"):
        proposal_validation.validate_proposal(
            {
                "summary": "Bad issues",
                "confidence": 0.1,
                "issues": "Nope",
                "actions": [],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"create_page\) requires data.name",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Nameless page",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "create_morrissey_compton_page",
                        "type": "create_page",
                        "display_label": (
                            "Create Morrissey-Compton Educational Center Page"
                        ),
                        "data": {},
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"create_form\) requires at least one data.schema field",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Blank form",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "empty_form",
                        "type": "create_form",
                        "data": {
                            "name": "Empty Form",
                            "form_type": "page",
                            "schema": [],
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"data.schema\[1\] requires title",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Bad form field",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "bad_form",
                        "type": "create_form",
                        "data": {
                            "name": "Bad Form",
                            "form_type": "page",
                            "schema": [{"id": "input-name", "type": "input"}],
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Page form without submission",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "cvs_pharmacy_page",
                        "type": "create_page",
                        "data": {
                            "name": "CVS Pharmacy",
                            "form_name": "Business",
                        },
                    },
                ],
            }
        )

    pending_submission = proposal_validation.validate_proposal(
        {
            "summary": "Page form with pending completion",
            "confidence": 0.8,
            "actions": [
                {
                    "id": "cvs_pharmacy_page",
                    "type": "create_page",
                    "data": {
                        "name": "CVS Pharmacy",
                        "form_name": "Business",
                    },
                },
            ],
        },
        allow_pending_submissions=True,
    )
    assert "submission" not in pending_submission["actions"][0]["data"]
    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        proposal_validation.validate_proposal(
            pending_submission,
            allow_pending_submissions=False,
        )

    empty_completed_submission = proposal_validation.validate_proposal(
        {
            "summary": "Page form with completed empty submission pass",
            "confidence": 0.8,
            "actions": [
                {
                    "id": "cvs_pharmacy_page",
                    "type": "create_page",
                    "data": {
                        "name": "CVS Pharmacy",
                        "form_name": "Business",
                        "submission": {},
                        "submission_empty_reason": (
                            "No submission fields were filled from the available evidence."
                        ),
                    },
                },
            ],
        },
        allow_pending_submissions=False,
    )
    assert (
        empty_completed_submission["actions"][0]["data"]["submission_empty_reason"]
        == "No submission fields were filled from the available evidence."
    )

    with pytest.raises(
        exceptions.AIException,
        match=r"uses a form and requires non-empty data.submission",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Task form with empty submission",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "screening_task",
                        "type": "create_task",
                        "data": {
                            "name": "Athletic Screening",
                            "page": "julie-page-id",
                            "form": "doctor-appointment-form-id",
                            "submission": {},
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"move_file\) requires exactly one source",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Missing move source",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "family_records",
                        "type": "create_page",
                        "data": {"name": "Family Records"},
                    },
                    {
                        "id": "move_file_richardson",
                        "type": "move_file",
                        "data": {
                            "file": "richardson-file-id",
                            "display_name": "Richardson Family Records.pdf",
                            "to_page_action": "family_records",
                        },
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"add_page_category\) requires data.page",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Missing page category add",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "add_records_category",
                        "type": "add_page_category",
                        "data": {"category": "records-category-id"},
                    },
                ],
            }
        )
    with pytest.raises(
        exceptions.AIException,
        match=r"update_form_values\) requires at least one data.updates row",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Empty submission update",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "empty_submission_update",
                        "type": "update_form_values",
                        "data": {"updates": []},
                    },
                ],
            }
        )

    with pytest.raises(
        exceptions.AIException,
        match=r"data.updates\[1\] requires exactly one page or task",
    ):
        proposal_validation.validate_proposal(
            {
                "summary": "Malformed submission update",
                "confidence": 0.1,
                "actions": [
                    {
                        "id": "bad_submission_update",
                        "type": "update_form_values",
                        "data": {
                            "updates": [
                                {
                                    "schema_id": "select-rank",
                                    "new_value": "white-belt",
                                }
                            ]
                        },
                    },
                ],
            }
        )

    recoverable_file_reference_proposal = proposal_validation.validate_proposal(
        {
            "summary": "Recoverable file reference problems",
            "confidence": 0.1,
            "issues": [
                "Some file references were readable labels instead of executable refs."
            ],
            "actions": [
                {
                    "id": "create_pettis_remodeling_design_page",
                    "type": "create_page",
                    "data": {"name": "Pettis Remodeling Design"},
                },
                {
                    "id": "attachment",
                    "type": "attach_file",
                    "data": {
                        "entity": "existing-page",
                        "display_name": "Pettis Proposal",
                        "file": "unavailable-report-file",
                    },
                },
                {
                    "id": "completed_task_display_file",
                    "type": "create_task",
                    "data": {
                        "page": "existing-page",
                        "completed_on": "2023-06-24",
                        "file_label": "Pettis Proposal",
                    },
                },
                {
                    "id": "completed_task_no_file",
                    "type": "create_task",
                    "display_label": "ToDo's? All Done! Service Agreement",
                    "data": {
                        "name": "Robbyn Willebeek-LeMair PM Agreement",
                        "page": "$create_pettis_remodeling_design_page",
                        "completed_on": "2014-06-09",
                        "model": "project-management-design-model",
                    },
                },
            ],
        }
    )
    assert recoverable_file_reference_proposal["summary"] == (
        "Recoverable file reference problems"
    )
    assert recoverable_file_reference_proposal["issues"] == [
        "Some file references were readable labels instead of executable refs."
    ]

    with pytest.raises(exceptions.AIException, match="attach_file"):
        proposal_validation.validate_proposal(
            {
                "summary": "Invalid task attachment shape",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "completed_task_with_file",
                        "type": "create_task",
                        "data": {
                            "page": "existing-page",
                            "completed_on": "2023-06-24",
                            "file": "registration.pdf",
                        },
                    },
                ],
            }
        )

    proposal = proposal_validation.validate_proposal(
        {
            "summary": "OK",
            "confidence": 0.9,
            "actions": [
                {
                    "id": "form",
                    "type": "create_form",
                    "data": {
                        "name": "Record Form",
                        "form_type": "page",
                        "schema": [
                            {
                                "id": "input-name",
                                "type": "input",
                                "input": "text",
                                "title": "Name",
                            }
                        ],
                    },
                },
                {
                    "id": "category",
                    "type": "create_category",
                    "data": {"form_action": "form"},
                },
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {"page": "existing-page"},
                },
                {
                    "id": "completed_task",
                    "type": "create_task",
                    "data": {
                        "page": "existing-page",
                        "completed_on": "2023-06-24",
                    },
                },
                {
                    "id": "completed_task_attachment",
                    "type": "attach_file",
                    "data": {
                        "entity_action": "completed_task",
                        "file": "registration.pdf",
                    },
                },
            ],
        }
    )
    assert proposal["summary"] == "OK"
    assert proposal["issues"] == []

    normalized = proposal_validation.validate_proposal(
        {
            "summary": "Normalize hash refs",
            "confidence": 0.9,
            "actions": [
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {
                        "page": "hash:abc123def456",
                        "description": "Unknown hash:000000000000 stays visible.",
                        "submission": {
                            "input-abc123def456": "Schema ids are not references."
                        },
                    },
                },
                {
                    "id": "attach_task_file",
                    "type": "attach_file",
                    "data": {
                        "entity_action": "task",
                        "file": "hash:def456abc789",
                    },
                },
            ],
        }
    )

    assert set(hash_lookups[0]) == {
        "abc123def456",
        "def456abc789",
        "000000000000",
    }
    assert normalized["actions"][0]["data"]["page"] == "page-id"
    assert normalized["actions"][1]["data"]["file"] == "file-id"
    assert normalized["actions"][0]["data"]["description"] == (
        "Unknown hash:000000000000 stays visible."
    )
    assert normalized["actions"][0]["data"]["submission"] == {
        "input-abc123def456": "Schema ids are not references."
    }


# @matrix ai-report : action-reference-namespace proposal submission validation
@pytest.mark.unit
def test_validate_proposal_treats_action_like_submission_fields_as_content():
    proposal = {
        "summary": "Record contract and compensation details.",
        "issues": [],
        "actions": [
            {
                "id": "contracts_page",
                "type": "create_page",
                "data": {"name": "Contracts"},
            },
            {
                "id": "contract_task",
                "type": "create_task",
                "data": {
                    "name": "Nate Patrin 2021 contract",
                    "page_action": "contracts_page",
                    "submission": {
                        "action": (
                            "4,175.00 in nonemployee compensation. No federal "
                            "or state income tax withholding was reported."
                        ),
                        "payment_action": (
                            "2500 total payment for 100 capsule album reviews."
                        ),
                    },
                },
            },
        ],
    }

    validated = proposal_validation.validate_proposal(copy.deepcopy(proposal))

    assert (
        validated["actions"][1]["data"]["submission"]
        == proposal["actions"][1]["data"]["submission"]
    )


# @matrix ai-report : file-placement proposal validation
@pytest.mark.unit
def test_validate_proposal_requires_every_report_file_attachment(monkeypatch):
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "aaaaaaaaaaaa": {"id": "first-file-id", "kind": "file"},
            "bbbbbbbbbbbb": {"id": "second-file-id", "kind": "file"},
        },
    )
    proposal = {
        "summary": "Attach one of two files.",
        "confidence": 0.7,
        "issues": [],
        "actions": [
            {
                "id": "attach_first",
                "type": "attach_file",
                "data": {
                    "entity": "existing-page",
                    "file": "hash:aaaaaaaaaaaa",
                },
            },
            {
                "id": "unresolved_second",
                "type": "attach_file",
                "data": {"file": "hash:bbbbbbbbbbbb"},
            },
        ],
    }

    with pytest.raises(
        exceptions.AIException,
        match=r"Missing report_file_ref values: hash:bbbbbbbbbbbb",
    ):
        proposal_validation.validate_proposal(
            proposal,
            required_file_refs=("hash:aaaaaaaaaaaa", "hash:bbbbbbbbbbbb"),
        )

    proposal["actions"][1]["data"]["entity"] = "existing-task"
    proposal["actions"][1]["type"] = "attach_file"

    validated = proposal_validation.validate_proposal(
        proposal,
        required_file_refs=("hash:aaaaaaaaaaaa", "hash:bbbbbbbbbbbb"),
    )
    assert validated["actions"][0]["data"]["file"] == "first-file-id"
    assert validated["actions"][1]["data"]["file"] == "second-file-id"


# @matrix ai-report : file-summary proposal validation
@pytest.mark.unit
def test_validate_proposal_requires_external_file_summaries(monkeypatch):
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "aaaaaaaaaaaa": {"id": "first-file-id", "kind": "file"},
            "bbbbbbbbbbbb": {"id": "second-file-id", "kind": "file"},
        },
    )
    proposal = {
        "summary": "Attach and summarize two files.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "attach_first",
                "type": "attach_file",
                "data": {"entity": "existing-page", "file": "hash:aaaaaaaaaaaa"},
            },
            {
                "id": "attach_second",
                "type": "attach_file",
                "data": {"entity": "existing-task", "file": "hash:bbbbbbbbbbbb"},
            },
        ],
    }
    required = ("hash:aaaaaaaaaaaa", "hash:bbbbbbbbbbbb")

    with pytest.raises(
        exceptions.AIException,
        match=r"Missing report_file_ref values: hash:aaaaaaaaaaaa, hash:bbbbbbbbbbbb",
    ):
        proposal_validation.validate_proposal(
            copy.deepcopy(proposal),
            required_file_refs=required,
            require_file_summaries=True,
        )

    proposal["actions"].extend(
        [
            {
                "id": "summarize_first",
                "type": "summarize_file",
                "data": {
                    "file": "hash:aaaaaaaaaaaa",
                    "summary": "The first source concerns Avery's contact details.",
                    "retrieval_terms": ["Avery", "contacts"],
                    "search": True,
                },
            },
            {
                "id": "summarize_second",
                "type": "summarize_file",
                "data": {
                    "file": "hash:bbbbbbbbbbbb",
                    "summary": "The second source records apiary maintenance.",
                    "retrieval_terms": ["apiary", "maintenance"],
                    "search": True,
                },
            },
        ]
    )

    validated = proposal_validation.validate_proposal(
        copy.deepcopy(proposal),
        required_file_refs=required,
        require_file_summaries=True,
    )
    assert validated["actions"][2]["data"]["file"] == "first-file-id"
    assert validated["actions"][3]["data"]["retrieval_terms"] == [
        "apiary",
        "maintenance",
    ]

    missing_terms = copy.deepcopy(proposal)
    missing_terms["actions"][2]["data"].pop("retrieval_terms")
    with pytest.raises(exceptions.AIException, match="exactly two distinct"):
        proposal_validation.validate_proposal(
            missing_terms,
            required_file_refs=required,
            require_file_summaries=True,
        )

    duplicate = copy.deepcopy(proposal)
    duplicate["actions"].append(
        {
            **copy.deepcopy(duplicate["actions"][3]),
            "id": "summarize_second_again",
        }
    )
    with pytest.raises(exceptions.AIException, match="exactly one summary"):
        proposal_validation.validate_proposal(
            duplicate,
            required_file_refs=required,
            require_file_summaries=True,
        )

    unexpected = copy.deepcopy(proposal)
    unexpected["actions"].append(
        {
            "id": "summarize_other",
            "type": "summarize_file",
            "data": {
                "file": "other-file-id",
                "summary": "This file is not part of the report.",
                "retrieval_terms": ["other", "unrelated"],
            },
        }
    )
    with pytest.raises(exceptions.AIException, match="must target report input"):
        proposal_validation.validate_proposal(
            unexpected,
            required_file_refs=required,
            require_file_summaries=True,
        )


# @matrix ai-report : dependencies proposal skip
@pytest.mark.unit
def test_skip_proposal_actions_marks_dependencies():
    proposal = {
        "summary": "Create then attach.",
        "confidence": 0.9,
        "actions": [
            {"id": "category", "type": "create_category", "data": {}},
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "Scanned Page", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file",
                "data": {"entity_action": "page", "file": "scan.pdf"},
            },
            {"id": "other", "type": "needs_review", "data": {}},
        ],
    }

    skipped = selection.skip_proposal_actions(proposal, 0)

    assert skipped == [1, 2, 3]
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]


# @matrix ai-report : dependencies grouped-display proposal restore skip
@pytest.mark.unit
def test_toggle_proposal_action_skip_restores_dependencies():
    proposal = {
        "summary": "Create then attach.",
        "confidence": 0.9,
        "actions": [
            {"id": "category", "type": "create_category", "data": {}},
            {
                "id": "page",
                "type": "create_page",
                "data": {"name": "Scanned Page", "category_action": "category"},
            },
            {
                "id": "attachment",
                "type": "attach_file",
                "data": {"entity_action": "page", "file": "scan.pdf"},
            },
            {"id": "other", "type": "needs_review", "data": {}},
        ],
    }

    skipped = selection.toggle_proposal_action_skip(proposal, 0)

    assert skipped == {"changed": [1, 2, 3], "skipped": [1, 2, 3]}
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]

    restored = selection.toggle_proposal_action_skip(proposal, 0)

    assert restored == {"changed": [1, 2, 3], "skipped": []}
    assert [action.get("skip") for action in proposal["actions"]] == [
        None,
        None,
        None,
        None,
    ]

    grouped = selection.toggle_proposal_action_indexes(proposal, 1, [0, 1])

    assert grouped == {"changed": [1, 2, 3], "skipped": [1, 2, 3]}
    assert [action.get("skip") for action in proposal["actions"]] == [
        True,
        True,
        True,
        None,
    ]
