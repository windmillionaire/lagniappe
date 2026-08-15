"""Runtime-safe configuration contracts for inbound AI email."""

from collections.abc import Mapping
import re
import unicodedata


AI_EMAIL_CONFIG_VERSION = 1
AI_EMAIL_PROVIDER = "resend"
AI_EMAIL_LIMITS = {
    "maxBodyBytes": 65536,
    "maxFiles": 20,
    "maxFileBytes": 31457280,
    "maxTotalFileBytes": 52428800,
    "hourlyPerUser": 30,
    "dailyPerUser": 200,
}
AI_EMAIL_TOOLS = ("ai", "ask", "create", "organize")

_TOP_LEVEL_KEYS = {
    "version",
    "provider",
    "enabled",
    "domain",
    "aliases",
    "resend",
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
_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
_EMAIL_LOCAL_PATTERN = re.compile(r'^[^\s@<>(),;:\\"\[\]\x00-\x1f\x7f]+$')


class AIEmailConfigurationError(ValueError):
    """Raised when optional AI email configuration is unsafe or incomplete."""


# @testable false
# @covered-by config/ai_email.py::normalize_ai_email_config
# @reason structured-value guard exercised through the public normalizer
def _mapping(value, name):
    if not isinstance(value, Mapping):
        raise AIEmailConfigurationError(f"{name} must be a mapping.")
    return dict(value)


# @testable false
# @covered-by config/ai_email.py::normalize_ai_email_config
# @reason schema-key guard exercised through the public normalizer
def _reject_unknown_keys(value, allowed, name):
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise AIEmailConfigurationError(
            f"{name} contains unknown settings: {', '.join(unknown)}."
        )


# @testable false
# @covered-by config/ai_email.py::normalize_ai_email_config
# @reason bounded-text guard exercised through the public normalizer
def _required_text(value, name, *, maximum=1000):
    text = str(value or "").strip()
    if (
        not text
        or len(text) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise AIEmailConfigurationError(f"{name} is missing or invalid.")
    return text


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_normalizes_domains_aliases_and_public_projection
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_rejects_security_weakening_values
# @features ai-email
# @dimensions config domain email-address
def normalize_email_address(value, name="email address"):
    """Normalize one bare mailbox without provider-specific rewrites."""
    address = unicodedata.normalize("NFC", str(value or "").strip())
    if address.count("@") != 1 or any(character in address for character in "\r\n"):
        raise AIEmailConfigurationError(f"{name} must be one bare email address.")
    local, raw_domain = address.rsplit("@", 1)
    if not local or not _EMAIL_LOCAL_PATTERN.fullmatch(local):
        raise AIEmailConfigurationError(f"{name} has an invalid local part.")
    domain = normalize_email_domain(raw_domain, f"{name} domain")
    return f"{local}@{domain}"


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_normalizes_domains_aliases_and_public_projection
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_rejects_security_weakening_values
# @features ai-email
# @dimensions config domain idna
def normalize_email_domain(value, name="AI email domain"):
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


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_normalizes_domains_aliases_and_public_projection
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_rejects_security_weakening_values
# @features ai-email
# @dimensions aliases
def _normalize_aliases(value):
    aliases = _mapping(value, "AI_EMAIL_CONFIG.aliases")
    _reject_unknown_keys(aliases, set(AI_EMAIL_TOOLS), "AI_EMAIL_CONFIG.aliases")
    normalized = {}
    for tool in AI_EMAIL_TOOLS:
        raw_alias = aliases.get(tool)
        if tool == "ai" and raw_alias in (None, ""):
            raw_alias = "ai"
        alias = str(raw_alias or "").strip().casefold()
        if not _ALIAS_PATTERN.fullmatch(alias) or "+" in alias:
            raise AIEmailConfigurationError(
                f"AI_EMAIL_CONFIG.aliases.{tool} is invalid."
            )
        normalized[tool] = alias
    if len(set(normalized.values())) != len(normalized):
        raise AIEmailConfigurationError("AI email aliases must be unique.")
    return normalized


# @testable false
# @covered-by config/ai_email.py::normalize_ai_email_config
# @reason provider schema details are exercised through the public normalizer
def _normalize_resend(value):
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


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_normalizes_domains_aliases_and_public_projection
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_rejects_security_weakening_values
# @tests tests_tooling/test_003_config.py::test_recovery_accepts_and_redacts_optional_ai_email_config
# @features ai-email
# @dimensions config normalization validation secrets limits
def normalize_ai_email_config(value):
    """Return canonical schema-1 configuration, or ``None`` when absent."""
    if value in (None, ""):
        return None
    config = _mapping(value, "AI_EMAIL_CONFIG")
    _reject_unknown_keys(config, _TOP_LEVEL_KEYS, "AI_EMAIL_CONFIG")
    if config.get("version") != AI_EMAIL_CONFIG_VERSION:
        raise AIEmailConfigurationError("AI_EMAIL_CONFIG.version must be 1.")
    if config.get("provider") != AI_EMAIL_PROVIDER:
        raise AIEmailConfigurationError("AI_EMAIL_CONFIG.provider must be 'resend'.")
    enabled = config.get("enabled")
    if not isinstance(enabled, bool):
        raise AIEmailConfigurationError(
            "AI_EMAIL_CONFIG.enabled must be true or false."
        )
    aliases = _normalize_aliases(config.get("aliases"))
    limits = _mapping(config.get("limits"), "AI_EMAIL_CONFIG.limits")
    _reject_unknown_keys(limits, set(AI_EMAIL_LIMITS), "AI_EMAIL_CONFIG.limits")
    if limits != AI_EMAIL_LIMITS:
        raise AIEmailConfigurationError(
            "AI_EMAIL_CONFIG.limits must match the locked schema-1 envelope."
        )
    return {
        "version": AI_EMAIL_CONFIG_VERSION,
        "provider": AI_EMAIL_PROVIDER,
        "enabled": enabled,
        "domain": normalize_email_domain(config.get("domain")),
        "aliases": aliases,
        "resend": _normalize_resend(config.get("resend")),
        "limits": dict(AI_EMAIL_LIMITS),
    }


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_config_normalizes_domains_aliases_and_public_projection
# @features ai-email
# @dimensions config public-projection secrets
def ai_email_public_config(value):
    """Expose only enabled addresses; never return provider state or secrets."""
    config = normalize_ai_email_config(value)
    if not config or not config["enabled"]:
        return {"enabled": False, "addresses": {}}
    return {
        "enabled": True,
        "addresses": {
            tool: f"{config['aliases'][tool]}@{config['domain']}"
            for tool in AI_EMAIL_TOOLS
        },
    }


__all__ = [
    "AI_EMAIL_CONFIG_VERSION",
    "AI_EMAIL_LIMITS",
    "AI_EMAIL_TOOLS",
    "AIEmailConfigurationError",
    "ai_email_public_config",
    "normalize_ai_email_config",
    "normalize_email_address",
    "normalize_email_domain",
]
