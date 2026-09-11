"""Reviewed, attributed, append-only Page document changes."""

import hashlib
from datetime import datetime, timezone
from html import escape

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, MutationIntent
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get, utility as database_utility
from lagniappe.core.tools.cache.documents import document_write_lock
from lagniappe.core.tools.document_crdt import (
    append_fragment,
    load_document,
    undo_fragment,
    document_structure,
)
from lagniappe.core.tools.document_updates import (
    checkpointed_document,
    fresh_document,
    save_checkpoint,
)

from .common import _data, _first_data_reference
from .references import _resolve_entity, _load_result_entity
from .results import _entity_result


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_source_quote_uses_trusted_origin
# @matrix agent-api email editor : document source-attribution
def document_source_quote(report, timestamp):
    origin = getattr(report, "origin", "web")
    source = {
        "web": "Application",
        "email": "Email",
        "api": "External API / skill",
    }.get(origin, "Application")
    if (
        origin == "api"
        and (getattr(report, "agent_manifest", None) or {}).get("source")
        == "remote_mcp"
    ):
        source = "Remote MCP"
    return f"<blockquote><p>{escape(timestamp)} · {source}</p></blockquote>"


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/documents.py::prepare_document_append
# @reason stable text/structure signature used by conservative document undo
def document_signature(document):
    return {
        "html": document.fingerprint,
        "structure": hashlib.sha256(
            document_structure(document.ydoc).encode()
        ).hexdigest(),
    }


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_and_undo_preserve_content
# @matrix ai-report editor : document append retry undo conflict
def prepare_document_append(action, report, user, created, record):
    page = _resolve_entity(
        _first_data_reference(_data(action), "page"), created, expected=Entities.PAGE
    )
    with document_write_lock(page.properties.document.sync_id):
        page = fresh_document(page, user)
        checkpointed_document(page)
        record["before"] = {
            "entity": _entity_result(page),
            "signature": document_signature(page.properties.document),
            "history_key": (
                database_get.urlsafe_key(database_utility.create_key("document_history", page))
                if page.get_asset("document") else None
            ),
        }
    record["document_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_and_undo_preserve_content
# @matrix ai-report editor : document append retry undo conflict
# @matrix ai-report editor sync : document append browser-review persistence source-attribution undo
def _append_page_document(action, report, user, created, context):
    record = context["action_record"]
    page = _resolve_entity(
        _first_data_reference(_data(action), "page"), created, expected=Entities.PAGE
    )
    with document_write_lock(page.properties.document.sync_id):
        page = fresh_document(page, user)
        document = page.properties.document
        receipt = load_document(document.ydoc)["lagniappeReports"].get(
            record["idempotency_key"]
        )
        if receipt:
            if receipt["state"] != "applied":
                raise exceptions.ValidationError(
                    "This document append has already been undone."
                )
            return page, [], {"document_after": receipt["signature"]}
        checkpointed_document(page)
        if document_signature(document) != record["before"]["signature"]:
            raise exceptions.ValidationError(
                "Document changed after preparation; recreate the append plan."
            )
        addition = (
            document_source_quote(report, record["document_at"])
            + _data(action)["document"]
        )
        html = (document.html or "") + addition
        snapshot, receipt = append_fragment(
            document.ydoc, addition, record["idempotency_key"], html_after=html
        )
        if record["before"]["history_key"]:
            history = Entities.DOCUMENT_HISTORY.create(
                page, key=database_get.datastore_key(record["before"]["history_key"])
            )
            if history is None or history.get_asset("document") is None:
                raise exceptions.ValidationError("Could not preserve the document version; append stopped.")
            history.name = f"Before report append — {record['document_at']}"
            page.add_mutation_intents(
                MutationIntent.standard(history, reason="report-document-version")
            )
        save_checkpoint(page, html=html, ydoc=snapshot)
        return page, [], {"document_after": receipt["signature"]}


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_and_undo_preserve_content
# @matrix ai-report editor : document append retry undo conflict
def inspect_document_append(record, user):
    page = _load_result_entity((record.get("before") or {}).get("entity"))
    if page is None:
        return "not-applied" if not record.get("prepared") else "drifted"
    try:
        page = fresh_document(page, user)
    except exceptions.ValidationError:
        return "drifted"
    receipt = load_document(page.properties.document.ydoc)["lagniappeReports"].get(
        record["idempotency_key"]
    )
    if not receipt:
        return "not-applied"
    if receipt["state"] != "applied":
        return "drifted"
    record["entity"] = _entity_result(page)
    # Reconcile a crash after the document committed but before the Report did.
    record.setdefault("document_after", receipt["signature"])
    return "applied"


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_and_undo_preserve_content
# @matrix ai-report editor : document append retry undo conflict
# @matrix ai-report editor sync : document append browser-review persistence source-attribution undo
def _undo_page_document(record, _report, user):
    page = _load_result_entity((record.get("before") or {}).get("entity"))
    if page is None:
        raise exceptions.ValidationError(
            "Document target is unavailable; undo stopped."
        )
    with document_write_lock(page.properties.document.sync_id):
        page = fresh_document(page, user)
        document = page.properties.document
        checkpointed_document(page)
        receipt = load_document(document.ydoc)["lagniappeReports"].get(
            record["idempotency_key"]
        )
        if receipt and receipt["state"] == "undone":
            return {
                "entity": _entity_result(page),
                "note": "Document append already undone.",
            }
        if not receipt or document_signature(document) != record.get("document_after"):
            raise exceptions.ValidationError(
                "Document changed after the append; undo stopped to preserve those edits."
            )
        html = ""
        history_key = record["before"]["history_key"]
        if history_key:
            history = Entities.fetch_one(history_key, request=Fetch.root())
            if (
                not isinstance(history, Entities.DOCUMENT_HISTORY)
                or history.key.parent != page.key
                or history.get_asset("document") is None
            ):
                raise exceptions.ValidationError("Saved document version is unavailable; undo stopped.")
            html = history.get_asset("document").get()
        snapshot = undo_fragment(document.ydoc, record["idempotency_key"])
        save_checkpoint(page, html=html, ydoc=snapshot)
        return {
            "entity": _entity_result(page),
            "note": "Removed the report's document addition.",
        }
