"""OAuth redirect URI configuration instructions."""

from runner import presentation as ui
from runner.presentation import output as print

from runner.console import wrap_text
from installer import FORMATTER


# @testable false
# @reason console-only custom-domain Google OAuth instructions
def update_oauth_redirect_uris(domain):
    """Provide instructions for updating OAuth redirect URIs."""
    f = FORMATTER.initialize()
    print(wrap_text(f"\n{ui.heading('Update authentication settings')}"))
    print(
        wrap_text(
            "Your OAuth configuration needs to be updated to configure Google sign-in:"
        )
    )
    print(wrap_text("\n1. Go to https://console.cloud.google.com/apis/credentials"))
    print(wrap_text("2. Click on your OAuth 2.0 Client ID"))
    print(wrap_text("3. Add these URLs to 'Authorized JavaScript origins':"))
    print(wrap_text(f"   https://{domain}"))
    print(wrap_text("4. Add these URLs to 'Authorized redirect URIs':"))
    print(wrap_text(f"   https://{domain}/users/google-signin"))
    print(wrap_text("5. Click 'Save'"))
    print(
        wrap_text(
            f"\n{f.warning('Google sign-in will not work with the custom domain until you update these settings.')}"
        )
    )
