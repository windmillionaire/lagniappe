"""AI report properties and process-backed report state."""

import re

from ..tools.files.utility import sanitize_html
from .base_db import DBProperty
from .base_process import ProcessProperty
from .base_property import Property


_REPORT_PROCESS_KEYS = (
    "status",
    "pending",
    "summary",
    "proposal",
    "result",
    "error",
    "deferred_job",
)
# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_create_and_file_cleanup
# @features ai-report
# @dimensions upload-manifest
class UploadManifest(DBProperty):
    """Signed direct-upload records awaiting background finalization."""

    _id = "upload_manifest"
    json = True


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_shape_preserves_safe_inbound_display_fields
# @features ai-email ai-report
# @dimensions origin legacy-default
class Origin(DBProperty):
    """How the initial report was submitted; legacy reports are web-origin."""

    _id = "origin"

    @property
    def value(self):
        return DBProperty.value.fget(self) or "web"

    @value.setter
    def value(self, value):
        normalized = str(value or "web").strip().casefold()
        if normalized not in {"web", "email"}:
            raise ValueError("AI report origin must be web or email")
        DBProperty.value.fset(self, normalized)


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_shape_preserves_safe_inbound_display_fields
# @features ai-email ai-report
# @dimensions inbound-manifest privacy
class InboundManifest(DBProperty):
    """Safe normalized email fields displayed with an email-origin report."""

    _id = "inbound_manifest"
    json = True


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_process_state_stores_report_metadata
# @features ai-report
# @dimensions process-state canonical-storage
class ReportProcess(ProcessProperty):
    """Process section containing an AI report's workflow state."""

    process_id = "process"
    section_id = "report"
    attributes = _REPORT_PROCESS_KEYS

    def revise(self):
        self.status = "revising"
        self.pending = True
        self.summary = None
        self.error = None

    def fail(self, message, result=None):
        self.status = "failed"
        self.pending = None
        self.error = message
        if result is not None:
            self.result = result

    def revision_failed(self, message):
        proposal = self.proposal if isinstance(self.proposal, dict) else {}
        actions = proposal.get("actions") or []
        self.status = (
            "complete"
            if self.entity.tool == "ask" and not actions
            else "ready"
        )
        self.pending = None
        self.error = message
        self.summary = proposal.get("summary")
        self.result = None

    def retry(self, message, result=None):
        self.status = "pending"
        self.pending = True
        self.error = message
        if result is not None:
            self.result = result

    def set_proposal(self, proposal, status="ready"):
        self.proposal = proposal
        self.summary = proposal.get("summary") if isinstance(proposal, dict) else None
        self.status = status
        self.pending = None
        self.error = None
        self.result = None


# @testable false
# @covered-by lagniappe/core/properties/ai_report.py::ReportProcess
# @reason thin process-backed value adapter exercised through report process state
class ReportProcessValue(Property):
    """Entity property facade for one report process attribute."""

    _blank_values = (None, [], {})

    @property
    def process_attribute(self):
        return getattr(self, "_process_attribute", self.id)

    @property
    def process(self):
        return self.entity.properties.process

    def _clear_cached_entity_views(self):
        if hasattr(self.entity, "_details"):
            self.entity._details = None
        if hasattr(self.entity, "_to_cache"):
            self.entity._to_cache = None

    @property
    def value(self):
        return getattr(self.process, self.process_attribute)

    @value.setter
    def value(self, value):
        if value in self._blank_values:
            value = None
        setattr(self.process, self.process_attribute, value)
        self._clear_cached_entity_views()


# @testable false
# @covered-by lagniappe/core/properties/ai_report.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Status(ReportProcessValue):
    """Current AI report processing status."""

    _id = "status"


# @testable false
# @covered-by lagniappe/core/properties/ai_report.py::ReportProcess
# @reason active deferred-job metadata is exercised through report process state
class DeferredJob(ReportProcessValue):
    """Reference metadata for the report's currently active background job."""

    _id = "deferred_job"


