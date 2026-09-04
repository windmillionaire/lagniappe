"""User-local MCP adapter for Lagniappe's canonical REST API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lagniappe-mcp")
except PackageNotFoundError:  # pragma: no cover - source-tree import fallback
    __version__ = "0.1.1"

__all__ = ["__version__"]
