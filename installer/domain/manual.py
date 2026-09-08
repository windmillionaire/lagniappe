"""Provider-neutral domain verification and DNS instructions."""

from runner import presentation as ui
from runner.presentation import output as print, read_input as input

from runner.console import format_prompt, format_value, wrap_text
from installer import FORMATTER


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_domain_ownership_instructions_name_selected_gcloud_account
# @matrix setup : account-identity custom-domain interactive-input ownership
def confirm_domain_ownership(domain):
    """Explain Google ownership verification and require confirmation."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
    print(wrap_text(f"\n{ui.heading('Verify domain ownership with Google')}"))
    print(wrap_text("1. Use the Google account selected by this installation:"))
    print(f"   {account}")
    print(
        wrap_text(
            "2. Open https://search.google.com/search-console while signed in "
            "to that exact account"
        )
    )
    print(wrap_text("3. Add the registrable domain as a Domain property"))
    print(wrap_text("4. Add the verification TXT record at your DNS provider"))
    print(wrap_text("5. Wait for Google Search Console to confirm ownership"))
    print(
        wrap_text(
            "6. In Search Console Settings > Users and permissions, confirm "
            "that account is an Owner"
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
    f = FORMATTER.initialize()
    print(wrap_text(f"\n{ui.heading(f'DNS records for {domain}')}"))
    print(
        wrap_text("Add every record below at your DNS provider with proxying disabled:")
    )
    for record in resource_records:
        record_type = str(record.get("type") or "")
        name = str(record.get("name") or "").strip() or domain
        value = str(record.get("rrdata") or "").strip()
        print(format_value("  Type", record_type, verbatim=True))
        print(format_value("  Name", name, verbatim=True))
        print(format_value("  Value", value, verbatim=True))
        print()
    print(wrap_text("Use your provider's automatic/default TTL."))
