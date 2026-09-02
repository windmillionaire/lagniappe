from io import BytesIO
import json
from types import SimpleNamespace
import zipfile

import pytest

from lagniappe.core.definitions import FileConsumerLimitError, LARGE_ASSET_BYTES
from lagniappe.core.tools.ai import (
    autofill,
    category,
    core as ai_core,
    dates,
    project,
    schema,
    summarize,
    text,
)
from lagniappe.core.tools.ai.guidelines import (
    FORM_ENTITY_BOUNDARIES,
    SUBMISSION_OUTPUT_REQUIREMENTS,
)
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.files.ooxml import (
    OOXMLExtractionResult,
    OOXMLTruncationReason,
)


DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _context_value(prompt, label):
    for block in prompt.context_blocks:
        if block["label"] == label:
            return block["value"]
    raise AssertionError(f"Missing prompt context block: {label}")


def _context_text(prompt, label):
    value = _context_value(prompt, label).strip()
    if value.startswith("```") and value.endswith("```"):
        return value.split("\n", 1)[1].rsplit("\n", 1)[0]
    return value


def _context_json(prompt, label):
    return json.loads(_context_text(prompt, label))


def _context_labels(prompt):
    return [block["label"] for block in prompt.context_blocks]


def _zip_bytes(parts):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in parts.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _docx_bytes():
    return _zip_bytes(
        {
            "word/document.xml": f"""
                <w:document xmlns:w="{WORD_NS}">
                  <w:body>
                    <w:p><w:r><w:t>Alpha paragraph</w:t></w:r></w:p>
                    <w:tbl>
                      <w:tr>
                        <w:tc><w:p><w:r><w:t>Left cell</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>Right cell</w:t></w:r></w:p></w:tc>
                      </w:tr>
                    </w:tbl>
                  </w:body>
                </w:document>
            """,
        }
    )


def _ooxml_summary_file(filename="source.docx", mimetype=DOCX_MIMETYPE):
    content = _docx_bytes()
    asset = SimpleNamespace(size=len(content), get=lambda: content)
    file = SimpleNamespace(
        filename=filename,
        mimetype=mimetype,
        properties=SimpleNamespace(
            file=SimpleNamespace(uri_to_ai=None),
            summarize=SimpleNamespace(
                status=None,
                enabled=None,
                search=None,
                complete=None,
                error=None,
            ),
        ),
        summary=None,
    )
    file.get_asset = lambda name: asset if name == "file" else None
    return file


