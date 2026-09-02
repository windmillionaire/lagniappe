"""
AI tool declarations and execution handlers for Gemini function calling.

Provides tools that let the AI query the app's data at generation time:
- search_entities: full-text search across the workspace
- get_entity: load full details of a specific entity
- get_file: retrieve file content and attach supported small files for analysis
- get_category_pages: sample pages from a category to understand its content
- get_page_details: load a page, its model category, and optionally its tasks
- get_page_file_list: list files attached to a page
- get_page_tasks: load a page's tasks
- get_task_history: load completion history for a task
- get_category_details: load a page's model category
- list_workspace_resources: inventory categories, projects, model tasks, forms
- get_schema: load one form schema for a form, page, task, or model task
- get_form_instances: load pages/tasks using a form for reviewed batch updates
- get_filter_schema: describe project/category filter fields and comparators
- query_workspace_filter: filter project tasks or category pages via shared cache
- get_guidelines: retrieve detailed prompt guidelines on demand
"""

import json

from google.genai import types

from .function_definitions import (
    search,
    get_entity,
    get_file,
    get_forms,
    get_pages,
    get_page_details,
    get_page_file_list,
    get_page_tasks,
    get_task_history,
    get_category_details,
    get_guidelines,
    get_schema,
    get_form_instances,
    list_resources,
    workspace_filter,
)
from .debug import ai_debug, debug_log
from .references import normalize_hash_references

# Default for direct tool-enabled prompts without a workflow-specific limit.
MAX_TOOL_ITERATIONS = 12
TRACE_STRING_LIMIT = 500
TRACE_LIST_LIMIT = 5
TRACE_DEPTH_LIMIT = 2
FILE_PART_LIMIT_REASON = (
    "Original file was not attached because this tool turn reached the "
    "original-file attachment limit. Call get_file again for this file with "
    "include_original=true if the original is still necessary."
)


DECLARATIONS = {
    "search_entities": search.SEARCH_ENTITIES,
    "get_entity": get_entity.GET_ENTITY,
    "get_file": get_file.GET_FILE,
    "get_category_pages": get_pages.GET_CATEGORY_PAGES,
    "get_category_forms": get_forms.GET_CATEGORY_FORMS,
    "get_page_details": get_page_details.GET_PAGE_DETAILS,
    "get_page_file_list": get_page_file_list.GET_PAGE_FILE_LIST,
    "get_page_tasks": get_page_tasks.GET_PAGE_TASKS,
    "get_task_history": get_task_history.GET_TASK_HISTORY,
    "get_category_details": get_category_details.GET_CATEGORY_DETAILS,
    "get_guidelines": get_guidelines.GET_GUIDELINES,
    "get_schema": get_schema.GET_SCHEMA,
    "get_form_instances": get_form_instances.GET_FORM_INSTANCES,
    "list_workspace_resources": list_resources.LIST_WORKSPACE_RESOURCES,
    "get_filter_schema": workspace_filter.GET_FILTER_SCHEMA,
    "query_workspace_filter": workspace_filter.QUERY_WORKSPACE_FILTER,
}

FUNCTION_TOOL = types.Tool(function_declarations=list(DECLARATIONS.values()))


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_config_combines_search_tools_json_and_thinking_settings
# @matrix ai : config tools
def build_function_tool(*names):
    """Build a types.Tool with only the requested function declarations."""
    declarations = [DECLARATIONS[n] for n in names if n in DECLARATIONS]
    if not declarations:
        return None
    return types.Tool(function_declarations=declarations)


HANDLERS = {
    "search_entities": search.execute_search,
    "get_entity": get_entity.execute_get_entity,
    "get_file": get_file.execute_get_file,
    "get_category_pages": get_pages.execute_get_category_pages,
    "get_category_forms": get_forms.execute_get_category_forms,
    "get_page_details": get_page_details.execute_get_page_details,
    "get_page_file_list": get_page_file_list.execute_get_page_file_list,
    "get_page_tasks": get_page_tasks.execute_get_page_tasks,
    "get_task_history": get_task_history.execute_get_task_history,
    "get_category_details": get_category_details.execute_get_category_details,
    "get_guidelines": get_guidelines.execute_get_guidelines,
    "get_schema": get_schema.execute_get_schema,
    "get_form_instances": get_form_instances.execute_get_form_instances,
    "list_workspace_resources": list_resources.execute_list_workspace_resources,
    "get_filter_schema": workspace_filter.execute_get_filter_schema,
    "query_workspace_filter": workspace_filter.execute_query_workspace_filter,
}


