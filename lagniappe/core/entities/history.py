from datetime import datetime, timezone
from copy import deepcopy

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
from ..tools.auth.restrictions import permission_relation
from ..tools.database.assets import cleanup_rejected_attempt, record_attempt_asset
from lagniappe.core.tools.forms import definitions as form_definitions
from ..tools.database import get as database_get


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
    def readonly(self):
        return True

    # @testable true
    # @tests tests_unit/test_009g_restriction_reconciliation.py::test_history_permissions_follow_live_task
    # @matrix permissions tasks : task-history live-task
    def allowed(self, action, user=None):
        return permission_relation(self, "task", required=True).allowed(action, user=user)

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
    def generation(self):
        return self.db.get("generation", 0) or 0

    @generation.setter
    def generation(self, value):
        self.db["generation"] = value

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
        try:
            for name in list(getattr(task, "assets", {}).keys()):
                asset = task.get_asset(name)
                copied = self.copy_asset(asset, isolated=True) if asset else None
                if not copied:
                    raise ValidationError("A saved answer attachment could not be preserved. Try reopening again.")
                record_attempt_asset(self, copied.definition)
        except Exception:
            cleanup_rejected_attempt(self)
            raise

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_create_snapshots_completed_task_state
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_create_clones_another_task_and_existing_history
    # @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
    # @matrix task-combine : asset-copy attachments existing-history metadata schema-version source-snapshot
    # @matrix task-completion : asset-copy snapshot
    # @matrix task-completion : history schema-version
    # @pair signature:asset-copy
    @classmethod
    def create(cls, task, overrides=None, *, source=None, submission_source="original"):
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
        explicit_answers = "submission" in overrides
        envelope = (
            form_definitions.completed_envelope(source)
            if submission_source == "original" else None
        )
        if envelope is not None and not explicit_answers and "form" not in overrides:
            form_key = source.properties.form.key
            if envelope.get("form_key") != database_get.urlsafe_key(form_key):
                form_key = database_get.datastore_key(envelope.get("form_key"))
            generation = envelope.get("generation", 0) or 0
            submission = envelope["submission"]
        else:
            form_key = form.key if "form" in overrides and form else source.properties.form.key
            generation = form.generation if explicit_answers and form else source.generation
            submission = overrides.get("submission", source.submission)
        if form_key:
            new_history.db["form"] = form_key
            if form is not None and form.key == form_key:
                new_history.form = form
        new_history.generation = overrides.get("generation", generation)
        if explicit_answers and submission is not None:
            new_history.ai_submission(submission)
        else:
            new_history.submission = submission

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
# @tests tests_unit/test_004f_form_drafts.py::test_archived_generation_preserves_schema_html_and_images
# @matrix form-schema html-field : history generation immutable-assets
class FormHistory(Entity, AssetMixin):
    entity_kind = "form_history"

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_definition_snapshot_requires_submitter_scoped_authorization
    # @matrix form-schema html-field : history permission-boundary
    def allowed(self, action, user=None):
        # An internal definition is not a standalone resource. Readers must
        # authorize the live Task/TaskHistory that selected this exact version.
        return False

    @property
    def exclude_from_index(self):
        exclude = {
            "schema",
            "schema_format",
            "assets",
            "source_asset_urls",
        }
        return frozenset(exclude)

    @property
    def hash(self):
        return short_hash(self.urlsafe_key) if self.key else None

    @property
    def form_type(self):
        return self.db.get("form_type")

    @property
    def content_available(self):
        return self.db.get("form_content_version") == 1

    @property
    def source_form_key(self):
        return self.db.get("form") or self.key.parent

    @property
    def fields(self):
        return self.properties.schema.fields

    @property
    def html_fields(self):
        return self.properties.schema.html_fields

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_archived_generation_preserves_schema_html_and_images
    # @matrix html-field : history immutable-assets
    def get_html_field(self, field_id):
        if not self.content_available:
            return None
        asset = self.get_asset(field_id)
        content = asset.html() if asset else None
        if not content:
            return content
        for name, source_url in self.db.get("source_asset_urls", {}).items():
            image = self.get_asset(name)
            if image and source_url:
                content = content.replace(source_url, image.url)
        return content

    @property
    def required(self):
        return None

    @property
    def modified(self):
        return self.created

    @property
    def generation(self):
        return self.db.get("generation", 0) or 0

    @generation.setter
    def generation(self, value):
        self.db["generation"] = value

    def _get_properties(self):
        properties = {
            "created": common_entity.Created,
            "name": common_entity.Name,
            "form": common_related.AttachedForm,
            "kind": common_entity.Kind,
            "schema": schema.Schema,
            "schema_format": schema.SchemaFormat,
        }
        return EntityProperties(self, properties)

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_form_history_create_copies_explicit_saved_definition_without_asset_copy
    # @matrix form-schema html-field : history content-version
    @classmethod
    def create(cls, source, previous_generation):
        """Build the old definition from the saved source supplied by Form Save."""
        history = cls(parent=source)
        history.kind = cls.entity_kind
        history.form = source
        history.generation = previous_generation
        history.schema = deepcopy(source.schema)
        history.schema_format = source.schema_format
        history.name = source.name
        history.created = datetime.now(timezone.utc)
        history.db["form_type"] = source.form_type
        if source.db.get("form_content_version") is not None:
            history.db["form_content_version"] = source.db["form_content_version"]
        return history


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_saves_do_not_create_automatic_history
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
    def create(cls, entity, *, name=None, html=None, key=None):
        named = name is not None or html is not None
        if named:
            name = cls.validate_name(name)
            cls.validate_html(html)

        new_history = cls(key, parent=entity)
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
