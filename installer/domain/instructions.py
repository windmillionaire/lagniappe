"""Console guidance for the custom-domain workflow."""

from runner import presentation as ui
from runner.presentation import output as print

from installer import wrap_text


# @testable false
# @covered-by installer/custom_domain.py::_setup_custom_domain
# @reason console-only overview for the custom-domain workflow
def explain_domain_setup(*, configure_auth=True, google_signin=True):
    """Explain domain ownership, DNS, and the applicable authentication work."""
    print("\n" + ui.heading("Custom domain setup"))
    print(
        wrap_text(
            "Verify Google domain ownership, then add the App Engine DNS records "
            "through Cloudflare or your DNS provider."
        )
    )
    if configure_auth and google_signin:
        print(
            wrap_text(
                "Setup will guide the Google OAuth update and configure the authentication origin."
            )
        )
    elif configure_auth:
        print(wrap_text("Setup will configure the custom authentication origin."))
    else:
        print(
            wrap_text(
                "The remaining authentication and email steps will use this domain."
            )
        )
    print(
        wrap_text(
            "Cloudflare automation is DNS-only, with proxying disabled. It leaves "
            "WAF, bot, cache, and zone-security settings unchanged."
        )
    )
