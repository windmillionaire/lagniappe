"""User capability projection for AI report actions."""

from .actions import ACTION_ORDER


# @testable true
# @tests tests_unit/test_020d_ai_report_prompts.py::test_report_prompts_filter_actions_by_user_permissions
# @matrix ai-report : action-capabilities permissions
def allowed_report_actions(user):
    """Return report action types this user may ask the runner to execute."""
    capabilities = user.properties.restrictions.ai_action_capabilities
    allowed = {"skip", "needs_review"}

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
    if capabilities["can_create_tasks"]:
        allowed.add("create_task")
    if capabilities["can_attach_files_to_pages"]:
        allowed.add("add_form_to_page")
        allowed.add("attach_file_to_page")
    if capabilities["can_attach_files_to_tasks"]:
        allowed.add("attach_file_to_task")
    if capabilities["can_move_pages"]:
        allowed.add("add_category")
        allowed.add("move_page")
    if capabilities["can_move_tasks"]:
        allowed.add("move_task")
    if capabilities["can_move_files"]:
        allowed.add("move_file")
    if capabilities["can_rename_entities"]:
        allowed.add("rename_entity")
    if capabilities["can_update_form_schemas"]:
        allowed.add("update_form_schema")
    if capabilities["can_update_submissions"]:
        allowed.add("update_submission_fields")
    if capabilities["can_delete_pages"]:
        allowed.add("delete_page")

    return tuple(action for action in ACTION_ORDER if action in allowed)


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @reason prompt text is verified through public prompt builders
def report_action_permission_context(user, allowed_actions=None):
    allowed = tuple(allowed_actions or allowed_report_actions(user))
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
        "can_create_tasks": (
            user_capabilities["can_create_tasks"] and "create_task" in allowed_set
        ),
        "can_attach_files_to_pages": (
            user_capabilities["can_attach_files_to_pages"]
            and "attach_file_to_page" in allowed_set
        ),
        "can_add_forms_to_pages": (
            user_capabilities["can_attach_files_to_pages"]
            and "add_form_to_page" in allowed_set
        ),
        "can_attach_files_to_tasks": (
            user_capabilities["can_attach_files_to_tasks"]
            and "attach_file_to_task" in allowed_set
        ),
        "can_move_pages": (
            user_capabilities["can_move_pages"]
            and bool({"add_category", "move_page"} & allowed_set)
        ),
        "can_move_tasks": (
            user_capabilities["can_move_tasks"] and "move_task" in allowed_set
        ),
        "can_move_files": (
            user_capabilities["can_move_files"] and "move_file" in allowed_set
        ),
        "can_rename_entities": (
            user_capabilities["can_rename_entities"] and "rename_entity" in allowed_set
        ),
        "can_update_form_schemas": (
            user_capabilities["can_update_form_schemas"]
            and "update_form_schema" in allowed_set
        ),
        "can_update_submissions": (
            user_capabilities["can_update_submissions"]
            and "update_submission_fields" in allowed_set
        ),
        "can_delete_pages": (
            user_capabilities["can_delete_pages"] and "delete_page" in allowed_set
        ),
    }
    rules = ["Only return action types listed in allowed_actions."]
    if "create_page" in allowed_set:
        rules.append("Creating pages requires an editable category.")
    if "create_model_task" in allowed_set:
        rules.append("Creating model tasks requires an editable project.")
    if "create_task" in allowed_set:
        rules.append("Creating tasks requires an editable target.")
    if {"attach_file_to_page", "attach_file_to_task"} & allowed_set:
        rules.append("Attaching files requires an editable target.")
    if "add_form_to_page" in allowed_set:
        rules.append(
            "Adding a form to a page requires an editable page and does not require a category."
        )
    if "add_category" in allowed_set:
        rules.append(
            "Adding page categories requires editable source and target entities."
        )
    if {"move_page", "move_task"} & allowed_set:
        rules.append("Moving pages/tasks requires editable source and target entities.")
    if "move_file" in allowed_set:
        rules.append("Moving files requires editable source and target pages or tasks.")
    if "rename_entity" in allowed_set:
        rules.append("Renaming requires an exact editable entity target.")
    if "update_form_schema" in allowed_set:
        rules.append("Schema edits are additive only and require editable forms.")
    if "update_submission_fields" in allowed_set:
        rules.append("Submission updates require exact editable page/task targets.")
    if "delete_page" in allowed_set:
        rules.append("Page deletion is manual cleanup rendered after report execution.")
    rules.append(
        "If the useful action is not allowed, use needs_review or answer without actions."
    )
    return {
        "allowed_actions": list(allowed),
        "capabilities": capabilities,
        "rules": rules,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @reason filtered contracts are observed through prompt output tests
def permission_filtered_output_contract(contract, allowed_actions):
    allowed_lines = "\n".join(f"- {action}" for action in allowed_actions)
    marker = "Allowed action types:"
    next_section = "\n\nReference rules:"
    if marker not in contract or next_section not in contract:
        return contract
    before, rest = contract.split(marker, 1)
    _old_actions, after = rest.split(next_section, 1)
    return f"{before}{marker}\n{allowed_lines}{next_section}{after}"


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::organize_prompt
# @covered-by lagniappe/core/tools/ai/ask.py::ask_prompt
# @reason permission instruction composition is verified through prompt tests
def report_action_permission_instructions():
    return """
The allowed action list is user-specific. Do not include action types that are
not listed in Report Action Permissions. When using an existing category,
project, page, task, or model task, first confirm the relevant tool result says
it can be edited for the intended action. If a useful workspace change would
require a forbidden action or an uneditable target, return needs_review or
explain the limitation instead of proposing work the runner will reject.
    """
