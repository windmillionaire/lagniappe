# @testable infrastructure
# @covered-by lagniappe/core/properties/form_inputs.py::TextInput
# @covered-by lagniappe/core/properties/form_textarea.py::Textarea
class SearchMixin:
    """Adds full-text search content. Indexed for text search.

    Provides:
        search_value: Value for search indexing (default: self.value).
    """

    @property
    def search_key(self):
        return self.label

    @property
    def search_value(self):
        return self.value
