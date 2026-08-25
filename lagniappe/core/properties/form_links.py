from urllib.parse import urlencode, urlparse

from ..definitions import Fetch, FieldType, FilterOptions, Ordering
from ..entities import Entities
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, FilterMixin
from ..tools import files
from ..tools.files.downloads import download_image, downloaded_image_file
from ..tools.links import metadata as external
from ..tools.services import places as location
from .base_schema import SchemaProperty

MAPS_SEARCH_URL = "https://www.google.com/maps/search/"


# @testable false
# @covered-by lagniappe/core/properties/form_links.py::Link.value
# @covered-by lagniappe/core/properties/form_links.py::Link.validate_import
# @covered-by lagniappe/core/properties/form_links.py::Link.ai_value
# @covered-by lagniappe/core/properties/form_links.py::Link.filter_value
# @reason link behavior is owned by value normalization and projection helpers
class Link(FilterMixin, ColumnMixin, AIMixin, SchemaProperty):
    """Link field. Supports internal entity links (location="in") and
    external URLs (location="out").

    For internal links, value is an entity details dict. For external
    links, value is {url, title}. Titles are auto-fetched for external
    URLs if not provided.

    Set:
        value (dict | str): {url, title} for external, or entity
            urlsafe_key for internal links.

    Get:
        value (dict): {url, title} or entity details dict.
        sort_value (str): Lowercase title or entity name.
        filter_value (str): Title for external, entity hash for internal.
        ai_value (str): URL for external, entity name for internal.
    """

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, entity=entity, **kwargs)
        self._fuzzy_match = None

    @property
    def fuzzy_match(self):
        return self._fuzzy_match

    @fuzzy_match.setter
    def fuzzy_match(self, value):
        self._fuzzy_match = value

    # Property Attributes
    @property
    def icon(self):
        return getattr(self, "_icon", None) or self["location"]

    @icon.setter
    def icon(self, value):
        self._icon = value

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_link_external
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_external_link_column
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_internal_link_column
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_internal_link_missing_target_clears_value
    # @features link
    # @dimensions row-submission, external, internal, entity-resolution, metadata, stale-target
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if not value:
            SchemaProperty.value.fset(self, None)
            return

        link = {}
        existing_value = self.entity.submission.get(self.id) or {}
        if self["location"] == "out":
            if not value.get("url"):
                SchemaProperty.value.fset(self, None)
                return
            link["url"] = value["url"]
            if value.get("url") != existing_value.get("url"):
                url_data = external.get_link_attributes(value["url"])
                link["title"] = value.get("title") or url_data.get("name", value["url"])
            elif value.get("title"):
                link["title"] = value["title"]
        elif self["location"] == "in":
            id = value if isinstance(value, str) else value.get("id")
            if not id:
                SchemaProperty.value.fset(self, None)
                return
            if id != existing_value.get("id", False):
                entity = Entities.fetch_one(id, request=Fetch.direct())
                link = entity.details if entity else None
            else:
                link = existing_value

        if not link:
            SchemaProperty.value.fset(self, None)
            return

        link.pop("parent", None)
        if link.get("kind") == "user":
            link["kind"] = "page"

        link = {k: v for k, v in link.items() if v}

        SchemaProperty.value.fset(self, link if link else None)

    # Ingress Attributes
    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_link_external
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_internal_link_exact_match
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_internal_link_fuzzy_match_warning
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_internal_link_no_match_records_error
    # @features link
    # @dimensions import, external, internal, fuzzy-match, no-match
    def validate_import(self, value):
        try:
            if self["location"] == "in":
                self._validate_internal_import(value)
                return

            result = urlparse(value) if value else None
            if value and all([result.scheme, result.netloc]):
                self.value = {"url": value}
            else:
                self.errors.append(
                    f"Invalid URL value '{value}' in column '({self.label})'"
                )
        except ValidationError as e:
            self.errors.append(e)

    def _validate_internal_import(self, value):
        if not value:
            self.value = None
            return False

        match = files.find_page(value, fuzzy=self.fuzzy_match, error_label=self.label)
        self.warnings.extend(match["warnings"])
        if match["id"]:
            self.value = match["id"]
            return True

        self.errors.extend(match["errors"])
        return False

    # AI Attributes
    # @testable true
    # @tests tests_unit/test_004d_submitter.py::test_ai_submission_internal_link_plaintext_resolves
    # @tests tests_unit/test_004d_submitter.py::test_ai_submission_internal_link_falls_back_to_value_setter
    # @features submission link
    # @dimensions ai-value internal entity-resolution fallback
    def validate_ai(self, value):
        try:
            if self["location"] == "in":
                if isinstance(value, dict) and value.get("id"):
                    self.value = value["id"]
                else:
                    lookup = value
                    if isinstance(value, dict):
                        lookup = value.get("name") or value.get("title")
                    if not self._validate_internal_import(lookup):
                        self.value = lookup
                return

            if isinstance(value, str):
                value = {"url": value}
            self.value = value
        except ValidationError as e:
            self.errors.append(e)

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def sort_value(self):
        if not self.value:
            return None
        if self.value.get("title"):
            return self.value.get("title").lower()
        elif self.value.get("name"):
            return self.value.get("name").lower()
        else:
            return None

    # AI Attributes
    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_link_external
    # @features link
    # @dimensions ai-value
    @property
    def ai_value(self):
        return self.value

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_link_external
    # @features link
    # @dimensions filter-value
    @property
    def filter_value(self):
        if not self.value:
            return None
        elif self.is_entity_valued:
            return self.value.get("hash")
        else:
            return self.value.get("title")

    @property
    def is_entity_valued(self):
        return True if self["location"] == "in" else False

    @property
    def index(self):
        return "internal" if self["location"] == "in" else None

    @property
    def placeholder(self):
        return "search..." if self["location"] == "in" else None


