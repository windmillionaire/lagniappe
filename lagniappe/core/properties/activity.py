"""DB and related-entity properties for activity entities."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities import types as models


from ..mixins import RelatedEntityListMixin, RelatedEntityMixin
from ..tools.files.html import strip_tags
from .base_asset import AssetProperty
from .base_db import DBProperty


NOTE_VISIBILITIES = frozenset({"private", "everyone"})
NOTE_SCOPES = frozenset({"home", "page"})


type _NoteParent = Entity
type _Author = models.User
type _InputFile = models.File


class Visibility(DBProperty[str]):
    """Who may see a note within its owning surface."""

    _id = "visibility"

    @property
    def value(self) -> str:
        return super().value or "private"

    @value.setter
    def value(self, value: str | None) -> None:
        value = value or "private"
        if value not in NOTE_VISIBILITIES:
            raise ValueError("visibility must be 'private' or 'everyone'")
        self._write_db_value(value)


class Scope(DBProperty[str]):
    """Surface that owns and displays a note."""

    _id = "scope"

    @property
    def value(self) -> str:
        return super().value or "home"

    @value.setter
    def value(self, value: str | None) -> None:
        value = value or "home"
        if value not in NOTE_SCOPES:
            raise ValueError("scope must be 'home' or 'page'")
        self._write_db_value(value)


class AttachedParent(RelatedEntityMixin[_NoteParent], DBProperty[_NoteParent]):
    """The parent attached to a note or notification."""

    # Property Attributes
    _id = "parent"


class AttachedUser(RelatedEntityMixin[_Author], DBProperty[_Author]):
    """The user who created a note."""

    # Property Attributes
    _id = "user"


class InputFiles(RelatedEntityListMixin[_InputFile], DBProperty[list[_InputFile]]):
    """Files uploaded as input for an AI report."""

    _id = "input_files"
    _kind = "file"
    _label = "Files"
    _icon = "file"


class Tool(DBProperty[str]):
    """Tool identifier used to generate an AI report."""

    _id = "tool"


class Instructions(DBProperty[str]):
    """Optional user guidance supplied when creating an AI report."""

    _id = "instructions"


class Body(DBProperty[str]):
    """Plain-text body for notes and notifications."""

    # Property Attributes
    _id = "body"

    @property
    def value(self) -> str | None:
        return super().value

    @value.setter
    def value(self, value: str | None) -> None:
        body = strip_tags(value).strip() if value else None
        self._write_db_value(body)


class Photo(AssetProperty):
    """Optional image asset attached to a note."""

    # Property Attributes
    _id = "photo"
    _asset_type = "image"
