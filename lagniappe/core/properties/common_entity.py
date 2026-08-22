from datetime import datetime, timezone

from ..definitions import (
    Attribute,
    EntityAttributes,
    FieldType,
    FilterOptions,
    Ordering,
)
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
from ..tools import cache, database
from ..tools.files.html import strip_tags
from .base_db import DBProperty


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_name
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_name_list_values_normalized_on_write_and_import
# @features name
# @dimensions property, details, filter, list-normalization, import
class Name(CacheMixin, ColumnMixin, DetailsMixin, AIMixin, FilterMixin, DBProperty):
    """Entity name. Primary display and search identifier.

    Strips "The " prefix for lexical sorting.

    Set:
        value (str): Entity name.

    Get:
        value (str): Entity name.
        column_value (dict): Full entity details dict for table display.
        sort_value (str): Lowercase name with "The " stripped.

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = []

    @property
    def schema(self):
        return {"type": "input", "input": "text"}

    @property
    def value(self):
        return DBProperty.value.fget(self)

    @value.setter
    def value(self, value):
        if isinstance(value, list):
            value = " ".join(
                str(v).strip() for v in value if v is not None and str(v).strip()
            )
        DBProperty.value.fset(self, value or None)

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_name
    # @features name
    # @dimensions sort
    @property
    def sort_value(self):
        return self.value.replace("The ", "").lower() if self.value else None

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_name
    # @features name
    # @dimensions column
    @property
    def column_value(self):
        return self.entity.details

    # AI Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_name
    # @features name
    # @dimensions ai
    @property
    def ai_key(self):
        return f"{self.entity.entity_kind}_name"

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value
    _filter_key = "name"

    @property
    def filter_label(self):
        return f"{self.filter_kind.capitalize()} Name"

    @property
    def filter_kind(self):
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value):
        self._filter_kind = value

    # Column Attributes
    @property
    def link(self):
        return getattr(self, "_link", True)

    @link.setter
    def link(self, value):
        self._link = value

    @property
    def parent(self):
        return getattr(self, "_parent", True)

    @parent.setter
    def parent(self, value):
        self._parent = value

    # Cache Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_name
    # @features name
    # @dimensions cache
    @property
    def cache_value(self):
        return self.value

    # Ingress Attributes
    def validate_import(self, value):
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


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_description
# @tests tests_unit/test_013_task_properties.py::test_task_description
# @features project, task
# @dimensions column
class Description(CacheMixin, ColumnMixin, AIMixin, FilterMixin, DBProperty):
    """Entity description. HTML tags are stripped on set.

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

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_description
    # @tests tests_unit/test_013_task_properties.py::test_task_description
    # @features project, task
    # @dimensions description, html-stripping
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, strip_tags(value))

    @property
    def kind(self):
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
    def sort_value(self):
        return True if self.value else False

    @property
    def filter_kind(self):
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value):
        self._filter_kind = value

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_description
    # @tests tests_unit/test_013_task_properties.py::test_task_description
    # @features project, task
    # @dimensions filter-value
    @property
    def filter_value(self):
        return self.value if self.value else None

    # Cache Attributes
    _cache_key = "desc"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_description
    # @tests tests_unit/test_013_task_properties.py::test_task_description
    # @features project, task
    # @dimensions cache
    @property
    def cache_value(self):
        return self.value

    # AI Attributes
    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_description
    # @tests tests_unit/test_013_task_properties.py::test_task_description
    # @features project, task
    # @dimensions ai-value
    @property
    def ai_key(self):
        if isinstance(self.entity, Entities.PAGE):
            return "page_description"
        elif isinstance(self.entity, Entities.TASK):
            return "task_description"
        return "description"


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_created_update_initializes_once
# @features created
# @dimensions update, initialized-once
class Created(DateMixin, ColumnMixin, FilterMixin, DBProperty):
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

    def update(self):
        if super().value:
            return

        DBProperty.value.fset(self, datetime.now(timezone.utc))

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _selected = False
    _editable = False


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_entity_modified
# @features modified
# @dimensions property, date, column, filter
class Modified(DateMixin, ColumnMixin, FilterMixin, DBProperty):
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

    def update(self):
        DBProperty.value.fset(self, datetime.now(timezone.utc))

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _selected = False
    _editable = False

    @property
    def filter_label(self):
        return "Last Modified"

    @property
    def filter_kind(self):
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value):
        self._filter_kind = value

    @property
    def details_value(self):
        return self.value.isoformat()


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::Kind.db_key
# @covered-by lagniappe/core/properties/common_entity.py::Kind.details_value
# @covered-by lagniappe/core/properties/common_entity.py::Kind.cache_value
# @reason Kind behavior is owned by its db/details/cache accessors
class Kind(DetailsMixin, CacheMixin, DBProperty):
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
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_kind
    # @features kind
    # @dimensions property, db-key
    @property
    def db_key(self):
        return "type"

    # Details Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_kind
    # @features kind
    # @dimensions details
    @property
    def details_value(self):
        if isinstance(self.entity, Entities.PAGE) and self.entity.db.get("user"):
            return "user"

        return self.value

    # Cache Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_kind
    # @features kind
    # @dimensions cache
    @property
    def cache_value(self):
        return self.details_value


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::Requires.value
# @covered-by lagniappe/core/properties/common_entity.py::Requires.cache_value
# @covered-by lagniappe/core/properties/common_entity.py::Requires.details_value
# @reason Requires behavior is owned by its value/details/cache accessors
class Requires(CacheMixin, DetailsMixin, DBProperty):
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

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_requires
    # @tests tests_unit/test_006b_ingress_entity.py::test_model_task_required_reports_unloaded_project_relation
    # @features requires
    # @dimensions property validation
    @property
    def value(self):
        value = super().value
        if value:
            return value

        self._value = self._required()
        return self._value

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, self._validate(value))

    # @testable false
    # @covered-by lagniappe/core/mutations/executor.py::_prepare_write
    def update(self):
        DBProperty.value.fset(self, self._required())

    def _required(self):
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

    def _validate(self, value):
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
        return required

    # Cache Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_requires
    # @features requires
    # @dimensions cache
    @property
    def cache_value(self):
        if isinstance(self.entity, Entities.PAGE) and self.entity.user:
            return ",".join(self.entity.user.required)

        return ",".join(self.value)

    # Details Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_requires
    # @features requires
    # @dimensions details
    @property
    def details_value(self):
        return self.value


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::Hash.value
# @covered-by lagniappe/core/properties/common_entity.py::Hash.filter_key
# @reason Hash behavior is owned by value generation and filter-key projection
class Hash(DetailsMixin, CacheMixin, FilterMixin, AIMixin, DBProperty):
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
    def ai_key(self):
        return self.id

    @property
    def ai_value(self):
        value = self.value
        return f"hash:{value}" if value else None

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_hash
    # @features hash
    # @dimensions property, details, cache
    @property
    def value(self):
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

        return self._value

    def update(self):
        DBProperty.value.fset(self, self.value)

    # Filter Attributes
    _field_type = FieldType.STRING

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_hash
    # @features hash
    # @dimensions filter
    @property
    def filter_key(self):
        return "cache_key"


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_attributes_empty_list_stays_persisted
# @features project
# @dimensions attributes blank-persistence
class Attributes(DBProperty):
    """Configurable entity attributes (e.g. scheduling, document features).

    Stores a list of active attribute names in entity.db. On get, returns
    initialized Attribute objects. Falls back to the entity's model
    attributes if none are set directly.

    Set:
        value (list): Attribute names or Attribute objects.

    Get:
        value (list[Attribute]): Initialized Attribute objects.
    """

    # Property Attributes
    _id = "attributes"
    _blank_values = (None,)

    @property
    def kind(self):
        return self.entity.entity_kind

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_attributes
    # @tests tests_unit/test_007_category_properties.py::test_category_attributes
    # @tests tests_unit/test_008_page_properties.py::test_page_attributes
    # @features project, category, page
    # @dimensions attributes, defaults
    @property
    def value(self):
        if self.is_set:
            return self._value

        selected = super().value
        if (
            not isinstance(selected, list)
            and self.entity.properties.get("model")
            and self.entity.model
        ):
            self._value = self.entity.model.attributes
            return self._value

        self._value = EntityAttributes[self.kind].initialize(self.entity, selected)

        return self._value

    @value.setter
    def value(self, names):
        if names is None:
            DBProperty.value.fset(self, None)
            return

        names = names if isinstance(names, list) else []

        if all(isinstance(n, str) for n in names):
            self._value = EntityAttributes[self.kind].initialize(self.entity, names)
        elif names and all(isinstance(n, Attribute) for n in names):
            self._value = names
        else:
            selected = super().value
            if (
                selected is None
                and self.entity.properties.get("model")
                and self.entity.model
            ):
                self._value = self.entity.model.attributes
            elif selected is None:
                self._value = EntityAttributes[self.kind].initialize(self.entity)
            else:
                self._value = EntityAttributes[self.kind].initialize(
                    self.entity, selected
                )

        self.entity.db[self.id] = [a.name for a in self._value if a.active]


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_deferred_job_reference_round_trips
# @pairs deferred-jobs:active-operation pages:create-autofill
class DeferredJobReference(DBProperty):
    """Reference metadata for an entity's currently active background job."""

    _id = "deferred_job"
    json = True


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_public_id_generation_is_unique_and_persisted
# @features public-id
# @dimensions generation, uniqueness, persistence
class PublicID(DBProperty):
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
    def value(self):
        if self.entity.db.get("public_id"):
            return self.entity.db["public_id"]
        return self._create_public_id()

    def _create_public_id(self):
        unique_id = False
        while not unique_id:
            new_id = short_uuid()
            entity = database.get.public_pages(new_id)
            if not entity:
                unique_id = new_id

        DBProperty.value.fset(self, unique_id)
        return unique_id


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::IsPublic.value
# @covered-by lagniappe/core/properties/common_entity.py::IsPublic.filter_value
# @reason public visibility behavior is owned by value storage and filter projection
class IsPublic(FilterMixin, DBProperty):
    """Whether an entity is publicly visible.

    Set:
        value (bool): Public visibility flag.

    Get:
        filter_value (bool): True if public, False otherwise.
    """

    _id = "public"
    _label = "Public"
    _icon = "public"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_is_public
    # @tests tests_unit/test_008_page_properties.py::test_page_public
    # @tests tests_unit/test_009a_user.py::test_user_is_public
    # @features project, page, user
    # @dimensions public
    @property
    def value(self):
        return self.entity.db.get("public", False)

    @value.setter
    def value(self, value):
        if not isinstance(value, bool):
            raise TypeError("public must be a boolean")

        self.entity.db["public"] = value

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.PUBLIC.value

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_is_public
    # @tests tests_unit/test_008_page_properties.py::test_page_public
    # @features project, page
    # @dimensions filter-value
    @property
    def filter_value(self):
        return True if self.value else False

    @property
    def filter_key(self):
        return "is_public"

    @property
    def filter_label(self):
        return "Is Public"

    @property
    def filter_kind(self):
        return self._filter_kind or self.kind

    @filter_kind.setter
    def filter_kind(self, value):
        self._filter_kind = value


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_ai_mode
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_ai_mode
# @features projects, categories
# @dimensions ai-generated, ai-create
class AiGenerated(DBProperty):
    """Flag indicating whether an entity was generated by AI."""

    _id = "ai_generated"

    @property
    def value(self):
        return self.entity.db.get("ai_generated", False)

    @value.setter
    def value(self, value):
        if not value:
            self.entity.db.pop("ai_generated", None)

        self.entity.db["ai_generated"] = True


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::Active.value
# @reason Active behavior is owned by the value accessor
class Active(DBProperty):
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

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_active
    # @tests tests_unit/test_002_entity_general_properties.py::test_entity_active_rejects_non_bool
    # @features active
    # @dimensions property, public-user validation
    @property
    def value(self):
        if getattr(self.entity, "user", None) and self.entity.user.is_public:
            return False
        return self.entity.db.get(self.id, True)

    @value.setter
    def value(self, value):
        if not isinstance(value, bool):
            raise TypeError("active must be a boolean")

        DBProperty.value.fset(self, value)

    # @testable false
    # @covered-by lagniappe/core/mutations/executor.py::_prepare_write
    def update(self):
        if self.id in self.entity.db:
            return

        DBProperty.value.fset(self, self.value)


