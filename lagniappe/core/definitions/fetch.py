"""Explicit relationship depth declarations for entity fetches."""

from dataclasses import dataclass
from enum import Enum, IntEnum


# @testable infrastructure
# @covered-by lagniappe/core/definitions/fetch.py::Fetch
class FetchDepth(IntEnum):
    """Total relationship depth available after a fetch completes."""

    ROOT = 0
    DIRECT = 1
    NESTED = 2


# @testable infrastructure
# @covered-by lagniappe/core/definitions/fetch.py::Fetch
class FetchReason(Enum):
    """Registered invariants that justify nested relationship loading."""

    TASK_SAVE_REQUIREMENTS = "task-save-requirements"
    TASK_COMBINE_REQUIREMENTS = "task-combine-requirements"
    TASK_FILTER_INDEX_MATERIALIZATION = "task-filter-index-materialization"
    CASCADE_SAVE_REQUIREMENTS = "cascade-save-requirements"
    PERMISSION_REQUIREMENTS_MATERIALIZATION = (
        "permission-requirements-materialization"
    )
    USER_SAVE_REQUIREMENTS = "user-save-requirements"
    DERIVED_PAGE_SAVE_REQUIREMENTS = "derived-page-save-requirements"


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_fetch_requires_registered_reason_for_nested_depth
# @pair entities:explicit-fetch-depth
# @pair permissions:registered-reason
@dataclass(frozen=True)
class Fetch:
    """A caller-owned declaration of the entity graph it needs.

    Root and direct fetches are self-explanatory at their call site. Nested
    fetches cross a second relationship boundary and therefore require a
    registered reason that can be surfaced in request load traces.
    """

    depth: FetchDepth
    reason: FetchReason | None = None

    def __post_init__(self):
        if not isinstance(self.depth, FetchDepth):
            raise TypeError("Fetch depth must be a FetchDepth")
        if self.depth is FetchDepth.NESTED and not isinstance(
            self.reason, FetchReason
        ):
            raise ValueError("Nested fetches require a registered FetchReason")
        if self.depth is not FetchDepth.NESTED and self.reason is not None:
            raise ValueError("Only nested fetches may declare a reason")

    @classmethod
    def root(cls):
        return cls(FetchDepth.ROOT)

    @classmethod
    def direct(cls):
        return cls(FetchDepth.DIRECT)

    @classmethod
    def nested(cls, *, because):
        return cls(FetchDepth.NESTED, reason=because)
