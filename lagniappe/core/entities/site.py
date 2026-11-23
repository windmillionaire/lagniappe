from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Never, Self, cast

from google.cloud import datastore
from google.cloud.datastore import Key

if TYPE_CHECKING:
    from .entity import Entity

from ..exceptions import PropertyError
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from ..tools.database import site as site_database


class Site:
    """Base class for non-Entity site-level objects (Home, Index).

    Unlike Entity, Site objects don't have a kind, properties system,
    or cache/filter output. They provide DB access via a site key
    and lazy property instantiation.
    """

    _site_id: str | None = None
    _key: Key | None = None
    _kind: str | None = None
    _urlsafe_key: str
    _entity: Entity | Self | None = None
    if TYPE_CHECKING:
        def _get_properties(self) -> Mapping[str, Callable[..., object]]: ...

    def __init__(self, *args: object, entity: Entity | None = None, **kwargs: object) -> None:
        identifier = args[0] if args and args[0] else None
        self._db: datastore.Entity | dict[Never, Never] = (
            identifier if isinstance(identifier, datastore.Entity) else {}
        )
        self._instances: dict[str, object] = {}
        self._properties = self._get_properties()
        self._entity = entity or self

        if isinstance(identifier, str):
            self._site_id = identifier

    def __getattr__(self, name: str) -> object:
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
    def entity(self) -> Entity | Self | None:
        return self._entity

    @property
    def kind(self) -> str | None:
        return self._kind

    @property
    def key(self) -> Key | None:
        if self._db and not self._key:
            self._key = cast(datastore.Entity, self._db).key
        elif self._site_id:
            self._key = site_database.key(self._site_id)
        else:
            raise ValueError("Site identifier not set")

        return self._key

    @property
    def urlsafe_key(self) -> str:
        if not (key := self.key):
            raise RuntimeError("no key assigned")

        if getattr(self, "_urlsafe_key", None):
            return self._urlsafe_key

        self._urlsafe_key = database_get.urlsafe_key(key)
        return self._urlsafe_key

    @property
    def db(self) -> datastore.Entity:
        if self._db:
            return cast(datastore.Entity, self._db)

        if not (key := self.key):
            raise RuntimeError("no key assigned")

        self._db = site_database.get_or_create(key)

        return self._db

    def save(self) -> None:
        database_utility.save(self)
