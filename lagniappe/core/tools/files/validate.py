"""CSV parsing, column type inference, and schema generation for file imports."""

import csv
import io
import re

from ... import exceptions
from ...definitions.identifiers import short_hash, short_uuid


# @testable true
# @tests tests_unit/test_006a_ingress_csv.py::test_categorical_detection
# @tests tests_unit/test_006a_ingress_csv.py::test_string_fallback
# @matrix ingress-csv : categorical fallback type-inference
def infer_column_types(rows, columns):
    """Infer column types (string, number, date, etc.) by sampling row values.

    Args:
        rows: List of row dicts keyed by column ID.
        columns: List of column dicts with 'id' and 'label' keys; updated in place with inferred type info.
    """
    threshold = 0.8
    date_patterns = [
        re.compile(r"^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$"),
        re.compile(r"^\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}$"),
        re.compile(
            r"^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}:\d{2}\s*([AaPp][Mm])?$"
        ),
    ]
    # Keep the path repetition flat. Nesting ``*`` inside another ``*`` here
    # causes catastrophic backtracking for long URL-like values that end with
    # an unsupported character.
    url_pattern = re.compile(
        r"^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})[\/\w \.-]*\/?$"
    )
    email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    boolean_values = {"yes", "no", "true", "false", "1", "0", "y", "n"}
    multiple_value_pattern = re.compile(r"[;|]\s*\w")

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_phone_detection
    # @matrix ingress-csv : phone type-inference
    def is_phone_number(s: str) -> bool:
        digits = "".join(c for c in s if c.isdigit())
        return 10 <= len(digits) <= 15

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_url_detection
    # @tests tests_unit/test_006a_ingress_csv.py::test_url_detection_rejects_long_unsupported_path_within_deadline
    # @matrix ingress-csv : type-inference url
    def is_url(s: str) -> bool:
        return bool(url_pattern.match(s.lower().strip()))

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_email_detection
    # @matrix ingress-csv : email type-inference
    def is_email(s: str) -> bool:
        return bool(email_pattern.match(s.lower().strip()))

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_multi_categorical_detection
    # @matrix ingress-csv : multi-categorical type-inference
    def has_multiple_values(s: str) -> bool:
        return bool(multiple_value_pattern.search(s))

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_number_detection
    # @matrix ingress-csv : number type-inference
    def is_numeric(s: str) -> bool:
        return str(s).replace(".", "").replace("-", "").isdigit()

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_date_detection
    # @matrix ingress-csv : date type-inference
    def is_date(s: str) -> bool:
        return any(pattern.match(str(s)) for pattern in date_patterns)

    # @testable true
    # @tests tests_unit/test_006a_ingress_csv.py::test_boolean_detection
    # @matrix ingress-csv : boolean type-inference
    def is_boolean(s: str) -> bool:
        return str(s).lower() in boolean_values

    for column in columns:
        values = [row.get(column["id"], "").strip() for row in rows]
        values = [v for v in values if v]
        column.update({"kind": "file", "icon": "text", "type": "string"})

        if not values:
            continue

        num_samples = min(50, len(values))
        samples = values[:num_samples]

        url_matches = sum(1 for s in samples if is_url(s))
        if url_matches / len(samples) >= threshold:
            column.update({"icon": "link", "type": "url"})
            continue

        email_matches = sum(1 for s in samples if is_email(s))
        if email_matches / len(samples) >= threshold:
            column.update({"icon": "email", "type": "email"})
            continue

        numeric_matches = sum(1 for s in samples if is_numeric(s))
        if numeric_matches / len(samples) >= threshold:
            phone_matches = sum(1 for s in samples if is_phone_number(s))
            if phone_matches / len(samples) >= threshold:
                column.update({"icon": "tel", "type": "phone"})
            else:
                column.update({"icon": "number", "type": "number"})
            continue

        date_matches = sum(1 for s in samples if is_date(s))
        if date_matches / len(samples) >= threshold:
            column.update({"icon": "date", "type": "datetime"})
            continue

        bool_matches = sum(1 for s in samples if is_boolean(s))
        if bool_matches / len(samples) >= threshold:
            column.update({"icon": "checkbox", "type": "boolean"})
            continue

        # Categorical detection - check for repeating discrete values
        unique_values = set(values)
        unique_count = len(unique_values)
        unique_ratio = unique_count / len(rows)
        avg_length = sum(len(v) for v in values) / len(values) if values else 0

        # Check for multi-value patterns (semicolon or pipe separated)
        multi_matches = sum(1 for s in values if has_multiple_values(s))
        has_multi_values = multi_matches / len(values) >= 0.1 if values else False

        # Categorical criteria:
        # 1. Few unique values (absolute): <= 15 distinct values
        # 2. Low unique ratio: < 20% for small sets, < 10% for larger
        # 3. Short values (avg < 50 chars) - excludes free text
        # 4. At least 2 unique values (not constant)
        # 5. Values must actually repeat — high-uniqueness columns are text
        ratio_threshold = 0.2 if len(rows) < 50 else 0.1
        is_categorical = (
            unique_count >= 2
            and unique_count <= 15
            and avg_length < 50
            and (
                unique_ratio < ratio_threshold
                or (unique_count <= 8 and unique_ratio < 0.7)
            )
        )

        if has_multi_values and is_categorical:
            column.update({"icon": "select", "type": "multi_categorical"})
            continue
        elif is_categorical:
            column.update({"icon": "radio", "type": "categorical"})
            continue


