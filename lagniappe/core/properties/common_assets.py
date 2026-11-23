import json
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from ..definitions.asset import AssetUpload, HTMLAsset, YDocAsset
    from ..entities.page import Page
    from ..entities.project import Project

from ..definitions import FieldType, FilterOptions, MutationIntent
from ..definitions.identifiers import short_uuid
from ..mixins import AIMixin, CacheMixin, FilterMixin
from .base_property import Property, UNSET

type DocumentOwner = Page | Project


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_document
# @tests tests_unit/test_005_project_properties.py::test_project_document_state_uses_markup_when_no_ydoc
# @tests tests_unit/test_008_page_properties.py::test_page_document
# @matrix page project : document document-state markup-fallback
class Document(CacheMixin, FilterMixin, AIMixin, Property["Document", DocumentOwner]):
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
    def value(self) -> Self:  # pyright: ignore[reportIncompatibleMethodOverride] -- This computed field is read-only.
        return self

    @property
    def kind(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- The owner determines the document kind.
        return self.entity.entity_kind

    # Entity Attributes
    @property
    def sync_id(self) -> str:
        return f"{self.entity.hash}:document"

    @property
    def fingerprint(self) -> str | None:
        asset = self.entity.get_asset(self.id)
        if not asset:
            return None
        return asset.fingerprint

    @property
    def state(self) -> str | None:
        return self.ydoc

    @property
    def html(self) -> str | None:
        if self._html is not UNSET:
            return cast("str | None", self._html)

        html_asset = cast("HTMLAsset | None", self.entity.get_asset(self.id))
        self._html = html_asset.html() if html_asset else None
        return self._html

    @html.setter
    def html(self, value: str | None) -> None:
        saved = self.entity.save_asset(value, self.id, "html")
        self._html = value if saved else None

    @property
    def ydoc(self) -> str | None:
        if self._ydoc is not UNSET:
            return cast("str | None", self._ydoc)

        ydoc_asset = cast("YDocAsset | None", self.entity.get_asset(self._ydoc_id))
        self._ydoc = ydoc_asset.get() if ydoc_asset else None
        return self._ydoc

    # @testable true
    # @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image
    # @pair editor:image-upload
    def add_image(self, image: AssetUpload, visibility: str = "private") -> str | None:
        name = f"image_{short_uuid()}"
        asset = self.entity.save_asset(image, name, "image", visibility=visibility)
        if asset is None:
            raise AttributeError("Image upload did not create an asset")
        return asset.url

    # @testable true
    # @tests tests_e2e/004_projects/test_004d_document.py::test_editor_loads_and_saves_text
    # @tests tests_e2e/004_projects/test_004d_document.py::test_task_list_persists
    # @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_saves_do_not_create_automatic_history
    # @matrix editor : history-list reload task-list text-save
    # @matrix editor : document isolated-checkpoint tombstones
    # @matrix editor mutations : document durable-first cleanup named-versions
    def save(self, *, html: str | None = None, ydoc: str | None = None, **kwargs: object) -> None:
        previous = {
            name: self.entity.assets.get(name)
            for name in (self.id, self._ydoc_id)
        }
        self._html = html
        self._ydoc = ydoc

        if self._html == "":
            # Keep tombstones so an offline editor cannot resurrect erased text.
            self.entity.assets.pop(self.id, None)
            if self._ydoc:
                self.entity.save_asset(self._ydoc, self._ydoc_id, "ydoc", isolated=True)
            else:
                self.entity.assets.pop(self._ydoc_id, None)
            self.entity.db["assets"] = json.dumps(self.entity.assets)
        elif self._ydoc and self._html is None:
            self.entity.assets.pop(self.id, None)
            self.entity.save_asset(self._ydoc, self._ydoc_id, "ydoc", isolated=True)
        elif self._html:
            self.entity.save_asset(self._html, self.id, "html", isolated=True)
            if self._ydoc:
                self.entity.save_asset(self._ydoc, self._ydoc_id, "ydoc", isolated=True)

        for name, asset in previous.items():
            if asset and asset.get("path") != (self.entity.assets.get(name) or {}).get("path"):
                # Retire only after the new pair commits. This deletes the live
                # object, not its backup generations or any embedded images.
                if "path" not in asset:
                    raise KeyError("path")
                self.entity.add_mutation_intents(
                    MutationIntent.delete_blob(
                        asset["path"], asset.get("visibility", "private"),
                        reason="superseded-document",
                    )
                )

    # Cache Attributes
    _cache_key = "doc"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_document
    # @tests tests_unit/test_008_page_properties.py::test_page_document
    # @matrix page project : cache
    @property
    def cache_value(self) -> str | None:
        return self.ai_value

    # AI Attributes
    @property
    def ai_key(self) -> str:
        return f"{self.kind}_document"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_document
    # @tests tests_unit/test_008_page_properties.py::test_page_document
    # @matrix page project : ai-value
    @property
    def ai_value(self) -> str | None:
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
    def filter_value(self) -> bool:
        return bool(self.entity.get_asset(self.id))

    @property
    def filter_kind(self) -> str | None:
        return self._filter_kind or self._kind

    @filter_kind.setter
    def filter_kind(self, value: str | None) -> None:
        self._filter_kind = value

    @property
    def filter_label(self) -> str:
        return "Has Document"
