"""Shared user-manual section catalog."""


MANUAL_SECTIONS = (
    {
        "key": "overview",
        "name": "Overview",
        "icon": "overview",
        "kind": "category",
    },
    {
        "key": "quickstart",
        "name": "Quickstart",
        "icon": "launch",
        "kind": "page",
    },
    {
        "key": "forms",
        "name": "Forms",
        "icon": "form",
        "kind": "form",
    },
    {
        "key": "tasks",
        "name": "Tasks",
        "icon": "tasks",
        "kind": "task",
    },
    {
        "key": "permissions",
        "name": "Permissions",
        "icon": "permissions",
        "kind": "user",
    },
    {
        "key": "search",
        "name": "Search & Filters",
        "icon": "search",
        "kind": "page",
    },
    {
        "key": "collaboration",
        "name": "Collaboration",
        "icon": "users",
        "kind": "user",
    },
    {
        "key": "installation",
        "name": "Installation",
        "icon": "installation",
        "kind": "task",
    },
    {
        "key": "security",
        "name": "Security",
        "icon": "security",
        "kind": "user",
    },
    {
        "key": "personalization",
        "name": "Personalization",
        "icon": "personalization",
        "kind": "project",
    },
    {
        "key": "ai",
        "name": "AI Integration",
        "icon": "generate",
        "kind": "form",
    },
    {
        "key": "under-the-hood",
        "name": "Under the Hood",
        "icon": "sitemap",
        "kind": "page",
    },
)

VALID_MANUAL_SECTIONS = frozenset(section["key"] for section in MANUAL_SECTIONS)
