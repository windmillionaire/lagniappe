from flask import abort, request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.properties.activity import NOTE_VISIBILITIES
from lagniappe.core.tools import database
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import pages


# @testable true
# @tests tests_e2e/005_pages/test_005j_page_notes.py::test_page_notes_visibility_and_title_menu
# @matrix notes pages : attribute-gate
def _notes_enabled(page):
    if not page.has("notes"):
        abort(404)


# @testable true
# @tests tests_e2e/005_pages/test_005j_page_notes.py::test_page_notes_visibility_and_title_menu
# @matrix notes pages permissions : load owner private shared viewer
@pages.route("<key>/notes", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def get_notes(key, **kwargs):
    page = kwargs["entity"]
    _notes_enabled(page)

    loaded = Entities.fetch(
        *database.get.page_notes(page),
        request=Fetch.direct(),
    )
    notes = [
        note
        for note in loaded
        if isinstance(note, Entities.NOTE)
        and note.scope == "page"
        and note.allowed(Action.VIEW, user=current_user)
    ]
    return responses.page_notes(notes, page)


# @testable true
# @tests tests_e2e/005_pages/test_005j_page_notes.py::test_page_note_text_photo_and_delete_modal
# @matrix notes pages : body create photo scope validation visibility
@pages.route("<key>/notes", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def create_note(key, **kwargs):
    page = kwargs["entity"]
    _notes_enabled(page)

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
            "user": current_user,
            "body": body,
            "photo": photo if has_photo else None,
            "visibility": visibility,
            "scope": "page",
        }
    )
    Entities.save(note)
    return responses.new_note(note, surface="page")