# @matrix ai : attachments cache-prefix context output-format prompt service-tier tool-batching tools
@pytest.mark.unit
def test_prompt_tracks_context_output_examples_and_attachments():
    user = SimpleNamespace(email="owner@example.com")
    prompt = Prompt("System intro", user=user, type="unit prompt")
    prompt.add_context("page_info", {"alpha": 1})
    prompt.add_context("plain_note", "Use directly", quote=False)
    prompt.add_context("empty_value", None)
    prompt.add_instructions("  Follow the rules.  ")
    prompt.set_output_format("JSON", description="Return an object.")
    prompt.add_example({"ok": True}, title="Valid")
    prompt.enable_search()
    prompt.enable_tools("get_entity")

    inline = BytesIO(b"image-bytes")
    prompt.add_bytes(inline, "image/png")
    prompt.add_bytes(BytesIO(b"ignored"), "application/octet-stream")
    prompt.add_file(
        SimpleNamespace(
            properties=SimpleNamespace(
                file=SimpleNamespace(
                    uri_to_ai={
                        "uri": "gs://bucket/source.pdf",
                        "mime_type": "application/pdf",
                    },
                )
            ),
        )
    )
    prompt.add_file(
        SimpleNamespace(
            properties=SimpleNamespace(file=SimpleNamespace(uri_to_ai=None)),
        )
    )

    assert prompt.prompt_type == "unit prompt"
    assert prompt.model_tier == "primary"
    assert prompt.service_tier is None
    assert prompt.search is True
    assert prompt.tools == ["get_entity"]
    assert _context_json(prompt, "Page Info") == {"alpha": 1}
    assert _context_text(prompt, "Plain Note") == "Use directly"
    assert "Empty Value" not in _context_labels(prompt)
    assert prompt.instruction_blocks == [
        {"title": None, "content": "Follow the rules."},
        {
            "title": None,
            "content": (
                "### Tool Call Planning\n\n"
                "- Before each tool turn, identify all useful calls whose arguments "
                "are already known.\n"
                "- Request those independent calls together in the same turn, "
                "including every\n"
                "  applicable `get_guidelines` bundle.\n"
                "- Defer a call only when its arguments depend on an earlier tool "
                "result. Do not\n"
                "  add unnecessary calls merely to form a batch."
            ),
            "role": "tool_call_planning",
        },
    ]
    assert prompt.preview().count("### Tool Call Planning") == 1
    prompt.enable_tools("get_entity", "get_schema")
    assert prompt.preview().count("### Tool Call Planning") == 1
    assert prompt.output_format["type"] == "JSON"
    assert prompt.output_format["description"] == "Return an object."
    assert prompt.examples == [{"example": {"ok": True}, "title": "Valid"}]

    contents = ai_core.GenAI()._build_contents(prompt)
    assert contents[0] == prompt.build()
    assert contents[1].inline_data.mime_type == "image/png"
    assert contents[1].inline_data.data == b"image-bytes"
    assert contents[2].file_data.file_uri == "gs://bucket/source.pdf"
    assert contents[2].file_data.mime_type == "application/pdf"
    assert prompt.audit()["duplicate_headings"] == []

    prompt.set_instructions_before_context()
    reordered = prompt.build()
    assert reordered.index("## Instructions") < reordered.index("## Context")

    role_prompt = Prompt()
    role_prompt.add_context(
        "lagniappe_concepts",
        "### Old Heading\n\nFirst",
        quote=False,
        role="workspace_concepts",
        unique=True,
    )
    role_prompt.add_workspace_concepts("### New Heading\n\nSecond")
    role_prompt.add_preflight_checks("### Before Returning\n\n- First check")
    role_prompt.add_preflight_checks("### Before Returning\n\n- Replacement check")
    assert _context_text(role_prompt, "Lagniappe Concepts") == "Second"
    assert role_prompt.instruction_blocks == [
        {
            "title": None,
            "content": "### Before Returning\n\n- Replacement check",
            "role": "preflight_checks",
        }
    ]

    guarded_prompt = Prompt()
    guarded_prompt.enable_tools("get_entity")
    with pytest.raises(RuntimeError, match="Prompt.user"):
        _ = guarded_prompt.tools

    prompt.set_model_tier("utility")
    assert prompt.model_tier == "utility"
    with pytest.raises(ValueError, match="Model tier"):
        prompt.set_model_tier("tiny")


