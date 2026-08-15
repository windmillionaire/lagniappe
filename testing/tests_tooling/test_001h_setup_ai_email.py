"""Focused setup/config contracts for production Resend AI email."""

import copy

import pytest

from config.ai_email import (
    AI_EMAIL_LIMITS,
    AIEmailConfigurationError,
    ai_email_public_config,
    normalize_ai_email_config,
)


pytestmark = pytest.mark.tooling


def _valid_config():
    return {
        "version": 1,
        "provider": "resend",
        "enabled": False,
        "domain": "INBOUND.Exämple.COM.",
        "aliases": {"ask": "ASK", "create": "create", "organize": "organize"},
        "resend": {
            "domainId": "domain-1",
            "webhookId": "webhook-1",
            "webhookSecret": "whsec_dGVzdC1zZWNyZXQ=",
            "inboundApiKey": "re_full",
            "sendingApiKey": "re_send",
            "senderEmail": "noreply@example.com",
            "senderName": "Lagniappe",
        },
        "limits": dict(AI_EMAIL_LIMITS),
    }


# @features ai-email config
# @dimensions config normalization domain email-address idna aliases public-projection secrets limits
def test_ai_email_config_normalizes_domains_aliases_and_public_projection():
    normalized = normalize_ai_email_config(_valid_config())

    assert normalized["domain"] == "inbound.xn--exmple-cua.com"
    assert normalized["aliases"]["ask"] == "ask"
    assert ai_email_public_config(normalized) == {
        "enabled": False,
        "addresses": {},
    }

    enabled = copy.deepcopy(normalized)
    enabled["enabled"] = True
    assert ai_email_public_config(enabled) == {
        "enabled": True,
        "addresses": {
            "ask": "ask@inbound.xn--exmple-cua.com",
            "create": "create@inbound.xn--exmple-cua.com",
            "organize": "organize@inbound.xn--exmple-cua.com",
        },
    }


# @features ai-email config
# @dimensions config validation normalization domain email-address idna limits aliases secrets public-projection
def test_ai_email_config_rejects_security_weakening_values():
    mutations = (
        lambda value: value.update(unknown=True),
        lambda value: value["limits"].update(maxBodyBytes=999999),
        lambda value: value["aliases"].update(create="ASK"),
        lambda value: value["resend"].update(sendingApiKey="re_full"),
        lambda value: value.update(enabled="yes"),
    )
    for mutate in mutations:
        candidate = _valid_config()
        mutate(candidate)
        with pytest.raises(AIEmailConfigurationError):
            normalize_ai_email_config(candidate)


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self.payload


# @features ai-email setup
# @dimensions setup resend-api authorization
def test_resend_setup_client_uses_full_key_for_provider_administration():
    from installer.ai_email import ResendSetupClient

    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(
            {"data": []}
        )

    client = ResendSetupClient(
        "re_full", request=request, retry_sleep=lambda _delay: None
    )
    assert client.list_domains() == []

    assert calls[0][2]["headers"]["Authorization"] == "Bearer re_full"
    assert calls[0][2]["timeout"] == 15


# @features ai-email setup
# @dimensions setup resend resend-domain domain idempotence receiving-only
def test_reconcile_receiving_domain_creates_or_reuses_one_exact_domain(monkeypatch):
    from installer import ai_email

    monkeypatch.setattr(ai_email, "record_mutation", lambda *args, **kwargs: None)

    class Client:
        def __init__(self, domains):
            self.domains = domains
            self.created = []
            self.enabled = []

        def list_domains(self):
            return self.domains

        def create_receiving_domain(self, name):
            self.created.append(name)
            return {"id": "domain-new"}

        def enable_domain_receiving(self, domain_id):
            self.enabled.append(domain_id)

        def get_domain(self, domain_id):
            return {
                "id": domain_id,
                "name": "inbound.example.com",
                "status": "verified",
                "capabilities": {"receiving": "enabled"},
            }

    created = Client([])
    assert (
        ai_email.reconcile_receiving_domain(created, "inbound.example.com")["id"]
        == "domain-new"
    )
    assert created.created == ["inbound.example.com"]

    reused = Client(
        [
            {
                "id": "domain-old",
                "name": "INBOUND.EXAMPLE.COM",
                "capabilities": {"receiving": "disabled"},
            }
        ]
    )
    assert (
        ai_email.reconcile_receiving_domain(reused, "inbound.example.com")["id"]
        == "domain-old"
    )
    assert reused.created == []
    assert reused.enabled == ["domain-old"]


