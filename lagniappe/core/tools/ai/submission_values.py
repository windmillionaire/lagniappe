"""Typed, actor-aware values keyed by the exact submission field IDs."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...mixins.field_host import FieldUser

from lagniappe.core.mixins import AIMixin


def values_by_id(fields: Mapping[str, object], user: FieldUser) -> dict[str, object]:
    values = {}
    for field_id, field in fields.items():
        if isinstance(field, AIMixin) and field.is_set:
            field.user = user
            value = field.ai_value
            if value is not None:
                values[field_id] = value
    return values
