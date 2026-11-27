from typing import TYPE_CHECKING, Self, TypedDict, cast

from flask import url_for

from ..definitions import Action, MutationIntent
from ..definitions.fingerprints import restricted_fingerprint
from ..mixins import AssetMixin
from ..properties import file_assets, file_entity, file_options, file_related, common_entity
from ..tools.auth.context import current_context_user
from ..tools.files.constants import ARTIFACT_MIMETYPE
from .entity import Entity, EntityProperties
from ..tools.auth.restrictions import permission_relation


if TYPE_CHECKING:
    from collections.abc import Mapping
    from google.cloud.datastore import Key
    from werkzeug.datastructures import FileStorage
    from ..definitions.asset import FileAsset as StoredFile
    from ..mixins.field_host import FieldUser
    from ..tools.database.assets import DirectUploadFile
    from ..tools.files.html import SafeHTML
    from .user import User
    from . import property_types
    from .page import Page
    from .task import Task


FileData = TypedDict(
    "FileData",
    {
        "name": str | None,
        "display-name": str | None,
        "filename": str | None,
        "mimetype": str | None,
        "summary": str | None,
        "description": str | None,
        "enable-extract": object,
        "extract": object,
        "search-text": object,
        "enable-summarize": object,
        "summarize": object,
        "search-summary": object,
    },
    total=False,
)


class File(AssetMixin, Entity):
    if TYPE_CHECKING:
        @property
        def restricted_to(self) -> dict[str, list[str]]: ...

        encoding: str | None
        filename: str | None
        @property
        def mimetype(self) -> str: ...
        @mimetype.setter
        def mimetype(self, value: str | None) -> None: ...

        @property
        def file(self) -> StoredFile | None: ...
        @file.setter
        def file(self, value: FileStorage | DirectUploadFile) -> None: ...

        @property
        def text(self) -> bool | None: ...
        @text.setter
        def text(self, value: str | None) -> None: ...

        size: int | None
        large: bool | None
        html: SafeHTML | None
        preview: str | None
        summary: str | None
        task_page: Page | None
        report_user: User | None
        _pending_file_processing: file_options.ProcessingRequest | None

        page: Page | None
        task: Task | None

        @property
        def properties(self) -> property_types.FileProperties: ...

    entity_kind = "file"

    @property
    def is_artifact(self) -> bool:
        return self.mimetype == ARTIFACT_MIMETYPE

    @property
    def searchable(self) -> bool:
        """Keep staged uploads out of workspace search until attachment."""
        return self.has_references

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"summary", "options", "assets", "task_page"})

    @property
    def required(self) -> list[str]:
        owner = self.owner
        requirements = list(owner.requires) if owner else []
        if owner is not None and self.properties.task.key:
            requirements.append(owner.hash)
        return list(dict.fromkeys(h for h in [self.hash, "models", *requirements] if h))

    @property
    def owner(self) -> Page | Task | None:
        if self.properties.task.key:
            return cast("Task", permission_relation(self, "task", required=True))
        return cast("Page | None", permission_relation(self, "page"))

    @property
    def fingerprint(self) -> str:
        return restricted_fingerprint(super().fingerprint, self.restricted_to)

    def normalize_owner(self) -> None:
        """Keep direct ownership separate from the primary Task's Page."""
        if self.properties.task.key:
            task = cast("Task", permission_relation(self, "task", required=True))
            self.page = None
            self.task_page = cast("Page", permission_relation(task, "page", required=True))
        else:
            self.task_page = None
        self.properties.requires.unset()
        self.properties.restricted_to.unset()
        self._details = None
        self._to_cache = None

    @property
    def has_references(self) -> bool:
        return bool(self.db.get("page") or self.db.get("task"))

    def move_to(self, owner: Page | Task) -> bool:
        if getattr(owner, "entity_kind", None) not in {"page", "task"}:
            raise ValueError("A File must belong to a Page or a live Task")
        previous = self.owner
        if previous and previous.key == owner.key:
            return False
        if previous and previous.entity_kind == "task":
            previous = cast("Task", previous)
            files = previous.properties.files
            if files.is_set:
                files.remove(self)
            else:
                previous.db["files"] = [key for key in files.keys if key != self.key]
                files._invalidate_projections()
            self.add_mutation_intents(
                MutationIntent.patch(previous, "files", reason="file-previous-task", depends_on=()),
            )
            if previous.page is not None:
                self.add_mutation_intents(
                    MutationIntent.touch(previous.page, reason="file-previous-task-page", depends_on=()),
                )
        if previous:
            self.add_mutation_intents(MutationIntent.touch(previous, reason="file-previous-owner", depends_on=()))
        self.page = None
        self.task = None
        if owner.entity_kind == "page":
            self.page = cast("Page", owner)
        else:
            owner = cast("Task", owner)
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
    def url(self) -> str:
        return url_for("files.view", key=self.urlsafe_key)

    def _get_properties(self) -> EntityProperties:
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
                "task_page": file_related.TaskPage,
                "restricted_to": common_entity.RestrictedTo,
                "report_user": file_related.ReportUser,
                "extract": file_options.Extract,
                "summarize": file_options.Summarize,
                "options": file_options.Options,
            }
        )
        return properties

    def allowed(self, action: Action, user: FieldUser = None) -> bool:
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
        return bool(user and user.is_authenticated and getattr(user, "is_admin", False))

    @classmethod
    def create(
        cls, page: Page | None = None, upload: FileStorage | DirectUploadFile | None = None,
        data: FileData | Mapping[str, str | None] | None = None, *,
        key: Key | None = None, report_user: User | None = None,
    ) -> Self:
        new_file = cls(key) if key is not None else cls()
        new_file.kind = cls.entity_kind

        if report_user:
            new_file.report_user = report_user

        if page:
            new_file.page = page

        if upload:
            new_file.filename = (data.get("filename") if data else None) or upload.filename
            new_file.mimetype = data.get("mimetype") if data else None
            new_file.file = upload

        if data:
            new_file.update(data)

        return new_file

    def update(self, data: FileData | Mapping[str, str | None]) -> None:
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

    def dispatch_pending_processing(self, *, actor: User) -> file_options.Extract | file_options.Summarize | None:
        """Dispatch processing selected by the last update after persistence."""
        request = getattr(self, "_pending_file_processing", None)
        if not request:
            return None
        result = file_options.dispatch_file_processing(self, request, actor=actor)
        self._pending_file_processing = None
        return result
