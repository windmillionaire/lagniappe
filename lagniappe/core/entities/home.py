from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .user import User
    from .entity import Entity

from ..properties import home
from .site import Site


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

    def __init__(self, *args: object, user: User, entity: Entity | None = None, **kwargs: object) -> None:
        if user is None:
            raise ValueError("Home requires a user")
        self._user = user
        super().__init__(*args, entity=entity, **kwargs)

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

    def section(self, name: str, *, cursor: str | None = None) -> home.HomeProperty:
        """Create a HomeProperty section (projects, categories, tasks, etc.) by name."""
        return cast(home.HomeProperty, self._properties[name](cursor=cursor))
