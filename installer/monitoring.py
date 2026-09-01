"""Focused reconciliation for Lagniappe's App Engine memory alert."""

from __future__ import annotations

from copy import deepcopy
from urllib.parse import quote

from runner.context import setup_command


MONITORING_API = "monitoring.googleapis.com"
MONITORING_ROOT = "https://monitoring.googleapis.com/v3"
MANAGED_BY = "lagniappe"
MANAGED_PURPOSE = "app_engine_memory"
POLICY_DISPLAY_NAME = "Lagniappe App Engine memory pressure"
POLICY_LABELS = {"managed_by": MANAGED_BY, "purpose": MANAGED_PURPOSE}
INSTANCE_CLASS_MEMORY_MIB = {
    "F1": 384,
    "F2": 768,
    "F4": 1536,
    "F4_1G": 3072,
    "B1": 384,
    "B2": 768,
    "B4": 1536,
    "B4_1G": 3072,
    "B8": 3072,
}
THRESHOLD_RATIO = 0.8
ALERT_DURATION_SECONDS = 120


class MonitoringReconciliationError(RuntimeError):
    """Raised when the focused monitoring resource cannot be reconciled."""


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason stable-label recognition is exercised through reconciliation and inspection
def _managed(resource):
    labels = resource.get("userLabels") or {}
    return (
        labels.get("managed_by") == MANAGED_BY
        and labels.get("purpose") == MANAGED_PURPOSE
    )


# @testable false
# @covered-by installer/monitoring.py::memory_threshold
# @reason instance-class lookup is exercised through the public threshold contract
def _instance_class(settings):
    instance_class = str(settings.get("DEPLOY_INSTANCE_CLASS") or "").upper()
    if instance_class not in INSTANCE_CLASS_MEMORY_MIB:
        raise MonitoringReconciliationError(
            f"Unsupported App Engine instance class: {instance_class or '(missing)'}"
        )
    return instance_class


# @testable true
# @tests tests_tooling/test_001i_setup_monitoring.py::test_memory_threshold_is_derived_from_each_supported_instance_class
# @matrix monitoring setup : instance-class threshold
def memory_threshold(settings):
    """Return the configured memory envelope and its 80% warning threshold."""
    instance_class = _instance_class(settings)
    envelope_mib = INSTANCE_CLASS_MEMORY_MIB[instance_class]
    return {
        "instance_class": instance_class,
        "envelope_mib": envelope_mib,
        "threshold_mib": envelope_mib * THRESHOLD_RATIO,
        "threshold_bytes": envelope_mib * 1024 * 1024 * THRESHOLD_RATIO,
    }


# @testable false
# @covered-by installer/monitoring.py::memory_policy_payload
# @reason MQL construction is asserted through the complete policy payload
def _memory_query(settings):
    threshold = memory_threshold(settings)["threshold_bytes"]
    return "\n".join(
        [
            "fetch gae_app",
            "| filter resource.module_id == 'default'",
            "| { metric 'appengine.googleapis.com/system/memory/usage'",
            "    | align mean_aligner(1m)",
            "    | every 1m",
            "    | group_by [resource.module_id, resource.version_id, resource.zone],",
            "        [memory_usage: sum(value.usage)]",
            "  ; metric 'appengine.googleapis.com/system/instance_count'",
            "    | align mean_aligner(1m)",
            "    | every 1m",
            "    | group_by [resource.module_id, resource.version_id, resource.zone],",
            "        [instance_count: sum(value.instance_count)]",
            "  }",
            "| join",
            "| value [memory_per_instance: val(0) / val(1)]",
            f"| condition val() > {threshold:.1f}",
        ]
    )


# @testable false
# @covered-by installer/monitoring.py::memory_policy_payload
# @reason chart-link encoding is asserted through policy documentation
def _chart_url(project):
    query = (
        "fetch gae_app | metric "
        "'appengine.googleapis.com/system/memory/usage' | "
        "filter resource.module_id == 'default'"
    )
    return (
        "https://console.cloud.google.com/monitoring/metrics-explorer?"
        f"project={quote(project, safe='')}&pageState={quote(query, safe='')}"
    )


