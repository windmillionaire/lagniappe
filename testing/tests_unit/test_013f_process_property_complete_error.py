"""``ProcessProperty`` ``complete`` / ``error`` setters are mutually exclusive."""

import pytest

from lagniappe.core.properties.base_process import ProcessProperty

from testing.utility.test_entities import TestEntities


class _SampleStep(ProcessProperty):
    process_id = "sample_proc"
    section_id = "step_a"
    attributes = ()


class _MissingProcessId(ProcessProperty):
    section_id = "step_a"
    attributes = ()


class _MissingSectionId(ProcessProperty):
    process_id = "sample_proc"
    attributes = ()


class _BadAttributes(ProcessProperty):
    process_id = "sample_proc"
    section_id = "step_a"
    attributes = []


def _task():
    return TestEntities.get(
        "TASK",
        {
            "name": "ProcessProperty sample",
            "hash": "ppx001",
            "page": {"name": "Parent", "hash": "pgppx1"},
        },
    )


# @features process-property
# @dimensions error complete-state
@pytest.mark.unit
def test_process_property_error_clears_complete():
    """Setting ``error`` removes ``complete`` from the section."""
    step = _SampleStep(entity=_task())
    step.complete = True
    assert step.complete is True

    step.error = "Something went wrong"

    assert step.error == "Something went wrong"
    assert step.complete is None


# @features process-property
# @dimensions complete error-state
@pytest.mark.unit
def test_process_property_complete_clears_error():
    """Setting ``complete`` removes ``error`` from the section."""
    step = _SampleStep(entity=_task())
    step.error = "Prior failure"
    assert step.error == "Prior failure"

    step.complete = True

    assert step.complete is True
    assert step.error is None


# @features process-property
# @dimensions initialization validation
@pytest.mark.unit
def test_process_property_contract_errors_are_explicit():
    entity = _task()

    with pytest.raises(NotImplementedError, match="requires process_id"):
        _MissingProcessId(entity=entity)

    with pytest.raises(NotImplementedError, match="requires section_id"):
        _MissingSectionId(entity=entity)

    with pytest.raises(TypeError, match="attributes must be a tuple"):
        _BadAttributes(entity=entity)
