from datetime import datetime, UTC
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.file import File
    from ..entities.form import Form
    from ..entities.page import Page
    from ..entities.task import Task
    from ..entities.user import User

from ..definitions import FieldType, FilterOptions, Ordering
from ..definitions.identifiers import random_hash, short_hash, short_uuid
from ..entities import Entities
from ..exceptions import PropertyError, ValidationError
from ..mixins import (
    AIMixin,
    CacheMixin,
    ColumnMixin,
    DateMixin,
    DetailsMixin,
    FilterMixin,
)
from ..tools import cache
from lagniappe.core.tools.database import get as database_get
from ..tools.files.html import strip_tags
from .base_db import DBProperty
from ..tools.auth.restrictions import normalize_restrictions, permission_relation

type RestrictionOwner = Form | Page | Task | File


class Name(CacheMixin, ColumnMixin, DetailsMixin, AIMixin, FilterMixin, DBProperty[str]):
    """Entity name. Primary display and search identifier.

    Strips "The " prefix for lexical sorting.

    Set:
        value (str): Entity name.

    Get:
        value (str): Entity name.
        column_value (dict): Full entity details dict for table display.
        sort_value (str): Lowercase name with a leading "The " stripped.

    Overrides:
        cache_value: Returns the entity name for search indexing.
        ai_key: Returns "{entity_kind}_name".
        filter_label: Returns "{kind} Name".
    """

    # Property Attributes
    _id = "name"
    _label = "Name"
    _icon = "text"

    # Column Attributes
    _ordering = Ordering.LEXICAL
    _selected = True
    _editable = True

    def __init__(self, *args: object, entity: Entity | None = None, **kwargs: object) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self.errors: list[str | ValidationError] = []

    @property
    def schema(self) -> dict[str, object]:
        return {"type": "input", "input": "text"}

    @property
    def value(self) -> str | None:
        return self._read_db_value()

    @value.setter
    def value[Part](self, value: str | list[Part] | None) -> None:
        if isinstance(value, list):
            value = " ".join(
                str(v).strip() for v in value if v is not None and str(v).strip()
            )
        self._write_db_value(value or None)

    @property
    def sort_value(self) -> str | None:
        return self.value.removeprefix("The ").lower() if self.value else None

    @property
    def column_value(self) -> dict[str, object]:
        return self.entity.details

    # AI Attributes
    @property
    def ai_key(self) -> str:
        return f"{self.entity.entity_kind}_name"

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value
    _filter_key = "name"

    @property
    def filter_label(self) -> str:
        return f"{self.filter_kind.capitalize()} Name"

    @property
    def filter_kind(self) -> str:
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value: str) -> None:
        self._filter_kind = value

    # Column Attributes
    @property
    def link(self) -> bool:
        return getattr(self, "_link", True)

    @link.setter
    def link(self, value: bool) -> None:
        self._link = value

    @property
    def parent(self) -> bool:
        return getattr(self, "_parent", True)

    @parent.setter
    def parent(self, value: bool) -> None:
        self._parent = value

    # Cache Attributes
    @property
    def cache_value(self) -> str | None:
        return self.value

    # Ingress Attributes
    def validate_import[Part](self, value: str | list[Part] | None) -> None:
        try:
            value_string = (
                " ".join(
                    str(v).strip() for v in value if v is not None and str(v).strip()
                )
                if isinstance(value, list)
                else value
            )
            self.value = value_string if value_string else None
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid text value '{value}' in column '({self.label})'"
            )


class Description(CacheMixin, ColumnMixin, AIMixin, FilterMixin, DBProperty[str]):
    """Entity description. HTML tags are stripped; text whitespace is preserved.

    Set:
        value (str): Description text. HTML tags are stripped before storage.

    Get:
        value (str): Plain-text description.
        sort_value (bool): Whether a description exists.

    Overrides:
        kind: Derived from entity type (page or task), not _kind.
        cache_value: Returns description text for search indexing.
        ai_key: Returns "page_description" or "task_description".
    """

    # Property Attributes
    _id = "description"
    _label = "Description"
    _icon = "textarea"

    @property
    def value(self) -> str | None:
        return super().value

    @value.setter
    def value(self, value: str | None) -> None:
        self._write_db_value(strip_tags(value, preserve_whitespace=True))

    @property
    def kind(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- Computed from the owner and intentionally read-only.
        return (
            "page"
            if isinstance(self.entity, (Entities.PAGE, Entities.CATEGORY))
            else "task"
        )

    # Column Attributes
    _ordering = False
    _selected = False
    _editable = False

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value
    _filter_key = "description"

    @property
    def sort_value(self) -> bool:
        return bool(self.value)

    @property
    def filter_kind(self) -> str:
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value: str) -> None:
        self._filter_kind = value

    @property
    def filter_value(self) -> str | None:
        return self.value if self.value else None

    # Cache Attributes
    _cache_key = "desc"

    @property
    def cache_value(self) -> str | None:
        return self.value

    # AI Attributes
    @property
    def ai_key(self) -> str:
        if isinstance(self.entity, Entities.PAGE):
            return "page_description"
        elif isinstance(self.entity, Entities.TASK):
            return "task_description"
        return "description"


