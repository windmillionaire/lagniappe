"""Reviewed, attributed, append-only Page document changes."""

from datetime import datetime, timezone
from html import escape

from lagniappe.core import exceptions
from lagniappe.core.definitions import MutationIntent
from lagniappe.core.entities import Entities
from lagniappe.core.tools.cache.documents import document_write_lock
from lagniappe.core.tools.document_crdt import (
    append_fragment,
    load_document,
)
from lagniappe.core.tools.document_updates import (
    checkpointed_document,
    fresh_document,
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


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_preserves_content
# @matrix ai-report editor : document append retry
def prepare_document_append(action, report, user, created, record):
    page = _resolve_entity(
        _first_data_reference(_data(action), "page"), created, expected=Entities.PAGE
    )
    record["before"] = {"entity": _entity_result(page)}
    record["document_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_preserves_content
# @matrix ai-report editor : document append retry
# @matrix ai-report editor sync : document append browser-review persistence source-attribution
def _append_page_document(action, report, user, created, context):
    record = context["action_record"]
    page = _resolve_entity(
        _first_data_reference(_data(action), "page"), created, expected=Entities.PAGE
    )
    from lagniappe.core.definitions import Action
    if not page.allowed(Action.EDIT, user=user):
        raise exceptions.ValidationError("Document is unavailable or no longer editable.")
    with document_write_lock(page.properties.document.sync_id):
        document = page.properties.document
        receipt = load_document(document.ydoc)["lagniappeReports"].get(
            record["idempotency_key"]
        )
        if receipt:
            # This operation already committed. Later user edits are authoritative;
            # retry must not restore or duplicate the originally appended content.
            return page, [], {"document_after": receipt["signature"]}
        batch = context["batch"]
        first_append = page.key not in batch.documents
        if first_append:
            checkpointed_document(page)
            batch.add_document(page)
        addition = (
            document_source_quote(report, record["document_at"])
            + _data(action)["document"]
        )
        html = (document.html or "") + addition
        snapshot, receipt = append_fragment(
            document.ydoc, addition, record["idempotency_key"], html_after=html
        )
        if first_append and page.get_asset("document"):
            history = Entities.DOCUMENT_HISTORY.create(page)
            if history is None or history.get_asset("document") is None:
                raise exceptions.ValidationError("Could not preserve the document version; append stopped.")
            history.name = f"Before report append — {record['document_at']}"
            page.add_mutation_intents(
                MutationIntent.standard(history, reason="report-document-version")
            )
        document.save(html=html, ydoc=snapshot)
        return page, [], {"document_after": receipt["signature"]}


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_preserves_content
# @matrix ai-report editor : document append retry
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
    # The applied receipt is historical proof, not a guard on current content.
    # Reconcile a lost Report checkpoint without treating later user edits as drift.
    record.setdefault("document_after", receipt["signature"])
    return "applied"
