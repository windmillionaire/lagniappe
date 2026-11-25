"""Domain errors for private messaging operations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tools.messaging.views import ConversationProjection
    from google.cloud.datastore import Entity as DatastoreEntity


class MessageConflict(RuntimeError):
    pass


class MessageRevisionConflict(RuntimeError):
    def __init__(self, conversation: DatastoreEntity) -> None:
        super().__init__("Conversation changed; refresh and try again.")
        # The service serializes the conflict before passing it to a web client.
        self.conversation: DatastoreEntity | ConversationProjection = conversation
