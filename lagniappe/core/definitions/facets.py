"""Search facet definitions for filtering search results by entity type."""

from enum import Enum


class Categories:
    """Facet configuration for category search results."""

    name = "categories"
    icon = "category"
    kind = "category"
    title = "Categories"


class Pages:
    """Facet configuration for page search results."""

    name = "pages"
    icon = "page"
    kind = "page"
    title = "Pages"


class Projects:
    """Facet configuration for project search results."""

    name = "projects"
    icon = "project"
    kind = "project"
    title = "Projects"


class Tasks:
    """Facet configuration for task search results."""

    name = "tasks"
    icon = "task"
    kind = "task"
    title = "Tasks"


class Forms:
    """Facet configuration for form search results."""

    name = "forms"
    icon = "form"
    kind = "form"
    title = "Forms"


class Users:
    """Facet configuration for user search results."""

    name = "users"
    icon = "user"
    kind = "user"
    title = "Users"


class Files:
    """Facet configuration for file search results."""

    name = "files"
    icon = "file"
    kind = "file"
    title = "Files"


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::search_page
# @covered-by src/script/views/results.mjs::Results.init
class SearchFacets(Enum):
    """
    Enum of available search facets.

    Each facet defines metadata for a search result entity type including
    name, icon, kind, and display title.
    """

    CATEGORIES = Categories
    PAGES = Pages
    PROJECTS = Projects
    TASKS = Tasks
    FILES = Files
    FORMS = Forms
    USERS = Users
