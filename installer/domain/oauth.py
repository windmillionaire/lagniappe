"""OAuth redirect URI configuration instructions."""

from installer import FORMATTER


# @testable false
# @reason console-only custom-domain Google OAuth instructions
def update_oauth_redirect_uris(domain):
    """Provide instructions for updating OAuth redirect URIs."""
    f = FORMATTER.initialize()
    print(f"\n{f.info('Update Authentication Settings')}")
    print("=" * 40)
    print("Your OAuth configuration needs to be updated to configure Google sign-in:")
    print("\n1. Go to https://console.cloud.google.com/apis/credentials")
    print("2. Click on your OAuth 2.0 Client ID")
    print("3. Add these URLs to 'Authorized JavaScript origins':")
    print(f"   https://{domain}")
    print("4. Add these URLs to 'Authorized redirect URIs':")
    print(f"   https://{domain}/users/google-signin")
    print("5. Click 'Save'")
    print(
        f"\n{f.warning('Important: Google sign-in will not work with the custom domain until you update these settings!')}"
    )
