from dataclasses import dataclass

from .schemas import Schemas
from .schema_fields import SchemaFields


@dataclass
class FormDefinition:
    name: str
    form_type: str
    schema: tuple = None


basic_page_form = FormDefinition(
    name="Basic Page Form",
    form_type="page",
    schema=Schemas.basic_page_form.get(),
)

create_page_form = FormDefinition(
    name="Create Page Form",
    form_type="page",
    schema=Schemas.basic_page_form.get(),
)


basic_task_form = FormDefinition(
    name="Basic Task Form",
    form_type="task",
)

alternate_task_form = FormDefinition(
    name="Alternate Task Form",
    form_type="task",
)

add_inputs = FormDefinition(
    name="Add Inputs",
    form_type="page",
)

add_fields = FormDefinition(
    name="Add Fields",
    form_type="page",
)

builder_delete_components = FormDefinition(
    name="Builder Delete Components",
    form_type="page",
    schema=Schemas.add_fields.get(),
)

builder_select_options = FormDefinition(
    name="Builder Select Options",
    form_type="page",
)

builder_field_visibility = FormDefinition(
    name="Builder Field Visibility",
    form_type="page",
)

builder_select_visibility = FormDefinition(
    name="Builder Select Visibility",
    form_type="page",
)

builder_table_columns = FormDefinition(
    name="Builder Table Columns",
    form_type="page",
)

builder_status_messages = FormDefinition(
    name="Builder Status Messages",
    form_type="task",
)

builder_signature_unique = FormDefinition(
    name="Builder Signature Unique",
    form_type="task",
)

builder_html_field = FormDefinition(
    name="Builder HTML Field",
    form_type="task",
)

builder_drag_component = FormDefinition(
    name="Builder Drag Component",
    form_type="page",
)

preview_panel_form = FormDefinition(
    name="Preview Panel Form",
    form_type="page",
    schema=Schemas.add_fields.get(),
)

page_submission_test = FormDefinition(
    name="Page Submission Test",
    form_type="page",
    schema=Schemas.page_submission_test.get(),
)

basic_inputs_form = FormDefinition(
    name="Basic Inputs Form",
    form_type="page",
    schema=Schemas.basic_inputs.get(),
)

selection_types_form = FormDefinition(
    name="Selection Types Form",
    form_type="page",
    schema=Schemas.selection_types.get(),
)

link_external_form = FormDefinition(
    name="External Link Form",
    form_type="page",
    schema=Schemas.link_external_only.get(),
)

owner_restricted_form = FormDefinition(
    name="Owner Restricted Form",
    form_type="page",
    schema=Schemas.basic_page_form.get(),
)

group_restricted_form = FormDefinition(
    name="Group Restricted Form",
    form_type="page",
    schema=Schemas.basic_page_form.get(),
)

index_restricted_form = FormDefinition(
    name="Index Restricted Form",
    form_type="page",
    schema=Schemas.basic_page_form.get(),
)

task_history_form = FormDefinition(
    name="Task History Form",
    form_type="task",
    schema=Schemas.basic_inputs.get(),
)

task_signature_form = FormDefinition(
    name="Task Signature Form",
    form_type="task",
    schema=(
        SchemaFields.SIGNATURE.get(
            _id="task-signature-field",
            title="Approval Signature",
        ),
    ),
)

task_status_form = FormDefinition(
    name="Task Status Form",
    form_type="task",
    schema=Schemas.task_status.get(),
)

task_history_table_form = FormDefinition(
    name="Task History Table Form",
    form_type="task",
    schema=Schemas.submission_headline_table.get(),
)

project_filter_task_form = FormDefinition(
    name="Project Filter Task Form",
    form_type="task",
    schema=Schemas.project_filter_task.get(),
)

category_filter_page_form = FormDefinition(
    name="Category Filter Page Form",
    form_type="page",
    schema=Schemas.category_filter_page.get(),
)

category_table_page_form = FormDefinition(
    name="Category Table Page Form",
    form_type="page",
    schema=Schemas.submission_headline_table.get(),
)

sync_page_form = FormDefinition(
    name="Sync Page Form",
    form_type="page",
    schema=Schemas.sync_text.get(),
)
