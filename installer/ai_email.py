"""Provision the Resend transport used by production AI email submissions."""

import time
import webbrowser

import requests

from config.ai_email import (
    AI_EMAIL_LIMITS,
    normalize_ai_email_config,
    normalize_email_address,
    normalize_email_domain,
)
from installer import FORMATTER, wrap_text
from installer.errors import (
    ProviderError,
    ProviderInvalidInput,
    SetupCancelled,
    classify_provider_error,
    retry_provider_call,
)
from installer.state import record_mutation
from runner.context import setup_command


RESEND_API_ROOT = "https://api.resend.com"
RESEND_API_KEYS_URL = "https://resend.com/api-keys"
RESEND_DOMAINS_URL = "https://resend.com/domains"
RESEND_API_TIMEOUT = 15
WEBHOOK_PATH = "/webhooks/resend/ai-email"
WEBHOOK_EVENTS = ["email.received"]


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_resend_setup_client_uses_full_key_for_provider_administration
# @features ai-email
# @dimensions setup resend-api authorization
class ResendSetupClient:
    """Bounded Resend administration adapter for the focused installer."""

    def __init__(self, api_key, *, request=None, retry_sleep=None):
        self.api_key = str(api_key or "").strip()
        self.request = request or requests.request
        self.retry_sleep = retry_sleep

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason shared HTTP implementation exercised through the public adapter
    def _request(self, method, path, *, json_data=None, api_key=None, headers=None):
        request_headers = {
            "Authorization": f"Bearer {api_key or self.api_key}",
            "Content-Type": "application/json",
        }
        request_headers.update(headers or {})

        # @testable false
        # @covered-by installer/ai_email.py::ResendSetupClient._request
        # @reason retry closure exercised through the owning request adapter
        def operation():
            try:
                response = self.request(
                    method,
                    f"{RESEND_API_ROOT}{path}",
                    headers=request_headers,
                    json=json_data,
                    timeout=RESEND_API_TIMEOUT,
                )
            except (requests.ConnectionError, requests.Timeout) as error:
                raise classify_provider_error(error) from error
            if not response.ok:
                raise classify_provider_error(
                    RuntimeError("Resend API request failed."),
                    message=f"Resend {method} {path} returned HTTP {response.status_code}.",
                    status_code=response.status_code,
                )
            try:
                payload = response.json()
            except ValueError as error:
                raise ProviderError("Resend returned invalid JSON.") from error
            if not isinstance(payload, dict):
                raise ProviderError("Resend returned an invalid response object.")
            return payload

        retry_options = {
            "description": f"Resend {method} {path}",
            "attempts": 3,
            "delays": (1, 2),
        }
        if self.retry_sleep is not None:
            retry_options["sleep"] = self.retry_sleep
        return retry_provider_call(operation, **retry_options)

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through the public setup client
    def list_domains(self):
        payload = self._request("GET", "/domains")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError("Resend returned an invalid domain list.")
        return [item for item in data if isinstance(item, dict)]

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through domain reconciliation
    def create_receiving_domain(self, domain):
        return self._request(
            "POST",
            "/domains",
            json_data={
                "name": domain,
                "capabilities": {"sending": "disabled", "receiving": "enabled"},
            },
        )

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through domain reconciliation
    def get_domain(self, domain_id):
        return self._request("GET", f"/domains/{domain_id}")

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through domain reconciliation
    def enable_domain_receiving(self, domain_id):
        return self._request(
            "PATCH",
            f"/domains/{domain_id}",
            json_data={"capabilities": {"receiving": "enabled"}},
        )

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through the setup workflow
    def verify_domain(self, domain_id):
        return self._request("POST", f"/domains/{domain_id}/verify")

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through webhook reconciliation
    def list_webhooks(self):
        payload = self._request("GET", "/webhooks")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError("Resend returned an invalid webhook list.")
        return [item for item in data if isinstance(item, dict)]

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through webhook reconciliation
    def get_webhook(self, webhook_id):
        return self._request("GET", f"/webhooks/{webhook_id}")

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through webhook reconciliation
    def create_webhook(self, endpoint):
        return self._request(
            "POST",
            "/webhooks",
            json_data={"endpoint": endpoint, "events": WEBHOOK_EVENTS},
        )

    # @testable false
    # @covered-by installer/ai_email.py::ResendSetupClient
    # @reason endpoint adapter exercised through webhook reconciliation
    def update_webhook(self, webhook_id, *, endpoint, status):
        return self._request(
            "PATCH",
            f"/webhooks/{webhook_id}",
            json_data={
                "endpoint": endpoint,
                "events": WEBHOOK_EVENTS,
                "status": status,
            },
        )

