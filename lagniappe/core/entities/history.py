from datetime import datetime, timezone
from copy import deepcopy
import json
from uuid import uuid4

from google.cloud import datastore

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
from ..tools.database import assets as storage_assets
from ..tools.database.assets import cleanup_rejected_attempt, record_attempt_asset
from ..tools.form_definitions import _snapshot_key
from ..tools import form_definitions


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

    # @testable false
    # @covered-by lagniappe/core/tools/form_definitions.py::validate_completion_write
    # @reason capture serialized identity only when raw data is actually accessed
    @property
    def db(self):
        raw = Entity.db.fget(self)
        if "_completion_identity" not in self.__dict__:
            form_definitions.capture_completion_identity(self, raw)
        return raw

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
    def create(cls, task, overrides=None, *, source=None):
        overrides = dict(overrides or {})
        source = source or task
        history_key = overrides.pop("_key", None)
        new_history = cls(history_key, parent=task)
        if history_key is not None and new_history.key is None:
            new_history._key = history_key
        new_history._definition_create_guard = (new_history.key, None)
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

        # Archive serialized originals, even if a caller edited the parsed
        # answer dictionary in memory while viewing the completed Task.
        envelope = form_definitions.completed_envelope(source, refresh=True)
        if envelope is not None and "form" not in overrides and "submission" not in overrides:
            form_key, version = form_definitions.definition_identity(source)
            if form_key:
                new_history.db["form"] = form_key
                if source.form is not None and source.form.key == form_key:
                    new_history.form = source.form
            new_history.version = version
        else:
            form = overrides.get("form", source.form)
            if form:
                new_history.form = form
                source_version = getattr(source, "schema_version", None)
                snapshot = None
                if "submission" in overrides or (source.entity_kind != "task_history" and not source.completed):
                    snapshot = form.snapshot_for_completion()
                    source_version = snapshot.version
                new_history.version = overrides.get("version", source_version)
                if snapshot is not None and snapshot.version == new_history.version:
                    new_history._submission_definition = (
                        (new_history.properties.form.key, new_history.version),
                        form_definitions.SubmissionDefinition(snapshot, snapshot.version, True),
                    )
            elif source.properties.form.key:
                new_history.db["form"] = source.properties.form.key
                new_history.version = source.schema_version

        if "submission" in overrides:
            submission = overrides.get("submission")
            if submission is not None:
                new_history.ai_submission(submission)
            else:
                new_history.submission = None
        else:
            new_history.submission = source.submission
            cached = getattr(source, "_submission_definition", None)
            if cached and cached[0] == (new_history.properties.form.key, new_history.version):
                new_history._submission_definition = cached

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
    # @tests tests_unit/test_004f_form_drafts.py::test_history_snapshot_owns_original_assets_and_marks_legacy_content_unknown
    # @matrix html-field : history immutable-assets missing-content
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

    # @testable true
    # @tests tests_unit/test_004f_form_drafts.py::test_history_snapshot_owns_original_assets_and_marks_legacy_content_unknown
    # @matrix form-schema html-field : history immutable-assets content-version
    @classmethod
    def snapshot(cls, form, version, *, content_available, copy_content=True, on_asset=None):
        """Prepare a version snapshot with independent, attempt-isolated assets."""
        history = cls(_snapshot_key(form.key, version))
        # A new snapshot's key is complete; seed its row without a lazy lookup.
        history._db = datastore.Entity(key=history.key)
        history._db.update({
            "type": "form_history", "form": form.key, "schema_version": version,
            "schema": deepcopy(form.schema), "schema_format": form.db.get("schema_format"),
            "form_type": form.form_type,
            "name": form.name, "created": datetime.now(timezone.utc),
        })
        history._definition_create_guard = (history.key, None)
        if not content_available:
            return history
        history.db["form_content_version"] = 1
        history.db["source_asset_urls"] = {}
        if not copy_content:
            return history
        html_ids = {field["id"] for field in form.schema if field.get("type") == "html"}
        attempt = uuid4().hex
        for name, definition in form.assets.items():
            if name not in html_ids and not any(name.startswith(f"image_{field_id}_") for field_id in html_ids):
                continue
            asset = form.get_asset(name)
            destination = f"{history.hash}_{attempt}_{name}.{asset.extension}"
            blob = storage_assets.copy_file(
                asset.path, asset.visibility.value, destination, "private",
                **({"source_generation": asset.generation} if asset.generation else {}),
            )
            if not blob:
                raise ValidationError("Could not preserve the Form's original content.")
            copied = deepcopy(definition)
            copied["path"] = destination
            copied.pop("visibility", None)
            if getattr(blob, "generation", None) is not None:
                copied["generation"] = str(blob.generation)
            history.assets[name] = copied
            record_attempt_asset(history, copied)
            if on_asset is not None:
                on_asset(copied)
            if definition.get("type") == "image":
                history.db["source_asset_urls"][name] = asset.url
        history.db["assets"] = json.dumps(history.assets)
        return history

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
            "created": common_entity.Created,
            "name": common_entity.Name,
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
