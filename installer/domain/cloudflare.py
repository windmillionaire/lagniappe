"""Optional Cloudflare DNS-only reconciliation for custom domains."""

from getpass import getpass

from installer.errors import (
    ProviderError,
    ProviderNotFound,
    SetupCancelled,
    classify_provider_error,
    retry_provider_call,
)
from installer.package_install import install_if_missing
from installer.state import record_mutation
from installer import wrap_text

from .validation import validate_cloudflare_api_token

CLOUDFLARE_API_ROOT = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_API_TOKEN_URL = "https://dash.cloudflare.com/profile/api-tokens"
CLOUDFLARE_API_TIMEOUT = 10
CLOUDFLARE_RECORD_COMMENT = "Managed by Lagniappe App Engine domain setup"


# @testable false
# @covered-by installer/domain/cloudflare.py::_cloudflare_request
# @reason bearer header adapter is owned by Cloudflare DNS reconciliation
def _cloudflare_headers(api_token):
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


# @testable false
# @covered-by installer/domain/cloudflare.py::_cloudflare_request
# @reason provider error adapter is owned by Cloudflare DNS reconciliation
def _cloudflare_error_message(payload, status_code):
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list):
        messages = [
            str(error.get("message") or "").strip()
            for error in errors
            if isinstance(error, dict)
        ]
        messages = [message for message in messages if message]
        if messages:
            return "; ".join(messages)
    return f"Cloudflare API returned HTTP {status_code}."


