"""User capability projection for AI report actions."""

from .actions import ACTION_ORDER


# @testable true
# @matrix ai-report : action-capabilities permissions
# @pair permissions:own-page
def allowed_report_actions(user):
    """Return report action types this user may ask the runner to execute."""
    capabilities = user.properties.restrictions.ai_action_capabilities
    allowed = {"create_task", "complete_task", "skip", "needs_review", "update_task", "update_page", "update_project", "update_model_task"}

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
    if capabilities["can_append_page_documents"]:
        allowed.add("append_page_document")
    if capabilities["can_attach_files_to_pages"]:
        allowed.add("attach_file")
    if capabilities["can_attach_files_to_tasks"]:
        allowed.add("attach_file")
    if capabilities["can_move_tasks"]:
        allowed.add("move_task")
    if capabilities["can_move_files"]:
        allowed.add("move_file")
    if capabilities["can_update_form_schemas"]:
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
    user_capabilities = user.properties.restrictions.ai_action_capabilities
    capabilities = {
        "can_create_forms": (
            user_capabilities["can_create_forms"] and "create_form" in allowed_set
        ),
        "can_create_categories": (
            user_capabilities["can_create_categories"]
            and "create_category" in allowed_set
        ),
        "can_create_projects": (
            user_capabilities["can_create_projects"] and "create_project" in allowed_set
        ),
        "can_create_pages": (
            user_capabilities["can_create_pages"] and "create_page" in allowed_set
        ),
        "can_create_model_tasks": (
            user_capabilities["can_create_model_tasks"]
            and "create_model_task" in allowed_set
        ),
        "can_attach_files_to_pages": (
            user_capabilities["can_attach_files_to_pages"]
            and "attach_file" in allowed_set
        ),
        "can_append_page_documents": (
            user_capabilities["can_append_page_documents"] and "append_page_document" in allowed_set
        ),
        "can_add_forms_to_pages": (
            user_capabilities["can_attach_files_to_pages"]
            and "update_page" in allowed_set
        ),
        "can_attach_files_to_tasks": (
            user_capabilities["can_attach_files_to_tasks"]
            and "attach_file" in allowed_set
        ),
        "can_move_pages": (
            user_capabilities["can_move_pages"]
            and "update_page" in allowed_set
        ),
        "can_move_tasks": (
            user_capabilities["can_move_tasks"] and "move_task" in allowed_set
        ),
        "can_move_files": (
            user_capabilities["can_move_files"] and "move_file" in allowed_set
        ),
        "can_rename_entities": (
            user_capabilities["can_rename_entities"] and bool({"update_page", "update_task", "update_project", "update_model_task"} & allowed_set)
        ),
        "can_update_form_schemas": (
            user_capabilities["can_update_form_schemas"]
            and "update_form_schema" in allowed_set
        ),
        "can_update_submissions": (
            user_capabilities["can_update_submissions"]
            and bool({"update_page", "update_task"} & allowed_set)
        ),
        "can_delete_pages": (
            user_capabilities["can_delete_pages"] and "suggest_page_deletion" in allowed_set
        ),
    }
    rules = ["Only return action types listed in allowed_actions.", "Cohesive updates require exact editable targets. Use data.entity and data.changes. Omitted fields remain unchanged; form reassignment requires complete target submission. Existing-form submission patches preserve unmentioned answer IDs. Completed tasks cannot be restructured. Model-task form changes affect future tasks only. Project model_tasks ordering includes every model exactly once. Use $action_id for earlier creations. Documents support append only; inline replacement or deletion requires the editor."]
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
    if "update_form_schema" in allowed_set:
        rules.append("Schema edits require editable forms and user review. Preview migrations across every affected Page/Task, explain destructive changes, and require visibility of the complete population.")
    if "suggest_page_deletion" in allowed_set:
        rules.append("Page deletion is manual cleanup rendered after report execution.")
    rules.append(
        "If the useful action is not allowed, use needs_review or answer without actions."
    )
    return {
        "allowed_actions": list(allowed),
        "capabilities": capabilities,
        "rules": rules,
    }
