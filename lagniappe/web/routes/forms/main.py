from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.tools.ai.form_draft import FormDraft
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

import json
import re

from flask import redirect, render_template, request, url_for
from flask_login import current_user

from lagniappe.core.definitions import AI, Action, Fetch, Resource
from lagniappe.core import exceptions
from lagniappe.core.properties.form_table import Table
from lagniappe.core.entities import Entities, index
from lagniappe.core.mixins.submitter import normalize_submission_values
from lagniappe.core.tools.ai import schema as ai_schema
from lagniappe.core.tools.forms import drafts as form_drafts
from lagniappe.core.tools.ai.form_draft import prepare_generated_changes
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.web.auth import authenticated_user, load_route_entity, permission, require_ai_access

from . import forms
from lagniappe.web.pagination import pagination_options
from lagniappe.web import responses, direct_uploads


def _draft_json(data, name, default=None):
    value = data.get(name, default)
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError) as error:
        raise exceptions.ValidationError(f"Invalid builder {name}. Reload the builder and retry.") from error


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


def _draft_conflict(error, form):
    return responses.json_response({
        "code": "stale_form_draft", "error": str(error),
        "saved_url": url_for("forms.view", key=form.urlsafe_key),
    }, status=409)


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


@forms.route("", methods=["GET"])
@forms.route("/", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def forms_root() -> ResponseReturnValue:
    return redirect(url_for("forms.form_index"))


@forms.route("/index", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def form_index() -> ResponseReturnValue:
    form_index = index.FormIndex()

    return responses.index("forms", form_index)


@forms.route("/rows", methods=["GET"])
@permission(Resource.FORMS, Action.VIEW)
def rows() -> ResponseReturnValue:
    form_index = index.FormIndex(**pagination_options())
    forms = form_index.forms

    return responses.rows(forms, form_index)


@forms.route("/<key>", methods=["GET"])
@permission(Resource.FORM, Action.VIEW, no_store=True)
def view(key: str, **kwargs: Unpack[EntityContext[models.Form]]) -> ResponseReturnValue:
    form = kwargs["entity"]

    from lagniappe.core.tools.forms import changes as form_changes, conversions as form_conversions
    draft = dict(form_drafts.builder_draft(form))
    if form.db.get(form_changes.PENDING):
        result = form_changes.change_response(form, authenticated_user())
        draft.update(result["draft"])
        if "pending_change" in result:
            draft["pending_change"] = result["pending_change"]
    return render_template("forms/builder.html", form=form, builder_draft=draft,
                           conversion_catalog=form_conversions.conversion_catalog())


@forms.route("/<key>/change", methods=["GET", "POST"])
@permission(Resource.FORM, Action.EDIT, no_store=True)
def form_change(
    key: str, **kwargs: Unpack[EntityContext[models.Form]]
) -> ResponseReturnValue:
    from lagniappe.core.tools.forms import changes as form_changes
    try:
        result = (form_changes.change_response(kwargs["entity"], authenticated_user()) if request.method == "GET"
                  else form_changes.recover_change(kwargs["entity"], authenticated_user(),
                      (request.get_json(silent=True) or request.form).get("action") or ""))
        return responses.json_response(result)
    except (exceptions.ValidationError, exceptions.MutationConflict) as error:
        return responses.error(str(error))


@forms.route("<key>/update", methods=["PUT"])
@permission(Resource.FORM, Action.EDIT)
def update(
    key: str, **kwargs: Unpack[EntityContext[models.Form]]
) -> ResponseReturnValue:
    form = kwargs["entity"]
    data = request.get_json(silent=True) or request.form
    try:
        draft, images = _builder_request(data, form)
        result = form_drafts.save_form_draft(
            form, draft, data.get("baseline") or "", data.get("save_id") or "", authenticated_user(),
            images=images,
        )
    except form_drafts.FormDraftConflict as error:
        return _draft_conflict(error, form)
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    direct_uploads.cleanup_direct_uploads(request.form)
    return responses.json_response(result)


@forms.route("<key>/update/direct-upload", methods=["POST"])
@permission(Resource.FORM, Action.EDIT)
def update_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    return direct_uploads.direct_upload_response()


@forms.route("/create", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def create() -> ResponseReturnValue:
    name = (request.form.get("name") or "").strip()
    if not name:
        return responses.error("Name this form before creating it.")
    form_type = (request.form.get("form-type") or "").strip()
    if form_type not in {"page", "task"}:
        return responses.error("Select whether this form is for pages or tasks.")
    create_data: dict[str, object] = {
        **request.form.to_dict(),
        "name": name,
        "form-type": form_type,
    }
    try:
        new_form = Entities.FORM.create(create_data)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    new_form.save()

    return responses.rows(new_form, index.FormIndex())


@forms.route("<key>/copy", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def copy_form(
    key: str, **kwargs: Unpack[EntityContext[models.Form]]
) -> ResponseReturnValue:
    source = kwargs["entity"]
    data = request.get_json(silent=True) or request.form
    try:
        draft, images = _builder_request(data, source)
        result = form_drafts.copy_form_draft(
            source, draft, data.get("baseline") or "", data.get("save_id") or "", authenticated_user(),
            images=images,
        )
    except form_drafts.FormDraftConflict as error:
        return _draft_conflict(error, source)
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    direct_uploads.cleanup_direct_uploads(request.form)
    payload = dict(result)
    payload["url"] = url_for("forms.view", key=payload.pop("form_key"))
    return responses.json_response(payload)


@forms.route("<key>/copy/direct-upload", methods=["POST"])
@permission(Resource.FORM, Action.CREATE)
def copy_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    return direct_uploads.direct_upload_response()


@forms.route("<key>/delete", methods=["DELETE"])
@permission(Resource.FORM, Action.DELETE)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.Form]]
) -> ResponseReturnValue:
    form = kwargs["entity"]
    Entities.delete(form)

    return responses.ok()


@forms.route("<key>/validate-row/<table_id>", methods=["GET"])
@permission(requested=Action.EDIT)
def validate_row(
    key: str, table_id: str, **kwargs: Unpack[EntityContext[models.Page | models.Task]]
) -> ResponseReturnValue:
    entity = load_route_entity(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    field = entity.properties.submission.fields.get(table_id)
    if not isinstance(field, Table):
        return responses.error("The original table definition is unavailable.")
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
    row_submission = field.validate_row_submission(dict(values))
    return responses.json_response({"row": row_submission})


@forms.route("<key>/expand-table-cell/<table_id>", methods=["GET"])
@permission(requested=Action.VIEW)
def expand_table_cell(
    key: str,
    table_id: str,
    **kwargs: Unpack[EntityContext[models.Page | models.Task | models.TaskHistory]],
) -> ResponseReturnValue:
    entity = load_route_entity(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    field = entity.properties.submission.fields.get(table_id)
    if not isinstance(field, Table):
        return responses.error("The original table definition is unavailable.")
    submission = entity.properties.submission.value
    field.value = submission.get(table_id) if isinstance(submission, dict) else None
    field.kind = (
        entity.kind if not isinstance(entity, Entities.TASK_HISTORY) else "form"
    )

    return responses.expanded_table_cell(field)


# @scaffolding testing/resources/form.py::Builder.restrict_to_owner
# @scaffolding testing/resources/form.py::Builder.restrict_to_group
@forms.route("<key>/restrictions", methods=["PUT"])
@permission(Resource.FORM, Action.EDIT)
def restrictions(
    key: str, **kwargs: Unpack[EntityContext[models.Form]]
) -> ResponseReturnValue:
    form = kwargs["entity"]

    admin_only = request.form.get("admin") in {"on", "true"}
    keys = [] if admin_only else request.form.getlist("group-key")
    try:
        resolver = SubmittedReferenceResolver(authenticated_user(), *keys)
        groups = [resolver.one(key, expected=Entities.USER_GROUP, action=Action.VIEW, required=True)
                  for key in keys]
        form.groups = groups
        form.properties.restricted_to.materialize(admin_only=admin_only)
        form.save()
    except (exceptions.ValidationError, ValueError) as error:
        return responses.error(str(error))
    return responses.ok()


@forms.route("/create-schema", methods=["POST"])
@permission(Resource.FORMS, Action.EDIT)
def create_schema() -> ResponseReturnValue:
    description = request.form.get("description", "")
    form_key = request.form.get("form-key")
    try:
        form = SubmittedReferenceResolver(authenticated_user(), form_key).one(
            form_key,
            expected=Entities.FORM,
            action=Action.EDIT,
            required=True,
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    require_ai_access(AI.CREATE)

    if request.form.get("explain") or request.form.get("role") == "explain":
        return responses.error("Initial Prompt is no longer available.")

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
        draft: FormDraft = {"schema": schema, "html_fields": html_fields}
        form_type = form.form_type
        if form_type is None:
            raise exceptions.ValidationError("The Form type is unavailable.")
        prompt = ai_schema.form_generation_prompt(form_type, description=description, draft=dict(draft))
        sources = _draft_image_sources(form, html_fields)
        result = ai_schema.generate_schema(prompt, validator=lambda value: prepare_generated_changes(
            value, draft, form_type=form_type, image_sources=sources,
        ))
        current = Entities.fetch_one(form.key, request=Fetch.direct())
        if not isinstance(current, Entities.FORM) or not current.allowed(Action.EDIT, user=current_user):
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


@forms.route("<key>/schema", methods=["GET"])
@permission(Resource.FORM, Action.VIEW)
def schema(
    key: str, **kwargs: Unpack[EntityContext[models.Form]]
) -> ResponseReturnValue:
    form = kwargs["entity"]
    return responses.json_response({"schema": form.schema})
