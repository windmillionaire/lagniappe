from ..properties import home
from .site import Site


# @testable false
# @covered-by lagniappe/core/properties/home.py
# @covered-by lagniappe/web/routes/home/main.py::home_page
# @reason home entity is a section/property container; list behavior lives on home properties
class Home(Site):
    _site_id = "home"

    # @testable false
    # @covered-by lagniappe/core/properties/home.py
    def _get_properties(self):
        return {
            "pages": home.PageList,
            "projects": home.ProjectList,
            "categories": home.CategoryList,
            "tasks": home.TaskList,
            "notes": home.NoteList,
            "starred": home.StarredList,
            "ingress": home.IngressList,
            "tools": home.ToolsList,
        }

    # @testable false
    # @covered-by lagniappe/web/routes/home/main.py::get
    def section(self, name, **kwargs):
        """Create a HomeProperty section (projects, categories, tasks, etc.) by name."""
        return self._properties[name](**kwargs)