# @testable false
# @covered-by installer/ai_email.py::configure_ai_email
# @reason interactive prompt behavior is owned by the focused setup workflow
def _prompt(label, default=None):
    if default not in (None, ""):
        suffix = f" [{default}] (Enter to keep; x to exit): "
    else:
        suffix = " (x to exit): "
    value = input(f"{label}{suffix}").strip()
    if value.casefold() == "x":
        raise SetupCancelled("AI email setup cancelled.")
    return value or str(default or "").strip()


# @testable false
# @covered-by installer/ai_email.py::configure_ai_email
# @reason secret-preserving prompt behavior is owned by the setup workflow
def _prompt_secret(label, existing=None):
    suffix = (
        " (Enter to keep the saved value; x to exit): "
        if existing
        else " (x to exit): "
    )
    value = input(f"{label}{suffix}").strip()
    if value.casefold() == "x":
        raise SetupCancelled("AI email setup cancelled.")
    return value or str(existing or "")


# @testable false
# @covered-by installer/ai_email.py::guide_resend_receiving_key
# @covered-by installer/ai_email.py::guide_resend_sending_identity
# @reason browser launch behavior is exercised through the public instruction helpers
def _open_resend_page(label, url):
    print(f"Opening {label}:\n  {url}")
    try:
        webbrowser.open_new_tab(url)
    except webbrowser.Error:
        pass


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_resend_setup_guides_full_receiving_key_creation
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_rerun_reuses_saved_inbound_api_key_without_prompt
# @features ai-email
# @dimensions setup resend browser instructions authorization secrets
def guide_resend_receiving_key(*, existing=False):
    """Explain the exact dashboard steps for the receiving administration key."""
    print("\nConfigure the Resend receiving administration key:")
    if existing:
        print(
            wrap_text(
                "A Full access receiving key is already saved. Setup will reuse "
                "it for provider reconciliation without prompting for it again."
            )
        )
        return
    print(wrap_text("1. Sign in to Resend and open API Keys."))
    print(wrap_text("2. Click 'Create API Key'."))
    print("   - Name: Lagniappe AI Email Receiving")
    print("   - Permission: Full access")
    print(
        wrap_text(
            "3. Click 'Create', then copy the key immediately. Resend displays "
            "the key value only once. Do not use this Full access key for sending."
        )
    )
    print(
        wrap_text(
            "4. Return to setup and paste the key. Setup will verify Full access "
            "by listing and reconciling Resend domains before it saves anything."
        )
    )
    if not existing:
        _open_resend_page("Resend API Keys", RESEND_API_KEYS_URL)


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_resend_setup_explains_when_authentication_email_can_be_reused
# @features ai-email
# @dimensions setup resend instructions sending-domain authorization secrets reuse
def guide_resend_sending_identity(sending_domain, *, reusable_sender=None):
    """Confirm reuse of the Resend identity established by authentication email."""
    print("\nConfigure the Resend feedback-sending identity:")
    if not reusable_sender:
        raise ProviderInvalidInput(
            "AI email requires Resend-backed authentication email. "
            "Rerun ./setup.sh email and choose Resend first."
        )
    print(
        wrap_text(
            f"Authentication email already established the verified Resend sender "
            f"{reusable_sender} on {sending_domain} and its Sending-access key. "
            "AI email will reuse that sender and key; it will not repeat the "
            "sending-domain DNS setup or create another Sending key. The new Full "
            "access receiving key must remain different."
        )
    )


