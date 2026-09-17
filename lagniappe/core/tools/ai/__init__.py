"""Public API for AI-powered content generation tools."""

from .dates import scheduling_prompt, generate_schedule
from .images import (
    generate_ai_image,
    page_image_generation_prompt,
)
from .text import (
    document_generation_context,
    generate_ai_text,
    text_generation_prompt,
)
from .references import render_ai_markdown
from .category import generate_category, category_creation_prompt
from .summarize import summarize_file, generate_summary
from .schema import form_generation_prompt, generate_schema
from .autofill import (
    autofill_prompt_data,
    autofill_summary_dependencies,
    form_autofill_prompt,
    generate_autofilled_submission,
)
from .project import project_creation_prompt, generate_project
from .planner import REPORT_MAX_TOOL_ITERATIONS, report_prompt, generate_report
from .reporting.completion.files import summarize_report_input_files
from .reporting.proposals.selection import skip_proposal_actions, toggle_proposal_action_indexes, toggle_proposal_action_skip
from .reporting.proposals.validation import validate_proposal
from .reporting.execution.ledger import REPORT_LEDGER_VERSION
from .reporting.execution.runner import run_report
from .reporting.execution.undo import undo_report
from .reporting.uploads import (
    cleanup_report_upload_manifest,
    finalize_report_upload_manifest,
    prepare_report_upload_manifest,
)
from .core import ai_model


# @testable false
# @covered-by lagniappe/core/tools/ai/core.py::GenAI.initialize
# @reason package-level convenience wrapper around provider client initialization
def initialize():
    ai_model.initialize()


__all__ = [
    "initialize",
    "scheduling_prompt",
    "generate_schedule",
    "generate_ai_image",
    "generate_ai_text",
    "document_generation_context",
    "text_generation_prompt",
    "render_ai_markdown",
    "page_image_generation_prompt",
    "generate_category",
    "category_creation_prompt",
    "form_generation_prompt",
    "generate_schema",
    "summarize_file",
    "generate_summary",
    "form_autofill_prompt",
    "autofill_prompt_data",
    "autofill_summary_dependencies",
    "generate_autofilled_submission",
    "project_creation_prompt",
    "generate_project",
    "REPORT_MAX_TOOL_ITERATIONS",
    "report_prompt",
    "generate_report",
    "summarize_report_input_files",
    "skip_proposal_actions",
    "toggle_proposal_action_indexes",
    "toggle_proposal_action_skip",
    "validate_proposal",
    "run_report",
    "undo_report",
    "REPORT_LEDGER_VERSION",
    "cleanup_report_upload_manifest",
    "finalize_report_upload_manifest",
    "prepare_report_upload_manifest",
]
