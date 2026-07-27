"""Provider-neutral domain verification and DNS instructions."""

from installer import FORMATTER


# @testable false
# @covered-by installer/custom_domain.py::_setup_custom_domain
# @reason manual Search Console confirmation belongs to the interactive flow
def confirm_domain_ownership(domain):
    """Explain Google ownership verification and require confirmation."""
    f = FORMATTER.initialize()
    print(f"\n{f.info('Verify domain ownership with Google')}")
    print("1. Open https://search.google.com/search-console")
    print("2. Add the registrable domain as a Domain property")
    print("3. Add the verification TXT record at your DNS provider")
    print("4. Wait for Google Search Console to confirm ownership")
    verified = input(
        f.info(f"Has Google confirmed ownership for {domain}? [y/N]: ")
    )
    return verified.casefold() == "y"


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_custom_domain_supports_manual_dns
# @features setup
# @dimensions custom-domain provider-records manual-dns
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