# @testable false
# @covered-by installer/ai_email.py::reconcile_receiving_domain
# @reason provider identifier guard is exercised through domain reconciliation
def _domain_id(domain):
    value = str(domain.get("id") or "").strip()
    if not value:
        raise ProviderError("Resend did not return a domain ID.")
    return value


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_reconcile_receiving_domain_creates_or_reuses_one_exact_domain
# @features ai-email
# @dimensions setup resend domain idempotence receiving-only
def reconcile_receiving_domain(client, domain):
    """Find/create one exact receiving domain without touching unrelated domains."""
    matches = [
        item
        for item in client.list_domains()
        if str(item.get("name") or "").rstrip(".").casefold() == domain.casefold()
    ]
    if len(matches) > 1:
        raise ProviderError(f"Resend returned duplicate domain resources for {domain}.")
    if matches:
        domain_id = _domain_id(matches[0])
        capabilities = matches[0].get("capabilities") or {}
        if capabilities.get("receiving") != "enabled":
            client.enable_domain_receiving(domain_id)
            record_mutation(
                "ai-email-domain",
                action="updated",
                resource="Resend receiving domain",
                identifier=domain_id,
            )
    else:
        created = client.create_receiving_domain(domain)
        domain_id = _domain_id(created)
        record_mutation(
            "ai-email-domain",
            action="created",
            resource="Resend receiving domain",
            identifier=domain_id,
        )
    current = client.get_domain(domain_id)
    if str(current.get("name") or "").rstrip(".").casefold() != domain.casefold():
        raise ProviderError("Resend returned a different domain than requested.")
    capabilities = current.get("capabilities") or {}
    if capabilities.get("receiving") != "enabled":
        raise ProviderError("Resend receiving capability is not enabled.")
    return current


# @testable false
# @covered-by installer/ai_email.py::guide_resend_receiving_dns
# @reason operator-only record rendering is exercised through DNS guidance
def _print_domain_records(domain):
    records = domain.get("records")
    if not isinstance(records, list) or not records:
        raise ProviderError(
            "Resend did not return DNS records for the receiving domain."
        )
    print("\nAdd the exact Resend records below at your DNS provider:")
    for record in records:
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("type") or "").upper()
        name = str(record.get("name") or "").strip()
        value = str(record.get("value") or "").strip()
        priority = record.get("priority")
        priority_text = f" priority={priority}" if priority is not None else ""
        print(f"  {record_type:<6} {name:<35} {value}{priority_text}")


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_receiving_dns_guidance_prefers_cloudflare_and_keeps_manual_fallback
# @features ai-email
# @dimensions setup receiving-domain cloudflare-dns browser instructions manual-dns
def guide_resend_receiving_dns(domain, *, cloudflare_default=False):
    """Guide assisted or manual DNS without dumping records unnecessarily."""
    domain_name = str(domain.get("name") or "").strip()
    if not domain_name:
        raise ProviderError("Resend did not return the receiving domain name.")
    suffix = "[Y/n] (x to exit)" if cloudflare_default else "[y/N] (x to exit)"
    choice = input(f"Is DNS for {domain_name} hosted by Cloudflare? {suffix}: ")
    choice = choice.strip().casefold()
    if choice == "x":
        raise SetupCancelled(
            "The Resend domain was retained; rerun setup when DNS is ready."
        )
    use_cloudflare = choice == "y" or (not choice and cloudflare_default)
    if use_cloudflare:
        print("\nConfigure the new receiving subdomain through Resend and Cloudflare:")
        print(
            wrap_text(
                f"1. Open Resend Domains and select {domain_name}. Setup has "
                "already created it with receiving enabled."
            )
        )
        print(
            wrap_text(
                "2. Use Resend's 'Sign in to Cloudflare' or automatic DNS setup "
                "when it is offered, select the correct Cloudflare zone, and "
                "authorize the receiving record."
            )
        )
        print(
            wrap_text(
                "3. Return here after Resend/Cloudflare reports that the DNS "
                "change was submitted. If the automatic option is unavailable, "
                "type M to switch to the exact manual records."
            )
        )
        _open_resend_page("Resend Domains", RESEND_DOMAINS_URL)
        completion = (
            input(
                "Press Enter after Cloudflare setup, M for manual records, or X to exit: "
            )
            .strip()
            .casefold()
        )
        if completion == "x":
            raise SetupCancelled(
                "The Resend domain was retained; rerun setup when DNS is ready."
            )
        if completion != "m":
            return

    _print_domain_records(domain)
    confirmed = input(
        "After adding all exact records at your DNS provider, press Enter (x to exit): "
    ).strip()
    if confirmed.casefold() == "x":
        raise SetupCancelled(
            "The Resend domain was retained; rerun setup after adding its DNS records."
        )


