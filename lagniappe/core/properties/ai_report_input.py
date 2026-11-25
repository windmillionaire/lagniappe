"""Persisted input and origin fields for AI reports."""

from .base_db import DBProperty


class FormatVersion(DBProperty[int]):
    """Server-owned report format; missing versions are unavailable."""

    _id = "format_version"


class FileUsage(DBProperty[list[dict[str, object]]]):
    """Reviewed usage of each uploaded file, separate from executable actions."""

    _id = "file_usage"
    json = True

class UploadManifest(DBProperty[list[dict[str, object]]]):
    """Signed direct-upload records awaiting background finalization."""

    _id = "upload_manifest"
    json = True


class AgentManifest(DBProperty[dict[str, object]]):
    """Versioned, non-transcript metadata for an external plan workspace."""

    _id = "agent_manifest"
    json = True


class Origin(DBProperty[str]):
    """How the initial report was submitted; legacy reports are web-origin."""

    _id = "origin"

    @property
    def value(self) -> str:
        return self._read_db_value() or "web"

    @value.setter
    def value(self, value: object) -> None:
        normalized = str(value or "web").strip().casefold()
        if normalized not in {"web", "email", "api"}:
            raise ValueError("AI report origin must be web, email, or api")
        self._write_db_value(normalized)


class InboundManifest(DBProperty[dict[str, object]]):
    """Safe normalized email fields displayed with an email-origin report."""

    _id = "inbound_manifest"
    json = True
