"""Per-user AI access tiers."""

from enum import Enum, auto

from .default import DefaultEnum


# @testable true
# @tests tests_unit/test_009f_user_ai_access.py::test_ai_access_tiers_are_hierarchical_and_fail_closed
# @matrix ai-access : fail-closed hierarchy validation
class AI(Enum, metaclass=DefaultEnum):
    """Hierarchical AI entitlements, independent from resource permissions."""

    NONE = 0
    ASK = auto()
    CREATE = auto()

    DEFAULT = NONE

    def implies(self, required):
        """Return whether this tier includes a concrete required AI capability."""
        return bool(
            isinstance(required, AI)
            and required is not AI.NONE
            and self is not AI.NONE
            and self.value >= required.value
        )

    @classmethod
    def name_for(cls, value):
        """Normalize an enum or exact stored/form name, rejecting unknown values."""
        if isinstance(value, cls):
            return value.name
        if isinstance(value, str) and value in {
            cls.NONE.name,
            cls.ASK.name,
            cls.CREATE.name,
        }:
            return value
        raise ValueError("AI access must be CREATE, ASK, or NONE.")
