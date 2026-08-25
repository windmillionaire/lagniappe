from ..definitions import (
    Fetch,
    FetchReason,
)
from ..mixins import AssetMixin
from ..properties import common_related, file_assets, file_entity, file_ingress
from . import Entities
from .entity import Entity


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_project
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_category_and_form
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix ingress : model parent related-entities
class Ingress(AssetMixin, Entity):
    entity_kind = "ingress"

    @property
    def exclude_from_index(self):
        return frozenset({"workflow", "execution", "assets"})

    @property
    def required(self):
        return [self.hash, "site"]

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_category_and_form
    # @matrix category : parent related-entities
    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "mimetype": file_entity.Mimetype,
                "name": file_entity.DisplayName,
                "encoding": file_entity.Encoding,
                "file": file_assets.FileAsset,
                "text": file_assets.TextAsset,
                "rows": file_assets.Rows,
                "results": file_assets.Results,
                "filename": file_entity.Filename,
                "category": common_related.AttachedCategory,
                "project": common_related.AttachedProject,
                "model": common_related.AttachedModelTask,
                "form": common_related.AttachedForm,
                "stage": file_ingress.Stage,
                "process_csv": file_ingress.ProcessCSV,
                "choose_type": file_ingress.ChooseType,
                "choose_form": file_ingress.ChooseForm,
                "choose_parent": file_ingress.ChooseParent,
                "assign_columns": file_ingress.AssignColumns,
                "verify_import": file_ingress.VerifyImport,
                "importing": file_ingress.Importing,
                "completed": file_ingress.Completed,
            }
        )
        return properties

    @property
    def parent(self):
        return self.category or self.model or self.project

    @property
    def entity_type(self):
        return self.properties.choose_type.entity_type

    @parent.setter
    def parent(self, parent):
        if not parent:
            self.category = None
            self.model = None
            self.project = None
            self.form = None
            return
        if parent.kind == "project":
            self.project = parent
        elif parent.kind == "category":
            self.category = parent
            self.form = parent.form
        elif parent.kind == "model":
            self.model = parent
            self.project = parent.project
            self.form = parent.form

    def clear_form_stages(self):
        """Reset all stages after choose_form (when the form changes)."""
        self.properties.assign_columns.clear()
        self.properties.verify_import.clear()
        self.properties.importing.clear()
        self.properties.completed.clear()

    def _result_entity_id(self, result):
        entity = result.get("entity") if isinstance(result, dict) else None
        return entity.get("id") if isinstance(entity, dict) else None

    def _result_entity_ids(self):
        return [
            entity_id
            for entity_id in [self._result_entity_id(result) for result in self.results]
            if entity_id
        ]

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_ingress_results_remove_deleted_imported_entities
    # @matrix ingress : delete row-results
    def remove_results_for_entities(self, *entity_ids):
        entity_ids = {entity_id for entity_id in entity_ids if entity_id}
        if not entity_ids:
            return 0

        results = self.results
        kept = [
            result
            for result in results
            if self._result_entity_id(result) not in entity_ids
        ]
        removed = len(results) - len(kept)
        if not removed:
            return 0

        results[:] = kept
        self.properties.results.save()
        return removed

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_ingress_results_prune_missing_entities
    # @matrix ingress : delete reload row-results
    def prune_missing_results(self):
        result_ids = set(self._result_entity_ids())
        if not result_ids:
            return 0

        existing_ids = {
            entity.urlsafe_key
            for entity in Entities.fetch(*result_ids, request=Fetch.root())
            if entity
        }
        missing_ids = result_ids - existing_ids
        return self.remove_results_for_entities(*missing_ids)

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_ingress_delete_imported_entities_deletes_pages_and_tasks
    # @matrix ingress : bulk-delete delete row-results
    def delete_imported_entities(self):
        result_ids = self._result_entity_ids()
        if not result_ids:
            return 0

        imported = [
            entity
            for entity in Entities.fetch(
                *result_ids,
                request=Fetch.nested(
                    because=FetchReason.CASCADE_SAVE_REQUIREMENTS
                ),
            )
            if isinstance(entity, (Entities.PAGE, Entities.TASK))
        ]
        deleted_ids = {entity.urlsafe_key for entity in imported}
        if not imported:
            return 0

        Entities.delete(*imported)
        self.remove_results_for_entities(*deleted_ids)
        return len(imported)

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_ingress_rejects_oversized_csv_before_read
    # @tests tests_unit/test_006b_ingress_entity.py::test_import_wizard_story_parses_the_uploaded_csv_into_rows_and_columns
    # @matrix ingress : rows size-limit
    @classmethod
    def create(cls, upload):
        from ..tools.ingress import IngressService

        return IngressService.create(upload, entity_cls=cls)
