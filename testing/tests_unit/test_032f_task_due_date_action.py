"""Calendar-date validation shared by cohesive Task updates."""
import pytest
from lagniappe.core import exceptions
from lagniappe.core.tools.ai.reporting.schedules import validate_task_due_date

# @matrix ai-report task-scheduling : due-date validation
@pytest.mark.unit
@pytest.mark.parametrize("value,valid", [
    (None, True), ("2026-09-12", True), ("2028-02-29", True),
    ("2026-02-29", False), ("2026-13-01", False), ("tomorrow", False),
    ("", False), (False, False), ("20260912", False), ("2026-9-12", False),
    ("2026-09-12T00:00:00Z", False),
])
def test_due_date_contract_validates_calendar_dates(value, valid):
    if valid:
        assert validate_task_due_date(value) == value
    else:
        with pytest.raises(exceptions.AIException, match="YYYY-MM-DD"):
            validate_task_due_date(value)