# @testable false
# @covered-by installer/ai_email.py::configure_ai_email
# @reason bounded polling is exercised through the setup workflow
def _wait_for_domain(client, domain_id, *, attempts=12, sleep=time.sleep):
    for attempt in range(attempts):
        current = client.get_domain(domain_id)
        status = str(current.get("status") or "").casefold()
        if status == "verified":
            return current
        if status == "failed":
            raise ProviderError(
                "Resend could not verify the receiving DNS records. Check the exact "
                "record names, values, and MX priority, then rerun setup."
            )
        if attempt < attempts - 1:
            sleep(5)
    raise ProviderError(
        "Resend domain verification is still pending. Wait for DNS propagation and "
        "rerun ./setup.sh ai-email; the existing domain will be reused."
    )


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_reconcile_webhook_reuses_endpoint_and_disables_before_deploy
# @features ai-email
# @dimensions setup resend webhook idempotence disabled-first secret-retrieval
def reconcile_webhook(client, endpoint):
    """Return one exact webhook and leave it disabled for safe deployment."""
    matches = [
        item
        for item in client.list_webhooks()
        if str(item.get("endpoint") or "").rstrip("/") == endpoint.rstrip("/")
    ]
    if len(matches) > 1:
        raise ProviderError(f"Resend returned duplicate webhooks for {endpoint}.")
    if matches:
        webhook_id = str(matches[0].get("id") or "").strip()
        if not webhook_id:
            raise ProviderError("Resend did not return a webhook ID.")
        client.update_webhook(webhook_id, endpoint=endpoint, status="disabled")
        action = "updated"
    else:
        created = client.create_webhook(endpoint)
        webhook_id = str(created.get("id") or "").strip()
        if not webhook_id:
            raise ProviderError("Resend did not return a webhook ID.")
        # Creation is currently enabled by default. Disable it immediately so
        # the complete local configuration can be saved before delivery starts.
        client.update_webhook(webhook_id, endpoint=endpoint, status="disabled")
        action = "created-disabled"
    current = client.get_webhook(webhook_id)
    secret = str(current.get("signing_secret") or "").strip()
    if not secret:
        raise ProviderError("Resend did not return the webhook signing secret.")
    if str(current.get("status") or "").casefold() != "disabled":
        raise ProviderError("Resend webhook could not be disabled before deployment.")
    record_mutation(
        "ai-email-webhook",
        action=action,
        resource="Resend webhook",
        identifier=webhook_id,
    )
    return current


