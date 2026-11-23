"""Remote MCP service for Lagniappe's canonical REST API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lagniappe-mcp")
except PackageNotFoundError:  # pragma: no cover - source-tree import fallback
    __version__ = "0.1.6"

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

__all__ = ["__version__"]
