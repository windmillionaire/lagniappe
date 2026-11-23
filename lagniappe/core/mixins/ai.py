from .field_host import FieldHost

# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Name.ai_key
# @covered-by lagniappe/core/properties/form_inputs.py::TextInput
# @covered-by lagniappe/core/properties/form_textarea.py::Textarea
class AIMixin(FieldHost):
    """Adds AI context output. Collected by Entity.to_ai().

    Provides:
        ai_value: Value for AI consumption (default: self.value).
        ai_key (str): Key in the AI context dict (default: self.label).
    """

    @property
    def ai_value(self) -> object:
        val = self.value
        return None if val is None else val

    @property
    def ai_key(self) -> str | None:
        return self.label
