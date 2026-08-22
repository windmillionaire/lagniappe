"""Deferred-job adapters for the pages domain."""

from copy import deepcopy
import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobSpec,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
    Fetch,
    FetchReason,
    FileConsumer,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database, dates, files, site_export
from lagniappe.core.tools.database import assets as storage_assets

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
    DeferredJobDriftError,
)
from ..locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    active_deferred_job_lock,
    deferred_job_lock_key,
)




# @testable infrastructure
class PageGenerationAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.PAGE_GENERATION
    required_ai_access = AI.CREATE
    queued_message = "Generating pages..."
    retry_message = "AI is temporarily busy; retrying page generation shortly..."
    success_message = "Generated pages are ready."
    failure_prefix = "Page generation failed."
    mutation_inputs = ("category", "form")

    # @testable infrastructure
    def authorize(self, context):
        super().authorize(context)
        category = context.input("category")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred page generation user is invalid.")
        if not isinstance(category, Entities.CATEGORY):
            raise exceptions.ValidationError("Deferred page generation category is invalid.")
        if not category.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to edit this category."
            )
        form = context.input("form")
        if form is not None and (
            not isinstance(form, Entities.FORM)
            or not form.allowed(Action.VIEW, user=context.actor)
        ):
            raise exceptions.ValidationError(
                "You do not have permission to use this form."
            )

    # @testable infrastructure
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.GENERATING)
        category = context.input("category")
        form = context.input("form")
        fields = context.parameters.get("fields") or {}
        form_schema = form.schema if form else None
        prompt = ai.page_generation_prompt(
            category_name=category.name,
            category_description=category.description,
            category_id=category.urlsafe_key,
            form_id=form.urlsafe_key if form else None,
            user_request=fields.get("user_description"),
            num_pages=fields.get("num_pages"),
            form_schema=form_schema,
            user=context.actor,
        )
        generated = ai.generate_pages(prompt, form_schema=form_schema)
        records = []
        for item in generated:
            key = database.create_key("page", None)
            records.append(
                {
                    "key": database.get.urlsafe_key(key),
                    "page": item,
                }
            )
        return {"pages": records}

    # @testable infrastructure
    def inspect(self, context):
        records = context.checkpoint.get("pages") or []
        if not records:
            return DeferredJobInspection.APPLIED
        existing = [
            Entities.fetch_one(record["key"], request=Fetch.direct())
            for record in records
        ]
        return (
            DeferredJobInspection.APPLIED
            if all(existing)
            else DeferredJobInspection.NOT_APPLIED
        )

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_pages.py::test_page_generation_apply_uses_direct_fields_and_form_fallbacks
    # @pairs ai:page-generation pages:form-defaults pages:no-form
    def apply(self, context):
        context.ensure_active()
        category = context.input("category")
        form = context.input("form")
        pages = []
        for record in context.checkpoint.get("pages") or []:
            existing = Entities.fetch_one(record["key"], request=Fetch.direct())
            if existing:
                pages.append(existing)
                continue
            generated = deepcopy(record["page"])
            submission = generated.get("submission")
            if not isinstance(submission, dict):
                submission = {}
            name = generated.get("name") or submission.get("name")
            description = generated.get("description") or submission.get("description")
            page = Entities.PAGE.create(
                {
                    "model": category,
                    "form": form,
                    "name": name,
                    "description": description,
                }
            )
            page._key = database.get.datastore_key(record["key"])
            if generated.get("document"):
                page.properties.document.html = generated["document"]
            if form and submission:
                schema_ids = {
                    field.get("id")
                    for field in form.schema or []
                    if isinstance(field, dict)
                }
                if name and "name" in schema_ids:
                    submission["name"] = name
                if description and "description" in schema_ids:
                    submission["description"] = description
                page.ai_submission(submission)
            pages.append(page)
        Entities.save(*pages, category)
        return {"page_keys": [page.urlsafe_key for page in pages]}
