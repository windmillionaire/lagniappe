"""Pure builder AI proposals preserve identities and never mutate source drafts."""

from copy import deepcopy

from bs4 import BeautifulSoup
import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.ai.form_draft import prepare_generated_changes
from lagniappe.core.tools.ai.schema import form_generation_prompt


def _draft():
    return {
        "schema": [
            {"id": "notes", "type": "input", "input": "text", "title": "Notes", "required": True},
            {"id": "choice", "type": "select", "title": "Choice", "multiple": True,
             "options": [{"value": "original", "label": "Old label"}]},
            {"id": "grid", "type": "table", "title": "Grid", "columns": [
                {"id": "cell", "type": "input", "input": "text", "title": "Old heading"},
            ]},
            {"id": "intro", "type": "html", "title": "Introduction"},
        ],
        "html_fields": {"intro": "<p>Original content</p>"},
    }


# @matrix forms ai : draft-generation stable-identity validation no-side-effects
@pytest.mark.unit
def test_generated_changes_patch_exact_identities_without_mutating_draft():
    draft = _draft()
    original = deepcopy(draft)
    result = {"operations": [
        {"op": "update_field", "field_id": "notes", "changes": {"title": "Instructions"}},
        {"op": "update_option", "field_id": "choice", "value": "original", "label": "New label"},
        {"op": "update_column", "field_id": "grid", "column_id": "cell", "title": "New heading"},
        {"op": "add_field", "field": {"id": "additional", "type": "textarea", "title": "Extra"}},
    ], "content_markdown": {"intro": "**Updated** content"}}
    raw = deepcopy(result)

    proposal = prepare_generated_changes(result, draft, form_type="task")

    assert draft == original
    assert result == raw
    assert proposal["operations"][:3] == result["operations"][:3]
    assert proposal["operations"][3] == {
        "op": "add_field",
        "field": {"id": "additional", "type": "textarea", "title": "Extra"},
    }
    assert proposal["html_fields"] == {"intro": "<p><strong>Updated</strong> content</p>"}


# @matrix forms ai : draft-generation stable-identity validation no-side-effects
@pytest.mark.unit
@pytest.mark.parametrize("operation", [
    {"op": "remove_field", "field_id": "notes"},
    {"op": "update_field", "field_id": "notes", "changes": {"type": "textarea"}},
    {"op": "update_field", "field_id": "notes", "changes": {"required": False}},
    {"op": "update_option", "field_id": "choice", "value": "new-value", "label": "New"},
    {"op": "update_column", "field_id": "grid", "column_id": "missing", "title": "New"},
    {"op": "add_field", "field": {"id": "notes", "type": "textarea"}},
    {"op": "add_field", "field": {"id": "unsupported", "type": "unknown"}},
    {"op": "add_field", "field": {"id": "bad-options", "type": "select", "options": [
        {"value": "same", "label": "One"}, {"value": "same", "label": "Two"},
    ]}},
    {"op": "add_field", "field": {"id": "raw", "type": "html", "html": "<p>Raw</p>"}},
    {"op": "add_field", "field": {"id": "html-a.b", "type": "html", "title": "Instructions"}},
    {"op": "add_field", "field": {"id": "new-grid", "type": "table", "columns": [
        {"id": "cell\"quoted", "type": "input", "title": "Cell"},
    ]}},
    {"op": "add_field", "field": {"id": "new-radio", "type": "radio", "options": [
        {"value": "value\"quoted", "label": "Choice"},
    ]}},
])
def test_generated_changes_reject_entire_invalid_proposal(operation):
    draft = _draft()
    original = deepcopy(draft)
    result = {"operations": [
        {"op": "update_field", "field_id": "notes", "changes": {"title": "Would change"}},
        operation,
    ]}
    raw = deepcopy(result)
    with pytest.raises((ValidationError, ValueError)):
        prepare_generated_changes(result, draft, form_type="task")
    assert draft == original
    assert result == raw


# @matrix forms ai : draft-generation stable-identity validation no-side-effects
@pytest.mark.unit
def test_generated_changes_preserve_noop_and_intentional_empty_html():
    draft = _draft()
    assert prepare_generated_changes({"operations": []}, draft, form_type="task") == {
        "operations": [], "html_fields": {},
    }
    proposal = prepare_generated_changes(
        {"operations": [], "content_markdown": {"intro": ""}}, draft, form_type="task",
    )
    assert proposal["html_fields"] == {"intro": ""}
    assert draft["html_fields"]["intro"] == "<p>Original content</p>"


