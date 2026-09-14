import json
import re

from flask import render_template, request, url_for
from flask_login import current_user

from lagniappe.core.definitions import AI, Action, Fetch, Resource
from lagniappe.core import exceptions
from lagniappe.core.entities import Entities, index
from lagniappe.core.mixins.submitter import normalize_submission_values
from lagniappe.core.tools import ai
from lagniappe.core.tools import form_drafts
from lagniappe.core.tools.ai.form_draft import prepare_generated_changes
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.web.auth import permission, require_ai_access

from . import forms
from lagniappe.web import responses, direct_uploads


# @testable false
# @covered-by lagniappe/web/routes/forms/main.py::update
# @covered-by lagniappe/web/routes/forms/main.py::create_schema
# @reason request parsing delegates domain validation to the shared draft service
def _draft_json(data, name, default=None):
    value = data.get(name, default)
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError) as error:
        raise exceptions.ValidationError(f"Invalid builder {name}. Reload the builder and retry.") from error


# @testable false
# @covered-by lagniappe/web/routes/forms/main.py::update
# @covered-by lagniappe/web/routes/forms/main.py::copy_form
# @reason complete draft and lazy upload parsing are owned by publication routes
def _builder_request(data, form):
    draft = {
        "name": data.get("name", form.name),
        "form_type": form.form_type,
        "schema": _draft_json(data, "schema"),
        "html_fields": _draft_json(data, "html_fields", {}),
        "image_manifest": _draft_json(data, "image_manifest", []),
    }
    if data.get("migration"):
        draft["migration"] = _draft_json(data, "migration")
    manifest = draft["image_manifest"]
    if not isinstance(manifest, list):
        raise exceptions.ValidationError("Invalid builder image manifest.")
    images = {}
    for item in manifest:
        if not isinstance(item, dict) or set(item) != {"id", "field_id", "input_name"}:
            raise exceptions.ValidationError("Invalid builder image ownership.")
        image_id = item["id"]
        if not isinstance(image_id, str) or not form_drafts.IMAGE_ID.fullmatch(image_id):
            raise exceptions.ValidationError("Invalid builder image identity.")
        input_name = item["input_name"]
        if image_id in images or input_name != f"draft-image-{image_id}":
            raise exceptions.ValidationError("Duplicate or mismatched builder image identity.")
        images[image_id] = {
            "field_id": item["field_id"],
            "file": lambda name=input_name: request.files.get(name) or direct_uploads.direct_upload_file(name),
        }
    return draft, images


# @testable false
# @covered-by lagniappe/web/routes/forms/main.py::update
# @covered-by lagniappe/web/routes/forms/main.py::create_schema
# @reason conflict presentation preserves local work at the existing request boundary
def _draft_conflict(error, form):
    return responses.json_response({
        "code": "stale_form_draft", "error": str(error),
        "saved_url": url_for("forms.view", key=form.urlsafe_key),
    }, status=409)


