"""AI-powered form autofill using context, files, and web search."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage
    from ...entities.file import File
    from ...entities.category import Category
    from .guidelines.field_types import GuidanceField
    from ...entities.form import Form
    from ...entities.page import Page
    from ...entities.task import Task
    from ...entities.user import User
    from ...properties.file_assets import FilePart
    from ..database.assets import DirectUploadFile

import re
from functools import partial

from ... import exceptions
from ...definitions import Action
from .core import ai_model
from .guidelines import (
    FILE_CONTEXT,
)
from .guidelines.field_types import schema_guidance
from .prompt import Prompt
from .submission_values import values_by_id
from ...properties.schema import SchemaFields

citations = re.compile(r"\. \[.*?\]")

GENERIC_MESSAGE = "Generation failed. Please try again. "
AUTOFILL_MAX_TOOL_ITERATIONS = 2

AUTOFILL_RULES = """
### Grounded form updates

- Propose updates for this one form using exact field IDs. Omitted fields stay unchanged.
- Preserve useful existing answers. You may enrich or correct populated answers
  when requested or supported by the supplied evidence; do not invent facts or
  silently choose between conflicting sources.
- You may add table rows and todo items to populated fields. Return the complete
  proposed value for a changed collection, retaining existing rows/items, order,
  and checked states unless the user asks to change them. New todos are unchecked.
- Respect explicit user instructions first, then supplied files and existing
  answers. Use focused public web research for missing public facts, including
  when only a title/name was supplied. Do not search for private workspace facts.
- Do not invent personal opinions, ratings, signatures, or user-action answers.
  Creative content is appropriate only when the field or request calls for it.
- The supplied original file is ready to use: do not wait for a summary. Other
  listed files can be read with get_file(include_original=true) when needed.
- Optional page/category context is available through get_entity using the listed
  references. Read it only if relevant answers need that context; do not explore
  unrelated entities, sibling tasks, or task history. Batch independent reads.
- Once you have enough evidence, return the proposed updates. Unsupported fields
  can be omitted without blocking the rest of the form.
"""

AUTOFILL_OUTPUT_REQUIREMENTS = """
### Submission Output Requirements

