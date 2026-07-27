"""AI prompt for Ask tool reports."""

from lagniappe.core import exceptions

from .guidelines import (
    HTML_GENERATION_RULES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
)
from .organize import (
    READ_ONLY_CONTEXT_TOOLS,
    allowed_report_actions,
    permission_filtered_output_contract,
    report_proposal_response_schema,
    report_action_permission_context,
    report_action_permission_instructions,
    generate_validated_proposal,
    validate_proposal,
)
from .prompt import Prompt

ASK_MAX_TOOL_ITERATIONS = 50
ASK_READ_ONLY_CONTEXT_TOOLS = (
    *READ_ONLY_CONTEXT_TOOLS,
    "get_task_history",
    "get_filter_schema",
    "query_workspace_filter",
)
ASK_ACTION_TYPES = frozenset(
    {
        "create_form",
        "create_category",
        "create_project",
        "create_model_task",
        "create_page",
        "create_task",
        "add_form_to_page",
        "add_category",
        "move_page",
        "move_task",
        "move_file",
        "rename_entity",
        "update_form_schema",
        "update_submission_fields",
        "delete_page",
        "skip",
        "needs_review",
    }
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
conflict or the evidence is not strong enough for a direct answer, say what is
uncertain and use needs_review only when a human decision or follow-up
workspace action is actually useful.
"""

ASK_PREFLIGHT_CHECKS = """
### Before Returning

- Make sure the summary directly answers the user's question.
- Keep internal entity hash tokens out of the user-facing summary and
  answer_html. Use the corresponding human name and URL when available; if no
  human name is available, describe the entity generically rather than showing
  its hash token.
- Describe follow-up actions as proposed changes that would or could happen,
  never as guaranteed future changes.
- If links, lists, or emphasis would help, include answer_html with clean
  semantic HTML and only use links backed by tool results or web search.
- Keep actions empty when the answer does not need workspace follow-up.
- If actions are included, make sure they are useful follow-up work, not merely
  a way to answer the question.
- Do not propose file attachment actions; Ask can read and link files, but it
  does not organize uploaded files into the workspace.
- Treat delete_page as a manual cleanup suggestion; after execution, the report
  result will show normal delete controls rather than letting the runner delete
  pages.
- Make sure every existing entity hash token used in an action came from prompt
  context or a read-only tool result.
- Make sure every action `type` exactly matches one value in the Report Action
  Permissions allowed_actions list; do not invent aliases or shortened names.
- Make sure every action reference points to an earlier action in the same
  proposal.
- Do not invent due_date values; only use exact dates supplied by the user.
- Distinguish workspace evidence from outside-world information when both are
  used.
"""

ASK_OUTPUT_REQUIREMENTS = """
### Ask Report Output Requirements

Return a single JSON object only, with no markdown fences or commentary.

Shape:
{
  "summary": "short plain-text answer for lists and notifications",
  "answer_html": "optional clean HTML answer for the report detail view",
  "confidence": 0.0,
  "actions": []
}

Answer rules:
- Put the direct answer in `summary`.
- When the answer includes links, lists, or emphasis, also include
  `answer_html` using clean semantic HTML.
- Hash tokens are internal references for tool calls and action data. Never
  display them in `summary` or `answer_html`; use human names and URLs instead.
- Describe unexecuted follow-up actions conditionally (for example, "would
  move"), not as guaranteed future changes.
- Use links in `answer_html` when a tool result provides a `url` and `name`,
  or when citing an external source found by web search.
- If no workspace change is useful, return an empty `actions` array.
- If follow-up work is useful, include ordered actions using the report action
  shapes below.

Allowed action types:
- create_form
- create_category
- create_project
- create_model_task
- create_page
- create_task
- add_form_to_page
- add_category
- move_page
- move_task
- move_file
- rename_entity
- update_form_schema
- update_submission_fields
- delete_page
- skip
- needs_review

Reference rules:
- Use action references only for entities created earlier in the same actions
  list.
- Reference earlier actions with "$action_id", "action:action_id",
  {"action": "action_id"}, or a data key ending in "_action".
- Use existing Lagniappe entity hash tokens only when a read-only tool returned
  that hash.
- Use get_page_file_list to discover existing files attached to a page. For
  move_file, copy the returned file hash into data.file, include exactly one
  source page/task reference and exactly one target page/task reference, and
  include display_name or file_name when known so the proposal is readable.
- Ask follow-up actions do not attach files. Link to files in answer_html when
  tool results provide URLs.
- Do not create a form with an empty schema. If you cannot identify at least
  one useful structured field, omit the create_form action or use needs_review.

Common data shapes:
- create_form: {"name": string, "form_type": "page"|"task", "schema": [field_object, ...]}
- create_category: {"name": string, "description": string, "form": entity_or_action_ref}
- create_project: {"name": string, "description": string}
- create_model_task: {"name": string, "project": entity_or_action_ref, "form": entity_or_action_ref}
- create_page: {"name": string, "description": string, "category": entity_or_action_ref, "form": entity_or_action_ref, "submission": object, "document": html_string}
- create_task: {"name": string, "description": string, "page": entity_or_action_ref, "project": entity_or_action_ref, "model": entity_or_action_ref, "form": entity_or_action_ref, "submission": object, "due_date": "YYYY-MM-DD"}
- add_form_to_page: {"page": entity_ref, "form": entity_or_action_ref}
- add_category: {"page": entity_ref, "category": entity_ref}
- move_page: {"page": entity_ref, "category": entity_ref}
- move_task: {"task": entity_ref, "to_page": entity_ref}
- move_file: {"file": entity_ref, "from_page": entity_ref, "from_task": entity_ref, "to_page": entity_ref, "to_task": entity_ref}
- rename_entity: {"entity": entity_ref, "name": string}
- update_form_schema: {"form": entity_ref, "operations": [{"op": "add_field", "field": object} or {"op": "add_select_option", "schema_id": string, "option": {"value": string, "label": string}}]}
- update_submission_fields: {"updates": [{"page": entity_ref, "schema_id": string, "new_value": any} or {"task": entity_ref, "schema_id": string, "new_value": any}]}
- delete_page: {"page": entity_ref}
- skip: {"note": string}
- needs_review: {"note": string, "questions": [string]}
"""


# @testable false
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::revise_ask_prompt
# @reason action filtering is observed through public Ask prompt builders
def _ask_allowed_actions(user):
    return tuple(
        action for action in allowed_report_actions(user) if action in ASK_ACTION_TYPES
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::revise_ask_prompt
# @reason shared prompt composition is verified through public prompt builders
def _ask_prompt_base(report, user, intro, extra_contexts=()):
    allowed_actions = _ask_allowed_actions(user)
    prompt = Prompt(intro, user=user, type="ask report")
    prompt.enable_search()
    prompt.enable_tools(*ASK_READ_ONLY_CONTEXT_TOOLS)
    prompt.set_max_tool_iterations(ASK_MAX_TOOL_ITERATIONS)
    prompt.set_allowed_actions(allowed_actions)
    prompt.set_response_schema(
        report_proposal_response_schema(
            allowed_actions,
            allow_answer_html=True,
        )
    )
    prompt.add_output_contract(
        "JSON",
        permission_filtered_output_contract(ASK_OUTPUT_REQUIREMENTS, allowed_actions),
    )
    prompt.add_context("user_question", report.instructions or "")
    prompt.add_context(
        "report_action_permissions",
        report_action_permission_context(user, allowed_actions),
    )
    for key, value, quote in extra_contexts:
        prompt.add_context(key, value, quote=quote)
    prompt.add_workspace_concepts(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(ASK_SOURCE_GUIDELINES)
    prompt.add_instructions(
        report_action_permission_instructions(),
        section_title="Report action permissions",
        role="action_permissions",
        unique=True,
    )
    prompt.add_instructions(HTML_GENERATION_RULES)
    return prompt


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_ask_prompt_prioritizes_answers_and_exposes_read_tools
# @features ai-report
# @dimensions ask prompt search tool-context actions
def ask_prompt(report, user):
    """Build the AI prompt used to answer an Ask report."""
    prompt = _ask_prompt_base(
        report,
        user,
        "You are the Lagniappe Ask tool. Answer the user's question using "
        "permitted workspace records and web search when useful. Return JSON "
        "only. Do not execute mutations or claim actions were performed.",
    )
    prompt.add_instructions(
        """
Answer the user's question directly in the top-level summary. If the question
can be answered without changing the workspace, return an empty actions array.
When the answer mentions pages, tasks, files, or external sources with URLs,
include `answer_html` with appropriate anchor tags so the report detail can
show clickable links.

Use workspace search for people, pages, tasks, projects, categories, forms, and
files mentioned in the question. Use get_page_file_list for files attached to a
relevant page, and use get_file when the answer may depend on summaries,
extracted text, or original supported file bytes. Large original files are not
attached automatically; only request include_original when the user explicitly
asks to inspect the original large document, audio, or video. If the user asks
for current or outside-world information, use web search and keep the answer
clear about what comes from the workspace versus outside research.

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

Use get_schema only when a follow-up action needs a submission object for a
specific form, page, task, or model task. Use get_form_instances when a
follow-up action should patch exact submission fields across pages or tasks
that share a form.

If the answer naturally implies follow-up work, you may include deterministic
proposal actions using the action shape described in the output format. Prefer
creating a task on an existing relevant page, project, or model task. Do not
include or invent due_date values unless the user explicitly provides an
exact date. Ask follow-up actions should not attach files or record completed
evidence; use the file-organization workflow when uploaded files need to be
saved or classified.

When a follow-up edit changes existing workspace data, use exact reviewed
actions: add_category, move_page, move_task, move_file, rename_entity,
update_submission_fields, or update_form_schema.
For batch submission updates, list every affected page/task id, schema_id, and
new_value explicitly; never ask the runner to infer "all matching" records.
Call get_guidelines("schema_evolution") before proposing update_form_schema.

Use delete_page only as a manual cleanup suggestion for specific existing pages,
usually after move_file actions relocate the useful files elsewhere. The runner
will not delete pages automatically; the report result shows normal delete
controls so the user gets the usual confirmation, permissions, and cascade
behavior.

Use needs_review when the safe answer depends on ambiguous identity matches,
conflicting records, missing evidence, or a human decision. Never create actions
just to answer a question; actions are only for useful follow-up.
        """,
        section_title="Ask report task",
    )
    prompt.add_preflight_checks(ASK_PREFLIGHT_CHECKS)
    return prompt


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_revise_ask_prompt_preserves_question_and_adds_review_context
# @features ai-report
# @dimensions ask revision feedback proposal context
def revise_ask_prompt(report, user, feedback):
    """Build the AI prompt used to revise an Ask report answer or proposal."""
    prompt = _ask_prompt_base(
        report,
        user,
        "You are the Lagniappe Ask revision tool. Revise the saved answer and "
        "optional action proposal using the user's feedback. Return a complete "
        "JSON-only replacement response. Do not execute actions or claim "
        "actions have been performed.",
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
shape; do not return patches or partial actions.

If follow-up work remains useful, include deterministic proposal actions. If
the revised answer no longer needs workspace changes, return an empty actions
array.
        """,
        section_title="Ask report revision task",
        role="revision_task",
        unique=True,
    )
    prompt.add_preflight_checks(ASK_PREFLIGHT_CHECKS)
    return prompt


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_repairs_unusable_answers
# @features ai-report
# @dimensions ask generate validate repair usable-answer
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
# @tests tests_unit/test_020b_ai_ask.py::test_validate_ask_response_requires_a_usable_answer[answer-html]
# @features ai-report
# @dimensions ask validation usable-answer
def validate_ask_response(
    response,
    allowed_actions=None,
    allow_pending_submissions=True,
):
    """Validate answer fields and deterministic actions in an Ask response."""
    response = validate_proposal(
        response,
        allowed_actions=allowed_actions,
        allow_pending_submissions=allow_pending_submissions,
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

    answer_html = response.get("answer_html")
    if answer_html is not None and not isinstance(answer_html, str):
        raise exceptions.AIException(
            "Ask response answer_html must be a string when present."
        )

    return response


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_complete_ask_report_owns_prompt_generation_and_report_state
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
# @features ai-report
# @dimensions ask pipeline create revision status live-provider corpus workspace-tools usable-answer structured-filter
def complete_ask_report(report, user, feedback=None, generate=None):
    """Build, generate, validate, and apply one Ask response to ``report``."""
    prompt = (
        revise_ask_prompt(report, user, feedback)
        if feedback is not None
        else ask_prompt(report, user)
    )
    response = (generate or generate_ask_report)(prompt)
    status = "ready" if response.get("actions") else "complete"
    report.properties.process.set_proposal(response, status=status)
    return response


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_ask_report_name_is_compact_and_marks_truncation
# @features ai-report
# @dimensions ask title-truncation
def ask_report_name(question):
    """Build a compact report title from an Ask question."""
    text = " ".join((question or "").split())
    if not text:
        return "Ask:"
    suffix = "..." if len(text) > 80 else ""
    return f"Ask: {text[:80]}{suffix}"