# @testable false
# @covered-by installer/monitoring.py::memory_policy_payload
# @reason responder guidance is asserted through the complete policy payload
def _documentation(settings, project):
    threshold = memory_threshold(settings)
    workers = str(settings.get("DEPLOY_WORKER_COUNT") or "3")
    return "\n\n".join(
        [
            "Lagniappe-managed warning for memory pressure in the App Engine "
            "default service, grouped independently by revision and zone.",
            f"Configured instance class: **{threshold['instance_class']}**. "
            f"Gunicorn workers: **{workers}**. Warning threshold: **80% of "
            f"{threshold['envelope_mib']} MiB ({threshold['threshold_mib']:g} "
            "MiB per instance) for two minutes**. The policy divides "
            "`system/memory/usage` by `system/instance_count`, sampled once "
            "per minute.",
            "Remediation: inspect the affected revision, confirm three workers "
            "for F2/B2, reduce worker count if it is higher on another class, "
            "and review recent code or workload changes before increasing the "
            "instance class.",
            f"[Open the Monitoring memory chart]({_chart_url(project)})",
        ]
    )


# @testable true
# @tests tests_tooling/test_001i_setup_monitoring.py::test_memory_policy_payload_uses_per_instance_query_and_actionable_documentation
# @matrix monitoring setup : alert-policy documentation memory-pressure payload
def memory_policy_payload(settings, project, notification_channels):
    """Build the exact owned alert-policy fields."""
    return {
        "displayName": POLICY_DISPLAY_NAME,
        "documentation": {
            "content": _documentation(settings, project),
            "mimeType": "text/markdown",
        },
        "userLabels": dict(POLICY_LABELS),
        "conditions": [
            {
                "displayName": "Per-instance App Engine memory above 80%",
                "conditionMonitoringQueryLanguage": {
                    "query": _memory_query(settings),
                    "duration": f"{ALERT_DURATION_SECONDS}s",
                    "trigger": {"count": 1},
                },
            }
        ],
        "combiner": "OR",
        "enabled": True,
        "severity": "WARNING",
        "notificationChannels": sorted(set(notification_channels)),
        "alertStrategy": {
            "autoClose": "1800s",
            "notificationPrompts": ["OPENED"],
        },
    }


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason paginated provider reads are exercised through reconciliation and inspection
def _list_resources(session, url, headers, key):
    from installer.google_provider import _api_request

    resources = []
    page_token = None
    while True:
        page_url = url
        if page_token:
            separator = "&" if "?" in page_url else "?"
            page_url += f"{separator}pageToken={quote(page_token, safe='')}"
        _response, payload = _api_request(session, "GET", page_url, headers)
        resources.extend(payload.get(key) or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            return resources


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @reason channel-label lookup is exercised through owner reconciliation
def _email(channel):
    return str((channel.get("labels") or {}).get("email_address") or "").strip()


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @reason enabled-channel filtering is exercised through owner reconciliation
def _enabled(channel):
    return channel.get("enabled") is not False


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason owner-channel selection is exercised through reconciliation and drift inspection
def _choose_owner_channel(channels, owner_email):
    expected = owner_email.casefold()
    matching = [
        channel
        for channel in channels
        if channel.get("type") == "email"
        and _enabled(channel)
        and _email(channel).casefold() == expected
    ]
    matching.sort(key=lambda channel: (not _managed(channel), channel.get("name", "")))
    return matching[0] if matching else None


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @reason managed channel creation is exercised through owner reconciliation
def _create_owner_channel(session, project, headers, owner_email):
    from installer.google_provider import _api_request

    url = f"{MONITORING_ROOT}/projects/{project}/notificationChannels"
    _response, channel = _api_request(
        session,
        "POST",
        url,
        headers,
        json_data={
            "type": "email",
            "displayName": "Lagniappe owner memory alerts",
            "description": "Lagniappe-managed App Engine memory warning channel.",
            "labels": {"email_address": owner_email},
            "userLabels": dict(POLICY_LABELS),
            "enabled": True,
        },
        allow_codes=[201],
    )
    if not channel.get("name"):
        raise MonitoringReconciliationError(
            "Monitoring did not return the created notification channel."
        )
    return channel


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason provider-owned field normalization is exercised through idempotence and drift checks
def _owned_policy_fields(policy):
    owned = {
        key: policy.get(key)
        for key in (
            "displayName",
            "documentation",
            "userLabels",
            "combiner",
            "enabled",
            "severity",
            "notificationChannels",
            "alertStrategy",
        )
    }
    owned["conditions"] = [
        {
            key: condition.get(key)
            for key in ("displayName", "conditionMonitoringQueryLanguage")
        }
        for condition in policy.get("conditions") or []
    ]
    return owned


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason normalized equality is exercised through idempotence and drift checks
def _policy_matches(policy, expected):
    return _owned_policy_fields(policy) == _owned_policy_fields(expected)


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @reason channel ownership and operator preservation are asserted by reconciliation tests
def _desired_channels(existing_policy, channels, selected_channel):
    managed_names = {
        channel.get("name")
        for channel in channels
        if _managed(channel) and channel.get("type") == "email"
    }
    current = (existing_policy or {}).get("notificationChannels") or []
    operator_channels = [name for name in current if name not in managed_names]
    return sorted(set([*operator_channels, selected_channel["name"]]))


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason authenticated REST setup is exercised through the public provider operations
def _provider_context(project, *, session=None):
    if session is None:
        import requests

        session = requests.Session()
    from installer.google_provider import _get_access_token, _google_request_headers

    token = _get_access_token()
    if not token:
        raise MonitoringReconciliationError(
            "Google credentials are unavailable for Monitoring reconciliation."
        )
    return session, _google_request_headers(token, project, json_content=True)


# @testable false
# @covered-by installer/monitoring.py::reconcile_memory_alert
# @covered-by installer/monitoring.py::inspect_memory_alert
# @reason managed resource discovery is exercised through reconciliation and drift inspection
def _resources(session, project, headers):
    base = f"{MONITORING_ROOT}/projects/{project}"
    channels = _list_resources(
        session,
        f"{base}/notificationChannels",
        headers,
        "notificationChannels",
    )
    policies = _list_resources(
        session,
        f"{base}/alertPolicies",
        headers,
        "alertPolicies",
    )
    return channels, [policy for policy in policies if _managed(policy)]


# @testable true
# @tests tests_tooling/test_001i_setup_monitoring.py::test_reconcile_reuses_owner_channel_preserves_operator_channels_and_is_idempotent
# @tests tests_tooling/test_001i_setup_monitoring.py::test_reconcile_creates_owner_channel_and_detaches_obsolete_managed_channels
# @matrix monitoring setup : alert-policy creation idempotence notification-channel operator-preservation owner-reconciliation
def reconcile_memory_alert(*, settings=None, project=None, session=None):
    """Enable Monitoring and reconcile one managed policy and owner channel."""
    from config import SETTINGS
    from installer.google_provider import _api_request
    from installer.utils import run_gcloud_command

    settings = settings or SETTINGS.APP
    project = str(project or settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    owner_email = str(settings.get("ADMIN_EMAIL") or "").strip()
    if not project or not owner_email:
        raise MonitoringReconciliationError(
            "GOOGLE_CLOUD_PROJECT and ADMIN_EMAIL are required for memory monitoring."
        )
    memory_threshold(settings)

    run_gcloud_command(["services", "enable", MONITORING_API, f"--project={project}"])
    session, headers = _provider_context(project, session=session)
    channels, managed_policies = _resources(session, project, headers)
    if len(managed_policies) > 1:
        raise MonitoringReconciliationError(
            "More than one Lagniappe-managed memory policy exists; review them "
            "before retrying."
        )

    selected_channel = _choose_owner_channel(channels, owner_email)
    if selected_channel is None:
        selected_channel = _create_owner_channel(session, project, headers, owner_email)
        channels.append(selected_channel)

    existing_policy = managed_policies[0] if managed_policies else None
    desired_channels = _desired_channels(existing_policy, channels, selected_channel)
    expected = memory_policy_payload(settings, project, desired_channels)
    base = f"{MONITORING_ROOT}/projects/{project}/alertPolicies"
    if existing_policy and _policy_matches(existing_policy, expected):
        return existing_policy

    if existing_policy:
        name = existing_policy.get("name")
        if not name:
            raise MonitoringReconciliationError(
                "The managed memory policy has no provider resource name."
            )
        update_mask = quote(
            ",".join(
                [
                    "display_name",
                    "documentation",
                    "user_labels",
                    "conditions",
                    "combiner",
                    "enabled",
                    "severity",
                    "notification_channels",
                    "alert_strategy",
                ]
            ),
            safe=",_",
        )
        write_payload = deepcopy(expected)
        existing_conditions = existing_policy.get("conditions") or []
        if len(existing_conditions) == 1 and existing_conditions[0].get("name"):
            write_payload["conditions"][0]["name"] = existing_conditions[0]["name"]
        _response, reconciled = _api_request(
            session,
            "PATCH",
            f"{MONITORING_ROOT}/{name}?updateMask={update_mask}",
            headers,
            json_data={"name": name, **write_payload},
        )
    else:
        _response, reconciled = _api_request(
            session,
            "POST",
            base,
            headers,
            json_data=expected,
            allow_codes=[201],
        )
    if not _policy_matches(reconciled, expected):
        raise MonitoringReconciliationError(
            "The App Engine memory policy did not match after reconciliation."
        )
    return reconciled


# @testable true
# @tests tests_tooling/test_001i_setup_monitoring.py::test_automatic_reconciliation_failure_is_nonfatal_and_prints_retry_command
# @matrix monitoring setup : failure-isolation post-deploy retry-command
def reconcile_memory_alert_after_deploy():
    """Run automatic reconciliation without invalidating a completed deploy."""
    from config import SETTINGS
    from installer import FORMATTER

    project = str(SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    owner = str(SETTINGS.APP.get("ADMIN_EMAIL") or "").strip()
    if not project or not owner:
        return False
    try:
        reconcile_memory_alert(settings=SETTINGS.APP, project=project)
        return True
    except Exception as error:
        f = FORMATTER.initialize()
        print(
            f.warning(
                "WARNING: deployment succeeded, but App Engine memory "
                f"monitoring could not be reconciled ({type(error).__name__})."
            )
        )
        print(f.warning(f"Retry with: {setup_command('monitoring')}"))
        return False


# @testable true
# @tests tests_tooling/test_001i_setup_monitoring.py::test_inspection_reports_missing_and_drifted_managed_policy
# @matrix doctor monitoring setup : drift read-only
def inspect_memory_alert(settings, project, *, session=None):
    """Return a doctor-compatible read-only policy observation."""
    try:
        session, headers = _provider_context(project, session=session)
        channels, managed_policies = _resources(session, project, headers)
        if len(managed_policies) != 1:
            return {
                "state": "ABSENT",
                "details": {"managed_policy_count": len(managed_policies)},
                "error": None,
            }
        selected = _choose_owner_channel(
            channels, str(settings.get("ADMIN_EMAIL") or "").strip()
        )
        if selected is None:
            return {
                "state": "ABSENT",
                "details": {"owner_channel": "missing"},
                "error": None,
            }
        policy = managed_policies[0]
        expected = memory_policy_payload(
            settings,
            project,
            _desired_channels(policy, channels, selected),
        )
        matches = _policy_matches(policy, expected)
        return {
            "state": "AVAILABLE" if matches else "ABSENT",
            "details": {"policy": "current" if matches else "drifted"},
            "error": None,
        }
    except Exception as error:
        return {
            "state": "UNAVAILABLE",
            "details": None,
            "error": type(error).__name__,
        }
