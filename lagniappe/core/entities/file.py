from flask import url_for

from ..definitions import Action, MutationIntent
from ..mixins import AssetMixin
from ..properties import file_assets, file_entity, file_options, file_related, common_entity
from ..tools.auth.context import current_context_user
from .entity import Entity
from ..tools.auth.restrictions import permission_relation
from ..tools.auth.restrictions import prepare_permissions


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_records_metadata_before_asset_save
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_lists_pages_that_reference_it
# @tests tests_unit/test_006_file_properties.py::test_file_reverse_task_links_drive_permissions_and_references
# @matrix file : asset-lifecycle attached-pages attached-tasks badges permissions references reverse-links task-history upload
class File(AssetMixin, Entity):
    entity_kind = "file"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_report_file_is_searchable_only_after_workspace_attachment
    # @pairs ai-report:pre-execution files:search-visibility
    @property
    def searchable(self):
        """Keep report-only evidence out of workspace search until attachment."""
        return self.has_references

    @property
    def exclude_from_index(self):
        return frozenset({"summary", "options", "assets"})

    @property
    def required(self):
        owner = self.owner
        requirements = list(owner.requires) if owner else []
        if self.properties.task.key:
            requirements.append(owner.hash)
        return list(dict.fromkeys(h for h in [self.hash, "models", *requirements] if h))

    @property
    def owner(self):
        if self.properties.page.key and self.properties.task.key:
            raise ValueError("A File cannot belong to both a Page and a Task")
        if self.properties.page.key:
            return permission_relation(self, "page", required=True)
        return permission_relation(self, "task")

    @property
    def has_references(self):
        return bool(self.db.get("page") or self.db.get("task"))

    # @testable true
    # @tests tests_unit/test_009g_restriction_reconciliation.py::test_file_move_preserves_single_ownership
    # @tests tests_unit/test_009g_restriction_reconciliation.py::test_file_move_does_not_load_previous_task_attachments
    # @tests tests_unit/test_009g_restriction_reconciliation.py::test_file_move_does_not_load_destination_task_attachments
    # @matrix files : ownership move reverse-links unloaded-relation
    def move_to(self, owner):
        if getattr(owner, "entity_kind", None) not in {"page", "task"}:
            raise ValueError("A File must belong to a Page or a live Task")
        prepare_permissions(self, owner)
        previous = self.owner
        if previous and previous.key == owner.key:
            return False
        if previous and previous.entity_kind == "task":
            files = previous.properties.files
            if files.is_set:
                files.remove(self)
            else:
                previous.db["files"] = [key for key in files.keys if key != self.key]
                files._invalidate_projections()
            self.add_mutation_intents(
                MutationIntent.patch(previous, "files", reason="file-previous-task", depends_on=()),
                MutationIntent.touch(previous.page, reason="file-previous-task-page", depends_on=()),
            )
        if previous:
            self.add_mutation_intents(MutationIntent.touch(previous, reason="file-previous-owner", depends_on=()))
        self.page = None
        self.task = None
        if owner.entity_kind == "page":
            self.page = owner
        else:
            self.task = owner
            files = owner.properties.files
            if files.is_set or not files.keys:
                files.add(self)
            elif self.key not in files.keys:
                owner.db["files"] = [*files.keys, self.key]
                files._invalidate_projections()
            self.add_mutation_intents(MutationIntent.patch(owner, "files", reason="file-task-owner", depends_on=()))
        self.properties.requires.update()
        return True

    @property
    def url(self):
        return url_for("files.view", key=self.urlsafe_key)

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "name": file_entity.DisplayName,
                "filename": file_entity.Filename,
                "mimetype": file_entity.Mimetype,
                "encoding": file_entity.Encoding,
                "file": file_assets.FileAsset,
                "size": file_entity.Size,
                "large": file_entity.Large,
                "text": file_assets.TextAsset,
                "html": file_entity.AsHTML,
                "preview": file_entity.Preview,
                "summary": file_entity.Summary,
                "page": file_related.AttachedPage,
                "task": file_related.AttachedTask,
                "restricted_to": common_entity.RestrictedTo,
                "report_user": file_related.ReportUser,
                "extract": file_options.Extract,
                "summarize": file_options.Summarize,
                "options": file_options.Options,
            }
        )
        return properties

    def allowed(self, action, user=None):
        user = current_context_user(user)
        action = Action.EDIT if action.implies(Action.EDIT) else action

        owner = self.owner
        if owner:
            return owner.allowed(action, user=user)
        report_key = self.properties.report_user.key
        if report_key:
            return bool(user and user.is_authenticated and (
                getattr(user, "is_admin", False)
                or (action is Action.VIEW and report_key == user.key)
            ))
        return super().allowed(action, user=user)

    @classmethod
    def create(cls, page=None, upload=None, data=None, *, key=None, report_user=None):
        new_file = cls(key) if key is not None else cls()
        new_file.kind = cls.entity_kind

        if report_user:
            new_file.report_user = report_user

        if page:
            new_file.page = page

        if upload:
            new_file.filename = data.get("filename") or upload.filename
            new_file.mimetype = data.get("mimetype")
            new_file.file = upload

        if data:
            new_file.update(data)

        return new_file

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_description_form_field_populates_search_cache
    # @tests tests_unit/test_006_file_properties.py::test_file_update_preserves_processing_options_when_controls_absent
    # @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
    # @matrix file : cache deferred-dispatch description option-preservation
    def update(self, data):
        self.name = data.get("name") or data.get("display-name")
        self.summary = data.get("summary") or data.get("description")
        if "description" in data and "summary" not in data:
            self.properties.summarize.search = bool(self.summary)

        extract = self.properties.extract.update(data)
        summarize = self.properties.summarize.update(data)
        if extract and summarize:
            self.properties.extract.status = "Waiting for file summary..."
        self._pending_file_processing = (
            {
                "extract": extract,
                "summarize": summarize,
            }
            if extract or summarize
            else None
        )

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
    # @matrix deferred-jobs file : deferred-dispatch post-save-dispatch summary-first
    def dispatch_pending_processing(self):
        """Dispatch processing selected by the last update after persistence."""
        request = getattr(self, "_pending_file_processing", None)
        if not request:
            return None
        result = file_options.dispatch_file_processing(self, request)
        self._pending_file_processing = None
        return result
