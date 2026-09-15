"""Typed, actor-aware values keyed by the exact submission field IDs."""

from lagniappe.core.mixins import AIMixin


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_schema.py::execute_get_schema
# @covered-by lagniappe/core/tools/ai/function_definitions/get_task_history.py::execute_get_task_history
# @reason current and original reads share typed field projections and reference permissions
# @covered-by lagniappe/core/tools/ai/autofill.py::autofill_prompt_data
def values_by_id(fields, user):
    values = {}
    for field_id, field in fields.items():
        if isinstance(field, AIMixin) and field.is_set:
            field.user = user
            value = field.ai_value
            if value is not None:
                values[field_id] = value
    return values
