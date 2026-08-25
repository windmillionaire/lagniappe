from flask import url_for
from ..properties import category, common_entity, common_related
from ..tools import database
from .entity import Entity
from .index import PageIndex

UNCATEGORIZED_PAGES_NAME = "Uncategorized Pages"


# @testable true
# @tests tests_unit/test_007_category_properties.py::test_category_schema
# @matrix category form-schema : delegation schema
class Category(Entity):
    entity_kind = "category"

    @property
    def exclude_from_index(self):
        return frozenset({"description"})

    @property
    def required(self):
        return ["models", self.hash]

    @property
    def url(self):
        return url_for("categories.index", key=self.urlsafe_key)

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "form": common_related.AttachedForm,
                "forms": common_related.RelatedForms,
                "description": common_entity.Description,
                "restricted_to": common_entity.RestrictedTo,
                "attributes": common_entity.Attributes,
                "filters": category.CategoryFilters,
                "ai_generated": common_entity.AiGenerated,
            }
        )
        return properties

    def index(self, *args, **kwargs):
        return PageIndex(*args, entity=self, **kwargs)

    @property
    def schema(self):
        return self.form.schema if self.form else None

    @classmethod
    def create(cls, data):
        new_category = cls()
        new_category.kind = cls.entity_kind

        new_category.update(data)
        return new_category

    # @testable true
    # @tests tests_unit/test_012_category_conditions.py::test_category_string_filters
    # @tests tests_unit/test_012_category_conditions.py::test_category_boolean_filters
    # @tests tests_unit/test_012_category_conditions.py::test_category_timestamp_filters
    # @tests tests_unit/test_012_category_conditions.py::test_category_entity_filters
    # @matrix category : boolean condition-definition entity-valued string timestamp
    def update(self, data):
        self.form = data.get("form")
        self.name = data.get("name")
        self.attributes = data.get("attributes")
        self.description = data.get("description")

    # @testable true
    # @tests tests_unit/test_007_category_properties.py::test_uncategorized_pages_get_create
    # @matrix category pages : default-category get-create
    @classmethod
    def get_uncategorized_pages(cls):
        exists = database.get.category_by_name(UNCATEGORIZED_PAGES_NAME)
        if exists:
            return cls(exists)

        category = cls.create({"name": UNCATEGORIZED_PAGES_NAME})
        category.save()
        return category


# @testable true
# @tests tests_unit/test_009b_user_permissions.py::test_users_category_uses_users_scope_not_models_scope
# @matrix category permissions users : models-scope users-category
class UserCategory(Category):
    entity_kind = "users"

    @property
    def required(self):
        return ["users"]

    @classmethod
    def get(cls):
        return cls(database.get.reserved("users"))
