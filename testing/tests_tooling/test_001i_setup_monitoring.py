"""Focused contracts for installer-managed App Engine memory monitoring."""

import json
import types

import pytest

from installer import monitoring


pytestmark = pytest.mark.tooling


SETTINGS = {
    "GOOGLE_CLOUD_PROJECT": "demo-project",
    "ADMIN_EMAIL": "owner@example.test",
    "DEPLOY_INSTANCE_CLASS": "B2",
    "DEPLOY_WORKER_COUNT": "3",
}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class MonitoringSession:
    def __init__(self, *, channels=(), policies=()):
        self.channels = [dict(channel) for channel in channels]
        self.policies = [dict(policy) for policy in policies]
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "/notificationChannels" in url:
            return FakeResponse(200, {"notificationChannels": self.channels})
        if "/alertPolicies" in url:
            return FakeResponse(200, {"alertPolicies": self.policies})
        raise AssertionError(f"Unexpected GET: {url}")

    def post(self, url, **kwargs):
        payload = dict(kwargs["json"])
        self.calls.append(("POST", url, payload))
        if url.endswith("/notificationChannels"):
            payload["name"] = "projects/demo-project/notificationChannels/managed-owner"
            self.channels.append(payload)
            return FakeResponse(201, payload)
        if url.endswith("/alertPolicies"):
            payload["name"] = "projects/demo-project/alertPolicies/memory"
            payload["conditions"][0]["name"] = (
                "projects/demo-project/alertPolicies/memory/conditions/pressure"
            )
            self.policies.append(payload)
            return FakeResponse(201, payload)
        raise AssertionError(f"Unexpected POST: {url}")

    def patch(self, url, **kwargs):
        payload = dict(kwargs["json"])
        self.calls.append(("PATCH", url, payload))
        name = payload["name"]
        payload["conditions"][0].setdefault(
            "name",
            f"{name}/conditions/pressure",
        )
        for index, policy in enumerate(self.policies):
            if policy.get("name") == name:
                self.policies[index] = payload
                return FakeResponse(200, payload)
        raise AssertionError(f"Unexpected PATCH: {url}")


def _channel(name, email, *, managed=False, enabled=True):
    channel = {
        "name": name,
        "type": "email",
        "enabled": enabled,
        "labels": {"email_address": email},
    }
    if managed:
        channel["userLabels"] = dict(monitoring.POLICY_LABELS)
    return channel


def _policy(name="projects/demo-project/alertPolicies/memory", **values):
    return {
        "name": name,
        "userLabels": dict(monitoring.POLICY_LABELS),
        **values,
    }


# @matrix monitoring setup : instance-class threshold
@pytest.mark.parametrize(
    ("instance_class", "envelope_mib"),
    sorted(monitoring.INSTANCE_CLASS_MEMORY_MIB.items()),
)
def test_memory_threshold_is_derived_from_each_supported_instance_class(
    instance_class,
    envelope_mib,
):
    threshold = monitoring.memory_threshold({"DEPLOY_INSTANCE_CLASS": instance_class})
    assert threshold == {
        "instance_class": instance_class,
        "envelope_mib": envelope_mib,
        "threshold_mib": envelope_mib * 0.8,
        "threshold_bytes": envelope_mib * 1024 * 1024 * 0.8,
    }
    if instance_class in {"F2", "B2"}:
        assert threshold["envelope_mib"] == 768


# @matrix monitoring setup : alert-policy documentation memory-pressure payload
def test_memory_policy_payload_uses_per_instance_query_and_actionable_documentation():
    channels = ["projects/demo-project/notificationChannels/owner"]
    payload = monitoring.memory_policy_payload(SETTINGS, "demo-project", channels)
    condition = payload["conditions"][0]["conditionMonitoringQueryLanguage"]
    query = condition["query"]

    assert payload["userLabels"] == {
        "managed_by": "lagniappe",
        "purpose": "app_engine_memory",
    }
    assert payload["severity"] == "WARNING"
    assert payload["notificationChannels"] == channels
    assert condition["duration"] == "120s"
    assert "appengine.googleapis.com/system/memory/usage" in query
    assert "appengine.googleapis.com/system/instance_count" in query
    assert query.count("fetch gae_app") == 1
    assert "| { metric 'appengine.googleapis.com/system/memory/usage'" in query
    assert "| join" in query
    assert "resource.module_id == 'default'" in query
    assert "resource.version_id, resource.zone" in query
    assert "val(0) / val(1)" in query
    assert "sum(value.instance_count)" in query
    assert "condition val() > 644245094.4" in query

    documentation = payload["documentation"]["content"]
    for expected in (
        "B2",
        "three workers",
        "80%",
        "768 MiB",
        "614.4 MiB",
        "Remediation",
        "console.cloud.google.com/monitoring/metrics-explorer",
    ):
        assert expected in documentation


