"""Persisted public-page visibility and search-preview settings."""

from typing import TypedDict

from ..definitions import MutationIntent
from ..exceptions import ValidationError
from .base_db import DBProperty
from .common_entity import IsPublic


class PageSettings(TypedDict):
    version: int
    allow_indexing: bool
    title: str | None
    description: str | None
    preview_image_asset: str | None
    directory_category: str | None
    directory_order: int | None


PUBLIC_PAGE_SETTINGS_VERSION = 2
PUBLIC_TITLE_LIMIT = 120
PUBLIC_DESCRIPTION_LIMIT = 300
PUBLIC_DIRECTORY_ORDER_MIN = 1
PUBLIC_DIRECTORY_ORDER_MAX = 9999


def normalize_public_settings(value: object = None) -> PageSettings:
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

    def optional_text(name: str, limit: int, label: str) -> str | None:
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
    raw_order = incoming.get("directory_order")
    directory_order: int | None
    if raw_order is None or (isinstance(raw_order, str) and not raw_order.strip()):
        directory_order = None
    elif isinstance(raw_order, bool):
        raise ValidationError(
            "Public directory order must be a whole number from 1 to 9999."
        )
    else:
        try:
            if isinstance(raw_order, int):
                parsed_order = raw_order
            elif isinstance(raw_order, str) and raw_order.strip().isdigit():
                parsed_order = int(raw_order.strip())
            else:
                raise ValueError("not an integer")
        except ValueError as error:
            raise ValidationError(
                "Public directory order must be a whole number from 1 to 9999."
            ) from error
        if not (PUBLIC_DIRECTORY_ORDER_MIN <= parsed_order <= PUBLIC_DIRECTORY_ORDER_MAX):
            raise ValidationError(
                "Public directory order must be a whole number from 1 to 9999."
            )
        directory_order = parsed_order

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
        "directory_order": directory_order,
    }


class PageIsPublic(IsPublic):
    """Page visibility with public-discovery invalidation registration."""

    @property
    def value(self) -> bool:
        return super().value

    @value.setter
    def value(self, value: bool) -> None:
        previous = super().value
        self._write_public(value)
        if value != previous:
            self.entity.add_mutation_intents(
                MutationIntent.invalidate_public_discovery(
                    reason="page-public-visibility"
                )
            )


class PublicSettings(DBProperty[PageSettings]):
    """Versioned discovery and social metadata for one public page."""

    _id = "public_settings"
    json = True

    @property
    def value(self) -> PageSettings:
        return normalize_public_settings(self._read_db_value())

    @value.setter
    def value(self, value: object) -> None:
        previous = self.value
        normalized = normalize_public_settings(value)
        self._write_db_value(normalized)
        if (
            normalized["allow_indexing"] != previous["allow_indexing"]
            or normalized["directory_category"] != previous["directory_category"]
            or normalized["directory_order"] != previous["directory_order"]
        ):
            self.entity.add_mutation_intents(
                MutationIntent.invalidate_public_discovery(
                    reason="page-discovery-setting"
                )
            )
