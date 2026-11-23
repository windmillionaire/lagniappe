from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .user import User
    from .entity import Entity

from ..properties import home
from .site import Site


# @testable false
# @covered-by lagniappe/core/properties/home.py
# @covered-by lagniappe/web/routes/home/main.py::home_page
# @reason home entity is a section/property container; list behavior lives on home properties
class Home(Site):
    _site_id = "home"

    if TYPE_CHECKING:
        pages: home.PageList
        projects: home.ProjectList
        categories: home.CategoryList
        tasks: home.TaskList
        notes: home.NoteList
        starred: home.StarredList
        ingress: home.IngressList
        tools: home.ToolsList

    # @testable true
    # @tests tests_unit/test_002i_home_properties.py::test_home_requires_explicit_user
    # @tests tests_unit/test_002i_home_properties.py::test_home_sections_keep_their_viewer_across_lazy_and_paginated_reads
    # @matrix home : explicit-user validation
    def __init__(self, *args: object, user: User, entity: Entity | None = None, **kwargs: object) -> None:
        if user is None:
            raise ValueError("Home requires a user")
        self._user = user
        super().__init__(*args, entity=entity, **kwargs)

    # @testable false
    # @covered-by lagniappe/core/properties/home.py
    def _get_properties(self) -> Mapping[str, Callable[..., home.HomeProperty]]:
        sections = {
            "pages": home.PageList,
            "projects": home.ProjectList,
            "categories": home.CategoryList,
            "tasks": home.TaskList,
            "notes": home.NoteList,
            "starred": home.StarredList,
            "ingress": home.IngressList,
            "tools": home.ToolsList,
        }
        return {name: partial(section, user=self._user) for name, section in sections.items()}

    # @testable true
    # @tests tests_unit/test_002i_home_properties.py::test_home_sections_keep_their_viewer_across_lazy_and_paginated_reads
    # @matrix home : explicit-user pagination
    def section(self, name: str, *, cursor: str | None = None) -> home.HomeProperty:
        """Create a HomeProperty section (projects, categories, tasks, etc.) by name."""
        return cast(home.HomeProperty, self._properties[name](cursor=cursor))
