"""App Engine custom-domain setup with optional Cloudflare DNS automation."""

from installer import wrap_text

from .verify import prepare_existing_installation


# @testable false
# @covered-by installer/custom_domain.py::_setup_custom_domain
# @reason entrypoint verification/deploy wrapper around custom-domain setup
def add_custom_domain():
    """Configure a custom domain for an existing installation."""
    prepare_existing_installation()

    from config import SETTINGS
    from installer import FORMATTER, utils

    f = FORMATTER.initialize()
    if not _setup_custom_domain():
        print(f.error("Custom-domain setup is incomplete."))
        return 1

    SETTINGS.save()
    print(
        f.success(
            "The app must be redeployed for custom-domain authentication "
            "settings to take effect."
        )
    )
    consent = input(f.info("Would you like to deploy the app now? [y/N]: "))
    if consent.casefold() == "y":
        utils.deploy_to_app_engine()
        print(
            f"Your app is available at: "
            f"https://{SETTINGS.APP['CUSTOM_DOMAIN']}"
        )
    else:
        print("Custom domain saved. Deploy when ready.")
    return 0


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_uses_provider_records_and_dns_only_cloudflare
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_supports_manual_dns
# @features setup
# @dimensions custom-domain cloudflare-dns dns-only provider-records idempotence disabled-provider
def _setup_custom_domain(*, configure_auth=True):
    """Create the domain mapping and optionally update existing authentication."""
    from config import SETTINGS
    from installer import FORMATTER
    from installer.utils import validate_input

    from .domain import (
        confirm_domain_ownership,
        create_gcp_domain_mapping,
        explain_domain_setup,
        get_cloudflare_api_token,
        get_cloudflare_zone,
        print_manual_dns_instructions,
        reconcile_cloudflare_dns_records,
        update_oauth_redirect_uris,
        validate_domain,
    )

    f = FORMATTER.initialize()

    # @testable false
    # @covered-by installer/custom_domain.py::_setup_custom_domain
    # @reason local input accessor delegates deterministic validation
    @validate_input(
        "Enter your custom domain (for example app.example.com)",
        validation_fn=validate_domain,
        error_msg="Invalid domain format",
    )
    def get_domain(value):
        return value.strip().lower()

    google_signin_enabled = SETTINGS.APP.get("GOOGLE_SIGNIN_ENABLED", True) is True
    explain_domain_setup(
        configure_auth=configure_auth,
        google_signin=google_signin_enabled,
    )
    domain = get_domain()
    if not confirm_domain_ownership(domain):
        print(
            f.warning(
                "Complete Google Search Console ownership verification, then "
                "rerun this command."
            )
        )
        return False

    with f.yaspin(
        text=f.success("Creating or discovering App Engine domain mapping")
    ) as spinner:
        mapping = create_gcp_domain_mapping(domain, spinner)
        spinner.ok(f.ok_glyph)

    resource_records = mapping["resourceRecords"]
    use_cloudflare = input(
        f.info("Configure these DNS records through Cloudflare? [y/N]: ")
    )
    if use_cloudflare.casefold() == "y":
        api_token = get_cloudflare_api_token()
        with f.yaspin(text=f.success("Resolving Cloudflare DNS zone")) as spinner:
            zone = get_cloudflare_zone(domain, api_token)
            spinner.write(f.success(f"Using Cloudflare zone {zone['name']}"))
            spinner.ok(f.ok_glyph)
        with f.yaspin(
            text=f.success("Reconciling DNS-only Cloudflare records")
        ) as spinner:
            record_ids = reconcile_cloudflare_dns_records(
                domain,
                zone,
                api_token,
                resource_records,
            )
            spinner.write(
                f.success(
                    f"Reconciled {len(record_ids)} DNS-only Cloudflare records"
                )
            )
            spinner.ok(f.ok_glyph)
        SETTINGS.APP["CLOUDFLARE_ZONE_ID"] = zone["id"]
        account_id = (zone.get("account") or {}).get("id")
        if account_id:
            SETTINGS.APP["CLOUDFLARE_ACCOUNT_ID"] = account_id
    else:
        print_manual_dns_instructions(domain, resource_records)
        configured = input(
            f.info("Have you added all of the App Engine DNS records? [y/N]: ")
        )
        if configured.casefold() != "y":
            print(
                f.warning(
                    "The App Engine mapping was retained. Add the records and "
                    "rerun this command to finish safely."
                )
            )
            return False
        SETTINGS.APP.pop("CLOUDFLARE_ZONE_ID", None)
        SETTINGS.APP.pop("CLOUDFLARE_ACCOUNT_ID", None)

    SETTINGS.APP["GOOGLE_LOGIN_URI"] = (
        f"https://{domain}/users/google-signin"
    )
    SETTINGS.APP["CUSTOM_DOMAIN"] = domain
    if configure_auth:
        if google_signin_enabled:
            update_oauth_redirect_uris(domain)
            confirmed = input(
                f.info("Have you updated the Google OAuth settings? [y/N]: ")
            )
            if confirmed.casefold() != "y":
                print(
                    f.warning(
                        "The domain mapping and DNS records were retained. Complete "
                        "the authentication settings and rerun this command."
                    )
                )
                return False

        from .identity import setup_identity_platform

        setup_identity_platform(app_url=f"https://{domain}")
    print(f.success(f"Custom domain configured: https://{domain}"))
    print(
        wrap_text(
            "App Engine provisions and renews the managed TLS certificate. DNS "
            "and certificate activation can take time; the default App Engine "
            "URL remains available while they settle."
        )
    )
    return True