# @testable false
# @covered-by lagniappe/web/routes/forms/main.py::create_schema
# @reason generation may retain only saved owned images and current local draft tokens
def _draft_image_sources(form, html_fields):
    result = {}
    for field_id, content in html_fields.items():
        sources = []
        for name, definition in form.assets.items():
            if name.startswith(f"image_{field_id}_") and definition.get("type") == "image":
                asset = form.get_asset(name)
                if asset and asset.url:
                    sources.append((asset.url, asset.url))
        sources.extend((token, token) for token in set(re.findall(
            r"draft-image:[A-Za-z0-9_-]{1,100}", content,
        )))
        result[field_id] = sources
    return result


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_index_*
# @matrix forms : create-control index index-view permission-gates tools
@forms.route("/index", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def form_index():
    form_index = index.FormIndex()

    return responses.index("forms", form_index)


# @testable true
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_index_lists_forms_*
# @pair forms:index-view
@forms.route("/rows", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def rows():
    form_index = index.FormIndex(**request.values)
    forms = form_index.forms

    return responses.rows(forms, form_index)


# @testable true
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_builder_*
# @matrix forms : builder-edit permission-gates restriction-control
@forms.route("/<key>", methods=["GET"])
@permission(Resource.FORM, Action.VIEW, no_store=True)
def view(key, **kwargs):
    form = kwargs["entity"]

    from lagniappe.core.tools import form_changes, form_conversions
    draft = form_drafts.builder_draft(form)
    if form.db.get(form_changes.PENDING):
        result = form_changes.change_response(form, current_user)
        draft.update(result["draft"], pending_change=result["pending_change"])
    return render_template("forms/builder.html", form=form, builder_draft=draft,
                           conversion_catalog=form_conversions.conversion_catalog())


# @testable true
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_failed_preflight_recovers_after_reload
# @matrix form-migration : status recovery
@forms.route("/<key>/change", methods=["GET", "POST"])
@permission(Resource.FORM, Action.EDIT, no_store=True)
def form_change(key, **kwargs):
    from lagniappe.core.tools import form_changes
    try:
        result = (form_changes.change_response(kwargs["entity"], current_user) if request.method == "GET"
                  else form_changes.recover_change(kwargs["entity"], current_user,
                      (request.get_json(silent=True) or request.form).get("action")))
        return responses.json_response(result)
    except (exceptions.ValidationError, exceptions.MutationConflict) as error:
        return responses.error(str(error))


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
# @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
# @tests tests_e2e/003_forms/test_003f_builder_drafts.py::test_builder_publication_rejects_incompatible_payload_and_reuses_receipt
# @tests tests_e2e/003_forms/test_003f_builder_drafts.py::test_stale_save_preserves_local_draft_after_another_editor_saves
# @matrix forms : builder-add-fields builder-add-inputs builder-reload builder-save
# @matrix forms : migration-required save-receipt stale-acknowledgement persistent-error concurrent-edit
@forms.route("<key>/update", methods=["PUT"])
@permission(Resource.FORM, Action.EDIT)
def update(key, **kwargs):
    form = kwargs["entity"]
    data = request.get_json(silent=True) or request.form
    try:
        draft, images = _builder_request(data, form)
        result = form_drafts.save_form_draft(
            form, draft, data.get("baseline"), data.get("save_id"), current_user,
            images=images,
        )
    except form_drafts.FormDraftConflict as error:
        return _draft_conflict(error, form)
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    direct_uploads.cleanup_direct_uploads(request.form)
    return responses.json_response(result)


# @testable false
# @covered-by lagniappe/web/routes/forms/main.py::update
# @reason signed upload creation has the same permission as final draft publication
@forms.route("<key>/update/direct-upload", methods=["POST"])
@permission(Resource.FORM, Action.EDIT)
def update_direct(key, **kwargs):
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
# @matrix forms : create page-form task-form
@forms.route("/create", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def create():
    new_form = Entities.FORM.create(request.form)
    new_form.save()

    return responses.rows(new_form, index.FormIndex())


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
# @matrix forms : builder-copy form-type navigation schema
@forms.route("<key>/copy", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def copy_form(key, **kwargs):
    source = kwargs["entity"]
    data = request.get_json(silent=True) or request.form
    try:
        draft, images = _builder_request(data, source)
        result = form_drafts.copy_form_draft(
            source, draft, data.get("baseline"), data.get("save_id"), current_user,
            images=images,
        )
    except form_drafts.FormDraftConflict as error:
        return _draft_conflict(error, source)
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    direct_uploads.cleanup_direct_uploads(request.form)
    result["url"] = url_for("forms.view", key=result.pop("form_key"))
    return responses.json_response(result)


# @testable false
# @covered-by lagniappe/web/routes/forms/main.py::copy_form
# @reason signed upload creation has the same permission as final draft copy
@forms.route("<key>/copy/direct-upload", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def copy_direct(key, **kwargs):
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
# @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
# @matrix forms : page-form task-form
@forms.route("<key>/delete", methods=["DELETE"])
@permission(Resource.FORM, Action.DELETE)
def delete(key, **kwargs):
    form = kwargs["entity"]
    Entities.delete(form)

    return responses.ok()


# @testable true
# @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
# @tests tests_unit/test_003e_tables.py::test_table_form_mixed_column_types
# @matrix form-table : mixed-columns row-submission
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
    try:
        entity.validate_browser_submission_references(
            {table_id: {"rows": [values]}},
            actor=current_user,
            normalized=True,
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    row_submission = field.validate_row_submission(values)
    return responses.json_response({"row": row_submission})


# @testable true
# @tests tests_unit/test_003e_tables.py::test_table_form_single_row
# @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_expands_table_submission_cell
# @matrix form-table table-controls : form-table-column table-cell-expand
# @matrix form-table : form-submission row-submission
@forms.route("<key>/expand-table-cell/<table_id>", methods=["GET"])
@permission(requested=Action.VIEW)
def expand_table_cell(key, table_id, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    field = entity.properties.submission.fields.get(table_id)
    if field is None:
        return responses.error("The original table definition is unavailable.")
    field.value = entity.submission.get(table_id)
    field.kind = (
        entity.kind if not isinstance(entity, Entities.TASK_HISTORY) else "form"
    )

    return responses.expanded_table_cell(field)


# @testable true
# @scaffolding testing/resources/form.py::Builder.restrict_to_owner
# @scaffolding testing/resources/form.py::Builder.restrict_to_group
# @matrix forms : access-restrictions group-restricted owner-restricted
@forms.route("<key>/restrictions", methods=["PUT"])
@permission(Resource.FORM, Action.EDIT)
def restrictions(key, **kwargs):
    form = kwargs["entity"]

    admin_only = request.form.get("admin") in {"on", "true"}
    keys = [] if admin_only else request.form.getlist("group-key")
    try:
        resolver = SubmittedReferenceResolver(current_user, *keys)
        groups = [resolver.one(key, expected=Entities.USER_GROUP, action=Action.VIEW, required=True)
                  for key in keys]
        form.groups = groups
        form.properties.restricted_to.materialize(admin_only=admin_only)
        form.save()
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    return responses.ok()


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_generate_form_schema_live_saved_state
# @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_schema_generation_requires_edit_access_to_submitted_form
# @matrix ai forms : generate-schema live-ai reload saved-state submitted-reference
@forms.route("/create-schema", methods=["POST"])
@permission(Resource.FORMS, Action.EDIT)
def create_schema():
    description = request.form.get("description", "")
    form_key = request.form.get("form-key")
    try:
        form = SubmittedReferenceResolver(current_user, form_key).one(
            form_key,
            expected=Entities.FORM,
            action=Action.EDIT,
            required=True,
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    require_ai_access(AI.CREATE)

    try:
        schema = form_drafts.validate_draft_schema(_draft_json(request.form, "schema"), form.form_type)
        html_fields = _draft_json(request.form, "html_fields", {})
        if not isinstance(html_fields, dict) or any(
            not isinstance(value, str) for value in html_fields.values()
        ):
            raise exceptions.ValidationError("Invalid builder HTML draft.")
        html_ids = {field["id"] for field in schema if field["type"] == "html"}
        if set(html_fields) != html_ids:
            raise exceptions.ValidationError("Generation needs the complete current HTML draft.")
        baseline = request.form.get("baseline")
        if baseline != form_drafts.builder_draft(form)["baseline"]:
            raise form_drafts.FormDraftConflict("The saved Form changed. Your draft is preserved; reconcile it before generating.")
        request_id = request.form.get("request_id")
        revision = int(request.form.get("draft_revision", "-1"))
        if not isinstance(request_id, str) or not form_drafts.IMAGE_ID.fullmatch(request_id) or revision < 0:
            raise exceptions.ValidationError("Generation needs a valid draft request identity.")
        draft = {"schema": schema, "html_fields": html_fields}
        prompt = ai.form_generation_prompt(form.form_type, description=description, draft=draft)
        if request.form.get("explain"):
            return responses.explain(prompt)
        sources = _draft_image_sources(form, html_fields)
        result = ai.generate_schema(prompt, validator=lambda value: prepare_generated_changes(
            value, draft, form_type=form.form_type, image_sources=sources,
        ))
        current = Entities.fetch_one(form.key, request=Fetch.direct())
        if current is None or not current.allowed(Action.EDIT, user=current_user):
            raise exceptions.ValidationError("This Form is no longer editable.")
        if form_drafts.builder_draft(current)["baseline"] != baseline:
            raise form_drafts.FormDraftConflict("The saved Form changed during generation. Your draft is preserved.")
    except form_drafts.FormDraftConflict as error:
        return _draft_conflict(error, form)
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    except Exception as e:
        return responses.error(str(e), exception=e)
    return responses.json_response({**result, "request_id": request_id, "draft_revision": revision})


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_schema
# @pair form-schema:property
@forms.route("<key>/schema", methods=["GET"])
@permission(Resource.FORM, Action.VIEW)
def schema(key, **kwargs):
    form = kwargs["entity"]
    return responses.json_response({"schema": form.schema})