# @matrix ai : file-context output-format project-context prompt-builders search structured-output submission thinking tools
@pytest.mark.unit
def test_ai_prompt_builders_capture_product_context_and_tool_choices():
    user = SimpleNamespace(email="owner@example.com")
    category_prompt = category.category_creation_prompt("A customer directory")
    project_prompt = project.project_creation_prompt("A woodworking workflow")
    form_prompt = schema.form_generation_prompt("task", "Track measurements")
    schedule_prompt = dates.scheduling_prompt(
        mode="periodic", user_prompt="repeat every two weeks"
    )
    text_prompt = text.text_generation_prompt(
        "Rewrite this",
        {
            "user": user,
            "page_info": {"name": "Ada"},
            "selected_text": "old words",
        },
    )
    upload = BytesIO(b"image")
    upload.content_type = "image/png"
    create_upload = BytesIO(b"recipe-image")
    create_upload.content_type = "image/png"
    autofill_prompt = autofill.form_autofill_prompt(
        user=user,
        target={
            "kind": "page",
            "name": "Ada",
            "description": "Existing page",
        },
        category={
            "name": "Customers",
            "description": "Customer relationship records.",
        },
        form=SimpleNamespace(
            name="Customer Form",
            schema=[{"id": "input-name", "type": "input"}],
        ),
        submission={"input-name": ""},
        file=upload,
        attached_files=[
            {
                "hash": "hash:customer-notes",
                "filename": "customer-notes.pdf",
                "summary": "Ada prefers email follow-up.",
            }
        ],
    )
    create_autofill_prompt = autofill.form_autofill_prompt(
        user=user,
        target={
            "kind": "page",
            "name": "Pimento Mac & Cheese",
            "description": "Draft recipe",
        },
        category={
            "name": "Recipes",
            "description": "Recipes worth making again.",
        },
        form=SimpleNamespace(
            name="Recipe Form",
            schema=[{"id": "input-name", "type": "input"}],
        ),
        file=create_upload,
    )

    assert category_prompt.output_format["type"] == "JSON"
    assert category_prompt.thinking_budget == 1024
    assert [example["title"] for example in category_prompt.examples] == [
        "Homogeneous collection with default form",
        "Context category without default form",
    ]
    assert "form_schema" in category_prompt.examples[0]["example"]
    assert "form_schema" not in category_prompt.examples[1]["example"]
    assert "Do not generate a category default form by default" in (
        category_prompt.preview()
    )
    assert "collection scope / subject / action and evidence" in (
        category_prompt.preview()
    )
    assert project_prompt.output_format["type"] == "JSON"
    assert project_prompt.examples
    assert form_prompt.output_format["type"] == "JSON"
    assert form_prompt.thinking_budget == 1024
    assert form_prompt.model_tier == "primary"
    assert schedule_prompt.output_format["type"] == "JSON"
    assert schedule_prompt.thinking_budget == 0
    assert schedule_prompt.model_tier == "utility"
    assert schedule_prompt.examples
    assert category_prompt.model_tier == "primary"
    assert project_prompt.model_tier == "primary"

    assert text_prompt.search is True
    assert text_prompt.tools == [
        "search_entities",
        "get_page_file_list",
        "get_page_tasks",
        "get_file",
    ]
    assert text_prompt.output_format["type"] == "MARKDOWN"
    assert "never return HTML" in text_prompt.output_format["requirements"]
    assert text_prompt.model_tier == "primary"
    assert _context_text(text_prompt, "User Request") == "Rewrite this"
    assert _context_json(text_prompt, "Page Info") == {"name": "Ada"}
    assert _context_text(text_prompt, "Selected Text") == "old words"

    project_text_prompt = text.text_generation_prompt(
        "Draft a statement",
        {
            "user": user,
            "project_info": {"project_name": "Internship Search"},
        },
    )
    assert project_text_prompt.tools == ["search_entities"]
    assert _context_json(project_text_prompt, "Project Info") == {
        "project_name": "Internship Search"
    }

    assert autofill_prompt.search is True
    assert autofill_prompt.tools == ["get_file"]
    assert (
        autofill_prompt.max_tool_iterations
        == autofill.AUTOFILL_MAX_TOOL_ITERATIONS
        == 2
    )
    assert autofill_prompt.observability_contract == {
        "workflow": "autofill",
        "stage": "generation",
        "id": "form-autofill",
        "version": 3,
    }
    assert autofill_prompt.output_format["type"] == "JSON"
    assert (
        autofill_prompt.output_format["description"]
        == SUBMISSION_OUTPUT_REQUIREMENTS
    )
    assert autofill_prompt.output_format["requirements"]
    assert autofill_prompt.response_schema is None
    assert "### JSON Output Requirements" in autofill_prompt.preview()
    assert "### Submission Output Requirements" in autofill_prompt.preview()
    assert autofill_prompt.model_tier == "primary"
    assert autofill_prompt.bytes[0]["bytes"] == b"image"
    assert FORM_ENTITY_BOUNDARIES.strip() not in [
        block["content"] for block in autofill_prompt.instruction_blocks
    ]
    assert _context_text(autofill_prompt, "File Data")
    assert _context_text(autofill_prompt, "Form Name") == "Customer Form"
    assert _context_json(autofill_prompt, "Form Schema") == [
        {"id": "input-name", "type": "input"}
    ]
    assert _context_json(autofill_prompt, "Existing Submission") == {
        "input-name": ""
    }
    assert _context_json(autofill_prompt, "Target Record") == {
        "kind": "page",
        "name": "Ada",
        "description": "Existing page",
    }
    assert _context_json(autofill_prompt, "Category") == {
        "name": "Customers",
        "description": "Customer relationship records.",
    }
    assert _context_json(autofill_prompt, "Attached Files") == [
        {
            "hash": "hash:customer-notes",
            "filename": "customer-notes.pdf",
            "summary": "Ada prefers email follow-up.",
        }
    ]
    for unavailable_tool in (
        "search_entities",
        "get_entity",
        "get_page_details",
        "get_page_file_list",
        "get_page_tasks",
        "get_task_history",
        "get_category_details",
    ):
        assert unavailable_tool not in autofill_prompt.preview()

    assert create_autofill_prompt.tools is None
    assert create_autofill_prompt.max_tool_iterations is None
    assert create_autofill_prompt.search is True
    assert create_autofill_prompt.response_schema is None
    assert create_autofill_prompt.bytes[0]["bytes"] == b"recipe-image"
    assert "Page Id" not in _context_labels(create_autofill_prompt)
    assert _context_json(create_autofill_prompt, "Category") == {
        "name": "Recipes",
        "description": "Recipes worth making again.",
    }


