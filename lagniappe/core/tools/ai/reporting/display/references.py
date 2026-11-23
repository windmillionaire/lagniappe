"""Reference and label resolution for AI-report proposal display."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.properties.ai_report_proposal import Proposal
    from lagniappe.core.tools.ai.reporting.contracts.actions import ActionData, ActionReferences, ReportAction
    from typing import TypeGuard


import re
from lagniappe.core.entities import Entities


class ProposalReferenceResolver:
    """Resolve stored action, file, and entity references for display."""

    def __init__(self, proposal: Proposal) -> None:
        self.proposal = proposal
        self._entity_details_cache = None

    def reset(self) -> None:
        self._entity_details_cache = None

    @property
    def value(self) -> object:
        return self.proposal.value

    @property
    def entity(self) -> models.AIReport:
        report = self.proposal.entity
        if not isinstance(report, Entities.REPORT):
            raise TypeError("Report proposal requires an AI report owner.")
        return report

    def existing_entity_reference(
        self, action: ActionReferences, root: str
    ) -> str | None:
        data = action.get("data") or {}
        for key in [root, f"{root}_id", f"{root}_ref"]:
            value = data.get(key)
            if not value or self.action_reference(value, key):
                continue
            reference = self.reference_identity(value)
            if reference:
                return reference
        return None

    def reference_identity(self, value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("id", "key", "hash", "name"):
                if value.get(key):
                    return value[key]
        return None

    def reference_is_opaque(self, value: object) -> TypeGuard[str]:
        if not isinstance(value, str):
            return False
        return value.startswith("hash:") or (len(value) > 32 and value.startswith("ah"))

    def reference_display_label(self, action: ReportAction, root: str) -> str | None:
        data = action.get("data") or {}
        value = data.get(root)
        for key in (f"{root}_name", f"{root}_display", f"{root}_label"):
            label = data.get(key)
            if isinstance(label, str) and label:
                return label
        page_name = data.get("page_name")
        if root != "page" and isinstance(page_name, str) and page_name:
            return page_name
        if isinstance(value, dict):
            for key in ("name", "title", "display_name", "label"):
                if value.get(key):
                    return value[key]
        return None

    def reference_action_id(self, action: ActionReferences, *roots: str) -> str | None:
        data = action.get("data") or {}
        for root in roots:
            for key in [f"{root}_action", root, f"{root}_ref", f"{root}_id"]:
                value = data.get(key)
                action_id = self.action_reference(value, key)
                if action_id:
                    return action_id
        return None

    def referenced_action_ids(self, action: ReportAction) -> set[str]:
        references = set()
        for action_id in action.get("depends_on") or []:
            references.add(self.strip_action_reference(action_id))
        references.update(self.referenced_action_ids_from_value(action.get("data")))
        return {reference for reference in references if reference}

    def referenced_action_ids_from_value(
        self, value: object, key: str | None = None
    ) -> set[str]:
        references = set()
        if isinstance(value, dict):
            if value.get("action"):
                references.add(self.strip_action_reference(value["action"]))
            for child_key, child_value in value.items():
                references.update(
                    self.referenced_action_ids_from_value(
                        child_value,
                        child_key,
                    )
                )
        elif isinstance(value, list):
            for child in value:
                references.update(self.referenced_action_ids_from_value(child))
        elif isinstance(value, str):
            action_id = self.action_reference(value, key)
            if action_id:
                references.add(action_id)
        return references

    def action_reference(self, value: object, key: str | None = None) -> str | None:
        if isinstance(value, dict):
            value = value.get("action")
        if not isinstance(value, str) or not value:
            return None
        if value.startswith("$") or value.startswith("action:"):
            return self.strip_action_reference(value)
        if key and key.endswith("_action"):
            return self.strip_action_reference(value)
        return None

    def strip_action_reference(self, value: str) -> str:
        if not isinstance(value, str):
            return value
        if value.startswith("$"):
            return value[1:]
        if value.startswith("action:"):
            return value.split(":", 1)[1]
        return value

    def action_labels(self, actions: Iterable[ReportAction]) -> dict[str, str]:
        labels = {}
        for action in actions:
            action_id = action.get("id")
            if not action_id:
                continue
            label = self.action_label(action)
            if (action.get("type") or "").startswith("create_"):
                data = action.get("data") or {}
                targeted_task = action.get("type") == "create_task" and any(
                    data.get(key)
                    for key in ("task", "task_id", "task_ref", "task_action")
                )
                label = (
                    f"{label} (existing task)" if targeted_task else f"{label} (new)"
                )
            labels[action_id] = label
        return labels

    def file_labels(self) -> dict[object, str]:
        labels = {}
        for file in self.entity.input_files or []:
            label = file.name or file.filename
            for key in [file.urlsafe_key, file.key, file.name, file.filename]:
                if key:
                    labels[key] = label
        return labels

    def action_label(self, action: ReportAction) -> str:
        data = action.get("data") or {}
        if (action.get("type") or "").startswith("create_"):
            return str(
                data.get("name")
                or action.get("display_label")
                or self.action_id_label(action)
                or action.get("id")
                or action.get("type")
                or "Action"
            )
        if action.get("type") == "move_file":
            return str(
                data.get("display_name")
                or data.get("file_name")
                or data.get("file_label")
                or data.get("file_display")
                or action.get("display_label")
                or data.get("name")
                or self.action_id_label(action)
                or action.get("id")
                or action.get("type")
                or "Action"
            )
        return str(
            action.get("display_label")
            or data.get("name")
            or action.get("id")
            or action.get("type")
            or "Action"
        )

    def action_id_label(self, action: ReportAction) -> str | None:
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id.strip():
            return None

        label = action_id.strip()
        action_type = action.get("type") or ""
        if action_type and label.startswith(f"{action_type}_"):
            label = label[len(action_type) + 1 :]
        elif action_type.startswith("create_") and label.startswith("create_"):
            label = label[len("create_") :]

        if action_type.startswith("create_"):
            suffix = action_type.split("_", 1)[1]
            if label.endswith(f"_{suffix}"):
                label = label[: -(len(suffix) + 1)]

        label = re.sub(r"[_-]+", " ", label).strip()
        if not label:
            return None
        return label.title()

    def move_file_display_label(self, action: ReportAction, fallback: str) -> str:
        data = action.get("data") or {}
        for key in ("display_name", "file_name", "file_label", "file_display"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return self.action_id_label(action) or fallback

    def resolve_detail(
        self,
        value: object,
        action_labels: Mapping[str, str],
        file_labels: Mapping[object, str],
        label: str | None = None,
    ) -> object:
        if isinstance(value, dict):
            if "_proposal_display_value" in value:
                return value["_proposal_display_value"]
            if value.get("name"):
                return value["name"]
            value = (
                value.get("action")
                or value.get("file")
                or value.get("id")
                or value.get("key")
            )
        if not value:
            return None
        if isinstance(value, str) and value.startswith("$"):
            value = value[1:]
        elif isinstance(value, str) and value.startswith("action:") or isinstance(value, str) and value.startswith("file:"):
            value = value.split(":", 1)[1]
        resolved = (action_labels.get(value) if isinstance(value, str) else None) or file_labels.get(value)
        if resolved:
            return resolved
        if label in {
            "Category",
            "Entity",
            "File",
            "Form",
            "From Page",
            "From Task",
            "Model Task",
            "Page",
            "Project",
            "Task",
            "To Page",
            "To Task",
        }:
            return self.entity_label(value) or value
        return None

    def entity_label(self, value: object) -> str | None:
        details = self.entity_details(value)
        if details:
            label = details.get("label")
            return label if isinstance(label, str) else None
        return None

    def entity_details(self, value: object) -> dict[str, object] | None:
        if not isinstance(value, str):
            return None

        details = self._entity_details_cache
        if details is None:
            details = self._load_proposal_entity_details()
            self._entity_details_cache = details
        return details.get(value)

    def _load_proposal_entity_details(self):
        from .....definitions import Fetch
        from .....entities import Entities

        actions = self.value.get("actions") if isinstance(self.value, dict) else []
        references = []
        for action in actions or []:
            data = action.get("data") or {}
            references.extend(self.entity_reference_values(data))
            references.extend(self.opaque_submission_references(data.get("submission")))
        if not references:
            return {}

        loaded = Entities.fetch(*dict.fromkeys(references), request=Fetch.direct())
        return {
            entity.urlsafe_key: self.entity_detail(entity)
            for entity in loaded
            if getattr(entity, "urlsafe_key", None) and getattr(entity, "name", None)
        }

    def opaque_submission_references(self, value: object) -> list[str]:
        """Collect possible normalized entity ids for schema-aware projection."""
        if isinstance(value, dict):
            references = []
            for child in value.values():
                references.extend(self.opaque_submission_references(child))
            return references
        if isinstance(value, list):
            references = []
            for child in value:
                references.extend(self.opaque_submission_references(child))
            return references
        if self.reference_is_opaque(value):
            return [value]
        return []

    def entity_detail(self, entity: Entity) -> dict[str, object]:
        detail = {
            "label": entity.name,
            "kind": getattr(entity, "kind", None),
        }
        category = self.entity_category_label(entity)
        if category:
            detail["category"] = category
        schema = getattr(entity, "schema", None)
        if not isinstance(schema, list):
            schema = getattr(getattr(entity, "form", None), "schema", None)
        if isinstance(schema, list):
            detail["schema"] = schema
        return detail

    def entity_category_label(self, entity: Entity) -> str | None:
        if getattr(entity, "kind", None) != "page":
            return None

        category = getattr(entity, "model", None)
        if (
            category
            and not getattr(category, "reserved", False)
            and getattr(category, "name", None)
        ):
            return category.name
        return None

    def entity_reference_values(self, data: ActionData) -> list[str]:
        references = []
        for root in (
            "entity",
            "category",
            "file",
            "form",
            "from_page",
            "from_task",
            "model",
            "page",
            "project",
            "source_page",
            "source_task",
            "target_page",
            "target_task",
            "task",
            "to_page",
            "to_task",
        ):
            for key in (root, f"{root}_id", f"{root}_ref"):
                references.extend(self.reference_strings(data.get(key)))
        return references

    def reference_strings(self, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return self.reference_strings(
                value.get("id") or value.get("key") or value.get("hash")
            )
        if isinstance(value, list):
            references = []
            for item in value:
                references.extend(self.reference_strings(item))
            return references
        return []
