"""Custom-domain input validation."""

import re


def validate_domain(domain: str) -> bool:
    """Validate domain format."""
    domain_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
    return bool(re.match(domain_pattern, domain)) and len(domain) <= 253


def validate_cloudflare_api_token(api_token: str) -> bool:
    """Reject empty or obviously malformed scoped API tokens."""
    token = api_token.strip()
    return len(token) >= 20 and not any(character.isspace() for character in token)
