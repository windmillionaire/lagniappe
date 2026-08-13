"""App Engine custom-domain mapping discovery and reconciliation."""

import json
import socket
import ssl
import subprocess
import time

from installer import FORMATTER, GCLOUD_CLI
from installer.errors import (
    GCLOUD_TIMEOUT,
    ProviderConflict,
    ProviderError,
    ProviderNotFound,
    ProviderTimeout,
    classify_provider_error,
    retry_provider_call,
)
from installer.state import record_mutation

DOMAIN_MAPPING_POLL_DELAYS = (0, 1, 2, 4, 8)
MANAGED_CERTIFICATE_POLL_DELAYS = (0,) + (15,) * 40


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @reason subprocess adapter is owned by App Engine mapping reconciliation
def _run_gcloud_json(arguments, *, allow_not_found=False):
    if not GCLOUD_CLI:
        raise ProviderError("gcloud CLI not found.")

    try:
        result = subprocess.run(
            [
                GCLOUD_CLI,
                *arguments,
                "--format=json",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=GCLOUD_TIMEOUT,
        )
    except subprocess.TimeoutExpired as error:
        raise ProviderTimeout(
            f"gcloud {' '.join(arguments)} timed out after "
            f"{GCLOUD_TIMEOUT} seconds."
        ) from error

    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        error = classify_provider_error(
            RuntimeError(detail),
            message=detail or f"gcloud {' '.join(arguments)} failed.",
        )
        if allow_not_found and isinstance(error, ProviderNotFound):
            return None
        raise error

    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ProviderError(
            "gcloud returned malformed JSON for the App Engine domain mapping."
        ) from error


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @reason discovery adapter is owned by App Engine mapping reconciliation
def _get_domain_mapping(project_id, domain, account=None):
    target_flags = [f"--project={project_id}"]
    if account:
        target_flags.append(f"--account={account}")
    return _run_gcloud_json(
        [
            "app",
            "domain-mappings",
            "describe",
            domain,
            *target_flags,
        ],
        allow_not_found=True,
    )


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason list adapter is owned by domain reconciliation and readiness polling
def _list_domain_mappings(project_id, account=None):
    target_flags = [f"--project={project_id}"]
    if account:
        target_flags.append(f"--account={account}")
    mappings = _run_gcloud_json(
        [
            "app",
            "domain-mappings",
            "list",
            *target_flags,
        ]
    )
    if not isinstance(mappings, list):
        raise ProviderError(
            "gcloud returned malformed JSON while listing App Engine domain "
            f"mappings for project {project_id}."
        )
    return mappings


# @testable false
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason discovery adapter is owned by managed-certificate readiness polling
def _get_ssl_certificate(project_id, certificate_id, account=None):
    target_flags = [f"--project={project_id}"]
    if account:
        target_flags.append(f"--account={account}")
    return _run_gcloud_json(
        [
            "app",
            "ssl-certificates",
            "describe",
            certificate_id,
            *target_flags,
        ],
        allow_not_found=True,
    )


# @testable false
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason TLS handshake adapter is exercised through readiness polling
def _https_certificate_is_served(domain, *, timeout=10):
    context = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=timeout) as connection:
            with context.wrap_socket(connection, server_hostname=domain):
                return True
    except OSError:
        return False


