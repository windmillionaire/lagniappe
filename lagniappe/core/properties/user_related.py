from ..definitions import Fetch, MutationIntent, Ordering, PageAttributes
from ..entities import Entities
from ..mixins import (
    ColumnMixin,
    FilterMixin,
    RelatedEntityListMixin,
    RelatedEntityMixin,
)
from .base_db import DBProperty


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_groups_membership_changes_recalculate_permissions
# @tests tests_unit/test_009a_user.py::test_user_groups_reject_invalid_relation_inputs
# @tests tests_unit/test_009a_user.py::test_public_user_groups_force_public_group_only
# @matrix user-groups : membership-change permission-recalc public-user relation-storage
class Groups(RelatedEntityListMixin, FilterMixin, ColumnMixin, DBProperty):
    """Groups a user belongs to.

    Changing group membership triggers a permission recalculation.

    Set:
        value (list): Group entities. Triggers permissions.create()
            if the set changes.

    Get:
        value (list): Group entities.
    """

    # Property Attributes
    _id = "groups"
    _label = "Groups"
    _ordering = Ordering.CATEGORICAL
    _icon = "group"

    @property
    def value(self):
        value = RelatedEntityListMixin.value.fget(self)
        if self.entity.is_public and not self._is_public_only(value):
            value = [self._public_group(value)]
            RelatedEntityListMixin.value.fset(self, value)
        return value

    @value.setter
    def value(self, value):
        if value is not None and not isinstance(value, list):
            raise TypeError("Value must be a list")

        value = value or []
        if self.entity.is_public:
            value = [self._public_group(value)]

        for group in value:
            if not getattr(group, "key", None):
                raise ValueError("Value must have a key")

        existing = [g.key for g in RelatedEntityListMixin.value.fget(self)]
        new = [g.key for g in value]

        if not set(existing) == set(new):
            RelatedEntityListMixin.value.fset(self, value)
            self.entity.properties.permissions.create()

    # DB Attributes
    def add(self, value):
        if not getattr(value, "key", None):
            raise ValueError("Value must have a key")

        if self.entity.is_public:
            existing_value = RelatedEntityListMixin.value.fget(self)
            public_group = self._public_group(existing_value)
            existing = [g.key for g in existing_value]
            self.value = [public_group]
            return set(existing) != {public_group.key}

        if super().add(value):
            self.entity.properties.permissions.create()

    def _public_group(self, value=None):
        for group in value or []:
            if self._is_public_group(group):
                return group
        return Entities.PUBLIC_GROUP.get()

    def _is_public_only(self, value):
        return len(value) == 1 and self._is_public_group(value[0])

    @staticmethod
    def _is_public_group(group):
        return (
            getattr(group, "kind", None) == "public_group"
            or getattr(group, "entity_kind", None) == "public_group"
            or getattr(group, "name", None) == "public"
        )


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_page_auto_create_lazy_load_and_owner_link
# @tests tests_unit/test_009a_user.py::test_user_page_missing_key_raises_runtime_error
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_reassign_and_remove_user_from_page
# @matrix user : auto-create lazy-load owner-link personal-page
# @pair user-settings:page-remove
class UserPage(RelatedEntityMixin, DBProperty):
    """The page entity associated with a user.

    Auto-created if not provided. The user entity handles auth and
    permissions; all other user data (notes, tasks, etc.) lives on
    this page. Setting the page also syncs the user's hash.

    Set:
        value (Entity | None): Page entity. None creates a new user page.

    Get:
        value (Entity): The user's page entity.
    """

    # Property Attributes
    _id = "page"

    @property
    def value(self):
        if self.is_set:
            return self._value

        key = self.entity.db.get(self.id)
        if not key:
            raise RuntimeError("User page key not found")
        self._value = Entities.fetch_one(key, request=Fetch.direct())
        self._value.user = self.entity
        self._cache_attached_entities()
        return self._value

    @value.setter
    def value(self, page):
        user_model = self._user_model(page)
        if not page:
            page = self._create_user_page(user_model)

        self._set_user_model(page, user_model)
        if self.entity.is_public:
            page.attributes = self._public_user_page_attributes()
        RelatedEntityMixin.value.fset(self, page)
        page.user = self.entity
        self.entity.add_mutation_intents(
            MutationIntent.standard(page, reason="user-page-mirror")
        )

    def _create_user_page(self, user_model):
        data = {
            "model": user_model,
            "user": self.entity,
            "name": self.entity.name,
        }
        if self.entity.is_public:
            data["attributes"] = self._public_user_page_attributes()
        return Entities.PAGE.create(data)

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_page_auto_create_lazy_load_and_owner_link
    # @tests tests_unit/test_009a_user.py::test_user_create_public_user_assigns_public_group
    # @matrix public-users : limited-attrs personal-page
    def _public_user_page_attributes(self):
        return [
            attribute.value.name
            for attribute in PageAttributes
            if attribute.value.name not in {"files", "photo"}
        ]

    def _user_model(self, page=None):
        model = page.model if page else None
        if isinstance(model, Entities.USERS):
            return model
        return Entities.USERS.get()

    def _set_user_model(self, page, user_model):
        categories = page.categories
        page.model = user_model
        page.categories = categories


# @testable true
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_file
# @tests tests_unit/test_009a_user.py::test_user_starred_cleanup_removes_stale_keys
# @matrix starred : category file page project stale-cleanup
class Starred(RelatedEntityListMixin, DBProperty):
    """Entities the user has starred (bookmarked).

    Supports toggling and bulk deletion of stale keys.

    Get:
        value (list): Starred entities.
    """

    # Property Attributes
    _id = "starred"
    _label = "Starred"

    def toggle_star(self, entity):
        if entity.key in [s.key for s in self.value]:
            self.remove(entity)
            return False
        else:
            self.add(entity)
            return True

    def delete_starred_keys(self, keys):
        for key in keys:
            self.entity.db[self.id].remove(key)
