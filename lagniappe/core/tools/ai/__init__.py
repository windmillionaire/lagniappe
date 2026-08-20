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
from .category import generate_category, category_creation_prompt
from .pages import generate_pages, page_generation_prompt
from .summarize import summarize_file, generate_summary
from .schema import form_generation_prompt, generate_schema
from .autofill import (
    autofill_prompt_data,
    autofill_summary_dependencies,
    form_autofill_prompt,
    generate_autofilled_submission,
)
from .project import project_creation_prompt, generate_project
from .ask import (
    ASK_MAX_TOOL_ITERATIONS,
    ask_report_name,
    ask_prompt,
    generate_ask_report,
    revise_ask_prompt,
    validate_ask_response,
)
from .create import (
    CREATE_MAX_TOOL_ITERATIONS,
    create_prompt,
    generate_create_report,
    revise_create_prompt,
)
from .organize import (
    ORGANIZE_MAX_TOOL_ITERATIONS,
    complete_organize_submissions,
    generate_organize_plan,
    generate_organize_report,
    organize_prompt,
    revise_organize_prompt,
    summarize_report_input_files,
    skip_proposal_actions,
    toggle_proposal_action_indexes,
    toggle_proposal_action_skip,
    validate_proposal,
)
from .organize_retrieval import prepare_organize_retrieval_context
from .report_runner import REPORT_LEDGER_VERSION, run_report, undo_report
from .report_uploads import (
    cleanup_report_upload_manifest,
    finalize_report_upload_manifest,
    prepare_report_upload_manifest,
)
from .email_router import (
    ai_email_routing_prompt,
    route_ai_email,
    validate_ai_email_route,
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
    "page_image_generation_prompt",
    "generate_category",
    "category_creation_prompt",
    "generate_pages",
    "page_generation_prompt",
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
    "ASK_MAX_TOOL_ITERATIONS",
    "ask_report_name",
    "ask_prompt",
    "generate_ask_report",
    "revise_ask_prompt",
    "validate_ask_response",
    "CREATE_MAX_TOOL_ITERATIONS",
    "create_prompt",
    "generate_create_report",
    "revise_create_prompt",
    "ORGANIZE_MAX_TOOL_ITERATIONS",
    "complete_organize_submissions",
    "generate_organize_plan",
    "organize_prompt",
    "revise_organize_prompt",
    "generate_organize_report",
    "summarize_report_input_files",
    "prepare_organize_retrieval_context",
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
    "ai_email_routing_prompt",
    "route_ai_email",
    "validate_ai_email_route",
]
