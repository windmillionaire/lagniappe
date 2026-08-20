import json

from .base_property import Property


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_db_property_blanks_pop_but_explicit_false_persists
# @tests tests_unit/test_002_entity_general_properties.py::test_db_property_custom_blank_values_can_keep_empty_lists
# @tests tests_unit/test_002_entity_general_properties.py::test_db_property_write_refreshes_entity_details_and_cache
# @features db-property
# @dimensions missing-key explicit-false blank-values custom-blank-values cache-invalidation
class DBProperty(Property):
    """Property that persists its value in entity.db.

    Reads from entity.db on first access and writes back on set.
    Set ``json = True`` on a subclass to auto-serialize/deserialize.
    Override ``db_key`` to store under a different key than ``self.id``.

    Set:
        value (any): Stored in entity.db[db_key]. JSON-encoded if ``json = True``.

    Get:
        value (any): Loaded from entity.db[db_key]. JSON-decoded if ``json = True``.
    """

    _blank_values = (None, [], {})

    @property
    def value(self):
        if self.is_set:
            return self._value

        if self.db_key not in self.entity.db:
            return None

        value = self.entity.db.get(self.db_key)
        if isinstance(value, str) and getattr(self, "json", False):
            value = json.loads(value)

        if value in self._blank_values:
            return None

        self._value = value

        return self._value

    @value.setter
    def value(self, value):
        if value in self._blank_values:
            self.entity.db.pop(self.db_key, None)
            self.unset()
        elif getattr(self, "json", False):
            self._value = value
            self.entity.db[self.db_key] = json.dumps(value)
        else:
            self._value = value
            self.entity.db[self.db_key] = value

        if hasattr(self.entity, "_details"):
            self.entity._details = None
        if hasattr(self.entity, "_to_cache"):
            self.entity._to_cache = None

    @property
    def db_key(self):
        return self.id
