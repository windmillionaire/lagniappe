from ..exceptions import PropertyError


# @testable true
# @tests tests_unit/test_013f_process_property_complete_error.py::test_process_property_contract_errors_are_explicit
# @matrix process-property : initialization validation
class ProcessProperty:
    """Property backed by a JSON process section in entity.db.

    Stores multi-step workflow state (ingress stages, file options, etc.).
    Subclasses must set ``process_id``, ``section_id``, and ``attributes``
    (a tuple of attribute names accessible via __getattr__/__setattr__).

    Get:
        section (dict): The raw dict for this section within the process.
        error (str | None): Error message if the process step failed.
        complete (bool): Whether this step has completed successfully.
    """

    attributes = tuple()

    def __init__(self, *args, entity=None, **kwargs):
        process_id = getattr(type(self), "process_id", None)
        section_id = getattr(type(self), "section_id", None)
        attributes = getattr(type(self), "attributes", None)

        if not process_id:
            raise NotImplementedError(f"{type(self).__name__} requires process_id")
        if not section_id:
            raise NotImplementedError(f"{type(self).__name__} requires section_id")
        if not isinstance(attributes, tuple):
            raise TypeError("attributes must be a tuple")

        self.entity = entity
        self.id = section_id
        self.root_process = self.entity.get_process(process_id)
        self._value = self.root_process.setdefault(section_id, {})

    @property
    def section(self):
        return self._value

    @section.setter
    def section(self, value):
        self._value.clear()
        if isinstance(value, dict):
            self._value.update({k.replace("_", "-"): v for k, v in value.items()})

    def update(self, form_data):
        self.section = {**form_data}

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_stage_clear
    # @matrix ingress : clear process-state
    def clear(self):
        self.section = None

    # @testable true
    # @tests tests_unit/test_013f_process_property_complete_error.py::test_process_property_error_clears_complete
    # @matrix process-property : complete-state error
    @property
    def error(self):
        return self.section.get("error")

    @error.setter
    def error(self, value):
        self.section["error"] = value
        self.section.pop("complete", None)

    # @testable true
    # @tests tests_unit/test_013f_process_property_complete_error.py::test_process_property_complete_clears_error
    # @matrix process-property : complete error-state
    @property
    def complete(self):
        return self.section.get("complete")

    @complete.setter
    def complete(self, value):
        self.section["complete"] = value
        self.section.pop("error", None)

    def __getattr__(self, attr):
        if attr.replace("-", "_") in self.attributes:
            return self._value.get(attr.replace("_", "-"))

        raise PropertyError(
            f"'{type(self).__name__}' has no attribute '{attr}'",
            entity=self.entity,
        )

    def __setattr__(self, attr, value):
        if attr not in self.attributes:
            super().__setattr__(attr, value)
        else:
            section_name = attr.replace("_", "-")
            if value is not None:
                self._value[section_name] = value
            elif section_name in self._value:
                self._value.pop(section_name)
