"""Framework-neutral restriction sentinels for data queries."""

from enum import Enum


# @testable infrastructure
class Restriction(Enum):
    """Sentinel values for permission restriction filters.

    ``UNRESTRICTED`` means no required-access filter should be applied. It is
    intentionally distinct from an empty list, which means the caller has no
    allowed hashes for that filtered view. ``BELONGS_TO_ALL`` bypasses the
    independent required-group membership filter for administrators.
    ``BELONGS_TO_NONE`` means that only entities without required groups match.
    """

    UNRESTRICTED = "UNRESTRICTED"
    BELONGS_TO_ALL = "BELONGS_TO_ALL"
    BELONGS_TO_NONE = "BELONGS_TO_NONE"

    @classmethod
    def is_unrestricted(cls, value):
        return value is cls.UNRESTRICTED

    @classmethod
    def is_denied(cls, value):
        return isinstance(value, list) and not value

    @classmethod
    def from_session(cls, value):
        for marker in cls:
            if value == marker.value:
                return marker
        return value

    @classmethod
    def to_session(cls, value):
        return value.value if isinstance(value, cls) else value
