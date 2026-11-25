"""Submitter mixin for entities with form submissions."""

from collections.abc import Container, Iterable, Mapping
from typing import TYPE_CHECKING, Protocol, cast

import hashlib
import json

from ..definitions.fingerprints import restricted_fingerprint
from ..exceptions import ValidationError
from ..entities import Entities
from lagniappe.core.tools.forms.definitions import (
    definition_for,
    require_mutable_submission,
)
from lagniappe.core.tools.database import get as database_get
from ..tools.auth.references import (
    SubmittedReferenceResolver,
    UNAVAILABLE_REFERENCE_ERROR,
)


if TYPE_CHECKING:
    from flask import Request
    from google.cloud.datastore import Key
    from werkzeug.local import LocalProxy

    from ..entities.entity import Entity
    from ..entities.history import TaskHistory
    from ..entities.page import Page
    from ..entities.task import Task
    from ..entities.user import User
    from ..mixins.field_host import FieldUser
    from ..properties.row_submission import ImportSettings
    from ..tools.forms.definitions import SubmissionDefinition

    type SubmissionOwner = Page | Task | TaskHistory
    type SubmissionActor = User | LocalProxy[User | None]


class FormValues(Protocol):
    def keys(self) -> Iterable[str]: ...
    def get(self, key: str, default: object = None, /) -> object: ...


class _Revision(Protocol):
    @property
    def fingerprint(self) -> str: ...


type NormalizedValues = dict[str, list[object] | dict[str, object]]


def normalize_submission_values(values: FormValues | Mapping[str, object], fields: Container[str]) -> NormalizedValues:
    updated: NormalizedValues = {}

    for field in values.keys():  # noqa: SIM118 -- form adapters may expose keys() without implementing iteration.
        parts = field.split(":", 1)
        schema_id = parts[0]
        part = parts[1] if len(parts) > 1 else None

        if schema_id not in fields:
            continue

        getlist = getattr(values, "getlist", None)
        source_values = getlist(field) if getlist else values.get(field)
        if isinstance(source_values, list):
            update = [v for v in source_values if v]
        else:
            update = [source_values] if source_values else []

        if part:
            # Multipart controls use a dictionary; a colliding single-value key still raises.
            parts_by_name = cast("dict[str, object]", updated.setdefault(schema_id, {}))
            parts_by_name[part] = update[0] if update else None
        else:
            updated[schema_id] = update

    return updated


def _link_identifier(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        identifier = value.get("id")
        return identifier if isinstance(identifier, str) and identifier else None
    return None


def _internal_link_ids(field: object, value: object) -> set[str]:
    """Extract internal Link identifiers without resolving or mutating fields."""
    from ..properties.form_links import Link
    from ..properties.form_table import Table

    if isinstance(field, Link):
        if not field.is_entity_valued:
            return set()
        identifier = _link_identifier(value)
        return {identifier} if identifier else set()

    if not isinstance(field, Table):
        return set()

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValidationError(UNAVAILABLE_REFERENCE_ERROR) from error
    if value is None:
        return set()
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("rows", []), list):
        rows = value.get("rows", [])
    else:
        raise ValidationError(UNAVAILABLE_REFERENCE_ERROR)

    internal_columns = {
        field_id
        for field_id, column in field.fields.items()
        if isinstance(column, Link) and column.is_entity_valued
    }
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError(UNAVAILABLE_REFERENCE_ERROR)
        for field_id in internal_columns:
            value = row.get(field_id)
            column = field.fields[field_id]
            if isinstance(value, list) and not column.multiple and value:
                value = value[0]
            identifier = _link_identifier(value)
            if identifier:
                identifiers.add(identifier)
    return identifiers