class Created(DateMixin, ColumnMixin, FilterMixin, DBProperty[datetime]):
    """Entity creation timestamp. Read-only after creation.

    Set:
        value (datetime): Creation date (UTC).

    Get:
        value (datetime): UTC datetime.
        column_value (datetime): User-timezone datetime (via DateMixin).
        sort_value (float): Timestamp for ordering.
    """

    # Property Attributes
    _id = "created"
    _label = "Created"
    _icon = "date"

    def update(self) -> None:
        if super().value:
            return

        self._write_db_value(datetime.now(UTC))

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _selected = False
    _editable = False


class Modified(DateMixin, ColumnMixin, FilterMixin, DBProperty[datetime]):
    """Entity last-modified timestamp.

    Set:
        value (datetime): Last modified date (UTC).

    Get:
        value (datetime): UTC datetime.
        column_value (datetime): User-timezone datetime (via DateMixin).
        sort_value (float): Timestamp for ordering.
    """

    # Property Attributes
    _id = "modified"
    _label = "Modified"
    _icon = "date"

    def update(self) -> None:
        self._write_db_value(datetime.now(UTC))

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _selected = False
    _editable = False

    @property
    def filter_label(self) -> str:
        return "Last Modified"

    @property
    def filter_kind(self) -> str:
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value: str) -> None:
        self._filter_kind = value

    @property
    def details_value(self) -> str:
        return cast(datetime, self.value).isoformat()


class Kind(DetailsMixin, CacheMixin, DBProperty[str]):
    """Entity type discriminator (e.g. "page", "task", "user").

    Stored in entity.db under key "type" (not "kind").

    Set:
        value (str): Entity type identifier.

    Get:
        value (str): Entity type identifier.

    Overrides:
        db_key: Returns "type" instead of "kind".
        details_value: Returns "user" for user-owned pages.
    """

    # Property Attributes
    _id = "kind"

    # DB Attributes
    @property
    def db_key(self) -> str:
        return "type"

    # Details Attributes
    @property
    def details_value(self) -> str | None:
        if isinstance(self.entity, Entities.PAGE) and self.entity.db.get("user"):
            return "user"

        return self.value

    # Cache Attributes
    @property
    def cache_value(self) -> str | None:
        return self.details_value


class Requires(CacheMixin, DetailsMixin, DBProperty[list[str]]):
    """Access-control list for an entity.

    A list of entity hashes and global resource names that a user must
    have access to in order to view this entity. Computed from
    entity.required on first access and persisted in entity.db and cache.

    Set:
        value (list | str): Required hashes/resources. A single string is wrapped in a list.

    Get:
        value (list): Required hashes/resources.
        cache_value (str): Comma-separated string for the search cache.
    """

    # Property Attributes
    _id = "requires"

    @property
    def value(self) -> list[str]:
        value = super().value
        if value:
            return value

        self._value = self._required()
        return cast("list[str]", self._value)

    @value.setter
    def value(self, value: str | list[str] | None) -> None:
        self._write_db_value(self._validate(value))

    def update(self) -> None:
        self._write_db_value(self._required())

    def _required(self) -> list[str]:
        try:
            required = self.entity.required
        except PropertyError:
            raise
        except AttributeError as error:
            raise PropertyError(
                f"{type(self.entity).__name__}.required could not be computed; "
                "load required relations before saving",
                entity=self.entity,
            ) from error
        return self._validate(required)

    def _validate(self, value: object) -> list[str]:
        required = [value] if not isinstance(value, list) else value
        invalid = [
            (index, item)
            for index, item in enumerate(required)
            if not isinstance(item, str) or not item
        ]
        if invalid:
            raise PropertyError(
                f"{type(self.entity).__name__}.required must return non-empty strings; "
                f"invalid entries: {invalid}",
                entity=self.entity,
            )
        return cast("list[str]", required)

    # Cache Attributes
    @property
    def cache_value(self) -> str:
        if isinstance(self.entity, Entities.PAGE) and self.entity.user:
            return ",".join(self.entity.user.required)

        return ",".join(self.value)

    # Details Attributes
    @property
    def details_value(self) -> list[str]:
        return self.value