Return a JSON object keyed by exact schema field IDs, containing only proposed
updates. Do not wrap it in submission/answers, include labels as keys, or add
commentary. A changed table/todo value contains its complete proposed rows/items.
Use null only for an intentional clearing requested by the user. Omission means
unchanged, not empty. Static HTML, status, and signatures cannot be generated.
"""


class AutofillPromptOptions(TypedDict, total=False):
    user: User
    user_context: str | None
    file: FileStorage | DirectUploadFile | None
    mimetype: str | None
    schema: list[dict[str, object]]
    form: Form | None
    form_name: str | None
    create: bool
    original_files: Sequence[File]
    original_file_parts: Sequence[FilePart]
    attached_files: Sequence[Mapping[str, str]]
    submission: dict[str, object] | None
    target: dict[str, object]
    parent_page: dict[str, object] | None
    category: dict[str, object] | None
    context_references: dict[str, str]
    review_context: dict[str, object] | None


def submission_response_schema() -> dict[str, object]:
    """Return the provider schema for one dynamic form submission object."""
    return {"type": "object"}


def _autofill_page(entity: Page | Task) -> Page | None:
    if getattr(entity, "entity_kind", None) == "task":
        return cast("Task", entity).page
    if getattr(entity, "entity_kind", None) == "page":
        return cast("Page", entity)
    return None


def _readable_autofill_files(entity, user):
    if getattr(entity, "entity_kind", None) not in {"page", "task"}:
        return []

    files = []
    seen = set()
    for file in getattr(entity, "files", None) or []:
        key = getattr(file, "key", None) or getattr(file, "hash", None)
        if not file or key in seen or not file.allowed(Action.VIEW, user=user):
            continue
        seen.add(key)
        files.append(file)
    return files


def autofill_attached_files(entity: Page | Task, user: User) -> list[dict[str, str]]:
    """List directly attached evidence without eagerly injecting its summaries."""
    return [
        {key: value for key, value in {
            "hash": f"hash:{file.hash}",
            "filename": file.filename,
            "mimetype": file.mimetype,
        }.items() if value}
        for file in _readable_autofill_files(entity, user)
    ]


def autofill_summary_dependencies(entity: Page | Task, user: User) -> dict[str, list[File]]:
    """Classify enabled attached-file summaries before autofill generation."""
    states = {"complete": [], "pending": [], "failed": []}
    for file in _readable_autofill_files(entity, user):
        summarize = file.properties.summarize
        if not summarize.enabled:
            continue
        if summarize.complete:
            states["complete"].append(file)
        elif summarize.error:
            states["failed"].append(file)
        else:
            states["pending"].append(file)
    return states


def autofill_prompt_data(
    entity: Page | Task,
    user: User,
    *,
    user_context: str | None = None,
    file: FileStorage | DirectUploadFile | None = None,
    mimetype: str | None = None,
    create: bool = False,
) -> AutofillPromptOptions:
    """Build the shared page/task data contract consumed by autofill prompts."""
    page = _autofill_page(entity)
    task = entity if getattr(entity, "entity_kind", None) == "task" else None
    target = {
        "kind": getattr(entity, "entity_kind", None),
        "name": getattr(entity, "name", None),
        "description": getattr(entity, "description", None),
    }
    target = {key: value for key, value in target.items() if value is not None}
    parent_page = None
    if task and page:
        parent_page = {
            "name": getattr(page, "name", None),
        }
        parent_page = {
            key: value for key, value in parent_page.items() if value is not None
        }

    category_context = None
    category = cast("Category | None", getattr(page, "model", None)) if page else None
    if category and category.allowed(Action.VIEW, user=user):
        category_context = {
            "name": getattr(category, "name", None),
        }
        category_context = {
            key: value
            for key, value in category_context.items()
            if value is not None
        }

    form = getattr(entity, "form", None)
    submission = None
    if getattr(entity, "properties", None):
        submission_property = entity.properties.submission
        submission_property.user = user
        submission = values_by_id(submission_property.fields, user)

    references = {}
    for label, source in (("page", page), ("category", category)):
        if source and getattr(source, "hash", None) and source.allowed(Action.VIEW, user=user):
            references[label] = f"hash:{source.hash}"

    return {
        "file": file,
        "user": user,
        "user_context": user_context,
        "mimetype": mimetype,
        "context_references": references,
        "submission": submission,
        "schema": entity.submission_schema,
        "form_name": form.name if form else None,
        "target": target,
        "parent_page": parent_page,
        "category": category_context,
        "attached_files": autofill_attached_files(entity, user),
        "create": create,
    }


def validate_submission(submission: object, *, entity: Page | Task | None = None, user: User | None = None, schema: Sequence[dict[str, object]] | None = None) -> dict[str, object]:
    """Validate exact target fields without mutation and clean text citations."""
    if not isinstance(submission, dict):
        raise exceptions.AIException("Submission must be a JSON object keyed by exact field ids.")
    submission = dict(submission)
    if entity is not None:
        fields = (
            {cast(str, field["id"]): field for field in schema}
            if schema is not None else entity.properties.submission.fields
        )
        unknown = set(submission) - set(fields)
        if unknown:
            raise exceptions.AIException(
                f"Submission contains unavailable field ids: {', '.join(sorted(unknown))}. "
                f"Use only these exact field ids: {', '.join(fields)}. "
                "Field titles are not keys; return the submission object without a wrapper."
            )
        for field_id, value in submission.items():
            try:
                if fields[field_id].get("type") in {"signature", "html", "status"}:
                    raise exceptions.ValidationError("This field cannot be generated.")
                SchemaFields.prepare_ai_field(fields[field_id], value, entity, user=user)
            except (ValueError, TypeError, AttributeError, exceptions.ValidationError) as error:
                raise exceptions.AIException(f"Submission field {field_id}: {error}") from error
    textareas = [
        (schema_id, v)
        for schema_id, v in submission.items()
        if (
            schema_id.startswith("textarea-") or schema_id == "description"
        )
        and isinstance(v, str)
    ]

    for schema_id, textarea in textareas:
        submission[schema_id] = citations.sub(".", textarea)

    return submission


def generate_autofilled_submission(prompt: Prompt, *, entity: Page | Task, user: User, schema: Sequence[dict[str, object]] | None = None) -> dict[str, object]:
    """Generate and validate an autofilled form submission from a Prompt."""
    try:
        return ai_model.generate_content(
            prompt,
            validator=partial(validate_submission, entity=entity, user=user, schema=schema),
            validation_retries=2,
        )
    except Exception as e:
        raise exceptions.AIException(
            f"{GENERIC_MESSAGE} {str(e)}",
            context=getattr(e, "context", None),
        ) from e


def form_autofill_prompt(**kwargs: Unpack[AutofillPromptOptions]) -> Prompt:
    """Build the AI prompt for form autofilling based on existing data"""

    intro = "Propose grounded updates to one page or task form, using its current answers, supplied evidence, and focused public research when useful."
    prompt = Prompt(intro, user=kwargs.get("user"), type="autofill")
    prompt.set_thinking_level("LOW")
    prompt.enable_search()

    form = kwargs.get("form")
    form_name = form.name if form else kwargs.get("form_name")
    form_schema = form.schema if form else kwargs.get("schema")
    file = kwargs.get("file")
    original_files = tuple(kwargs.get("original_files") or ())
    original_file_parts = tuple(kwargs.get("original_file_parts") or ())
    original_hashes = {
        f"hash:{source.hash}"
        for source in original_files
        if getattr(source, "hash", None)
    }
    attached_files = [
        source for source in kwargs.get("attached_files") or ()
        if source.get("hash") not in original_hashes
    ]

    tool_names = []
    if attached_files:
        tool_names.append("get_file")
    if kwargs.get("context_references"):
        tool_names.append("get_entity")
    if tool_names and kwargs.get("user"):
        prompt.enable_tools(*tool_names)
        prompt.set_max_tool_iterations(AUTOFILL_MAX_TOOL_ITERATIONS)

    prompt.add_context("target_record", kwargs.get("target"))
    prompt.add_context("parent_page", kwargs.get("parent_page"))
    prompt.add_context("category", kwargs.get("category"))
    prompt.add_context("form_name", form_name)
    prompt.add_context("form_schema", form_schema)
    prompt.add_context("existing_submission", kwargs.get("submission"))
    prompt.add_context("user_provided_context", kwargs.get("user_context"))
    prompt.add_context("optional_context_references", kwargs.get("context_references"))
    prompt.add_context("review_context", kwargs.get("review_context"))
    prompt.add_context("attached_files", attached_files)
    if file:
        mimetype = file.content_type or kwargs.get("mimetype")
        prompt.add_bytes(file, mimetype)
        if not prompt.bytes:
            raise exceptions.ValidationError("This file type cannot be read directly by autofill.")
    for source in original_files:
        before = len(prompt.files)
        prompt.add_file(source, user=kwargs.get("user"))
        if len(prompt.files) == before:
            raise exceptions.ValidationError("The supplied file is no longer available for autofill.")
    for part in original_file_parts:
        if not isinstance(part, dict) or not part.get("uri") or not part.get("mime_type"):
            raise exceptions.ValidationError("The supplied file is no longer available for autofill.")
        prompt.files.append({"uri": part["uri"], "mime_type": part["mime_type"]})

    if prompt.bytes or prompt.files:
        prompt.add_context("file_data", FILE_CONTEXT.strip())

    prompt.add_instructions(AUTOFILL_RULES)
    prompt.add_instructions(schema_guidance(cast("Sequence[GuidanceField] | None", form_schema)))
    prompt.set_output_format("JSON", description=AUTOFILL_OUTPUT_REQUIREMENTS)

    return prompt
