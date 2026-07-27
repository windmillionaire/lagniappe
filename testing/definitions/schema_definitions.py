import json
from pathlib import Path

from .schema_fields import SchemaField, SchemaFields

SCHEMAS_DIR = Path(__file__).parent.parent / "files" / "test_schemas"


def load_schema(name: str) -> tuple[SchemaField, ...]:
    """Load a JSON schema file and return a tuple of hydrated SchemaField instances."""
    filepath = SCHEMAS_DIR / f"{name}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Schema file not found: {filepath}")
    with open(filepath) as f:
        return tuple(SchemaField.from_dict(field) for field in json.load(f))

category_with_form_schema = (
    SchemaFields.TEXT_INPUT.get(title="Pseudonym", placeholder="Enter your pseudonym"),
)

add_inputs_schema = (
    SchemaFields.TEXT_INPUT.get(title="Text Input"),
    SchemaFields.EMAIL_INPUT.get(title="Email Input"),
    SchemaFields.NUMBER_INPUT.get(title="Number Input"),
    SchemaFields.DATE_INPUT.get(title="Date Input"),
    SchemaFields.TIME_INPUT.get(title="Time Input"),
    SchemaFields.PHONE_INPUT.get(title="Phone Input"),
)

add_fields_schema = (
    SchemaFields.TEXT_INPUT.get(title="Name", placeholder="Enter your name"),
    SchemaFields.TEXTAREA.get(title="Reason For Living", placeholder="whyyy???"),
    SchemaFields.CHECKBOX.get(title="Subscribe to Newsletter", checked=True),
    SchemaFields.RADIO.get(title="CHOOSE!!!", options=["Option 1", "Option 2"]),
    SchemaFields.SELECT.get(
        title="Select an Option",
        options=["Option 1", "Option 2"],
        multiple=True,
        placeholder="select an option",
    ),
    SchemaFields.TABLE.get(
        title="Table",
        columns=[
            SchemaFields.TEXT_INPUT.get(title="Column 1"),
            SchemaFields.CHECKBOX.get(title="Column 2"),
        ],
    ),
    SchemaFields.LINK.get(title="Website", location="out"),
    SchemaFields.LINK.get(title="Internal Link", location="in"),
    SchemaFields.LOCATION.get(title="Address"),
)

submission_tests = (
    SchemaFields.TEXT_INPUT.get(
        _id="name", title="Name", placeholder="Enter your name"
    ),
    SchemaFields.TEXTAREA.get(
        _id="description", title="Describe your grandma", placeholder="she's a real gem"
    ),
    SchemaFields.CHECKBOX.get(_id="checkbox", title="Is she a zombie?"),
    SchemaFields.RADIO.get(
        _id="radio", title="Favorite Food", options=["Apples", "Tuna"]
    ),
)

project_filter_task_schema = (
    SchemaFields.TEXT_INPUT.get(_id="filter-notes", title="Inspection Notes"),
    SchemaFields.NUMBER_INPUT.get(_id="filter-score", title="Risk Score"),
    SchemaFields.CHECKBOX.get(_id="filter-flagged", title="Requires Follow Up"),
    SchemaFields.SELECT.get(
        _id="filter-decision",
        title="Review Decision",
        options=[
            {"label": "Approved", "value": "approved"},
            {"label": "Needs Review", "value": "needs-review"},
        ],
    ),
    SchemaFields.TABLE.get(
        _id="filter-items",
        title="Inspection Items",
        columns=[
            SchemaFields.TEXT_INPUT.get(_id="filter-row-note", title="Note"),
        ],
    ),
)

category_filter_page_schema = (
    SchemaFields.TEXT_INPUT.get(
        _id="category-filter-notes",
        title="Inspection Notes",
    ),
    SchemaFields.NUMBER_INPUT.get(
        _id="category-filter-score",
        title="Risk Score",
    ),
    SchemaFields.CHECKBOX.get(
        _id="category-filter-flagged",
        title="Requires Follow Up",
    ),
    SchemaFields.SELECT.get(
        _id="category-filter-decision",
        title="Review Decision",
        options=[
            {"label": "Approved", "value": "approved"},
            {"label": "Needs Review", "value": "needs-review"},
        ],
    ),
)

sync_text_schema = (
    SchemaFields.TEXT_INPUT.get(_id="sync-text", title="Sync Text"),
)