class Hash(DetailsMixin, CacheMixin, FilterMixin, AIMixin, DBProperty[str]):
    """Short unique identifier for an entity.

    Generated from entity.urlsafe_key on first access. Retries with random
    short hashes if the deterministic short hash collides. Used in
    permissions, cache search, and filter indexing.

    Get:
        value (str): The entity's unique hash.

    Overrides:
        filter_key: Returns "cache_key" for filter indexing.
    """

    # Property Attributes
    _id = "hash"

    @property
    def ai_key(self) -> str:
        return self.id

    @property
    def ai_value(self) -> str | None:
        value = self.value
        return f"hash:{value}" if value else None

    @property
    def value(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- Computed from the owner and intentionally read-only.
        value = super().value
        if value:
            return value

        if isinstance(self.entity, Entities.USER) and self.entity.page:
            self._value = self.entity.page.hash
        elif self.entity.temporary:
            self._value = random_hash()

        if not self.is_set or not self._value:
            new_hash = short_hash(self.entity.urlsafe_key)
            while cache.check_hash(new_hash):
                new_hash = random_hash()
            self._value = new_hash

        return cast(str, self._value)

    def update(self) -> None:
        self._write_db_value(self.value)

    # Filter Attributes
    _field_type = FieldType.STRING

    @property
    def filter_key(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- The index uses a fixed key.
        return "cache_key"


class DeferredJobReference(DBProperty[dict[str, object]]):
    """Reference metadata for an entity's currently active background job."""

    _id = "deferred_job"
    json = True


class PublicID(DBProperty[str]):
    """Public URL identifier for publicly visible entities.

    Auto-generated on first access using a unique short UUID.
    Only applicable to pages and projects.

    Get:
        value (str): The public URL slug (auto-created if missing).
    """

    # Property Attributes
    _id = "public_id"
    _label = "Public"
    _icon = "public"
    _kind = "page"

    @property
    def value(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- Computed from the owner and intentionally read-only.
        if self.entity.db.get("public_id"):
            return cast(str, self.entity.db["public_id"])
        return self._create_public_id()

    def _create_public_id(self) -> str:
        unique_id = False
        while not unique_id:
            new_id = short_uuid()
            entity = database_get.public_pages(new_id)
            if not entity:
                unique_id = new_id

        self._write_db_value(unique_id)
        return unique_id


class IsPublic(FilterMixin, DBProperty[bool, "Entity", bool]):
    """Whether an entity is publicly visible.

    Set:
        value (bool): Public visibility flag.

    Get:
        filter_value (bool): True if public, False otherwise.
    """

    _id = "public"
    _label = "Public"
    _icon = "public"

    @property
    def value(self) -> bool:
        return cast(bool, self.entity.db.get("public", False))

    @value.setter
    def value(self, value: bool) -> None:
        self._write_public(value)

    def _write_public(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("public must be a boolean")

        self.entity.db["public"] = value

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.PUBLIC.value

    @property
    def filter_value(self) -> bool:
        return bool(self.value)

    @property
    def filter_key(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- The index uses a fixed key.
        return "is_public"

    @property
    def filter_label(self) -> str:
        return "Is Public"

    @property
    def filter_kind(self) -> str:
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value: str) -> None:
        self._filter_kind = value


class AiGenerated(DBProperty[bool]):
    """Flag indicating whether an entity was generated by AI."""

    _id = "ai_generated"

    @property
    def value(self) -> bool:
        return cast(bool, self.entity.db.get("ai_generated", False))

    @value.setter
    def value(self, value: bool | None) -> None:
        if not value:
            self.entity.db.pop("ai_generated", None)

        self.entity.db["ai_generated"] = True


class Active(DBProperty[bool, "Entity", bool]):
    """Whether an entity is active.

    Inactive entities are excluded from normal active-entity queries. Task
    completion is tracked by task-specific completion fields.

    Set:
        value (bool): Active flag.

    Get:
        value (bool): False for public-user pages; otherwise stored flag if
        True/False, defaulting to True when unset.
    """

    # Property Attributes
    _id = "active"

    @property
    def value(self) -> bool:
        user = cast("User | None", getattr(self.entity, "user", None))
        if user and user.is_public:
            return False
        return cast(bool, self.entity.db.get(self.id, True))

    @value.setter
    def value(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("active must be a boolean")

        self._write_db_value(value)

    def update(self) -> None:
        if self.id in self.entity.db:
            return

        self._write_db_value(self.value)


class Permissions[Owner: Entity = "Entity"](DBProperty[dict[str, str], Owner, dict[str, str] | None]):
    """Permission map for an entity.

    Stores a dict mapping resource hashes/names to Action level names.
    Used by has_permission() to check access.

    Set:
        value (dict): {resource_hash: Action.name}.

    Get:
        value (dict): {resource_hash: Action.name} (defaults to {}).
        form: Permission editing form for the UI.
    """

    # Property Attributes
    _id = "permissions"
    json = True

    @property
    def value(self) -> dict[str, str]:
        return super().value or {}

    @value.setter
    def value(self, value: dict[str, str] | None) -> None:
        self._write_db_value(value)

    if TYPE_CHECKING:
        def permissions_form(self) -> dict[str, object]: ...

    @property
    def form(self) -> dict[str, object]:
        if getattr(self, "_form", None):
            return self._form

        self._form = self.permissions_form()
        return self._form


class RestrictedTo(DBProperty[dict[str, list[str]], RestrictionOwner]):
    """Local group storage and effective restrictions separated by source.

    Set:
        value (list): List of group hashes.

    Get:
        value (dict): Match one group in each independent source clause.
        stored (list): Independent copy of explicitly stored group hashes.
    """

    # Property Attributes
    _id = "restricted_to"
    _label = "Restricted To"
    _icon = "group"

    @property
    def value(self) -> dict[str, list[str]]:  # pyright: ignore[reportIncompatibleMethodOverride] -- Computed from the owner and intentionally read-only.
        kind = getattr(self.entity, "entity_kind", None)
        if kind == "form":
            source = "task_form" if getattr(self.entity, "form_type", None) == "task" else "page_form"
            restrictions = {source: self.stored}
        elif kind == "page":
            form = permission_relation(self.entity, "form")
            restrictions = {
                "page": self.stored,
                "page_form": cast("Form", form).properties.restricted_to.stored if form else [],
            }
        elif kind == "task":
            page = permission_relation(self.entity, "page", required=True)
            form = permission_relation(self.entity, "form")
            restrictions = {
                **cast("Page", page).restricted_to,
                "task_form": cast("Form", form).properties.restricted_to.stored if form else [],
            }
        elif kind == "file":
            owner = cast("File", self.entity).owner
            restrictions = owner.restricted_to if owner else {}
        else:
            restrictions = {}
        return normalize_restrictions(restrictions)

    def materialize(self, *, admin_only: bool | None = None) -> None:
        """Project attached local groups into storage; inheritance stays computed."""
        if self.entity.entity_kind not in {"form", "page"}:
            return
        # Fetch-time materialization must not rewrite stored relation keys.
        if admin_only is True:
            self.entity.groups = []
        if admin_only is None:
            admin_only = self.stored == ["admin"]
        if admin_only:
            restrictions = ["admin"]
        else:
            groups = cast("Form", self.entity).properties.groups
            if groups.keys and not groups.is_set:
                return
            hashes = [group.hash for group in groups.value] if groups.keys else []
            restrictions = sorted(set(hashes))
        if restrictions != self.stored:
            self.entity._permission_sources_changed = True
        if restrictions:
            self.entity.db[self.id] = restrictions
        else:
            self.entity.db.pop(self.id, None)
        self.unset()
        self.entity._details = None
        self.entity._to_cache = None

    @property
    def stored(self) -> list[str]:
        value = self.entity.db.get(self.id)
        return list(value) if isinstance(value, list) else []

    def add(self, value: str) -> None:
        existing = self.stored

        if isinstance(value, str):
            existing.append(value)
            self.entity.db[self.id] = list(dict.fromkeys(existing))

        self.unset()

    def remove(self, value: str) -> None:
        existing = self.stored

        if isinstance(value, str):
            existing = [v for v in existing if v != value]
            if not existing:
                self.entity.db.pop(self.id, None)
            else:
                self.entity.db[self.id] = existing

        self.unset()
