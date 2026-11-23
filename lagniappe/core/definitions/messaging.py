"""Domain errors for private messaging operations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud.datastore import Entity as DatastoreEntity


class MessageConflict(RuntimeError):
    pass


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:read-race
class MessageRevisionConflict(RuntimeError):
    def __init__(self, conversation: DatastoreEntity) -> None:
        super().__init__("Conversation changed; refresh and try again.")
        # The service serializes the conflict before passing it to a web client.
        self.conversation: DatastoreEntity | dict[str, object] = conversation
