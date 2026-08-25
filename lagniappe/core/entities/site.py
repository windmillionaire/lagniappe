from google.cloud import datastore

from ..exceptions import PropertyError
from ..tools import database
from ..tools.database import site as site_database


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_site_lazy_properties_database_key_and_error_context
# @tests tests_unit/test_002_entity_general_properties.py::test_site_missing_key_raises_runtime_error
# @matrix site : db-key error-wrapping lazy-properties validation
class Site:
    """Base class for non-Entity site-level objects (Home, Index).

    Unlike Entity, Site objects don't have a kind, properties system,
    or cache/filter output. They provide DB access via a site key
    and lazy property instantiation.
    """

    _site_id = None
    _key = None
    _kind = None
    _entity = None

    def __init__(self, *args, **kwargs):
        identifier = args[0] if args and args[0] else None
        self._db = identifier if isinstance(identifier, datastore.Entity) else {}
        self._instances = {}
        self._properties = self._get_properties()
        self._entity = kwargs.get("entity") or self

        if isinstance(identifier, str):
            self._site_id = identifier

    def __getattr__(self, name):
        if name in self._instances:
            return self._instances[name]
        elif name in self._properties:
            try:
                self._instances[name] = self._properties[name](entity=self._entity)
            except PropertyError:
                raise
            except Exception as e:
                raise PropertyError(
                    f"Property {name!r} failed to instantiate on "
                    f"{type(self).__name__}: {e}",
                    entity=self._entity,
                ) from e
            return self._instances[name]
        else:
            raise AttributeError(f"Property {name} not found")

    @property
    def entity(self):
        return getattr(self, "_entity", None)

    @property
    def kind(self):
        return self._kind

    @property
    def key(self):
        if self._db and not self._key:
            self._key = self._db.key
        elif self._site_id:
            self._key = site_database.key(self._site_id)
        else:
            raise ValueError("Site identifier not set")

        return self._key

    @property
    def urlsafe_key(self):
        if not self.key:
            raise RuntimeError("no key assigned")

        if getattr(self, "_urlsafe_key", None):
            return self._urlsafe_key

        self._urlsafe_key = database.get.urlsafe_key(self.key)
        return self._urlsafe_key

    @property
    def db(self):
        if self._db:
            return self._db

        if not self.key:
            raise RuntimeError("no key assigned")

        self._db = site_database.get_or_create(self.key)

        return self._db

    def save(self):
        database.save(self)
