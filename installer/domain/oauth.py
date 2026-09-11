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
    print(
        wrap_text(
            (
                f"\n{ui.literal('1.')} Go to "
                f"{ui.literal('https://console.cloud.google.com/apis/credentials')}"
            )
        )
    )
    print(
        wrap_text(
            (f"{ui.literal('2.')} Click on your {ui.literal('OAuth 2.0 Client ID')}")
        )
    )
    print(
        wrap_text(
            (
                f"{ui.literal('3.')} Add these URLs to '"
                f"{ui.literal('Authorized JavaScript origins')}':"
            )
        )
    )
    print(f"   {ui.literal(f'https://{domain}')}")
    print(
        wrap_text(
            (
                f"{ui.literal('4.')} Add these URLs to '"
                f"{ui.literal('Authorized redirect URIs')}':"
            )
        )
    )
    print(f"   {ui.literal(f'https://{domain}/users/google-signin')}")
    print(wrap_text((f"{ui.literal('5.')} Click '{ui.literal('Save')}'")))
    print(
        wrap_text(
            f"\n{f.warning('Google sign-in will not work with the custom domain until you update these settings.')}"
        )
    )
