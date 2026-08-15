"""Internal idempotency marker for an accepted document mention."""

from .entity import Entity


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pairs mentions:idempotency mentions:entity-contract
class MentionMarker(Entity):
    entity_kind = "mention_marker"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair mentions:index-exclusion
    @property
    def exclude_from_index(self):
        return frozenset({"occurrence_id", "display_name"})
