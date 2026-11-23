from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from werkzeug.local import LocalProxy

    from ..entities.user import User


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Name.ai_key
# @covered-by lagniappe/core/properties/form_inputs.py::TextInput
# @covered-by lagniappe/core/properties/form_textarea.py::Textarea
class AIMixin:
    """Adds AI context output. Collected by Entity.to_ai().

    Provides:
        ai_value: Value for AI consumption (default: self.value).
        ai_key (str): Key in the AI context dict (default: self.label).
    """

    if TYPE_CHECKING:
        @property
        def value(self) -> object: ...
        @property
        def label(self) -> str: ...
        @property
        def is_set(self) -> bool: ...
        @property
        def user(self) -> User | LocalProxy[User | None] | None: ...
        @user.setter
        def user(self, value: User | LocalProxy[User | None] | None) -> None: ...

    @property
    def ai_value(self) -> object:
        val = self.value
        return None if val is None else val

    @property
    def ai_key(self) -> str:
        return self.label
