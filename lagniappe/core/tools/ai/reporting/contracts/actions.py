"""AI report action vocabulary and data contracts."""

READ_ONLY_CONTEXT_TOOLS = (
    "get_help",
    "list_workspace_resources",
    "get_guidelines",
    "search_entities",
    "get_entity",
    "get_schema",
    "get_file",
    "get_category_forms",
    "get_category_pages",
    "get_page_details",
    "get_page_file_list",
    "get_page_tasks",
    "get_form_instances",
    "preview_form_schema_update",
    "get_category_details",
)

REPORT_ACTION_DATA_CONTRACTS = {
    **{name: {"fields": ("entity", "changes"), "required": ("entity", "changes")}
       for name in ("update_task", "update_model_task", "update_project", "update_page", "update_file")},
    "create_form": {
        "fields": ("name", "form_type", "schema"),
        "required": ("name", "form_type", "schema"),
    },
    "create_category": {
        "fields": (
            "name",
            "description",
            "form",
            "form_action",
            "form_name",
        ),
        "required": ("name",),
    },
    "create_project": {
        "fields": ("name", "description"),
        "required": ("name",),
    },
    "create_model_task": {
        "fields": (
            "name",
            "project",
            "project_action",
            "project_name",
            "form",
            "form_action",
            "form_name",
        ),
        "required": ("name",),
        "required_groups": (("project", "project_action"),),
    },
    "create_page": {
        "fields": (
            "name",
            "description",
            "category",
            "category_action",
            "category_name",
            "form",
            "form_action",
            "form_name",
            "document_markdown",
            "submission",
            "submission_empty_reason",
        ),
        "required": ("name",),
    },
    "append_page_document": {
        "fields": ("page", "page_action", "page_name", "document_markdown"),
        "required": ("document_markdown",),
        "required_groups": (("page", "page_action"),),
    },
    "create_task": {
        "fields": (
            "name",
            "description",
            "page",
            "page_action",
            "page_name",
            "task",
            "task_action",
            "task_name",
            "project",
            "project_action",
            "project_name",
            "model",
            "model_action",
            "model_name",
            "form",
            "form_action",
            "form_name",
            "due_date",
            "schedule",
            "completed",
            "completed_on",
            "submission",
            "submission_empty_reason",
        ),
        "required": ("name",),
        "required_groups": (("page", "page_action"),),
    },
    "move_task": {
        "fields": (
            "task",
            "task_action",
            "task_name",
            "to_page",
            "to_page_action",
            "page_name",
        ),
        "required_groups": (
            ("task", "task_action"),
            ("to_page", "to_page_action"),
        ),
    },
    "move_file": {
        "fields": (
            "file",
            "display_name",
            "from_page",
            "from_page_action",
            "from_task",
            "from_task_action",
            "to_page",
            "to_page_action",
            "to_task",
            "to_task_action",
        ),
        "required": ("file",),
        "required_groups": (
            ("from_page", "from_page_action", "from_task", "from_task_action"),
            ("to_page", "to_page_action", "to_task", "to_task_action"),
        ),
    },
    "update_form_schema": {
        "fields": ("form", "form_action", "form_name", "operations", "baseline", "scope_fingerprint", "conversions"),
        "required": ("operations",),
        "required_groups": (("form", "form_action"),),
    },
    "complete_task": {
        "fields": ("task", "task_name"),
        "required": ("task",),
    },
    "attach_file": {
        "fields": ("entity", "entity_action", "entity_name", "file", "display_name"),
        "required": ("file",),
        "required_groups": (("entity", "entity_action"),),
    },
    "suggest_page_deletion": {
        "fields": ("page", "page_action", "page_name"),
        "required_groups": (("page", "page_action"),),
    },
    "skip": {
        "fields": ("note",),
        "required": ("note",),
    },
    "needs_review": {
        "fields": ("note", "questions"),
        "required": ("note", "questions"),
    },
    "summarize_file": {
        "fields": ("file", "summary", "retrieval_terms", "search"),
        "required": ("file", "summary"),
    },
}

# The ordered contract registry is the source of truth for action vocabulary.
# Keep summarize_file valid for older saved proposals and direct runner tests,
# but do not advertise it to new report prompts.
ALLOWED_ACTIONS = frozenset(REPORT_ACTION_DATA_CONTRACTS)
ACTION_ORDER = tuple(
    action_type
    for action_type in REPORT_ACTION_DATA_CONTRACTS
    if action_type != "summarize_file"
)