# @testable false
# @covered-by lagniappe/core/tools/ai/functions.py::tool_catalog
# @reason provider-schema conversion is asserted through the public JSON catalog
def _provider_schema_to_json(value):
    """Convert Google schema models into ordinary JSON Schema values."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        converted = {}
        for key, child in value.items():
            if key == "propertyOrdering":
                continue
            if key == "type" and isinstance(child, str):
                child = child.casefold()
            converted[key] = _provider_schema_to_json(child)
        return converted
    if isinstance(value, list):
        return [_provider_schema_to_json(child) for child in value]
    return value


TOOL_DEFINITIONS = {
    name: {
        "name": name,
        "description": declaration.description or "",
        "input_schema": _provider_schema_to_json(declaration.parameters),
    }
    for name, declaration in DECLARATIONS.items()
}


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_tool_catalog_and_dispatch_share_registered_tools
# @matrix agent-api ai : provider-neutral-schema tool-catalog
def tool_catalog(*, transport=None):
    """Return the provider-neutral catalog used by external tool clients."""
    catalog = []
    for name in DECLARATIONS:
        definition = TOOL_DEFINITIONS[name]
        if transport == "rest" and name == "get_file":
            definition = {
                **definition,
                "description": (
                    f"{definition['description']} In this REST API, "
                    "include_original=true returns a signed download_url that "
                    "expires after five minutes when original content is available; "
                    "treat that URL as a temporary credential and do not expose it."
                ),
            }
        catalog.append(definition)
    return catalog


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_tool_catalog_and_dispatch_share_registered_tools
# @matrix agent-api ai : permission-context provider-neutral-dispatch tool-registry
def execute_registered_tool(name, args, user):
    """Execute one registered read tool without constructing provider parts."""
    if name not in HANDLERS:
        return {"error": f"Unknown function: {name}"}, []
    if not isinstance(args, dict):
        return {"error": "Tool arguments must be a JSON object."}, []

    normalized_args = normalize_hash_references(args)
    result = HANDLERS[name](normalized_args, user)
    if isinstance(result, tuple):
        result, file_parts = result
    else:
        file_parts = []
    return result, list(file_parts or [])


# @testable false
# @covered-by lagniappe/core/tools/ai/functions.py::execute_function_calls
# @reason compact value formatting is exercised through traced tool dispatch
def _trace_value(value, depth=0):
    """Return a compact, JSON-safe value for AI tool diagnostics."""
    if depth >= TRACE_DEPTH_LIMIT:
        return f"<{type(value).__name__}>"

    if isinstance(value, str):
        if len(value) > TRACE_STRING_LIMIT:
            return f"{value[:TRACE_STRING_LIMIT]}...<truncated {len(value)} chars>"
        return value

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    if isinstance(value, dict):
        return {
            str(k): _trace_value(v, depth + 1)
            for k, v in list(value.items())[:TRACE_LIST_LIMIT]
        }

    if isinstance(value, (list, tuple)):
        items = [_trace_value(item, depth + 1) for item in value[:TRACE_LIST_LIMIT]]
        if len(value) > TRACE_LIST_LIMIT:
            items.append(f"...<{len(value) - TRACE_LIST_LIMIT} more>")
        return items

    return str(value)


# @testable false
# @covered-by lagniappe/core/tools/ai/functions.py::execute_function_calls
# @reason compact result summaries are exercised through traced tool dispatch
def _result_summary(result):
    """Summarize a tool result without copying full workspace data into logs."""
    if isinstance(result, dict):
        summary = {"type": "dict", "keys": list(result.keys())[:TRACE_LIST_LIMIT]}
        if "error" in result:
            summary["error"] = _trace_value(result["error"])
        return summary

    if isinstance(result, list):
        summary = {"type": "list", "count": len(result)}
        kinds = [
            item.get("kind")
            for item in result
            if isinstance(item, dict) and item.get("kind")
        ]
        if kinds:
            summary["kinds"] = sorted(set(kinds))[:TRACE_LIST_LIMIT]
        return summary

    if isinstance(result, str):
        return {"type": "str", "chars": len(result)}

    return {"type": type(result).__name__}


# @testable false
# @covered-by lagniappe/core/tools/ai/core.py::GenAI._tool_loop
# @reason requested-call summaries are emitted through tool-loop exception context
def summarize_function_calls(function_calls):
    """Compact function-call summary for exception context."""
    return [
        {"name": fc.name, "args": _trace_value(dict(fc.args))}
        for fc in function_calls
    ]


# @testable false
# @covered-by lagniappe/core/tools/ai/functions.py::execute_function_calls
# @reason limit annotation is part of the tool-dispatch contract
def _mark_file_parts_omitted(result):
    if not isinstance(result, dict):
        return result

    original_file = result.get("original_file")
    if not isinstance(original_file, dict):
        original_file = {}
    marked = dict(result)
    marked["original_file"] = {
        **original_file,
        "supported": original_file.get("supported", True),
        "attached": False,
        "reason": FILE_PART_LIMIT_REASON,
    }
    return marked


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_function_call_dispatch_serializes_caches_and_attaches_files
# @tests tests_unit/test_015_ai_tools.py::test_ai_function_call_dispatch_caps_file_parts_per_turn
# @matrix ai : caching file-parts limit tool-dispatch trace unknown-tool
def execute_function_calls(
    function_calls,
    user,
    cache=None,
    debug=False,
    trace=None,
    max_file_parts=None,
    execution_control=None,
):
    """Execute a list of function calls and return response parts.

    Handlers may return a tuple of (result, file_parts) when they need
    to attach files for the model to analyze directly. file_parts are
    dicts with "uri" and "mime_type" keys.
    """
    if cache is None:
        cache = {}
    responses = []
    file_parts = []
    function_calls = list(function_calls)
    raw_args = [dict(fc.args) for fc in function_calls]
    normalized_args = normalize_hash_references(raw_args)
    if debug:
        ai_debug(
            "tool.calls.normalized",
            calls=[
                {
                    "name": fc.name,
                    "raw_args": _trace_value(raw),
                    "args": _trace_value(normalized),
                    "normalized": raw != normalized,
                }
                for fc, raw, normalized in zip(
                    function_calls,
                    raw_args,
                    normalized_args,
                )
            ],
        )

    for fc, raw_args_item, args in zip(function_calls, raw_args, normalized_args):
        if execution_control is not None:
            execution_control.before_tool(fc.name)
        cache_key = (fc.name, json.dumps(args, sort_keys=True))
        trace_record = {
            "name": fc.name,
            "args": _trace_value(args),
            "cached": cache_key in cache,
        }

        if cache_key in cache:
            result, parts = cache[cache_key]
            if debug:
                debug_log(f"[ai:tool] {fc.name} -> cached")
        else:
            if debug:
                if raw_args_item != args:
                    debug_log(
                        f"[ai:tool] {fc.name}({raw_args_item}) "
                        f"-> normalized {args}"
                    )
                else:
                    debug_log(f"[ai:tool] {fc.name}({args})")
            result, parts = execute_registered_tool(fc.name, args, user)

            cache[cache_key] = (result, parts)

        if execution_control is not None:
            execution_control.after_tool(fc.name)

        allowed_parts = parts
        omitted_parts = 0
        if max_file_parts is not None:
            remaining = max(max_file_parts - len(file_parts), 0)
            allowed_parts = parts[:remaining]
            omitted_parts = len(parts) - len(allowed_parts)
            if omitted_parts:
                result = _mark_file_parts_omitted(result)

        trace_record["result"] = _result_summary(result)
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
        trace_record["result_chars"] = len(result)
        trace_record["file_parts"] = len(allowed_parts)
        if omitted_parts:
            trace_record["omitted_file_parts"] = omitted_parts

        file_parts.extend(allowed_parts)

        if debug:
            debug_log(f"[ai:tool] {fc.name} -> {len(result)} chars")

        if trace is not None:
            trace.append(trace_record)

        responses.append(
            types.Part.from_function_response(name=fc.name, response={"result": result})
        )

    return responses, file_parts
