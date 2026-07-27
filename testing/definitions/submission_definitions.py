from dataclasses import dataclass
from .schemas import Schemas


@dataclass
class SubmissionDefinition:
    schema: Schemas
    values: dict


default_category_form_submission = SubmissionDefinition(
    schema=Schemas.page_submission_test,
    values={
        "name": "Alberta",
        "description": "The Queen with the yellow Toyota.",
        "checkbox": True,
        "radio": "Apples",
    },
)

basic_inputs_submission = SubmissionDefinition(
    schema=Schemas.basic_inputs,
    values={
        "input-textab12": "Alberta Einstein",
        "input-datecd34": "2025-06-15",
        "input-timeef56": "14:30",
        "input-numgh78": "42",
        "input-emlij90": "test@example.com",
        "input-telkl12": "5551234567",
    },
)

partial_task_history_submission = SubmissionDefinition(
    schema=Schemas.basic_inputs,
    values={
        "input-textab12": "Partial completed task text",
    },
)

selection_types_submission = SubmissionDefinition(
    schema=Schemas.selection_types,
    values={
        "textarea-notesab": "A short note about grandma.",
        "checkbox-activecd": True,
        "radio-priorityef": "Medium",
        "select-statusgh": "Published",
        "select-tagsij12": ["Featured", "Sale"],
    },
)

link_external_submission = SubmissionDefinition(
    schema=Schemas.link_external_only,
    values={
        "link-ab12": {"url": "https://example.com", "title": "Example Site"},
    },
)

category_filter_match_submission = SubmissionDefinition(
    schema=Schemas.category_filter_page,
    values={
        "category-filter-notes": "Urgent permit packet",
        "category-filter-score": "92",
        "category-filter-flagged": True,
        "category-filter-decision": "approved",
    },
)

category_filter_nonmatch_submission = SubmissionDefinition(
    schema=Schemas.category_filter_page,
    values={
        "category-filter-notes": "Routine archive packet",
        "category-filter-score": "41",
        "category-filter-flagged": False,
        "category-filter-decision": "needs-review",
    },
)

category_table_submission = SubmissionDefinition(
    schema=Schemas.submission_headline_table,
    values={
        "headline": "Top story",
        "items": {"rows": [{"row_note": "Row one"}]},
    },
)

sync_form_initial_submission = SubmissionDefinition(
    schema=Schemas.sync_text,
    values={
        "sync-text": "Initial form sync",
    },
)

sync_form_submit_initial_submission = SubmissionDefinition(
    schema=Schemas.sync_text,
    values={
        "sync-text": "Before deliberate submit",
    },
)

offline_sync_form_initial_submission = SubmissionDefinition(
    schema=Schemas.sync_text,
    values={
        "sync-text": "Before headless replay",
    },
)
