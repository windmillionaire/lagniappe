"""AI prompt for Ask tool reports."""

from lagniappe.core import exceptions

from .guidelines import (
    LAGNIAPPE_WORKSPACE_CONCEPTS,
)
from lagniappe.core.tools.files.html import render_markdown
from .reporting.contracts.actions import (
    READ_ONLY_CONTEXT_TOOLS,
)
from .reporting.proposals.repair import (
    generate_validated_proposal,
)
from .prompt import Prompt

ASK_MAX_TOOL_ITERATIONS = 50
ASK_READ_ONLY_CONTEXT_TOOLS = (
    *READ_ONLY_CONTEXT_TOOLS,
    "get_task_history",
    "get_filter_schema",
    "query_workspace_filter",
)

ASK_SOURCE_GUIDELINES = """
### Ask Source Priority

Use sources in this order:
1. User question: answer the specific question asked.
2. Read-only workspace tool results: pages, tasks, files, projects,
   categories, forms, people, and other entities found in Lagniappe.
3. Task history and file contents: use get_task_history and get_file when the
   answer depends on past completions, proof, summaries, extracted text, or
   original supported file bytes.
4. Web search: use it for current or outside-world information, and clearly
   distinguish outside research from workspace records.

Tool results are evidence. Do not cite or link internal entities unless prompt
context or a tool result provided the hash token, url, or name. If sources
conflict or the evidence is not strong enough for a direct answer, clearly say
what is uncertain.
"""

ASK_PREFLIGHT_CHECKS = """
### Before Returning

- Make sure the summary directly answers the user's question.
- Keep internal entity hash tokens out of the user-facing summary and
  answer_markdown. Use the corresponding human name and URL when available; if no
  human name is available, describe the entity generically rather than showing
  its hash token.
- If links, lists, or emphasis would help, include answer_markdown with clean
  Markdown and only use links backed by tool results or web search.
- Always return an empty actions array. Ask reads and answers; Create and
  Organize own workspace changes.
- Distinguish workspace evidence from outside-world information when both are
  used.
"""

