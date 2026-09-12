"""Deterministic form conversion rules and temporary before-values."""

from copy import deepcopy

import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.form_conversions import (
    MISSING,
    classify_changes,
    conversion_catalog,
    conversion_rule,
    convert_submission,
    convert_value,
)


def field(kind, **settings):
    schema = next(
        (
            item["schema"]
            for item in conversion_catalog()["types"]
            if item["value"] == kind
        ),
        {"type": kind},
    )
    return {"id": "answer", "title": "Answer", **schema, **settings}


# @matrix form-migration : capabilities no-submission-read
def test_capabilities_are_schema_only():
    catalog = conversion_catalog()
    assert catalog["version"] == 1
    assert catalog["rules"]["textarea"]["table"] == "ai"
    assert catalog["rules"]["textarea"]["todo"] == "ai"
    for source, replacements in {
        "checkbox": {"text", "radio"},
        "out": {"text", "bookmark"},
        "in": set(),
        "location": {"text"},
        "textarea": {"text", "table", "todo"},
        "radio": {"text", "select", "multiple"},
        "select": {"text", "radio", "multiple"},
        "multiple": {"text", "radio", "select"},
        "table": {"textarea", "todo"},
        "todo": {"textarea", "table"},
    }.items():
        assert {
            kind for kind, rule in catalog["rules"][source].items()
            if rule and kind != source
        } == replacements
    for source in ("checkbox", "number", "email", "tel", "date", "out", "bookmark"):
        assert catalog["rules"][source]["time"] is None
    assert catalog["rules"]["text"]["time"] == "scalar"
    for source in ("text", "number", "email", "tel", "date", "time"):
        assert {
            kind for kind, rule in catalog["rules"][source].items()
            if rule and kind != source
        } == (
            {"number", "email", "tel", "date", "time", "textarea"}
            if source == "text" else {"text", "textarea"}
        )
    assert catalog["rules"]["out"]["bookmark"] == "scalar"
    assert catalog["rules"]["text"]["in"] is None
    for source in ("signature", "html", "status"):
        assert all(
            conversion_rule(field(source), target["schema"]) is None
            for target in catalog["types"]
        )


# @matrix form-migration : schema-diff identity validation
def test_schema_diff_preserves_ids_and_rejects_unsupported_changes():
    source = field("radio", options=[{"value": "a", "label": "One"}])
    assert (
        classify_changes(
            [source],
            [
                {
                    **source,
                    "title": "Renamed",
                    "options": [
                        {"value": "a", "label": "Uno"},
                        {"value": "b", "label": "Two"},
                    ],
                }
            ],
        )
        == []
    )
    assert classify_changes([field("html")], []) == []
    converted = classify_changes([field("text")], [field("number")])
    assert converted[0]["id"] == "answer"
    assert converted[0]["source"]["input"] == "text"
    for before, after in [
        (field("textarea"), field("table")),
        (field("textarea"), field("todo")),
        (field("signature"), field("text")),
        (field("checkbox"), field("time")),
        (field("checkbox"), field("select")),
        (field("checkbox"), field("number")),
        (field("in"), field("text")),
        (field("text"), field("radio")),
        (field("text"), field("todo")),
        (field("text", id="name"), None),
    ]:
        with pytest.raises(ValidationError):
            classify_changes([before], [after] if after else [])


