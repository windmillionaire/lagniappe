"""Shared detail collector used by proposal action display adapters."""

REFERENCE_DETAIL_LABELS = frozenset(
    {
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
    }
)

DETAIL_KINDS = {
    "Category": "category",
    "File": "file",
    "Form": "form",
    "Form Type": "form",
    "From Page": "page",
    "From Task": "task",
    "Model Task": "model",
    "Page": "page",
    "Project": "project",
    "Task": "task",
    "To Page": "page",
    "To Task": "task",
}


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_decision_details
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_empty_submission_reason
# @pair ai-report:classification
# @pair ai-report:details
# @pair ai-report:feedback
# @pair ai-report:proposal
# @pair ai-report:submission-empty-reason
class ProposalDetailCollector:
    """Resolve and collect display details without knowing action types."""

    def __init__(self, action_labels, file_labels, entity_label):
        self.action_labels = action_labels
        self.file_labels = file_labels
        self.entity_label = entity_label
        self.values = []

    def add(self, label, value):
        if value:
            self.values.append(
                {
                    "label": label,
                    "value": value,
                    "kind": DETAIL_KINDS.get(label, "default"),
                }
            )

    def reference(self, label, data, *roots):
        self.add_reference(label, self.first_value(data, *roots))

    def add_reference(self, label, value):
        resolved = self.resolve(value, label)
        if resolved:
            self.add(label, resolved)

    def resolve(self, value, label=None):
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
        resolved = self.action_labels.get(value) or self.file_labels.get(value)
        if resolved:
            return resolved
        if label in REFERENCE_DETAIL_LABELS:
            return self.entity_label(value) or value
        return None

    def submission(self, data, form_present=False):
        if "submission" not in data and not form_present:
            return
        if data.get("submission_empty_reason"):
            self.add("Submission", data["submission_empty_reason"])
            return
        submission = data.get("submission")
        created = (
            bool(submission) if isinstance(submission, dict) else submission is not None
        )
        self.add("Submission", "created" if created else "missing")

    @staticmethod
    def first_value(data, *roots):
        for root in roots:
            display_keys = [f"{root}_name", f"{root}_display", f"{root}_label"]
            if root == "file":
                display_keys.insert(0, "display_name")
            for key in display_keys:
                value = data.get(key)
                if value:
                    return {"_proposal_display_value": value}
            for key in (root, f"{root}_id", f"{root}_ref", f"{root}_action"):
                value = data.get(key)
                if value:
                    return value
        return None

    @staticmethod
    def file_values(data):
        values = [data[key] for key in ("file", "file_id", "file_ref") if data.get(key)]
        file_values = data.get("files") or data.get("file_refs") or []
        if isinstance(file_values, (str, dict)):
            file_values = [file_values]
        values.extend(file_values)
        return values