# @matrix ai files pages tasks : attached-files autofill entity-specific partial-submission shared-context
@pytest.mark.unit
def test_autofill_prompt_data_keeps_attachment_context_entity_specific():
    user = SimpleNamespace(email="owner@example.com", is_authenticated=True)

    class Submission:
        def __init__(self, value):
            self.ai_value = value
            self.user = None

    class EvidenceFile:
        def __init__(self, key, filename, summary):
            self.key = key
            self.hash = key
            self.filename = filename
            self.summary = summary

        def allowed(self, action, user=None):
            return True

        def to_ai(self, user=None):
            return {
                "hash": f"hash:{self.hash}",
                "filename": self.filename,
                "summary": self.summary,
            }

    page_file = EvidenceFile(
        "assessment-file", "assessment.pdf", "Parcel 123 is assessed at $245,000."
    )
    task_file = EvidenceFile("tax-file", "tax-bill.pdf", None)
    category = SimpleNamespace(
        name="Properties",
        description="Property records and obligations.",
        allowed=lambda action, user=None: True,
    )
    form = SimpleNamespace(
        name="Assessment Form",
        schema=[{"id": "input-value", "type": "input"}],
    )
    page = SimpleNamespace(
        entity_kind="page",
        urlsafe_key="page-key",
        hash="page-key",
        key="page-db-key",
        name="Pettis Trust",
        description="Property assessment record",
        model=category,
        form=form,
        files=[page_file],
        properties=SimpleNamespace(
            submission=Submission({"input-value": ""}),
            document=SimpleNamespace(ai_value="Assessment notes"),
        ),
    )
    task = SimpleNamespace(
        entity_kind="task",
        urlsafe_key="task-key",
        hash="task-key",
        key="task-db-key",
        name="Record annual tax",
        description="Use the attached evidence",
        page=page,
        form=form,
        files=[task_file],
        properties=SimpleNamespace(
            submission=Submission({"input-value": ""}),
        ),
    )

    page_data = autofill.autofill_prompt_data(page, user)
    task_data = autofill.autofill_prompt_data(task, user)
    page_prompt = autofill.form_autofill_prompt(**page_data)
    task_prompt = autofill.form_autofill_prompt(**task_data)

    assert page_data["attached_files"] == [page_file.to_ai(user)]
    assert task_data["attached_files"] == [task_file.to_ai(user)]
    assert task_data["document"] == page_data["document"] == "Assessment notes"
    assert task_data["parent_page"] == {
        "name": "Pettis Trust",
        "description": "Property assessment record",
    }
    assert task_data["category"] == page_data["category"] == {
        "name": "Properties",
        "description": "Property records and obligations.",
    }
    assert _context_json(page_prompt, "Attached Files") == [
        page_file.to_ai(user)
    ]
    assert _context_json(task_prompt, "Attached Files") == [task_file.to_ai(user)]
    assert _context_json(task_prompt, "Parent Page") == task_data["parent_page"]
    assert _context_json(task_prompt, "Target Record") == {
        "kind": "task",
        "name": "Record annual tax",
        "description": "Use the attached evidence",
    }
    assert "Task History" not in _context_labels(task_prompt)
    assert "Completed Tasks" not in _context_labels(task_prompt)
    assert task_prompt.tools == page_prompt.tools == ["get_file"]
    assert page_file.to_ai(user) not in _context_json(task_prompt, "Attached Files")