# @matrix form-migration : conversion invalid-value presence provider-free
@pytest.mark.parametrize(
    "source,target,value,expected",
    [
        ("text", "textarea", "  hello\r\nworld ", "  hello\r\nworld "),
        ("textarea", "text", "hello\r\nworld", "hello world"),
        ("text", "number", " 0 ", 0.0),
        ("text", "number", "1.25", 1.25),
        ("text", "number", "unknown", MISSING),
        ("text", "number", "NaN", MISSING),
        ("text", "number", "Infinity", MISSING),
        ("text", "number", None, MISSING),
        ("checkbox", "text", False, "False"),
        ("number", "text", 0, "0"),
        ("text", "email", "a@example.com", "a@example.com"),
        ("text", "email", "a@example.com trailing", MISSING),
        ("text", "tel", "+1 202-555-0123", "+12025550123"),
        ("text", "tel", "no phone", MISSING),
        ("text", "date", "2026-09-11", "2026-09-11T00:00:00+00:00"),
        ("text", "date", "2026-02-30", MISSING),
        ("text", "time", "23:45", "23:45"),
        ("text", "time", "25:45", MISSING),
        (
            "bookmark",
            "text",
            {"url": "https://example.com", "title": "Example"},
            "https://example.com",
        ),
        (
            "location",
            "text",
            {"name": "Office", "address": "123 Main"},
            "Office, 123 Main",
        ),
    ],
)
def test_scalar_conversions_and_invalid_values(source, target, value, expected):
    result, reason = convert_value(value, field(source), field(target))
    assert result is MISSING if expected is MISSING else result == expected
    if expected is MISSING:
        assert reason in {"unset", "invalid"}


# @matrix form-migration : conversion invalid-value presence nested-columns provider-free
def test_table_and_collection_conversions():
    options = [{"value": "yes-id", "label": "Yes"}, {"value": "no-id", "label": "No"}]
    radio, multi = field("radio", options=options), field("multiple", options=options)
    assert convert_value("no-id", radio, field("text"))[0] == "No"
    assert convert_value("yes-id", radio, multi)[0] == ["yes-id"]
    assert convert_value(["yes-id", "no-id"], multi, radio)[0] is MISSING
    assert convert_value(["yes-id", "no-id"], multi, field("text"))[0] == "Yes No"
    # Replacement is configured as a Select, then its final options/Multiple
    # setting determine the conversion when the form is saved.
    final_select = field(
        "select",
        multiple=True,
        options=[
            {"value": "checked", "label": "True"},
            {"value": "unchecked", "label": "False"},
        ],
    )
    changes = classify_changes(
        [field("radio", options=final_select["options"])], [final_select]
    )
    assert convert_submission({"answer": "unchecked"}, changes)[0] == {
        "answer": ["unchecked"]
    }
    todo = {
        "items": [
            {"text": "notes", "checked": False},
            {"text": "done", "checked": True},
        ],
    }
    assert convert_value(todo, field("todo"), field("textarea"))[0] == (
        "- [ ] notes\n- [x] done"
    )
    link = {"url": "https://example.com", "title": "Example", "description": "Kept"}
    assert convert_value(link, field("out"), field("bookmark"))[0] == link
    before = field(
        "table",
        columns=[
            field("text", id="quantity"),
            field("text", id="remove"),
            field("checkbox", id="keep"),
        ],
    )
    after = field(
        "table", columns=[field("number", id="quantity"), field("checkbox", id="keep")]
    )
    rows = {
        "rows": [
            {"quantity": "0", "remove": "old", "keep": False},
            {"quantity": "oops", "keep": True},
        ]
    }
    original = deepcopy(rows)
    assert convert_value(rows, before, after)[0] == {
        "rows": [{"quantity": 0.0, "keep": False}, {"keep": True}]
    }
    assert rows == original
    assert "old" in convert_value(rows, before, field("textarea"))[0]


# @matrix form-migration : notice preservation presence repeated-change
def test_submission_notice_preserves_first_values_and_unrelated_answers():
    first = classify_changes([field("text")], [field("number")])
    values, notice = convert_submission({"answer": "012", "unrelated": False}, first)
    assert values == {"answer": 12.0, "unrelated": False}
    assert notice["answer"]["value"] == "012"
    values, notice = convert_submission(
        values,
        classify_changes([field("number")], []),
        previous_notice=notice,
        generation=1,
    )
    assert values == {"unrelated": False}
    assert notice["answer"]["value"] == "012"
    assert notice["answer"]["generation"] == 0
    assert notice["answer"]["reason"] == "removed"
    assert convert_submission({}, first) == ({}, {})
    assert (
        convert_submission({"answer": "bad"}, first)[1]["answer"]["reason"] == "invalid"
    )
