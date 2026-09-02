"""Reference and label resolution for AI-report proposal display."""

import re


# @testable infrastructure
class ProposalReferenceResolver:
    """Resolve stored action, file, and entity references for display."""

    def __init__(self, proposal):
        self.proposal = proposal
        self._entity_details_cache = None

    def reset(self):
        self._entity_details_cache = None

    @property
    def value(self):
        return self.proposal.value

    @property
    def entity(self):
        return self.proposal.entity

    def existing_entity_reference(self, action, root):
        data = action.get("data") or {}
        for key in [root, f"{root}_id", f"{root}_ref"]:
            value = data.get(key)
            if not value or self.action_reference(value, key):
                continue
            reference = self.reference_identity(value)
            if reference:
                return reference
        return None

    def reference_identity(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("id", "key", "hash", "name"):
                if value.get(key):
                    return value[key]
        return None

    def reference_is_opaque(self, value):
        if not isinstance(value, str):
            return False
        return value.startswith("hash:") or (len(value) > 32 and value.startswith("ah"))

    def reference_display_label(self, action, root):
        data = action.get("data") or {}
        value = data.get(root)
        for key in (f"{root}_name", f"{root}_display", f"{root}_label"):
            if data.get(key):
                return data[key]
        if root != "page" and data.get("page_name"):
            return data["page_name"]
        if isinstance(value, dict):
            for key in ("name", "title", "display_name", "label"):
                if value.get(key):
                    return value[key]
        return None

    def reference_action_id(self, action, *roots):
        data = action.get("data") or {}
        for root in roots:
            for key in [f"{root}_action", root, f"{root}_ref", f"{root}_id"]:
                value = data.get(key)
                action_id = self.action_reference(value, key)
                if action_id:
                    return action_id
        return None

    def referenced_action_ids(self, action):
        references = set()
        for action_id in action.get("depends_on") or []:
            references.add(self.strip_action_reference(action_id))
        references.update(self.referenced_action_ids_from_value(action.get("data")))
        return {reference for reference in references if reference}

    def referenced_action_ids_from_value(self, value, key=None):
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

    def action_reference(self, value, key=None):
        if isinstance(value, dict):
            value = value.get("action")
        if not isinstance(value, str) or not value:
            return None
        if value.startswith("$") or value.startswith("action:"):
            return self.strip_action_reference(value)
        if key and key.endswith("_action"):
            return self.strip_action_reference(value)
        return None

    def strip_action_reference(self, value):
        if not isinstance(value, str):
            return value
        if value.startswith("$"):
            return value[1:]
        if value.startswith("action:"):
            return value.split(":", 1)[1]
        return value

    def action_labels(self, actions):
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

    def file_labels(self):
        labels = {}
        for file in self.entity.input_files or []:
            label = file.name or file.filename
            for key in [file.urlsafe_key, file.key, file.name, file.filename]:
                if key:
                    labels[key] = label
        return labels

    def action_label(self, action):
        data = action.get("data") or {}
        if (action.get("type") or "").startswith("create_"):
            return (
                data.get("name")
                or action.get("display_label")
                or self.action_id_label(action)
                or action.get("id")
                or action.get("type")
                or "Action"
            )
        if action.get("type") == "move_file":
            return (
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
        return (
            action.get("display_label")
            or data.get("name")
            or action.get("id")
            or action.get("type")
            or "Action"
        )

    # @testable true
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_humanize_generated_action_ids
    # @matrix ai-report files : details fallback-labels proposal
    def action_id_label(self, action):
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

    def move_file_display_label(self, action, fallback):
        data = action.get("data") or {}
        for key in ("display_name", "file_name", "file_label", "file_display"):
            value = data.get(key)
            if value:
                return value
        return self.action_id_label(action) or fallback

    def resolve_detail(self, value, action_labels, file_labels, label=None):
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
        elif isinstance(value, str) and value.startswith("action:"):
            value = value.split(":", 1)[1]
        elif isinstance(value, str) and value.startswith("file:"):
            value = value.split(":", 1)[1]
        resolved = action_labels.get(value) or file_labels.get(value)
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

    def entity_label(self, value):
        details = self.entity_details(value)
        if details:
            return details.get("label")
        return None

    # @testable true
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_resolve_normalized_entity_refs
    # @matrix ai-report : existing-page-category normalized-references
    def entity_details(self, value):
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

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/display/references.py::ProposalReferenceResolver.entity_details
    # @reason entity_details owns recursive discovery of normalized submission references
    def opaque_submission_references(self, value):
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

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/display/references.py::ProposalReferenceResolver.entity_details
    # @reason entity_details owns persisted reference projection and its tests
    def entity_detail(self, entity):
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

    def entity_category_label(self, entity):
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

    def entity_reference_values(self, data):
        references = []
        for root in (
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

    def reference_strings(self, value):
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
