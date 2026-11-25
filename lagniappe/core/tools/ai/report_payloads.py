"""Encode repeated entity records in one provider report conversation."""

from collections import Counter
import json

from .references import HASH_REFERENCE_REGEX

# Bound extra resident memory in long report conversations.
MAX_INDEX_CHARS = 1_000_000
MIN_RECORD_CHARS = 256
_ENTITY_TOOLS = {
    "get_entity", "get_entities", "get_category_details", "get_category_pages", "get_page_details",
    "get_page_tasks", "get_task_history", "query_workspace_filter", "search_entities",
}
_LABELS = (
    "name", "page_name", "task_name", "form_name", "category_name", "project_name",
    "model_name", "kind", "completed", "Completed",
)


class ReportToolPayloads:
    """An exact JSON match can point back to an already delivered record."""

    def __init__(self) -> None:
        self._calls: Counter[str] = Counter()
        self._locations: dict[str, dict[str, str | int]] = {}
        self._indexed_chars = 0

    def encode(self, name: str, result: object, *, edit: bool = False) -> str:
        self._calls[name] += 1
        if isinstance(result, str):
            return result
        if name not in _ENTITY_TOOLS or edit:
            return json.dumps(result, default=str)
        occurrence = self._calls[name]

        def project(value: object, path: str) -> object:
            if isinstance(value, list):
                return [project(child, f"{path}/{index}") for index, child in enumerate(value)]
            if not isinstance(value, dict):
                return value

            reference = value.get("hash")
            if (
                isinstance(reference, str)
                and HASH_REFERENCE_REGEX.fullmatch(reference)
                and isinstance(value.get("url"), str)
                and "same_as_tool_result" not in value
            ):
                full = json.dumps(value, default=str)
                if len(full) >= MIN_RECORD_CHARS:
                    if location := self._locations.get(full):
                        brief = {key: value[key] for key in ("hash", "url", *_LABELS) if key in value}
                        brief["same_as_tool_result"] = location
                        if len(json.dumps(brief, default=str)) < len(full):
                            return brief
                    elif self._indexed_chars + len(full) <= MAX_INDEX_CHARS:
                        self._locations[full] = {"tool": name, "occurrence": occurrence, "json_pointer": path}
                        self._indexed_chars += len(full)

            projected = {}
            for key, child in value.items():
                token = str(key).replace("~", "~0").replace("/", "~1")
                projected[key] = project(child, f"{path}/{token}")
            return projected

        return json.dumps(project(result, ""), default=str)
