from flask import url_for

from ..definitions import Action
from ..mixins import AssetMixin
from ..properties import file_assets, file_entity, file_options, file_related
from ..tools.auth.context import current_context_user
from .entity import Entity


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_records_metadata_before_asset_save
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_lists_pages_that_reference_it
# @matrix file : asset-lifecycle attached-pages permissions upload
class File(AssetMixin, Entity):
    entity_kind = "file"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_report_file_is_searchable_only_after_workspace_attachment
    # @pairs ai-report:pre-execution files:search-visibility
    @property
    def searchable(self):
        """Keep report-only evidence out of workspace search until attachment."""
        return not self.properties.report_user.exists or self.has_references

    @property
    def exclude_from_index(self):
        return frozenset({"summary", "options", "assets"})

    @property
    def required(self):
        page_requirements = [r for page in self.pages for r in page.requires]
        task_requirements = [r for task in self.tasks for r in task.requires]
        requirements = page_requirements + task_requirements
        return list([h for h in set([self.hash, "models"] + requirements) if h])

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_reverse_task_links_drive_permissions_and_references
    # @matrix file : attached-tasks badges reverse-links task-history
    @property
    def linked_tasks(self):
        tasks = []
        seen = set()
        for linked in self.tasks:
            task = (
                linked.task
                if getattr(linked, "entity_kind", None) == "task_history"
                else linked
            )
            if not task or getattr(task, "entity_kind", None) != "task":
                continue
            key = getattr(task, "key", None)
            if key in seen:
                continue
            seen.add(key)
            tasks.append(task)
        return tasks

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_reverse_task_links_drive_permissions_and_references
    # @pair file:references
    @property
    def has_references(self):
        return bool(self.db.get("pages") or self.db.get("tasks"))

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
                "pages": file_related.AttachedToPages,
                "tasks": file_related.AttachedToTasks,
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

        report_user = self.properties.report_user.value
        if (
            action is Action.VIEW
            and user
            and getattr(user, "is_authenticated", False)
            and report_user
            and report_user.key == user.key
        ):
            return True

        return super().allowed(action, user=user)

    @classmethod
    def create(cls, page=None, upload=None, data=None, *, key=None, report_user=None):
        new_file = cls(key) if key is not None else cls()
        new_file.kind = cls.entity_kind

        if report_user:
            new_file.report_user = report_user

        if page:
            new_file.properties.pages.add(page)

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
