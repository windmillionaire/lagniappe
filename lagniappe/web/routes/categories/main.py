from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from werkzeug.datastructures import MultiDict
    from lagniappe.core.entities.category import CategoryData
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from flask import jsonify, request
from flask_login import current_user

from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools import filters
from lagniappe.core.tools.ai import category as ai_category
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.core.definitions import (
    AI,
    Action,
    MutationIntent,
    Resource,
)
from lagniappe.web.auth import authenticated_user, permission, require_ai_access
from lagniappe.web.pagination import pagination_options
from lagniappe.web import responses
from lagniappe.core.tools.diagnostics import timed

from . import categories


@categories.route("/<key>", methods=["GET"])
@timed(profile=True)
@permission(Resource.CATEGORY, Action.RESTRICTED)
def index(
    key: str, **kwargs: Unpack[EntityContext[models.Category]]
) -> ResponseReturnValue:
    category = kwargs["entity"]

    filters.FilterCache(category).update()

    category_index = category.index(**pagination_options())
    pages = category_index.pages

    return responses.index("categories", category_index, pages=pages)


@categories.route("/<key>/rows", methods=["GET"])
@permission(Resource.CATEGORY, Action.RESTRICTED)
def rows(
    key: str, **kwargs: Unpack[EntityContext[models.Category]]
) -> ResponseReturnValue:
    category = kwargs["entity"]

    category_index = category.index(**pagination_options())
    pages = category_index.pages

    return responses.rows(pages, category_index)


@categories.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.CATEGORY, Action.VIEW)
def info(
    key: str, **kwargs: Unpack[EntityContext[models.Category]]
) -> ResponseReturnValue:
    return responses.category_info(kwargs["entity"])


def _category_data(form: MultiDict[str, str], category: models.Category | None = None) -> CategoryData:
    form_key = form.get("form")
    current_form = category.form if category else None
    selected_form = SubmittedReferenceResolver(authenticated_user(), form_key).one(
        form_key,
        expected=Entities.FORM,
        action=Action.VIEW,
        existing=current_form,
        predicate=lambda candidate: candidate.form_type == "page",
    )
    if not form_key and current_form and not current_form.allowed(
        Action.VIEW, user=current_user
    ):
        selected_form = current_form

    return {
        "name": form.get("name"),
        "description": form.get("description"),
        "form": selected_form,
    }


@categories.route("<key>/update", methods=["PUT"])
@permission(Resource.CATEGORY, Action.EDIT)
def update(
    key: str, **kwargs: Unpack[EntityContext[models.Category]]
) -> ResponseReturnValue:
    category = kwargs["entity"]

    try:
        category.update(_category_data(request.form, category=category))
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    Entities.save(category)

    return responses.category_info(category)


@categories.route("/<key>/patch", methods=["PATCH"])
@permission(Resource.CATEGORY, Action.EDIT)
def patch(
    key: str, **kwargs: Unpack[EntityContext[models.Category]]
) -> ResponseReturnValue:
    category = kwargs["entity"]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return responses.bad_request("Invalid category patch payload")

    schema_id = payload.get("schema_id")
    value = payload.get("value")

    if schema_id == "name":
        data: CategoryData = {
            "name": str(value) if value is not None else "",
            "description": category.description,
            "form": category.form,
        }
    elif schema_id == "description":
        data = {
            "name": category.name,
            "description": str(value) if value is not None else "",
            "form": category.form,
        }
    elif schema_id == "form":
        form_key = str(value).strip() if value else None
        try:
            selected_form = SubmittedReferenceResolver(
                authenticated_user(), form_key
            ).one(
                form_key,
                expected=Entities.FORM,
                action=Action.VIEW,
                existing=category.form,
                predicate=lambda candidate: candidate.form_type == "page",
            )
        except exceptions.ValidationError as error:
            return responses.error(str(error))
        data = {
            "name": category.name,
            "description": category.description,
            "form": selected_form,
        }
    else:
        return responses.bad_request(f"Unsupported category field: {schema_id}")

    try:
        category.update(data)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    Entities.save(category)

    return (
        jsonify(
            {
                "name": category.name,
                "description": category.description or "",
                "form": category.properties.form.column_value if category.form else None,
                "fingerprint": category.fingerprint,
            }
        ),
        200,
    )


def _generate_category(generated_data: ai_category.GeneratedCategory) -> CategoryData:
    if generated_data.get("form_schema"):
        create_form_data = {
            "name": generated_data.get("form_name"),
            "schema": generated_data.get("form_schema"),
            "form-type": "page",
        }
        form = Entities.FORM().create(create_form_data)
    else:
        form = None

    category_data: CategoryData = {
        "name": generated_data.get("category_name"),
        "description": generated_data.get("category_description"),
        "form": form,
    }

    return category_data


@categories.route("create", methods=["POST"])
@permission(Resource.MODELS, Action.CREATE)
def create() -> ResponseReturnValue:
    generate = request.form.get("generate")
    if request.form.get("role") == "explain" or request.form.get("explain"):
        return responses.error("Initial Prompt is no longer available.")

    if generate:
        require_ai_access(AI.CREATE)
        prompt = ai_category.category_creation_prompt(request.form.get("user_description") or "")
        try:
            results = ai_category.generate_category(prompt)
            generated_data = _generate_category(results)
        except (exceptions.AIException, Exception) as e:
            return responses.error(str(e), exception=e)

        category = Entities.CATEGORY().create(generated_data)
        category.ai_generated = True
        if category.form is not None:
            category.add_mutation_intents(
                MutationIntent.standard(
                    category.form,
                    reason="generated-category-form",
                )
            )
    else:
        try:
            category = Entities.CATEGORY().create(_category_data(request.form))
        except exceptions.ValidationError as error:
            return responses.error(str(error))

    category.save()

    return responses.new_category(category)


@categories.route("<key>/delete", methods=["DELETE"])
@permission(Resource.MODELS, Action.DELETE)
def delete(key: str, **kwargs: Unpack[EntityContext[Entity]]) -> ResponseReturnValue:
    category = kwargs["entity"]
    if not category:
        return responses.error("category not found")

    Entities.delete(category)

    return responses.ok()
