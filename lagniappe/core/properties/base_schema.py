from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, cast

from .base_property import Property

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..exceptions import ValidationError

type FieldDefinition = dict[str, object]
type SchemaSource = Mapping[str, object] | Iterable[tuple[str, object]]



# @testable infrastructure
# @covered-by lagniappe/core/properties/schema.py::Schema.fields
# @covered-by lagniappe/core/properties/form_inputs.py::TextInput
# @covered-by lagniappe/core/properties/form_table.py::Table
class SchemaProperty[Value = object](dict[str, object], Property[Value, "Entity"]):
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

    def __init__(
        self, *args: SchemaSource, entity: Entity | None = None, **kwargs: object
    ) -> None:
        dict.__init__(self, *args)
        self._id = cast(str | None, self.get("id"))
        self._label = cast(str | None, self.get("title"))
        Property.__init__(cast(Property, self), entity=entity, **kwargs)
        self.warnings: list[str] = []
        self.errors: list[str | ValidationError] = []

    @property
    def visibility(self) -> list[FieldDefinition] | FieldDefinition:
        return cast(list[FieldDefinition] | FieldDefinition, self.get("visibility", {}))

    @property
    def required(self) -> bool:
        return cast(bool, self.get("required", False))

    @property
    def multiple(self) -> bool:
        return cast(bool, getattr(self, "_multiple", self.get("multiple", False)))

    @multiple.setter
    def multiple(self, value: bool) -> None:
        self._multiple = value

    @property
    def placeholder(self) -> str | None:
        return cast(str | None, self.get("placeholder", None))

    @property
    def schema(self) -> FieldDefinition:
        return dict(self)

    def reset(self) -> None:
        self.unset()
        self.warnings = []
        self.errors = []

    def validate_import(self, value: object) -> None:
        self.value = cast("Value | None", value)

    def validate_ai(self, value: object) -> None:
        self.value = cast("Value | None", value)

    def validate_submission(self, value: object) -> None:
        self.value = cast("Value | None", value)
