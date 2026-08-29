"""
Test entity classes for unit testing.

Provides TestEntity base class and entity-specific test classes that
override methods requiring external services (cloud storage, database calls).

Usage:
    entity = TestEntities["PROJECT"].value()
    entity.initialize(test_data)
"""

import random
import string
from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace

import json

from lagniappe import CONFIG
from lagniappe.core.definitions.asset import AssetVisibility, LARGE_ASSET_BYTES
from lagniappe.core.definitions.permissions import Action, Resource
from lagniappe.core.tools.files.html import strip_tags
from smartypants import smartypants

__test__ = False


def _generate_hash():
    """Generate a random 7-character hash for testing entities."""
    return "".join(random.choices(string.ascii_lowercase, k=7))


class TestUser:
    """Mock user for unit tests."""

    def __init__(self, **kwargs):
        self.db = {"name": "Test User", "email": "test@example.com"}
        self.db["owner"] = kwargs.get("owner", True)
        if kwargs.get("requires", False):
            self.db["requires"] = kwargs.get("requires")
        if kwargs.get("permissions", False):
            self.db["permissions"] = kwargs.get("permissions")

    @property
    def is_authenticated(self):
        return True

    @property
    def is_owner(self):
        return self.db.get("owner", False)

    @property
    def permissions(self):
        return self.db.get("permissions", {})

    @property
    def properties(self):
        restrictions = SimpleNamespace(belongs_to=self.db.get("belongs_to", []))
        return SimpleNamespace(restrictions=restrictions)

    def has_permission(self, resource, action=Action.ALL):
        if self.is_owner:
            return True

        if isinstance(resource, Resource):
            return resource.allowed(action, user=self)

        required = getattr(resource, "requires", [])
        return any(
            Action[permission].implies(action)
            for permission in [self.permissions.get(item) for item in required]
            if permission
        )


class MockAsset:
    """In-memory asset for unit tests; mirrors production ``Asset`` call sites.

    JSON fixtures use either a definition dict (``{"type": "html", "path": "…"}``)
    or ``true`` as a shorthand for “present”, with body text under the same key
    in ``test_spec`` (e.g. ``"document": "…"``).

    ``get``, ``save``, and ``delete`` mutate in-memory state only (no cloud/DB).
    Tests may replace an entry in ``test_spec["assets"]`` with a custom object;
    ``get_asset`` leaves non-dict / non-bool values unchanged.
    """

    def __init__(self, name, entity, raw):
        self.name = name
        self.entity = entity
        self._updated = False
        if raw is True:
            self._type = "html" if name == "document" else "text"
            self._path = None
            self._visibility = "private"
            self._fingerprint = None
            self._size = None
            self._large = None
            self._body = entity.test_spec.get(name)
            if not isinstance(self._body, str):
                self._body = None
        elif isinstance(raw, dict):
            self._type = raw.get("type", "text")
            self._path = raw.get("path")
            self._visibility = raw.get("visibility", "private")
            self._fingerprint = raw.get("fingerprint")
            self._size = raw.get("size")
            self._large = raw.get("large")
            self._body = entity.test_spec.get(name)
            if not isinstance(self._body, str):
                self._body = None
        else:
            self._type = None
            self._path = None
            self._visibility = "private"
            self._fingerprint = None
            self._size = None
            self._large = None
            self._body = None

    @property
    def type(self):
        return self._type

    @property
    def path(self):
        if self._path:
            return self._path
        key = getattr(self.entity, "key", None) or "test"
        return f"{key}_{self.name}"

    @property
    def fingerprint(self):
        return self._fingerprint

    @fingerprint.setter
    def fingerprint(self, value):
        self._fingerprint = value

    @property
    def visibility(self):
        return AssetVisibility[self._visibility]

    @visibility.setter
    def visibility(self, value):
        vis = AssetVisibility[value] if isinstance(value, str) else value
        self._visibility = vis.name.lower()

    @property
    def content_type(self):
        if self._type == "html":
            return "text/html"
        if self._type == "image":
            if self._path and self._path.endswith(".png"):
                return "image/png"
            return "image/jpeg"
        return "text/plain"

    @property
    def size(self):
        """Return fixture-backed content size without consulting cloud storage."""
        configured = self.entity.test_spec.get("asset_sizes", {}).get(self.name)
        if configured is not None:
            return configured
        if self._size is not None:
            return int(self._size)
        body = self.get()
        if body is None:
            return 0
        if isinstance(body, bytes):
            return len(body)
        return len(str(body).encode("utf-8"))

    @property
    def large(self):
        if self._large is not None:
            return bool(self._large)
        return self.size > LARGE_ASSET_BYTES

    @content_type.setter
    def content_type(self, value):
        pass

    @property
    def extension(self):
        if self._path and "." in self._path:
            return self._path.rsplit(".", 1)[-1]
        if self.content_type and "/" in self.content_type:
            return self.content_type.split("/")[-1]
        return None

    @property
    def uri(self):
        bucket = (
            "public-bucket"
            if self.visibility == AssetVisibility.public
            else "private-bucket"
        )
        return f"gs://{bucket}/{self.path}"

    @property
    def definition(self):
        definition = {"type": self._type, "path": self.path}
        if self.visibility == AssetVisibility.public:
            definition["visibility"] = "public"
        if self._fingerprint:
            definition["fingerprint"] = self._fingerprint
        return definition

    def get(self):
        return self._body

    def html(self):
        text = self.get()
        return smartypants(text) if text else None

    @property
    def cache_value(self):
        raw = self.get()
        if raw is None:
            return None
        if self._type == "html":
            return strip_tags(raw).strip()
        if self._type == "text":
            return raw.strip()
        return None

    @property
    def updated(self):
        return self._updated

    @property
    def url(self):
        if self._type != "image":
            return None
        return f"https://test.example/{self.path}"

    def delete(self):
        self._body = None
        assets = self.entity.test_spec.get("assets")
        if isinstance(assets, dict) and self.name in assets:
            del assets[self.name]

    def save(self, content):
        if not content:
            return False
        if isinstance(content, str):
            self._body = content.strip()
        elif hasattr(content, "read"):
            self._body = content.read()
            if isinstance(self._body, bytes):
                self._body = self._body.decode("utf-8", errors="replace")
        else:
            self._body = str(content)
        self._updated = True
        assets = self.entity.test_spec.setdefault("assets", {})
        assets[self.name] = self.definition
        return True


