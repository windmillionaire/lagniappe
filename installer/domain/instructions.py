"""Console guidance for the custom-domain workflow."""

from runner import presentation as ui
from runner.presentation import output as print

from installer import FORMATTER, wrap_text


# @testable false
# @covered-by installer/custom_domain.py::_setup_custom_domain
# @reason console-only overview for the custom-domain workflow
def explain_domain_setup(*, configure_auth=True, google_signin=True):
    """Explain the supported App Engine and optional DNS automation."""
    f = FORMATTER.initialize()
    print(wrap_text(f"\n{ui.heading('Custom domain setup')}"))
    print(wrap_text("This flow will:"))
    print(wrap_text("  1. Confirm Google domain ownership verification"))
    print(wrap_text("  2. Create or discover the App Engine domain mapping"))
    print(wrap_text("  3. Read the exact DNS records returned by App Engine"))
    print(
        wrap_text(
            "  4. Add those records through Cloudflare, or print them for manual entry"
        )
    )
    if configure_auth and google_signin:
        print(
            wrap_text(
                "  5. Guide the Google OAuth update and reconcile Identity "
                "Platform automatically"
            )
        )
    elif configure_auth:
        print(
            wrap_text("  5. Reconcile the custom authentication origin automatically")
        )
    else:
        print(
            wrap_text(
                "  5. Use this domain for the remaining authentication and email setup"
            )
        )
    print()
    print(
        wrap_text(
            "Cloudflare automation is DNS-only. Records are created with "
            "proxying disabled, and setup never changes WAF, bot, cache, or "
            "zone-security settings."
        )
    )
