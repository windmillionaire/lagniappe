from .entity import Entity
from ..definitions import Action
from ..mixins import AssetMixin
from ..properties import activity
from ..tools.user_context import current_context_user


# @testable false
# @covered-by lagniappe/core/entities/note.py::Note.create
# @reason note entity shell metadata is exercised through the homepage activity create path
class Note(AssetMixin, Entity):
    entity_kind = "note"

    @property
    def exclude_from_index(self):
        exclude = {
            "assets",
            "body",
        }
        return frozenset(exclude)

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "parent": activity.AttachedParent,
                "user": activity.AttachedUser,
                "body": activity.Body,
                "photo": activity.Photo,
                "visibility": activity.Visibility,
                "scope": activity.Scope,
            }
        )
        return properties

    @property
    def required(self):
        return [self.parent.hash]

    # @testable true
    # @tests tests_unit/test_002j_notes.py::test_note_permissions_follow_visibility_scope_and_authorship
    # @features notes permissions
    # @dimensions private shared home page creator owner
    def allowed(self, action, user=None):
        user = current_context_user(user)
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_admin", False) or getattr(user, "is_owner", False):
            return True

        author_key = self.properties.user.key
        if author_key and author_key == user.key:
            return Action.DELETE.implies(action)

        if action is not Action.VIEW or self.visibility != "everyone":
            return False

        if self.scope == "home":
            return True

        return bool(
            self.scope == "page"
            and self.parent
            and self.parent.allowed(Action.VIEW, user=user)
        )

    # @testable true
    # @tests tests_unit/test_002j_notes.py::test_note_create_persists_body_photo_visibility_and_scope
    # @features notes
    # @dimensions create body photo parent visibility scope
    @classmethod
    def create(cls, data):
        parent = data.get("parent") or data.get("user")
        user = data.get("user")

        if not parent or not user:
            raise ValueError("notes require a parent and author")

        new_note = cls(parent=parent)
        new_note.kind = cls.entity_kind
        new_note.parent = parent

        new_note.user = user

        new_note.body = data.get("body")
        new_note.visibility = data.get("visibility") or "private"
        new_note.scope = data.get("scope") or "home"

        photo = data.get("photo")
        if photo and getattr(photo, "filename", None):
            new_note.photo = photo

        return new_note
