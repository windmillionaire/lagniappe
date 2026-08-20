"""
Unit tests for CSV processing (process_csv) and column type inference.

Tests the validate.py functions that parse CSV files and infer column types.
Uses various CSV files with different formats, delimiters, and edge cases.
"""

import signal
from pathlib import Path

import pytest

from lagniappe.core.tools.files.validate import process_csv
from lagniappe.core import exceptions


# Path to test CSV files
CSV_DIR = Path(__file__).parent.parent / "files"


# --- ProcessCSV Tests ---


# @features ingress-csv
# @dimensions delimiter
def test_standard_csv():
    """Test processing a standard comma-delimited CSV."""
    csv_path = CSV_DIR / "sample_data.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    assert result["delimiter"] == ","
    assert result["row_count"] == 10
    assert result["column_count"] == 7

    # Check column structure
    columns = result["columns"]
    column_labels = [c["label"] for c in columns.values()]
    assert "id" in column_labels
    assert "first_name" in column_labels
    assert "email" in column_labels
    assert "salary" in column_labels


# @features ingress-csv
# @dimensions delimiter
def test_semicolon_delimiter():
    """Test processing a semicolon-delimited CSV."""
    csv_path = CSV_DIR / "csv_semicolon.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    assert result["delimiter"] == ";"
    assert result["row_count"] == 3
    assert result["column_count"] == 4

    column_labels = [c["label"] for c in result["columns"].values()]
    assert "name" in column_labels
    assert "email" in column_labels
    assert "status" in column_labels
    assert "score" in column_labels


# @features ingress-csv
# @dimensions empty-rows
def test_empty_rows_skipped():
    """Test that empty rows are skipped during processing."""
    csv_path = CSV_DIR / "csv_with_empties.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    # Should have 4 valid data rows (rows with at least one value)
    assert result["row_count"] == 4
    assert result["column_count"] == 4


# @features ingress-csv
# @dimensions validation
def test_header_only_raises():
    """Test that a CSV with only headers raises an error."""
    csv_path = CSV_DIR / "csv_header_only.csv"
    text = csv_path.read_text()

    with pytest.raises(exceptions.ValidationError, match="No valid data rows"):
        process_csv(text)


# @features ingress-csv
# @dimensions validation
def test_no_header_raises():
    """Test that an empty CSV raises an error."""
    with pytest.raises(exceptions.ValidationError, match="No header row"):
        process_csv("")


# @features ingress-csv
# @dimensions column-ids
def test_rows_keyed_by_column_id():
    """Test that row data is keyed by column IDs."""
    csv_path = CSV_DIR / "sample_data.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    # Each row should be a dict with column IDs as keys
    first_row = result["rows"][0]
    assert isinstance(first_row, dict)

    # Keys should match column IDs
    column_ids = set(result["columns"].keys())
    row_keys = set(first_row.keys())
    assert row_keys == column_ids


# --- Column Type Inference Tests ---


# @features ingress-csv
# @dimensions type-inference email
def test_email_detection():
    """Test that email columns are detected."""
    csv_path = CSV_DIR / "csv_mixed_types.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    email_col = next(c for c in result["columns"].values() if c["label"] == "email")
    assert email_col["type"] == "email"
    assert email_col["icon"] == "email"


# @features ingress-csv
# @dimensions type-inference phone
def test_phone_detection():
    """Test that phone number columns are detected."""
    csv_path = CSV_DIR / "csv_mixed_types.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    phone_col = next(c for c in result["columns"].values() if c["label"] == "phone")
    assert phone_col["type"] == "phone"
    assert phone_col["icon"] == "tel"


# @features ingress-csv
# @dimensions type-inference date
def test_date_detection():
    """Test that date columns are detected."""
    csv_path = CSV_DIR / "csv_mixed_types.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    date_col = next(c for c in result["columns"].values() if c["label"] == "hire_date")
    assert date_col["type"] == "datetime"
    assert date_col["icon"] == "date"


# @features ingress-csv
# @dimensions type-inference url
def test_url_detection():
    """Test that URL columns are detected."""
    csv_path = CSV_DIR / "csv_mixed_types.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    url_col = next(c for c in result["columns"].values() if c["label"] == "website")
    assert url_col["type"] == "url"
    assert url_col["icon"] == "link"


# @features ingress-csv
# @dimensions type-inference url
def test_url_detection_rejects_long_unsupported_path_within_deadline():
    """Reject unsupported URL syntax without pathological regex backtracking."""
    unsupported_url = f"https://example.com/{'a' * 100}?"

    def fail_on_timeout(*_):
        raise TimeoutError("URL type inference exceeded its deadline")

    previous_handler = signal.signal(signal.SIGALRM, fail_on_timeout)
    signal.setitimer(signal.ITIMER_REAL, 1)
    try:
        result = process_csv(f"website\n{unsupported_url}\n")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    url_col = next(
        c for c in result["columns"].values() if c["label"] == "website"
    )
    assert url_col["type"] == "string"


# @features ingress-csv
# @dimensions type-inference boolean
def test_boolean_detection():
    """Test that boolean columns are detected."""
    csv_path = CSV_DIR / "csv_mixed_types.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    bool_col = next(c for c in result["columns"].values() if c["label"] == "active")
    assert bool_col["type"] == "boolean"
    assert bool_col["icon"] == "checkbox"


# @features ingress-csv
# @dimensions type-inference categorical
def test_categorical_detection():
    """Test that categorical columns are detected."""
    csv_path = CSV_DIR / "csv_mixed_types.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    # With improved detection: 8 rows, 3 unique short values = categorical
    cat_col = next(c for c in result["columns"].values() if c["label"] == "category")
    assert cat_col["type"] == "categorical"
    assert cat_col["icon"] == "radio"


# @features ingress-csv
# @dimensions type-inference multi-categorical
def test_multi_categorical_detection():
    """Test that multi-value categorical columns are detected."""
    csv_path = CSV_DIR / "csv_multi_categorical.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    # Both 'tags' and 'departments' should be multi_categorical
    tags_col = next(c for c in result["columns"].values() if c["label"] == "tags")
    assert tags_col["type"] == "multi_categorical"
    assert tags_col["icon"] == "select"


# @features ingress-csv
# @dimensions type-inference number
def test_number_detection():
    """Test that numeric columns are detected."""
    csv_path = CSV_DIR / "sample_data.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    salary_col = next(c for c in result["columns"].values() if c["label"] == "salary")
    assert salary_col["type"] == "number"
    assert salary_col["icon"] == "number"


# @features ingress-csv
# @dimensions type-inference fallback
def test_string_fallback():
    """Test that unrecognized columns default to string type."""
    csv_path = CSV_DIR / "sample_data.csv"
    text = csv_path.read_text()

    result = process_csv(text)

    name_col = next(c for c in result["columns"].values() if c["label"] == "first_name")
    assert name_col["type"] == "string"
    assert name_col["icon"] == "text"
