"""App Engine custom-domain mapping discovery and reconciliation."""

import json
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
def _get_domain_mapping(project_id, domain):
    return _run_gcloud_json(
        [
            "app",
            "domain-mappings",
            "describe",
            domain,
            f"--project={project_id}",
        ],
        allow_not_found=True,
    )


# @testable false
# @covered-by installer/domain/gcp.py::create_gcp_domain_mapping
# @reason provider response validation is owned by mapping reconciliation
def _validated_mapping(mapping, domain):
    if not isinstance(mapping, dict) or mapping.get("id") != domain:
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
# @tests tests_tooling/test_001d_setup_drift.py::test_app_engine_discovery_has_domain_mapping_create
# @features setup
# @dimensions gcp-domain api-drift idempotence provider-records
def create_gcp_domain_mapping(domain, sp, *, sleep=time.sleep):
    """Discover or create a mapping and return Google's exact DNS records."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]

    mapping = retry_provider_call(
        lambda: _get_domain_mapping(project_id, domain),
        description=f"Discover App Engine domain mapping {domain}",
    )
    created = False
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
                        f"--project={project_id}",
                    ]
                ),
                description=f"Create App Engine domain mapping {domain}",
            )
            created = True
        except ProviderConflict:
            # A concurrent or interrupted prior run may have completed creation.
            pass

    for delay in DOMAIN_MAPPING_POLL_DELAYS:
        if delay:
            sleep(delay)
        mapping = retry_provider_call(
            lambda: _get_domain_mapping(project_id, domain),
            description=f"Verify App Engine domain mapping {domain}",
        )
        validated = _validated_mapping(mapping, domain)
        if validated is not None:
            action = "created" if created else "existing"
            record_mutation(
                "custom-domain-mapping",
                action=action,
                resource="App Engine domain mapping",
                identifier=validated.get("name") or domain,
            )
            sp.write(f.success(f"App Engine domain mapping {action}: {domain}"))
            return validated

    raise ProviderTimeout(
        f"App Engine domain mapping {domain} did not return DNS records in time."
    )
