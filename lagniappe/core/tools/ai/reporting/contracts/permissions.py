"""User capability projection for AI report actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from lagniappe.core.entities import types as models


from .actions import ACTION_ORDER


def allowed_report_actions(user: models.User) -> tuple[str, ...]:
    """Return report action types this user may ask the runner to execute."""
    capabilities = user.properties.restrictions.ai_action_capabilities
    allowed = {"create_task", "complete_task", "skip", "needs_review", "update_task", "update_page", "update_project", "update_category", "update_model_task", "update_file"}

    if capabilities["can_create_forms"]:
        allowed.add("create_form")
    if capabilities["can_create_categories"]:
        allowed.add("create_category")
    if capabilities["can_create_projects"]:
        allowed.add("create_project")
    if capabilities["can_create_model_tasks"]:
        allowed.add("create_model_task")
    if capabilities["can_create_pages"]:
        allowed.add("create_page")
    if capabilities["can_update_pages"]:
        allowed.update({"append_page_document", "replace_page_document"})
    if capabilities["can_update_pages"] or capabilities["can_update_tasks"]:
        allowed.add("attach_file")
        allowed.add("move_file")
    if capabilities["can_update_tasks"] and capabilities["can_update_pages"]:
        allowed.add("move_task")
    if capabilities["can_update_forms"]:
        allowed.add("update_form_schema")
    if capabilities["can_delete_pages"]:
        allowed.add("suggest_page_deletion")
        allowed.add("delete_page")
    if capabilities.get("can_delete_categories"):
        allowed.add("delete_category")
    if capabilities.get("can_delete_projects"):
        allowed.update({"delete_project", "delete_model_task"})
    if capabilities.get("can_delete_tasks"):
        allowed.add("delete_task")
    if capabilities.get("can_delete_files"):
        allowed.add("delete_file")

    return tuple(action for action in ACTION_ORDER if action in allowed)


def report_action_permission_context(
    user: models.User, allowed_actions: Iterable[str] | None = None
) -> dict[str, list[str]]:
    allowed = tuple(allowed_report_actions(user) if allowed_actions is None else allowed_actions)
    allowed_set = set(allowed)
    rules = ["Only return action types listed in allowed_actions."]
    if {"update_page", "update_task", "update_project", "update_category", "update_model_task"} & allowed_set:
        rules.append("Cohesive updates require exact editable targets. Use data.entity and data.changes. Omitted fields remain unchanged; form reassignment requires complete target submission. Existing-form submission patches preserve unmentioned answer IDs. Completed tasks cannot be restructured. Model-task form changes affect future tasks only. Project model_tasks ordering includes every model exactly once. Use $action_id for earlier creations. Documents support append or explicit whole-document replacement with a recovery pin; inline edits require the editor.")
    if "create_page" in allowed_set:
        rules.append("Creating pages requires an editable category.")
    if "create_model_task" in allowed_set:
        rules.append("Creating model tasks requires an editable project.")
    if "create_task" in allowed_set:
        rules.append("Creating tasks requires an editable target.")
    if "complete_task" in allowed_set:
        rules.append("Completing tasks requires an exact editable Task and its required fields.")
    if "append_page_document" in allowed_set:
        rules.append("Document appends require an exact editable Page and preserve existing content.")
    if "replace_page_document" in allowed_set:
        rules.append("Document replacement requires an exact editable Page, explicit user intent, and the complete replacement text. The previous document is pinned before the collaborative edit.")
    if "attach_file" in allowed_set:
        rules.append("Attaching files requires an editable target. Each File has one owning Page or Task; attach_file never moves an already-owned File. Repeating the same attachment is a no-op. Use move_file for explicit ownership changes, or the existing File URL for references elsewhere. TaskHistory evidence remains owned by its live Task.")
    if "move_task" in allowed_set:
        rules.append("Moving tasks requires editable source and target entities.")
    if "move_file" in allowed_set:
        rules.append("Moving files requires editable source and target pages or tasks.")
    if "update_file" in allowed_set:
        rules.append("File name and description edits use update_file with an exact editable File. Omitted fields preserve values; description=null clears it. This preserves the file's contents and location, and requires no upload or file_usage entry for the existing File.")
    if "update_form_schema" in allowed_set:
        rules.append("Schema edits require editable forms and user review. Preview migrations across every affected Page/Task, explain destructive changes, and require visibility of the complete population.")
    if "suggest_page_deletion" in allowed_set:
        rules.append("Page deletion is manual cleanup rendered after report execution.")
    if {"delete_page", "delete_task", "delete_category", "delete_project", "delete_model_task", "delete_file"} & allowed_set:
        rules.append("Delete actions permanently remove existing records (never user personal pages or Uncategorized Pages) and pause for browser confirmation on ordinary user accounts.")
    rules.append(
        "If the useful action is not allowed, use needs_review or answer without actions."
        if "needs_review" in allowed_set
        else "If the useful action is not allowed, explain the limitation and answer without actions."
    )
    return {
        "allowed_actions": list(allowed),
        "rules": rules,
    }
