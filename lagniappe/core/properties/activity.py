"""DB and related-entity properties for activity entities."""

from ..mixins import RelatedEntityListMixin, RelatedEntityMixin
from ..tools import utility
from .base_asset import AssetProperty
from .base_db import DBProperty


NOTE_VISIBILITIES = frozenset({"private", "everyone"})
NOTE_SCOPES = frozenset({"home", "page"})


# @testable true
# @tests tests_unit/test_002j_notes.py::test_note_visibility_and_scope_validate_values
# @features notes
# @dimensions visibility persistence validation
class Visibility(DBProperty):
    """Who may see a note within its owning surface."""

    _id = "visibility"

    @property
    def value(self):
        return super().value or "private"

    @value.setter
    def value(self, value):
        value = value or "private"
        if value not in NOTE_VISIBILITIES:
            raise ValueError("visibility must be 'private' or 'everyone'")
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_002j_notes.py::test_note_visibility_and_scope_validate_values
# @features notes
# @dimensions scope persistence validation
class Scope(DBProperty):
    """Surface that owns and displays a note."""

    _id = "scope"

    @property
    def value(self):
        return super().value or "home"

    @value.setter
    def value(self, value):
        value = value or "home"
        if value not in NOTE_SCOPES:
            raise ValueError("scope must be 'home' or 'page'")
        DBProperty.value.fset(self, value)


class AttachedParent(RelatedEntityMixin, DBProperty):
    """The parent attached to a note or notification."""

    # Property Attributes
    _id = "parent"


class AttachedUser(RelatedEntityMixin, DBProperty):
    """The user who created a note."""

    # Property Attributes
    _id = "user"


class Target(RelatedEntityMixin, DBProperty):
    """The entity a notification points back to."""

    # Property Attributes
    _id = "target"


class InputFiles(RelatedEntityListMixin, DBProperty):
    """Files uploaded as input for an AI report."""

    _id = "input_files"
    _kind = "file"
    _label = "Files"
    _icon = "file"


class Tool(DBProperty):
    """Tool identifier used to generate an AI report."""

    _id = "tool"


class Instructions(DBProperty):
    """Optional user guidance supplied when creating an AI report."""

    _id = "instructions"


# @testable false
# @covered-by lagniappe/core/entities/notification.py::Notification.create
# @reason pending is notification metadata exercised through notification workflows
class Pending(DBProperty):
    """Whether a notification represents work still in progress."""

    _id = "pending"
    _truthy = {True, "true", "True", "1", 1, "on", "yes"}

    @property
    def value(self):
        return self.entity.db.get(self.db_key, False) in self._truthy

    @value.setter
    def value(self, value):
        pending = value in self._truthy
        self._value = pending

        if pending:
            self.entity.db[self.db_key] = True
        else:
            self.entity.db.pop(self.db_key, None)


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_create_note_body_and_photo_from_home
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_process_notification_uses_menu_not_home_notes
# @features activity notes notifications
# @dimensions body html-stripping
class Body(DBProperty):
    """Plain-text body for notes and notifications."""

    # Property Attributes
    _id = "body"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        body = utility.strip_tags(value).strip() if value else None
        DBProperty.value.fset(self, body)


# @testable true
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_create_note_body_and_photo_from_home
# @features activity notes
# @dimensions photo asset-lifecycle
class Photo(AssetProperty):
    """Optional image asset attached to a note."""

    # Property Attributes
    _id = "photo"
    _asset_type = "image"