# @testable false
# @covered-by installer/domain/cloudflare.py::get_cloudflare_zone
# @covered-by installer/domain/cloudflare.py::reconcile_cloudflare_dns_records
# @reason bounded HTTP adapter is exercised through zone and record contracts
def _cloudflare_request(method, path, api_token, *, params=None, json_data=None):
    install_if_missing("requests", "HTTP library for Cloudflare DNS setup")
    import requests

    # @testable false
    # @covered-by installer/domain/cloudflare.py::_cloudflare_request
    # @reason one-attempt closure is owned by the bounded retrying HTTP adapter
    def request():
        try:
            response = requests.request(
                method,
                f"{CLOUDFLARE_API_ROOT}{path}",
                headers=_cloudflare_headers(api_token),
                params=params,
                json=json_data,
                timeout=CLOUDFLARE_API_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            raise classify_provider_error(error) from error

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.ok and payload.get("success") is not False:
            return payload

        message = _cloudflare_error_message(payload, response.status_code)
        raise classify_provider_error(
            RuntimeError(message),
            message=message,
            status_code=response.status_code,
        )

    return retry_provider_call(
        request,
        description=f"Cloudflare {method} {path}",
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_cloudflare_token_prompt_explains_dashboard_steps_and_scope
# @features setup
# @dimensions cloudflare-api interactive-input least-privilege
def get_cloudflare_api_token():
    """Prompt for a scoped token without echoing or persisting it."""
    print(
        "\n"
        + wrap_text(
            "Cloudflare DNS automation uses a scoped user API token. "
            "Lagniappe uses it only during this run and does not save it."
        )
    )
    print("1. Open Cloudflare's API Tokens page:")
    print(f"   {CLOUDFLARE_API_TOKEN_URL}")
    print(
        wrap_text(
            "   Or, in the Cloudflare dashboard, open My Profile > API Tokens."
        )
    )
    print(wrap_text("2. Select Create Token."))
    print(
        wrap_text(
            "3. Find the 'Edit zone DNS' template and select Use template."
        )
    )
    print(
        wrap_text(
            "4. Set the resource scope to Specified Domains, then select only "
            "the DNS zone you are configuring."
        )
    )
    print(
        wrap_text(
            "5. Under DNS & Zones, select DNS > Edit and Zone > Read. Leave "
            "Zone > Edit off, and do not select all permissions."
        )
    )
    print(
        wrap_text(
            "6. Continue to summary, create the token, and paste the token "
            "shown once below. You can delete it from Cloudflare after setup."
        )
    )
    while True:
        ready = input(
            "Press Enter to paste the token, or x to stop setup: "
        ).strip()
        if ready.casefold() == "x":
            raise SetupCancelled("Setup stopped before Cloudflare DNS changes.")
        token = getpass("Paste Cloudflare API token (input hidden): ").strip()
        if validate_cloudflare_api_token(token):
            return token
        print("Enter a non-empty scoped Cloudflare API token.")


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_cloudflare_dns_only_reconciliation
# @features setup
# @dimensions cloudflare-api zone-resolution
def get_cloudflare_zone(domain, api_token):
    """Resolve the longest provider-owned zone suffix for a hostname."""
    zones = []
    page = 1
    while True:
        payload = _cloudflare_request(
            "GET",
            "/zones",
            api_token,
            params={"page": page, "per_page": 50},
        )
        zones.extend(
            zone for zone in payload.get("result") or [] if isinstance(zone, dict)
        )
        info = payload.get("result_info") or {}
        total_pages = int(info.get("total_pages") or 1)
        if page >= total_pages:
            break
        page += 1

    normalized_domain = domain.rstrip(".").casefold()
    matches = [
        zone
        for zone in zones
        if normalized_domain == str(zone.get("name") or "").casefold()
        or normalized_domain.endswith(
            f".{str(zone.get('name') or '').casefold()}"
        )
    ]
    if not matches:
        raise ProviderNotFound(
            f"The Cloudflare token cannot access a DNS zone for {domain}."
        )
    return max(matches, key=lambda zone: len(str(zone.get("name") or "")))


# @testable false
# @covered-by installer/domain/cloudflare.py::reconcile_cloudflare_dns_records
# @reason provider record normalization is owned by exact DNS reconciliation
def _desired_cloudflare_records(domain, zone_name, resource_records):
    desired = []
    seen = set()
    for record in resource_records:
        record_type = str(record.get("type") or "").upper()
        content = str(record.get("rrdata") or "").rstrip(".").strip()
        relative_name = str(record.get("name") or "").rstrip(".").strip()
        if relative_name:
            name = (
                relative_name
                if relative_name.casefold().endswith(
                    f".{zone_name.casefold()}"
                )
                or relative_name.casefold() == zone_name.casefold()
                else f"{relative_name}.{zone_name}"
            )
        else:
            name = domain
        key = (record_type, name.casefold(), content.casefold())
        if key in seen:
            continue
        seen.add(key)
        desired.append(
            {
                "type": record_type,
                "name": name,
                "content": content,
                "ttl": 1,
                "proxied": False,
                "comment": CLOUDFLARE_RECORD_COMMENT,
            }
        )
    return desired


# @testable false
# @covered-by installer/domain/cloudflare.py::reconcile_cloudflare_dns_records
# @reason journal projection excludes provider metadata not needed for repair
def _record_snapshot(record):
    return {
        "type": record.get("type"),
        "name": record.get("name"),
        "content": record.get("content"),
        "ttl": record.get("ttl"),
        "proxied": bool(record.get("proxied")),
    }


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_cloudflare_dns_only_reconciliation
# @features setup
# @dimensions cloudflare-dns dns-only idempotence provider-records partial-failure
def reconcile_cloudflare_dns_records(
    domain,
    zone,
    api_token,
    resource_records,
):
    """Reconcile only App Engine DNS records, always with proxying disabled."""
    zone_id = str(zone.get("id") or "")
    zone_name = str(zone.get("name") or "")
    if not zone_id or not zone_name:
        raise ProviderError("Cloudflare returned an invalid zone.")

    desired = _desired_cloudflare_records(domain, zone_name, resource_records)
    if not desired:
        raise ProviderError(
            "App Engine did not return any DNS records to configure."
        )

    desired_by_group = {}
    for record in desired:
        desired_by_group.setdefault(
            (record["type"], record["name"].casefold()),
            [],
        ).append(record)

    reconciled_ids = []
    for (record_type, _normalized_name), desired_group in desired_by_group.items():
        name = desired_group[0]["name"]
        payload = _cloudflare_request(
            "GET",
            f"/zones/{zone_id}/dns_records",
            api_token,
            params={"type": record_type, "name": name, "per_page": 100},
        )
        current = [
            record
            for record in payload.get("result") or []
            if isinstance(record, dict)
        ]
        desired_contents = {
            record["content"].casefold() for record in desired_group
        }

        for desired_record in desired_group:
            existing = next(
                (
                    record
                    for record in current
                    if str(record.get("content") or "")
                    .rstrip(".")
                    .casefold()
                    == desired_record["content"].casefold()
                ),
                None,
            )
            if existing is not None:
                record_id = str(existing.get("id") or "")
                previous = _record_snapshot(existing)
                if (
                    int(existing.get("ttl") or 1) != 1
                    or bool(existing.get("proxied"))
                    or existing.get("comment") != CLOUDFLARE_RECORD_COMMENT
                ):
                    result = _cloudflare_request(
                        "PATCH",
                        f"/zones/{zone_id}/dns_records/{record_id}",
                        api_token,
                        json_data=desired_record,
                    ).get("result") or {}
                    record_id = str(result.get("id") or record_id)
                    action = "updated"
                    details = {"previous": previous}
                else:
                    action = "existing"
                    details = None
            else:
                result = _cloudflare_request(
                    "POST",
                    f"/zones/{zone_id}/dns_records",
                    api_token,
                    json_data=desired_record,
                ).get("result") or {}
                record_id = str(result.get("id") or "")
                action = "created"
                details = None

            if not record_id:
                raise ProviderError(
                    f"Cloudflare did not return an ID for {record_type} {name}."
                )
            reconciled_ids.append(record_id)
            record_mutation(
                "custom-domain-dns",
                action=action,
                resource="Cloudflare DNS record",
                identifier=record_id,
                details=details,
            )

        for existing in current:
            content = (
                str(existing.get("content") or "").rstrip(".").casefold()
            )
            if (
                existing.get("comment") != CLOUDFLARE_RECORD_COMMENT
                or content in desired_contents
            ):
                continue
            record_id = str(existing.get("id") or "")
            previous = _record_snapshot(existing)
            _cloudflare_request(
                "DELETE",
                f"/zones/{zone_id}/dns_records/{record_id}",
                api_token,
            )
            record_mutation(
                "custom-domain-dns",
                action="deleted-stale",
                resource="Cloudflare DNS record",
                identifier=record_id,
                details={"previous": previous},
            )

    return reconciled_ids