class SubmitterMixin:
    """Adds form submission handling to entities with a Form schema.

    Used by Page and Task entities. Submission data is stored in
    entity.db["submission"] as JSON.

    Provides:
        form_submission(values): Validate and save form data from a web request.
        ai_submission(submission): Validate and save AI-generated field values.
        import_submission(submission): Validate and save CSV-imported field values.
        save_submission(): Persist ``submission.db_value`` and form metadata.
        fingerprint: MD5 combining the base entity revision, its own Form's
            schema version, and every effective restriction group.
    """

    @property
    def _submission_owner(self) -> SubmissionOwner:
        # These three registered entity classes supply the concrete field and datastore contracts.
        return cast("SubmissionOwner", self)

    def preview_form_submission(self, values: Request | FormValues, *, actor: SubmissionActor) -> dict[str, dict[str, object]]:
        """Validate a browser draft without changing the entity or its saved answers."""
        from ..properties.form_submission import FormSubmission
        from ..tools.ai.submission_values import values_by_id

        owner = self._submission_owner
        require_mutable_submission(owner)
        form_values = cast(FormValues, getattr(values, "form", values))
        if str(form_values.get("form-generation", "0")) != str(self.submission_definition.generation):
            raise ValidationError("The form fields changed. Your answers were not saved. Review the updated form before trying again.")
        submission = FormSubmission(entity=owner)
        updated = normalize_submission_values(form_values, submission.fields)
        preserved = self.validate_browser_submission_references(
            updated, actor=actor, normalized=True,
        )
        for field_id, field in submission.fields.items():
            if field_id in preserved:
                continue
            value = updated.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            field.validate_submission(value)
        return {
            "answers": submission.db_value,
            "values": submission.form_value,
            "ai_values": values_by_id(submission.fields, actor),
        }

    def form_submission(self, values: Request | FormValues, *, actor: SubmissionActor | None = None) -> None:
        owner = self._submission_owner
        require_mutable_submission(owner)
        submission = owner.properties.submission
        form_values = cast(FormValues, getattr(values, "form", values))
        if actor is not None and str(form_values.get("form-generation", "0")) != str(self.submission_definition.generation):
            raise ValidationError("The form fields changed. Your answers were not saved. Review the updated form before trying again.")
        files = getattr(values, "files", None)
        updated = normalize_submission_values(form_values, submission.fields)
        preserved = (
            self.validate_browser_submission_references(
                updated,
                actor=actor,
                normalized=True,
            )
            if actor is not None
            else set()
        )

        for field_id, field in submission.fields.items():
            if field_id in preserved:
                continue
            value = updated.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            if files and isinstance(value, str):
                uploaded = files.get(value)
                if uploaded:
                    value = uploaded

            field.validate_submission(value)

        self.save_submission()

    def validate_browser_submission_references(
        self,
        values: FormValues | Mapping[str, object],
        *,
        actor: SubmissionActor,
        normalized: bool = False,
    ) -> set[str]:
        """Authorize changed internal Link values before applying a browser form."""
        from ..definitions import Action
        from ..properties.form_links import Link
        from ..properties.form_table import Table

        owner = self._submission_owner
        submission = owner.properties.submission
        updated = (
            cast("Mapping[str, object]", values)
            if normalized
            else normalize_submission_values(values, submission.fields)
        )
        submitted_by_field = {}
        existing_by_field = {}

        for field_id, field in submission.fields.items():
            if not isinstance(field, (Link, Table)):
                continue

            value = updated.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            submitted_by_field[field_id] = _internal_link_ids(field, value)
            existing_by_field[field_id] = _internal_link_ids(field, field.db_value)

        all_ids = {
            identifier
            for identifiers in [*submitted_by_field.values(), *existing_by_field.values()]
            for identifier in identifiers
        }
        if not all_ids:
            return set()

        expected: tuple[type[Entity], ...] = (
            Entities.CATEGORY,
            Entities.PAGE,
            Entities.USER,
            Entities.GROUP,
            Entities.PROJECT,
            Entities.TASK,
            Entities.MODEL_TASK,
            Entities.FILE,
            Entities.FORM,
        )
        resolver = SubmittedReferenceResolver(cast("User", actor), *all_ids)
        preserved = set()

        for field_id, submitted_ids in submitted_by_field.items():
            existing_ids = existing_by_field[field_id]
            changed_ids = submitted_ids - existing_ids
            resolver.many(changed_ids, expected=expected, action=Action.VIEW)

            if field_id in updated or not existing_ids:
                continue

            for identifier in existing_ids:
                try:
                    resolver.one(
                        identifier,
                        expected=expected,
                        action=Action.VIEW,
                        required=True,
                    )
                except ValidationError:
                    preserved.add(field_id)
                    break

        return preserved

    def patch_submission(self, update: str | Mapping[str, object], *, actor: SubmissionActor | None = None) -> None:
        owner = self._submission_owner
        require_mutable_submission(owner)
        updated = json.loads(update) if isinstance(update, str) else update
        if actor is not None:
            self.validate_browser_submission_references(
                updated,
                actor=actor,
                normalized=True,
            )
        for field_id, field_value in updated.items():
            owner.properties.submission.patch(field_id, field_value)

        self.save_submission()

    def ai_submission(self, generated_submission: Mapping[str, object], *, actor: FieldUser = None, preserve_existing: bool = False) -> None:
        from ..properties.schema import SchemaFields

        owner = self._submission_owner
        require_mutable_submission(owner)
        unknown = set(generated_submission) - set(owner.properties.submission.fields)
        if unknown:
            raise ValidationError("Generated answers include unavailable fields and need review.")
        prepared = {}
        for field_id, field in owner.properties.submission.fields.items():
            if preserve_existing and field.is_set and field.db_value not in (None, "", [], {}):
                continue
            prepared[field_id] = SchemaFields.prepare_ai_field(
                field, generated_submission.get(field_id), owner, user=actor
            )
        for field_id, candidate in prepared.items():
            field = owner.properties.submission.fields[field_id]
            field.reset()
            if candidate.is_set:
                field.db_value = candidate.db_value

        self.save_submission()

    def import_submission(self, imported_submission: Mapping[str, object], import_process: ImportSettings) -> None:
        owner = self._submission_owner
        require_mutable_submission(owner)
        for field_id, field in owner.properties.submission.fields.items():
            try:
                field.reset()
                if hasattr(field, "fuzzy_match"):
                    setattr(field, "fuzzy_match", import_process.fuzzy_match(field_id))  # noqa: B010 -- optional CSV capability.
                if hasattr(field, "separator"):
                    setattr(field, "separator", import_process.separator)  # noqa: B010 -- optional CSV capability.
                if hasattr(field, "set_import_process"):
                    getattr(field, "set_import_process")(import_process)  # noqa: B009 -- optional nested table hook.
                value = imported_submission.get(field_id, None)
                if isinstance(value, list) and field.get("type") == "input":
                    value = " ".join(
                        str(v).strip()
                        for v in value
                        if v is not None and str(v).strip()
                    )
                field.validate_import(value)
            except Exception as e:
                raise ValidationError(
                    f"{field_id}:{imported_submission.get(field_id, None)} - {str(e)}"
                ) from e

        self.save_submission()

    @property
    def schema_version(self) -> str | None:
        return cast("str | None", self._submission_owner.db.get("schema_version"))

    @property
    def generation(self) -> int:
        return cast(int, self._submission_owner.db.get("generation", 0) or 0)

    @property
    def submission_definition(self) -> SubmissionDefinition:
        return definition_for(self._submission_owner)

    @property
    def submission_schema(self) -> list[dict[str, object]]:
        return self.submission_definition.schema

    @property
    def submission_schema_error(self) -> str | None:
        return self.submission_definition.error

    def save_submission(self) -> None:
        owner = self._submission_owner
        require_mutable_submission(owner)
        if owner.entity_kind in {"page", "task"}:
            owner._submission_input_generation = self.generation
        submission_value = owner.properties.submission.db_value
        owner.properties.submission.value = submission_value
        owner.db.pop("default_submission", None)
        owner.db.pop("pre_migration", None)
        if owner.form and owner.entity_kind != "task_history":
            owner.db["schema_version"] = owner.form.version
            owner.db["generation"] = owner.form.generation
        if "name" in submission_value:
            owner.name = cast("str | list[object] | None", submission_value["name"])
        if "description" in submission_value:
            owner.description = cast("str | None", submission_value["description"])

    @property
    def migration_notice(self) -> list[dict[str, object]]:
        from lagniappe.core.tools.forms.changes import notice_projection
        owner = self._submission_owner
        return notice_projection(owner) if owner.db.get("pre_migration") else []

    @property
    def derived_page_keys(self) -> list[Key]:
        owner = self._submission_owner
        keys = []
        for link in owner.properties.submission.links:
            if not isinstance(link, dict) or link.get("kind") not in ("page", "user"):
                continue

            key = database_get.datastore_key(link.get("id"))
            if key and key not in keys:
                keys.append(key)

        return keys

    @property
    def fingerprint(self) -> str:
        # TaskHistory resolves Entity.fingerprint before this mixin.
        owner = cast("Page | Task", self._submission_owner)
        form = owner.form
        version = (
            str(self.generation)
            if owner.entity_kind == "task_history"
            else (form.version if form else "")
        )
        return restricted_fingerprint(
            cast(_Revision, super()).fingerprint,
            owner.restricted_to,
            form_version=version or "",
        )

    @property
    def autofill_revision(self) -> str:
        """Stable revision for state that autofill reads and may overwrite."""
        owner = self._submission_owner
        form = owner.form
        schema_ids = {
            field.get("id")
            for field in (getattr(form, "schema", None) or [])
            if isinstance(field, dict) and field.get("id")
        }
        mirrored = {}
        if "name" in schema_ids:
            mirrored["name"] = owner.name
        if "description" in schema_ids:
            mirrored["description"] = owner.description

        canonical = json.dumps(
            {
                "form": getattr(form, "urlsafe_key", None),
                "form_version": getattr(form, "version", None),
                "schema_version": self.schema_version,
                "submission": owner.properties.submission.value or {},
                "mirrored": mirrored,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
