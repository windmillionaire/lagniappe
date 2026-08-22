"""Internal idempotency marker for an accepted document mention."""

from .entity import Entity
from ..properties import mention
from ..tools import database


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pairs mentions:idempotency mentions:entity-contract
class MentionMarker(Entity):
    entity_kind = "mention_marker"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair mentions:index-exclusion
    @property
    def exclude_from_index(self):
        return frozenset({"occurrence_id", "display_name"})

    def _get_properties(self):
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
        actor,
        recipient,
        document,
        occurrence_id,
        display_name,
        *,
        key,
        now,
    ):
        marker = cls(database.create_entity(key))
        marker.db.exclude_from_indexes = marker.exclude_from_index
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
