import json
from collections.abc import Mapping
from types import MappingProxyType
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
from .entity import Entity
from . import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.form_definitions import definition_version


# @testable false
# @covered-by lagniappe/core/entities/form.py::Form.__init__
# @reason retain serialized fields without copying their contents or hydrating relations
def _retained_form_value(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _retained_form_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_retained_form_value(item) for item in value)
    return value


# @testable false
# @covered-by lagniappe/core/tools/form_drafts.py::prepare_form_publication
# @reason reconstruct exact Datastore values only when preparing a guarded write
def _materialized_form_value(value):
    if isinstance(value, Mapping):
        return {key: _materialized_form_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_materialized_form_value(item) for item in value]
    return value


# @testable false
# @covered-by lagniappe/core/entities/form.py::Form.update
# @covered-by lagniappe/core/mutations/save.py::FormMutation.plan_save
# @covered-by lagniappe/core/properties/form.py::SchemaVersion
# @reason focused methods/properties own the durable Form behavior
class Form(Entity, AssetMixin):
    entity_kind = "form"

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_form_construction_retains_serialized_state_without_hydration_or_deepcopy
    # @matrix forms mutations : lazy-construction immutable-baseline guarded-save
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        existing = bool(args and args[0] is not None)
        self._retain_source_on_load = existing and not self._db
        self._form_source_state = _retained_form_value(self._db) if existing and self._db else None
        self._pending_html = {}

    # @testable false
    # @covered-by lagniappe/core/entities/form.py::Form.__init__
    # @reason first explicit row access captures keyed Forms before callers mutate them
    @property
    def db(self):
        value = super().db
        if getattr(self, "_retain_source_on_load", False):
            self._form_source_state = _retained_form_value(value) if value else None
            self._retain_source_on_load = False
        return value

    # @testable false
    # @covered-by lagniappe/core/tools/form_drafts.py::prepare_form_publication
    # @reason publication materializes the retained raw source for exact CAS
    def saved_form_state(self):
        if self._retain_source_on_load:
            _ = self.db
        return _materialized_form_value(self._form_source_state) if self._form_source_state is not None else None

    # @testable false
    # @covered-by lagniappe/core/tools/form_drafts.py::save_form_draft
    # @reason accepted writes establish the next lightweight publication baseline
    def capture_saved_form_state(self):
        self._form_source_state = _retained_form_value(self._db)
        self._retain_source_on_load = False

    @property
    def exclude_from_index(self):
        return frozenset({"schema", "schema_format", "version", "form_draft_receipt"})

    @property
    def required(self):
        return ["forms"]

    @property
    def url(self):
        return url_for("forms.view", key=self.urlsafe_key)

    def _get_properties(self):
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
            }
        )
        return properties

    @property
    def fields(self):
        return self.properties.schema.fields

    @property
    def table_fields(self):
        return self.properties.schema.table_fields

    def get_html_field(self, field_id):
        if field_id in self._pending_html:
            return self._pending_html[field_id] or None
        html_asset = self.get_asset(field_id)
        if not html_asset:
            return None
        return html_asset.html()

    @property
    def content_available(self):
        raw = self.db
        saved = self._form_source_state
        return bool(saved is not None and raw.get("form_content_version") == 1
                    and not self._pending_html
                    and all(saved.get(name) == raw.get(name)
                            for name in ("schema", "assets", "form_type", "version")))

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_completion_reuses_clean_current_content_without_snapshot_reads
    # @matrix task-completion form-schema : content-version current-definition no-extra-read
    def snapshot_for_completion(self):
        if self.content_available and self.version == definition_version(self):
            return self
        # Legacy completion needs persistence; keep that entry point out of
        # entity-registry initialization.
        from ..tools.form_drafts import ensure_form_snapshot

        return ensure_form_snapshot(self)

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_builder_draft_and_staged_html_are_read_only
    # @matrix forms html-field : draft baseline no-write
    def set_html_field(self, field_id, html):
        if not isinstance(field_id, str) or not isinstance(html, (str, type(None))):
            raise ValueError("HTML fields require a field ID and text content.")
        self._pending_html[field_id] = html or ""

    # @testable true
    # @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
    # @matrix html-field : asset-lifecycle image-upload unsaved-schema
    def add_html_field_image(self, field_id, image, visibility="private"):
        field = self.fields.get(field_id)
        if not field:
            field = form_special.HTML(
                {"id": field_id, "type": "html", "title": field_id},
                entity=self,
            )
        return field.add_image(image, visibility)

    @property
    def html_fields(self):
        return self.properties.schema.html_fields

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_save_refreshes_users_with_edited_form_schema
    # @matrix forms cache : owner-reuse no-extra-read
    # @pair form-schema:cache
    @property
    def used_by(self):
        return [
            entity for entity in Entities.fetch(
                self, *database_get.form_users(self), request=Fetch.direct(),
            )
            if entity.key != self.key
        ]

    @classmethod
    def create(cls, data):
        form = cls()
        form.kind = cls.entity_kind
        form.update(data)

        return form

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_schema_write_gateway_canonicalizes_without_adding_page_fields
    # @matrix form-schema : canonicalization membership write-gateway
    def set_schema(self, value):
        """Apply the one canonical durable schema write contract."""

        self.properties.schema.value = value
        return self.schema

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_update_sets_name_form_type_and_schema
    # @matrix form : form-type schema update
    def update(self, data):
        if data.get("name"):
            self.name = data["name"]

        if data.get("form-type"):
            self.form_type = data["form-type"]

        if "schema" in data:
            schema_definition = (
                json.loads(data["schema"])
                if isinstance(data["schema"], str)
                else data["schema"]
            )
            self.set_schema(schema_definition)
