from ..definitions import AI, Ordering
from ..mixins import ColumnMixin, DateMixin
from .base_db import DBProperty
from .base_asset import AssetProperty
from .base_property import UNSET
from ..tools import utility


# @testable false
# @covered-by lagniappe/core/properties/user_entity.py::NotificationRevision
# @covered-by lagniappe/core/properties/user_entity.py::OperationRevision
# @reason concrete user polling cursors exercise the shared monotonic value behavior
class PersonalRevision(DBProperty):
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, max(int(value or 0), 0))

    def update(self):
        self.value = self.value + 1


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_personal_revisions_default_and_advance_independently
# @pairs user:personal-activity user:revision
# @pairs polling:personal-activity polling:revision
# @pairs notifications:personal-activity notifications:revision
class NotificationRevision(PersonalRevision):
    """Monotonic cursor for this user's notification collection."""

    _id = "notification_revision"


# @testable true
# @tests tests_unit/test_009a_user.py::test_user_personal_revisions_default_and_advance_independently
# @pairs user:personal-activity user:revision
# @pairs polling:personal-activity polling:revision
# @pairs deferred-jobs:personal-activity deferred-jobs:revision
class OperationRevision(PersonalRevision):
    """Monotonic cursor for this user's durable-operation statuses."""

    _id = "operation_revision"


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
    /validate-user with a clear confirmation to reset the flag.

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
# @tests tests_unit/test_009a_user.py::test_user_is_owner
# @features user
# @dimensions owner, property
class IsOwner(DBProperty):
    """Whether the user is a site owner (highest privilege level)."""

    _id = "owner"
