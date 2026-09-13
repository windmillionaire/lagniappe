"""Server-owned preparation and review of report schema-change actions."""

from copy import deepcopy
import json

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools import (
    form_conversions,
    form_drafts,
    form_schema_updates as updates,
)


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_report_schema_preparation_binds_impact_and_external_candidates
# @matrix ai-report form-migration : preview preparation approval external
def prepare_schema_updates(proposal, user, *, external=False, verify=False):
    """Bind existing Form edits to complete impact before the report is reviewed."""
    if not any(
        action.get("type") == "update_form_schema"
        for action in proposal.get("actions", [])
    ):
        return proposal
    virtual, seen, schema_actions = {}, set(), {}
    for action in proposal.get("actions", []):
        data = action.get("data") or {}
        if action.get("type") == "create_form":
            virtual[action.get("id")] = deepcopy(data)
        if action.get("type") != "update_form_schema" or action.get("skip"):
            continue
        reference = data.get("form_action") or data.get("form")
        if reference in virtual:
            source = virtual[reference]
            target = updates.apply_operations(
                source["schema"], data["operations"], source["form_type"]
            )
            if form_conversions.classify_changes(source["schema"], target):
                raise ValidationError(
                    "Define the final schema in create_form instead of converting a Form created by this plan."
                )
            source["schema"] = target
            if not verify:
                action.pop("_schema_change", None)
            continue
        form = Entities.fetch_one(reference, request=Fetch.direct())
        if (
            not isinstance(form, Entities.FORM)
            or not form.allowed(Action.EDIT, user=user)
            or form.reserved
        ):
            raise ValidationError("You do not have permission to update this Form.")
        if form.key in seen:
            raise ValidationError(
                "Combine changes to the same Form into one update_form_schema action."
            )
        seen.add(form.key)
        if form.db.get("pending_form_change"):
            raise ValidationError(
                "This Form is already being updated. Wait for it to finish."
            )
        target = updates.apply_operations(
            form.schema, data["operations"], form.form_type
        )
        changes = form_conversions.classify_changes(form.schema, target)
        baseline = form_drafts.builder_draft(form)["baseline"]
        if (verify or data.get("baseline")) and data.get("baseline") != baseline:
            raise ValidationError(updates.STALE_MESSAGE)
        scope = updates.inspect_scope(form, changes, user)
        if (verify or (external and changes)) and data.get(
            "scope_fingerprint"
        ) != scope["scope_fingerprint"]:
            raise ValidationError(
                updates.STALE_MESSAGE + " Use preview_form_schema_update first."
            )
        if external:
            updates.validate_candidates(data.get("conversions", []), scope, changes)
        elif data.get("conversions"):
            raise ValidationError(
                "On-site proposals specify conversion instructions; the worker prepares values after approval."
            )
        ai_fields = {item["id"] for item in changes if item["rule"] == "ai"}
        instructions = data.get("conversion_instructions") or {}
        if (
            not isinstance(instructions, dict)
            or set(instructions) - ai_fields
            or any(
                not isinstance(value, str) or len(value) > 4000
                for value in instructions.values()
            )
        ):
            raise ValidationError(
                "Conversion instructions must name AI-converted fields and contain at most 4000 characters each."
            )
        if not verify:
            data["baseline"] = baseline
            data["scope_fingerprint"] = scope["scope_fingerprint"]
            action["_schema_change"] = {
                "form": form.urlsafe_key,
                "generation": form.generation,
                "migration": bool(changes),
                "changes": changes,
                "review": _operation_review(
                    form.schema, target, data["operations"], instructions
                ),
                "impact": [
                    {
                        "id": item["id"],
                        "kind": item["kind"],
                        "fields": [
                            {
                                key: field[key]
                                for key in ("schema_id", "title", "rule", "reason")
                            }
                            for field in item["fields"]
                        ],
                    }
                    for item in scope["instances"]
                ],
                "total": scope["total"],
            }
        schema_actions[form.urlsafe_key] = action
    if not verify:
        _bind_dependencies(proposal, schema_actions)
    if len(json.dumps(proposal, ensure_ascii=False).encode()) > 750 * 1024:
        raise ValidationError(
            "This schema proposal is too large to retain safely with its execution state. Use the on-site builder for this change."
        )
    return proposal


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/schema_updates.py::prepare_schema_updates
# @reason human review describes schema changes without exposing provider or storage details
def _operation_review(source, target, operations, instructions):
    before = {field["id"]: field for field in source}
    after = {field["id"]: field for field in target}
    result = []
    for operation in operations:
        field_id = operation.get("schema_id") or operation.get("field", {}).get("id")
        old, new = before.get(field_id, {}), after.get(field_id, {})
        label = new.get("title") or old.get("title") or "Field order"
        if operation["op"] == "remove_field":
            detail = "Remove field and clear its saved values."
        elif operation["op"] == "add_field":
            detail = f"Add {new.get('input') or new.get('type')} field."
        elif operation["op"] == "add_select_option":
            detail = f"Add choice: {operation['option']['label']}."
        elif operation["op"] == "reorder_fields":
            detail = " → ".join(
                after[key].get("title", key) for key in operation["ids"]
            )
        else:
            details = []
            for key in operation["patch"]:
                value = new.get(key)
                if key in {"columns", "options"}:
                    value = ", ".join(
                        item.get("title", item.get("label", "")) for item in value or []
                    )
                elif key in {"visibility", "status"}:
                    value = json.dumps(value, ensure_ascii=False)
                details.append(
                    f"{key.capitalize()}: {value if value is not None else 'cleared'}"
                )
            detail = "; ".join(details)
        result.append(
            {
                "label": label,
                "detail": detail,
                "instructions": instructions.get(field_id, ""),
            }
        )
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/schema_updates.py::prepare_schema_updates
# @reason schema-dependent actions must execute after publication and skip together
def _bind_dependencies(proposal, schema_actions):
    if not schema_actions:
        return
    positions = {
        action.get("id"): index
        for index, action in enumerate(proposal.get("actions", []))
    }
    for index, action in enumerate(proposal.get("actions", [])):
        if action.get("type") == "update_form_schema":
            continue
        data = action.get("data") or {}
        references = [
            data.get(root)
            for root in ("form", "page", "task", "entity", "model", "category")
        ]
        references.extend(
            row.get(root)
            for row in data.get("updates", [])
            if isinstance(row, dict)
            for root in ("page", "task")
        )
        for reference in {value for value in references if isinstance(value, str)}:
            entity = Entities.fetch_one(reference, request=Fetch.direct())
            if entity is None:
                continue
            form_key = (
                entity.urlsafe_key
                if isinstance(entity, Entities.FORM)
                else entity.db.get("form")
            )
            if form_key and not isinstance(form_key, str):
                from lagniappe.core.tools.database.get import urlsafe_key

                form_key = urlsafe_key(form_key)
            dependency = schema_actions.get(form_key)
            if dependency is None:
                continue
            if positions[dependency["id"]] > index:
                raise ValidationError(
                    "Place the schema update before actions that use the affected Form or submissions."
                )
            dependencies = action.setdefault("depends_on", [])
            if dependency["id"] not in dependencies:
                dependencies.append(dependency["id"])


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_report_impact_redacts_revoked_access_and_paginates
# @matrix ai-report form-migration : review links pagination permissions
def report_impact(report, user, *, page=1):
    """Project saved affected identities through current permissions, one page at a time."""
    result = {}
    for action in (getattr(report, "proposal", None) or {}).get("actions", []):
        change = action.get("_schema_change")
        if not change:
            continue
        entries = change.get("impact", [])
        output = {
            "total": len(entries),
            "page": page,
            "has_more": page * 25 < len(entries),
            "items": [],
            "migration": change["migration"],
        }
        form = Entities.fetch_one(change["form"], request=Fetch.direct())
        if form and form.allowed(Action.EDIT, user=user):
            output.update(
                form_name=form.name, form_url=form.url, review=change.get("review", [])
            )
        candidates = {
            (row["entity"], row["schema_id"]): row
            for row in action["data"].get("conversions", [])
        }
        for entry in entries[(page - 1) * 25 : page * 25]:
            entity = Entities.fetch_one(entry["id"], request=Fetch.direct())
            if not entity:
                output["items"].append({"unavailable": True})
                continue
            try:
                entity = updates.require_visible(entity, user)
            except ValidationError:
                output["items"].append({"unavailable": True})
                continue
            fields = []
            for field in entry["fields"]:
                item = dict(field)
                candidate = candidates.get((entry["id"], field["schema_id"]))
                if candidate:
                    item["candidate"] = candidate.get(
                        "unresolved_reason"
                    ) or json.dumps(
                        candidate.get("value"), ensure_ascii=False, indent=2
                    )
                    item["cleared"] = "unresolved_reason" in candidate
                fields.append(item)
            output["items"].append(
                {"name": entity.name, "url": entity.url, "fields": fields}
            )
        result[action["id"]] = output
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason irreversible migrations must be detected before any compensating write
def migration_started(report):
    return any(
        record.get("migration_id")
        for record in (getattr(report, "result", None) or {}).get("actions", [])
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason report ownership protects candidates until a linked migration publishes
def migration_pending(report):
    if getattr(report, "status", None) == "running" and any(
        (action.get("_schema_change") or {}).get("migration")
        for action in (getattr(report, "proposal", None) or {}).get("actions", [])
    ):
        return True
    for record in (getattr(report, "result", None) or {}).get("actions", []):
        if not record.get("migration_id"):
            continue
        form = Entities.fetch_one(record.get("migration_form"), request=Fetch.direct())
        if form:
            from lagniappe.core.tools.form_changes import json_value, PENDING

            if json_value(form.db, PENDING).get("id") == record["migration_id"]:
                return True
    return False
