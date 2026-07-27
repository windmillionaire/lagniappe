"""
Resource classes - the "HOW to interact" layer.

Resources encapsulate entity creation and page interaction logic.
Each resource provides:
- Selectors: CSS selectors for page elements (as class attributes)
- create(): Programmatic entity creation using the same core entity path as route handlers
- Properties: url, key, entity (populated after creation)

Entity creation typically uses `Entities.TYPE.create(...)` followed by
`entity.save()`, which mirrors the route-layer persistence path while avoiding
browser overhead for tests that only need setup data to exist.

Architecture:
    Definition Enums -> Resource Classes -> Definition Dataclasses
    (what to test)    (how to interact)  (entity properties)

Resource Types:
    Base:
        - SiteResource (core.py): Base class with user, definition, url, key, entity

    Static Pages (no create() method):
        - HomePage: Main dashboard at /
        - LoginPage: Authentication at /users/login
        - FormIndex: Form builder at /forms/index
        - UserIndex: User management at /users/index
        - AdminPage: Site settings at /admin
        - SitePage: Generic page wrapper

    Creatable Entities (have create() method):
        - Category: Entities.CATEGORY.create() + save
        - Page: Entities.PAGE.create() + save
        - Project: Entities.PROJECT.create() + save
        - Task: Entities.TASK.create() + save
        - Form: Entities.FORM.create() + save
        - User: Entities.USER.create() + save
        - ModelTask: Entities.MODEL_TASK.create() + save

Usage:
    # Resources are typically accessed via definition enums:
    category = Categories.test_my_feature.get(user)  # Returns Category resource

    # Or via user.go() for static pages:
    home = user.go(SitePages.HOME)  # Returns HomePage resource
    user.locate(home.PROJECT_LIST_TOGGLE).click()

See Also:
    - testing/definitions/: Definition enums that wrap these resources
    - testing/elements/: Reusable UI component helpers
    - documentation/TESTING_WRITING_TESTS.md: Authoring guide for the testing package
"""

from .category import Category
from .file import File
from .form import Form
from .group import Group
from .home import HomePage
from .model_task import ModelTask
from .note import Note
from .page import Page
from .project import Project
from .report import Report
from .site import AdminPage, FormIndex, LoginPage, SitePage, TaskIndex, UserIndex
from .task import Task
from .user import User
from .core import SiteResource

__all__ = [
    "User",
    "HomePage",
    "AdminPage",
    "FormIndex",
    "LoginPage",
    "SitePage",
    "UserIndex",
    "TaskIndex",
    "Project",
    "Report",
    "Category",
    "Form",
    "Task",
    "Note",
    "ModelTask",
    "Page",
    "File",
    "Group",
    "SiteResource",
]
