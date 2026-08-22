"""Notification-email service errors."""


class NotificationEmailError(RuntimeError):
    """Raised when a queued notification email cannot be completed yet."""
