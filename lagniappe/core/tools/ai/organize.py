"""AI prompt orchestration and compatibility exports for Organize reports."""

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities

from .core import ai_model
from .debug import ai_debug
from .guidelines import (
    LAGNIAPPE_WORKSPACE_CONCEPTS,
    ORGANIZE_PLANNING_ACTIONS,
    ORGANIZE_PLANNING_CONCEPTS,
    ORGANIZE_PLANNING_OUTPUT,
    ORGANIZE_PLANNING_POLICY,
    ORGANIZE_PLANNING_PREFLIGHT,
    ORGANIZE_PLANNING_TOOLS,
    SCHEMA_TYPE_GUIDELINES,
)
from .prompt import Prompt
from .references import hash_reference
from .summarize import generate_summary
from .reporting.contracts import (
    ACTION_ORDER,
    ALLOWED_ACTIONS,
    READ_ONLY_CONTEXT_TOOLS,
    REPORT_ACTION_DATA_CONTRACTS,
    allowed_report_actions,
    permission_filtered_output_contract,
    report_action_permission_context,
    report_action_permission_instructions,
    report_proposal_response_schema,
)
from .reporting.organize_completion import (
    ORGANIZE_SUBMISSION_COMPLETION_RULES,
    ORGANIZE_SUBMISSION_OUTPUT_REQUIREMENTS,
    OVERSIZED_REPORT_SUMMARY,
    _report_file_summary_warning,
    complete_organize_submissions,
    organize_submission_completion_prompt,
    summarize_report_input_files,
    validate_organize_submission_results,
)
from .reporting.proposals import (
    ENTITY_PAIR_ACTION_REFERENCES,
    _proposal_debug_summary,
    generate_validated_proposal,
    skip_proposal_actions,
    toggle_proposal_action_indexes,
    toggle_proposal_action_skip,
    validate_or_repair_proposal,
    validate_proposal,
)

# Stable compatibility surface while implementations live in ai.reporting.
__all__ = (
    "ACTION_ORDER",
    "ALLOWED_ACTIONS",
    "ENTITY_PAIR_ACTION_REFERENCES",
    "Entities",
    "ORGANIZE_ACTION_TYPES",
    "ORGANIZE_MAX_TOOL_FILE_PARTS_PER_TURN",
    "ORGANIZE_MAX_TOOL_ITERATIONS",
    "ORGANIZE_SUBMISSION_COMPLETION_RULES",
    "ORGANIZE_SUBMISSION_OUTPUT_REQUIREMENTS",
    "OVERSIZED_REPORT_SUMMARY",
    "READ_ONLY_CONTEXT_TOOLS",
    "REPORT_ACTION_DATA_CONTRACTS",
    "SCHEMA_TYPE_GUIDELINES",
    "allowed_report_actions",
    "complete_organize_submissions",
    "exceptions",
    "generate_organize_plan",
    "generate_organize_report",
    "generate_summary",
    "generate_validated_proposal",
    "organize_prompt",
    "organize_submission_completion_prompt",
    "permission_filtered_output_contract",
    "report_action_permission_context",
    "report_action_permission_instructions",
    "report_proposal_response_schema",
    "revise_organize_prompt",
    "skip_proposal_actions",
    "summarize_report_input_files",
    "toggle_proposal_action_indexes",
    "toggle_proposal_action_skip",
    "validate_or_repair_proposal",
    "validate_organize_submission_results",
    "validate_proposal",
)

ORGANIZE_MAX_TOOL_ITERATIONS = 50
ORGANIZE_MAX_TOOL_FILE_PARTS_PER_TURN = 2

