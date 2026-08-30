from flask import request
from flask_login import current_user

from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools import ai, filters
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobSpec,
    DeferredJobType,
    MutationIntent,
    Resource,
)
from lagniappe.web.auth import permission, require_ai_access
from lagniappe.web import responses
from lagniappe.core.tools.diagnostics import timed

from . import categories


# @testable true
# @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_page_acl_user_sees_one_page_on_category_index_home_and_search
# @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_category_create_scoped_to_one_category
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_renders_first_batch_before_cursor_continuation
# @matrix categories : create-control first-batch index-filter permission-gates server-render
@categories.route("/<key>", methods=["GET"])
@timed(profile=True)
@permission(Resource.CATEGORY, Action.RESTRICTED)
def index(key, **kwargs):
    category = kwargs["entity"]

    filters.FilterCache(category).update()

    category_index = category.index(**request.values)
    pages = category_index.pages

    return responses.index("categories", category_index, pages=pages)


# @testable true
# @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_page_acl_user_sees_one_page_on_category_index_home_and_search
# @matrix categories : index-filter permission-gates
@categories.route("/<key>/rows", methods=["GET"])
@permission(Resource.CATEGORY, Action.RESTRICTED)
def rows(key, **kwargs):
    category = kwargs["entity"]

    category_index = category.index(**request.values)
    pages = category_index.pages

    return responses.rows(pages, category_index)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::category_info
@categories.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.CATEGORY, Action.VIEW)
def info(key, **kwargs):
    return responses.category_info(kwargs["entity"])


# @testable false
# @covered-by lagniappe/web/routes/categories/main.py::create
# @covered-by lagniappe/web/routes/categories/main.py::update
# @reason form parsing helper owned by category create/update routes
def _category_data(form, category=None):
    form_key = form.get("form")
    current_form = category.form if category else None
    selected_form = SubmittedReferenceResolver(current_user, form_key).one(
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


# @testable true
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_update_category_info_from_tools
# @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_category_viewer_opens_readonly_settings
# @matrix categories : permission-gates update
@categories.route("<key>/update", methods=["PUT"])
@permission(Resource.CATEGORY, Action.EDIT)
def update(key, **kwargs):
    category = kwargs["entity"]

    try:
        category.update(_category_data(request.form, category=category))
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    Entities.save(category)

    return responses.category_info(category)


# @testable false
# @covered-by lagniappe/web/routes/categories/main.py::create
# @reason AI response shaping is exercised through the category create route
def _generate_category(generated_data):
    if generated_data.get("form_schema"):
        create_form_data = {
            "name": generated_data.get("form_name"),
            "schema": generated_data.get("form_schema"),
            "form-type": "page",
        }
        form = Entities.FORM().create(create_form_data)
    else:
        form = None

    category_data = {
        "name": generated_data.get("category_name"),
        "description": generated_data.get("category_description"),
        "form": form,
    }

    return category_data


# @testable true
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_category_form_explain_button
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_manual_mode
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_ai_mode
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_with_form
# @matrix categories : ai-create attach-form create-manual explain-button
@categories.route("create", methods=["POST"])
@permission(Resource.MODELS, Action.CREATE)
def create():
    generate = request.form.get("generate")
    explain = request.form.get("role") == "explain"

    if generate:
        require_ai_access(AI.CREATE)
        prompt = ai.category_creation_prompt(request.form.get("user_description"))
        if explain:
            return responses.explain(prompt)

        try:
            results = ai.generate_category(prompt)
            generated_data = _generate_category(results)
        except (exceptions.AIException, Exception) as e:
            return responses.error(str(e), exception=e)

        category = Entities.CATEGORY().create(generated_data)
        category.ai_generated = True
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


# @testable true
# @tests tests_e2e/002_home/test_002c_home_categories.py::test_delete_category
# @pair categories:delete
@categories.route("<key>/delete", methods=["DELETE"])
@permission(Resource.MODELS, Action.DELETE)
def delete(key, **kwargs):
    category = kwargs["entity"]
    if not category:
        return responses.error("category not found")

    Entities.delete(category)

    return responses.ok()


# @testable false
# @covered-by lagniappe/web/routes/categories/main.py::create_pages
# @reason prompt data assembly is part of the generated-pages workflow
def page_generation_data(category, form, form_data, user):
    return {
        "category_name": category.name,
        "category_description": category.description,
        "category_id": category.urlsafe_key,
        "form_id": form.urlsafe_key if form else None,
        "user_request": form_data.get("user_description"),
        "num_pages": form_data.get("num_pages"),
        "form_schema": form.schema if form else None,
        "user": user,
    }


# @testable true
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_generate_pages_explain_prompt_from_category_tools
# @matrix pages : ai-form explain-button generate
@categories.route("<key>/generate-pages", methods=["POST"])
@permission(Resource.CATEGORY, Action.EDIT)
def create_pages(key, **kwargs):
    require_ai_access(AI.CREATE)

    category = kwargs["entity"]
    explain = request.form.get("role") == "explain"
    form_key = request.form.get("form")
    try:
        form = SubmittedReferenceResolver(current_user, form_key).one(
            form_key,
            expected=Entities.FORM,
            action=Action.VIEW,
            predicate=lambda candidate: candidate.form_type == "page",
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    fields = request.form.to_dict(flat=True)
    operation_id = fields.pop("operation-id", None)

    if explain:
        generate_data = page_generation_data(category, form, fields, current_user)
        return responses.explain(ai.page_generation_prompt(**generate_data))

    job, notification = DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.PAGE_GENERATION,
            actor=current_user._get_current_object(),
            idempotency_key=operation_id,
            inputs={"category": category, "form": form},
            parameters={"fields": fields},
            notification_body="Generating pages...",
            notification_target=category,
            client={
                "key": category.urlsafe_key,
                "source_widget": "GeneratePages",
                "destination": "table:IndexTable",
            },
        )
    )

    return responses.json_response(
        {
            "deferred": True,
            "operation": job.urlsafe_key,
            "notification": responses.notification_item(notification),
        }
    )
