"""Proposal validation and deterministic schema repair coverage."""

import copy
from datetime import datetime, timezone

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import references as ai_references
from lagniappe.core.tools.ai.reporting.proposals import selection
from lagniappe.core.tools.ai.reporting.proposals import (
    validation as proposal_validation,
)


# @source lagniappe/core/tools/ai/reporting/proposals/repair.py::_complete_form_schema_fields
# @matrix ai-report : deterministic-repair form-type schema-field-id schema-update
# @matrix form-schema : deterministic-repair form-type schema-update
@pytest.mark.unit
@pytest.mark.parametrize("consumer,form_type", [("create_page", "page"), ("create_task", "task")])
def test_schema_repairs_keep_existing_fields_and_complete_unambiguous_structure(consumer, form_type):
    from lagniappe.core.tools.ai.reporting.proposals.repair import _complete_form_schema_fields

    proposal = {"actions": [
        {"id": "form", "type": "create_form", "data": {"name": "Details", "schema": [
            {"id": "input-name", "type": "input", "input": "email", "title": "Original"},
            {"type": "input", "placeholder": "Enter your name"},
            {"type": "input", "title": "Name"},
        ]}},
        {"id": "use", "type": consumer, "data": {"name": "Record", "form_action": "form"}},
        {"id": "schema", "type": "update_form_schema", "data": {"operations": [
            {"op": "add_field", "field": {"type": "checkbox", "label": "Ready"}},
        ]}},
    ]}
    before = copy.deepcopy(proposal)

    repaired = _complete_form_schema_fields(proposal)

    assert proposal == before
    created = repaired["actions"][0]["data"]
    assert created["form_type"] == form_type
    assert created["schema"][0] == before["actions"][0]["data"]["schema"][0]
    assert [field["id"] for field in created["schema"]] == ["input-name", "input-name-2", "input-name-3"]
    assert all(field["input"] == "text" for field in created["schema"][1:])
    field = repaired["actions"][2]["data"]["operations"][0]["field"]
    assert field["id"] == "checkbox-ready" and field["title"] == "Ready"
    assert _complete_form_schema_fields(repaired) is repaired


# @source lagniappe/core/tools/ai/reporting/proposals/repair.py::_complete_form_schema_fields
# @matrix ai-report form-schema : deterministic-repair form-type
@pytest.mark.unit
def test_schema_repair_leaves_conflicting_form_usage_for_validation():
    from lagniappe.core.tools.ai.reporting.proposals.repair import _complete_form_schema_fields

    proposal = {"actions": [
        {"id": "form", "type": "create_form", "data": {"name": "Shared", "schema": []}},
        {"id": "page", "type": "create_page", "data": {"form_action": "form"}},
        {"id": "task", "type": "create_task", "data": {"form_action": "form"}},
    ]}
    assert _complete_form_schema_fields(proposal) is proposal
    assert "form_type" not in proposal["actions"][0]["data"]


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
