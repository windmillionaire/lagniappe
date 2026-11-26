from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from flask import g, request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.properties.activity import NOTE_VISIBILITIES
from lagniappe.core.tools.database import get as database_get
from lagniappe.web import responses
from lagniappe.web.auth import authenticated_user, permission

from . import pages


@pages.route("<key>/notes", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def get_notes(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    rows = database_get.page_notes(page)
    if not rows:
        page.remember_empty_notes()
        return responses.page_notes([], page)
    if g.get("experiments_variant") != "page-notes:control":
        viewer = authenticated_user()
        known = {entity.key: entity for entity in (page, viewer) if entity.key is not None}
        notes_to_load = [Entities.NOTE(row) for row in rows]
        for note in notes_to_load:
            note.attach(known, resolved_keys=known)
    else:
        notes_to_load = rows
    loaded = Entities.fetch(*notes_to_load, request=Fetch.direct())
    notes = [
        note
        for note in loaded
        if isinstance(note, Entities.NOTE)
        and note.scope == "page"
        and note.allowed(Action.VIEW, user=current_user)
    ]
    return responses.page_notes(notes, page)


@pages.route("<key>/notes", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def create_note(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    body = (request.form.get("body") or "").strip()
    photo = request.files.get("note-file")
    has_photo = bool(photo and getattr(photo, "filename", None))
    if not body and not has_photo:
        return responses.error("Add a note before saving.")

    visibility = request.form.get("visibility") or "private"
    if visibility not in NOTE_VISIBILITIES:
        return responses.error("Choose who can see this note.")

    note = Entities.NOTE.create(
        {
            "parent": page,
            "user": authenticated_user(),
            "body": body,
            "photo": photo if has_photo else None,
            "visibility": visibility,
            "scope": "page",
        }
    )
    Entities.save(note)
    return responses.new_note(note, surface="page")
