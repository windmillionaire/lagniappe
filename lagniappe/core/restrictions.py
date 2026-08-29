"""Framework-neutral restriction sentinels for data queries."""

from enum import Enum


# @testable infrastructure
class Restriction(Enum):
    """Sentinel values for permission restriction filters.

    ``UNRESTRICTED`` means no required-access filter should be applied. It is
    intentionally distinct from an empty list, which means the caller has no
    allowed hashes for that filtered view.
    """

    UNRESTRICTED = "UNRESTRICTED"

    @classmethod
    def is_unrestricted(cls, value):
        return value is cls.UNRESTRICTED

    @classmethod
    def is_denied(cls, value):
        return isinstance(value, list) and not value

    @classmethod
    def from_session(cls, value):
        return cls.UNRESTRICTED if value == cls.UNRESTRICTED.value else value

    @classmethod
    def to_session(cls, value):
        return cls.UNRESTRICTED.value if value is cls.UNRESTRICTED else value