ASK_OUTPUT_REQUIREMENTS = """
### Ask Report Output Requirements

Return a single JSON object only, with no markdown fences or commentary.

Shape:
{
  "summary": "short plain-text answer for lists and notifications",
  "answer_markdown": "optional Markdown answer for the report detail view",
  "confidence": 0.0,
  "actions": []
}

Answer rules:
- Put the direct answer in `summary`.
- When the answer includes links, lists, or emphasis, also include
  `answer_markdown` using ordinary Markdown.
- Hash tokens are internal references for tool calls. Never
  display them in `summary` or `answer_markdown`; use human names and URLs instead.
- Use links in `answer_markdown` when a tool result provides a `url` and `name`,
  or when citing an external source found by web search.
- Always return `actions` as an empty array. If the user requests workspace
  changes, answer what can be established and direct them to Create or Organize.
"""


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_ask_prompt_prioritizes_answers_and_exposes_read_tools
# @matrix ai-report : answer-only ask provider-validation structured-output
def ask_response_schema():
    """Return Ask's answer-only provider envelope."""
    properties = {
        "summary": {"type": "string"},
        "answer_markdown": {"type": "string"},
        "confidence": {"type": "number"},
        "actions": {
            "type": "array",
            "items": {"type": "object"},
            "maxItems": 0,
        },
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["summary", "confidence", "actions"],
        "propertyOrdering": list(properties),
        "additionalProperties": False,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::revise_ask_prompt
# @reason shared prompt composition is verified through public prompt builders
def _ask_prompt_base(report, user, intro, extra_contexts=()):
    prompt = Prompt(intro, user=user, type="ask report")
    prompt.enable_search()
    prompt.enable_tools(*ASK_READ_ONLY_CONTEXT_TOOLS)
    prompt.set_max_tool_iterations(ASK_MAX_TOOL_ITERATIONS)
    prompt.set_allowed_actions(())
    prompt.set_response_schema(ask_response_schema())
    prompt.add_output_contract("JSON", ASK_OUTPUT_REQUIREMENTS)
    prompt.add_context("user_question", report.instructions or "")
    for key, value, quote in extra_contexts:
        prompt.add_context(key, value, quote=quote)
    prompt.add_workspace_concepts(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(ASK_SOURCE_GUIDELINES)
    return prompt


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_ask_prompt_prioritizes_answers_and_exposes_read_tools
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
# @matrix ai-report : answer-only ask prompt search structured-filter tool-context workspace-tools
def ask_prompt(report, user):
    """Build the AI prompt used to answer an Ask report."""
    prompt = _ask_prompt_base(
        report,
        user,
        "You are the Lagniappe Ask tool. Answer the user's question using "
        "permitted workspace records and web search when useful. Return JSON "
        "only. Ask is read-only; always return an empty actions array.",
    )
    submitted_files = [
        {
            "id": file.hash,
            "filename": file.filename,
            "content_type": file.mimetype,
            "size": file.size,
            "summary": file.summary,
            "url": file.url,
        }
        for file in (report.input_files or [])
    ]
    if submitted_files:
        prompt.add_context("submitted_files", submitted_files)
    prompt.add_instructions(
        """
Answer the user's question directly in the top-level summary and always return
an empty actions array. When the answer mentions pages, tasks, files, or
external sources with URLs,
include `answer_markdown` with ordinary Markdown links so the report detail can
show clickable links after trusted server-side rendering.

Use workspace search for people, pages, tasks, projects, categories, forms, and
files mentioned in the question. Use get_page_file_list for files attached to a
relevant page, and use get_file when the answer may depend on summaries,
extracted text, or original supported file bytes. Large original files are not
attached automatically; only request include_original when the user explicitly
asks to inspect the original large document, audio, or video. If the user asks
for current or outside-world information, use web search and keep the answer
clear about what comes from the workspace versus outside research.

When submitted_files context is present, those files were attached directly to
this Ask report. Treat their ids as valid get_file references and use their
summaries or original content when relevant. They are read-only evidence for
the answer.

Use get_task_history when the question asks about past completions, last or
recent occurrences, frequency, average gaps, or proof for a recurring task.
First identify the relevant page and task, then load its history. History rows
are returned newest first and may include the name and description saved for
that completion, completed_on, submission values, and file hash tokens. Use
get_file on history-attached file hash tokens when the answer depends on the
original evidence or file contents.

Use get_filter_schema followed by query_workspace_filter when the question
requires finding or counting project tasks or category pages by structured
fields such as completion, due date, assignment, category membership, or form
submission values. Identify the parent project or category first. Treat every
returned record as evidence and do not infer records beyond the returned set;
if the result says it was truncated, state that limitation or run a narrower
query.

Treat list_workspace_resources as a compact map of available structure, not as
a closed list of possible answers. Use search_entities or get_entity when a
specific entity may answer the question. Tool results are evidence; do not cite
or link internal entities unless a tool result or prompt context provided the
hash token, url, or name.

When the user asks for workspace changes, answer any factual part of the
question and explain that Create handles new work while Organize handles
changes to existing workspace content. Do not design or return those changes.
        """,
        section_title="Ask report task",
    )
    prompt.add_preflight_checks(ASK_PREFLIGHT_CHECKS)
    return prompt


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_revise_ask_prompt_preserves_question_and_adds_review_context
# @matrix ai-report : ask context feedback proposal revision
def revise_ask_prompt(report, user, feedback):
    """Build the AI prompt used to revise an Ask report answer."""
    prompt = _ask_prompt_base(
        report,
        user,
        "You are the Lagniappe Ask revision tool. Revise the saved answer "
        "using the user's feedback. Return a complete JSON-only replacement "
        "response with an empty actions array.",
        extra_contexts=(
            ("user_feedback", feedback or "None provided.", True),
            ("current_response_json", report.proposal or {}, True),
        ),
    )
    prompt.add_instructions(
        """
The user reviewed the current Ask response and provided feedback. Update the
answer so it follows the feedback while preserving correct parts of the
existing response. Return a complete replacement response using the Ask report
shape; do not return a patch. Keep actions empty.
        """,
        section_title="Ask report revision task",
        role="revision_task",
        unique=True,
    )
    prompt.add_preflight_checks(ASK_PREFLIGHT_CHECKS)
    return prompt


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_repairs_unusable_answers
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
# @matrix ai-report : ask generate live-provider repair usable-answer validate
def generate_ask_report(prompt):
    """Generate and validate a usable Ask response."""
    return generate_validated_proposal(
        prompt,
        report_label="Ask",
        validator=validate_ask_response,
    )


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_validate_ask_response_requires_a_usable_answer[summary]
# @tests tests_unit/test_020b_ai_ask.py::test_validate_ask_response_requires_a_usable_answer[confidence]
# @tests tests_unit/test_020b_ai_ask.py::test_validate_ask_response_renders_answer_markdown
# @tests tests_unit/test_020b_ai_ask.py::test_validate_ask_response_requires_a_usable_answer[answer-html]
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_discards_workspace_actions
# @matrix ai-report : action-discard answer-only ask usable-answer validation
# @pairs editor:html-sanitization markdown:html-sanitization
def validate_ask_response(
    response,
    allowed_actions=None,
    allow_pending_submissions=True,
):
    """Validate answer fields and deterministically discard workspace actions."""
    if not isinstance(response, dict):
        raise exceptions.AIException("Ask response must be a JSON object.")
    response = {**response, "actions": []}
    issues = response.get("issues")
    if issues is None:
        response["issues"] = []
    elif not isinstance(issues, list) or any(
        not isinstance(issue, str) for issue in issues
    ):
        raise exceptions.AIException(
            "Ask response issues must be a list of strings when present."
        )

    summary = response.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise exceptions.AIException(
            "Ask response must include a non-empty summary answer."
        )

    confidence = response.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise exceptions.AIException(
            "Ask response confidence must be a number from 0 to 1."
        )

    answer_markdown = response.get("answer_markdown")
    if answer_markdown is not None and not isinstance(answer_markdown, str):
        raise exceptions.AIException(
            "Ask response answer_markdown must be a string when present."
        )
    if answer_markdown is not None:
        response["answer_html"] = render_markdown(answer_markdown)
        response.pop("answer_markdown", None)
    else:
        answer_html = response.get("answer_html")
        if answer_html is not None and not isinstance(answer_html, str):
            raise exceptions.AIException(
                "Ask response answer_html must be a string when present."
            )

    return response


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_ask_report_name_is_compact_and_marks_truncation
# @matrix ai-report : ask title-truncation
def ask_report_name(question):
    """Build a compact report title from an Ask question."""
    text = " ".join((question or "").split())
    if not text:
        return "Ask:"
    suffix = "..." if len(text) > 80 else ""
    return f"Ask: {text[:80]}{suffix}"
