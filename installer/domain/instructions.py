"""Console guidance for the custom-domain workflow."""

from installer import FORMATTER, wrap_text


# @testable false
# @covered-by installer/custom_domain.py::_setup_custom_domain
# @reason console-only overview for the custom-domain workflow
def explain_domain_setup(*, configure_auth=True, google_signin=True):
    """Explain the supported App Engine and optional DNS automation."""
    f = FORMATTER.initialize()
    print(f"\n{f.info('Custom Domain Setup for Lagniappe')}")
    print("=" * 50)
    print("This flow will:")
    print("  1. Confirm Google domain ownership verification")
    print("  2. Create or discover the App Engine domain mapping")
    print("  3. Read the exact DNS records returned by App Engine")
    print("  4. Add those records through Cloudflare, or print them for manual entry")
    if configure_auth and google_signin:
        print(
            "  5. Guide the Google OAuth update and reconcile Identity "
            "Platform automatically"
        )
    elif configure_auth:
        print("  5. Reconcile the custom authentication origin automatically")
    else:
        print(
            "  5. Use this domain for the remaining authentication and email "
            "setup"
        )
    print()
    print(
        wrap_text(
            "Cloudflare automation is DNS-only. Records are created with "
            "proxying disabled, and setup never changes WAF, bot, cache, or "
            "zone-security settings."
        )
    )
