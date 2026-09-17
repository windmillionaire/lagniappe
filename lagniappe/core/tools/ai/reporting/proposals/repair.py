"""Safe mechanical repairs shared by report planning."""

import copy
import re

from ...observability import mark_outcome
from .references import _first_data_reference, _proposal_string, _strip_action_reference

# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/repair.py::complete_proposal_structure
# @reason safe schema-id completion is asserted through proposal repair behavior
def _schema_field_title(field):
    """Return or derive a readable title without inventing field meaning."""
    for key in ("title", "label", "name"):
        if _proposal_string(field.get(key)):
            return field[key].strip()

    placeholder = field.get("placeholder")
    if _proposal_string(placeholder):
        title = re.sub(
            r"^(?:enter|select|choose|provide|add)\s+(?:a\s+|an\s+|the\s+|your\s+)?",
            "",
            placeholder.strip(),
            flags=re.IGNORECASE,
        ).strip(" .:;-")
        return title or placeholder.strip()

    schema_id = field.get("id")
    if _proposal_string(schema_id):
        parts = [part for part in re.split(r"[^a-zA-Z0-9]+", schema_id) if part]
        field_type = str(field.get("type") or "").lower()
        if parts and parts[0].lower() in {field_type, "field", "row"}:
            parts = parts[1:]
        if parts:
            return " ".join(parts).title()
    return None


# @testable true
# @matrix ai-report : deterministic-repair form-type schema-field-id schema-update
# @matrix form-schema : deterministic-repair form-type schema-update
def _complete_form_schema_fields(proposal):
    """Complete safe mechanical parts of proposed create/add field definitions."""
    if not isinstance(proposal, dict):
        return proposal

    actions = proposal.get("actions")
    if not isinstance(actions, list):
        return proposal
    repaired = copy.deepcopy(proposal)
    changed = False
    create_form_ids = {
        action.get("id")
        for action in repaired["actions"]
        if isinstance(action, dict)
        and action.get("type") == "create_form"
        and _proposal_string(action.get("id"))
    }
    form_usage_types = {action_id: set() for action_id in create_form_ids}
    usage_type_by_action = {
        "create_category": "page",
        "create_page": "page",
        "create_model_task": "task",
        "create_task": "task",
    }
    for usage_action in repaired["actions"]:
        if not isinstance(usage_action, dict):
            continue
        usage_type = usage_type_by_action.get(usage_action.get("type"))
        usage_data = usage_action.get("data")
        if not usage_type or not isinstance(usage_data, dict):
            continue
        form_reference = _first_data_reference(usage_data, "form")
        if isinstance(form_reference, dict):
            form_reference = (
                form_reference.get("action")
                or form_reference.get("id")
                or form_reference.get("key")
            )
        if isinstance(form_reference, str):
            form_reference = _strip_action_reference(form_reference)
        if form_reference in form_usage_types:
            form_usage_types[form_reference].add(usage_type)

    for action in repaired["actions"]:
        if not isinstance(action, dict):
            continue
        data = action.get("data")
        if not isinstance(data, dict):
            continue

        if action.get("type") == "create_form" and not (
            data.get("form_type") or data.get("form-type")
        ):
            usage_types = form_usage_types.get(action.get("id"), set())
            if len(usage_types) == 1:
                data["form_type"] = next(iter(usage_types))
                changed = True

        fields = []
        if action.get("type") == "create_form" and isinstance(data.get("schema"), list):
            fields = data["schema"]
        elif action.get("type") == "update_form_schema" and isinstance(
            data.get("operations"), list
        ):
            fields = [
                operation.get("field")
                for operation in data["operations"]
                if isinstance(operation, dict)
                and (operation.get("op") or operation.get("type")) == "add_field"
            ]
        if not fields:
            continue

        used = set()
        for index, field in enumerate(fields, 1):
            if not isinstance(field, dict):
                continue

            title = _schema_field_title(field)
            if not _proposal_string(field.get("title")) and _proposal_string(title):
                field["title"] = title
                changed = True

            field_type = field.get("type")
            if field_type == "input" and not _proposal_string(field.get("input")):
                field["input"] = "text"
                changed = True

            schema_id = field.get("id")
            if _proposal_string(schema_id):
                used.add(schema_id.strip())
                continue
            if not _proposal_string(field_type) or not _proposal_string(title):
                continue

            prefix = re.sub(r"[^a-z0-9]+", "-", field_type.lower()).strip("-")
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            base = f"{prefix or 'field'}-{slug or index}"
            candidate = base
            suffix = 2
            while candidate in used:
                candidate = f"{base}-{suffix}"
                suffix += 1
            field["id"] = candidate
            used.add(candidate)
            changed = True
    return repaired if changed else proposal


# @testable true
# @matrix ai-report : deterministic-repair page-form references
def _complete_unambiguous_add_form_references(proposal):
    """Link a form-less page-form action when one earlier page form can fit."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("actions"), list):
        return proposal

    repaired = copy.deepcopy(proposal)
    page_form_actions = []
    changed = False
    for action in repaired["actions"]:
        if not isinstance(action, dict):
            continue
        data = action.get("data")
        if not isinstance(data, dict):
            continue

        if action.get("type") == "create_form":
            form_type = data.get("form_type") or data.get("form-type")
            action_id = action.get("id")
            form_name = data.get("name")
            if (
                form_type == "page"
                and _proposal_string(action_id)
                and _proposal_string(form_name)
            ):
                page_form_actions.append((action_id, form_name.strip()))
            continue

        if action.get("type") != "add_form_to_page" or _first_data_reference(
            data, "form"
        ):
            continue

        declared_name = next(
            (
                data[key].strip()
                for key in ("form_name", "form_display", "form_label")
                if _proposal_string(data.get(key))
            ),
            None,
        )
        candidates = page_form_actions
        if declared_name:
            candidates = [
                candidate
                for candidate in candidates
                if candidate[1].casefold() == declared_name.casefold()
            ]
        if len(candidates) == 1:
            data["form_action"] = candidates[0][0]
            changed = True

    return repaired if changed else proposal



# @testable true
# @tests tests_unit/test_020b_ai_planner.py::test_generate_report_validates_answers_actions_and_file_usage
# @matrix ai-report : validation generate
def complete_proposal_structure(proposal):
    """Fill unambiguous schema IDs and references without another model call."""
    repaired = _complete_unambiguous_add_form_references(_complete_form_schema_fields(proposal))
    if repaired != proposal:
        mark_outcome("local_repair")
    return repaired
