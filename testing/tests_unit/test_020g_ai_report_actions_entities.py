"""Focused AI-report characterization coverage."""

from testing.utility.ai_report_fakes import *  # noqa: F403




# @features ai-report
# @dimensions proposal skip grouped-display exact-indexes schema-section
@pytest.mark.unit
def test_toggle_proposal_action_indexes_can_skip_exact_indexes_without_dependencies():
    proposal = {
        "summary": "Schema change plus exact field patches.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "schema",
                "type": "update_form_schema",
                "data": {
                    "form": "invoice-form",
                    "operations": [
                        {
                            "op": "add_select_option",
                            "schema_id": "select-status",
                            "option": {"value": "paid", "label": "Paid"},
                        }
                    ],
                },
            },
            {
                "id": "updates",
                "type": "update_submission_fields",
                "depends_on": ["schema"],
                "data": {
                    "updates": [
                        {
                            "task": "invoice-task",
                            "schema_id": "select-status",
                            "new_value": "paid",
                        }
                    ]
                },
            },
        ],
    }

    skipped = organize.toggle_proposal_action_indexes(
        proposal,
        0,
        [0],
        include_dependencies=False,
    )

    assert skipped == {"changed": [1], "skipped": [1]}
    assert [action.get("skip") for action in proposal["actions"]] == [True, None]




# @features ai-report categories
# @dimensions deterministic-run add-category idempotent undo
@pytest.mark.unit
def test_run_report_adds_page_category_without_changing_primary_with_undo(
    monkeypatch,
):
    user = _test_user("runner-add-category-owner")
    primary = TestEntities.get(
        "CATEGORY", {"name": "Primary Records", "hash": "primary-records"}
    )
    extra = TestEntities.get(
        "CATEGORY", {"name": "Family Records", "hash": "family-records-category"}
    )
    page = TestEntities.get(
        "PAGE", {"name": "Richardson Records", "hash": "richardson-records-page"}
    )
    page.model = primary
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Add page category",
            "hash": "runner-add-category-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Also file the page under Family Records.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "add_family_records",
                        "type": "add_category",
                        "data": {
                            "page": page.urlsafe_key,
                            "category": extra.urlsafe_key,
                        },
                    },
                    {
                        "id": "add_family_records_again",
                        "type": "add_category",
                        "data": {
                            "page": page.urlsafe_key,
                            "category": extra.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    entities = {
        entity.urlsafe_key: entity
        for entity in (primary, extra, page)
    }
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert [action["type"] for action in result["actions"]] == [
        "add_category",
        "add_category",
    ]
    assert page.model is primary
    assert page.categories == [primary, extra]
    assert result["actions"][0]["target"]["id"] == extra.urlsafe_key
    assert result["actions"][0]["previous"] == {"had_category": False}
    assert result["actions"][1]["previous"] == {"had_category": True}
    assert result["actions"][1]["note"] == "Page already had this category."

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert page.model is primary
    assert page.categories == [primary]
    assert undo["actions"][0]["note"] == "Category was already present; nothing removed."
    assert undo["actions"][1]["note"] == "Removed added page category."
    assert saved
