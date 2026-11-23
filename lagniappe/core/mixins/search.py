from collections.abc import Sequence

from .field_host import FieldHost

class SearchMixin(FieldHost):
    """Adds full-text search content. Indexed for text search.

    Provides:
        search_value: Value for search indexing (default: self.value).
    """

    @property
    def search_key(self) -> str | Sequence[str | None] | None:
        return self.label

    @property
    def search_value(self) -> object:
        return self.value
