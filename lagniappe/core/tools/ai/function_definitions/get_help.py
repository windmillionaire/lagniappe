"""Read canonical application guidance without creating a Plan or calling AI."""

from google.genai import types
from redis.exceptions import RedisError

from lagniappe.core.definitions import Restriction
from lagniappe.core.tools import cache
from lagniappe.reference import get_topic, topic_context

GET_HELP = types.FunctionDeclaration(
    name="get_help",
    description=(
        "Look up how Lagniappe works before answering questions about its features, "
        "controls or general permissions. Supply exactly one of query (a few specific "
        "keywords, such as 'task history' or 'email') or a canonical topic_id returned "
        "by this tool. Returns up to three complete short Markdown articles with "
        "related topic IDs and browser URLs; cite those URLs in your answer. General "
        "guidance does not establish access to a particular workspace record. "
        "No Plan, provider call or workspace change is needed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Short help search keywords."},
            "topic_id": {"type": "string", "description": "Exact canonical help topic ID."},
        },
    },
)


# @testable true
# @tests tests_unit/test_035_help.py::test_help_tool_is_bounded_source_backed_and_shared
# @tests tests_unit/test_035_help.py::test_help_tool_rejects_invalid_requests_and_reports_search_failure
# @matrix help : ai-lookup validation provider-failure
def execute_get_help(args, user):
    provided = [key for key in ("query", "topic_id") if key in args]
    if len(provided) != 1 or set(args) - {"query", "topic_id"}:
        return {"error": "Supply exactly one of query or topic_id."}
    value = args[provided[0]]
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        return {"error": "Help lookup requires a nonempty string of at most 500 characters."}
    if "topic_id" in args:
        try:
            selected = [get_topic(value)]
        except KeyError:
            return {"error": "Help topic not found.", "topic_id": value}
    else:
        try:
            results, _ = cache.search(
                value, [], Restriction.BELONGS_TO_NONE,
                kinds=["help"], limit=3, include_help=True,
            )
        except (RedisError, TimeoutError):
            return {"error": "Help search is temporarily unavailable. Retry shortly or use a known topic_id."}
        selected = [get_topic(result["id"]) for result in results]
    output = []
    for topic in selected:
        record = topic.as_dict()
        if context := topic_context(topic.id, user):
            record["context"] = context
        output.append(record)
    return {"topics": output}
