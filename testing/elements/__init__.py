"""
UI element helpers - reusable selectors and interaction patterns.

This package provides two types of helpers:
1. Selector classes: CSS selectors as class attributes (Buttons, FormElements, Roles)
2. Helper classes: Wrappers with built-in assertions and common actions (Modal, Link, Table)

Architecture:
    Selectors are static strings used with locator():
        form.locator(FormElements.NAME).fill("Test")
        form.locator(Buttons.SIGNIN).click()

    Helpers wrap elements and provide methods:
        modal = Modal(user.page)
        modal.delete()  # Clicks, waits for spinner, waits for hide

Modules:
    site_common.py: Core selectors (Buttons, FormElements, Roles) and helpers (Modal, Link)
    forms_common.py: Form-specific helpers (SpinnerButtons, FormSelect, ProjectSelect, DateSelect, UserSelect, FileSelect)
    indexes.py: Index page helpers (Table, Tools)
    tabs.py: Tab navigation helper (Tabs)
    tasks.py: Task-specific helpers (PostponeDropdown)
    search.py: Search functionality (HeaderSearch)
    combobox.py: Select/dropdown helpers (Select, Dropdown)
    containers.py: Shared list helper (List)
    uploads.py: Upload menu helper (UploadDropdown)

Usage:
    from testing.elements import Buttons, FormElements, Modal, Table

    # Selectors for locating elements
    user.locate(home.CREATE_PROJECT_TOGGLE).click()
    form.locator(FormElements.NAME).fill("My Project")
    form.locator(Buttons.LP_DELETE).click()

    # Helpers for common patterns
    modal = Modal(user.page)
    modal.delete()

    table = Table(user.page)
    new_row = table.new_row("My Entity")

See Also:
    - documentation/TESTING_WRITING_TESTS.md: Element patterns documentation
    - testing/resources/: Resources that use these elements internally
"""

from .badges import Badges
from .combobox import Dropdown, Select
from .containers import List
from .editor import (
    Editor,
    EditorAddImage,
    EditorAddLink,
    EditorAddYouTube,
    EditorColorOptions,
    EditorFontFamilyOptions,
    EditorFormOptions,
    EditorGenerateText,
    EditorGenerateTextMode,
    EditorImageSettings,
    EditorMenuOptions,
    EditorToggleOptions,
)
from .filters import CategoryFilterConditions, Filters, ProjectFilterConditions
from .forms_common import (
    DateSelect,
    FileSelect,
    FormSelect,
    ProjectSelect,
    SpinnerButtons,
    UserSelect,
)
from .ingress import IngressWizard
from .indexes import MobileTableControls, Table, Tools
from .permissions_form import PermissionsForm
from .search import HeaderSearch
from .site_common import Buttons, FormElements, Link, Modal, Roles, StarButton
from .tabs import MobileNav, Tabs
from .tasks import PostponeDropdown
from .uploads import UploadDropdown

__all__ = [
    # Button helpers
    "FormSelect",
    "ProjectSelect",
    "DateSelect",
    "UserSelect",
    "FileSelect",
    "SpinnerButtons",
    # Container helpers
    "Table",
    "MobileTableControls",
    # UI component helpers
    "Modal",
    "Link",
    "Tabs",
    "MobileNav",
    "Tools",
    "HeaderSearch",
    "PostponeDropdown",
    "UploadDropdown",
    "IngressWizard",
    # Editor helpers
    "Editor",
    "EditorMenuOptions",
    "EditorToggleOptions",
    "EditorFormOptions",
    "EditorColorOptions",
    "EditorFontFamilyOptions",
    "EditorGenerateText",
    "EditorGenerateTextMode",
    "EditorAddImage",
    "EditorAddLink",
    "EditorAddYouTube",
    "EditorImageSettings",
    "Dropdown",
    "Select",
    "Badges",
    "List",
    "Buttons",
    "FormElements",
    "Link",
    "Modal",
    "Roles",
    "StarButton",
    "Filters",
    "CategoryFilterConditions",
    "ProjectFilterConditions",
    "PermissionsForm",
]
