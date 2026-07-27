from enum import Enum
from copy import deepcopy

from . import schema_definitions as sd


class Schemas(Enum):
    # Python-authored (builder tests)
    basic_page_form = sd.category_with_form_schema
    add_inputs = sd.add_inputs_schema
    add_fields = sd.add_fields_schema
    page_submission_test = sd.submission_tests
    project_filter_task = sd.project_filter_task_schema
    category_filter_page = sd.category_filter_page_schema
    sync_text = sd.sync_text_schema

    # JSON-backed (filter/submission/integration tests)
    basic_inputs = sd.load_schema("basic_inputs")
    selection_types = sd.load_schema("selection_types")
    complex_types = sd.load_schema("complex_types")
    date_time_inputs = sd.load_schema("date_time_inputs")
    visibility_test = sd.load_schema("visibility_test")
    table_scalar_columns = sd.load_schema("table_scalar_columns")
    submission_headline_table = sd.load_schema("submission_headline_table")
    link_external_only = sd.load_schema("link_external_only")
    task_status = sd.load_schema("task_status")

    def get(self):
        return deepcopy(self.value)

    def to_dict(self):
        return [field.to_dict() for field in self.get()]
