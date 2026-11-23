"""Type requirements supplied by the field that owns a projection mixin."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Literal, overload

    from werkzeug.local import LocalProxy

    from ..entities.entity import Entity
    from ..entities.user import User

    type FieldUser = User | LocalProxy[User | None] | None

    class FieldHost:
        """Describe host attributes without overriding the field's descriptors."""

        @overload
        def __getattr__(self, name: Literal["schema"]) -> dict[str, object] | None: ...
        @overload
        def __getattr__(self, name: Literal["id", "kind"]) -> str: ...
        @overload
        def __getattr__(self, name: Literal["label", "icon"]) -> str | None: ...
        @overload
        def __getattr__(self, name: Literal["value"]) -> object: ...
        @overload
        def __getattr__(self, name: Literal["is_set", "is_entity_valued"]) -> bool: ...
        @overload
        def __getattr__(self, name: Literal["entity"]) -> Entity: ...
        def __getattr__(self, name: str) -> object: ...

        @property
        def user(self) -> FieldUser: ...
        @user.setter
        def user(self, value: FieldUser) -> None: ...
else:
    # Runtime mixin behavior comes entirely from the concrete field class.
    FieldHost = object
