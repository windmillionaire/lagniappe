"""Provider-neutral domain verification and DNS instructions."""

from runner import presentation as ui
from runner.presentation import output as print, read_input as input

from runner.console import format_prompt, wrap_text
from installer import FORMATTER


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_domain_ownership_instructions_name_selected_gcloud_account
# @matrix setup : account-identity custom-domain interactive-input ownership
def confirm_domain_ownership(domain):
    """Explain Google ownership verification and require confirmation."""
    from config import SETTINGS

    FORMATTER.initialize()
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
    print(wrap_text(f"\n{ui.heading('Verify domain ownership with Google')}"))
    print(
        wrap_text(
            (
                f"{ui.literal('1.')} Use the Google account selected by this "
                "installation:"
            )
        )
    )
    print(f"   {ui.literal(account)}")
    print(
        wrap_text(
            (
                f"{ui.literal('2.')} Open "
                f"{ui.literal('https://search.google.com/search-console')} while signed "
                "in to that exact account"
            )
        )
    )
    print(
        wrap_text(
            (
                f"{ui.literal('3.')} Add the registrable domain as a "
                f"{ui.literal('Domain property')}"
            )
        )
    )
    print(
        wrap_text(
            (f"{ui.literal('4.')} Add the verification TXT record at your DNS provider")
        )
    )
    print(
        wrap_text(
            (f"{ui.literal('5.')} Wait for Google Search Console to confirm ownership")
        )
    )
    print(
        wrap_text(
            (
                f"{ui.literal('6.')} In Search Console "
                f"{ui.literal('Settings > Users and permissions')}, confirm that account "
                f"is an {ui.literal('Owner')}"
            )
        )
    )
    verified = input(
        format_prompt(
            f"Has Google confirmed that {account} owns {domain}? [y/N]: "
        )
    )
    return verified.casefold() == "y"


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_supports_manual_dns
# @tests tests_tooling/test_001k_setup_console.py::test_dns_values_remain_verbatim
# @matrix setup : custom-domain manual-dns provider-records terminal-wrapping
def print_manual_dns_instructions(domain, resource_records):
    """Print the exact records returned by App Engine."""
    FORMATTER.initialize()
    print(wrap_text(f"\n{ui.heading(f'DNS records for {domain}')}"))
    print(
        wrap_text("Add every record below at your DNS provider with proxying disabled:")
    )
    for record in resource_records:
        record_type = str(record.get("type") or "")
        name = str(record.get("name") or "").strip() or domain
        value = str(record.get("rrdata") or "").strip()
        print(ui.value("  Type", record_type, verbatim=True, action=True))
        print(ui.value("  Name", name, verbatim=True, action=True))
        print(ui.value("  Value", value, verbatim=True, action=True))
        print()
    print(wrap_text("Use your provider's automatic/default TTL."))
