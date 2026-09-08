"""App Engine custom-domain setup with optional Cloudflare DNS automation."""

from runner import presentation as ui
from runner.presentation import output as print, read_input as input

from runner.console import format_prompt
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
        print(f.error(wrap_text("Custom-domain setup is incomplete.")))
        return 1

    SETTINGS.save()
    print(
        ui.info(
            wrap_text(
                "The app must be redeployed for custom-domain authentication "
                "settings to take effect."
            )
        )
    )
    consent = input(
        format_prompt("Deploy app now", hint="y/N")
    )
    if consent.casefold() == "y":
        utils.deploy_to_app_engine(print_final_summary=False)
        print(ui.success("Custom domain settings deployed"))
        print(
            ui.value(
                "Open this installation",
                f"https://{SETTINGS.APP['CUSTOM_DOMAIN']}",
                action=True,
                verbatim=True,
                standalone=True,
            )
        )
    else:
        print(wrap_text("Custom domain saved. Deploy when ready."))
    return 0


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_uses_provider_records_and_dns_only_cloudflare
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_supports_manual_dns
# @matrix setup : cloudflare-dns custom-domain disabled-provider dns-only idempotence provider-records
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

    with f.progress(
        text="Creating or discovering App Engine domain mapping",
        success_text='App Engine domain mapping ready',
    ) as spinner:
        mapping = create_gcp_domain_mapping(domain, spinner)
        spinner.ok()

    resource_records = mapping["resourceRecords"]
    use_cloudflare = input(
        format_prompt("Configure these DNS records through Cloudflare? [y/N]: ")
    )
    if use_cloudflare.casefold() == "y":
        api_token = get_cloudflare_api_token()
        with f.progress(
            text="Resolving Cloudflare DNS zone",
            success_text='Cloudflare DNS zone found',
        ) as spinner:
            zone = get_cloudflare_zone(domain, api_token)
            spinner.ok(f"Using Cloudflare zone {zone['name']}")
        with f.progress(
            text="Reconciling DNS-only Cloudflare records",
            success_text='Cloudflare DNS records reconciled',
        ) as spinner:
            record_ids = reconcile_cloudflare_dns_records(
                domain,
                zone,
                api_token,
                resource_records,
            )
            spinner.ok(f"Reconciled {len(record_ids)} DNS-only Cloudflare records")
        SETTINGS.APP["CLOUDFLARE_ZONE_ID"] = zone["id"]
        account_id = (zone.get("account") or {}).get("id")
        if account_id:
            SETTINGS.APP["CLOUDFLARE_ACCOUNT_ID"] = account_id
    else:
        print_manual_dns_instructions(domain, resource_records)
        configured = input(
            format_prompt(
                "Have you added all of the App Engine DNS records? [y/N]: "
            )
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
                format_prompt(
                    "Have you updated the Google OAuth settings? [y/N]: "
                )
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
    print(f.success(wrap_text(f"Custom domain configured: https://{domain}")))
    print(
        wrap_text(
            "App Engine provisions and renews the managed TLS certificate. DNS "
            "and certificate activation can take time; the default App Engine "
            "URL remains available while they settle."
        )
    )
    return True