# @testable false
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.value
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.validate_submission
# @reason bookmark behavior is owned by value storage and submission side effects
class Bookmark(Link):
    """External bookmark with metadata extraction.

    On submission, fetches page metadata (title, image, description)
    from the URL. Can optionally replace the entity's image, name,
    or description using replace-* flags in the submission.

    Set:
        value (dict): {url, title, replace-image, replace-name,
            replace-description}. Replace flags trigger side effects.

    Get:
        value (dict): {url, title}.
    """

    _icon = "bookmark"

    @property
    def is_entity_valued(self):
        return False

    # Property Attributes
    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_bookmark
    # @features bookmark
    # @dimensions ai-value, filter-value
    @property
    def value(self):
        return super().value or {}

    @value.setter
    def value(self, value):
        SchemaProperty.value.fset(self, value if isinstance(value, dict) else None)

    # Form Attributes
    def validate_ai(self, value):
        self._value = value

    def validate_import(self, value):
        self._value = value

    # Submission Attributes
    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_bookmark_replace_flags_update_entity_fields
    # @features bookmark
    # @dimensions replace-fields, side-effects
    def validate_submission(self, value=None):
        if value is None:
            self._value = value
            return

        value = value if isinstance(value, dict) else {}
        if not any(v for k, v in value.items() if k in ["url", "title"]):
            return

        new_values = set(value.values()).difference(set(self.value.values()))
        replace = any(k.startswith("replace-") and v for k, v in value.items())
        if not new_values and not replace:
            return

        metadata = external.get_bookmark_metadata(value)
        if value.get("replace-image") and metadata.get("image"):
            result = download_image(metadata["image"])
            image = downloaded_image_file(result)
            if image is not None:
                self.entity.save_asset(image, self.id, "image")

        if value.get("replace-name"):
            self.entity.name = metadata.get("name")

        if value.get("replace-description"):
            self.entity.description = metadata.get("description")

        self.value = {
            "url": value["url"],
            "title": metadata.get("name") or value.get("title"),
        }


