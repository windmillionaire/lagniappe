"""Provider-neutral result contracts for shared AI read tools."""


ENTITY = {"type": "object", "additionalProperties": True}
ENTITY_LIST = {"type": "array", "items": ENTITY}
REFERENCE = {
    "type": "object",
    "required": ["hash", "name"],
    "properties": {
        "hash": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string"},
    },
    "additionalProperties": True,
}


# @testable false
# @covered-by lagniappe/core/tools/ai/functions.py::tool_catalog
# @reason schema construction is published and asserted through the canonical catalog
def _object(*required, properties=None):
    return {
        "type": "object",
        "required": list(required),
        "properties": properties or {},
        "additionalProperties": True,
    }


# These describe the successful direct shared-handler result. REST wraps those values
# as {"result": <value>}; provider-native function calls receive <value>.
OUTPUT_SCHEMAS = {
    "search_entities": ENTITY_LIST,
    "get_entity": ENTITY,
    "get_file": _object(
        properties={
            "content": {"type": "string"},
            "original_file": _object(
                "supported",
                "attached",
                properties={
                    "supported": {"type": "boolean"},
                    "attached": {"type": "boolean"},
                    "download_url": {"type": "string"},
                    "expires_in": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            ),
        },
    ),
    "get_category_pages": _object(
        "category",
        "requested_limit",
        "effective_limit",
        "returned_count",
        "has_more",
        "pages",
        properties={
            "category": {"type": "string"},
            "requested_limit": {"type": "integer"},
            "effective_limit": {"type": "integer"},
            "returned_count": {"type": "integer"},
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"]},
            "pages": ENTITY_LIST,
        },
    ),
    "get_category_forms": _object(
        "category",
        "form_count",
        "forms",
        properties={
            "category": {"type": "string"},
            "form_count": {"type": "integer"},
            "forms": ENTITY_LIST,
        },
    ),
    "get_page_details": _object(
        "page",
        properties={
            "page": ENTITY,
            "category": ENTITY,
            "tasks": ENTITY_LIST,
            "files": ENTITY_LIST,
        },
    ),
    "get_page_file_list": _object(
        "page",
        "files",
        properties={"page": REFERENCE, "files": ENTITY_LIST},
    ),
    "get_page_tasks": _object(
        "page",
        "tasks",
        "completed_tasks",
        properties={
            "page": REFERENCE,
            "tasks": ENTITY_LIST,
            "completed_tasks": ENTITY_LIST,
        },
    ),
    "get_task_history": _object(
        "task",
        "count",
        "limit",
        "truncated",
        "history",
        properties={
            "task": ENTITY,
            "count": {"type": "integer"},
            "limit": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "history": ENTITY_LIST,
        },
    ),
    "get_category_details": ENTITY,
    "get_guidelines": _object(
        "task",
        "description",
        "guidelines",
        "content_bytes",
        "section_count",
        properties={
            "task": {"type": "string"},
            "description": {"type": "string"},
            "guidelines": {"type": "string"},
            "content_bytes": {"type": "integer"},
            "section_count": {"type": "integer"},
            "filters": {"type": "object"},
        },
    ),
    "get_schema": _object(
        "entity",
        "form",
        "schema",
        "field_count",
        properties={
            "entity": REFERENCE,
            "form": {"oneOf": [REFERENCE, {"type": "null"}]},
            "form_type": {"type": "string"},
            "schema": {"type": "array", "items": {"type": "object"}},
            "field_count": {"type": "integer"},
        },
    ),
    "get_form_instances": _object(
        "form",
        "form_type",
        "field_count",
        "instances",
        "total",
        "returned",
        "truncated",
        properties={
            "form": REFERENCE,
            "form_type": {"type": "string"},
            "field_count": {"type": "integer"},
            "instances": ENTITY_LIST,
            "total": {"type": "integer"},
            "returned": {"type": "integer"},
            "truncated": {"type": "boolean"},
        },
    ),
    "list_workspace_resources": _object(
        "personal_page",
        "categories",
        "projects",
        "standalone_forms",
        properties={
            "personal_page": REFERENCE,
            "categories": ENTITY_LIST,
            "projects": ENTITY_LIST,
            "standalone_forms": ENTITY_LIST,
        },
    ),
    "get_filter_schema": _object(
        properties={
            "parent": REFERENCE,
            "fields": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "query_workspace_filter": _object(
        "parent",
        "result_kind",
        "matched",
        "returned",
        "truncated",
        "results",
        properties={
            "parent": REFERENCE,
            "result_kind": {"type": "string", "enum": ["page", "task"]},
            "matched": {"type": "integer"},
            "returned": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "results": ENTITY_LIST,
            "incomplete": {"type": "boolean"},
            "serialization_errors": {
                "type": "array",
                "items": {"type": "object"},
            },
        },
    ),
}


RESULT_PATHS = {
    "search_entities": {"primary_collection": "$", "pagination": None},
    "get_entity": {"primary_entity": "$", "pagination": None},
    "get_file": {"primary_entity": "$", "pagination": None},
    "get_category_pages": {
        "primary_collection": "$.pages",
        "pagination": {
            "has_more": "$.has_more",
            "next_cursor": "$.next_cursor",
            "returned": "$.returned_count",
        },
    },
    "get_category_forms": {"primary_collection": "$.forms", "pagination": None},
    "get_page_details": {"primary_entity": "$.page", "pagination": None},
    "get_page_file_list": {"primary_collection": "$.files", "pagination": None},
    "get_page_tasks": {
        "primary_collections": ["$.tasks", "$.completed_tasks"],
        "pagination": None,
    },
    "get_task_history": {
        "primary_collection": "$.history",
        "pagination": {"truncated": "$.truncated", "returned": "$.limit"},
    },
    "get_category_details": {"primary_entity": "$", "pagination": None},
    "get_guidelines": {"primary_text": "$.guidelines", "pagination": None},
    "get_schema": {"primary_collection": "$.schema", "pagination": None},
    "get_form_instances": {
        "primary_collection": "$.instances",
        "pagination": {
            "truncated": "$.truncated",
            "returned": "$.returned",
            "total": "$.total",
        },
    },
    "list_workspace_resources": {
        "primary_collections": ["$.categories", "$.projects", "$.standalone_forms"],
        "pagination": None,
    },
    "get_filter_schema": {"primary_collection": "$.fields", "pagination": None},
    "query_workspace_filter": {
        "primary_collection": "$.results",
        "pagination": {
            "truncated": "$.truncated",
            "returned": "$.returned",
            "total": "$.matched",
        },
    },
}
