from .base_property import Property


# @testable infrastructure
# @covered-by lagniappe/core/properties/schema.py::Schema.fields
# @covered-by lagniappe/core/properties/form_inputs.py::TextInput
# @covered-by lagniappe/core/properties/form_table.py::Table
class SchemaProperty(dict, Property):
    """Base class for form fields defined by a user-created schema.

    Initialized from a schema definition dict (the dict itself is the
    field definition). Provides validation entry points for form
    submissions, AI submissions, and CSV imports.

    Get:
        db_value (any): The validated value for storage in entity.db.
        form_value (any): The value formatted for form display (defaults to db_value).
        visibility (list[dict]): Conditional visibility rules from the schema
            (each dict is one condition). A legacy single dict is still accepted.
        required (bool): Whether the field is required.
    """

    def __init__(self, *args, entity=None, **kwargs):
        dict.__init__(self, *args)
        self._id = self.get("id", None)
        self._label = self.get("title", None)
        Property.__init__(self, entity=entity, **kwargs)
        self.warnings = []
        self.errors = []

    @property
    def visibility(self):
        return self.get("visibility", {})

    @property
    def required(self):
        return self.get("required", False)

    @property
    def multiple(self):
        return getattr(self, "_multiple", self.get("multiple", False))

    @multiple.setter
    def multiple(self, value):
        self._multiple = value

    @property
    def placeholder(self):
        return self.get("placeholder", None)

    @property
    def schema(self):
        return dict(self)

    def reset(self):
        self.unset()
        self.warnings = []
        self.errors = []

    def validate_import(self, value):
        self.value = value

    def validate_ai(self, value):
        self.value = value

    def validate_submission(self, value):
        self.value = value
