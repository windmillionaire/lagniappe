"""Shared user-manual section catalog."""


MANUAL_SECTIONS = (
    {
        "key": "overview",
        "name": "Overview",
        "icon": "overview",
        "kind": "category",
        "description": "Learn how {app_name} organizes knowledge, checklists, forms, projects, and AI tools in one collaborative workspace.",
    },
    {
        "key": "quickstart",
        "name": "Quickstart",
        "icon": "launch",
        "kind": "page",
        "description": "Set up your personal page, create notes, categories, and forms, build tasks, and start your first project.",
    },
    {
        "key": "forms",
        "name": "Forms",
        "icon": "form",
        "kind": "form",
        "description": "Design reusable structured forms with sections, field validation, conditional rules, and attached AI summaries.",
    },
    {
        "key": "tasks",
        "name": "Tasks",
        "icon": "tasks",
        "kind": "task",
        "description": "Track one-off checklists and repeatable tasks with due dates, flexible schedules, project models, and submission history.",
    },
    {
        "key": "permissions",
        "name": "Permissions",
        "icon": "permissions",
        "kind": "user",
        "description": "Control visibility and editing across roles, user groups, custom restrictions, and public links.",
    },
    {
        "key": "search",
        "name": "Search & Filters",
        "icon": "search",
        "kind": "page",
        "description": "Search across pages, tasks, files, and help articles, then slice tables with saved live filters and inline editing.",
    },
    {
        "key": "collaboration",
        "name": "Collaboration",
        "icon": "users",
        "kind": "user",
        "description": "Invite teammates, organize user groups, send direct messages, mention people in documents, and configure notification emails.",
    },
    {
        "key": "installation",
        "name": "Installation",
        "icon": "installation",
        "kind": "task",
        "description": "Install, configure, update, back up, and monitor your self-hosted {app_name} server.",
    },
    {
        "key": "security",
        "name": "Security",
        "icon": "security",
        "kind": "user",
        "description": "Understand {app_name}'s server-enforced permissions, Google Identity Platform sign-in, HTTP security headers, owner boundaries, and Secret Manager.",
    },
    {
        "key": "personalization",
        "name": "Personalization",
        "icon": "personalization",
        "kind": "project",
        "description": "Customize site colors, icons, branding, page photos, public landing pages, and deployment upgrades.",
    },
    {
        "key": "ai",
        "name": "AI Integration",
        "icon": "generate",
        "kind": "form",
        "description": "Use built-in AI plans, answers, email submissions, image generation, and external MCP or REST agent connections.",
    },
    {
        "key": "under-the-hood",
        "name": "Under the Hood",
        "icon": "sitemap",
        "kind": "page",
        "description": "Explore {app_name}'s application architecture, storage, full-text indexing, offline support, and async task processing.",
    },
)

VALID_MANUAL_SECTIONS = frozenset(section["key"] for section in MANUAL_SECTIONS)