# @matrix monitoring setup : idempotence notification-channel operator-preservation owner-reconciliation
def test_reconcile_reuses_owner_channel_preserves_operator_channels_and_is_idempotent(
    monkeypatch,
):
    owner = _channel(
        "projects/demo-project/notificationChannels/operator-owner",
        "owner@example.test",
    )
    pager = _channel(
        "projects/demo-project/notificationChannels/operator-pager",
        "pager@example.test",
    )
    obsolete = _channel(
        "projects/demo-project/notificationChannels/obsolete-owner",
        "old-owner@example.test",
        managed=True,
    )
    session = MonitoringSession(
        channels=[owner, pager, obsolete],
        policies=[
            _policy(
                displayName="drifted",
                notificationChannels=[pager["name"], obsolete["name"]],
            )
        ],
    )
    enabled = []
    monkeypatch.setattr(
        monitoring,
        "_provider_context",
        lambda project, session=None: (session or globals()["session"], {"auth": "x"}),
    )
    monkeypatch.setattr(
        "installer.utils.run_gcloud_command",
        lambda command, **kwargs: enabled.append(command),
    )

    reconciled = monitoring.reconcile_memory_alert(
        settings=SETTINGS,
        project="demo-project",
        session=session,
    )
    assert reconciled["notificationChannels"] == sorted([owner["name"], pager["name"]])
    assert obsolete["name"] not in reconciled["notificationChannels"]
    assert [call[0] for call in session.calls].count("PATCH") == 1
    assert [call[0] for call in session.calls].count("POST") == 0

    monitoring.reconcile_memory_alert(
        settings=SETTINGS,
        project="demo-project",
        session=session,
    )
    assert [call[0] for call in session.calls].count("PATCH") == 1
    assert enabled == [
        ["services", "enable", "monitoring.googleapis.com", "--project=demo-project"],
        ["services", "enable", "monitoring.googleapis.com", "--project=demo-project"],
    ]


# @matrix monitoring setup : notification-channel operator-preservation owner-reconciliation
def test_reconcile_creates_owner_channel_and_detaches_obsolete_managed_channels(
    monkeypatch,
):
    pager = _channel(
        "projects/demo-project/notificationChannels/operator-pager",
        "pager@example.test",
    )
    obsolete = _channel(
        "projects/demo-project/notificationChannels/obsolete-owner",
        "old-owner@example.test",
        managed=True,
    )
    session = MonitoringSession(
        channels=[pager, obsolete],
        policies=[_policy(notificationChannels=[pager["name"], obsolete["name"]])],
    )
    monkeypatch.setattr(
        monitoring,
        "_provider_context",
        lambda project, session=None: (session or globals()["session"], {"auth": "x"}),
    )
    monkeypatch.setattr(
        "installer.utils.run_gcloud_command", lambda *args, **kwargs: None
    )

    reconciled = monitoring.reconcile_memory_alert(
        settings=SETTINGS,
        project="demo-project",
        session=session,
    )
    managed_owner = "projects/demo-project/notificationChannels/managed-owner"
    assert reconciled["notificationChannels"] == sorted([pager["name"], managed_owner])
    assert obsolete["name"] not in reconciled["notificationChannels"]
    assert obsolete in session.channels
    assert [call[0] for call in session.calls].count("POST") == 1
    assert all(call[0] != "DELETE" for call in session.calls)


# @source installer/monitoring.py::reconcile_memory_alert
# @matrix monitoring setup : alert-policy creation idempotence
def test_reconcile_creates_exactly_one_policy_and_tolerates_provider_condition_names(
    monkeypatch,
):
    owner = _channel(
        "projects/demo-project/notificationChannels/operator-owner",
        "owner@example.test",
    )
    session = MonitoringSession(channels=[owner], policies=[])
    monkeypatch.setattr(
        monitoring,
        "_provider_context",
        lambda project, session=None: (session or globals()["session"], {"auth": "x"}),
    )
    monkeypatch.setattr(
        "installer.utils.run_gcloud_command", lambda *args, **kwargs: None
    )

    policy = monitoring.reconcile_memory_alert(
        settings=SETTINGS,
        project="demo-project",
        session=session,
    )
    assert policy["conditions"][0]["name"].endswith("/conditions/pressure")
    assert len(session.policies) == 1
    assert [call[0] for call in session.calls].count("POST") == 1

    monitoring.reconcile_memory_alert(
        settings=SETTINGS,
        project="demo-project",
        session=session,
    )
    assert [call[0] for call in session.calls].count("POST") == 1


# @matrix monitoring setup : failure-isolation post-deploy retry-command
def test_automatic_reconciliation_failure_is_nonfatal_and_prints_retry_command(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        monitoring,
        "reconcile_memory_alert",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    monkeypatch.setattr(
        "config.SETTINGS",
        types.SimpleNamespace(APP=dict(SETTINGS)),
    )
    formatter = types.SimpleNamespace(warning=lambda message: message)
    monkeypatch.setattr(
        "installer.FORMATTER",
        types.SimpleNamespace(initialize=lambda: formatter),
    )

    assert monitoring.reconcile_memory_alert_after_deploy() is False
    output = capsys.readouterr().out
    assert "deployment succeeded" in output
    assert "monitoring could not be reconciled" in output
    assert "Retry with: ./setup.sh monitoring" in output


# @matrix doctor monitoring setup : drift read-only
def test_inspection_reports_missing_and_drifted_managed_policy(monkeypatch):
    owner = _channel(
        "projects/demo-project/notificationChannels/operator-owner",
        "owner@example.test",
    )
    session = MonitoringSession(channels=[owner], policies=[])
    monkeypatch.setattr(
        monitoring,
        "_provider_context",
        lambda project, session=None: (session or globals()["session"], {"auth": "x"}),
    )
    assert (
        monitoring.inspect_memory_alert(SETTINGS, "demo-project", session=session)[
            "state"
        ]
        == "ABSENT"
    )

    session.policies = [_policy(displayName="drifted", notificationChannels=[])]
    drifted = monitoring.inspect_memory_alert(SETTINGS, "demo-project", session=session)
    assert drifted == {
        "state": "ABSENT",
        "details": {"policy": "drifted"},
        "error": None,
    }

    expected = monitoring.memory_policy_payload(
        SETTINGS,
        "demo-project",
        [owner["name"]],
    )
    session.policies = [_policy(**expected)]
    assert monitoring.inspect_memory_alert(
        SETTINGS, "demo-project", session=session
    ) == {
        "state": "AVAILABLE",
        "details": {"policy": "current"},
        "error": None,
    }
