"""Configure SMTP delivery for authentication action links."""

import re
import smtplib
import ssl
import webbrowser
from email.message import EmailMessage
from email.utils import formataddr

import certifi

from installer import FORMATTER, wrap_text
from installer.errors import (
    ProviderError,
    ProviderTimeout,
    ProviderTransientError,
    SetupCancelled,
    retry_provider_call,
)
from runner.context import setup_command

GMAIL_APP_PASSWORDS_URL = (
    "https://accounts.google.com/AccountChooser"
    "?continue=https%3A%2F%2Fmyaccount.google.com%2Fapppasswords"
)
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
RESEND_DOMAINS_URL = "https://resend.com/domains"
RESEND_API_KEYS_URL = "https://resend.com/api-keys"
RESEND_SMTP_HOST = "smtp.resend.com"
RESEND_SMTP_PORT = 465
RESEND_SMTP_USERNAME = "resend"
SMTP_TIMEOUT = 15
SMTP_SECURITY_MODES = {"starttls", "ssl"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_auth_email_config_requires_canonical_smtp
# @features setup
# @dimensions authentication-email validation app-password
def normalize_app_password(value):
    """Normalize and validate Google's displayed 16-character app password."""
    password = "".join(str(value or "").split())
    return password if re.fullmatch(r"[A-Za-z0-9]{16}", password) else None


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_auth_email_config_requires_canonical_smtp
# @features setup
# @dimensions authentication-email validation smtp
def normalize_auth_email_config(config):
    """Return one validated generic SMTP configuration or ``None``."""
    config = config or {}
    if config.get("provider") != "smtp":
        return None
    service = str(config.get("service") or "SMTP").strip()
    host = str(config.get("host") or "").strip()
    security = str(config.get("security") or "").strip().casefold()
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    sender_email = str(config.get("senderEmail") or "").strip()
    sender_name = str(config.get("senderName") or "").strip()
    try:
        port = int(config.get("port"))
    except (TypeError, ValueError):
        return None
    if not (
        service
        and host
        and 1 <= port <= 65535
        and security in SMTP_SECURITY_MODES
        and username
        and password
        and EMAIL_PATTERN.fullmatch(sender_email)
        and sender_name
    ):
        return None
    return {
        "provider": "smtp",
        "service": service,
        "host": host,
        "port": port,
        "security": security,
        "username": username,
        "password": password,
        "senderEmail": sender_email,
        "senderName": sender_name,
    }


# @testable false
# @covered-by installer/auth_email.py::normalize_auth_email_config
# @reason validation predicate delegates to the canonical normalizer
def auth_email_config_matches(config):
    """Return whether saved authentication-email settings are complete."""
    return normalize_auth_email_config(config) is not None


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_smtp_test_message_supports_tls_and_reports_transport_failures
# @features setup
# @dimensions authentication-email smtp tls certificate-validation
def _create_smtp_tls_context():
    """Build an SMTP context with system and installer-managed CA certificates."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_smtp_test_message_supports_tls_and_reports_transport_failures
# @features setup
# @dimensions authentication-email smtp tls transient-retry error-reporting
def test_smtp_delivery(
    config,
    recipient=None,
    *,
    smtp_factory=smtplib.SMTP,
    smtp_ssl_factory=smtplib.SMTP_SSL,
    tls_context=None,
    smtp_attempts=2,
    retry_sleep=None,
):
    """Send a test message through the candidate SMTP configuration."""
    normalized = normalize_auth_email_config(config)
    if not normalized:
        raise ProviderError("Authentication-email SMTP settings are incomplete.")
    recipient = str(recipient or normalized["senderEmail"]).strip()
    if not EMAIL_PATTERN.fullmatch(recipient):
        raise ProviderError("Enter a valid test-recipient email address.")

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = formataddr(
        (normalized["senderName"], normalized["senderEmail"])
    )
    message["Subject"] = "Lagniappe authentication email test"
    message.set_content(
        "Lagniappe can use this email service to send account verification "
        "and password-reset links."
    )
    context = tls_context or _create_smtp_tls_context()

    # @testable false
    # @covered-by installer/auth_email.py::test_smtp_delivery
    # @reason nested response sanitizer is exercised through SMTP failure handling
    def response_detail(response):
        if isinstance(response, bytes):
            response = response.decode("utf-8", errors="replace")
        return " ".join(str(response or "").split())[:500]

    # @testable false
    # @covered-by installer/auth_email.py::test_smtp_delivery
    # @reason one-attempt transport helper is exercised through bounded delivery retry
    def send_test_message():
        stage = "connect to the email service"
        try:
            if normalized["security"] == "ssl":
                smtp_connection = smtp_ssl_factory(
                    normalized["host"],
                    normalized["port"],
                    timeout=SMTP_TIMEOUT,
                    context=context,
                )
            else:
                smtp_connection = smtp_factory(
                    normalized["host"],
                    normalized["port"],
                    timeout=SMTP_TIMEOUT,
                )
            with smtp_connection as smtp:
                if normalized["security"] == "starttls":
                    stage = "start the encrypted connection"
                    smtp.starttls(context=context)
                stage = "sign in"
                smtp.login(normalized["username"], normalized["password"])
                stage = "send the test message"
                smtp.send_message(message)
        except smtplib.SMTPRecipientsRefused as error:
            responses = list(error.recipients.values())
            code, response = responses[0] if responses else (None, None)
            detail = response_detail(response)
            code_text = f"SMTP {code}" if code is not None else "SMTP error"
            suffix = f": {detail}" if detail else ""
            raise ProviderError(
                f"{normalized['service']} rejected the test recipient "
                f"({code_text}{suffix})."
            ) from error
        except smtplib.SMTPResponseException as error:
            detail = response_detail(error.smtp_error)
            suffix = f": {detail}" if detail else ""
            error_type = (
                ProviderTransientError
                if 400 <= error.smtp_code < 500
                else ProviderError
            )
            raise error_type(
                f"{normalized['service']} rejected the SMTP request while "
                f"trying to {stage} (SMTP {error.smtp_code}{suffix})."
            ) from error
        except ssl.SSLCertVerificationError as error:
            detail = response_detail(error)
            suffix = f" ({detail})" if detail else ""
            raise ProviderError(
                f"The TLS certificate from {normalized['service']} could not "
                f"be verified while trying to {stage}{suffix}. No mailbox or "
                "password was sent. If a VPN or security tool inspects "
                "encrypted traffic, pause it and retry. Do not disable "
                "certificate verification."
            ) from error
        except smtplib.SMTPServerDisconnected as error:
            detail = response_detail(error)
            suffix = f" ({detail})" if detail else ""
            raise ProviderTransientError(
                f"The connection to {normalized['service']} was interrupted "
                f"while trying to {stage}{suffix}. The mailbox and app "
                "password were not explicitly rejected. Check the internet "
                "connection or VPN and retry."
            ) from error
        except TimeoutError as error:
            raise ProviderTimeout(
                f"The connection to {normalized['service']} timed out while "
                f"trying to {stage}. The mailbox and app password were not "
                "explicitly rejected. Check the internet connection or VPN "
                "and retry."
            ) from error
        except smtplib.SMTPNotSupportedError as error:
            detail = response_detail(error)
            suffix = f": {detail}" if detail else ""
            raise ProviderError(
                f"{normalized['service']} could not {stage}{suffix}."
            ) from error
        except smtplib.SMTPException as error:
            detail = response_detail(error)
            suffix = f": {detail}" if detail else ""
            raise ProviderError(
                f"The SMTP test could not {stage} "
                f"({type(error).__name__}{suffix})."
            ) from error
        except OSError as error:
            detail = response_detail(error)
            suffix = f" ({detail})" if detail else ""
            raise ProviderTransientError(
                f"The connection to {normalized['service']} failed while "
                f"trying to {stage}{suffix}. The mailbox and app password "
                "were not explicitly rejected. Check the internet connection "
                "or VPN and retry."
            ) from error
        return True

    retry_options = {
        "description": f"Test {normalized['service']} email delivery",
        "attempts": smtp_attempts,
        "delays": (1,),
    }
    if retry_sleep is not None:
        retry_options["sleep"] = retry_sleep
    return retry_provider_call(send_test_message, **retry_options)


# @testable false
# @covered-by installer/auth_email.py::setup_auth_email
# @reason interactive browser guidance is owned by the public setup step
def _print_gmail_instructions():
    print("\nConfigure authentication email:")
    print(
        wrap_text(
            "A new installation can send verification and password-reset "
            "links through any Gmail or Google Workspace mailbox with 2-Step "
            "Verification and App Passwords enabled. After adding a custom "
            f"domain, {setup_command('email')} can replace Gmail with any "
            "SMTP email service."
        )
    )
    print(
        wrap_text(
            "Google warns about app passwords because they let an app sign in "
            "without the usual interactive Google prompt. Lagniappe uses this "
            "one only to send email from the chosen mailbox on its owner's "
            "behalf, so people the owner invites can verify their email "
            "addresses and request password resets."
        )
    )
    print(wrap_text("\n1. Choose the mailbox Lagniappe should send from."))
    print(wrap_text("2. Enable 2-Step Verification if it is not already enabled."))
    print(
        wrap_text(
            "3. In the App name box, enter 'Lagniappe', then click Create."
        )
    )
    print(
        wrap_text(
            "4. Copy the 16-character password Google displays. Setup will "
            "test it and store it in the private application settings file."
        )
    )
    ready = input(
        "Press Enter when you are ready to open Google App Passwords "
        "(x to exit): "
    ).strip()
    if ready.casefold() == "x":
        raise SetupCancelled("Installation cancelled before Google App Passwords.")
    print(
        "Opening a Google account picker for App Passwords:\n"
        f"  {GMAIL_APP_PASSWORDS_URL}"
    )
    try:
        webbrowser.open_new_tab(GMAIL_APP_PASSWORDS_URL)
    except webbrowser.Error:
        pass


# @testable false
# @covered-by installer/auth_email.py::setup_auth_email
# @covered-by installer/auth_email.py::_setup_provider_auth_email
# @reason interactive retry and cancellation behavior is owned by setup
def _prompt(label, default=None):
    if default not in (None, ""):
        suffix = (
            f" [{default}] "
            "(press Enter to use the bracketed value; x to exit): "
        )
    else:
        suffix = " (x to exit): "
    value = input(f"{label}{suffix}").strip()
    if value.casefold() == "x":
        raise SetupCancelled("Installation cancelled during email installer.")
    return value or str(default or "").strip()


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_setup_auth_email_saves_generic_gmail_smtp_after_test
# @tests tests_tooling/test_001b_setup_providers.py::test_setup_auth_email_uses_custom_domain_provider_path
# @features setup
# @dimensions authentication-email smtp interactive-input settings-save failure-isolation custom-domain
def setup_auth_email():
    """Select a custom-domain SMTP service or the zero-domain Gmail bootstrap."""
    from config import SETTINGS

    existing = SETTINGS.APP.get("AUTH_EMAIL_CONFIG")
    normalized = normalize_auth_email_config(existing)
    if normalized:
        print(
            "Authentication email is configured for "
            f"{normalized['senderEmail']}."
        )
        return True

    custom_domain = str(SETTINGS.APP.get("CUSTOM_DOMAIN") or "").strip()
    if not custom_domain:
        use_custom_domain = input(
            "Do you have a custom domain to use for this installation? [y/N] "
            "(x to exit): "
        ).strip().casefold()
        if use_custom_domain == "x":
            raise SetupCancelled("Installation cancelled before email installer.")
        if use_custom_domain == "y":
            from .custom_domain import _setup_custom_domain

            if not _setup_custom_domain(configure_auth=False):
                raise SetupCancelled(
                    "Custom-domain setup is incomplete. Run setup again to "
                    "resume."
                )
            SETTINGS.save()
            custom_domain = str(SETTINGS.APP.get("CUSTOM_DOMAIN") or "").strip()

    if custom_domain:
        return _setup_provider_auth_email()

    f = FORMATTER.initialize()
    _print_gmail_instructions()
    suggested_email = str(SETTINGS.APP.get("ADMIN_EMAIL") or "").strip()
    suggested_name = str(SETTINGS.APP.get("APP_NAME") or "Lagniappe").strip()

    while True:
        sender_email = _prompt("Email sending account", suggested_email)
        if not EMAIL_PATTERN.fullmatch(sender_email):
            print(f.error("Enter a valid Gmail or Google Workspace email address."))
            continue
        print(
            wrap_text(
                "The sender name is what recipients will see next to the "
                "sending email address."
            )
        )
        sender_name = _prompt("Sender name", suggested_name)
        app_password = normalize_app_password(
            _prompt("Google App Password (input is visible)")
        )
        if not app_password:
            print(f.error("Enter the 16-character Google App Password."))
            continue

        candidate = {
            "provider": "smtp",
            "service": "Gmail",
            "host": GMAIL_SMTP_HOST,
            "port": GMAIL_SMTP_PORT,
            "security": "starttls",
            "username": sender_email,
            "password": app_password,
            "senderEmail": sender_email,
            "senderName": sender_name,
        }
        print(
            "Testing authentication email delivery "
            "(an interrupted connection is retried once)..."
        )
        try:
            test_smtp_delivery(candidate, sender_email)
        except ProviderError as error:
            print(f.error(str(error)))
            print(
                f.warning(
                    "Email settings were not saved. If the message above says "
                    "the connection failed, was interrupted, timed out, or "
                    "could not verify the TLS certificate, retry with the same "
                    "mailbox and app password after resolving that issue. "
                    "Create a new password only if Gmail explicitly rejects "
                    "sign-in."
                )
            )
            retry = input("Try email setup again? [Y/n]: ").strip().casefold()
            if retry == "n":
                raise
            continue

        SETTINGS.APP["AUTH_EMAIL_CONFIG"] = candidate
        SETTINGS.save()
        print(f.success(f"Authentication email configured for {sender_email}."))
        return True


# @testable false
# @covered-by installer/auth_email.py::_setup_provider_auth_email
# @reason transport choice prompt is owned by the provider configuration workflow
def _prompt_security(default="starttls"):
    while True:
        value = _prompt(
            "SMTP encryption: STARTTLS (usually 587/2525) or SSL/TLS "
            "(usually 465)",
            default,
        ).casefold()
        if value in {"starttls", "start", "587", "2525"}:
            return "starttls"
        if value in {"ssl", "tls", "465"}:
            return "ssl"
        print("Choose STARTTLS or SSL/TLS.")


# @testable false
# @covered-by installer/auth_email.py::_setup_provider_auth_email
# @reason numeric port prompt is owned by the provider configuration workflow
def _prompt_port(default=587):
    while True:
        value = _prompt("SMTP port", default)
        try:
            port = int(value)
        except ValueError:
            port = 0
        if 1 <= port <= 65535:
            return port
        print("Enter an SMTP port between 1 and 65535.")


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_auth_email_dmarc_setup_supports_cloudflare_and_manual_dns
# @features setup
# @dimensions authentication-email dmarc cloudflare-dns manual-dns
def _configure_dmarc_for_sender(sender_email):
    """Publish or confirm a DMARC policy for the visible sender domain."""
    from config import SETTINGS
    from .domain import (
        DMARC_DEFAULT_POLICY,
        ensure_cloudflare_dmarc_record,
        get_cloudflare_api_token,
        get_cloudflare_zone,
    )

    sender_domain = str(sender_email).rsplit("@", 1)[-1].strip().lower()
    record_name = f"_dmarc.{sender_domain}"
    print(
        "\n"
        + wrap_text(
            "DMARC ties the visible From domain to SPF or DKIM and tells "
            "receiving mail systems how to handle messages that fail. Setup "
            "starts with the non-disruptive p=none policy; it enables DMARC "
            "authentication without asking receivers to quarantine or reject "
            "mail. This step is recommended but optional."
        )
    )

    cloudflare_configured = bool(
        SETTINGS.APP.get("CLOUDFLARE_ZONE_ID")
        or SETTINGS.APP.get("CLOUDFLARE_ACCOUNT_ID")
    )
    if cloudflare_configured:
        use_cloudflare = (
            input(
                "Publish or verify this sender-domain DMARC record through "
                "Cloudflare? [Y/n] (s to skip; x to exit): "
            )
            .strip()
            .casefold()
        )
        if use_cloudflare == "x":
            raise SetupCancelled("Authentication-email DMARC setup cancelled.")
        if use_cloudflare == "s":
            print("Skipped optional DMARC setup.")
            return False
        if use_cloudflare != "n":
            api_token = get_cloudflare_api_token()
            zone = get_cloudflare_zone(sender_domain, api_token)
            result = ensure_cloudflare_dmarc_record(
                sender_domain,
                zone,
                api_token,
            )
            verb = "Created" if result["action"] == "created" else "Verified"
            print(f"{verb} Cloudflare TXT {result['name']}: {result['content']}")
            return True

    print("\nAdd this DNS record at the provider for the sender domain:")
    print("  Type:  TXT")
    print(f"  Name:  {record_name}")
    print(f"  Value: {DMARC_DEFAULT_POLICY}")
    confirmed = (
        input(
            "Have you added or verified this DMARC record? [y/N] "
            "(s to skip; x to exit): "
        )
        .strip()
        .casefold()
    )
    if confirmed == "x":
        raise SetupCancelled("Authentication-email DMARC setup cancelled.")
    if confirmed == "s":
        print("Skipped optional DMARC setup.")
        return False
    if confirmed != "y":
        raise SetupCancelled(
            "DMARC setup is incomplete. The previous email settings remain active."
        )
    return True


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_provider_auth_email_uses_resend_cloudflare_shortcut
# @tests tests_tooling/test_001b_setup_providers.py::test_resend_auth_email_rerun_reuses_saved_sending_key_without_prompt
# @features setup
# @dimensions authentication-email smtp resend cloudflare-dns interactive-input settings-save
def _setup_resend_auth_email(current, custom_domain):
    """Guide Resend/Cloudflare setup and save Resend's fixed SMTP settings."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    cloudflare_configured = bool(
        SETTINGS.APP.get("CLOUDFLARE_ZONE_ID")
        or SETTINGS.APP.get("CLOUDFLARE_ACCOUNT_ID")
    )
    print(f"\n{f.info('Configure Resend')}")
    if cloudflare_configured:
        print(
            wrap_text(
                "This installation already uses Cloudflare DNS. Resend can "
                "publish its SPF, DKIM, and return-path records through the "
                "'Sign in to Cloudflare' button. After the SMTP test, setup "
                "will separately publish or verify the sender domain's DMARC "
                "record."
            )
        )
    else:
        print(
            wrap_text(
                "Add a sending domain in Resend and complete its DNS "
                "verification before continuing."
            )
        )
    print(f"Opening Resend domains:\n  {RESEND_DOMAINS_URL}")
    try:
        webbrowser.open_new_tab(RESEND_DOMAINS_URL)
    except webbrowser.Error:
        pass
    domain_ready = input(
        "When Resend shows the sending domain as verified, press Enter "
        "(x to exit): "
    ).strip()
    if domain_ready.casefold() == "x":
        raise SetupCancelled("Resend domain setup is incomplete.")

    from .domain.validation import validate_domain

    current_is_resend = (
        str(current.get("service") or "").strip().casefold() == "resend"
    )
    current_sender = str(current.get("senderEmail") or "").strip()
    current_sending_key = (
        str(current.get("password") or "") if current_is_resend else ""
    )
    verified_domain_default = (
        current_sender.rsplit("@", 1)[-1]
        if current_is_resend and "@" in current_sender
        else None
    )
    print(
        wrap_text(
            f"\nThe application domain is {custom_domain}, but Resend may use "
            "a dedicated sending subdomain such as "
            f"mail.{custom_domain}. Copy the exact domain shown on the Resend "
            "key and domain pages."
        )
    )

    while True:
        verified_domain = _prompt(
            "Verified Resend sending domain",
            verified_domain_default,
        ).strip().lower().rstrip(".")
        if not validate_domain(verified_domain):
            print(f.error("Enter the exact valid domain verified by Resend."))
            continue
        verified_domain_default = verified_domain
        current_sender_domain = (
            current_sender.rsplit("@", 1)[-1].strip().lower()
            if "@" in current_sender
            else ""
        )
        using_saved_key = bool(
            current_sending_key
            and verified_domain == current_sender_domain
        )
        if using_saved_key:
            api_key = current_sending_key
            print(
                wrap_text(
                    "A Resend Sending key is already saved for this verified "
                    "domain. Setup will reuse it without prompting."
                )
            )
        else:
            print(
                wrap_text(
                    "\nCreate an API key named 'Lagniappe' with Sending access. "
                    "Restrict it to the verified sending domain when Resend offers "
                    "that choice. The key is shown only once."
                )
            )
            print(f"Opening Resend API keys:\n  {RESEND_API_KEYS_URL}")
            try:
                webbrowser.open_new_tab(RESEND_API_KEYS_URL)
            except webbrowser.Error:
                pass
            api_key = _prompt("Resend API key (input is visible)")
        default_sender = (
            current_sender
            if current_is_resend
            and current_sender.casefold().endswith(
                f"@{verified_domain.casefold()}"
            )
            else f"noreply@{verified_domain}"
        )
        sender_email = _prompt(
            "Sender email address on the verified Resend domain",
            default_sender,
        )
        sender_domain = (
            sender_email.rsplit("@", 1)[-1].strip().lower()
            if "@" in sender_email
            else ""
        )
        if sender_domain != verified_domain:
            print(
                f.error(
                    f"The sender must end in @{verified_domain}, matching the "
                    "verified Resend domain and domain-restricted API key."
                )
            )
            continue
        sender_name = _prompt(
            "Sender name",
            current.get("senderName")
            or SETTINGS.APP.get("APP_NAME")
            or "Lagniappe",
        )
        test_recipient = _prompt(
            "Send the test message to",
            SETTINGS.APP.get("ADMIN_EMAIL") or sender_email,
        )
        candidate = normalize_auth_email_config(
            {
                "provider": "smtp",
                "service": "Resend",
                "host": RESEND_SMTP_HOST,
                "port": RESEND_SMTP_PORT,
                "security": "ssl",
                "username": RESEND_SMTP_USERNAME,
                "password": api_key,
                "senderEmail": sender_email,
                "senderName": sender_name,
            }
        )
        if not candidate:
            print(
                f.error(
                    "Enter a Resend API key and a valid sender address on the "
                    "verified domain."
                )
            )
            continue

        print("Testing Resend SMTP delivery...")
        try:
            test_smtp_delivery(candidate, test_recipient)
        except ProviderError as error:
            print(f.error(str(error)))
            print(
                f.warning(
                    "The previous authentication-email settings remain active. "
                    "Confirm that Resend verified the domain and that the API "
                    "key has Sending access before retrying."
                )
            )
            retry = input("Try Resend setup again? [Y/n]: ").strip().casefold()
            if retry == "n":
                raise
            if using_saved_key:
                current_sending_key = ""
            continue

        _configure_dmarc_for_sender(sender_email)
        SETTINGS.APP["AUTH_EMAIL_CONFIG"] = candidate
        SETTINGS.save()
        print(
            f.success(
                f"Authentication email configured through Resend as "
                f"{sender_email}."
            )
        )
        return True


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_provider_auth_email_saves_only_after_successful_smtp_test
# @features setup
# @dimensions authentication-email smtp custom-domain interactive-input settings-save
def _setup_provider_auth_email():
    """Collect, test, and save provider-neutral SMTP settings."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    current = normalize_auth_email_config(SETTINGS.APP.get("AUTH_EMAIL_CONFIG")) or {}
    custom_domain = str(SETTINGS.APP["CUSTOM_DOMAIN"]).strip().lower()
    print(f"\n{f.info('Authentication Email Configuration')}")
    print(
        wrap_text(
            "Setup can configure Resend directly, or accept SMTP details from "
            "Postmark, Mailgun, Mailjet, SMTP2GO, Amazon SES, or another "
            "provider. The sender address must belong to a domain the provider "
            "has approved."
        )
    )
    existing_service = str(current.get("service") or "").strip().casefold()
    default_resend = existing_service in {"", "gmail", "resend"}
    choice_hint = "[Y/n]" if default_resend else "[y/N]"
    use_resend = input(
        f"Use Resend for authentication email? {choice_hint} (x to exit): "
    ).strip().casefold()
    if use_resend == "x":
        raise SetupCancelled("Authentication email setup cancelled.")
    if use_resend == "y" or (not use_resend and default_resend):
        return _setup_resend_auth_email(current, custom_domain)

    print(
        wrap_text(
            f"Lagniappe's application domain is {custom_domain}. Gather the "
            "SMTP host, port, encryption mode, username, and password or API "
            "key from the email provider before continuing."
        )
    )

    while True:
        service = _prompt("Email service name", current.get("service") or "SMTP")
        host = _prompt("SMTP host", current.get("host"))
        port = _prompt_port(current.get("port") or 587)
        security = _prompt_security(current.get("security") or "starttls")
        username = _prompt("SMTP username", current.get("username"))
        password = _prompt("SMTP password or API key (input is visible)")
        sender_email = _prompt(
            "Sender email address on the verified domain",
            current.get("senderEmail"),
        )
        sender_name = _prompt(
            "Sender name",
            current.get("senderName")
            or SETTINGS.APP.get("APP_NAME")
            or "Lagniappe",
        )
        test_recipient = _prompt(
            "Send the test message to",
            SETTINGS.APP.get("ADMIN_EMAIL") or sender_email,
        )
        candidate = normalize_auth_email_config(
            {
                "provider": "smtp",
                "service": service,
                "host": host,
                "port": port,
                "security": security,
                "username": username,
                "password": password,
                "senderEmail": sender_email,
                "senderName": sender_name,
            }
        )
        if not candidate:
            print(
                f.error(
                    "The SMTP settings are incomplete. Check the host, "
                    "credentials, sender address, and encryption mode."
                )
            )
            continue

        print(f"Testing {service} SMTP delivery...")
        try:
            test_smtp_delivery(candidate, test_recipient)
        except ProviderError as error:
            print(f.error(str(error)))
            print(
                f.warning(
                    "The previous authentication-email settings remain active. "
                    "Confirm the provider credentials and verified sender "
                    "domain before retrying."
                )
            )
            retry = input("Try email setup again? [Y/n]: ").strip().casefold()
            if retry == "n":
                raise
            continue

        _configure_dmarc_for_sender(sender_email)
        SETTINGS.APP["AUTH_EMAIL_CONFIG"] = candidate
        SETTINGS.save()
        print(
            f.success(
                f"Authentication email configured through {service} as "
                f"{sender_email}."
            )
        )
        return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_email_cli_requires_custom_domain
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_email_cli_configures_and_optionally_deploys
# @features setup
# @dimensions authentication-email smtp custom-domain cli deploy
def configure_auth_email():
    """Replace authentication-email delivery on an existing installation."""
    from .verify import prepare_existing_installation

    prepare_existing_installation()

    from config import SETTINGS
    from installer import FORMATTER, utils

    f = FORMATTER.initialize()
    if not str(SETTINGS.APP.get("CUSTOM_DOMAIN") or "").strip():
        print(
            f.error(
                "A custom application domain is required before configuring "
                "a dedicated email service."
            )
        )
        print(
            wrap_text(
                f"Run {setup_command('url')} first. The current Gmail or Google "
                "Workspace sender remains active until custom-domain email "
                "setup succeeds."
            )
        )
        return 1

    _setup_provider_auth_email()
    consent = input(f.info("Deploy the updated email settings now? [Y/n]: "))
    if consent.strip().casefold() != "n":
        utils.deploy_to_app_engine()
        print(f.success("Authentication email settings deployed."))
    else:
        print(
            f.warning(
                "Email settings were saved locally but are not active in the "
                "deployed app. Deploy when ready."
            )
        )
    return 0