# @matrix ai files : autofill complete failed pending summary-dependency
@pytest.mark.unit
def test_autofill_summary_dependencies_track_enabled_processing():
    user = SimpleNamespace(is_authenticated=True)

    class EvidenceFile:
        def __init__(self, key, *, enabled=True, complete=None, error=None):
            self.key = key
            self.hash = key
            self.properties = SimpleNamespace(
                summarize=SimpleNamespace(
                    enabled=enabled,
                    complete=complete,
                    error=error,
                )
            )

        def allowed(self, action, user=None):
            return True

    complete = EvidenceFile("complete", complete=True)
    pending = EvidenceFile("pending")
    failed = EvidenceFile("failed", error="page limit")
    disabled = EvidenceFile("disabled", enabled=False)
    target = SimpleNamespace(
        entity_kind="page",
        files=[complete, pending, failed, disabled],
    )

    dependencies = autofill.autofill_summary_dependencies(target, user)

    assert dependencies == {
        "complete": [complete],
        "pending": [pending],
        "failed": [failed],
    }


# @matrix ai : summary-fallback summary-prompt
# @matrix files : docx ooxml
@pytest.mark.unit
def test_ai_summary_generation_uses_docx_text_fallback(monkeypatch):
    generated_prompts = []

    def generate_content(prompt, *, validator=None):
        generated_prompts.append(prompt)
        result = "  Office summary.  "
        return validator(result) if validator else result

    monkeypatch.setattr(
        summarize, "ai_model", SimpleNamespace(generate_content=generate_content)
    )

    file = _ooxml_summary_file(filename="quarterly.docx")
    result = summarize.generate_summary(file)

    assert result.complete is True
    assert file.summary == "Office summary."
    assert generated_prompts[0].files == []
    extracted_text = _context_text(generated_prompts[0], "Extracted File Text")
    assert "quarterly.docx" in extracted_text
    assert "Alpha paragraph" in extracted_text
    assert "Left cell\tRight cell" in extracted_text


# @matrix ai : ooxml summary-prompt
@pytest.mark.unit
def test_ai_summary_generation_marks_partial_ooxml_context(monkeypatch):
    generated_prompts = []
    extraction_limits = []

    def generate_content(prompt, *, validator=None):
        generated_prompts.append(prompt)
        result = "Partial Office summary."
        return validator(result) if validator else result

    def extract(content, filename=None, mimetype=None, *, max_characters=None):
        extraction_limits.append(max_characters)
        return OOXMLExtractionResult(
            "x" * summarize.EXTRACTED_CONTEXT_LIMIT,
            OOXMLTruncationReason.ROWS,
        )

    monkeypatch.setattr(
        summarize, "ai_model", SimpleNamespace(generate_content=generate_content)
    )
    monkeypatch.setattr(summarize, "extract_ooxml", extract)

    file = _ooxml_summary_file(filename="large.xlsx")
    result = summarize.generate_summary(file)

    assert result.complete is True
    context = _context_text(generated_prompts[0], "Extracted File Text")
    assert len(context) <= summarize.EXTRACTED_CONTEXT_LIMIT
    assert context.endswith(
        "[Extracted text is partial because the worksheet row limit was reached.]"
    )
    assert extraction_limits == [
        summarize.EXTRACTED_CONTEXT_LIMIT
        - len(summarize._extracted_context_header("large.xlsx"))
    ]


# @pair ai:tools
@pytest.mark.unit
def test_prompt_rejects_oversized_inline_file_before_read():
    class OversizedUpload:
        filename = "oversized.pdf"
        size = LARGE_ASSET_BYTES + 1

        def seek(self, *_args):
            raise AssertionError("oversized prompt input must not be opened")

        def read(self):
            raise AssertionError("oversized prompt input must not be read")

    with pytest.raises(
        FileConsumerLimitError,
        match=r"oversized\.pdf is too large for AI autofill attachment",
    ):
        Prompt().add_bytes(OversizedUpload(), "application/pdf")


# @pair ai:summary-prompt
@pytest.mark.unit
def test_ai_summary_generation_rejects_oversized_ooxml_before_download():
    file = _ooxml_summary_file(filename="oversized.docx")
    asset = file.get_asset("file")
    asset.size = LARGE_ASSET_BYTES + 1
    asset.get = lambda: (_ for _ in ()).throw(
        AssertionError("oversized OOXML must not be downloaded")
    )

    result = summarize.generate_summary(file)

    assert result.complete is None
    assert "Could not extract text from oversized.docx" in result.error
