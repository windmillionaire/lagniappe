from typing import TYPE_CHECKING, cast

from ..exceptions import PropertyError
from ..tools.auth.context import current_context_user


if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.site import Site
    from ..mixins.field_host import FieldUser


UNSET = object()


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_property_contract_errors_are_explicit
# @tests tests_unit/test_002_entity_general_properties.py::test_property_unset_state_is_distinct_from_explicit_values
# @tests tests_unit/test_001_test_general_and_utilities.py::test_property_defaults_to_config_test_user
# @matrix property : current-user explicit-false explicit-none initialization propagation unset validation
class Property[Value = object, Owner: Entity | Site = "Entity", Write = Value | None]:
    """Base property class. Most entity properties inherit from this.

    Subclasses must set _id (unique within the entity). Optionally set
    _kind (UI theming), _label (display name), and _icon (UI icon).

    ``__getattribute__`` intercepts descriptor-originated ``AttributeError``
    and re-raises as ``PropertyError`` so errors are never silently swallowed
    by ``getattr()`` or ``__getattr__`` higher in the call chain.
    """

    _id: str | None = None
    _kind: str | None = None
    _label: str | None = None
    _icon: str | None = None
    _user: FieldUser = None
    _value: object
    _is_entity_valued = False

    def __init__(self, *args: object, entity: Owner | None = None, **kwargs: object) -> None:
        if not self._id:
            raise NotImplementedError(f"{type(self).__name__} requires _id")
        if not entity:
            raise ValueError(f"{type(self).__name__} requires entity")
        self._entity = entity
        self._user = current_context_user(cast("FieldUser", kwargs.get("user")))

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_property_getattribute_wraps_descriptor_attribute_error
    # @matrix property : descriptor error-wrapping
    def __getattribute__(self, name: str) -> object:
        try:
            return object.__getattribute__(self, name)
        except AttributeError as e:
            for cls in type(self).__mro__:
                if name in cls.__dict__:
                    raise PropertyError(
                        f"Error in {name!r} on property "
                        f"{object.__getattribute__(self, '_id')!r}: {e}",
                        entity=object.__getattribute__(self, "_entity"),
                    ) from e
            raise

    @property
    def entity(self) -> Owner:
        return self._entity

    @entity.setter
    def entity(self, value: Owner) -> None:
        self._entity = value

    @property
    def user(self) -> FieldUser:
        return self._user

    @user.setter
    def user(self, value: FieldUser) -> None:
        self._user = value

    @property
    def id(self) -> str:
        # __init__ requires a nonempty id before exposing the property.
        return cast(str, self._id)

    @id.setter
    def id(self, value: str) -> None:
        self._id = value

    @property
    def kind(self) -> str:
        if not self._kind:
            self._kind = self._entity.entity_kind

        if not self._kind:
            raise NotImplementedError(f"{self.__class__.__name__} requires kind")
        return self._kind

    @kind.setter
    def kind(self, value: str) -> None:
        self._kind = value

    @property
    def icon(self) -> str:
        if not self._icon:
            raise NotImplementedError(f"{self.__class__.__name__} requires icon")
        return self._icon

    @icon.setter
    def icon(self, value: str) -> None:
        self._icon = value

    @property
    def label(self) -> str | None:
        return self._label

    @label.setter
    def label(self, value: str | None) -> None:
        self._label = value

    @property
    def is_set(self) -> bool:
        return getattr(self, "_value", UNSET) is not UNSET

    def unset(self) -> None:
        self._value = UNSET

    @property
    def value(self) -> Value | None:
        # The cache can also contain UNSET; is_set excludes only that sentinel.
        return cast("Value | None", self._value) if self.is_set else None

    @value.setter
    def value(self, value: Write) -> None:
        self._value = value

    @property
    def editable(self) -> bool:
        return getattr(self, "_editable", False)

    @editable.setter
    def editable(self, value: bool) -> None:
        self._editable = value

    @property
    def db_value(self) -> object:
        return self.value if self.is_set else None

    @db_value.setter
    def db_value(self, value: object) -> None:
        self._value = value

    @property
    def form_value(self) -> object:
        return self.db_value

    @property
    def is_entity_valued(self) -> bool:
        return self._is_entity_valued

    @property
    def schema(self) -> dict[str, object] | None:
        return None
