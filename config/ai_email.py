"""Runtime-safe configuration contracts for inbound AI email."""

import re
import unicodedata
from collections.abc import Mapping
from typing import TypedDict


class AIEmailConfig(TypedDict):
    provider: str
    enabled: bool
    domain: str
    resend: dict[str, str]


class PublicAIEmailConfig(TypedDict):
    enabled: bool
    addresses: dict[str, str]





AI_EMAIL_PROVIDER = "resend"
AI_EMAIL_ALIAS = "ai"
AI_EMAIL_LIMITS = {
    "maxBodyBytes": 65536,
    "maxFiles": 20,
    "maxFileBytes": 31457280,
    "maxTotalFileBytes": 52428800,
    "hourlyPerUser": 30,
    "dailyPerUser": 200,
}
_TOP_LEVEL_KEYS = {
    "provider",
    "enabled",
    "domain",
    "resend",
    # Generated settings may contain policy metadata. It is not configuration:
    # runtime routing and limits come exclusively from the constants above.
    # Never inspect its version, interpret aliases, or rewrite the input.
    "version",
    "aliases",
    "limits",
    # Accepted only so a checkout deployed between the transport proof and the
    # production handoff can read its saved configuration. Normalization drops
    # the temporary field and the installer removes it on its next save.
    "setupProbe",
}
_RESEND_KEYS = {
    "domainId",
    "webhookId",
    "webhookSecret",
    "inboundApiKey",
    "sendingApiKey",
    "senderEmail",
    "senderName",
    # Legacy transport-probe evidence. Sender authentication is useful
    # telemetry, but is not the report authorization boundary.
    "trustedAuthservIds",
}
_EMAIL_LOCAL_PATTERN = re.compile(r'^[^\s@<>(),;:\\"\[\]\x00-\x1f\x7f]+$')


class AIEmailConfigurationError(ValueError):
    """Raised when optional AI email configuration is unsafe or incomplete."""


def _mapping(value, name):
    if not isinstance(value, Mapping):
        raise AIEmailConfigurationError(f"{name} must be a mapping.")
    return dict(value)


def _reject_unknown_keys(value, allowed, name):
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise AIEmailConfigurationError(
            f"{name} contains unknown settings: {', '.join(unknown)}."
        )


def _required_text(value, name, *, maximum=1000):
    text = str(value or "").strip()
    if (
        not text
        or len(text) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise AIEmailConfigurationError(f"{name} is missing or invalid.")
    return text


def normalize_email_address(value: object, name: str = "email address") -> str:
    """Normalize one bare mailbox without provider-specific rewrites."""
    address = unicodedata.normalize("NFC", str(value or "").strip())
    if address.count("@") != 1 or any(character in address for character in "\r\n"):
        raise AIEmailConfigurationError(f"{name} must be one bare email address.")
    local, raw_domain = address.rsplit("@", 1)
    if not local or not _EMAIL_LOCAL_PATTERN.fullmatch(local):
        raise AIEmailConfigurationError(f"{name} has an invalid local part.")
    domain = normalize_email_domain(raw_domain, f"{name} domain")
    return f"{local}@{domain}"


def normalize_email_domain(value: object, name: str = "AI email domain") -> str:
    """Return a lower-case IDNA ASCII domain without a trailing dot."""
    domain = str(value or "").strip().rstrip(".")
    if not domain or any(character in domain for character in "\r\n/@"):
        raise AIEmailConfigurationError(f"{name} is missing or invalid.")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise AIEmailConfigurationError(
            f"{name} is not a valid IDNA domain."
        ) from error
    labels = ascii_domain.split(".")
    if (
        len(ascii_domain) > 253
        or len(labels) < 2
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
            for label in labels
        )
    ):
        raise AIEmailConfigurationError(f"{name} is not a valid domain.")
    return ascii_domain


def _normalize_resend(value: object) -> dict[str, str]:
    resend = _mapping(value, "AI_EMAIL_CONFIG.resend")
    _reject_unknown_keys(resend, _RESEND_KEYS, "AI_EMAIL_CONFIG.resend")
    normalized = {
        "domainId": _required_text(
            resend.get("domainId"), "AI_EMAIL_CONFIG.resend.domainId"
        ),
        "webhookId": _required_text(
            resend.get("webhookId"), "AI_EMAIL_CONFIG.resend.webhookId"
        ),
        "webhookSecret": _required_text(
            resend.get("webhookSecret"),
            "AI_EMAIL_CONFIG.resend.webhookSecret",
            maximum=512,
        ),
        "inboundApiKey": _required_text(
            resend.get("inboundApiKey"),
            "AI_EMAIL_CONFIG.resend.inboundApiKey",
            maximum=512,
        ),
        "sendingApiKey": _required_text(
            resend.get("sendingApiKey"),
            "AI_EMAIL_CONFIG.resend.sendingApiKey",
            maximum=512,
        ),
        "senderEmail": normalize_email_address(
            resend.get("senderEmail"), "AI_EMAIL_CONFIG.resend.senderEmail"
        ),
        "senderName": _required_text(
            resend.get("senderName"),
            "AI_EMAIL_CONFIG.resend.senderName",
            maximum=200,
        ),
    }
    if normalized["inboundApiKey"] == normalized["sendingApiKey"]:
        raise AIEmailConfigurationError(
            "Receiving and sending Resend API keys must be distinct."
        )
    return normalized


def normalize_ai_email_config(value: object) -> AIEmailConfig | None:
    """Validate installation choices without reading or rewriting code policy."""
    if value in (None, ""):
        return None
    config = _mapping(value, "AI_EMAIL_CONFIG")
    _reject_unknown_keys(config, _TOP_LEVEL_KEYS, "AI_EMAIL_CONFIG")
    if config.get("provider") != AI_EMAIL_PROVIDER:
        raise AIEmailConfigurationError("AI_EMAIL_CONFIG.provider must be 'resend'.")
    enabled = config.get("enabled")
    if not isinstance(enabled, bool):
        raise AIEmailConfigurationError(
            "AI_EMAIL_CONFIG.enabled must be true or false."
        )
    return {
        "provider": AI_EMAIL_PROVIDER,
        "enabled": enabled,
        "domain": normalize_email_domain(config.get("domain")),
        "resend": _normalize_resend(config.get("resend")),
    }


def ai_email_public_config(value: object) -> PublicAIEmailConfig:
    """Expose only enabled addresses; never return provider state or secrets."""
    config = normalize_ai_email_config(value)
    if not config or not config["enabled"]:
        return {"enabled": False, "addresses": {}}
    return {
        "enabled": True,
        "addresses": {
            "ai": f"{AI_EMAIL_ALIAS}@{config['domain']}",
        },
    }


__all__ = [
    "AI_EMAIL_ALIAS",
    "AI_EMAIL_LIMITS",
    "AIEmailConfigurationError",
    "ai_email_public_config",
    "normalize_ai_email_config",
    "normalize_email_address",
    "normalize_email_domain",
]
