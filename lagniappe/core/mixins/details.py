from typing import TYPE_CHECKING


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Name
# @covered-by lagniappe/core/properties/common_entity.py::Kind.details_value
class DetailsMixin:
    """Adds API detail output. Collected by Entity.details.

    Provides:
        details_value: Value for the details dict (default: self.value).
        details_key (str): Key in the details dict (default: self.id).
    """

    if TYPE_CHECKING:
        @property
        def value(self) -> object: ...
        @property
        def id(self) -> str: ...

    @property
    def details_value(self) -> object:
        return self.value

    @property
    def details_key(self) -> str:
        return self.id
