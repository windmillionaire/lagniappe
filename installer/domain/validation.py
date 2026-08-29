"""Custom-domain input validation."""

import re


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_validators_cover_expected_inputs
# @pair setup:validation
def validate_domain(domain):
    """Validate domain format."""
    domain_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
    return bool(re.match(domain_pattern, domain)) and len(domain) <= 253


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_validators_cover_expected_inputs
# @pair setup:validation
def validate_cloudflare_api_token(api_token):
    """Reject empty or obviously malformed scoped API tokens."""
    token = api_token.strip()
    return len(token) >= 20 and not any(character.isspace() for character in token)
