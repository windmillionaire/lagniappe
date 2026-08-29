from ..definitions import FieldType, FilterOptions, MutationIntent
from ..definitions.identifiers import short_uuid
from ..mixins import AIMixin, CacheMixin, FilterMixin
from .base_property import Property, UNSET


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_document
# @tests tests_unit/test_005_project_properties.py::test_project_document_state_uses_markup_when_no_ydoc
# @tests tests_unit/test_008_page_properties.py::test_page_document
# @matrix page project : document document-state markup-fallback
class Document(CacheMixin, FilterMixin, AIMixin, Property):
    """Collaborative rich-text document (HTML + YDoc).

    Stores HTML content and a YDoc snapshot as separate assets.
    Supports inline image uploads. The cache/AI value is tag-stripped
    plain text for search indexing.

    Get:
        value (dict): {html, ydoc, resource_id} loaded from assets.
        html (str): The HTML content (settable).
        ydoc: The YDoc snapshot (settable).
        ai_value (str | None): Tag-stripped text for AI context.
        filter_value (bool): Whether a document exists.

    Overrides:
        cache_value: Returns ai_value for search indexing.
        ai_key: Returns "{kind}_document".
    """

    # Property Attributes
    _id = "document"
    _ydoc_id = "snapshot"
    _ydoc = UNSET
    _html = UNSET
    _icon = "document"
    _label = "Page"

    @property
    def value(self):
        return self

    @property
    def kind(self):
        return self.entity.entity_kind

    # Entity Attributes
    @property
    def sync_id(self):
        return f"{self.entity.hash}:document"

    @property
    def fingerprint(self):
        asset = self.entity.get_asset(self.id)
        if not asset:
            return None
        return asset.fingerprint

    @property
    def state(self):
        return self.ydoc

    @property
    def html(self):
        if self._html is not UNSET:
            return self._html

        html_asset = self.entity.get_asset(self.id)
        self._html = html_asset.html() if html_asset else None
        return self._html

    @html.setter
    def html(self, value):
        self._html = self.entity.save_asset(value, self.id, "html")

    @property
    def ydoc(self):
        if self._ydoc is not UNSET:
            return self._ydoc

        ydoc_asset = self.entity.get_asset(self._ydoc_id)
        self._ydoc = ydoc_asset.get() if ydoc_asset else None
        return self._ydoc

    # @testable true
    # @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image
    # @pair editor:image-upload
    def add_image(self, image, visibility="private"):
        name = f"image_{short_uuid()}"
        asset = self.entity.save_asset(image, name, "image", visibility=visibility)
        return asset.url

    # @testable true
    # @tests tests_e2e/004_projects/test_004d_document.py::test_editor_loads_and_saves_text
    # @tests tests_e2e/004_projects/test_004d_document.py::test_task_list_persists
    # @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_created_on_save
    # @matrix editor : history-list reload task-list text-save
    def save(self, **kwargs):
        self._html = kwargs.get("html")
        self._ydoc = kwargs.get("ydoc")

        if self._html == "":
            self.entity.delete_asset(self.id)
            self.entity.delete_asset(self._ydoc_id)
        elif self._ydoc and self._html is None:
            self.entity.delete_asset(self.id)
            self.entity.save_asset(self._ydoc, self._ydoc_id, "ydoc")
        elif self._html:
            html_asset = self.entity.save_asset(self._html, self.id, "html")
            if html_asset.updated:
                self._create_history()
                self.entity.save_asset(self._ydoc, self._ydoc_id, "ydoc")

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.save
    # @reason document history creation is a private side effect of saving changed HTML
    def _create_history(self):
        from ..entities import Entities

        history = Entities.DOCUMENT_HISTORY.create(self.entity)
        if not history:
            return
        self.entity.add_mutation_intents(
            MutationIntent.standard(history, reason="document-history")
        )
        self.entity.db["document_history"] = True

    # Cache Attributes
    _cache_key = "doc"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_document
    # @tests tests_unit/test_008_page_properties.py::test_page_document
    # @matrix page project : cache
    @property
    def cache_value(self):
        return self.ai_value

    # AI Attributes
    @property
    def ai_key(self):
        return f"{self.kind}_document"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_document
    # @tests tests_unit/test_008_page_properties.py::test_page_document
    # @matrix page project : ai-value
    @property
    def ai_value(self):
        asset = self.entity.get_asset(self.id)
        if not asset:
            return None
        return asset.cache_value

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.DOCUMENT.value
    _field_text = "has"
    _filter_key = "has_document"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_document
    # @tests tests_unit/test_008_page_properties.py::test_page_document
    # @matrix page project : filter-value
    @property
    def filter_value(self):
        return True if self.entity.get_asset(self.id) else False

    @property
    def filter_kind(self):
        return self._filter_kind or self._kind

    @filter_kind.setter
    def filter_kind(self, value):
        self._filter_kind = value

    @property
    def filter_label(self):
        return "Has Document"
