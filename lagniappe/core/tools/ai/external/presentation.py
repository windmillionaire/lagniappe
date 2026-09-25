"""External API presentation."""

from copy import deepcopy

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.report_contracts import MAX_PROPOSAL_ACTIONS as MAX_PROPOSAL_ACTIONS
from lagniappe.core.tools.database import get as database_get

from ..references import HASH_REFERENCE_REGEX, hash_reference
from .validation import _walk_strings


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_entity_links_use_the_site_origin_without_rewriting_evidence
# @pair agent-api:origin-validation
def absolute_entity_links(value, *, origin):
    """Qualify structured record links for clients outside the website."""
    if isinstance(value, dict):
        result = {
            key: absolute_entity_links(child, origin=origin)
            for key, child in value.items()
        }
        reference = result.get("hash")
        url = result.get("url")
        if (
            isinstance(reference, str)
            and HASH_REFERENCE_REGEX.fullmatch(reference)
            and isinstance(url, str)
            and url.startswith("/")
            and not url.startswith("//")
        ):
            result["url"] = f"{origin.rstrip('/')}{url}"
        return result
    if isinstance(value, list):
        return [absolute_entity_links(child, origin=origin) for child in value]
    if isinstance(value, tuple):
        return tuple(absolute_entity_links(child, origin=origin) for child in value)
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/external/presentation.py::public_plan_proposal
# @reason recursive projection is asserted through the public round-trip contract
def _replace_internal_references(value, replacements):
    if isinstance(value, dict):
        return {
            _replace_internal_references(
                key, replacements
            ): _replace_internal_references(
                child,
                replacements,
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_internal_references(child, replacements) for child in value]
    if not isinstance(value, str):
        return value
    for internal, public in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        value = value.replace(internal, public)
    return value


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_public_execution_receipt_rechecks_entity_visibility
# @pair agent-api:execution-receipt
def public_execution_receipt(report, user):
    """Expose bounded outcomes, never the recovery ledger or stale entity data."""
    result = getattr(report, "result", None)
    if not isinstance(result, dict):
        return None
    records = result.get("actions") or []
    records = records if isinstance(records, list) else []
    selected = [
        record for record in records[:MAX_PROPOSAL_ACTIONS] if isinstance(record, dict)
    ]
    identifiers = list(
        dict.fromkeys(
            entity["id"]
            for record in selected
            if isinstance(entity := record.get("entity"), dict)
            and isinstance(entity.get("id"), str)
            and entity["id"]
        )
    )
    entities = (
        {
            entity.urlsafe_key: entity
            for entity in Entities.fetch(
                *identifiers,
                request=Fetch.nested(
                    because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION
                ),
            )
            if entity and entity.allowed(Action.VIEW, user=user)
        }
        if identifiers
        else {}
    )
    actions = []
    for record in selected:
        action = {
            key: str(record[key])[:200]
            for key in ("id", "type", "status")
            if record.get(key) is not None
        }
        source = record.get("entity")
        if isinstance(source, dict):
            entity = entities.get(source.get("id"))
            action["entity"] = (
                {
                    "hash": hash_reference(entity),
                    "kind": entity.entity_kind,
                    "name": getattr(entity, "name", None),
                    "url": entity._ai_url() if getattr(entity, "url", None) else None,
                }
                if entity
                else None
            )
        for key in ("schema_updates",):
            changes = record.get(key)
            if isinstance(changes, dict):
                # Counts expose partial success without leaking field values,
                # private diagnostics, or stale target identities from the ledger.
                action[key] = {
                    status: len(rows)
                    if isinstance(rows := changes.get(status), list)
                    else 0
                    for status in ("applied", "skipped")
                }
        actions.append(action)
    return {
        "status": str(result.get("status") or report.status)[:40],
        "actions": actions,
        "returned_count": len(actions),
        "total_count": len(records),
        "has_more": len(records) > len(selected),
    }


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_public_plan_proposal_round_trips_hash_references_and_markdown
# @tests tests_unit/test_032_agent_api.py::test_public_plan_omits_preview_references_before_loading_entities
# @matrix agent-api ai-report : markdown public-reference round-trip stored-execution
def public_plan_proposal(report, user=None):
    """Project stored execution state back into the public submission contract."""
    proposal = getattr(report, "proposal", None)
    if not isinstance(proposal, dict):
        return proposal
    public = deepcopy(proposal)
    # Review snapshots can reference virtual entities that exist only during
    # preparation. They are private metadata, not workspace references to load.
    for action in public.get("actions") or []:
        action.pop("_schema_change", None)
        action.pop("_entity_update", None)
        data = action.get("data") if isinstance(action, dict) else None
        if isinstance(data, dict) and action.get("type") in {"create_page", "append_page_document"}:
            data.pop("document", None)
    public.pop("answer_html", None)
    if user is not None:
        from lagniappe.core.tools.forms import schema_updates as form_schema_updates

        for action in proposal.get("actions", []):
            if action.get("type") == "update_form_schema":
                for candidate in action.get("data", {}).get("conversions", []):
                    entity = Entities.fetch_one(
                        candidate["entity"], request=Fetch.direct()
                    )
                    form_schema_updates.require_visible(entity, user)

    manifest = getattr(report, "agent_manifest", None)
    replacements = {
        internal: public_reference
        for internal, public_reference in (
            (manifest or {}).get("public_references") or {}
        ).items()
        if isinstance(internal, str)
        and isinstance(public_reference, str)
        and HASH_REFERENCE_REGEX.fullmatch(public_reference)
    }
    identifiers = []
    for value in _walk_strings(public):
        if value not in replacements and database_get.is_urlsafe_key(value):
            identifiers.append(value)
    entities = (
        Entities.fetch(
            *list(dict.fromkeys(identifiers)),
            request=Fetch.direct(),
        )
        if identifiers
        else []
    )
    replacements.update(
        {
            entity.urlsafe_key: hash_reference(entity)
            for entity in entities
            if entity and hash_reference(entity)
        }
    )
    public = _replace_internal_references(public, replacements)

    return public