# @features ai-email setup
# @dimensions setup resend resend-webhook webhook idempotence disabled-first secret-retrieval
def test_reconcile_webhook_reuses_endpoint_and_disables_before_deploy(monkeypatch):
    from installer import ai_email

    monkeypatch.setattr(ai_email, "record_mutation", lambda *args, **kwargs: None)
    events = []

    class Client:
        def list_webhooks(self):
            return [
                {
                    "id": "webhook-1",
                    "endpoint": "https://app.example.com/webhooks/resend/ai-email",
                    "status": "enabled",
                }
            ]

        def update_webhook(self, webhook_id, *, endpoint, status):
            events.append(("update", webhook_id, endpoint, status))

        def get_webhook(self, webhook_id):
            assert events[-1][-1] == "disabled"
            return {
                "id": webhook_id,
                "endpoint": "https://app.example.com/webhooks/resend/ai-email",
                "events": ["email.received"],
                "status": "disabled",
                "signing_secret": "whsec_dGVzdA==",
            }

    result = ai_email.reconcile_webhook(
        Client(), "https://app.example.com/webhooks/resend/ai-email"
    )

    assert result["id"] == "webhook-1"
    assert events == [
        (
            "update",
            "webhook-1",
            "https://app.example.com/webhooks/resend/ai-email",
            "disabled",
        )
    ]


# @features ai-email setup resend
# @dimensions setup resend browser instructions authorization secrets
def test_resend_setup_guides_full_receiving_key_creation(monkeypatch, capsys):
    from installer import ai_email

    opened = []
    monkeypatch.setattr(ai_email.webbrowser, "open_new_tab", opened.append)

    ai_email.guide_resend_receiving_key()

    output = capsys.readouterr().out
    assert "Lagniappe AI Email Receiving" in output
    assert "Permission: Full access" in output
    assert "Do not use this Full access key for sending" in output
    assert opened == [ai_email.RESEND_API_KEYS_URL]


# @features ai-email setup resend
# @dimensions setup resend instructions authorization secrets reuse authentication-email
def test_resend_setup_explains_when_authentication_email_can_be_reused(
    monkeypatch,
    capsys,
):
    from installer import ai_email

    opened = []
    monkeypatch.setattr(ai_email.webbrowser, "open_new_tab", opened.append)

    ai_email.guide_resend_sending_identity(
        "example.com",
        reusable_sender="noreply@example.com",
    )

    output = capsys.readouterr().out
    assert (
        "Authentication email already established the verified Resend sender" in output
    )
    assert "noreply@example.com" in output
    assert "reuse that sender and key" in output
    assert "sending-domain DNS setup" in output
    assert "create another Sending key" in output
    assert opened == []


# @features ai-email setup
# @dimensions setup receiving-domain cloudflare-dns browser instructions manual-dns
def test_receiving_dns_guidance_prefers_cloudflare_and_keeps_manual_fallback(
    monkeypatch,
    capsys,
):
    import builtins

    from installer import ai_email

    domain = {
        "name": "inbound.app.example.com",
        "records": [
            {
                "type": "MX",
                "name": "inbound",
                "value": "inbound-smtp.resend.com",
                "priority": 10,
            }
        ],
    }
    opened = []
    monkeypatch.setattr(ai_email.webbrowser, "open_new_tab", opened.append)
    cloudflare_responses = iter(["", ""])
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(cloudflare_responses),
    )

    ai_email.guide_resend_receiving_dns(domain, cloudflare_default=True)

    assisted_output = capsys.readouterr().out
    assert "Sign in to Cloudflare" in assisted_output
    assert "inbound-smtp.resend.com" not in assisted_output
    assert opened == [ai_email.RESEND_DOMAINS_URL]

    manual_responses = iter(["n", ""])
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(manual_responses),
    )
    ai_email.guide_resend_receiving_dns(domain, cloudflare_default=True)

    manual_output = capsys.readouterr().out
    assert "inbound-smtp.resend.com" in manual_output
    assert "priority=10" in manual_output


# @features ai-email setup
# @dimensions setup prerequisites custom-domain supporting-services
def test_ai_email_setup_requires_custom_domain_and_supporting_services():
    from installer.ai_email import _prerequisites
    from installer.errors import ProviderInvalidInput

    with pytest.raises(ProviderInvalidInput, match="custom application domain"):
        _prerequisites({})
    with pytest.raises(ProviderInvalidInput, match="Resend-backed"):
        _prerequisites(
            {
                "CUSTOM_DOMAIN": "app.example.com",
                "AUTH_EMAIL_CONFIG": {"provider": "smtp", "service": "Gmail"},
                "AI_MODEL": "gemini-test",
                "RESOURCE_REGION": "us-central1",
                "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@example.test",
            }
        )

    assert (
        _prerequisites(
            {
                "CUSTOM_DOMAIN": "App.Example.com",
                "AUTH_EMAIL_CONFIG": {
                    "provider": "smtp",
                    "service": "Resend",
                    "password": "re_send",
                    "senderEmail": "noreply@example.com",
                    "senderName": "Lagniappe",
                },
                "AI_MODEL": "gemini-test",
                "RESOURCE_REGION": "us-central1",
                "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@example.test",
            }
        )
        == "app.example.com"
    )