# @source lagniappe/core/tools/files/html.py::render_markdown
# @matrix forms ai : draft-generation stable-identity validation no-side-effects
# @matrix form-html security : html-sanitization owned-image
@pytest.mark.unit
def test_generated_static_content_retains_only_known_images():
    url = "https://example.test/assets/original/image"
    local = "draft-image:local-one"
    proposal = prepare_generated_changes({
        "operations": [],
        "content_markdown": {"intro": (
            f"![Original]({url})\n\n![Local]({local})\n\n"
            "![Unknown](https://untrusted.example/tracker.png)\n\n"
            '<script>alert("bad")</script>'
        )},
    }, _draft(), form_type="task", image_sources={"intro": [(url, url), (local, local)]})
    html = proposal["html_fields"]["intro"]
    assert url in html
    assert local in html
    assert "untrusted.example" not in html
    assert "<script" not in html


# @source lagniappe/core/tools/files/html.py::render_markdown
# @matrix forms ai : draft-generation validation no-side-effects
# @matrix form-html security : html-sanitization owned-image
@pytest.mark.unit
@pytest.mark.parametrize("source", ["https://example.test/assets/original/image", "draft-image:local-one"])
@pytest.mark.parametrize(("style", "suffix"), [
    ('width: 50%; display: block; float: none; margin-left: auto; margin-right: 0', ''),
    ('width: 50%; display: block; float: none; margin-left: auto; margin-right: 0',
     '{width="50%" style="display:block;float:none;margin-left:auto;margin-right:0"}'),
    ('width: 70%; display: block; float: left; margin: 0 1em 1em 0', ''),
])
def test_generated_text_preserves_draft_image_layout(source, style, suffix):
    draft = _draft()
    draft["html_fields"]["intro"] = (
        '<p><strong>Original instruction</strong></p>'
        f'<img src="{source}" alt="Bookshelf" title="Original image" style="{style}" onclick="bad()">'
    )
    original = deepcopy(draft)
    proposal = prepare_generated_changes({
        "operations": [{"op": "update_field", "field_id": "notes", "changes": {
            "placeholder": "Enter a generated verification note",
        }}],
        "content_markdown": {"intro": f'**Generated instruction**\n\n![Image]({source}){suffix}'},
    }, draft, form_type="task", image_sources={"intro": [(source, source)]})

    content = BeautifulSoup(proposal["html_fields"]["intro"], "html.parser")
    assert content.get_text(" ", strip=True) == "Generated instruction"
    assert content.strong.string == "Generated instruction"
    assert len(content.find_all("img")) == 1
    assert content.img["src"] == source
    assert content.img["alt"] == "Bookshelf"
    assert content.img["title"] == "Original image"
    declarations = dict(part.strip().split(":", 1) for part in content.img["style"].split(";") if part.strip())
    expected = dict(part.strip().split(":", 1) for part in style.split(";") if part.strip())
    assert {key: value.strip() for key, value in declarations.items()} == {
        key: value.strip() for key, value in expected.items()
    }
    assert "onclick" not in content.img.attrs
    assert proposal["operations"][0]["changes"]["placeholder"] == "Enter a generated verification note"
    assert draft == original


# @source lagniappe/core/tools/ai/schema.py::form_generation_prompt
# @matrix ai : output-format prompt-builders thinking
@pytest.mark.unit
def test_draft_prompt_includes_live_schema_and_operation_contract():
    draft = _draft()
    prompt = form_generation_prompt("task", "Rename the selected option", draft=draft)
    context = "\n".join(block["value"] for block in prompt.context_blocks)
    instructions = "\n".join(str(block) for block in prompt.instruction_blocks)
    assert '"value": "original"' in context
    assert "Original content" in context
    assert "update_option" in instructions
    assert "content_markdown" in instructions
    assert "never a replacement schema array" in instructions
    assert "Non-empty Markdown content" not in instructions
    assert "empty string intentionally clears" in instructions
    assert "Nothing is saved" in prompt.intro
