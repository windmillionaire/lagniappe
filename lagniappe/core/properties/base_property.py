from ..exceptions import PropertyError
from ..tools.auth.context import current_context_user


UNSET = object()


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_property_contract_errors_are_explicit
# @tests tests_unit/test_002_entity_general_properties.py::test_property_unset_state_is_distinct_from_explicit_values
# @tests tests_unit/test_001_test_general_and_utilities.py::test_property_defaults_to_config_test_user
# @features property
# @dimensions initialization validation unset explicit-false explicit-none current-user propagation
class Property:
    """Base property class. Most entity properties inherit from this.

    Subclasses must set _id (unique within the entity). Optionally set
    _kind (UI theming), _label (display name), and _icon (UI icon).

    ``__getattribute__`` intercepts descriptor-originated ``AttributeError``
    and re-raises as ``PropertyError`` so errors are never silently swallowed
    by ``getattr()`` or ``__getattr__`` higher in the call chain.
    """

    _id = None
    _kind = None
    _label = None
    _icon = None
    _user = None
    _is_entity_valued = False

    def __init__(self, *args, entity=None, **kwargs):
        if not self._id:
            raise NotImplementedError(f"{type(self).__name__} requires _id")
        if not entity:
            raise ValueError(f"{type(self).__name__} requires entity")
        self._entity = entity
        self._user = current_context_user(kwargs.get("user"))

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_property_getattribute_wraps_descriptor_attribute_error
    # @features property
    # @dimensions error-wrapping, descriptor
    def __getattribute__(self, name):
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
    def entity(self):
        return self._entity

    @entity.setter
    def entity(self, value):
        self._entity = value

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, value):
        self._user = value

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        self._id = value

    @property
    def kind(self):
        if not self._kind:
            self._kind = self._entity.entity_kind

        if not self._kind:
            raise NotImplementedError(f"{self.__class__.__name__} requires kind")
        return self._kind

    @kind.setter
    def kind(self, value):
        self._kind = value

    @property
    def icon(self):
        if not self._icon:
            raise NotImplementedError(f"{self.__class__.__name__} requires icon")
        return self._icon

    @icon.setter
    def icon(self, value):
        self._icon = value

    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, value):
        self._label = value

    @property
    def is_set(self):
        return getattr(self, "_value", UNSET) is not UNSET

    def unset(self):
        self._value = UNSET

    @property
    def value(self):
        return self._value if self.is_set else None

    @value.setter
    def value(self, value):
        self._value = value

    @property
    def editable(self):
        return getattr(self, "_editable", False)

    @editable.setter
    def editable(self, value):
        self._editable = value

    @property
    def db_value(self):
        return self.value if self.is_set else None

    @db_value.setter
    def db_value(self, value):
        self._value = value

    @property
    def form_value(self):
        return self.db_value

    @property
    def is_entity_valued(self):
        return self._is_entity_valued

    @property
    def schema(self):
        return None
