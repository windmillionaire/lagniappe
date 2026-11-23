"""Form-related properties for form type filtering and display."""
import hashlib
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal, cast

from ..definitions import Ordering
from ..exceptions import ValidationError
from ..mixins import (
    AIMixin,
    CacheMixin,
    ColumnMixin,
    DetailsMixin,
    FilterMixin,
)
from .base_db import DBProperty
from .base_filters import Filters
from .form_table import Table

if TYPE_CHECKING:
    from ..entities.form import Form
    from .base_schema import FieldDefinition


class FormType(AIMixin, ColumnMixin, DetailsMixin, CacheMixin, DBProperty[str, "Form"]):
    """Form type classification (e.g. "page", "task").

    Set:
        value (str): Form type identifier.

    Get:
        value (str): Form type identifier.
        sort_value (dict): {Capitalized: value} for categorical ordering.
    """

    # Property Attributes
    _id = "form_type"
    _label = "Form Type"
    _icon = "form"

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    @property
    def sort_value(self) -> dict[str, str] | None:
        return {self.value.capitalize(): self.value} if self.value else None

    @property
    def ai_key(self) -> str:
        return self.id

    # Cache Attributes
    @property
    def cache_value(self) -> str | None:
        return self.value

    @property
    def cache_key(self) -> str:
        return "type"


class FormFilters(Filters):
    _filter_fields = []

    @property
    def fields(self) -> dict[str, FilterMixin]:
        if self.entity.db.get("pending_form_change"):
            return {}
        return {
            k: v
            for k, v in cast("Form", self.entity).fields.items()
            if isinstance(v, FilterMixin) and not isinstance(v, Table)
        }

    def _condition(self, field: FilterMixin) -> dict[str, object]:
        return {
            "field": field.filter_key,
            "label": field.label,
            "kind": field.kind,
            "icon": field.icon,
        }

    @property
    def conditions(self) -> list[dict[str, object]]:
        if cached := getattr(self, "_conditions", None):
            return cached

        self._conditions = [self._condition(field) for field in self.fields.values()]
        return self._conditions


def requires_submission_conversion(
    previous_schema: Iterable[FieldDefinition] | None,
    proposed_schema: Iterable[FieldDefinition] | None,
) -> bool:
    """Compare normalized definitions for changes that affect existing values.

    Labels, presentation, ordering and additions leave saved values readable.
    Removed identities and changed field representations need migration first.
    """
    proposed_fields = {field["id"]: field for field in proposed_schema or []}
    for previous in previous_schema or []:
        if previous.get("type") in {"html", "status"}:
            continue
        proposed = proposed_fields.get(previous["id"])
        if proposed is None or previous.get("type") != proposed.get("type"):
            return True
        kind = previous.get("type")
        if kind == "input" and (
            previous.get("input", "text") != proposed.get("input", "text")
        ):
            return True
        if kind == "select" and (
            bool(previous.get("multiple")) != bool(proposed.get("multiple"))
        ):
            return True
        if kind == "link" and (
            previous.get("location", "out") != proposed.get("location", "out")
        ):
            return True
        if kind in {"select", "radio"}:
            option_values = {option["value"] for option in cast("list[dict[str, str]]", proposed.get("options", []))}
            if any(
                option["value"] not in option_values
                for option in cast("list[dict[str, str]]", previous.get("options", []))
            ):
                return True
        if kind == "table" and requires_submission_conversion(
            cast("list[FieldDefinition]", previous.get("columns", [])),
            cast("list[FieldDefinition]", proposed.get("columns", [])),
        ):
            return True
    return False


class FormGeneration(DBProperty[int, "Form"]):
    """Submission representation generation, advanced explicitly at publication.

    Missing generations start at zero, independently of older version fields.
    """

    _id = "generation"

    @property
    def value(self) -> int:
        value = super().value
        return 0 if value is None else value

    @value.setter
    def value(self, value: object) -> None:
        if type(value) is not int or value < 0:
            raise ValidationError("Form generation must be a nonnegative integer.")
        self._write_db_value(value)


class SchemaVersion(DBProperty[str, "Form"]):
    """Content fingerprint used to invalidate cached Form presentations."""

    _id = "version"

    def update(self) -> str | Literal[False] | None:
        """Refresh the schema and published HTML/image fingerprint."""
        previous_version = super().value
        html_ids = {
            cast(str, field["id"]) for field in self.entity.schema if field.get("type") == "html"
        }
        assets = {
            name: {key: asset.get(key) for key in ("type", "fingerprint")}
            for name, asset in self.entity.assets.items()
            if name in html_ids or any(
                name.startswith(f"image_{field_id}_") for field_id in html_ids
            )
        }
        if any(
            not isinstance(asset["fingerprint"], str) or not asset["fingerprint"]
            for asset in assets.values()
        ):
            raise ValidationError("Form content requires a fingerprint before publication.")
        next_version = hashlib.md5(
            json.dumps({
                "schema": self.entity.schema,
                "form_type": self.entity.form_type,
                "assets": assets,
            }, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if previous_version == next_version:
            return False
        self.value = next_version
        return previous_version
