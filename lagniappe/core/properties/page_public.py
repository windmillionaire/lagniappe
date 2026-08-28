"""Persisted public-page visibility and search-preview settings."""

from ..definitions import MutationIntent
from ..exceptions import ValidationError
from .base_db import DBProperty
from .common_entity import IsPublic


PUBLIC_PAGE_SETTINGS_VERSION = 2
PUBLIC_TITLE_LIMIT = 120
PUBLIC_DESCRIPTION_LIMIT = 300


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_public_settings_normalize_and_invalidate_discovery
# @matrix page public-directory sitemap : category metadata settings-validation
def normalize_public_settings(value=None):
    """Return the versioned canonical per-page public settings."""
    if value is None:
        incoming = {}
    elif isinstance(value, dict):
        incoming = value
    else:
        raise ValidationError("Public page settings must be an object.")

    allow_indexing = incoming.get("allow_indexing", True)
    if not isinstance(allow_indexing, bool):
        raise ValidationError("Page indexing must be enabled or disabled.")

    # @testable false
    # @covered-by lagniappe/core/properties/page_public.py::normalize_public_settings
    # @reason bounded text normalization is exercised through the public normalizer
    def optional_text(name, limit, label):
        raw = incoming.get(name)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        if len(text) > limit:
            raise ValidationError(f"{label} must be {limit} characters or fewer.")
        return text

    preview = optional_text("preview_image_asset", 255, "Preview image")
    raw_directory_category = incoming.get("directory_category")
    if raw_directory_category is not None and not isinstance(
        raw_directory_category,
        str,
    ):
        raise ValidationError("Directory category must be a URL-safe key.")
    directory_category = optional_text(
        "directory_category",
        2048,
        "Directory category",
    )
    return {
        "version": PUBLIC_PAGE_SETTINGS_VERSION,
        "allow_indexing": allow_indexing,
        "title": optional_text("title", PUBLIC_TITLE_LIMIT, "Public title"),
        "description": optional_text(
            "description",
            PUBLIC_DESCRIPTION_LIMIT,
            "Public description",
        ),
        "preview_image_asset": preview,
        "directory_category": directory_category,
    }


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_public_visibility_invalidates_discovery_only_when_changed
# @matrix page public-directory sitemap : visibility
class PageIsPublic(IsPublic):
    """Page visibility with public-discovery invalidation registration."""

    @IsPublic.value.setter
    def value(self, value):
        previous = IsPublic.value.fget(self)
        IsPublic.value.fset(self, value)
        if value != previous:
            self.entity.add_mutation_intents(
                MutationIntent.invalidate_public_discovery(
                    reason="page-public-visibility"
                )
            )


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_public_settings_normalize_and_invalidate_discovery
# @matrix page public-directory sitemap : category metadata settings-validation
class PublicSettings(DBProperty):
    """Versioned discovery and social metadata for one public page."""

    _id = "public_settings"
    json = True

    @property
    def value(self):
        return normalize_public_settings(DBProperty.value.fget(self))

    @value.setter
    def value(self, value):
        previous = self.value
        normalized = normalize_public_settings(value)
        DBProperty.value.fset(self, normalized)
        if (
            normalized["allow_indexing"] != previous["allow_indexing"]
            or normalized["directory_category"] != previous["directory_category"]
        ):
            self.entity.add_mutation_intents(
                MutationIntent.invalidate_public_discovery(
                    reason="page-discovery-setting"
                )
            )
