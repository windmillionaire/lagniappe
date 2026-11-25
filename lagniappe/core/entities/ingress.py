from typing import TYPE_CHECKING, Any, cast

from ..definitions import (
    Fetch,
    FetchReason,
)
from ..mixins import AssetMixin
from ..properties import common_related, file_assets, file_entity, file_ingress
from . import Entities
from .entity import Entity


if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage
    from ..tools.database.assets import DirectUploadFile
    from . import property_types
    from .category import Category
    from .project import Project
    from .form import Form
    from .model_task import ModelTask


class Ingress(AssetMixin, Entity):
    if TYPE_CHECKING:
        form: Form | None
        category: Category | None
        project: Project | None
        model: ModelTask | None
        filename: str | None
        encoding: str | None
        results: list[dict[str, Any] | None]
        mimetype: str | None

        @property
        def properties(self) -> property_types.IngressProperties: ...

    entity_kind = "ingress"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"workflow", "execution", "assets"})

    @property
    def required(self) -> list[str]:
        return [self.hash, "site"]

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
    def parent(self) -> Category | ModelTask | Project | None:
        return self.category or self.model or self.project

    @property
    def entity_type(self) -> str | None:
        return self.properties.choose_type.entity_type

    @parent.setter
    def parent(self, parent: Category | ModelTask | Project | None) -> None:
        if not parent:
            self.category = None
            self.model = None
            self.project = None
            self.form = None
            return
        if parent.kind == "project":
            self.project = cast("Project", parent)
        elif parent.kind == "category":
            self.category = cast("Category", parent)
            self.form = cast("ModelTask | Category", parent).form
        elif parent.kind == "model":
            self.model = cast("ModelTask", parent)
            self.project = cast("ModelTask", parent).project
            self.form = cast("ModelTask | Category", parent).form

    def clear_form_stages(self) -> None:
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

    def remove_results_for_entities(self, *entity_ids: str | None) -> int:
        removed_ids = {entity_id for entity_id in entity_ids if entity_id}
        if not removed_ids:
            return 0

        results = self.results
        kept = [
            result
            for result in results
            if self._result_entity_id(result) not in removed_ids
        ]
        removed = len(results) - len(kept)
        if not removed:
            return 0

        results[:] = kept
        self.properties.results.save()
        return removed

    def prune_missing_results(self) -> int:
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

    def delete_imported_entities(self) -> int:
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

    @classmethod
    def create(cls, upload: FileStorage | DirectUploadFile) -> Ingress:
        from ..tools.ingress import IngressService

        return IngressService.create(upload, entity_cls=cls)
