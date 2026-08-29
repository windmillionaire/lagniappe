"""AI report action vocabulary and data contracts."""

READ_ONLY_CONTEXT_TOOLS = (
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
    "get_category_details",
)

REPORT_ACTION_DATA_CONTRACTS = {
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
            "document",
            "submission",
            "submission_empty_reason",
        ),
        "required": ("name",),
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
    "add_form_to_page": {
        "fields": (
            "page",
            "page_action",
            "page_name",
            "form",
            "form_action",
            "form_name",
        ),
        "required_groups": (
            ("page", "page_action"),
            ("form", "form_action"),
        ),
    },
    "add_category": {
        "fields": (
            "page",
            "page_action",
            "page_name",
            "category",
            "category_action",
            "category_name",
        ),
        "required_groups": (
            ("page", "page_action"),
            ("category", "category_action"),
        ),
    },
    "move_page": {
        "fields": (
            "page",
            "page_action",
            "page_name",
            "category",
            "category_action",
            "category_name",
        ),
        "required_groups": (
            ("page", "page_action"),
            ("category", "category_action"),
        ),
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
    "rename_entity": {
        "fields": ("entity", "entity_action", "entity_name", "name"),
        "required": ("name",),
        "required_groups": (("entity", "entity_action"),),
    },
    "update_form_schema": {
        "fields": ("form", "form_action", "form_name", "operations"),
        "required": ("operations",),
        "required_groups": (("form", "form_action"),),
    },
    "update_submission_fields": {
        "fields": ("page", "page_name", "task", "task_name", "updates"),
        "required": ("updates",),
    },
    "attach_file_to_page": {
        "fields": ("page", "page_action", "page_name", "file", "display_name"),
        "required": ("file",),
        "required_groups": (("page", "page_action"),),
    },
    "attach_file_to_task": {
        "fields": ("task", "task_action", "task_name", "file", "display_name"),
        "required": ("file",),
        "required_groups": (("task", "task_action"),),
    },
    "delete_page": {
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
        "fields": ("file", "summary", "search"),
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
