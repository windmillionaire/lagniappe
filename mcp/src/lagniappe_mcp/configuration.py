"""Runtime connection configuration with no model-visible credentials."""

from __future__ import annotations

from dataclasses import dataclass, field

from .url_security import SiteAuthority


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    """Ephemeral connection values used by one authenticated adapter request."""

    authority: SiteAuthority
    api_key: str = field(repr=False)