class TestEntityMixin:
    """
    Mixin providing test-specific initialization and method overrides.

    Overrides asset-related methods to work with in-memory test data
    instead of cloud storage. Provides ``url`` so ``to_ai()`` and similar
    code paths never call Flask ``url_for`` during unit tests.

    Special test_spec keys:
        test_user: Config for CONFIG.TEST_CURRENT_USER (owner, permissions, etc.)
        user: For PAGE - the User entity who owns this page (sets db["user"])
        page: For TASK/USER - the parent Page entity
        assigned_to: For TASK - nested USER spec; stores assignee's **page** key (production shape)
        project: For MODEL_TASK - the parent Project entity
        categories: For PAGE - list of Category entities
        groups: For USER/PAGE - list of UserGroup entities (page disclosure / view_access)
        restricted_to: For PAGE - db list of group hashes (API restriction)
        enforce_allowed: If true, run real ``Entity.allowed`` / ``restricted_access`` (not permissive test mode)
    """

    def _sync_group_views_from_permissions(self):
        """Mirror ``user_groups.get_view_hashes`` for groups loaded from JSON."""
        perms = self.permissions
        self.db["views"] = [
            h
            for h, act in perms.items()
            if Action[act].implies(Action.VIEW) and h != "forms"
        ]

    def __init__(self, test_spec, **kwargs):
        self.test_spec = test_spec

        test_user_config = test_spec.get("test_user")
        if test_user_config is not None or CONFIG.TEST_CURRENT_USER is None:
            CONFIG.TEST_CURRENT_USER = TestUser(**(test_user_config or {}))

        super().__init__(testing=True)

        # Set related entities before accessing required (needed by MODEL_TASK, TASK)
        if kwargs.get("project"):
            self.properties.project._value = kwargs["project"]
        elif "project" in test_spec:
            self.properties.project._value = TestEntities.get(
                "PROJECT", test_spec["project"]
            )
        if kwargs.get("page"):
            self.properties.page._value = kwargs["page"]
            if self.entity_kind == "user":
                kwargs["page"].properties.user._value = self
        elif "page" in test_spec:
            self.properties.page._value = TestEntities.get("PAGE", test_spec["page"])
            if self.entity_kind == "user":
                self.properties.page._value.properties.user._value = self
        if self.entity_kind in {"report", "note"}:
            parent = test_spec.get("parent") or test_spec.get("user")
            if parent:
                self.properties.parent._value = (
                    parent
                    if hasattr(parent, "db")
                    else TestEntities.get("USER", parent)
                )
            user = test_spec.get("user") or parent
            if user:
                self.properties.user._value = (
                    user if hasattr(user, "db") else TestEntities.get("USER", user)
                )

        # Auto-set fields that would normally be set on save
        self.db["type"] = self.entity_kind
        self.db["hash"] = test_spec.get("hash", _generate_hash())
        self.db["active"] = test_spec.get("active", True)
        self.db["requires"] = test_spec.get("requires", super().required)
        self.db["created"] = test_spec.get("created", datetime.now(timezone.utc))
        self.db["modified"] = test_spec.get("modified", datetime.now(timezone.utc))

        if self.entity_kind == "ingress":
            self.db["ingress_format"] = test_spec.get("ingress_format", 1)
            self.get_process("workflow").update(
                {
                    "current": "PROCESS_CSV",
                    "highest_completed": "PROCESS_CSV",
                    "configuration_revision": 1,
                    "process_csv": {"complete": True},
                }
            )
            self.get_process("execution").update(
                {
                    "status": "idle",
                    "cursor": 0,
                    "total_rows": 0,
                    "dispatch_sequence": 0,
                    "attempt": 0,
                }
            )

        if "attributes" in test_spec:
            self.db["attributes"] = test_spec["attributes"]

        # Set owner flag from top-level test_spec
        if test_spec.get("owner"):
            self.is_owner = True
        elif "permissions" in test_spec:
            self.permissions = test_spec["permissions"]

        self.db["name"] = self.test_spec.get("name", "")

        if self.entity_kind == "user" and "public" in test_spec:
            self.db["public"] = bool(test_spec["public"])

        if self.entity_kind == "report":
            input_files = test_spec.get("input_files", [])
            self.properties.input_files._value = [
                file if hasattr(file, "db") else TestEntities.get("FILE", file)
                for file in input_files
            ]
            for field in ["tool", "instructions"]:
                if field in test_spec:
                    self.db[field] = test_spec[field]
            for field in [
                "status",
                "summary",
                "proposal",
                "result",
                "error",
                "pending",
            ]:
                if field in test_spec:
                    setattr(self.properties.process, field, test_spec[field])

        # Kind.details_value uses db["user"], not only page.user — set before any property reads details.
        if self.entity_kind == "page" and "user" in test_spec:
            u = TestEntities.get("USER", test_spec["user"], page=self)
            self.properties.user._value = u
            self.db["user"] = u.key

        # AssignedTo persists the assignee's page key, not the user key.
        if self.entity_kind == "task" and "assigned_to" in test_spec:
            assignee = TestEntities.get("USER", test_spec["assigned_to"])
            user_page = assignee.page
            self.db["assigned_to"] = user_page.key
            self.properties.assigned_to._value = user_page

        if "restricted_to" in test_spec:
            self.db["restricted_to"] = list(test_spec["restricted_to"])

        if self.entity_kind in ("group", "public_group") and "permissions" in test_spec:
            self._sync_group_views_from_permissions()

        if test_spec.get("enforce_allowed"):
            self._testing = False

    @property
    def key(self):
        return self.db.get("hash")

    @property
    def reserved(self):
        return self.test_spec.get("reserved", False)

    @property
    def urlsafe_key(self):
        return self.db.get("hash")

    @property
    def url(self):
        """Synthetic URL for unit tests; avoids Flask url_for on production `url` properties."""
        key = self.urlsafe_key
        if not key:
            return None
        return f"/test/{self.entity_kind}/{key}"

    @property
    def should_match(self):
        return json.dumps(self.test_spec.get("should_match"), sort_keys=True)

    @property
    def assets(self):
        """Return test assets dict instead of loading from db."""
        return self.test_spec.get("assets", {})

    def get_asset(self, name):
        """Resolve a name from ``test_spec["assets"]`` to a ``MockAsset`` when JSON-safe.

        Dict definitions and boolean ``true`` (shorthand) become ``MockAsset``.
        Other values (e.g. a ``SimpleNamespace`` patched in by a test) are returned as-is.
        """
        name = name.split(".")[0] if isinstance(name, str) else name
        if not self.assets:
            return None
        raw = self.assets.get(name)
        if raw is None:
            return None
        if isinstance(raw, MockAsset):
            return raw
        if isinstance(raw, dict) or raw is True:
            asset = MockAsset(name, self, raw)
            if raw is True and asset.get() is None:
                return None
            return asset
        return raw

    def text_for_cache(self, name):
        """Return test text content for cache/AI."""
        return self.test_spec.get(name, "")

    @property
    def page(self):
        if "page" not in self.properties:
            return None
        if getattr(self.properties.page, "_value", None) is not None:
            return super().page
        if "page" not in self.test_spec:
            return None
        self.properties.page._value = TestEntities.get("PAGE", self.test_spec["page"])
        return super().page

    @property
    def form(self):
        # Don't recreate if already set (preserves schema etc.)
        if getattr(self.properties.form, "_value", None) is not None:
            return super().form

        if (
            "model" in self.properties
            and self.model
            and self.model.form
            and "form" not in self.test_spec
        ):
            form = self.model.form
        elif "form" not in self.test_spec:
            form = None
        else:
            form = TestEntities.get("FORM", self.test_spec["form"])

        self.properties.form._value = form
        return super().form

    def column(self, field_id):
        """Prime ``properties.form._value`` before column reads.

        ``AttachedForm.column_value`` uses ``properties.form.value`` (db-backed).
        Test fixtures define forms in ``test_spec`` via the ``form`` property above;
        table code calls ``entity.column("form")`` without touching ``entity.form``.
        """
        if field_id == "form" and "form" in self.properties:
            _ = self.form
        return super().column(field_id)

    @property
    def categories(self):
        if (
            "categories" not in self.test_spec
            and getattr(self.properties.categories, "_value", None) is not None
        ):
            return super().categories

        cats = [
            TestEntities.get(self._category_type(category), category)
            for category in self.test_spec.get("categories", [])
        ]
        # PageCategories uses _all_categories which includes model + categories
        model = self.model if "model" in self.test_spec else None
        self.properties.categories._all_categories = ([model] if model else []) + cats
        self.properties.categories._value = cats
        return super().categories

    @property
    def groups(self):
        """For User or Page - returns list of test group entities."""
        if "groups" not in self.test_spec:
            if self.entity_kind == "user":
                return []
            return super().groups
        self.properties.groups._value = [
            TestEntities.get("USER_GROUP", group) for group in self.test_spec["groups"]
        ]
        return super().groups

    @property
    def model_tasks(self):
        """For PROJECT entity — list of model task entities."""
        if "model_tasks" not in self.test_spec:
            self.properties.model_tasks._value = []
        else:
            models = []
            for model_spec in self.test_spec["model_tasks"]:
                # Pass project so MODEL_TASK.required can access it during init
                model_task = TestEntities.get("MODEL_TASK", model_spec, project=self)
                # Set model name from test_spec
                model_task.name = model_spec.get("name")
                models.append(model_task)
            self.properties.model_tasks._value = models
        return self.properties.model_tasks.value

    @property
    def projects(self):
        """For FORM entity — related projects (``common_related.Projects``)."""
        if "projects" not in self.properties:
            return super().projects
        if "projects" not in self.test_spec:
            self.properties.projects._value = []
        else:
            self.properties.projects._value = [
                TestEntities.get("PROJECT", p) for p in self.test_spec["projects"]
            ]
        return self.properties.projects.value

    @property
    def user(self):
        """For PAGE entity - returns the User entity who owns this page."""
        if "user" not in self.properties:
            return super().user
        if getattr(self.properties.user, "_value", None) is not None:
            return super().user
        if "user" not in self.test_spec:
            self.properties.user._value = None
            return super().user
        u = TestEntities.get("USER", self.test_spec["user"], page=self)
        self.properties.user._value = u
        self.db["user"] = u.key
        return super().user

    @property
    def model(self):
        """For PAGE/TASK entity - returns model Category or ModelTask."""
        if "model" not in self.properties:
            return None
        # Don't overwrite if already set (e.g. by setter)
        if getattr(self.properties.model, "_value", None) is None:
            if "model" not in self.test_spec:
                self.properties.model._value = None
            elif self.entity_kind == "task":
                # TASK.model is a MODEL_TASK
                self.properties.model._value = TestEntities.get(
                    "MODEL_TASK", self.test_spec["model"]
                )
            else:
                # PAGE.model is a CATEGORY
                model_spec = self.test_spec["model"]
                self.properties.model._value = TestEntities.get(
                    self._category_type(model_spec), model_spec
                )
        return super().model

    @staticmethod
    def _category_type(spec):
        if not isinstance(spec, dict):
            return "CATEGORY"
        if spec.get("_type"):
            return spec["_type"]
        if spec.get("type") == "users" or spec.get("hash") == "users":
            return "USERS"
        return "CATEGORY"

    @model.setter
    def model(self, value):
        """Set model and initialize categories._value to prevent DB access."""
        if "model" not in self.properties:
            return
        self.properties.model._value = value
        # For PAGE: ensure categories._value is set so PageCategories.value doesn't hit DB
        if hasattr(self.properties, "categories"):
            if not getattr(self.properties.categories, "_value", None):
                self.properties.categories._value = []
            if hasattr(self.properties.categories, "_all_categories"):
                self.properties.categories._all_categories = None

    @property
    def pages(self):
        """For FILE entity - returns list of Page entities this file is attached to."""
        self.properties.pages._value = (
            [TestEntities.get("PAGE", page) for page in self.test_spec["pages"]]
            if "pages" in self.test_spec
            else []
        )
        return super().pages

    @property
    def parent(self):
        """For FILTER - returns the entity being filtered."""
        if "parent" in self.test_spec:
            entity_spec = self.test_spec["parent"]
            entity_type = entity_spec.get("_type", "PROJECT")
            self.properties.parent._value = TestEntities.get(entity_type, entity_spec)
        else:
            self.properties.parent._value = None
        return super().parent

    @property
    def creator(self):
        """For FILTER - returns the user who created the filter."""
        self.properties.creator._value = (
            TestEntities.get("USER", self.test_spec["creator"])
            if "creator" in self.test_spec
            else None
        )
        return super().creator


