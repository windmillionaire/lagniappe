"""Parse an uploaded CSV into column metadata and rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.files import validate as file_validation

if TYPE_CHECKING:
    from lagniappe.core.entities.ingress import Ingress


type CsvColumns = dict[str, file_validation.CSVColumn]


type CsvRow = dict[str, str]


class IngressParser:
    """Pure parsing boundary for an ingress upload or stored text asset."""

    @staticmethod
    def parse_entity(entity: Ingress) -> tuple[file_validation.CSVMetadata, list[CsvRow]]:
        if entity.mimetype != "text/csv":
            raise ValidationError("File must be a CSV file.")
        text = entity.properties.text.asset
        if text is None:
            raise ValidationError("The CSV file has no text to parse.")
        parsed = dict(file_validation.process_csv(text))
        rows = cast(list[CsvRow], parsed.pop("rows", []))
        # ParsedCSV extends CSVMetadata with only the rows field.
        return cast(file_validation.CSVMetadata, parsed), rows
