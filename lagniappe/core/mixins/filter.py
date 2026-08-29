# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Name
# @covered-by lagniappe/core/properties/common_entity.py::Description.filter_value
# @covered-by lagniappe/core/properties/common_entity.py::Hash.filter_key
# @covered-by lagniappe/core/properties/form_inputs.py::TextInput
# @covered-by lagniappe/core/properties/task_dates.py::DueDate
class FilterMixin:
    """Adds filter indexing. Collected by Entity.to_filter_index().

    The filter cache stores {filter_key: filter_value} per entity.
    FilterExpression queries the cache using JSONPath on filter_key.
    filter_key and filter_value must be consistent between the index,
    query conditions, and frontend form inputs.

    Provides:
        filter_key (str): Cache index key (default: self.id).
        filter_value: Value stored and compared (default: self.value).
        filter_label (str): Display label (default: self.label).
        filter_kind (str): Kind for UI theming (default: self._kind).
        field_type (FieldType): Data type for query building.
        field_options: Available comparators for this field type.
        is_entity_valued (bool): Whether values are entity hashes.

    Override:
        _field_type (FieldType): Required. Data type for the filter cache.
        _field_options (FilterOptions): Comparator options for the UI.
        _filter_key (str): Custom cache key (default: self.id).
        _is_entity_valued (bool): True if filter values are entity hashes.
        _default (str): Default comparator name.
    """

    _filter_kind = None

    @property
    def filter_key(self):
        return getattr(self, "_filter_key", self.id)

    @filter_key.setter
    def filter_key(self, value):
        self._filter_key = value

    @property
    def filter_value(self):
        return self.value

    @property
    def filter_label(self):
        return self.label

    @property
    def filter_kind(self):
        return self._kind

    @filter_kind.setter
    def filter_kind(self, value):
        self._filter_kind = value

    @property
    def default(self):
        return getattr(self, "_default", None)

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_column_and_filter_contract_errors_are_explicit
    # @matrix property : filter validation
    @property
    def field_type(self):
        if not hasattr(self, "_field_type"):
            raise NotImplementedError(f"{self.__class__.__name__} requires _field_type")
        return self._field_type

    @field_type.setter
    def field_type(self, value):
        self._field_type = value

    @property
    def field_text(self):
        return getattr(self, "_field_text", None)

    @property
    def field_options(self):
        return getattr(self, "_field_options", None)

    @property
    def index(self):
        return getattr(self, "_index", None)

    @property
    def placeholder(self):
        return getattr(self, "_placeholder", None)

    @property
    def choices(self):
        return getattr(self, "_choices", None)

    @choices.setter
    def choices(self, value):
        self._choices = value

    def filter_details(self, condition):
        """Build display details dict for a filter condition.

        Subclasses override to add type-specific keys (or, entity, etc.).
        Returns {field, type, text, status, value}.
        """
        comparator = condition.comparator.name
        value = condition.value

        details = {
            "field": self,
            "type": self.field_type.value,
            "text": self.field_options[comparator].value
            if hasattr(self.field_options, comparator)
            else None,
            "status": comparator,
            "value": value,
        }

        if self.entity.kind == "form":
            # details["form"] = self.entity.name
            details["kind"] = "form"
        elif self.entity.kind == "category":
            details["kind"] = "page"
        elif self.entity.kind == "project":
            details["kind"] = "task"

        return details