# @features ai-email
# @dimensions setup cli prerequisites deploy manual-smoke-test disabled-first
def test_ai_email_setup_saves_deploys_then_enables_webhook(
    monkeypatch,
    capsys,
):
    import builtins
    import types

    import config
    from installer import ai_email
    from installer import verify

    events = []
    settings = types.SimpleNamespace(
        APP={
            "APP_NAME": "Lagniappe",
            "ADMIN_EMAIL": "owner@example.com",
            "AUTH_EMAIL_CONFIG": {
                "provider": "smtp",
                "service": "Resend",
                "password": "re_send",
                "senderEmail": "noreply@example.com",
                "senderName": "Lagniappe",
            },
            "AI_MODEL": "gemini-test",
            "CUSTOM_DOMAIN": "app.example.com",
            "RESOURCE_REGION": "us-central1",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@example.test",
        },
        save=lambda: events.append("save"),
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(
        verify,
        "prepare_existing_installation",
        lambda: events.append("prepare"),
    )

    class Client:
        def __init__(self, api_key):
            assert api_key == "re_full"

        def update_webhook(self, webhook_id, *, endpoint, status):
            assert webhook_id == "webhook-1"
            assert endpoint.endswith("/webhooks/resend/ai-email")
            assert status == "enabled"
            events.append("enable-webhook")

        def get_webhook(self, webhook_id):
            return {"id": webhook_id, "status": "enabled"}

    monkeypatch.setattr(ai_email, "ResendSetupClient", Client)
    monkeypatch.setattr(
        ai_email,
        "reconcile_receiving_domain",
        lambda client, domain: {
            "id": "domain-1",
            "name": domain,
            "status": "verified",
            "capabilities": {"receiving": "enabled"},
        },
    )
    monkeypatch.setattr(
        ai_email,
        "reconcile_webhook",
        lambda client, endpoint: {
            "id": "webhook-1",
            "endpoint": endpoint,
            "events": ["email.received"],
            "status": "disabled",
            "signing_secret": "whsec_dGVzdC1zZWNyZXQ=",
        },
    )
    monkeypatch.setattr(
        "installer.utils.deploy_to_app_engine",
        lambda: events.append("deploy"),
    )
    monkeypatch.setattr(ai_email.webbrowser, "open_new_tab", lambda _url: True)
    responses = iter(
        [
            "",  # suggested inbound domain
            "y",  # dedicated domain with no unrelated MX records
            "re_full",
            "",  # deploy
        ]
    )
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(responses))

    assert ai_email.configure_ai_email() == 0

    assert events == [
        "prepare",
        "save",
        "deploy",
        "enable-webhook",
    ]
    saved = settings.APP["AI_EMAIL_CONFIG"]
    assert saved["enabled"] is True
    assert saved["resend"]["sendingApiKey"] == "re_send"
    assert saved["resend"]["senderEmail"] == "noreply@example.com"
    output = capsys.readouterr().out
    assert "Next step: deploy and activate AI email submissions." in output
    assert "no synthetic email or health probe is run" in output
    assert "Send a normal email from a registered user's exact email address" in output


# @features ai-email setup
# @dimensions setup disable disabled-first provider-state deploy secrets
def test_ai_email_disable_turns_off_provider_before_saving_and_deploying(
    monkeypatch,
):
    import builtins
    import types

    import config
    from installer import ai_email

    events = []
    settings = types.SimpleNamespace(
        APP={
            "CUSTOM_DOMAIN": "app.example.com",
            "AI_EMAIL_CONFIG": normalize_ai_email_config(_valid_config()),
        },
        save=lambda: events.append("save"),
    )
    monkeypatch.setattr(config, "SETTINGS", settings)

    class Client:
        def __init__(self, key):
            assert key == "re_full"

        def update_webhook(self, webhook_id, *, endpoint, status):
            assert webhook_id == "webhook-1"
            assert endpoint.endswith("/webhooks/resend/ai-email")
            assert status == "disabled"
            events.append("provider-disable")

        def get_webhook(self, webhook_id):
            events.append("provider-check")
            return {"id": webhook_id, "status": "disabled"}

    monkeypatch.setattr(ai_email, "ResendSetupClient", Client)
    monkeypatch.setattr(
        "installer.utils.deploy_to_app_engine",
        lambda: events.append("deploy"),
    )
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "")

    existing = settings.APP["AI_EMAIL_CONFIG"]
    assert ai_email._disable(existing) == 0

    assert events == ["provider-disable", "provider-check", "save", "deploy"]
    disabled = settings.APP["AI_EMAIL_CONFIG"]
    assert disabled["enabled"] is False
    assert disabled["resend"]["webhookSecret"] == existing["resend"]["webhookSecret"]
