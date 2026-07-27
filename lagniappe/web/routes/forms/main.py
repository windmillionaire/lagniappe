from copy import deepcopy

from flask import render_template, request, url_for
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities, index
from lagniappe.core.mixins.submitter import normalize_submission_values
from lagniappe.core.tools import ai
from lagniappe.web.auth import abort_ai_restricted_action, permission

from . import forms
from lagniappe.web import responses


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_index_*
# @features forms
# @dimensions index tools permission-gates index-view create-control
@forms.route("/index", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def form_index():
    form_index = index.FormIndex()

    return responses.index("forms", form_index)


# @testable true
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_index_lists_forms_*
# @features forms
# @dimensions index-view
@forms.route("/rows", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def rows():
    form_index = index.FormIndex(**request.values)
    forms = form_index.forms

    return responses.rows(forms, form_index)


# @testable true
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_builder_*
# @features forms
# @dimensions builder-edit permission-gates restriction-control
@forms.route("/<key>", methods=["GET"])
@permission(Resource.FORM, Action.VIEW)
def view(key, **kwargs):
    form = kwargs["entity"]

    return render_template("forms/builder.html", form=form)


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
# @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
# @features forms
# @dimensions builder-add-inputs builder-add-fields builder-save builder-reload
@forms.route("<key>/update", methods=["PUT"])
@permission(Resource.FORM, Action.EDIT)
def update(key, **kwargs):
    form = kwargs["entity"]
    form.update(request.form)
    form.save()

    return responses.ok()


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
# @features forms
# @dimensions create page-form task-form
@forms.route("/create", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def create():
    new_form = Entities.FORM.create(request.form)
    new_form.save()

    return responses.rows(new_form, index.FormIndex())


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
# @features forms
# @dimensions builder-copy schema form-type navigation
@forms.route("<key>/copy", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def copy_form(key, **kwargs):
    source = kwargs["entity"]
    payload = request.get_json(silent=True) or {}
    source_name = str(payload.get("name") or source.name).strip() or source.name
    schema = payload.get("schema", source.schema)

    copied = Entities.FORM.create(
        {
            "name": f"Copy of {source_name}",
            "form-type": source.form_type,
            "schema": deepcopy(schema),
        }
    )
    copied.save()

    return responses.json_response(
        {"url": url_for("forms.view", key=copied.urlsafe_key)}
    )


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
@forms.route("<key>/delete", methods=["DELETE"])
@permission(Resource.FORM, Action.DELETE)
def delete(key, **kwargs):
    form = kwargs["entity"]
    Entities.delete(form)

    return responses.ok()


# @testable true
# @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
# @tests tests_unit/test_003e_tables.py::test_table_form_mixed_column_types
@forms.route("<key>/validate-row/<table_id>", methods=["GET"])
@permission(requested=Action.EDIT)
def validate_row(key, table_id, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    field = entity.properties.submission.fields.get(table_id)
    field.user = current_user

    values = normalize_submission_values(request.values, field.fields)
    row_submission = field.validate_row_submission(values)
    return responses.json_response({"row": row_submission})


# @testable true
# @tests tests_unit/test_003e_tables.py::test_table_form_single_row
# @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_expands_table_submission_cell
# @features form-table table-controls
# @dimensions table-cell-expand form-table-column
@forms.route("<key>/expand-table-cell/<table_id>", methods=["GET"])
@permission(requested=Action.VIEW)
def expand_table_cell(key, table_id, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    field = entity.form.fields.get(table_id)
    field.value = entity.submission.get(table_id)
    field.kind = (
        entity.kind if not isinstance(entity, Entities.TASK_HISTORY) else "form"
    )

    return responses.expanded_table_cell(field)


# @testable true
# @scaffolding testing/resources/form.py::Builder.restrict_to_owner
# @scaffolding testing/resources/form.py::Builder.restrict_to_group
# @features forms
# @dimensions access-restrictions owner-restricted group-restricted
@forms.route("<key>/restrictions", methods=["PUT"])
@permission(Resource.FORM, Action.EDIT)
def restrictions(key, **kwargs):
    form = kwargs["entity"]

    action = request.form.get("action")
    group_key = request.form.get("group-key")
    group = (
        Entities.fetch_one(group_key, request=Fetch.direct()) if group_key else None
    )
    specific = request.form.get("specific")
    added = False

    if group and action == "add":
        added = form.properties.groups.add(group)
    elif group and action == "remove":
        form.properties.groups.remove(group)
    elif specific and action == "add":
        form.properties.restricted_to.add(specific)
    elif specific and action == "remove":
        form.properties.restricted_to.remove(specific)

    form.save()

    if not group and not added:
        return responses.ok()

    return responses.new_form_restriction(group)


# @testable true
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_with_form
# @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_filters_invalid_top_level
# @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_table_filters_bad_columns
# @tests tests_e2e/003_forms/test_003a_forms.py::test_generate_form_schema_live_saved_state
# @features forms ai
# @dimensions generate-schema live-ai saved-state reload
@forms.route("/create-schema", methods=["POST"])
@permission(Resource.FORMS, Action.EDIT)
def create_schema():
    abort_ai_restricted_action()

    description = request.form.get("description", "")
    form_type = request.form.get("form-type", "task")
    form = Entities.FORM(request.form.get("form-key"))

    prompt = ai.form_generation_prompt(form_type, description=description)

    if request.form.get("explain"):
        return responses.explain(prompt)

    try:
        result = ai.generate_schema(prompt)
        form.properties.schema.validate_ai(result)
    except Exception as e:
        return responses.error(str(e), exception=e)

    form.save()

    return responses.json_response({"schema": form.schema})


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_schema
@forms.route("<key>/schema", methods=["GET"])
@permission(Resource.FORM, Action.VIEW)
def schema(key, **kwargs):
    form = kwargs["entity"]
    return responses.json_response({"schema": form.schema})
