"""Runtime connection configuration with no model-visible credentials."""

from __future__ import annotations

from dataclasses import dataclass, field
import os

from .errors import ConfigurationError
from .url_security import SiteAuthority, normalize_site_url


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    """Ephemeral connection values used by one adapter process."""

    authority: SiteAuthority
    api_key: str = field(repr=False)
    profile_name: str | None = None
    actor_hash: str | None = None


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/configuration.py::from_environment
def _required_environment(environ: dict[str, str], name: str) -> str:
    if name not in environ:
        raise ConfigurationError(
            "missing_environment",
            f"Required environment variable {name} is missing.",
        )
    value = environ[name]
    if not value.strip():
        raise ConfigurationError(
            "empty_environment",
            f"Required environment variable {name} is empty.",
        )
    return value.strip()


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_manual_environment_configuration_is_explicit_and_validated
def from_environment(*, environ: dict[str, str] | None = None) -> ConnectionConfig:
    """Load the non-persistent manual/CI connection mode."""
    values = os.environ if environ is None else environ
    url = _required_environment(values, "LAGNIAPPE_URL")
    key = _required_environment(values, "LAGNIAPPE_API_KEY")
    return ConnectionConfig(
        authority=normalize_site_url(url),
        api_key=key,
    )
