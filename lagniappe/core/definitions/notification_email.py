"""Per-user notification email delivery modes."""

from enum import Enum


class NotificationEmailMode(Enum):
    """Stored names for notification email preferences."""

    NONE = "none"
    IMMEDIATE = "immediate"
    DAILY = "daily"

    # @testable true
    # @tests tests_unit/test_029a_notification_email_policy.py::test_notification_email_preference_defaults_and_eligibility
    # @pair notification-email:preference
    @classmethod
    def name_for(cls, value):
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