# @testable false
# @covered-by lagniappe/core/properties/form_links.py::Location.value
# @covered-by lagniappe/core/properties/form_links.py::Location.column_value
# @covered-by lagniappe/core/properties/form_links.py::Location.filter_value
# @covered-by lagniappe/core/properties/form_links.py::Location.ai_value
# @covered-by lagniappe/core/properties/form_links.py::Location.validate_ai
# @covered-by lagniappe/core/properties/form_links.py::Location.validate_import
# @reason location behavior is owned by value normalization and projection helpers
class Location(FilterMixin, ColumnMixin, AIMixin, SchemaProperty):
    """Google Places location field.

    Stores a resolved place (``id``, ``address``, optional ``name`` and
    ``address2``) or free text (``address`` / ``name`` only). AI and import
    inputs use Places search with a simplified-address retry before falling
    back to stored text.

    Set:
        value (dict): Resolved place id/details or ``{address, name}`` without
            ``id``.

    Get:
        value (dict): Stored location fields.
        column_value (dict): {url, title} with place or Maps search link.
        sort_value (str): Lowercase display text with "The " stripped.
        filter_value (str): Location name or address.
    """

    _icon = "location"

    @staticmethod
    def _clean_text(value):
        if value is None:
            return None
        text = value.strip() if isinstance(value, str) else str(value).strip()
        return text or None

    @classmethod
    def _same_text(cls, left, right):
        left = cls._clean_text(left)
        right = cls._clean_text(right)
        if not left or not right:
            return False
        return left.casefold() == right.casefold()

    @classmethod
    def _location_id(cls, value):
        if not isinstance(value, dict):
            return None
        return cls._clean_text(value.get("id") or value.get("place_id"))

    @classmethod
    def _address_text(cls, value):
        if not value:
            return None

        address = cls._clean_text(value.get("address"))
        address2 = cls._clean_text(value.get("address2"))
        if not address:
            return address2

        if not address2 or address2.casefold() in address.casefold():
            return address

        first, separator, rest = address.partition(",")
        if not separator:
            return f"{address}, {address2}"
        return f"{first}, {address2},{rest}"

    @classmethod
    def _display_text(cls, value):
        if not value:
            return None

        address = cls._address_text(value)
        raw_address = cls._clean_text(value.get("address"))
        name = cls._clean_text(value.get("name"))
        if name and raw_address and cls._same_text(name, raw_address):
            name = None

        if name and address:
            return f"{name}, {address}"
        return name or address

    @classmethod
    def _normalize_place(cls, place):
        if not place:
            return None

        google_id = cls._location_id(place)
        address = cls._clean_text(place.get("address"))
        name = cls._clean_text(place.get("name"))
        address2 = cls._clean_text(place.get("address2"))

        normalized = {}
        if google_id:
            normalized["id"] = google_id
        if address:
            normalized["address"] = address
        if name and not cls._same_text(name, address):
            normalized["name"] = name
        if address2:
            normalized["address2"] = address2

        return normalized or None

    # Property Attributes
    # @testable true
    # @tests tests_unit/test_003d_submission_location.py::test_location_address_only_value_and_column
    # @tests tests_unit/test_003d_submission_location.py::test_location_place_value_preserves_address2
    # @tests tests_unit/test_003d_submission_location.py::test_location_free_text_value_preserves_address2
    # @tests tests_unit/test_003d_submission_location.py::test_location_same_id_updates_address2_without_refetch
    # @tests tests_unit/test_003d_submission_location.py::test_location_place_detail_failure_falls_back_to_submitted_text
    # @features location
    # @dimensions address2, free-text, no-refetch provider-failure fallback warnings
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if not value or not isinstance(value, dict):
            SchemaProperty.value.fset(self, None)
            return

        existing_value = self.entity.submission.get(self.id) or {}
        address2 = self._clean_text(value.get("address2"))
        google_id = self._location_id(value)
        if not google_id:
            text = self._clean_text(value.get("address") or value.get("name"))
            if text:
                location_value = {"address": text, "name": text}
                if address2:
                    location_value["address2"] = address2
                SchemaProperty.value.fset(self, location_value)
            else:
                SchemaProperty.value.fset(self, None)
            return

        if self._location_id(existing_value) == google_id:
            place = self._normalize_place(existing_value) or {"id": google_id}
            place.pop("address2", None)
        else:
            place = self._normalize_place(location.get_place_details(google_id))

        if not place:
            fallback = self._clean_text(value.get("address") or value.get("name"))
            if fallback:
                place = {"address": fallback, "name": fallback}
                self.warnings.append(
                    "Place details were unavailable; stored the submitted location "
                    "as text."
                )
            else:
                self.warnings.append(
                    "Place details were unavailable and no location text was supplied."
                )

        if place and address2:
            place["address2"] = address2

        SchemaProperty.value.fset(self, place)

    # Form Attributes
    def validate_submission(self, value):
        if isinstance(value, str):
            value = {"address": value, "name": value} if value.strip() else None
        self.value = value

    # Ingress Attributes
    # @testable true
    # @tests tests_unit/test_003d_submission_location.py::test_location_validate_ai_fallback
    # @features location
    # @dimensions fallback, warnings
    def validate_ai(self, value):
        """Validate AI-submitted location (string or dict)."""
        place = (
            value
            if isinstance(value, str)
            else value.get("address")
            if isinstance(value, dict)
            else None
        )
        if not place:
            self.value = None
            return

        place = place.strip() if isinstance(place, str) else str(place).strip()
        resolved = location.resolve_location_query(place)
        if resolved:
            self.value = resolved
        else:
            self.value = {"address": place, "name": place}
            self.warnings.append(
                f"No place found for '{place}'; stored as address text."
            )

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_location
    # @tests tests_unit/test_003d_submission_location.py::test_location_validate_import_fallback
    # @features location
    # @dimensions import, fallback
    def validate_import(self, value):
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                self.value = None
                return
            query = value.strip() if isinstance(value, str) else str(value).strip()
            resolved = location.resolve_location_query(query)
            if resolved:
                self.value = resolved
            else:
                self.value = {"address": query, "name": query}
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid location value '{value}' in column '({self.label})'"
            )

    # Column Attributes
    _ordering = Ordering.EXISTS

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_location
    # @tests tests_unit/test_003d_submission_location.py::test_location_address_only_value_and_column
    # @tests tests_unit/test_003d_submission_location.py::test_location_place_value_preserves_address2
    # @tests tests_unit/test_003d_submission_location.py::test_location_free_text_value_preserves_address2
    # @features location
    # @dimensions column
    @property
    def column_value(self):
        if not self.value:
            return {"url": None, "title": None}
        column = self.value.copy()
        title = self._display_text(column)
        params = {"api": "1", "query": title}
        google_id = self._location_id(column)
        if google_id:
            params["query_place_id"] = google_id
        url = f"{MAPS_SEARCH_URL}?{urlencode(params)}" if title else None
        return {"url": url, "title": title}

    @property
    def sort_value(self):
        return (
            self.filter_value.replace("The ", "").lower() if self.filter_value else None
        )

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_location
    # @tests tests_unit/test_003d_submission_location.py::test_location_place_value_preserves_address2
    # @features location
    # @dimensions filter-value
    @property
    def filter_value(self):
        if not self.value:
            return None
        return self._display_text(self.value)

    # AI Attributes
    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_location
    # @tests tests_unit/test_003d_submission_location.py::test_location_place_value_preserves_address2
    # @features location
    # @dimensions ai-value
    @property
    def ai_value(self):
        if not self.value:
            return None
        return self._display_text(self.value)
