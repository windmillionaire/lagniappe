"""User capability projection for AI report actions."""

from .actions import ACTION_ORDER


# @testable true
# @matrix ai-report : action-capabilities permissions
# @pair permissions:own-page
def allowed_report_actions(user):
    """Return report action types this user may ask the runner to execute."""
    capabilities = user.properties.restrictions.ai_action_capabilities
    allowed = {"create_task", "complete_task", "skip", "needs_review", "update_task", "update_page", "update_project", "update_model_task", "update_file"}

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
        allowed.add("append_page_document")
    if capabilities["can_update_pages"] or capabilities["can_update_tasks"]:
        allowed.add("attach_file")
        allowed.add("move_file")
    if capabilities["can_update_tasks"] and capabilities["can_update_pages"]:
        allowed.add("move_task")
    if capabilities["can_update_forms"]:
        allowed.add("update_form_schema")
    if capabilities["can_delete_pages"]:
        allowed.add("suggest_page_deletion")

    return tuple(action for action in ACTION_ORDER if action in allowed)


# @testable false
# @covered-by lagniappe/core/tools/ai/planner.py::report_prompt
# @reason prompt text is verified through public prompt builders
def report_action_permission_context(user, allowed_actions=None):
    allowed = tuple(allowed_report_actions(user) if allowed_actions is None else allowed_actions)
    allowed_set = set(allowed)
    rules = ["Only return action types listed in allowed_actions."]
    if {"update_page", "update_task", "update_project", "update_model_task"} & allowed_set:
        rules.append("Cohesive updates require exact editable targets. Use data.entity and data.changes. Omitted fields remain unchanged; form reassignment requires complete target submission. Existing-form submission patches preserve unmentioned answer IDs. Completed tasks cannot be restructured. Model-task form changes affect future tasks only. Project model_tasks ordering includes every model exactly once. Use $action_id for earlier creations. Documents support append only; inline replacement or deletion requires the editor.")
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
    if "attach_file" in allowed_set:
        rules.append("Attaching files requires an editable target.")
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
    rules.append(
        "If the useful action is not allowed, use needs_review or answer without actions."
        if "needs_review" in allowed_set
        else "If the useful action is not allowed, explain the limitation and answer without actions."
    )
    return {
        "allowed_actions": list(allowed),
        "rules": rules,
    }
