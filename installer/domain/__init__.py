"""App Engine custom-domain setup with optional Cloudflare DNS automation."""

# Validation
from .validation import (
    validate_domain,
    validate_cloudflare_api_token,
)

# Instructions and explanations
from .instructions import explain_domain_setup

# Cloudflare configuration
from .cloudflare import (
    DMARC_DEFAULT_POLICY,
    ensure_cloudflare_dmarc_record,
    get_cloudflare_api_token,
    get_cloudflare_zone,
    reconcile_cloudflare_dns_records,
)

# Manual DNS setup
from .manual import (
    confirm_domain_ownership,
    print_manual_dns_instructions,
)

# GCP domain mapping
from .gcp import (
    create_gcp_domain_mapping,
)

# OAuth configuration
from .oauth import update_oauth_redirect_uris