# @testable false
# @covered-by installer/ai_email.py::configure_ai_email
# @reason canonical config assembly delegates validation to config.ai_email
def _setup_config(
    existing,
    *,
    domain,
    domain_id,
    webhook,
    inbound_key,
    sending_key,
    sender_email,
    sender_name,
):
    return normalize_ai_email_config(
        {
            "version": 1,
            "provider": "resend",
            "enabled": True,
            "domain": domain,
            "aliases": (existing or {}).get("aliases")
            or {
                "ai": "ai",
                "ask": "ask",
                "create": "create",
                "organize": "organize",
            },
            "resend": {
                "domainId": domain_id,
                "webhookId": webhook["id"],
                "webhookSecret": webhook["signing_secret"],
                "inboundApiKey": inbound_key,
                "sendingApiKey": sending_key,
                "senderEmail": sender_email,
                "senderName": sender_name,
            },
            "limits": dict(AI_EMAIL_LIMITS),
        }
    )


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_setup_requires_custom_domain_and_supporting_services
# @features ai-email
# @dimensions setup prerequisites custom-domain supporting-services
def _prerequisites(settings):
    custom_domain = str(settings.get("CUSTOM_DOMAIN") or "").strip()
    auth_email = settings.get("AUTH_EMAIL_CONFIG") or {}
    missing = []
    if not custom_domain:
        missing.append("a custom application domain")
    if not (
        str(auth_email.get("provider") or "").casefold() == "smtp"
        and str(auth_email.get("service") or "").casefold() == "resend"
        and auth_email.get("password")
        and auth_email.get("senderEmail")
        and auth_email.get("senderName")
    ):
        missing.append(
            "Resend-backed authentication email (run ./setup.sh email and choose Resend)"
        )
    if not settings.get("AI_MODEL"):
        missing.append("AI configuration")
    if not settings.get("RESOURCE_REGION") or not settings.get(
        "RUNTIME_SERVICE_ACCOUNT_EMAIL"
    ):
        missing.append("deferred-job infrastructure")
    if missing:
        raise ProviderInvalidInput(
            "AI email setup requires " + ", ".join(missing) + "."
        )
    return normalize_email_domain(custom_domain, "CUSTOM_DOMAIN")


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_disable_turns_off_provider_before_saving_and_deploying
# @features ai-email
# @dimensions setup disable disabled-first provider-state deploy secrets
def _disable(existing):
    from config import SETTINGS
    from installer import utils

    client = ResendSetupClient(existing["resend"]["inboundApiKey"])
    endpoint = f"https://{SETTINGS.APP['CUSTOM_DOMAIN']}{WEBHOOK_PATH}"
    client.update_webhook(
        existing["resend"]["webhookId"], endpoint=endpoint, status="disabled"
    )
    current = client.get_webhook(existing["resend"]["webhookId"])
    if str(current.get("status") or "").casefold() != "disabled":
        raise ProviderError("Resend webhook did not enter the disabled state.")
    disabled = dict(existing)
    disabled["enabled"] = False
    SETTINGS.APP["AI_EMAIL_CONFIG"] = normalize_ai_email_config(disabled)
    SETTINGS.save()
    print(
        "AI email receiving is disabled; provider resources and secrets were retained."
    )
    if input(
        "Deploy the disabled AI email configuration now? [Y/n]: "
    ).strip().casefold() != "n":
        utils.deploy_to_app_engine()
        print("The disabled AI email configuration has been deployed.")
    else:
        print(
            "The disabled configuration was saved locally. Deploy it later to remove "
            "the addresses from the application."
        )
    return 0


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_main_install_ai_email_offer_requires_custom_domain_and_resend
# @features setup ai-email
# @dimensions main-install prerequisites optional deferred-activation
def setup_ai_email():
    """Offer AI email during a fresh install and defer activation to its deploy."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    settings = SETTINGS.APP
    custom_domain = str(settings.get("CUSTOM_DOMAIN") or "").strip()
    auth_email = settings.get("AUTH_EMAIL_CONFIG") or {}
    resend_ready = (
        str(auth_email.get("provider") or "").casefold() == "smtp"
        and str(auth_email.get("service") or "").casefold() == "resend"
        and bool(auth_email.get("password"))
    )

    if not custom_domain or not resend_ready:
        print(
            f.info(
                "AI email submissions can be added after a custom application "
                "domain and Resend authentication email are configured."
            )
        )
        print("To add it later:")
        print(f"  1. Configure the custom URL: {setup_command('url')}")
        print(f"  2. Choose Resend for email: {setup_command('email')}")
        print(f"  3. Configure AI email: {setup_command('ai-email')}")
        return None

    _prerequisites(settings)
    choice = (
        input(
            "Configure inbound AI email submissions through Resend now? "
            "[y/N] (x to exit): "
        )
        .strip()
        .casefold()
    )
    if choice == "x":
        raise SetupCancelled("Installation cancelled before AI email setup.")
    if choice != "y":
        print(f"AI email can be configured later with {setup_command('ai-email')}.")
        return None
    return configure_ai_email(prepare_installation=False, deploy=False)


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_setup_saves_deploys_then_enables_webhook
# @tests tests_tooling/test_001e_setup_orchestration.py::test_default_install_activates_ai_email_after_deploy_and_jobs
# @pair ai-email:activation
# @pair ai-email:provider-verification
# @pair setup:main-install
def activate_ai_email(candidate=None):
    """Enable and verify a configured webhook after its application deploy."""
    from config import SETTINGS

    candidate = normalize_ai_email_config(
        candidate or SETTINGS.APP.get("AI_EMAIL_CONFIG")
    )
    if not candidate or not candidate["enabled"]:
        raise ProviderInvalidInput("Enabled AI email configuration is unavailable.")
    endpoint = f"https://{SETTINGS.APP['CUSTOM_DOMAIN']}{WEBHOOK_PATH}"
    webhook_id = candidate["resend"]["webhookId"]
    client = ResendSetupClient(candidate["resend"]["inboundApiKey"])
    client.update_webhook(webhook_id, endpoint=endpoint, status="enabled")
    current_webhook = client.get_webhook(webhook_id)
    if str(current_webhook.get("status") or "").casefold() != "enabled":
        raise ProviderError(
            "Resend did not enable the AI email webhook. Rerun setup to reconcile it."
        )

    f = FORMATTER.initialize()
    print(f.success("AI email provider configuration is ready."))
    for tool in ("ai", "ask", "create", "organize"):
        print(f"  {tool.title():<8} {candidate['aliases'][tool]}@{candidate['domain']}")
    print("\nNext steps:")
    print("  1. Send a normal email from a registered user's exact email address.")
    print("  2. Confirm the acceptance email links to a pending report, then confirm")
    print("     the result email links to the completed answer/proposal.")
    print(
        wrap_text(
            "Create and Organize emails only prepare reports. Applying a proposal still "
            "requires the user to sign in, review it, and run it in Lagniappe."
        )
    )
    return True


# @testable true
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_setup_requires_custom_domain_and_supporting_services
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_setup_saves_deploys_then_enables_webhook
# @tests tests_tooling/test_001h_setup_ai_email.py::test_ai_email_rerun_reuses_saved_inbound_api_key_without_prompt
# @features ai-email
# @dimensions setup prerequisites provider-verification deployment-guidance deploy disabled-first manual-smoke-test
def configure_ai_email(*, prepare_installation=True, deploy=True):
    """Configure production Resend receiving and optionally deploy it."""
    if prepare_installation:
        from installer.verify import prepare_existing_installation

        prepare_existing_installation()
    from config import SETTINGS
    from installer import utils

    f = FORMATTER.initialize()
    custom_domain = _prerequisites(SETTINGS.APP)
    try:
        existing = normalize_ai_email_config(SETTINGS.APP.get("AI_EMAIL_CONFIG"))
    except ValueError as error:
        raise ProviderInvalidInput(
            f"Saved AI_EMAIL_CONFIG is invalid: {error}"
        ) from error

    if existing:
        print(
            f"AI email submissions are "
            f"{'enabled' if existing['enabled'] else 'disabled'} for "
            f"{existing['domain']}."
        )
        action = input("Reconcile, disable, or exit? [R/d/x]: ").strip().casefold()
        if action == "x":
            raise SetupCancelled("AI email setup cancelled.")
        if action == "d":
            return _disable(existing)

    print(f"\n{f.info('AI Email Submissions')}")
    print(
        wrap_text(
            "This configures Resend receiving and the Lagniappe AI, Ask, Create, "
            "and Organize addresses. It verifies the provider resources and saves "
            "the application configuration, then offers to deploy and activate it."
        )
    )
    default_domain = (existing or {}).get("domain") or f"inbound.{custom_domain}"
    domain = normalize_email_domain(
        _prompt("Dedicated inbound email subdomain", default_domain)
    )
    if domain == custom_domain or not domain.endswith(f".{custom_domain}"):
        raise ProviderInvalidInput(
            f"Use a dedicated subdomain beneath {custom_domain}, not the application/root domain."
        )
    dedicated = (
        input(
            f"Confirm {domain} is dedicated to Lagniappe receiving and has no "
            "unrelated MX records [y/N] (x to exit): "
        )
        .strip()
        .casefold()
    )
    if dedicated == "x":
        raise SetupCancelled("AI email setup cancelled.")
    if dedicated != "y":
        raise ProviderInvalidInput(
            "Choose or clear a dedicated inbound subdomain before continuing."
        )

    existing_resend = (existing or {}).get("resend") or {}
    saved_inbound_key = str(existing_resend.get("inboundApiKey") or "")
    guide_resend_receiving_key(existing=bool(saved_inbound_key))
    inbound_key = saved_inbound_key or _prompt_secret(
        "Resend Full access API key (input is visible)"
    )
    client = ResendSetupClient(inbound_key)
    domain_state = reconcile_receiving_domain(client, domain)
    domain_id = _domain_id(domain_state)
    if str(domain_state.get("status") or "").casefold() != "verified":
        guide_resend_receiving_dns(
            domain_state,
            cloudflare_default=bool(
                SETTINGS.APP.get("CLOUDFLARE_ZONE_ID")
                or SETTINGS.APP.get("CLOUDFLARE_ACCOUNT_ID")
            ),
        )
        client.verify_domain(domain_id)
        domain_state = _wait_for_domain(client, domain_id)
    print(f.success(f"Resend receiving domain {domain} is verified."))

    auth_email = SETTINGS.APP.get("AUTH_EMAIL_CONFIG") or {}
    try:
        sender_email = normalize_email_address(
            auth_email.get("senderEmail"),
            "AUTH_EMAIL_CONFIG.senderEmail",
        )
    except ValueError as error:
        raise ProviderInvalidInput(
            "Authentication email must have a valid configured sender before "
            "AI email setup can run. Rerun ./setup.sh email first."
        ) from error
    sender_name = str(
        auth_email.get("senderName") or SETTINGS.APP.get("APP_NAME") or "Lagniappe"
    ).strip()
    if not sender_name:
        raise ProviderInvalidInput(
            "Authentication email must have a configured sender name. "
            "Rerun ./setup.sh email first."
        )
    sending_domain = sender_email.rsplit("@", 1)[-1]
    sending_key = str(auth_email.get("password") or "")
    guide_resend_sending_identity(
        sending_domain,
        reusable_sender=sender_email,
    )
    if not sending_key or sending_key == inbound_key:
        raise ProviderInvalidInput(
            "The authentication-email Resend Sending key must differ from the "
            "Full access receiving key. Rerun ./setup.sh email to rotate the "
            "Sending key, then rerun this command."
        )
    print(
        f"Feedback sender: {sender_name} <{sender_email}> (from authentication email)"
    )

    endpoint = f"https://{custom_domain}{WEBHOOK_PATH}"
    webhook = reconcile_webhook(client, endpoint)
    candidate = _setup_config(
        existing,
        domain=domain,
        domain_id=domain_id,
        webhook=webhook,
        inbound_key=inbound_key,
        sending_key=sending_key,
        sender_email=sender_email,
        sender_name=sender_name,
    )
    SETTINGS.APP["AI_EMAIL_CONFIG"] = candidate
    SETTINGS.save()

    if not deploy:
        print(
            f.success(
                "AI email settings are ready; the webhook will remain disabled "
                "until the main installation deploy succeeds."
            )
        )
        return candidate

    print("\nNext step: deploy and activate AI email submissions.")
    print(
        wrap_text(
            f"Setup has verified the Resend domain and webhook configuration and "
            f"saved the application settings locally. It can now deploy the current "
            f"checkout to https://{custom_domain}. After a successful deployment it "
            "will enable the Resend webhook; no synthetic email or health probe is run."
        )
    )
    if (
        input("Deploy and activate AI email submissions now? [Y/n]: ")
        .strip()
        .casefold()
        == "n"
    ):
        print(
            f.warning(
                "Configuration was saved locally and the Resend webhook remains "
                "disabled. Rerun ./setup.sh ai-email when ready to deploy."
            )
        )
        return 0

    utils.deploy_to_app_engine()
    activate_ai_email(candidate)
    return 0


__all__ = [
    "ResendSetupClient",
    "activate_ai_email",
    "configure_ai_email",
    "setup_ai_email",
    "guide_resend_receiving_key",
    "guide_resend_receiving_dns",
    "guide_resend_sending_identity",
    "reconcile_receiving_domain",
    "reconcile_webhook",
]
