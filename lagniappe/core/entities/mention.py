"""Internal idempotency marker for an accepted document mention."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import property_types
    from datetime import datetime
    from google.cloud.datastore import Key
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import EntityProperties
    from typing import Self


from .entity import Entity
from ..properties import mention
from lagniappe.core.tools.database import utility as database_utility


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @matrix mentions : entity-contract idempotency
class MentionMarker(Entity):
    if TYPE_CHECKING:
        document: Key | None
        actor: Key | None
        recipient: Key | None
        occurrence_id: str | None
        display_name: str | None

        @property
        def properties(self) -> property_types.MentionMarkerProperties: ...

    entity_kind = "mention_marker"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair mentions:index-exclusion
    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"occurrence_id", "display_name"})

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "document": mention.Document,
                "actor": mention.Actor,
                "recipient": mention.Recipient,
                "occurrence_id": mention.OccurrenceID,
                "display_name": mention.DisplayName,
            }
        )
        return properties

    @classmethod
    def create(
        cls,
        actor: models.User,
        recipient: models.User,
        document: Entity,
        occurrence_id: str,
        display_name: str,
        *,
        key: Key,
        now: datetime,
    ) -> Self:
        row = database_utility.create_entity(key)
        marker = cls(row)
        row.exclude_from_indexes = set(marker.exclude_from_index)
        marker.db.update(
            {
                "type": cls.entity_kind,
                "kind": cls.entity_kind,
                "document": document.key,
                "actor": actor.key,
                "recipient": recipient.key,
                "occurrence_id": occurrence_id,
                "display_name": display_name,
                "created": now,
                "modified": now,
            }
        )
        return marker
