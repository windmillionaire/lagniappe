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


# @testable false
# @covered-by lagniappe/core/entities/form.py::Form.update
# @covered-by lagniappe/core/mutations/save.py::FormMutation.plan_save
# @covered-by lagniappe/core/properties/form.py::SchemaVersion
# @reason focused methods/properties own the durable Form behavior
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

    # @testable true
    # @matrix forms html-field : draft no-write
    def get_html_field(self, field_id: str) -> str | None:
        pending = getattr(self, "_pending_html", {})
        if field_id in pending:
            return pending[field_id] or None
        html_asset = self.get_asset(field_id)
        if not html_asset:
            return None
        return cast("HTMLAsset", html_asset).html()

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_builder_draft_and_staged_html_are_read_only
    # @matrix forms html-field : draft baseline no-write
    def set_html_field(self, field_id: str, html: str | None) -> None:
        if not isinstance(field_id, str) or not isinstance(html, (str, type(None))):
            raise ValueError("HTML fields require a field ID and text content.")
        if not hasattr(self, "_pending_html"):
            self._pending_html = {}
        self._pending_html[field_id] = html or ""

    # @testable true
    # @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
    # @matrix html-field : asset-lifecycle image-upload unsaved-schema
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

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_save_refreshes_users_with_edited_form_schema
    # @matrix forms cache : owner-reuse no-extra-read
    # @pair form-schema:cache
    @property
    def used_by(self) -> list[Entity]:
        return [
            entity for entity in Entities.fetch(
                self, *database_get.form_users(self), request=Fetch.direct(),
            )
            if entity.key != self.key
        ]

    # @testable true
    # @tests tests_unit/test_032h_report_batches.py::test_dependent_creations_share_one_commit
    # @matrix ai-report : identity
    @classmethod
    def create(cls, data: Mapping[str, object], *, key: Key | None = None) -> Self:
        form = cls(key)
        form.kind = cls.entity_kind
        form.update(data)

        return form

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_schema_write_gateway_canonicalizes_without_adding_page_fields
    # @matrix form-schema : canonicalization membership write-gateway
    def set_schema(self, value: object) -> list[dict[str, object]]:
        """Apply the one canonical durable schema write contract."""

        self.properties.schema.value = value
        return self.schema

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_update_sets_name_form_type_and_schema
    # @matrix form : form-type schema update
    def update(self, data: Mapping[str, object]) -> None:
        if data.get("name"):
            self.name = cast("str | list[object]", data["name"])

        if data.get("form-type"):
            self.form_type = cast(str, data["form-type"])

        if "schema" in data:
            raw = data["schema"]
            schema_definition = json.loads(raw) if isinstance(raw, str) else raw
            self.set_schema(schema_definition)
