from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast

import json
from flask import url_for
from ..definitions import Fetch
from ..mixins import AssetMixin
from ..properties import (
    common_entity,
    common_related,
    form,
    form_special,
    schema,
)
from .entity import Entity, EntityProperties
from . import Entities
from lagniappe.core.tools.database import get as database_get


if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..definitions.asset import AssetUpload, HTMLAsset
    from ..properties.row_submission import ColumnField
    from ..properties.schema import SchemaField
    from . import property_types
    from .category import Category
    from .project import Project


class Form(Entity, AssetMixin):
    if TYPE_CHECKING:
        @property
        def restricted_to(self) -> dict[str, list[str]]: ...

        categories: list[Category]
        projects: list[Project]
        _pending_html: dict[str, str]
        schema_format: int | None
        version: str | None
        generation: int
        form_type: str | None
        schema: list[dict[str, object]]

        @property
        def filters(self) -> form.FormFilters: ...

        @property
        def properties(self) -> property_types.FormProperties: ...

    entity_kind = "form"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"schema", "schema_format", "version", "form_draft_receipt", "pending_form_change"})

    @property
    def required(self) -> list[str]:
        return ["forms"]

    @property
    def url(self) -> str:
        return url_for("forms.view", key=self.urlsafe_key)

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "categories": common_related.Categories,
                "projects": common_related.Projects,
                "form_type": form.FormType,
                "schema": schema.Schema,
                "schema_format": schema.SchemaFormat,
                "filters": form.FormFilters,
                "restricted_to": common_entity.RestrictedTo,
                "groups": common_related.Groups,
                "version": form.SchemaVersion,
                "generation": form.FormGeneration,
            }
        )
        return properties

    @property
    def fields(self) -> dict[str, SchemaField]:
        return self.properties.schema.fields

    @property
    def table_fields(self) -> dict[str, ColumnField]:
        return self.properties.schema.table_fields

    def get_html_field(self, field_id: str) -> str | None:
        pending = getattr(self, "_pending_html", {})
        if field_id in pending:
            return pending[field_id] or None
        html_asset = self.get_asset(field_id)
        if not html_asset:
            return None
        return cast("HTMLAsset", html_asset).html()

    def set_html_field(self, field_id: str, html: str | None) -> None:
        if not isinstance(field_id, str) or not isinstance(html, (str, type(None))):
            raise ValueError("HTML fields require a field ID and text content.")
        if not hasattr(self, "_pending_html"):
            self._pending_html = {}
        self._pending_html[field_id] = html or ""

    def add_html_field_image(self, field_id: str, image: AssetUpload, visibility: str = "private") -> str | None:
        field = self.fields.get(field_id)
        if not field:
            field = form_special.HTML(
                {"id": field_id, "type": "html", "title": field_id},
                entity=self,
            )
        return cast(form_special.HTML, field).add_image(image, visibility)

    @property
    def html_fields(self) -> list[form_special.HTML]:
        return self.properties.schema.html_fields

    @property
    def used_by(self) -> list[Entity]:
        return [
            entity for entity in Entities.fetch(
                self, *database_get.form_users(self), request=Fetch.direct(),
            )
            if entity.key != self.key
        ]

    @classmethod
    def create(cls, data: Mapping[str, object], *, key: Key | None = None) -> Self:
        form = cls(key)
        form.kind = cls.entity_kind
        form.update(data)

        return form

    def set_schema(self, value: object) -> list[dict[str, object]]:
        """Apply the one canonical durable schema write contract."""

        self.properties.schema.value = value
        return self.schema

    def update(self, data: Mapping[str, object]) -> None:
        if data.get("name"):
            self.name = cast("str | list[object]", data["name"])

        if data.get("form-type"):
            self.form_type = cast(str, data["form-type"])

        if "schema" in data:
            raw = data["schema"]
            schema_definition = json.loads(raw) if isinstance(raw, str) else raw
            self.set_schema(schema_definition)