ORGANIZE_ACTION_TYPES = frozenset(
    {
        "create_form",
        "create_category",
        "create_project",
        "create_model_task",
        "create_page",
        "create_task",
        "add_form_to_page",
        "add_category",
        "update_form_schema",
        "attach_file_to_page",
        "attach_file_to_task",
        "delete_page",
        "skip",
        "needs_review",
    }
)


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/organize.py::revise_organize_prompt
# @reason Organize action filtering is observed through public prompt tests
def _organize_allowed_actions(user):
    return tuple(
        action
        for action in allowed_report_actions(user)
        if action in ORGANIZE_ACTION_TYPES
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/organize.py::revise_organize_prompt
# @reason compact Organize permissions are verified through prompt tests
def _organize_action_permission_context(user, allowed_actions):
    context = report_action_permission_context(user, allowed_actions)
    capabilities = context.get("capabilities") or {}
    context["capabilities"] = {
        key: value
        for key, value in capabilities.items()
        if key
        not in {
            "can_move_pages",
            "can_move_tasks",
            "can_move_files",
            "can_rename_entities",
            "can_update_submissions",
        }
    }
    if "add_category" in set(allowed_actions or ()):
        context["capabilities"]["can_add_page_categories"] = True
    return context


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_organize_prompt_includes_files_tools_instructions_and_high_limit
# @features ai-report
# @dimensions prompt files tools iteration-limit
def organize_prompt(report, user, retrieval_context=None):
    """Build the AI prompt used to create an organize report proposal."""
    prompt = _organize_prompt_base(
        report,
        user,
        "You are the Lagniappe Organize tool. Create a JSON-only proposal report; "
        "do not execute actions or claim actions have been performed.",
        retrieval_context=retrieval_context,
    )
    prompt.add_instructions(
        """
Return a proposal only. Do not imply the work has already been performed, and
do not produce a final entity outside the action list. The report runner will
validate permissions and execute the saved action list later if the user chooses
to run it.
        """,
        section_title="Organize report task",
    )
    prompt.add_preflight_checks(ORGANIZE_PLANNING_PREFLIGHT)

    return prompt


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_revise_organize_prompt_includes_feedback_and_current_proposal
# @features ai-report
# @dimensions revision feedback proposal context
def revise_organize_prompt(report, user, feedback, retrieval_context=None):
    """Build the AI prompt used to revise an organize report proposal."""
    prompt = _organize_prompt_base(
        report,
        user,
        "You are the Lagniappe Organize revision tool. Revise the saved "
        "proposal using the user's feedback and return a complete JSON-only "
        "replacement proposal. Do not execute actions or claim actions have "
        "been performed.",
        extra_contexts=(
            ("user_feedback", feedback or "None provided.", True),
            ("current_proposal_json", report.proposal or {}, True),
        ),
        retrieval_context=retrieval_context,
    )
    prompt.add_instructions(
        """
The user reviewed the current proposal and provided feedback. Update the
proposal so it follows the feedback while preserving correct parts of the
existing plan. Return a complete replacement proposal using the same organize
action schema; do not return patches or partial actions.

If the feedback changes classification, reconsider category/form/project/model
task choices. Prefer an existing matching form/category/project/model task when
one is a close conceptual fit; otherwise propose creating the needed structure
before creating pages or tasks that depend on it.

Do not preserve or generate data.submission. Select the right form and assign
the exact supporting files; the submission completion stage will rebuild form
data from the revised structure and summaries.

References in current_proposal_json may already be executable stored ids.
Preserve those references exactly when keeping an existing page/task/form/file;
do not add a hash: prefix to an existing long id.
        """,
        section_title="Organize report revision task",
        role="revision_task",
        unique=True,
    )
    prompt.add_preflight_checks(ORGANIZE_PLANNING_PREFLIGHT)

    return prompt


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/organize.py::revise_organize_prompt
# @reason prompt section composition is verified by the public prompt builders
def _organize_prompt_base(
    report,
    user,
    intro,
    extra_contexts=(),
    retrieval_context=None,
):
    allowed_actions = _organize_allowed_actions(user)
    prompt = Prompt(intro, user=user, type="organize report")
    prompt.set_instructions_before_context()
    # Leave thinking unset so each primary model uses its native default; a raw
    # token budget can constrain Gemini 3 and makes model A/B tests less comparable.
    prompt.enable_tools(*READ_ONLY_CONTEXT_TOOLS)
    prompt.set_max_tool_iterations(ORGANIZE_MAX_TOOL_ITERATIONS)
    prompt.set_max_tool_file_parts_per_turn(ORGANIZE_MAX_TOOL_FILE_PARTS_PER_TURN)
    prompt.set_allowed_actions(allowed_actions)
    prompt.set_response_schema(
        report_proposal_response_schema(
            allowed_actions,
            require_issues=True,
            include_submission_fields=False,
        )
    )
    prompt.add_output_contract(
        "JSON",
        permission_filtered_output_contract(
            ORGANIZE_PLANNING_OUTPUT,
            allowed_actions,
        ),
        include_requirements=False,
    )
    prompt.add_workspace_concepts(
        (f"{LAGNIAPPE_WORKSPACE_CONCEPTS}\n\n{ORGANIZE_PLANNING_CONCEPTS.strip()}")
    )
    prompt.add_context("user_instructions", report.instructions or "None provided.")
    prompt.add_context(
        "report_input_files",
        _input_file_context(
            report,
            user=user,
            retrieval_context=retrieval_context,
        ),
    )
    prompt.add_context(
        "report_action_permissions",
        _organize_action_permission_context(user, allowed_actions),
    )
    for key, value, quote in extra_contexts:
        prompt.add_context(key, value, quote=quote)
    prompt.add_instructions(
        """
Use the relevant guideline bundle instead of guessing about forms, documents,
categories, projects, or model tasks. Schema-changing actions have mandatory
guideline reads:

- get_guidelines("category") before proposing a new category with a generated
  page form.
- get_guidelines("project") before proposing a new project, model tasks, or
  model-task forms.
- You MUST call get_guidelines("page_form") or get_guidelines("task_form")
  before writing a new form schema, matching the create_form form_type.
- You MUST call get_guidelines("schema_evolution") before proposing additive
  changes to an existing form schema.
- get_guidelines("page_document") before adding optional document HTML.

It is fine to read multiple guideline bundles when the proposal crosses several
areas. Keep using the organize action shape in the final answer even after
reading another guideline bundle.
        """,
        section_title="On-demand guidelines",
    )
    prompt.add_decision_policy(ORGANIZE_PLANNING_POLICY)
    prompt.add_instructions(
        report_action_permission_instructions(),
        section_title="Report action permissions",
        role="action_permissions",
        unique=True,
    )
    prompt.add_instructions(ORGANIZE_PLANNING_TOOLS, role="tool_use")
    prompt.add_instructions(ORGANIZE_PLANNING_ACTIONS, role="action_planning")
    return prompt


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/organize.py::revise_organize_prompt
# @reason file projection is verified through prompt context tests
def _input_file_context(report, user=None, retrieval_context=None):
    files = []
    user = user or getattr(report, "user", None)
    retrieval_context = retrieval_context or {}
    for file in report.input_files:
        file_hash = hash_reference(file)
        if hasattr(file, "to_ai"):
            context = file.to_ai(user)
            context["report_file_ref"] = context.get("hash")
            warning = _report_file_summary_warning(file)
            if warning:
                context["summary_warning"] = warning
            searches = retrieval_context.get(context["report_file_ref"])
            if searches:
                context["workspace_searches"] = searches
            files.append(context)
            continue
        context = {
            "hash": file_hash,
            "report_file_ref": file_hash,
            "display_name": file.name,
            "filename": file.filename,
            "mimetype": file.mimetype,
            "summary": file.summary,
        }
        warning = _report_file_summary_warning(file)
        if warning:
            context["summary_warning"] = warning
        searches = retrieval_context.get(file_hash)
        if searches:
            context["workspace_searches"] = searches
        files.append(context)
    return files


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_validates_ai_output
# @features ai-report
# @dimensions generate validate
def generate_organize_plan(prompt):
    """Generate and structurally validate the Organize planning stage."""
    ai_debug(
        "organize.generate.start",
        prompt_type=getattr(prompt, "prompt_type", None),
        allowed_actions=list(getattr(prompt, "allowed_actions", None) or []),
        tools=getattr(prompt, "tools", None),
        max_tool_iterations=getattr(prompt, "max_tool_iterations", None),
        max_tool_file_parts_per_turn=getattr(
            prompt,
            "max_tool_file_parts_per_turn",
            None,
        ),
    )

    # @testable false
    # @covered-by lagniappe/core/tools/ai/organize.py::generate_organize_plan
    # @reason Inline validator behavior is exercised through organize generation.
    def validate_plan(proposal):
        ai_debug("organize.generate.raw_proposal", **_proposal_debug_summary(proposal))
        return validate_or_repair_proposal(
            prompt,
            proposal,
            report_label="Organize",
            allow_pending_submissions=True,
        )

    proposal = ai_model.generate_content(prompt, validator=validate_plan)
    ai_debug("organize.generate.planned", **_proposal_debug_summary(proposal))
    return proposal


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_completes_planned_submissions
# @pair ai-report:generate
# @pair ai-report:pipeline
# @pair ai-report:submission-completion
# @pair form-schema:structured-output
# @pair submission:focused-prompt
# @pair submission:evidence-mapping
def generate_organize_report(prompt, report, user):
    """Generate, complete, and validate an Organize report proposal."""
    proposal = generate_organize_plan(prompt)
    proposal = complete_organize_submissions(
        proposal,
        report,
        user,
        service_tier=getattr(prompt, "service_tier", None),
    )
    ai_debug("organize.generate.validated", **_proposal_debug_summary(proposal))
    return proposal