# @testable false
# @covered-by lagniappe/core/tools/files/validate.py::create_schema
# @reason categorical option extraction is part of schema generation
def extract_options(rows, column):
    """Extract unique option values for a categorical or multi-categorical column.

    Args:
        rows: List of row dicts keyed by column ID.
        column: Column dict with 'id' and 'type' keys.

    Returns:
        Tuple of (sorted option values, detected separator or None).
    """
    values = [row.get(column["id"], "").strip() for row in rows]

    if column["type"] == "multi_categorical":
        joined_values = "".join(values)
        if not re.search(r"[;|]", joined_values):
            separator = None
        else:
            separator = max(["|", ";"], key=joined_values.count)

        all_cats = set()
        for val in values:
            cats = val.split(separator) if separator else [val]
            all_cats.update(cat.strip() for cat in cats if cat.strip())

        return sorted(all_cats), separator
    else:
        return sorted(set(values.strip() for values in values)), None


# @testable true
# @tests tests_unit/test_006a_ingress_csv.py::test_standard_csv
# @tests tests_unit/test_006a_ingress_csv.py::test_semicolon_delimiter
# @tests tests_unit/test_006a_ingress_csv.py::test_empty_rows_skipped
# @tests tests_unit/test_006a_ingress_csv.py::test_header_only_raises
# @tests tests_unit/test_006a_ingress_csv.py::test_no_header_raises
# @tests tests_unit/test_006a_ingress_csv.py::test_rows_keyed_by_column_id
# @matrix ingress-csv : column-ids delimiter empty-rows validation
def process_csv(text):
    """Parse CSV text into structured rows, columns, and inferred types.

    Args:
        text: Raw CSV string content.

    Returns:
        Dict with 'delimiter', 'rows', 'columns', 'row_count', and 'column_count'.
    """
    try:
        dialect = csv.Sniffer().sniff(text, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect=dialect)

    header_row = next(reader, None)
    if not header_row:
        raise exceptions.ValidationError("No header row found in the CSV file")

    columns = []
    for idx, col_label in enumerate(header_row):
        if not col_label or not str(col_label).strip():
            continue

        column = {
            "id": f"col-{short_hash(f'{col_label}-{idx}')}",
            "label": col_label.replace("\n", " ").replace("\r", " ").strip(),
            "index": idx,
        }

        columns.append(column)

    rows = []
    for row_data in reader:
        if not any(cell and str(cell).strip() for cell in row_data):
            continue

        row = {
            column["id"]: row_data[column["index"]]
            for column in columns
            if column["index"] < len(row_data)
        }
        rows.append(row)

    if not rows:
        raise exceptions.ValidationError("No valid data rows found in the CSV file")

    infer_column_types(rows, columns)

    return {
        "delimiter": dialect.delimiter,
        "rows": rows,
        "columns": {column["id"]: column for column in columns},
        "row_count": len(rows),
        "column_count": len(columns),
    }


# @testable false
# @covered-by lagniappe/core/tools/files/validate.py::create_schema
# @reason select/radio option shaping is part of schema generation
def create_options(values, column_schema):
    """Build option objects for a select column, switching to radio for small sets."""
    if len(values) < 6:
        column_schema["type"] = "radio"
        column_schema["id"] = f"{column_schema['type']}-{short_uuid()}"

    return [{"value": f"o{short_uuid()}", "label": v} for v in values]


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_import_wizard_story_builds_or_selects_the_submission_form
# @matrix form ingress : choose-form default-form schema-generation
def create_schema(columns, rows):
    """Generate a form schema from inferred column types and row data.

    Args:
        columns: Dict of column dicts keyed by column ID.
        rows: List of row dicts for option extraction.

    Returns:
        Tuple of (schema list, detected multi-value separator or None).
    """
    schema, separators = [], []

    type_to_schema = {
        "string": {"type": "input", "input": "text"},
        "number": {"type": "input", "input": "number"},
        "datetime": {"type": "input", "input": "date"},
        "email": {"type": "input", "input": "email"},
        "phone": {"type": "input", "input": "tel"},
        "url": {"type": "link", "location": "out"},
        "boolean": {"type": "checkbox"},
        "categorical": {"type": "select"},
        "multi_categorical": {"type": "select", "multiple": True},
    }

    # @testable false
    # @covered-by lagniappe/core/tools/files/validate.py::create_schema
    # @reason per-column schema assembly is part of create_schema
    def build_schema(column, separators):
        label = column["label"].strip()
        column_schema = {"title": label}

        settings = type_to_schema[column["type"]]
        if label.lower() == "name":
            column_schema["title"] = "Name"
            column_schema["id"] = "name"
        elif label.lower() == "description":
            column_schema["title"] = "Description"
            column_schema["id"] = "description"
            column_schema["type"] = "textarea"
            column_schema.pop("input", None)
        else:
            column_schema["id"] = f"{settings['type']}-{short_uuid()}"
        column_schema.update(settings)

        if column["type"] in ["multi_categorical", "categorical"]:
            values, detected_separator = extract_options(rows, column)
            if detected_separator:
                separators.append(detected_separator)
            column_schema["options"] = create_options(values, column_schema)

        return column_schema

    for column in columns.values():
        column_schema = build_schema(column, separators)
        schema.append(column_schema)

    separator = None if not separators else max(separators, key=separators.count)
    return schema, separator
