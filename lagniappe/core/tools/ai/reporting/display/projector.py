"""Grouped display projection for stored AI report proposals."""

import json

from .contracts import ProposalActionGrouping
from .details import ProposalDetailCollector
from .references import ProposalReferenceResolver
from .registry import proposal_action_display


# @testable infrastructure
class ProposalDisplayProjector:
    """Compose registered action adapters into a grouped display tree."""

    def __init__(self, proposal):
        self.proposal = proposal
        self.references = ProposalReferenceResolver(proposal)

    @property
    def value(self):
        return self.proposal.value

    # @testable true
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_decision_details
    # @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_shows_proposed_submission_values
    # @matrix ai-report : details proposal submission-review
    # @pair form-schema:submission-review
    @property
    def display_actions(self):
        if not isinstance(self.value, dict):
            return []

        self.references.reset()
        actions = self.value.get("actions") or []
        action_labels = self.references.action_labels(actions)
        file_labels = self.references.file_labels()
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
        actions_by_id = {action["id"]: action for action in actions if action.get("id")}
        for index, action in enumerate(actions, 1):
            definition = proposal_action_display(action.get("type"))
            if definition.hidden:
                continue
            item = dict(action)
            data = item.get("data") or {}
            item["data"] = data
            item["action_index"] = index
            item["support"] = []
            details = ProposalDetailCollector(
                action_labels,
                file_labels,
                self.references.entity_label,
            )
            if definition.details:
                definition.details(details, data, item)
            self._add_submission_preview(details, data, actions_by_id)
            item["details"] = details.values
            item["display_label"] = self._proposal_display_action_label(item)
            display_actions.append(item)

        return display_actions

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/display/projector.py::ProposalDisplayProjector.display_actions
    # @reason display_actions owns the schema-aware proposal detail projection
    def _add_submission_preview(self, details, data, actions_by_id):
        preview = self._proposal_submission_details(data, actions_by_id)
        if not preview:
            return
        for detail in reversed(details.values):
            if detail.get("label") == "Submission" and detail.get("value") == "created":
                detail["items"] = preview
                return

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/display/projector.py::ProposalDisplayProjector.display_actions
    # @reason display_actions owns the schema-aware proposal detail projection
    def _proposal_submission_details(self, data, actions_by_id):
        submission = data.get("submission")
        if not isinstance(submission, dict) or not submission:
            return []

        schema = self._proposal_submission_schema(data, actions_by_id)
        fields = {
            field.get("id"): field
            for field in schema
            if isinstance(field, dict) and field.get("id")
        }
        return [
            {
                "label": (fields.get(field_id) or {}).get("title") or field_id,
                "value": self._proposal_submission_value(
                    value,
                    fields.get(field_id),
                ),
                "kind": "default",
            }
            for field_id, value in submission.items()
        ]

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/display/projector.py::ProposalDisplayProjector.display_actions
    # @reason display_actions owns the schema-aware proposal detail projection
    def _proposal_submission_schema(self, data, actions_by_id, visited=None):
        schema = data.get("schema")
        if isinstance(schema, list):
            return schema

        visited = visited or set()
        action = {"data": data}
        for root in ("form", "category", "model", "project", "task"):
            action_id = self.references.reference_action_id(action, root)
            if action_id and action_id not in visited:
                visited.add(action_id)
                source = actions_by_id.get(action_id)
                source_schema = self._proposal_submission_schema(
                    (source or {}).get("data") or {},
                    actions_by_id,
                    visited,
                )
                if source_schema:
                    return source_schema

            reference = self.references.existing_entity_reference(action, root)
            entity_details = (
                self.references.entity_details(reference) if reference else None
            )
            entity_schema = (entity_details or {}).get("schema")
            if isinstance(entity_schema, list):
                return entity_schema
        return []

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/display/projector.py::ProposalDisplayProjector.display_actions
    # @reason display_actions owns the human-readable proposal value projection
    def _proposal_submission_value(self, value, field):
        def display(item, item_field=None):
            item_field = item_field or {}
            field_type = item_field.get("type")
            options = [
                (option.get("value"), option.get("label"))
                for option in item_field.get("options") or []
                if isinstance(option, dict) and option.get("label")
            ]
            for option_value, option_label in options:
                if item == option_value:
                    return option_label
            if isinstance(item, bool):
                return "Yes" if item else "No"
            if item is None:
                return "None"
            if field_type == "table":
                rows = item.get("rows") if isinstance(item, dict) else item
                count = len(rows) if isinstance(rows, list) else 0
                return f"{count} {'row' if count == 1 else 'rows'}"
            if field_type == "todo":
                items = item.get("items") if isinstance(item, dict) else item
                count = len(items) if isinstance(items, list) else 0
                complete = sum(
                    1
                    for todo in items or []
                    if isinstance(todo, dict) and todo.get("checked") is True
                )
                noun = "item" if count == 1 else "items"
                return f"{count} {noun} ({complete} complete)"
            if field_type == "signature":
                return "Provided" if item else "Not provided"
            if field_type == "html":
                return "Content provided" if item else "(blank)"
            if (
                field_type == "link"
                and item_field.get("location") == "in"
                and isinstance(item, str)
            ):
                if self.references.reference_is_opaque(item):
                    return (
                        self.references.entity_label(item)
                        or "Linked item unavailable"
                    )
                return item
            if isinstance(item, dict):
                columns = [
                    column
                    for column in item_field.get("columns") or []
                    if isinstance(column, dict) and column.get("id")
                ]
                if columns:
                    by_id = {column["id"]: column for column in columns}
                    ordered_ids = [
                        column["id"] for column in columns if column["id"] in item
                    ]
                    ordered_ids.extend(key for key in item if key not in by_id)
                    return "; ".join(
                        f"{(by_id.get(key) or {}).get('title') or key}: "
                        f"{display(item[key], by_id.get(key))}"
                        for key in ordered_ids
                    )
                name = item.get("name") or item.get("label")
                address = item.get("address") or item.get("formatted_address")
                if name and address and name != address:
                    return f"{name} — {address}"
                if name or address:
                    return str(name or address)
                if field_type == "link":
                    return str(item.get("title") or item.get("url") or "Link provided")
                return json.dumps(item, ensure_ascii=False, sort_keys=True)
            if isinstance(item, list):
                return ", ".join(display(child, item_field) for child in item)
            if item == "":
                return "(blank)"
            return str(item)

        rendered = " ".join(display(value, field).split())
        return f"{rendered[:297]}..." if len(rendered) > 300 else rendered

    # @testable true
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_group_move_files_under_target_page
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_groups_added_categories_under_page
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_group_completed_task_events
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_group_schema_updates_separately
    # @matrix ai-report categories files : grouped-display
    # @pairs ai-report:existing-page-category form-schema:schema-section
    def _group_proposal_display_actions(self, actions, action_labels, file_labels):
        by_id = {action["id"]: action for action in actions if action.get("id")}
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
            grouping = proposal_action_display(action.get("type")).grouping
            if grouping is ProposalActionGrouping.PAGE:
                roots.append(action)
                consumed_indexes.add(action["action_index"])
            elif grouping is ProposalActionGrouping.TASK:
                page_ref = self.references.reference_action_id(action, "page")
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
            elif grouping is ProposalActionGrouping.PAGE_ATTACHMENT:
                page_ref = self.references.reference_action_id(action, "page")
                target = targets.get(page_ref)
                if not target:
                    target = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                support = (
                    self._add_attachment_support(target, action) if target else None
                )
                if support:
                    consumed_indexes.add(action["action_index"])
                    self._remember_file_support(file_targets, action, support)
            elif grouping is ProposalActionGrouping.TASK_ATTACHMENT:
                task_ref = self.references.reference_action_id(action, "task")
                target = targets.get(task_ref)
                support = (
                    self._add_attachment_support(target, action) if target else None
                )
                if support:
                    consumed_indexes.add(action["action_index"])
                    self._remember_file_support(file_targets, action, support)
            elif grouping is ProposalActionGrouping.PAGE_FORM:
                page_ref = self.references.reference_action_id(action, "page")
                target = targets.get(page_ref)
                if not target:
                    target = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                support = (
                    self._add_page_form_support(
                        target,
                        action,
                        action_labels,
                    )
                    if target
                    else None
                )
                if support:
                    consumed_indexes.add(action["action_index"])
            elif grouping is ProposalActionGrouping.PAGE_CATEGORY:
                page_ref = self.references.reference_action_id(action, "page")
                target = targets.get(page_ref)
                if not target:
                    target = self._proposal_page_group(
                        action,
                        roots,
                        page_groups,
                        action_labels,
                        file_labels,
                    )
                support = (
                    self._add_category_support(
                        target,
                        action,
                        action_labels,
                    )
                    if target
                    else None
                )
                if support:
                    consumed_indexes.add(action["action_index"])
            elif grouping is ProposalActionGrouping.FILE_MOVE:
                target = self._proposal_move_file_target(
                    action,
                    roots,
                    page_groups,
                    targets,
                    action_labels,
                    file_labels,
                )
                support = (
                    self._add_move_file_support(
                        target,
                        action,
                        action_labels,
                    )
                    if target
                    else None
                )
                if support:
                    consumed_indexes.add(action["action_index"])
            elif grouping is ProposalActionGrouping.FILE_SUMMARY:
                file_support = self._file_support(file_targets, action)
                if file_support:
                    file_support["support"].append(
                        self._proposal_summary_support(action)
                    )
                    consumed_indexes.add(action["action_index"])
            elif grouping is ProposalActionGrouping.SCHEMA:
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
            elif grouping is ProposalActionGrouping.REVIEW:
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
        page_ref = self.references.existing_entity_reference(action, "page")
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
            label = self.references.resolve_detail(
                page_ref,
                action_labels,
                file_labels,
                "Page",
            )
        if not label or (
            label == page_ref and self.references.reference_is_opaque(label)
        ):
            return None
        return label

    def _proposal_existing_page_details(self, page_ref):
        entity_details = self.references.entity_details(page_ref)
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
            target = targets.get(self.references.reference_action_id(action, root))
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
        page_ref = self.references.existing_entity_reference(action, root)
        if not page_ref:
            return None

        page_action = {
            "data": {"page": page_ref},
            "details": [],
        }
        page_label = self.references.reference_display_label(action, root)
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

    def _assign_proposal_page_group_indexes(self, roots, actions):
        actions_by_index = {action["action_index"]: action for action in actions}
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
                (actions_by_index.get(index) or {}).get("skip") for index in indexes
            )

    def _proposal_display_action_label(self, action):
        action_type = action.get("type") or ""
        definition = proposal_action_display(action_type)
        data = action.get("data") or {}
        label = (
            data.get("name")
            or action.get("display_label")
            or self.references.action_label(action)
        )
        if definition.prefer_file_label:
            label = self.references.move_file_display_label(action, label)
        elif definition.label_detail:
            detail = self._proposal_detail(action, definition.label_detail)
            if detail and detail.get("value"):
                label = detail["value"]
        if action_type.startswith("create_"):
            targeted_task = action_type == "create_task" and any(
                data.get(key) for key in ("task", "task_id", "task_ref", "task_action")
            )
            label = f"{label} (existing task)" if targeted_task else f"{label} (new)"
        prefix = definition.prefix
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
        definition = proposal_action_display(action.get("type"))
        for inherited in definition.inherited_details:
            reference = self.references.reference_action_id(
                action,
                *inherited.reference_roots,
            )
            source = by_id.get(reference)
            source_data = source.get("data") if source else None
            if source_data and not self._proposal_has_detail(action, inherited.label):
                details = ProposalDetailCollector(
                    action_labels,
                    file_labels,
                    self.references.entity_label,
                )
                details.add_reference(
                    inherited.label,
                    details.first_value(source_data, *inherited.value_roots),
                )
                action["details"].extend(details.values)

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
                or self.references.action_label(action)
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
            support["value"] = self.references.move_file_display_label(
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
                referenced_ids.update(self.references.referenced_action_ids(action))

        changed = True
        while changed:
            changed = False
            for action_id in list(referenced_ids):
                action = by_id.get(action_id)
                if not action or action["action_index"] in consumed_indexes:
                    continue
                consumed_indexes.add(action["action_index"])
                referenced_ids.update(self.references.referenced_action_ids(action))
                changed = True

    def _assign_proposal_group_indexes(self, roots, actions, by_id):
        actions_by_index = {action["action_index"]: action for action in actions}
        root_base_indexes = {
            id(root): self._proposal_support_indexes(root) for root in roots
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
            for action_id in self.references.referenced_action_ids(action):
                referenced_action = by_id.get(action_id)
                if (
                    not referenced_action
                    or referenced_action["action_index"] in references
                ):
                    continue
                references.add(referenced_action["action_index"])
                stack.append(referenced_action["action_index"])
        return references

    def _proposal_detail(self, action, label):
        for detail in action.get("details", []):
            if detail.get("label") == label:
                return detail
        return None

    def _proposal_has_detail(self, action, label):
        return self._proposal_detail(action, label) is not None
