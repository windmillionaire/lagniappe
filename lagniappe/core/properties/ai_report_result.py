"""Read-only grouped projection for AI report execution results."""

from .ai_report_process import ReportProcessValue

# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020h_ai_report_execution.py::test_grouped_result_actions_groups_completed_task_history_under_created_task
# @tests tests_unit/test_020h_ai_report_execution.py::test_grouped_result_actions_groups_page_files_tasks_and_summaries
# @matrix ai-report : attachments completed-task-history grouping result
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
