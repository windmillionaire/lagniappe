"""Autofill uses exact schema IDs and validates before changing saved answers."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools.ai import autofill, core as ai_core
from lagniappe.core.tools.ai import settings as runtime_settings
from lagniappe.core.tools.ai import observability
from testing.utility.test_entities import TestEntities


@pytest.fixture
def game(monkeypatch):
    from lagniappe.core.tools.database import get as database_get

    monkeypatch.setattr(database_get, "page_files", lambda key: [])
    actor = TestEntities.get("USER", {"name": "Owner", "hash": "autofill-owner", "owner": True})
    actor.db["timezone"] = "America/Los_Angeles"
    page = TestEntities.get("PAGE", {"name": "Outer Wilds", "hash": "autofill-game"})
    form = TestEntities.get("FORM", {"name": "Game", "hash": "autofill-game-form"})
    form.schema = [
        {"id": "select-playstat", "type": "select", "title": "Play status", "options": [
            {"label": "Interested in playing", "value": "interested"},
            {"label": "Played", "value": "played"},
        ]},
        {"id": "input-publisher", "type": "input", "title": "Notes"},
        {"id": "input-developer", "type": "input", "title": "Notes"},
        {"id": "checkbox-finished", "type": "checkbox", "title": "Finished"},
        {"id": "input-hours", "type": "input", "input": "number", "title": "Hours"},
        {"id": "input-release", "type": "input", "input": "date", "title": "Release"},
        {"id": "table-reviews", "type": "table", "title": "Reviews", "columns": [
            {"id": "row-outlet", "type": "input", "title": "Outlet"},
        ]},
    ]
    page.form = form
    page.properties.submission.value = {"select-playstat": "interested"}
    return page, actor


# @source lagniappe/core/tools/ai/autofill.py::autofill_prompt_data
# @matrix ai : partial-submission shared-context
@pytest.mark.unit
def test_autofill_context_preserves_exact_ids_with_duplicate_labels(game):
    page, actor = game
    page.properties.submission.value = {
        "select-playstat": "interested", "input-publisher": "Annapurna",
        "input-developer": "Mobius", "checkbox-finished": False, "input-hours": 0,
        "table-reviews": {"rows": [{"row-outlet": "Example"}]},
    }
    # Human-readable entity projections deliberately use labels and lose duplicate
    # titles. Autofill must instead use the exact-ID projection used by get_schema.
    assert "Play status" in page.properties.submission.ai_value
    data = autofill.autofill_prompt_data(page, actor)
    assert data["schema"] == page.submission_schema
    assert data["submission"] == {
        "select-playstat": "Interested in playing", "input-publisher": "Annapurna",
        "input-developer": "Mobius", "checkbox-finished": False, "input-hours": 0,
        "table-reviews": {"rows": [{"row-outlet": "Example"}]},
    }


# @source lagniappe/core/tools/ai/autofill.py::generate_autofilled_submission
# @source lagniappe/core/tools/ai/autofill.py::validate_submission
# @source lagniappe/core/tools/ai/core.py::GenAI._tool_loop
# @matrix ai : validation repair
@pytest.mark.unit
@pytest.mark.parametrize("exhausted", [False, True])
def test_autofill_repairs_invalid_ids_and_table_rows_before_acceptance(monkeypatch, game, exhausted):
    page, actor = game
    before = deepcopy(page.submission)
    invalid = {"Play status": "Interested in playing", "select-playstat": "interested",
               "input-publisher": "Annapurna"}
    final = {"select-playstat": "played", "input-publisher": "Annapurna",
             "table-reviews": {"rows": [{"row-outlet": "Example"}]}}
    payloads = [invalid, {"table-reviews": {"rows": [{"Outlet": "Example"}]}},
                invalid if exhausted else final]
    calls = []
    summaries = []

    def provider(**kwargs):
        calls.append(deepcopy(kwargs))
        return SimpleNamespace(function_calls=[], candidates=[SimpleNamespace(
            finish_reason=None, content=SimpleNamespace(parts=[SimpleNamespace(
                text=json.dumps(payloads[len(calls) - 1]),
            )]),
        )])

    monkeypatch.setattr(runtime_settings.site_database, "ai", lambda: None)
    monkeypatch.setattr(observability, "_write_summary", lambda summary: summaries.append(summary.payload()))
    monkeypatch.setattr(observability, "prune_old_records", lambda: None)
    generator = ai_core.GenAI()
    generator._client = SimpleNamespace(models=SimpleNamespace(generate_content=provider))
    monkeypatch.setattr(autofill, "ai_model", generator)
    prompt = autofill.form_autofill_prompt(**autofill.autofill_prompt_data(page, actor))
    if exhausted:
        with pytest.raises(exceptions.AIException, match="unavailable field ids"):
            autofill.generate_autofilled_submission(prompt, entity=page, user=actor)
    else:
        result = autofill.generate_autofilled_submission(prompt, entity=page, user=actor)
        assert result == {**final, "select-playstat": "Interested in playing"}
    assert len(calls) == 3
    assert page.submission == before
    correction = calls[1]["contents"][-1].parts[0].text
    assert "Play status" in correction and "select-playstat" in correction
    assert "complete corrected JSON response" in correction
    assert "unknown column ids" in calls[2]["contents"][-1].parts[0].text
    assert calls[0]["model"] == calls[1]["model"] == calls[2]["model"]
    assert summaries[-1]["success"] is not exhausted
    assert (summaries[-1]["validated_result_chars"] > 0) is not exhausted


# @source lagniappe/core/tools/ai/autofill.py::validate_submission
# @source lagniappe/core/properties/schema.py::SchemaFields.prepare_ai_field
# @source lagniappe/core/mixins/submitter.py::SubmitterMixin.ai_submission
# @matrix submission : ai validation preservation
# @matrix ai : validation
@pytest.mark.unit
def test_autofill_preserves_answers_and_applies_dates_for_actor(monkeypatch, game):
    page, actor = game
    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", None)
    saved = {"select-playstat": "interested", "checkbox-finished": False, "input-hours": 0}
    page.properties.submission.value = saved
    generated = {"select-playstat": "played", "checkbox-finished": True,
                 "input-hours": 100, "input-release": "2026-09-24"}
    validated = autofill.validate_submission(generated, entity=page, user=actor)
    assert page.submission == saved
    assert validated["checkbox-finished"] is False
    assert validated["input-hours"] == 0
    page.ai_submission(validated, actor=actor, preserve_existing=True)
    assert {key: page.submission[key] for key in saved} == saved
    assert page.properties.submission.fields["input-release"].value == datetime(
        2026, 9, 24, 7, tzinfo=timezone.utc
    )


# @source lagniappe/core/mixins/submitter.py::SubmitterMixin.ai_submission
# @source lagniappe/core/properties/schema.py::SchemaFields.prepare_ai_field
# @matrix submission : ai validation preservation
@pytest.mark.unit
def test_ai_submission_rejects_later_invalid_field_without_partial_changes(game):
    page, actor = game
    before = deepcopy(page.submission)
    with pytest.raises(ValueError, match="unknown column ids"):
        page.ai_submission({"input-publisher": "Annapurna",
                            "table-reviews": {"rows": [{"Outlet": "Example"}]}}, actor=actor)
    assert page.submission == before
    assert page.properties.submission.fields["select-playstat"].value == "interested"
    assert not page.properties.submission.fields["input-publisher"].is_set


# @source lagniappe/core/tools/ai/autofill.py::validate_submission
# @matrix ai : validation
@pytest.mark.unit
@pytest.mark.parametrize("payload", [[], None, "answer", {"submission": {"input-publisher": "Annapurna"}}])
def test_autofill_rejects_wrong_response_shape(game, payload):
    page, actor = game
    with pytest.raises(exceptions.AIException):
        autofill.validate_submission(payload, entity=page, user=actor)
    assert page.submission == {"select-playstat": "interested"}
