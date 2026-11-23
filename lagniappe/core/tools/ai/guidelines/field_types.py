"""Submission guidance limited to the field types a request actually uses."""

from collections.abc import Iterable
import re
from typing import TypedDict

from .forms import SCHEMA_TYPE_GUIDELINES


class GuidanceField(TypedDict, total=False):
    type: str
    columns: list[GuidanceField]


# @testable true
# @pair ai:autofill
def schema_type_guidance(field_types: Iterable[str | None]) -> str:
    """Select complete type sections, including the shared radio/select section."""
    wanted = set(field_types)
    sections = re.split(r"\n(?=#### )", SCHEMA_TYPE_GUIDELINES.strip())
    selected = [
        "### Submission values\n\nUse exact field IDs and the supplied schema. "
        "Omitted fields are unchanged; only include supported updates."
    ]
    for section in sections[1:]:
        if wanted.intersection(re.findall(r"`([^`]+)`", section.splitlines()[0])):
            selected.append(section.strip())
    return "\n\n".join(selected)


# @testable true
# @pair ai:autofill
def schema_guidance(schema: Iterable[GuidanceField] | None) -> str:
    """Include column types as well as the top-level fields' types."""
    pending = list(schema or ())
    types = set()
    while pending:
        field = pending.pop()
        types.add(field.get("type"))
        pending.extend(field.get("columns") or ())
    return schema_type_guidance(types)
