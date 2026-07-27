"""
Test data definitions - the "WHAT to test" layer.

This package provides enum-based definitions for all testable entities.
Each enum member wraps a Resource with a definition dataclass specifying
the entity's properties.

Architecture:
    Definition Enums → Resource Classes → Definition Dataclasses
    (what to test)    (how to interact)  (entity properties)

Entity Type Mappings:
    Each entity type maps to application layers:
    - Entity: lagniappe/core/entities/
    - Routes: lagniappe/web/routes/
    - Templates: lagniappe/web/templates/
    - View: src/script/views/

Definition Types:
    Static Pages (no creation needed):
        - SitePages: Fixed routes like HOME, LOGIN_PAGE, FORM_INDEX

    Creatable Entities (created via UI on first access):
        - Categories: Category containers for pages
        - Pages: Page entities within categories
        - Projects: Project containers
        - Tasks: Task items on pages or home
        - Forms: Form definitions in form builder
        - Files: File attachments

    Authentication:
        - Users: OWNER (admin), ANONYMOUS (no auth)

    Supporting Data:
        - DueDates: Due date field configurations
        - CommonFormFields, PageFormFields, TaskFormFields: Form field specs

Usage:
    from testing.definitions import Users, SitePages, Categories

    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    category = Categories.test_my_feature.get(user)

See Also:
    - documentation/TESTING_WRITING_TESTS.md: Definition patterns and E2E authoring guide
    - testing/resources/: Resource classes that implement creation logic
"""

from .categories import Categories
from .due_date import DueDates
from .files import Files
from .forms import Forms
from .model_tasks import ModelTasks
from .pages import Pages
from .projects import Projects
from .schema_fields import CommonFormFields, PageFormFields, TaskFormFields
from .schemas import Schemas
from .site_pages import SitePages
from .submission_fields import SubmissionFields
from .tasks import Tasks
from .upload import Uploads
from .upload_definitions import UploadMethod
from .users import Users
from .groups import Groups
from .permissions import Permissions
from .permission_definitions import PermissionDefinition
from .submissions import Submissions

__all__ = [
    "Categories",
    "DueDates",
    "Files",
    "Forms",
    "ModelTasks",
    "Pages",
    "Projects",
    "SitePages",
    "Tasks",
    "Uploads",
    "Users",
    "CommonFormFields",
    "PageFormFields",
    "TaskFormFields",
    "SubmissionFields",
    "UploadMethod",
    "Schemas",
    "Permissions",
    "Groups",
    "PermissionDefinition",
    "Submissions",
]
