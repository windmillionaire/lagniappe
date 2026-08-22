"""Domain errors for private messaging operations."""


class MessageConflict(RuntimeError):
    pass


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:read-race
class MessageRevisionConflict(RuntimeError):
    def __init__(self, conversation):
        super().__init__("Conversation changed; refresh and try again.")
        self.conversation = conversation
