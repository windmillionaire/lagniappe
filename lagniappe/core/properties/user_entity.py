from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from ..definitions import AI, NotificationEmailMode, Ordering
from ..mixins import ColumnMixin, DateMixin
from ..tools.files.downloads import download_image, downloaded_image_file
from ..tools.http import PROFILE_IMAGE_POLICY
from .base_asset import AssetProperty
from .base_db import DBProperty
from .base_property import UNSET

if TYPE_CHECKING:
    from ..definitions.asset import AssetUpload, ImageAsset
    from ..entities.user import User as User


class LastLogin(DateMixin, ColumnMixin, DBProperty[datetime, "User"]):
    """User's last login timestamp.

    Set:
        value (datetime): Login time (UTC).

    Get:
        value (datetime): UTC datetime.
        column_value (datetime): User-timezone datetime (via DateMixin).
    """

    # Property Attributes
    _id = "last_login"
    _label = "Last Login"
    _icon = "login"
    _ordering = Ordering.NUMERIC


class Email(ColumnMixin, DBProperty[str, "User"]):
    """User's email address.

    Set:
        value (str): Email address.

    Get:
        value (str): Email address.
        sort_value (bool): Whether an email exists (EXISTS ordering).
    """

    _id = "email"
    _label = "Email"
    _icon = "email"
    _ordering = Ordering.EXISTS

    @property
    def sort_value(self) -> bool:
        return bool(self.value)


class ProfilePhoto(AssetProperty["User", str, "AssetUpload | None"]):
    """User profile photo. Stored as an image asset. Downloaded on first access if logged in from Google."""

    _id = "photo"

    @property
    def value(self) -> str | None:
        stored = cast("ImageAsset | None", self._stored_asset())
        if stored:
            return stored.url

        return "/images/anonymous.png"

    @value.setter
    def value(self, value: AssetUpload | None) -> None:
        self._asset = UNSET

        if value:
            self._value = self.entity.save_asset(value, self.id, "image")
        else:
            self.entity.delete_asset(self.id)
            self._value = None

    def save_google_photo(self) -> None:
        if self.entity.db.get("photo"):
            result = download_image(
                cast(str, self.entity.db["photo"]), policy=PROFILE_IMAGE_POLICY
            )
            image = downloaded_image_file(result)
            if image is not None:
                self.value = image


class InvalidateCache(DBProperty[bool, "User", object]):
    """Flag to trigger client-side cache invalidation.

    Set to True when permissions change. The service worker reads this
    from the response header, clears its cache and ETag store, then calls
    /l/validate-user with a clear confirmation to reset the flag.

    Set:
        value (bool): True to invalidate, False to clear the flag.

    Get:
        value (bool): Whether the cache needs invalidating.
    """

    _id = "invalidate_cache"

    @property
    def value(self) -> bool | None:
        return super().value

    @value.setter
    def value(self, value: object) -> None:
        self._write_db_value(value)
        if value:
            # Each mutation owns a distinct acknowledgement, including a
            # second invalidation while an earlier one is still outstanding.
            self.entity.db["cache_invalidation_revision"] = uuid4().hex


class AIAccess(DBProperty[str, "User", object]):
    """Canonical per-user AI entitlement name."""

    _id = "ai_access"

    @property
    def value(self) -> str:
        stored = self._read_db_value()
        if stored is None:
            return (
                AI.NONE.name
                if getattr(self.entity, "is_public", False)
                else AI.CREATE.name
            )
        try:
            return AI.name_for(stored)
        except ValueError:
            return AI.NONE.name

    @value.setter
    def value(self, value: object) -> None:
        name = AI.name_for(value)
        previous = self.value
        self._write_db_value(name)
        if previous != name:
            self.entity.invalidate_cache = True


class NotificationEmailPreference(DBProperty[str, "User", object]):
    """Canonical per-user notification email mode."""

    _id = "notification_email_mode"

    @property
    def value(self) -> str:
        if getattr(self.entity, "is_public", False):
            return NotificationEmailMode.NONE.name
        stored = self._read_db_value()
        if stored is None:
            return NotificationEmailMode.DAILY.name
        try:
            return NotificationEmailMode.name_for(stored)
        except ValueError:
            return NotificationEmailMode.NONE.name

    @value.setter
    def value(self, value: object) -> None:
        name = NotificationEmailMode.name_for(value)
        if (
            getattr(self.entity, "is_public", False)
            and name != NotificationEmailMode.NONE.name
        ):
            raise ValueError("Public users cannot receive notification email.")
        previous = self.value
        self._write_db_value(name)
        if name == NotificationEmailMode.NONE.name and previous != name:
            self.entity.db["notification_email_opt_out_epoch"] = (
                int(cast(int | str, self.entity.db.get("notification_email_opt_out_epoch") or 0)) + 1
            )


class IsOwner(DBProperty[bool, "User", object]):
    """Whether this row is the configured singleton primary Owner."""

    _id = "owner"

    @property
    def value(self) -> bool:
        stored = bool(self._read_db_value())
        if getattr(self.entity, "_testing", False):
            return stored

        email = str(self.entity.db.get("email") or "").strip().casefold()
        from ..entities import user as user_module

        owner_email = (
            str(getattr(user_module.CONFIG, "ADMIN_EMAIL", "") or "").strip().casefold()
        )
        validated_email = getattr(self, "_validated_owner_email", "")
        return bool(
            stored and email and (email in (owner_email, validated_email))
        )

    @value.setter
    def value(self, value: object) -> None:
        enabled = bool(value)
        if not getattr(self.entity, "_testing", False):
            email = str(self.entity.db.get("email") or "").strip().casefold()
            from ..entities import user as user_module

            owner_email = (
                str(getattr(user_module.CONFIG, "ADMIN_EMAIL", "") or "")
                .strip()
                .casefold()
            )
            if enabled and (not owner_email or email != owner_email):
                raise ValueError("Only the configured primary Owner can be an owner.")
            if not enabled and self.value:
                raise ValueError("The configured primary Owner cannot be demoted.")
            if enabled:
                self._validated_owner_email = owner_email
        self._write_db_value(enabled)


class IsAdmin(DBProperty[bool, "User", object]):
    """Stored additional-Administrator role, with Owner inheritance."""

    _id = "admin"

    @property
    def value(self) -> bool:
        return bool(
            getattr(self.entity, "is_owner", False) or self._read_db_value()
        )

    @value.setter
    def value(self, value: object) -> None:
        enabled = bool(value)
        previous = bool(self._read_db_value())
        self._write_db_value(enabled)
        if previous != enabled:
            self.entity.invalidate_cache = True


class OwnerInboundToggle(DBProperty[bool, "User", object]):
    """Fail-closed owner opt-in for a collaboration channel."""

    _truthy = {True, "true", "True", "1", "on", "yes"}

    @property
    def value(self) -> bool:
        return self.entity.db.get(self.db_key, False) in self._truthy

    @value.setter
    def value(self, value: object) -> None:
        enabled = value in self._truthy
        self._value = enabled
        if enabled:
            self.entity.db[self.db_key] = True
        else:
            self.entity.db.pop(self.db_key, None)


class AllowMessagesAndMentions(OwnerInboundToggle):
    _id = "allow_messages_and_mentions"


class AllowTaskAssignments(OwnerInboundToggle):
    _id = "allow_task_assignments"


class AllowSiteEmail(OwnerInboundToggle):
    """Fail-closed public-user consent for email sent by the site owner."""

    _id = "allow_site_email"


class AllowAutoExecute(OwnerInboundToggle):
    """Fail-closed user opt-in for automatic safe plan execution."""

    _id = "allow_auto_execute"