# @testable infrastructure
# @covered-by lagniappe/core/properties/user_permissions.py::UserPermissions.create
# @covered-by lagniappe/core/properties/user_groups.py::GroupPermissions.create
# @covered-by lagniappe/core/properties/user_groups.py::PublicPermissions.create
class Permissions(DBProperty):
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
    def value(self):
        return super().value or {}

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)

    @property
    def form(self):
        if getattr(self, "_form", None):
            return self._form

        self._form = self.permissions_form()
        return self._form


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::RestrictedTo.value
# @covered-by lagniappe/core/properties/common_entity.py::RestrictedTo.add
# @reason restricted-to behavior is owned by value resolution and explicit mutation
class RestrictedTo(CacheMixin, DBProperty):
    """List of user groups restricted to a form.

    Set:
        value (list): List of group hashes.

    Get:
        value (list): Effective group hashes, including the owner fallback.
        stored (list): Independent copy of explicitly stored group hashes.
        column_value (str | None): Comma-separated group names for table display.
    """

    # Property Attributes
    _id = "restricted_to"
    _label = "Restricted To"
    _icon = "group"

    # @testable true
    # @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_owner_can_restrict_form_to_site_owner
    # @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_group_restricted_form_opens_for_group_member_only
    # @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_form_index_lists_group_restricted_form_only_for_group_member
    # @tests tests_unit/test_002_entity_general_properties.py::test_restricted_to_effective_projection_does_not_alias_sources
    # @features forms
    # @dimensions access-restrictions owner-restricted group-restricted index-filter inheritance side-effect-free stable-order
    @property
    def value(self):
        if self.is_set:
            return self._value

        restrictions = self.stored
        if not restrictions:
            page = getattr(self.entity, "page", None)
            restrictions = page.restricted_to if page else None
        if not restrictions:
            form = getattr(self.entity, "form", None)
            restrictions = form.restricted_to if form else None
        if not restrictions:
            groups = getattr(self.entity, "groups", None)
            restrictions = [group.hash for group in groups] if groups else None

        if isinstance(restrictions, list):
            self._value = list(dict.fromkeys([*restrictions, "owner"]))
        else:
            self._value = restrictions or False

        return self._value

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_restricted_to_effective_projection_does_not_alias_sources
    # @features forms
    # @dimensions access-restrictions stored-projection side-effect-free
    @property
    def stored(self):
        value = self.entity.db.get(self.id)
        return list(value) if isinstance(value, list) else []

    # @testable true
    # @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_owner_can_restrict_form_to_site_owner
    # @tests tests_unit/test_002_entity_general_properties.py::test_restricted_to_add_preserves_first_seen_order
    # @features forms
    # @dimensions access-restrictions owner-restricted stable-order side-effect-free
    def add(self, value):
        existing = self.stored

        if isinstance(value, str):
            existing.append(value)
            self.entity.db[self.id] = list(dict.fromkeys(existing))

        self.unset()

    def remove(self, value):
        existing = self.stored

        if isinstance(value, str):
            existing = [v for v in existing if v != value]
            if not existing:
                self.entity.db.pop(self.id, None)
            else:
                self.entity.db[self.id] = existing

        self.unset()

    # Cache Attributes
    @property
    def cache_value(self):
        return ",".join(self.value) if self.value else None
