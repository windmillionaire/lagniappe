"""AI prompt for Create tool reports."""

from lagniappe.core import exceptions

from .guidelines import (
    CONTEXT_USAGE_GUIDELINES,
    HTML_GENERATION_RULES,
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    REPORT_PREFLIGHT_CHECKS,
    REPORT_TASK_SCHEDULING_GUIDELINES,
)
from .reporting.contracts.actions import READ_ONLY_CONTEXT_TOOLS
from .reporting.contracts.permissions import (
    allowed_report_actions,
    permission_filtered_output_contract,
    report_action_permission_context,
    report_action_permission_instructions,
)
from .reporting.contracts.schema import report_proposal_response_schema
from .reporting.proposals.repair import (
    generate_validated_proposal,
)
from .prompt import Prompt

CREATE_MAX_TOOL_ITERATIONS = 50

CREATE_ACTION_TYPES = frozenset(
    {
        "create_form",
        "create_category",
        "create_project",
        "create_model_task",
        "create_page",
        "create_task",
        "needs_review",
    }
)

CREATE_OUTPUT_REQUIREMENTS = """
### Create Report Output Requirements

Return a single JSON object only, with no markdown fences or commentary.

Shape:
{
  "summary": "short user-facing summary",
  "confidence": 0.0,
  "actions": [
    {
      "id": "short_unique_id",
      "type": "create_page",
      "display_label": "short human action label",
      "reason": "why this action is proposed",
      "depends_on": ["earlier_action_id"],
      "data": {
        "name": "action-specific executable name",
        "description": "action-specific executable details"
      }
    }
  ]
}

Create rules:
- Return a proposal with at least one action. Do not answer only in prose.
- Use `needs_review` when the request cannot safely become deterministic
  workspace actions.
- Prefer reusable workspace structure when it helps future retrieval or repeat
  work: forms, categories, projects, model tasks, pages, tasks, page documents,
  and form submissions.
- Use existing workspace structure only when read-only tools show it is a close
  fit for the user's request.
- Create page document HTML when durable written content is useful.
- Use form schemas and submission objects only when structured fields add
  meaningful domain data beyond entity names, descriptions, and relationships.
- Category default forms are exceptional: include one only when the request or
  evidence unambiguously defines the category's pages as repeated instances of
  one type sharing a small stable schema. Otherwise create the category without
  a form. This does not prevent a specific page from using its own close-fitting
  page form.
- Do not include file attachment or file summary actions; Create reports do not
  have report-uploaded files.
- The data object is the executable payload. Do not leave data empty for
  create_* actions. Action display labels and reasons are display text only;
  copy required executable fields into data.
- Do not create a form with an empty schema. If you cannot identify at least
  one useful structured field, omit the create_form action or use needs_review.

Allowed action types:
- create_form
- create_category
- create_project
- create_model_task
- create_page
- create_task
- needs_review

Reference rules:
- Use action references only for entities created earlier in the same actions
  list.
- Reference earlier actions with "$action_id", "action:action_id",
  {"action": "action_id"}, or a data key ending in "_action".
- Use existing Lagniappe entity hash tokens only when a read-only tool returned
  that hash.
- When referencing an existing category, form, project, model task, page, or
  task by hash, also include the matching human display field when you know it:
  category_name, form_name, project_name, model_name, page_name, or task_name.

Common data shapes:
- create_form: {"name": string, "form_type": "page"|"task", "schema": [field_object, ...]}
- create_category: {"name": string, "description": string, "form": entity_or_action_ref}
- create_project: {"name": string, "description": string}
- create_model_task: {"name": string, "project": entity_or_action_ref, "form": entity_or_action_ref}
- create_page: {"name": string, "description": string, "category": entity_or_action_ref, "form": entity_or_action_ref, "submission": object, "document": html_string}
- create_task: {"name": string, "description": string, "page": entity_or_action_ref, "project": entity_or_action_ref, "model": entity_or_action_ref, "form": entity_or_action_ref, "submission": object, "due_date": "YYYY-MM-DD", "schedule": canonical_schedule_object}
- needs_review: {"note": string, "questions": [string]}
"""