# @testable false
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason provider response normalization is owned by readiness polling
def _managed_certificate_status(certificate):
    if not isinstance(certificate, dict):
        return "PENDING"
    managed = certificate.get("managedCertificate")
    if not isinstance(managed, dict):
        managed = certificate.get("managed_certificate")
    if not isinstance(managed, dict):
        return "PENDING"
    return str(managed.get("status") or "PENDING").strip().upper()


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason SSL response normalization is owned by domain reconciliation/readiness
def _ssl_settings(mapping):
    if not isinstance(mapping, dict):
        return None
    settings = mapping.get("sslSettings")
    if settings is None:
        settings = mapping.get("ssl_settings")
    return settings if isinstance(settings, dict) else None


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @reason automatic-management validation is owned by domain reconciliation
def _uses_automatic_ssl(mapping):
    settings = _ssl_settings(mapping)
    if settings is None:
        return False
    management_type = str(
        settings.get("sslManagementType")
        or settings.get("ssl_management_type")
        or "SSL_MANAGEMENT_TYPE_UNSPECIFIED"
    ).strip().upper()
    return management_type in {
        "AUTOMATIC",
        "SSL_MANAGEMENT_TYPE_UNSPECIFIED",
    }


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason provider resource identity validation is owned by domain reconciliation
def _mapping_matches_target(mapping, project_id, domain):
    if not isinstance(mapping, dict):
        return False
    expected_name = f"apps/{project_id}/domainMappings/{domain}"
    return mapping.get("id") == domain and mapping.get("name") == expected_name


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @covered-by installer/domain/gcp.py::wait_for_managed_certificate
# @reason exact list selection is owned by domain reconciliation/readiness
def _listed_domain_mapping(mappings, project_id, domain):
    expected_name = f"apps/{project_id}/domainMappings/{domain}"
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        if mapping.get("id") == domain or mapping.get("name") == expected_name:
            if not _mapping_matches_target(mapping, project_id, domain):
                raise ProviderError(
                    "Google Cloud listed a custom-domain resource that did not "
                    f"match {expected_name}: {mapping.get('name')!r}."
                )
            return mapping
    return None


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_managed_certificate_waits_for_provider_and_https_readiness
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_managed_certificate_reports_permanent_provider_failure
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_managed_certificate_timeout_keeps_deployment_incomplete
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_managed_certificate_reports_missing_domain_mapping
# @features setup
# @dimensions gcp-domain managed-certificate deploy retry timeout operator-guidance https provider-status provider-failure incomplete-deployment missing-resource account-project
def wait_for_managed_certificate(
    domain,
    *,
    sleep=time.sleep,
    poll_delays=MANAGED_CERTIFICATE_POLL_DELAYS,
    https_probe=_https_certificate_is_served,
):
    """Wait for Google's managed certificate and a verified TLS handshake."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    account = str(SETTINGS.GCLOUD_CONFIG.get("ACCOUNT") or "").strip()
    target = f"Google Cloud project {project_id}"
    if account:
        target += f" using {account}"
    inspection_flags = f"--project={project_id}"
    if account:
        inspection_flags += f" --account={account}"
    delays = tuple(poll_delays)
    wait_minutes = max(1, round(sum(delays) / 60))
    wait_description = (
        "1 minute" if wait_minutes == 1 else f"{wait_minutes} minutes"
    )
    last_status = "PENDING"

    print(
        f"Checking the App Engine managed TLS certificate for https://{domain} "
        f"in {target}. This can take up to {wait_description}."
    )
    for attempt, delay in enumerate(delays):
        if delay:
            sleep(delay)

        mappings = retry_provider_call(
            lambda: _list_domain_mappings(project_id, account),
            description=f"List App Engine domain mappings in project {project_id}",
        )
        listed_mapping = _listed_domain_mapping(mappings, project_id, domain)
        if listed_mapping is None:
            raise ProviderNotFound(
                "Deployment succeeded, but no App Engine domain mapping for "
                f"{domain} exists in Google Cloud project {project_id}.",
                repair_action=(
                    f"Confirm account {account or '<configured-account>'} and "
                    f"project {project_id}, then run `gcloud app domain-mappings "
                    f"describe {domain} {inspection_flags}` and rerun the "
                    "custom-domain setup."
                ),
            )
        mapping = retry_provider_call(
            lambda: _get_domain_mapping(project_id, domain, account),
            description=f"Describe App Engine domain mapping {domain}",
        )
        if not _mapping_matches_target(mapping, project_id, domain):
            raise ProviderError(
                "Google Cloud returned an unexpected App Engine domain mapping "
                f"while checking https://{domain} in {target}: "
                f"{mapping.get('name') if isinstance(mapping, dict) else mapping!r}.",
                repair_action=(
                    "Run `gcloud app domain-mappings describe "
                    f"{domain} {inspection_flags} --format=json` and confirm its "
                    f"name is apps/{project_id}/domainMappings/{domain}."
                ),
            )
        ssl_settings = _ssl_settings(mapping)
        if ssl_settings is None:
            raise ProviderError(
                f"The App Engine domain mapping for {domain} is not configured "
                f"for managed TLS in {target}.",
                repair_action=(
                    "Rerun the custom-domain setup to enable automatic "
                    f"certificate management for {domain} in project "
                    f"{project_id}."
                ),
            )
        management_type = str(
            ssl_settings.get("sslManagementType")
            or ssl_settings.get("ssl_management_type")
            or "SSL_MANAGEMENT_TYPE_UNSPECIFIED"
        ).strip().upper()
        if management_type == "MANUAL":
            raise ProviderError(
                f"The App Engine domain mapping for {domain} uses manual TLS "
                f"instead of a Google-managed certificate in {target}.",
                repair_action=(
                    "Rerun the custom-domain setup to enable automatic "
                    f"certificate management for {domain} in project "
                    f"{project_id}."
                ),
            )
        active_id = str(ssl_settings.get("certificateId") or "").strip()
        pending_id = str(
            ssl_settings.get("pendingManagedCertificateId") or ""
        ).strip()

        if active_id:
            last_status = "ACTIVE"
            if https_probe(domain):
                print(
                    f.success(
                        f"Managed TLS certificate {active_id} active for "
                        f"https://{domain} in {target}; HTTPS ready."
                    )
                )
                return True
            last_status = "ACTIVE; WAITING FOR HTTPS"
        elif pending_id:
            certificate = retry_provider_call(
                lambda: _get_ssl_certificate(project_id, pending_id, account),
                description=f"Check App Engine managed certificate {pending_id}",
            )
            last_status = _managed_certificate_status(certificate)
            if last_status == "FAILED_PERMANENT":
                raise ProviderError(
                    "App Engine permanently failed to provision the managed "
                    f"TLS certificate {pending_id} for https://{domain} in "
                    f"{target}.",
                    repair_action=(
                        "Verify the domain's App Engine DNS records and CAA policy, "
                        "then run `gcloud app domain-mappings describe "
                        f"{domain} {inspection_flags}` and rerun setup."
                    ),
                )
        else:
            last_status = "PENDING"

        if attempt < len(delays) - 1:
            next_delay = delays[attempt + 1]
            if last_status == "ACTIVE; WAITING FOR HTTPS":
                detail = (
                    f"Google reports certificate {active_id} active for "
                    f"https://{domain} in {target}, but the HTTPS "
                    "edge is not serving it yet"
                )
            else:
                certificate_id = pending_id or "not assigned yet"
                detail = (
                    f"Managed TLS certificate {certificate_id} for "
                    f"https://{domain} in {target}: {last_status}"
                )
            print(f"{detail}. Retrying in {next_delay} seconds...")

    raise ProviderTimeout(
        "Deployment succeeded, but the App Engine managed TLS certificate for "
        f"https://{domain} in {target} is still {last_status} after "
        f"{wait_description}.",
        repair_action=(
            "Leave the App Engine DNS records in place, then run "
            f"`gcloud app domain-mappings describe {domain} "
            f"{inspection_flags}` and rerun setup."
        ),
    )


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @reason provider response validation is owned by mapping reconciliation
def _validated_mapping(mapping, project_id, domain):
    if not _mapping_matches_target(mapping, project_id, domain):
        return None
    records = mapping.get("resourceRecords")
    if not isinstance(records, list) or not records:
        return None
    for record in records:
        if not isinstance(record, dict):
            return None
        if record.get("type") not in {"A", "AAAA", "CNAME"}:
            return None
        if not str(record.get("rrdata") or "").strip():
            return None
    return mapping


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_gcp_domain_mapping_and_ai_cache_commands
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_empty_mapping_list_creates_managed_mapping
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_existing_domain_mapping_enables_managed_tls
# @tests tests_tooling/test_001d_setup_drift.py::test_app_engine_discovery_has_domain_mapping_create
# @features setup
# @dimensions gcp-domain managed-certificate missing-resource reconciliation api-drift idempotence provider-records
def create_gcp_domain_mapping(domain, sp, *, sleep=time.sleep):
    """Discover or create a mapping and return Google's exact DNS records."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    account = str(SETTINGS.GCLOUD_CONFIG.get("ACCOUNT") or "").strip()
    target_flags = [f"--project={project_id}"]
    if account:
        target_flags.append(f"--account={account}")
    target = f"project {project_id}"
    if account:
        target += f" using {account}"

    mappings = retry_provider_call(
        lambda: _list_domain_mappings(project_id, account),
        description=f"List App Engine domain mappings in project {project_id}",
    )
    mapping = _listed_domain_mapping(mappings, project_id, domain)
    if mapping is not None:
        mapping = retry_provider_call(
            lambda: _get_domain_mapping(project_id, domain, account),
            description=f"Describe App Engine domain mapping {domain}",
        )
        if not _mapping_matches_target(mapping, project_id, domain):
            raise ProviderError(
                "Google Cloud described an App Engine domain mapping outside "
                f"apps/{project_id}/domainMappings/{domain}: "
                f"{mapping.get('name') if isinstance(mapping, dict) else mapping!r}."
            )
    created = False
    updated = False
    if mapping is None:
        try:
            retry_provider_call(
                lambda: _run_gcloud_json(
                    [
                        "app",
                        "domain-mappings",
                        "create",
                        domain,
                        "--certificate-management=automatic",
                        *target_flags,
                    ]
                ),
                description=f"Create App Engine domain mapping {domain}",
            )
            created = True
        except ProviderConflict:
            # A concurrent or interrupted prior run may have completed creation.
            pass
    elif not _uses_automatic_ssl(mapping):
        retry_provider_call(
            lambda: _run_gcloud_json(
                [
                    "app",
                    "domain-mappings",
                    "update",
                    domain,
                    "--certificate-management=automatic",
                    *target_flags,
                ]
            ),
            description=f"Enable managed TLS for App Engine domain {domain}",
        )
        updated = True

    for delay in DOMAIN_MAPPING_POLL_DELAYS:
        if delay:
            sleep(delay)
        mappings = retry_provider_call(
            lambda: _list_domain_mappings(project_id, account),
            description=f"Verify App Engine domain mapping list for {domain}",
        )
        listed_mapping = _listed_domain_mapping(mappings, project_id, domain)
        if listed_mapping is None:
            continue
        mapping = retry_provider_call(
            lambda: _get_domain_mapping(project_id, domain, account),
            description=f"Verify App Engine domain mapping {domain}",
        )
        validated = _validated_mapping(mapping, project_id, domain)
        if validated is not None and _uses_automatic_ssl(validated):
            action = "created" if created else "updated" if updated else "existing"
            ssl_settings = _ssl_settings(validated) or {}
            management_type = str(
                ssl_settings.get("sslManagementType")
                or ssl_settings.get("ssl_management_type")
                or "SSL_MANAGEMENT_TYPE_UNSPECIFIED"
            ).strip().upper()
            certificate_id = str(
                ssl_settings.get("certificateId")
                or ssl_settings.get("pendingManagedCertificateId")
                or "not assigned yet"
            ).strip()
            record_mutation(
                "custom-domain-mapping",
                action=action,
                resource="App Engine domain mapping",
                identifier=validated.get("name") or domain,
            )
            sp.write(
                f.success(
                    f"App Engine domain mapping {action}: {validated['name']} "
                    f"using {account or '<configured-account>'}; managed TLS "
                    f"{management_type}, certificate {certificate_id}"
                )
            )
            return validated

    raise ProviderTimeout(
        f"App Engine domain mapping {domain} in {target} did not return DNS "
        "records with automatic managed TLS in time."
    )
