from datetime import datetime, timezone

from .entity import Entity, EntityProperties
from ..mixins import AssetMixin, SubmitterMixin
from ..exceptions import ValidationError
from ..definitions.identifiers import short_hash
from ..properties import (
    common_entity,
    common_related,
    form_submission,
    schema,
    task_dates,
    task_related,
)
from ..tools.files.html import strip_tags


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_uncomplete_after_complete
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_create_snapshots_completed_task_state
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_legacy_task_history_snapshot_text_defaults_to_none
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_fingerprint_ignores_later_form_versions
# @matrix task-completion : asset-copy description history immutable-fingerprint legacy linked-pages name schema-version snapshot submission
class TaskHistory(Entity, SubmitterMixin, AssetMixin):
    """Immutable task snapshot with a stable entity fingerprint.

    ``Entity`` intentionally precedes ``SubmitterMixin`` so the snapshot keeps
    the base fingerprint derived from ``modified`` (which is fixed to
    ``created`` below). Later changes to the attached Form version must not
    change an existing history row. The stable fingerprint remains part of the
    generic entity/ETag contract for directly loaded history rows; it is not an
    edit-revision signal.
    """

    entity_kind = "task_history"

    @property
    def exclude_from_index(self):
        exclude = {
            "submission",
            "schema",
        }
        return frozenset(exclude)

    @property
    def hash(self):
        if not self.key:
            return None

        urlsafe_key = self.urlsafe_key
        return short_hash(urlsafe_key) if urlsafe_key else None

    @property
    def required(self):
        task = self.task
        if task:
            return task.required

        return self.page.required if self.page else []

    @property
    def modified(self):
        return self.created

    @property
    def version(self):
        return self.db.get("schema_version")

    @version.setter
    def version(self, value):
        self.db["schema_version"] = value

    def _get_properties(self):
        properties = {
            "name": common_entity.Name,
            "created": common_entity.Created,
            "description": common_entity.Description,
            "submission": form_submission.FormSubmission,
            "completed_on": task_dates.CompletedOn,
            "completed_by": task_related.CompletedBy,
            "linked_pages": task_related.LinkedPages,
            "form": common_related.AttachedForm,
            "kind": common_entity.Kind,
            "requires": common_entity.Requires,
            "task": common_related.AttachedTask,
            "page": common_related.AttachedPage,
            "files": task_related.TaskFiles,
        }
        return EntityProperties(self, properties)

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_create_snapshots_completed_task_state
    # @matrix task-completion : asset-copy history
    # @pair signature:asset-copy
    def copy_assets(self, task):
        for name in list(getattr(task, "assets", {}).keys()):
            asset = task.get_asset(name)
            self.copy_asset(asset)

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_create_snapshots_completed_task_state
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_create_clones_another_task_and_existing_history
    # @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
    # @matrix task-combine : asset-copy attachments existing-history metadata schema-version source-snapshot
    # @matrix task-completion : asset-copy snapshot
    # @pair signature:asset-copy
    @classmethod
    def create(cls, task, overrides=None, *, source=None):
        overrides = dict(overrides or {})
        source = source or task
        history_key = overrides.pop("_key", None)
        new_history = cls(history_key, parent=task)
        if history_key is not None and new_history.key is None:
            new_history._key = history_key
        new_history.kind = cls.entity_kind
        new_history.task = task
        new_history.completed_on = overrides.get("completed_on", source.completed_on)
        new_history.completed_by = overrides.get("completed_by", source.completed_by)
        new_history.page = overrides.get("page", source.page)
        new_history.name = overrides.get("name", source.name)
        new_history.description = overrides.get("description", source.description)
        pages = [source.page] if source.page else []
        linked_pages = overrides.get(
            "linked_pages", pages + list(source.linked_pages or [])
        )
        new_history.linked_pages = linked_pages
        new_history.files = list(overrides.get("files", source.files) or [])

        form = overrides.get("form", source.form)
        if form:
            new_history.form = form
            source_version = getattr(source, "version", None)
            new_history.version = overrides.get(
                "version", source_version or form.version
            )

        if "submission" in overrides:
            submission = overrides.get("submission")
            if submission is not None:
                new_history.ai_submission(submission)
            else:
                new_history.submission = None
        else:
            new_history.submission = source.submission

        if "created" in overrides:
            new_history.created = overrides["created"]
        elif isinstance(source, cls):
            new_history.created = source.created
        elif source is not task:
            new_history.created = source.completed_on or source.modified

        if overrides.get("copy_assets", not overrides or source is not task):
            new_history.copy_assets(source)

        return new_history


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_save_records_schema_history_on_version_change
# @pair form:schema-history
class FormHistory(Entity):
    entity_kind = "form_history"

    @property
    def exclude_from_index(self):
        exclude = {
            "schema",
            "schema_format",
        }
        return frozenset(exclude)

    @property
    def hash(self):
        return None

    @property
    def required(self):
        return None

    @property
    def modified(self):
        return self.created

    @property
    def version(self):
        return self.db.get("schema_version")

    @version.setter
    def version(self, value):
        self.db["schema_version"] = value

    def _get_properties(self):
        properties = {
            "form": common_related.AttachedForm,
            "kind": common_entity.Kind,
            "schema": schema.Schema,
            "schema_format": schema.SchemaFormat,
        }
        return EntityProperties(self, properties)

    @classmethod
    def create(cls, form, previous_version):
        new_history = cls(parent=form)
        new_history.kind = cls.entity_kind
        new_history.form = form
        new_history.version = previous_version
        new_history.schema = form.properties.schema.previous

        return new_history


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_created_on_save
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_document_history_create_copies_document_asset
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_document_history_named_versions_order_and_delete_in_bounded_batches
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_document_history_named_version_rejects_invalid_name_or_content
# @matrix document-history : asset-copy asset-path batch-delete current-content legacy named ordering validation
# @matrix editor : history-list validation
class DocumentHistory(AssetMixin, Entity):
    entity_kind = "document_history"

    DOCUMENT_ASSET = "document"
    DELETE_BATCH_SIZE = 100
    MAX_NAME_LENGTH = 100

    @property
    def exclude_from_index(self):
        return frozenset({"assets"})

    @property
    def hash(self):
        return self.db.get("hash")

    @hash.setter
    def hash(self, value):
        self.db["hash"] = value

    @property
    def required(self):
        return None

    @property
    def modified(self):
        return self.created

    @property
    def pinned(self):
        return bool(self.name)

    @property
    def entry(self):
        return {
            "key": self.urlsafe_key,
            "name": self.name or None,
            "pinned": self.pinned,
            "created": self.created.isoformat() if self.created else None,
        }

    def _get_properties(self):
        properties = {
            "created": common_entity.Created,
            "kind": common_entity.Kind,
            "name": common_entity.Name,
        }
        return EntityProperties(self, properties)

    @classmethod
    def create(cls, entity, *, name=None, html=None):
        named = name is not None or html is not None
        if named:
            name = cls.validate_name(name)
            cls.validate_html(html)

        new_history = cls(parent=entity)
        new_history.kind = cls.entity_kind
        key_identity = new_history.urlsafe_key or str(new_history.key)
        new_history.hash = key_identity

        if named:
            new_history.name = name
            new_history.save_asset(html, cls.DOCUMENT_ASSET, "html")
            return new_history

        doc = entity.properties.document
        html_asset = entity.get_asset(doc.id)
        if not html_asset:
            return None

        new_history.copy_asset(html_asset, cls.DOCUMENT_ASSET)
        return new_history

    @classmethod
    def validate_name(cls, value):
        if not isinstance(value, str):
            raise ValidationError("Version name is required")

        name = strip_tags(value).strip()
        if not name:
            raise ValidationError("Version name is required")
        if len(name) > cls.MAX_NAME_LENGTH:
            raise ValidationError(
                f"Version name must be {cls.MAX_NAME_LENGTH} characters or fewer"
            )
        return name

    @staticmethod
    def validate_html(value):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Document content is required")

        text = strip_tags(value)
        markup = value.lower()
        meaningful_markup = any(
            tag in markup
            for tag in ("<img", "<video", "<audio", "<iframe", "<table", "<hr")
        )
        if not text and not meaningful_markup:
            raise ValidationError("Document content is required")
        return value

    @classmethod
    def ordered(cls, histories):
        def newest(history):
            return history.created or datetime.min.replace(tzinfo=timezone.utc)

        pinned = sorted(
            (history for history in histories if history.pinned),
            key=newest,
            reverse=True,
        )
        unpinned = sorted(
            (history for history in histories if not history.pinned),
            key=newest,
            reverse=True,
        )
        return pinned + unpinned

    @classmethod
    def delete_unpinned(cls, histories, *, batch_size=None, delete=None):
        from . import Entities

        delete = delete or Entities.delete
        batch_size = max(int(batch_size or cls.DELETE_BATCH_SIZE), 1)
        unpinned = [
            history
            for history in histories
            if isinstance(history, cls) and not history.pinned
        ]
        for start in range(0, len(unpinned), batch_size):
            delete(*unpinned[start : start + batch_size])
        return len(unpinned)
