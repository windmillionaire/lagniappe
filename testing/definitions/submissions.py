from enum import Enum

from . import submission_definitions as sd
from .submission_fields import SubmissionFields


def build_submission(schema, values):
    """Build a list of SubmissionField instances from a schema and values dict.

    Maps each SchemaField's type to the correct SubmissionField subclass
    and pairs it with the value from `values` keyed by field ID.

    Args:
        schema: Tuple of SchemaField instances (from Schemas.*.get()).
        values: Dict mapping field IDs to submission values.

    Returns:
        List of SubmissionField instances ready for set/verify.
    """
    submission = []
    for field in schema:
        field_type = field.type.upper()
        assert field_type in SubmissionFields.__members__, (
            f"Unknown field type: {field_type}"
        )
        if not values.get(field.id):
            continue
        submission.append(SubmissionFields[field_type].get(field, values[field.id]))
    return submission


class Submissions(Enum):
    default_category_form = sd.default_category_form_submission
    basic_inputs = sd.basic_inputs_submission
    partial_task_history = sd.partial_task_history_submission
    selection_types = sd.selection_types_submission
    link_external = sd.link_external_submission
    category_filter_match = sd.category_filter_match_submission
    category_filter_nonmatch = sd.category_filter_nonmatch_submission
    category_table = sd.category_table_submission
    sync_form_initial = sd.sync_form_initial_submission
    sync_form_submit_initial = sd.sync_form_submit_initial_submission
    offline_sync_form_initial = sd.offline_sync_form_initial_submission

    def get(self):
        return build_submission(self.value.schema.get(), self.value.values)
