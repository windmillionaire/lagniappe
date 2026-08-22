from ..definitions import AI, NotificationEmailMode, Ordering
from ..mixins import ColumnMixin, DateMixin
from .base_db import DBProperty
from .base_asset import AssetProperty
from .base_property import UNSET
from ..tools import utility


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_last_login
# @features user
# @dimensions last-login, date, column
class LastLogin(DateMixin, ColumnMixin, DBProperty):
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


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_email
# @features user
# @dimensions email, column, sort
class Email(ColumnMixin, DBProperty):
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
    def sort_value(self):
        return True if self.value else False


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_profile_photo_value_asset_lifecycle_and_google_download
# @features user
# @dimensions profile-photo default-image asset-lifecycle google-download
class ProfilePhoto(AssetProperty):
    """User profile photo. Stored as an image asset. Downloaded on first access if logged in from Google."""

    _id = "photo"

    @property
    def value(self):
        if super().value:
            return super().value.url

        return "/images/anonymous.png"

    @value.setter
    def value(self, value):
        self._asset = UNSET

        if value:
            self._value = self.entity.save_asset(value, self.id, "image")
        else:
            self.entity.delete_asset(self.id)
            self._value = None

    def save_google_photo(self):
        if self.entity.db.get("photo"):
            image = utility.download_image(self.entity.db["photo"])
            if image["success"]:
                self.value = image["file"]


# @testable false
# @covered-by lagniappe/core/properties/user_entity.py::InvalidateCache.value
class InvalidateCache(DBProperty):
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

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_invalidate_cache
    # @features user, cache
    # @dimensions invalidation, test-user
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_009f_user_ai_access.py::test_user_ai_access_legacy_defaults_validation_and_invalidation
# @features ai-access
# @dimensions persistence legacy-default public validation cache-invalidation
class AIAccess(DBProperty):
    """Canonical per-user AI entitlement name."""

    _id = "ai_access"

    @property
    def value(self):
        stored = DBProperty.value.fget(self)
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
    def value(self, value):
        name = AI.name_for(value)
        previous = self.value
        DBProperty.value.fset(self, name)
        if previous != name:
            self.entity.invalidate_cache = True


# @testable true
# @tests tests_unit/test_029a_notification_email_policy.py::test_notification_email_preference_defaults_and_eligibility
# @pairs notification-email:preference notification-email:eligibility
class NotificationEmailPreference(DBProperty):
    """Canonical per-user notification email mode."""

    _id = "notification_email_mode"

    @property
    def value(self):
        if getattr(self.entity, "is_public", False):
            return NotificationEmailMode.NONE.name
        stored = DBProperty.value.fget(self)
        if stored is None:
            return NotificationEmailMode.DAILY.name
        try:
            return NotificationEmailMode.name_for(stored)
        except ValueError:
            return NotificationEmailMode.NONE.name

    @value.setter
    def value(self, value):
        name = NotificationEmailMode.name_for(value)
        if (
            getattr(self.entity, "is_public", False)
            and name != NotificationEmailMode.NONE.name
        ):
            raise ValueError("Public users cannot receive notification email.")
        previous = self.value
        DBProperty.value.fset(self, name)
        if name == NotificationEmailMode.NONE.name and previous != name:
            self.entity.db["notification_email_opt_out_epoch"] = int(
                self.entity.db.get("notification_email_opt_out_epoch") or 0
            ) + 1


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_is_owner
# @tests tests_unit/test_009a_user.py::test_user_admin_role_is_separate_from_owner_and_invalidates_cache
# @pairs user:owner user:property owner:singleton
class IsOwner(DBProperty):
    """Whether this row is the configured singleton primary Owner."""

    _id = "owner"

    @property
    def value(self):
        stored = bool(DBProperty.value.fget(self))
        if getattr(self.entity, "_testing", False):
            return stored

        email = str(self.entity.db.get("email") or "").strip().casefold()
        from ..entities import user as user_module

        owner_email = str(
            getattr(user_module.CONFIG, "ADMIN_EMAIL", "") or ""
        ).strip().casefold()
        validated_email = getattr(self, "_validated_owner_email", "")
        return bool(
            stored
            and email
            and (email == owner_email or email == validated_email)
        )

    @value.setter
    def value(self, value):
        enabled = bool(value)
        if not getattr(self.entity, "_testing", False):
            email = str(self.entity.db.get("email") or "").strip().casefold()
            from ..entities import user as user_module

            owner_email = str(
                getattr(user_module.CONFIG, "ADMIN_EMAIL", "") or ""
            ).strip().casefold()
            if enabled and (not owner_email or email != owner_email):
                raise ValueError("Only the configured primary Owner can be an owner.")
            if not enabled and self.value:
                raise ValueError("The configured primary Owner cannot be demoted.")
            if enabled:
                self._validated_owner_email = owner_email
        DBProperty.value.fset(self, enabled)


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_admin_role_is_separate_from_owner_and_invalidates_cache
# @pairs admin:role admin:legacy-default admin:ai-independent
# @pairs user:property cache:cache-invalidation
class IsAdmin(DBProperty):
    """Stored additional-Administrator role, with Owner inheritance."""

    _id = "admin"

    @property
    def value(self):
        return bool(getattr(self.entity, "is_owner", False) or DBProperty.value.fget(self))

    @value.setter
    def value(self, value):
        enabled = bool(value)
        previous = bool(DBProperty.value.fget(self))
        DBProperty.value.fset(self, enabled)
        if previous != enabled:
            self.entity.invalidate_cache = True


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair messaging:owner-opt-in
class OwnerInboundToggle(DBProperty):
    """Fail-closed owner opt-in for a collaboration channel."""

    _truthy = {True, "true", "True", "1", 1, "on", "yes"}

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair messaging:owner-opt-in
    @property
    def value(self):
        return self.entity.db.get(self.db_key, False) in self._truthy

    @value.setter
    def value(self, value):
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


# @testable true
# @tests tests_unit/test_009a_user.py::test_page_update_user_authorization_rules
# @pair public-users:email-consent
class AllowSiteEmail(OwnerInboundToggle):
    """Fail-closed public-user consent for email sent by the site owner."""

    _id = "allow_site_email"