# @testable false
# @covered-by lagniappe/core/tools/ai/create.py::create_prompt
# @covered-by lagniappe/core/tools/ai/create.py::revise_create_prompt
# @reason action filtering is observed through the public Create prompt builders
def _create_allowed_actions(user):
    return tuple(
        action
        for action in allowed_report_actions(user)
        if action in CREATE_ACTION_TYPES
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/create.py::create_prompt
# @covered-by lagniappe/core/tools/ai/create.py::revise_create_prompt
# @reason shared prompt composition is verified through public prompt builders
def _create_prompt_base(report, user, intro, extra_contexts=()):
    allowed_actions = _create_allowed_actions(user)
    prompt = Prompt(intro, user=user, type="create report")
    prompt.enable_search()
    prompt.enable_tools(*READ_ONLY_CONTEXT_TOOLS)
    prompt.set_max_tool_iterations(CREATE_MAX_TOOL_ITERATIONS)
    prompt.set_allowed_actions(allowed_actions)
    prompt.set_response_schema(report_proposal_response_schema(allowed_actions))
    prompt.add_output_contract(
        "JSON",
        permission_filtered_output_contract(
            CREATE_OUTPUT_REQUIREMENTS,
            allowed_actions,
        ),
    )
    prompt.add_context("user_request", report.instructions or "")
    prompt.add_context(
        "report_action_permissions",
        report_action_permission_context(user, allowed_actions),
    )
    for key, value, quote in extra_contexts:
        prompt.add_context(key, value, quote=quote)
    prompt.add_workspace_concepts(LAGNIAPPE_WORKSPACE_CONCEPTS)
    prompt.add_instructions(CONTEXT_USAGE_GUIDELINES)
    prompt.add_instructions(REPORT_TASK_SCHEDULING_GUIDELINES)
    prompt.add_instructions(
        report_action_permission_instructions(),
        section_title="Report action permissions",
        role="action_permissions",
        unique=True,
    )
    prompt.add_instructions(HTML_GENERATION_RULES)
    prompt.add_instructions(
        """
Use read-only tools to understand existing workspace structure before proposing
new entities. Call list_workspace_resources early, then use search_entities or
get_entity when the user's request may overlap existing pages, tasks, projects,
categories, forms, or files. Use get_schema for one likely form-bearing entity
before writing a submission object.

Call get_guidelines whenever detailed rules would help shape safe action data:
category, project, page_form, task_form, form_autofill, page_document, or
report_actions. Keep using the Create report JSON action shape after reading
guidelines.

Return a saved proposal only. Do not imply the work has already been performed.
The deterministic report runner will validate permissions and execute the saved
action list later if the user chooses to run it.
        """,
        section_title="Create report task",
    )
    return prompt


# @testable true
# @tests tests_unit/test_020d_ai_report_prompts.py::test_create_prompt_builds_creation_proposal_without_file_actions
# @matrix ai-report : actions create prompt search tools
def create_prompt(report, user):
    """Build the AI prompt used to create a Create report proposal."""
    prompt = _create_prompt_base(
        report,
        user,
        "You are the Lagniappe Create tool. Convert the user's request into a "
        "JSON-only proposal for deterministic workspace creation. Do not "
        "execute actions or claim actions have been performed.",
    )
    prompt.add_preflight_checks(REPORT_PREFLIGHT_CHECKS)
    return prompt


# @testable true
# @tests tests_unit/test_020d_ai_report_prompts.py::test_revise_create_prompt_includes_feedback_and_current_proposal
# @matrix ai-report : context create feedback proposal revision
def revise_create_prompt(report, user, feedback):
    """Build the AI prompt used to revise a Create report proposal."""
    prompt = _create_prompt_base(
        report,
        user,
        "You are the Lagniappe Create revision tool. Revise the saved proposal "
        "using the user's feedback and return a complete JSON-only replacement "
        "proposal. Do not execute actions or claim actions have been performed.",
        extra_contexts=(
            ("user_feedback", feedback or "None provided.", True),
            ("current_proposal_json", report.proposal or {}, True),
        ),
    )
    prompt.add_instructions(
        """
The user reviewed the current proposal and provided feedback. Update the
proposal so it follows the feedback while preserving correct parts of the
existing plan. Return a complete replacement proposal; do not return patches or
partial actions.
        """,
        section_title="Create report revision task",
        role="revision_task",
        unique=True,
    )
    prompt.add_preflight_checks(REPORT_PREFLIGHT_CHECKS)
    return prompt


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_create_report_validates_non_empty_actions
# @matrix ai-report : create generate validate
def generate_create_report(prompt):
    """Generate and validate a Create report proposal."""
    proposal = generate_validated_proposal(prompt, report_label="Create")
    if not proposal.get("actions"):
        raise exceptions.AIException("Create report must include at least one action.")
    return proposal
