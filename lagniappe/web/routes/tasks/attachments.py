"""Browser routes and submitted-file handling for task attachments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any, Unpack

    from flask import Request
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
    from lagniappe.web.auth import EntityContext

import json

from flask import request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools.auth.references import UNAVAILABLE_REFERENCE_ERROR
from lagniappe.core.tools.auth.task_attachments import (
    sign_task_attachment_claim,
    valid_task_attachment_claim,
)
from lagniappe.web import direct_uploads, responses
from lagniappe.web.auth import (
    abort_public_user_action,
    authenticated_user,
    load_route_entity,
    permission,
)

from . import tasks


def submitted_assets(request: Request) -> dict[str, object] | None:
    """Read the assets field, preserving the distinction between omitted and empty."""
    raw_assets = request.form.get("assets")
    if raw_assets is None:
        return None

    try:
        assets = json.loads(raw_assets or "{}")
    except json.JSONDecodeError as error:
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR) from error

    if not isinstance(assets, dict):
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR)
    return assets


def file_keys(assets: dict[str, object] | None) -> list[Any]:
    """Collect raw file identifiers in form order for the shared reference lookup."""
    if assets is None:
        return []

    keys = []
    for definition in assets.values():
        if not isinstance(definition, dict):
            continue

        file_key = definition.get("key") or definition.get("id")
        if file_key:
            keys.append(file_key)

    return keys


def _add_file_to_assets(assets, file, *, attachment_claim=None):
    assets = dict(assets or {})
    details = dict(file.details)
    if attachment_claim:
        details["attachment_claim"] = attachment_claim
    assets[file.filename or file.name or file.hash] = details
    return assets


def _asset_claims(assets, file_key):
    return [
        definition.get("attachment_claim")
        for definition in (assets or {}).values()
        if isinstance(definition, dict)
        and (definition.get("key") or definition.get("id")) == file_key
        and definition.get("attachment_claim")
    ]


def _remove_file_from_assets(assets, file_key):
    return {
        name: definition
        for name, definition in (assets or {}).items()
        if not isinstance(definition, dict)
        or (definition.get("key") or definition.get("id")) != file_key
    }


def _create_task_file():
    uploaded_file = request.files.get("task-file") or direct_uploads.direct_upload_file(
        "task-file"
    )
    if not uploaded_file:
        return None

    data = {
        "filename": uploaded_file.filename,
        "mimetype": request.form.get("mimetype"),
    }
    file = Entities.FILE().create(
        upload=uploaded_file,
        data=data,
        report_user=authenticated_user(),
    )
    file.save()
    return file


def resolve_files(
    resolver: SubmittedReferenceResolver,
    submitted_keys: Iterable[object],
    *,
    assets: dict[str, object],
    page: models.Page,
    task: models.Task | None,
) -> list[models.File]:
    """Resolve submitted attachments and retain existing files hidden from the editor."""
    existing_files = list(task.files) if task else []
    scope = task or page

    def file_authorized(file: models.File) -> bool:
        return (
            file.has_references and file.allowed(Action.VIEW, user=current_user)
        ) or any(
            valid_task_attachment_claim(
                claim,
                actor=authenticated_user(),
                file=file,
                scope=scope,
            )
            for claim in _asset_claims(assets, file.urlsafe_key)
        )

    selected_files = resolver.many(
        submitted_keys,
        expected=Entities.FILE,
        existing=existing_files,
        authorize=file_authorized,
    )
    selected_keys = {file.key for file in selected_files}
    preserved_files = [
        file
        for file in existing_files
        if file.key not in selected_keys
        and not file.allowed(Action.VIEW, user=current_user)
    ]
    return [*selected_files, *preserved_files]


@tasks.route("<key>/upload-file", methods=["POST"])
@permission(requested=Action.EDIT)
def upload_file(
    key: str, **kwargs: Unpack[EntityContext[Entity]]
) -> ResponseReturnValue:
    abort_public_user_action()

    try:
        existing_assets = submitted_assets(request)
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    file = _create_task_file()
    if not file:
        return responses.error("No file uploaded")

    scope = kwargs["entity"]
    attachment_claim = sign_task_attachment_claim(
        actor=authenticated_user(),
        file=file,
        scope=scope,
    )
    assets = _add_file_to_assets(
        existing_assets,
        file,
        attachment_claim=attachment_claim,
    )
    details = dict(file.details)
    details["attachment_claim"] = attachment_claim

    return responses.json_response({"assets": assets, "file": details})


@tasks.route("<key>/upload-file/direct-upload", methods=["POST"])
@permission(requested=Action.EDIT)
def upload_file_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    abort_public_user_action()

    return direct_uploads.direct_upload_response()


def _delete_file_if_unreferenced(file):
    if file and not file.has_references:
        Entities.delete(file)


@tasks.route("<key>/files/<file_key>", methods=["DELETE"])
@permission(Resource.TASK, Action.EDIT)
def delete_file(
    key: str, file_key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    file = Entities.fetch_one(
        file_key,
        request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
    )
    if (
        not isinstance(file, Entities.FILE)
        or file.key not in task.properties.files.keys
        or not file.allowed(Action.VIEW, user=current_user)
    ):
        return responses.not_found("File not found")

    try:
        assets = submitted_assets(request) or task.properties.files.preload
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    assets = _remove_file_from_assets(assets, file.urlsafe_key)
    task.properties.files.remove(file)
    task.save()
    _delete_file_if_unreferenced(file)

    return responses.entity_response(
        responses.json_response(
            {
                "assets": assets,
                "deleted": file.details,
            }
        ),
        task,
        task.page,
    )