# @testable false
# @covered-by lagniappe/core/properties/ai_report.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Summary(ReportProcessValue):
    """Short user-facing AI report summary."""

    _id = "summary"


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_create_and_file_cleanup
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_show_decision_details
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_show_empty_submission_reason
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_group_move_files_under_target_page
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_humanize_generated_action_ids
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_groups_added_categories_under_page
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_form_to_existing_page_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_resolve_normalized_entity_refs
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_group_completed_task_events
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_show_rename_entity_details
# @features ai-report
# @dimensions ask answer-html html-sanitization proposal details classification feedback completed-task grouped-display submission-empty-reason page-form
class Proposal(ReportProcessValue):
    """Structured action proposal generated by AI."""

    _id = "proposal"

    @property
    def answer_html(self):
        if not isinstance(self.value, dict):
            return None

        answer = self.value.get("answer_html")
        if not answer:
            return None

        return sanitize_html(answer)

    # @testable true
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_group_move_files_under_target_page
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_humanize_generated_action_ids
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_groups_added_categories_under_page
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_resolve_normalized_entity_refs
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_group_schema_updates_separately
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_proposal_display_actions_show_rename_entity_details
    # @pair ai-report:proposal
    # @pair ai-report:details
    # @pair ai-report:rename
    # @pair ai-report:move-file
    # @pair ai-report:grouped-display
    # @pair files:proposal
    # @pair files:details
    # @pair files:move-file
    # @pair files:grouped-display
    # @pair ai-report:fallback-labels
    # @pair files:fallback-labels
    # @pair ai-report:add-category
    # @pair categories:proposal
    # @pair categories:details
    # @pair categories:grouped-display
    # @pair categories:add-category
    # @pair ai-report:existing-page-category
    # @pair ai-report:attachment-grouping
    # @pair categories:existing-page-category
    # @pair categories:attachment-grouping
    # @pair files:existing-page-category
    # @pair files:attachment-grouping
    # @pair ai-report:normalized-references
    # @pair ai-report:display-labels
    # @pair ai-report:schema-section
    # @pair ai-report:skip-grouping
    # @pair form-schema:proposal
    # @pair form-schema:details
    # @pair form-schema:schema-section
    # @pair form-schema:skip-grouping
    @property
    def display_actions(self):
        if not isinstance(self.value, dict):
            return []

        self._proposal_entity_details_cache = None
        actions = self.value.get("actions") or []
        action_labels = self._proposal_action_labels(actions)
        file_labels = self._proposal_file_labels()
        display_actions = self._proposal_action_items(
            actions,
            action_labels,
            file_labels,
        )
        return self._group_proposal_display_actions(
            display_actions,
            action_labels,
            file_labels,
        )

    def _proposal_action_items(self, actions, action_labels, file_labels):
        display_actions = []
        for index, action in enumerate(actions, 1):
            if action.get("type") == "delete_page":
                continue
            item = dict(action)
            data = item.get("data") or {}
            item["data"] = data
            item["action_index"] = index
            item["support"] = []
            item["details"] = self._proposal_action_details(
                item,
                data,
                action_labels,
                file_labels,
            )
            item["display_label"] = self._proposal_display_action_label(item)
            display_actions.append(item)

        return display_actions

    def _group_proposal_display_actions(self, actions, action_labels, file_labels):
        by_id = {
            action["id"]: action
            for action in actions
            if action.get("id")
        }
        for action in actions:
            self._add_inherited_proposal_details(
                action,
                by_id,
                action_labels,
                file_labels,
            )

        roots = []
        consumed_indexes = set()
        file_targets = {}
        page_groups = {}
        schema_group = None
        targets = {
            action["id"]: action
            for action in actions
            if action.get("id") and action.get("type") == "create_page"
        }

        for action in actions:
            action_type = action.get("type")
            if action_type == "create_page":
                roots.append(action)
                consumed_indexes.add(action["action_index"])
            elif action_type == "create_task":
                page_ref = self._proposal_reference_action_id(action, "page")
                page_target = targets.get(page_ref)
                if page_target:
                    support = self._proposal_action_support(
                        "Task",
                        action,
                        "task",
                        action_labels,
                        exclude_labels={"Page"},
                    )
                    page_target["support"].append(support)
                    consumed_indexes.add(action["action_index"])
                    if action.get("id"):
                        targets[action["id"]] = support
                else:
                    page_group = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                    if page_group:
                        support = self._proposal_action_support(
                            "Task",
                            action,
                            "task",
                            action_labels,
                            exclude_labels={"Page"},
                        )
                        page_group["support"].append(support)
                        consumed_indexes.add(action["action_index"])
                        if action.get("id"):
                            targets[action["id"]] = support
                    else:
                        roots.append(action)
                        consumed_indexes.add(action["action_index"])
                        if action.get("id"):
                            targets[action["id"]] = action
            elif action_type == "attach_file_to_page":
                page_ref = self._proposal_reference_action_id(action, "page")
                target = targets.get(page_ref)
                if not target:
                    target = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                support = self._add_attachment_support(target, action) if target else None
                if support:
                    consumed_indexes.add(action["action_index"])
                    self._remember_file_support(file_targets, action, support)
            elif action_type == "attach_file_to_task":
                task_ref = self._proposal_reference_action_id(action, "task")
                target = targets.get(task_ref)
                support = self._add_attachment_support(target, action) if target else None
                if support:
                    consumed_indexes.add(action["action_index"])
                    self._remember_file_support(file_targets, action, support)
            elif action_type == "add_form_to_page":
                page_ref = self._proposal_reference_action_id(action, "page")
                target = targets.get(page_ref)
                if not target:
                    target = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                support = self._add_page_form_support(
                    target,
                    action,
                    action_labels,
                ) if target else None
                if support:
                    consumed_indexes.add(action["action_index"])
            elif action_type == "add_category":
                page_ref = self._proposal_reference_action_id(action, "page")
                target = targets.get(page_ref)
                if not target:
                    target = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                support = self._add_category_support(
                    target,
                    action,
                    action_labels,
                ) if target else None
                if support:
                    consumed_indexes.add(action["action_index"])
            elif action_type == "move_file":
                target = self._proposal_move_file_target(
                    action,
                    roots,
                    page_groups,
                    targets,
                    action_labels,
                    file_labels,
                )
                support = self._add_move_file_support(
                    target,
                    action,
                    action_labels,
                ) if target else None
                if support:
                    consumed_indexes.add(action["action_index"])
            elif action_type == "summarize_file":
                file_support = self._file_support(file_targets, action)
                if file_support:
                    file_support["support"].append(
                        self._proposal_summary_support(action)
                    )
                    consumed_indexes.add(action["action_index"])
            elif action_type == "update_form_schema":
                if schema_group is None:
                    schema_group = self._proposal_schema_group(roots)
                support = self._proposal_action_support(
                    "Schema Update",
                    action,
                    "form",
                    action_labels,
                )
                schema_group["support"].append(support)
                if schema_group.get("action_index") is None:
                    schema_group["action_index"] = action["action_index"]
                schema_group["skip"] = all(
                    item.get("skip") for item in schema_group["support"]
                )
                consumed_indexes.add(action["action_index"])
            elif action_type in {"skip", "needs_review"}:
                roots.append(action)
                consumed_indexes.add(action["action_index"])

        self._consume_referenced_support_actions(actions, by_id, consumed_indexes)
        for action in actions:
            if action["action_index"] not in consumed_indexes:
                roots.append(action)
                consumed_indexes.add(action["action_index"])

        self._assign_proposal_group_indexes(roots, actions, by_id)
        self._assign_proposal_page_group_indexes(roots, actions)
        return roots

    def _proposal_schema_group(self, roots):
        group = {
            "id": "schema-updates",
            "type": "schema_update_group",
            "data": {},
            "display_label": "Schema Updates",
            "support": [],
            "details": [],
            "skip": None,
            "skip_dependencies": False,
            "action_index": None,
            "group_action_indexes": [],
        }
        roots.append(group)
        return group

    def _proposal_page_group(
        self,
        action,
        roots,
        page_groups,
        action_labels,
        file_labels,
    ):
        page_ref = self._proposal_existing_entity_reference(action, "page")
        if not page_ref:
            return None

        page_label = self._proposal_page_group_label(
            action,
            page_ref,
            action_labels,
            file_labels,
        )
        if not page_label:
            return None

        page_key = str(page_ref)
        if page_key in page_groups:
            return page_groups[page_key]

        group = {
            "id": f"page:{page_key}",
            "type": "page_group",
            "data": {},
            "display_label": f"Page: {page_label}",
            "support": [],
            "details": self._proposal_existing_page_details(page_ref),
            "skip": None,
            "action_index": None,
            "group_action_indexes": [],
        }
        roots.append(group)
        page_groups[page_key] = group
        return group

    def _proposal_page_group_label(
        self,
        action,
        page_ref,
        action_labels,
        file_labels,
    ):
        detail = self._proposal_detail(action, "Page")
        if detail and detail.get("value"):
            label = detail["value"]
        else:
            label = self._resolve_proposal_detail(
                page_ref,
                action_labels,
                file_labels,
                "Page",
            )
        if not label or (
            label == page_ref and self._proposal_reference_is_opaque(label)
        ):
            return None
        return label

    def _proposal_existing_page_details(self, page_ref):
        entity_details = self._proposal_entity_details(page_ref)
        category = entity_details.get("category") if entity_details else None
        if not category:
            return []
        return [
            {
                "label": "Category",
                "value": category,
                "kind": "category",
            }
        ]

    def _proposal_existing_entity_reference(self, action, root):
        data = action.get("data") or {}
        for key in [root, f"{root}_id", f"{root}_ref"]:
            value = data.get(key)
            if not value or self._proposal_action_reference(value, key):
                continue
            reference = self._proposal_reference_identity(value)
            if reference:
                return reference
        return None

    def _proposal_reference_identity(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("id", "key", "hash", "name"):
                if value.get(key):
                    return value[key]
        return None

    def _proposal_reference_is_opaque(self, value):
        if not isinstance(value, str):
            return False
        return value.startswith("hash:") or (
            len(value) > 32 and value.startswith("ah")
        )

    def _proposal_move_file_target(
        self,
        action,
        roots,
        page_groups,
        targets,
        action_labels,
        file_labels,
    ):
        page_roots = ("to_page", "target_page", "destination_page", "page")
        task_roots = ("to_task", "target_task", "destination_task", "task")

        for root in (*page_roots, *task_roots):
            target = targets.get(self._proposal_reference_action_id(action, root))
            if target:
                return target

        for root in page_roots:
            target = self._proposal_page_group_for_reference(
                action,
                root,
                roots,
                page_groups,
                action_labels,
                file_labels,
            )
            if target:
                return target

        return None

    def _proposal_page_group_for_reference(
        self,
        action,
        root,
        roots,
        page_groups,
        action_labels,
        file_labels,
    ):
        page_ref = self._proposal_existing_entity_reference(action, root)
        if not page_ref:
            return None

        page_action = {
            "data": {"page": page_ref},
            "details": [],
        }
        page_label = self._proposal_reference_display_label(action, root)
        if page_label:
            page_action["details"].append(
                {"label": "Page", "value": page_label, "kind": "page"}
            )
        return self._proposal_page_group(
            page_action,
            roots,
            page_groups,
            action_labels,
            file_labels,
        )

    def _proposal_reference_display_label(self, action, root):
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

    def _assign_proposal_page_group_indexes(self, roots, actions):
        actions_by_index = {
            action["action_index"]: action
            for action in actions
        }
        for root in roots:
            if root.get("type") != "page_group":
                continue
            indexes = root.get("group_action_indexes") or sorted(
                self._proposal_support_indexes(root)
            )
            if not indexes:
                continue
            root["action_index"] = indexes[0]
            root["skip"] = all(
                (actions_by_index.get(index) or {}).get("skip")
                for index in indexes
            )

    def _proposal_display_action_label(self, action):
        action_type = action.get("type") or ""
        data = action.get("data") or {}
        label = (
            data.get("name")
            or action.get("display_label")
            or self._proposal_action_label(action)
        )
        if action_type == "move_file":
            label = self._proposal_move_file_display_label(action, label)
        elif action_type == "add_form_to_page":
            form_detail = self._proposal_detail(action, "Form")
            if form_detail and form_detail.get("value"):
                label = form_detail["value"]
        elif action_type == "add_category":
            category_detail = self._proposal_detail(action, "Category")
            if category_detail and category_detail.get("value"):
                label = category_detail["value"]
        if action_type.startswith("create_"):
            targeted_task = action_type == "create_task" and any(
                data.get(key)
                for key in ("task", "task_id", "task_ref", "task_action")
            )
            label = (
                f"{label} (existing task)"
                if targeted_task
                else f"{label} (new)"
            )
        prefix = {
            "create_page": "Page",
            "create_task": "Task",
            "add_form_to_page": "Add Form",
            "create_category": "Category",
            "create_form": "Form",
            "create_project": "Project",
            "create_model_task": "Model Task",
            "add_category": "Add Category",
            "move_page": "Move Page",
            "move_task": "Move Task",
            "move_file": "Move File",
            "rename_entity": "Rename",
            "update_form_schema": "Schema Update",
            "update_submission_fields": "Submission Update",
            "attach_file_to_page": "Attached File",
            "attach_file_to_task": "Attached File",
            "summarize_file": "Summary",
            "delete_page": "Delete Page",
            "needs_review": "Needs Review",
            "skip": "Skip",
        }.get(action_type)
        if not prefix:
            return label
        return f"{prefix}: {label}"

    def _add_inherited_proposal_details(
        self,
        action,
        by_id,
        action_labels,
        file_labels,
    ):
        action_type = action.get("type")
        if action_type == "create_page":
            category_ref = self._proposal_reference_action_id(
                action,
                "category",
                "model",
            )
            category = by_id.get(category_ref)
            if category and not self._proposal_has_detail(action, "Form"):
                self._add_ref_detail(
                    action["details"],
                    "Form",
                    self._first_data_value(category.get("data") or {}, "form"),
                    action_labels,
                    file_labels,
                )
        elif action_type == "create_task":
            model_ref = self._proposal_reference_action_id(action, "model")
            model = by_id.get(model_ref)
            model_data = model.get("data") if model else None
            if model_data and not self._proposal_has_detail(action, "Project"):
                self._add_ref_detail(
                    action["details"],
                    "Project",
                    self._first_data_value(model_data, "project"),
                    action_labels,
                    file_labels,
                )
            if model_data and not self._proposal_has_detail(action, "Form"):
                self._add_ref_detail(
                    action["details"],
                    "Form",
                    self._first_data_value(model_data, "form"),
                    action_labels,
                    file_labels,
                )

    def _proposal_action_support(
        self,
        label,
        action,
        kind,
        action_labels,
        exclude_labels=None,
    ):
        exclude_labels = exclude_labels or set()
        details = [
            detail
            for detail in action.get("details", [])
            if detail.get("label") not in exclude_labels
        ]
        return {
            "label": label,
            "value": (
                action_labels.get(action.get("id"))
                or self._proposal_action_label(action)
            ),
            "kind": kind,
            "details": details,
            "support": [],
            "skip": action.get("skip"),
            "action_index": action.get("action_index"),
            "group_action_indexes": [action.get("action_index")],
        }

    def _add_attachment_support(self, target, action):
        file_detail = self._proposal_detail(action, "File")
        if not file_detail:
            return None
        support = {
            "label": "Attached File",
            "value": file_detail["value"],
            "kind": "file",
            "details": [],
            "support": [],
            "skip": action.get("skip"),
            "action_index": action.get("action_index"),
            "group_action_indexes": [action.get("action_index")],
        }
        target.setdefault("support", []).append(support)
        return support

    def _add_move_file_support(self, target, action, action_labels):
        support = self._proposal_action_support(
            "Move File",
            action,
            "file",
            action_labels,
            exclude_labels={"File", "To Page", "To Task"},
        )
        file_detail = self._proposal_detail(action, "File")
        if file_detail and file_detail.get("value"):
            support["value"] = self._proposal_move_file_display_label(
                action,
                file_detail["value"],
            )
        target.setdefault("support", []).append(support)
        return support

    def _add_category_support(self, target, action, action_labels):
        support = self._proposal_action_support(
            "Add Category",
            action,
            "category",
            action_labels,
            exclude_labels={"Page", "Category"},
        )
        category_detail = self._proposal_detail(action, "Category")
        if category_detail and category_detail.get("value"):
            support["value"] = category_detail["value"]
        target.setdefault("support", []).append(support)
        return support

    def _add_page_form_support(self, target, action, action_labels):
        support = self._proposal_action_support(
            "Add Form",
            action,
            "form",
            action_labels,
            exclude_labels={"Page", "Form"},
        )
        form_detail = self._proposal_detail(action, "Form")
        if form_detail and form_detail.get("value"):
            support["value"] = form_detail["value"]
        target.setdefault("support", []).append(support)
        return support

    def _remember_file_support(self, file_targets, action, support):
        file_detail = self._proposal_detail(action, "File")
        if file_detail:
            file_targets[file_detail["value"]] = support
        for reference in self._proposal_file_references(action):
            file_targets[reference] = support

    def _file_support(self, file_targets, action):
        file_detail = self._proposal_detail(action, "File")
        if file_detail and file_detail["value"] in file_targets:
            return file_targets[file_detail["value"]]
        for reference in self._proposal_file_references(action):
            if reference in file_targets:
                return file_targets[reference]
        return None

    def _proposal_summary_support(self, action):
        data = action.get("data") or {}
        return {
            "label": "Summary",
            "value": (
                data.get("summary")
                or action.get("display_label")
                or "Generate summary for search"
            ),
            "kind": "file",
            "details": [],
            "support": [],
            "skip": action.get("skip"),
            "action_index": action.get("action_index"),
            "group_action_indexes": [action.get("action_index")],
        }

    def _proposal_file_references(self, action):
        data = action.get("data") or {}
        for key in [
            "file",
            "file_id",
            "file_ref",
            "display_name",
            "file_name",
            "file_label",
        ]:
            value = data.get(key)
            if isinstance(value, dict):
                value = value.get("file") or value.get("id") or value.get("key")
            if value:
                yield value

    def _consume_referenced_support_actions(self, actions, by_id, consumed_indexes):
        referenced_ids = set()
        for action in actions:
            if action["action_index"] in consumed_indexes:
                referenced_ids.update(self._proposal_referenced_action_ids(action))

        changed = True
        while changed:
            changed = False
            for action_id in list(referenced_ids):
                action = by_id.get(action_id)
                if not action or action["action_index"] in consumed_indexes:
                    continue
                consumed_indexes.add(action["action_index"])
                referenced_ids.update(self._proposal_referenced_action_ids(action))
                changed = True

    def _assign_proposal_group_indexes(self, roots, actions, by_id):
        actions_by_index = {
            action["action_index"]: action
            for action in actions
        }
        root_base_indexes = {
            id(root): self._proposal_support_indexes(root)
            for root in roots
        }
        root_references = {
            root_key: self._proposal_reference_closure(
                indexes,
                actions_by_index,
                by_id,
            )
            for root_key, indexes in root_base_indexes.items()
        }
        reference_counts = {}
        for references in root_references.values():
            for index in references:
                reference_counts[index] = reference_counts.get(index, 0) + 1

        for root in roots:
            root_key = id(root)
            private_references = {
                index
                for index in root_references[root_key]
                if reference_counts.get(index) == 1
            }
            root["group_action_indexes"] = sorted(
                root_base_indexes[root_key] | private_references
            )

    def _proposal_support_indexes(self, item):
        indexes = set()
        if item.get("action_index"):
            indexes.add(item["action_index"])
        for child in item.get("support") or []:
            indexes.update(self._proposal_support_indexes(child))
        return indexes

    def _proposal_reference_closure(self, indexes, actions_by_index, by_id):
        references = set()
        stack = list(indexes)
        while stack:
            action = actions_by_index.get(stack.pop())
            if not action:
                continue
            for action_id in self._proposal_referenced_action_ids(action):
                referenced_action = by_id.get(action_id)
                if (
                    not referenced_action
                    or referenced_action["action_index"] in references
                ):
                    continue
                references.add(referenced_action["action_index"])
                stack.append(referenced_action["action_index"])
        return references

    def _proposal_reference_action_id(self, action, *roots):
        data = action.get("data") or {}
        for root in roots:
            for key in [f"{root}_action", root, f"{root}_ref", f"{root}_id"]:
                value = data.get(key)
                action_id = self._proposal_action_reference(value, key)
                if action_id:
                    return action_id
        return None

    def _proposal_referenced_action_ids(self, action):
        references = set()
        for action_id in action.get("depends_on") or []:
            references.add(self._strip_proposal_action_reference(action_id))
        references.update(
            self._proposal_referenced_action_ids_from_value(action.get("data"))
        )
        return {reference for reference in references if reference}

    def _proposal_referenced_action_ids_from_value(self, value, key=None):
        references = set()
        if isinstance(value, dict):
            if value.get("action"):
                references.add(self._strip_proposal_action_reference(value["action"]))
            for child_key, child_value in value.items():
                references.update(
                    self._proposal_referenced_action_ids_from_value(
                        child_value,
                        child_key,
                    )
                )
        elif isinstance(value, list):
            for child in value:
                references.update(self._proposal_referenced_action_ids_from_value(child))
        elif isinstance(value, str):
            action_id = self._proposal_action_reference(value, key)
            if action_id:
                references.add(action_id)
        return references

    def _proposal_action_reference(self, value, key=None):
        if isinstance(value, dict):
            value = value.get("action")
        if not isinstance(value, str) or not value:
            return None
        if value.startswith("$") or value.startswith("action:"):
            return self._strip_proposal_action_reference(value)
        if key and key.endswith("_action"):
            return self._strip_proposal_action_reference(value)
        return None

    def _strip_proposal_action_reference(self, value):
        if not isinstance(value, str):
            return value
        if value.startswith("$"):
            return value[1:]
        if value.startswith("action:"):
            return value.split(":", 1)[1]
        return value

    def _proposal_detail(self, action, label):
        for detail in action.get("details", []):
            if detail.get("label") == label:
                return detail
        return None

    def _proposal_has_detail(self, action, label):
        return self._proposal_detail(action, label) is not None

    def _proposal_action_labels(self, actions):
        labels = {}
        for action in actions:
            action_id = action.get("id")
            if not action_id:
                continue
            label = self._proposal_action_label(action)
            if (action.get("type") or "").startswith("create_"):
                data = action.get("data") or {}
                targeted_task = action.get("type") == "create_task" and any(
                    data.get(key)
                    for key in ("task", "task_id", "task_ref", "task_action")
                )
                label = (
                    f"{label} (existing task)"
                    if targeted_task
                    else f"{label} (new)"
                )
            labels[action_id] = label
        return labels

    def _proposal_file_labels(self):
        labels = {}
        for file in self.entity.input_files or []:
            label = file.name or file.filename
            for key in [file.urlsafe_key, file.key, file.name, file.filename]:
                if key:
                    labels[key] = label
        return labels

    def _proposal_action_label(self, action):
        data = action.get("data") or {}
        if (action.get("type") or "").startswith("create_"):
            return (
                data.get("name")
                or action.get("display_label")
                or self._proposal_action_id_label(action)
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
                or self._proposal_action_id_label(action)
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

    def _proposal_action_id_label(self, action):
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id.strip():
            return None

        label = action_id.strip()
        action_type = action.get("type") or ""
        if action_type and label.startswith(f"{action_type}_"):
            label = label[len(action_type) + 1:]
        elif action_type.startswith("create_") and label.startswith("create_"):
            label = label[len("create_"):]

        if action_type.startswith("create_"):
            suffix = action_type.split("_", 1)[1]
            if label.endswith(f"_{suffix}"):
                label = label[: -(len(suffix) + 1)]

        label = re.sub(r"[_-]+", " ", label).strip()
        if not label:
            return None
        return label.title()

    def _proposal_move_file_display_label(self, action, fallback):
        data = action.get("data") or {}
        for key in ("display_name", "file_name", "file_label", "file_display"):
            value = data.get(key)
            if value:
                return value
        return self._proposal_action_id_label(action) or fallback

    def _proposal_action_details(self, action, data, action_labels, file_labels):
        details = []
        action_type = action.get("type")
        if action_type == "create_form":
            self._add_detail(
                details,
                "Form Type",
                data.get("form_type") or data.get("form-type"),
            )
        elif action_type == "create_category":
            self._add_ref_detail(
                details,
                "Form",
                self._first_data_value(data, "form"),
                action_labels,
                file_labels,
            )
        elif action_type == "create_model_task":
            self._add_ref_detail(
                details,
                "Project",
                self._first_data_value(data, "project"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Form",
                self._first_data_value(data, "form"),
                action_labels,
                file_labels,
            )
        elif action_type == "create_page":
            self._add_ref_detail(
                details,
                "Category",
                self._first_data_value(data, "category", "model"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Form",
                self._first_data_value(data, "form"),
                action_labels,
                file_labels,
            )
            self._add_submission_detail(
                details,
                data,
                form_present=bool(self._first_data_value(data, "form")),
            )
        elif action_type == "create_task":
            self._add_ref_detail(
                details,
                "Task",
                self._first_data_value(data, "task"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Page",
                self._first_data_value(data, "page"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Project",
                self._first_data_value(data, "project"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Model Task",
                self._first_data_value(data, "model"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Form",
                self._first_data_value(data, "form"),
                action_labels,
                file_labels,
            )
            self._add_detail(
                details,
                "Due Date",
                data.get("due_date") or data.get("due-date"),
            )
            self._add_detail(
                details,
                "Completed On",
                data.get("completed_on") or data.get("completed-on"),
            )
            if data.get("completed") is True and not (
                data.get("completed_on") or data.get("completed-on")
            ):
                self._add_detail(details, "Status", "Completed")
            self._add_submission_detail(
                details,
                data,
                form_present=bool(self._first_data_value(data, "form")),
                )
            for file_ref in self._proposal_file_values(data):
                self._add_ref_detail(
                    details,
                    "File",
                    file_ref,
                    action_labels,
                    file_labels,
                )
        elif action_type == "add_form_to_page":
            self._add_ref_detail(
                details,
                "Page",
                self._first_data_value(data, "page"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Form",
                self._first_data_value(data, "form"),
                action_labels,
                file_labels,
            )
        elif action_type == "add_category":
            self._add_ref_detail(
                details,
                "Page",
                self._first_data_value(data, "page"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Category",
                self._first_data_value(data, "category", "model"),
                action_labels,
                file_labels,
            )
        elif action_type == "rename_entity":
            self._add_ref_detail(
                details,
                "Entity",
                self._first_data_value(data, "entity"),
                action_labels,
                file_labels,
            )
            self._add_detail(details, "New Name", data.get("name"))
        elif action_type == "move_page":
            self._add_ref_detail(
                details,
                "Page",
                self._first_data_value(data, "page"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Category",
                self._first_data_value(data, "category", "model"),
                action_labels,
                file_labels,
            )
        elif action_type == "move_task":
            self._add_ref_detail(
                details,
                "Task",
                self._first_data_value(data, "task"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "Page",
                self._first_data_value(data, "to_page", "page"),
                action_labels,
                file_labels,
            )
        elif action_type == "move_file":
            self._add_ref_detail(
                details,
                "File",
                self._first_data_value(data, "file"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "From Page",
                self._first_data_value(data, "from_page", "source_page", "page_from"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "From Task",
                self._first_data_value(data, "from_task", "source_task", "task_from"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "To Page",
                self._first_data_value(
                    data,
                    "to_page",
                    "target_page",
                    "destination_page",
                    "page",
                ),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "To Task",
                self._first_data_value(
                    data,
                    "to_task",
                    "target_task",
                    "destination_task",
                    "task",
                ),
                action_labels,
                file_labels,
            )
        elif action_type == "update_form_schema":
            self._add_ref_detail(
                details,
                "Form",
                self._first_data_value(data, "form"),
                action_labels,
                file_labels,
            )
            self._add_detail(details, "Updates", self._operation_count(data))
        elif action_type == "update_submission_fields":
            self._add_detail(details, "Updates", self._submission_update_count(data))
        elif action_type == "attach_file_to_page":
            self._add_ref_detail(
                details,
                "Page",
                self._first_data_value(data, "page"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "File",
                self._first_data_value(data, "file"),
                action_labels,
                file_labels,
            )
        elif action_type == "attach_file_to_task":
            self._add_ref_detail(
                details,
                "Task",
                self._first_data_value(data, "task"),
                action_labels,
                file_labels,
            )
            self._add_ref_detail(
                details,
                "File",
                self._first_data_value(data, "file"),
                action_labels,
                file_labels,
            )
        elif action_type == "summarize_file":
            self._add_ref_detail(
                details,
                "File",
                self._first_data_value(data, "file"),
                action_labels,
                file_labels,
            )
            if data.get("summary"):
                self._add_detail(details, "Summary", data.get("summary"))
        return details

    def _operation_count(self, data):
        operations = data.get("operations")
        if isinstance(operations, list):
            return f"{len(operations)} schema change{'s' if len(operations) != 1 else ''}"
        return None

    def _submission_update_count(self, data):
        updates = data.get("updates")
        if isinstance(updates, list):
            return f"{len(updates)} field update{'s' if len(updates) != 1 else ''}"
        return None

    def _proposal_file_values(self, data):
        values = []
        for key in ["file", "file_id", "file_ref"]:
            value = data.get(key)
            if value:
                values.append(value)
        file_values = data.get("files") or data.get("file_refs") or []
        if isinstance(file_values, (str, dict)):
            file_values = [file_values]
        values.extend(file_values)
        return values

    def _add_submission_detail(self, details, data, form_present=False):
        if "submission" not in data and not form_present:
            return

        if data.get("submission_empty_reason"):
            self._add_detail(details, "Submission", data["submission_empty_reason"])
            return

        submission = data.get("submission")
        created = (
            bool(submission)
            if isinstance(submission, dict)
            else submission is not None
        )
        self._add_detail(details, "Submission", "created" if created else "missing")

    def _first_data_value(self, data, *roots):
        for root in roots:
            display_keys = [f"{root}_name", f"{root}_display", f"{root}_label"]
            if root == "file":
                display_keys.insert(0, "display_name")
            for key in display_keys:
                value = data.get(key)
                if value:
                    return {"_proposal_display_value": value}
            for key in [
                root,
                f"{root}_id",
                f"{root}_ref",
                f"{root}_action",
            ]:
                value = data.get(key)
                if value:
                    return value
        return None

    def _add_detail(self, details, label, value):
        if value:
            details.append(
                {
                    "label": label,
                    "value": value,
                    "kind": self._proposal_detail_kind(label),
                }
            )

    def _proposal_detail_kind(self, label):
        return {
            "Completed On": "default",
            "Category": "category",
            "Due Date": "default",
            "File": "file",
            "Form": "form",
            "Form Type": "form",
            "From Page": "page",
            "From Task": "task",
            "Model Task": "model",
            "Page": "page",
            "Project": "project",
            "Status": "default",
            "Submission": "default",
            "Task": "task",
            "To Page": "page",
            "To Task": "task",
            "Updates": "default",
        }.get(label, "default")

    def _add_ref_detail(self, details, label, value, action_labels, file_labels):
        resolved = self._resolve_proposal_detail(
            value,
            action_labels,
            file_labels,
            label,
        )
        if resolved:
            self._add_detail(details, label, resolved)

    def _resolve_proposal_detail(self, value, action_labels, file_labels, label=None):
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
            return self._proposal_entity_label(value) or value
        return None

    def _proposal_entity_label(self, value):
        details = self._proposal_entity_details(value)
        if details:
            return details.get("label")
        return None

    def _proposal_entity_details(self, value):
        if not isinstance(value, str):
            return None

        details = getattr(self, "_proposal_entity_details_cache", None)
        if details is None:
            details = self._load_proposal_entity_details()
            self._proposal_entity_details_cache = details
        return details.get(value)

    def _load_proposal_entity_details(self):
        from ..definitions import Fetch
        from ..entities import Entities

        actions = self.value.get("actions") if isinstance(self.value, dict) else []
        references = []
        for action in actions or []:
            references.extend(
                self._proposal_entity_reference_values(action.get("data") or {})
            )
        if not references:
            return {}

        loaded = Entities.fetch(
            *dict.fromkeys(references), request=Fetch.direct()
        )
        return {
            entity.urlsafe_key: self._proposal_entity_detail(entity)
            for entity in loaded
            if getattr(entity, "urlsafe_key", None) and getattr(entity, "name", None)
        }

    def _proposal_entity_detail(self, entity):
        detail = {
            "label": entity.name,
            "kind": getattr(entity, "kind", None),
        }
        category = self._proposal_entity_category_label(entity)
        if category:
            detail["category"] = category
        return detail

    def _proposal_entity_category_label(self, entity):
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

    def _proposal_entity_reference_values(self, data):
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
                references.extend(self._proposal_reference_strings(data.get(key)))
        return references

    def _proposal_reference_strings(self, value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return self._proposal_reference_strings(
                value.get("id") or value.get("key") or value.get("hash")
            )
        if isinstance(value, list):
            references = []
            for item in value:
                references.extend(self._proposal_reference_strings(item))
            return references
        return []


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020_ai_reports.py::test_grouped_result_actions_groups_completed_task_history_under_created_task
# @tests tests_unit/test_020_ai_reports.py::test_grouped_result_actions_groups_page_files_tasks_and_summaries
# @features ai-report
# @dimensions result grouping attachments completed-task-history
class Result(ReportProcessValue):
    """Structured deterministic run result for an AI report."""

    _id = "result"

    @property
    def grouped_actions(self):
        if not isinstance(self.value, dict):
            return []

        grouped = []
        by_entity_id = {}
        page_groups = {}
        task_groups = {}
        file_targets = {}
        for action in self.value.get("actions") or []:
            item = dict(action)
            target = item.get("target") or {}
            entity = item.get("entity") or {}
            action_type = item.get("type")

            if action_type == "attach_file_to_page":
                page_group = self._result_page_group(target, grouped, page_groups)
                if page_group:
                    page_group.setdefault("attachments", []).append(item)
                    self._remember_result_file_target(file_targets, item)
                    continue

            if action_type == "attach_file_to_task":
                task_group = task_groups.get(target.get("id")) or by_entity_id.get(
                    target.get("id")
                )
                if task_group:
                    task_group.setdefault("attachments", []).append(item)
                    self._remember_result_file_target(file_targets, item)
                    continue

            if action_type == "summarize_file":
                file_target = self._result_file_target(file_targets, item)
                if file_target:
                    self._merge_result_file_summary(file_target, item)
                    continue

            if action_type == "create_task" and entity.get("kind") == "task_history":
                task_group = task_groups.get(target.get("id")) or by_entity_id.get(
                    target.get("id")
                )
                if not task_group:
                    page_group = self._result_page_group(
                        item.get("page") or target.get("parent"),
                        grouped,
                        page_groups,
                    )
                    task_group = self._result_task_group(
                        target,
                        page_group,
                        task_groups,
                        by_entity_id,
                    )
                if task_group:
                    task_group.setdefault("histories", []).append(item)
                    if entity.get("id"):
                        by_entity_id[entity["id"]] = item
                    self._remember_result_attachment_targets(file_targets, item)
                    continue

            if action_type == "create_task":
                self._remember_result_attachment_targets(file_targets, item)
                page_group = self._result_page_group(
                    item.get("page") or entity.get("parent"),
                    grouped,
                    page_groups,
                )
                if page_group:
                    page_group.setdefault("tasks", []).append(item)
                    if entity.get("id"):
                        by_entity_id[entity["id"]] = item
                        task_groups[entity["id"]] = item
                    continue

            if entity.get("kind") == "page" and entity.get("id"):
                grouped.append(item)
                by_entity_id[entity["id"]] = item
                page_groups[entity["id"]] = item
                continue

            grouped.append(item)
            if entity.get("id"):
                by_entity_id[entity["id"]] = item
                if entity.get("kind") == "task":
                    task_groups[entity["id"]] = item

        return grouped

    def _result_page_group(self, page, grouped, page_groups):
        if not isinstance(page, dict) or not page.get("id"):
            return None
        page_id = page["id"]
        if page_id in page_groups:
            return page_groups[page_id]

        group = {
            "id": f"page:{page_id}",
            "type": "page_group",
            "title": page.get("name") or "Page",
            "status": "complete",
            "created": False,
            "entity": page,
        }
        grouped.append(group)
        page_groups[page_id] = group
        return group

    def _result_task_group(self, task, page_group, task_groups, by_entity_id):
        if not page_group or not isinstance(task, dict) or not task.get("id"):
            return None
        task_id = task["id"]
        if task_id in task_groups:
            return task_groups[task_id]

        group = {
            "id": f"task:{task_id}",
            "type": "create_task",
            "title": task.get("name") or "Task",
            "status": "complete",
            "created": False,
            "entity": task,
            "page": page_group.get("entity"),
        }
        page_group.setdefault("tasks", []).append(group)
        task_groups[task_id] = group
        by_entity_id[task_id] = group
        return group

    def _remember_result_file_target(self, file_targets, action):
        entity = action.get("entity") or {}
        for value in (entity.get("id"), entity.get("name")):
            if value:
                file_targets[value] = action

    def _remember_result_attachment_targets(self, file_targets, action):
        for attachment in action.get("attachments") or []:
            self._remember_result_file_target(file_targets, attachment)

    def _result_file_target(self, file_targets, action):
        entity = action.get("entity") or {}
        for value in (entity.get("id"), entity.get("name")):
            target = file_targets.get(value)
            if target:
                return target
        return None

    def _merge_result_file_summary(self, file_target, summary_action):
        summary = summary_action.get("file_summary")
        if summary:
            file_target["file_summary"] = summary
            file_target["summary"] = summary
        file_target.setdefault("summaries", []).append(summary_action)


# @testable false
# @covered-by lagniappe/core/properties/ai_report.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Error(ReportProcessValue):
    """User-facing AI report error message."""

    _id = "error"


# @testable false
# @covered-by lagniappe/core/properties/ai_report.py::ReportProcess
# @reason bool coercion is exercised through report process state
class Pending(ReportProcessValue):
    """Whether an AI report still represents work in progress."""

    _id = "pending"
    _truthy = {True, "true", "True", "1", 1, "on", "yes"}

    @property
    def value(self):
        return getattr(self.process, self.process_attribute) in self._truthy

    @value.setter
    def value(self, value):
        pending = value in self._truthy
        setattr(self.process, self.process_attribute, True if pending else None)
        self.entity.db.pop(self.id, None)
        self._clear_cached_entity_views()


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_create_and_file_cleanup
# @features ai-report
# @dimensions status
class Note(Property):
    """User-facing note derived from the report process state."""

    _id = "note"

    @property
    def value(self):
        if self.entity.error:
            return self.entity.error
        if self.entity.summary:
            return self.entity.summary
        pending = {
            "ask": "Thinking...",
            "create": "Planning creation...",
        }.get(self.entity.tool, "Analyzing files...")
        labels = {
            "pending": pending,
            "revising": "Revising report...",
            "ready": "Ready to run",
            "running": "Running report...",
            "complete": "Report complete",
            "failed": "Report failed",
        }
        return labels.get(self.entity.status, "Report created")
