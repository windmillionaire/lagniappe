"""Default schema and seed data for reserved user entities."""

from datetime import datetime, timezone
import json


DEFAULT_USER_SCHEMA = [
    {
        "id": "name",
        "input": "text",
        "label": "Name",
        "placeholder": "Name",
        "type": "input",
        "required": True,
    },
    {
        "type": "input",
        "id": "email",
        "label": "Email",
        "placeholder": "Email",
        "input": "email",
        "required": True,
    },
]

DEFAULT_USER_PAGE = {
    "name": "Users",
    "reserved": True,
    "type": "users",
    "created": datetime.now(timezone.utc),
}

DEFAULT_USER_FORM = {
    "name": "User",
    "reserved": True,
    "type": "form",
    "created": datetime.now(timezone.utc),
    "schema": json.dumps(DEFAULT_USER_SCHEMA),
}
