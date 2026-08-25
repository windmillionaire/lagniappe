"""Provider-neutral domain verification and DNS instructions."""

from installer import FORMATTER


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_domain_ownership_instructions_name_selected_gcloud_account
# @matrix setup : account-identity custom-domain interactive-input ownership
def confirm_domain_ownership(domain):
    """Explain Google ownership verification and require confirmation."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
    print(f"\n{f.info('Verify domain ownership with Google')}")
    print("1. Use the Google account selected by this installation:")
    print(f"   {account}")
    print(
        "2. Open https://search.google.com/search-console while signed in "
        "to that exact account"
    )
    print("3. Add the registrable domain as a Domain property")
    print("4. Add the verification TXT record at your DNS provider")
    print("5. Wait for Google Search Console to confirm ownership")
    print(
        "6. In Search Console Settings > Users and permissions, confirm "
        "that account is an Owner"
    )
    verified = input(
        f.info(
            f"Has Google confirmed that {account} owns {domain}? [y/N]: "
        )
    )
    return verified.casefold() == "y"


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_supports_manual_dns
# @matrix setup : custom-domain manual-dns provider-records
def print_manual_dns_instructions(domain, resource_records):
    """Print the exact records returned by App Engine."""
    f = FORMATTER.initialize()
    print(f"\n{f.info(f'DNS records for {domain}')}")
    print("Add every record below at your DNS provider with proxying disabled:")
    for record in resource_records:
        record_type = str(record.get("type") or "")
        name = str(record.get("name") or "").strip() or domain
        value = str(record.get("rrdata") or "").strip()
        print(f"  {record_type:<5} {name:<30} {value}")
    print("Use your provider's automatic/default TTL.")
