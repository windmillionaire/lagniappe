from typing import TYPE_CHECKING, Self, TypedDict, Unpack, cast

from flask import url_for
from ..properties import category, common_entity, common_related
from lagniappe.core.tools.database import get as database_get
from .entity import Entity, EntityProperties
from .index import CollectionOptions, PageIndex


if TYPE_CHECKING:
    from google.cloud.datastore import Entity as Row, Key

    from . import property_types
    from .form import Form

UNCATEGORIZED_PAGES_NAME = "Uncategorized Pages"


class CategoryData(TypedDict, total=False):
    name: str | None
    description: str | None
    form: Form | None


class Category(Entity):
    if TYPE_CHECKING:
        description: str | None

        @property
        def filters(self) -> category.CategoryFilters: ...

        form: Form | None
        forms: list[Form]

        @property
        def properties(self) -> property_types.CategoryProperties: ...

    entity_kind = "category"
    retired_fields = frozenset({"attributes"})

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"description"})

    @property
    def required(self) -> list[str]:
        return ["models", self.hash]

    @property
    def url(self) -> str:
        return url_for("categories.index", key=self.urlsafe_key)

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "form": common_related.AttachedForm,
                "forms": common_related.RelatedForms,
                "description": common_entity.Description,
                "filters": category.CategoryFilters,
                "ai_generated": common_entity.AiGenerated,
            }
        )
        return properties

    def index(self, *args: object, **kwargs: Unpack[CollectionOptions]) -> PageIndex:
        return PageIndex(*args, entity=self, **kwargs)

    @property
    def schema(self) -> list[dict[str, object]] | None:
        return self.form.schema if self.form else None

    @classmethod
    def create(cls, data: CategoryData, *, key: Key | None = None) -> Self:
        new_category = cls(key)
        new_category.kind = cls.entity_kind

        new_category.update(data)
        return new_category

    def update(self, data: CategoryData) -> None:
        self.form = data.get("form")
        self.name = data.get("name")
        self.description = data.get("description")

    @classmethod
    def get_uncategorized_pages(cls) -> Self:
        exists = database_get.category_by_name(UNCATEGORIZED_PAGES_NAME)
        if exists:
            return cls(exists)

        category = cls.create({"name": UNCATEGORIZED_PAGES_NAME})
        category.save()
        return category


class UserCategory(Category):
    entity_kind = "users"

    @property
    def required(self) -> list[str]:
        return ["users"]

    @classmethod
    def get(cls) -> Self:
        return cls(cast("Row", database_get.reserved("users")))
