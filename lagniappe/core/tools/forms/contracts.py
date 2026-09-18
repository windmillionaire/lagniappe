"""Persisted Form-change vocabulary and value helpers shared below workflows."""

from copy import deepcopy
import json

from ...exceptions import ValidationError

PENDING = "pending_form_change"
NOTICE = "pre_migration"
RECEIPT = "form_change_receipt"
ANSWER_FIELDS = (
    "form",
    "submission",
    "generation",
    "completed",
    "completed_submission",
    "assets",
)


# @testable false
# @covered-by lagniappe/core/tools/forms/changes.py::start_change
# @covered-by lagniappe/core/tools/forms/changes.py::apply_target
# @reason persisted JSON is read explicitly at job, mutation, and projection boundaries
def json_value(raw, name):
    value = raw.get(name)
    value = json.loads(value) if isinstance(value, str) else deepcopy(value)
    if value is not None and not isinstance(value, dict):
        raise ValidationError("Saved form change data needs repair.")
    return value or {}


# @testable false
# @covered-by lagniappe/core/tools/forms/changes.py::apply_target
# @reason bounded records are checked before any live answer is changed
def check_size(raw):
    if (
        len(json.dumps(dict(raw), default=str, ensure_ascii=False).encode())
        > 900 * 1024
    ):
        raise ValidationError(
            "A submission or Form is too large to retain its changed values. No further changes were applied."
        )


# @testable false
# @covered-by lagniappe/core/tools/forms/schema_updates.py::inspect_scope
# @reason blank collection envelopes should never require a provider call
def needs_ai_value(value):
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, dict) and (value == {"rows": []} or value == {"items": []}):
        return False
    return True
