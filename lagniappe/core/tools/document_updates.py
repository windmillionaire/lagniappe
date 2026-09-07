"""Guarded durable document checkpoints shared by reviewed appends and sync."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.cache import documents
from lagniappe.core.tools.document_crdt import document_state


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_requires_a_checkpointed_collaborative_baseline
# @matrix editor sync : document append checkpoint conflict
def document_seed(entity):
    document = entity.properties.document
    return {
        "ydoc": document.ydoc,
        "fingerprint": document.fingerprint,
        "markup": document.html if not document.ydoc else None,
    }


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_fresh_document_rechecks_current_permissions
# @matrix editor sync : document permissions fresh-read
def fresh_document(entity, user):
    current = Entities.fetch_one(entity.key, request=Fetch.direct())
    if current is None or not current.allowed(Action.EDIT, user=user):
        raise exceptions.ValidationError(
            "Document is unavailable or no longer editable."
        )
    return current


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_requires_a_checkpointed_collaborative_baseline
# @matrix editor sync : document append checkpoint conflict
def checkpointed_document(entity):
    seed = document_seed(entity)
    state = documents.current_document_state(
        entity.properties.document.sync_id, seed=seed
    )
    if seed["markup"]:
        raise exceptions.ValidationError(
            "Open and save this document once to initialize its collaborative state, then retry."
        )
    if state.get("updates") or document_state(state.get("ydoc")) != document_state(
        seed.get("ydoc")
    ):
        raise exceptions.ValidationError(
            "Document has unsaved collaborative edits; wait for them to sync and retry."
        )
    return seed


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_checkpoint_persists_before_publishing_and_guards_assets
# @matrix mutations sync : document append guarded-checkpoint durable-first
def save_checkpoint(entity, *, html, ydoc, advance_parent=True, publish=True):
    expected = {"assets": entity.db.get("assets")}
    entity.properties.document.save(html=html, ydoc=ydoc)
    outcome = Entities.save_document_checkpoint(
        entity, advance_parent=advance_parent, expected_state=expected
    )
    if publish:
        documents.publish_document_checkpoint(
            entity.properties.document.sync_id, seed=document_seed(entity)
        )
    return outcome
