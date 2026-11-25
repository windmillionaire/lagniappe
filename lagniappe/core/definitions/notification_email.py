"""Per-user notification email delivery modes."""

from enum import Enum


class NotificationEmailMode(Enum):
    """Stored names for notification email preferences."""

    NONE = "none"
    IMMEDIATE = "immediate"
    DAILY = "daily"

    @classmethod
    def name_for(cls, value: object) -> str:
        """Normalize an enum or exact stored/form name."""
        if isinstance(value, cls):
            return value.name
        if isinstance(value, str):
            name = value.strip().upper()
            if name in cls.__members__:
                return name
        raise ValueError(
            "Notification email preference must be NONE, IMMEDIATE, or DAILY."
        )
