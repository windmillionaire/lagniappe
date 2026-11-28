"""Read canonical application guidance without creating a Plan or calling AI."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

from google.genai import types
from redis.exceptions import RedisError

from lagniappe.core.tools import cache
from lagniappe.reference import get_topic, topic_catalog, topic_context

GET_HELP = types.FunctionDeclaration(
    name="get_help",
    description=(
        "Look up how Lagniappe works before answering questions about its features, "
        "controls or general permissions. Supply exactly one of query (a few specific "
        "keywords, such as 'task history' or 'backups'), topic_id (a canonical topic ID), "
        "or list_topics=true to list every available topic ID, category, title, URL, and "
        "summary. Returns up to three complete Markdown articles (or the topic catalog "
        "when list_topics=true); cite returned browser URLs in your answer. General "
        "guidance does not establish access to a particular workspace record. "
        "No Plan, provider call or workspace change is needed."
    ),
    parameters=types.Schema.model_validate({
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Short help search keywords."},
            "topic_id": {"type": "string", "description": "Exact canonical help topic ID."},
            "list_topics": {
                "type": "boolean",
                "description": "Set to true to return the full catalog of available help topics.",
            },
        },
    }),
)


def execute_get_help(args: Mapping[str, object], user: User) -> Mapping[str, object]:
    provided = [key for key in ("query", "topic_id", "list_topics") if key in args]
    if len(provided) != 1 or set(args) - {"query", "topic_id", "list_topics"}:
        return {"error": "Supply exactly one of query, topic_id, or list_topics=true."}
    if "list_topics" in args:
        if args["list_topics"] is not True:
            return {"error": "Set list_topics to true to list available help topics."}
        return {"topics": [], "catalog": topic_catalog()}
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
            results, _ = cache.help_search(value, limit=3)
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