class TestEntityRegistry:
    def initialize(self, entities):
        class TestProject(TestEntityMixin, entities.PROJECT):
            pass

        class TestPage(TestEntityMixin, entities.PAGE):
            pass

        class TestTask(TestEntityMixin, entities.TASK):
            pass

        class TestCategory(TestEntityMixin, entities.CATEGORY):
            pass

        class TestUserCategory(TestEntityMixin, entities.USERS):
            pass

        class TestUser(TestEntityMixin, entities.USER):
            pass

        class TestModelTask(TestEntityMixin, entities.MODEL_TASK):
            pass

        class TestForm(TestEntityMixin, entities.FORM):
            pass

        class TestFile(TestEntityMixin, entities.FILE):
            pass

        class TestFilter(TestEntityMixin, entities.FILTER):
            pass

        class TestUserGroup(TestEntityMixin, entities.USER_GROUP):
            pass

        class TestPublicGroup(TestEntityMixin, entities.PUBLIC_GROUP):
            pass

        class TestIngress(TestEntityMixin, entities.INGRESS):
            pass

        class TestAIReport(TestEntityMixin, entities.REPORT):
            pass

        class TestNote(TestEntityMixin, entities.NOTE):
            pass

        class TestEntities(Enum):
            PROJECT = TestProject
            PAGE = TestPage
            TASK = TestTask
            CATEGORY = TestCategory
            USERS = TestUserCategory
            USER = TestUser
            MODEL_TASK = TestModelTask
            MODEL = TestModelTask  # Alias
            FORM = TestForm
            FILE = TestFile
            FILTER = TestFilter
            USER_GROUP = TestUserGroup
            GROUP = TestUserGroup  # Alias
            PUBLIC_GROUP = TestPublicGroup
            INGRESS = TestIngress
            REPORT = TestAIReport
            NOTE = TestNote

        self._types = TestEntities

    def get(self, kind, test_spec, **kwargs):
        entity_class = self._types[kind].value
        return entity_class(test_spec, **kwargs)


TestEntities = TestEntityRegistry()
