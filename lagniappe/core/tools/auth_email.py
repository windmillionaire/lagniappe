"""Authentication-email delivery through operator-provided SMTP."""

import re
import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

SMTP_TIMEOUT = 15
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthEmailError(RuntimeError):
    """Raised when authentication email cannot be delivered."""


# @testable false
# @covered-by lagniappe/core/tools/auth_email.py::send_auth_email
# @reason SMTP normalization is exercised through public delivery
def _smtp_config(config):
    config = config or {}
    try:
        port = int(config.get("port"))
    except (TypeError, ValueError):
        port = 0
    normalized = {
        "provider": config.get("provider"),
        "service": str(config.get("service") or "SMTP").strip(),
        "host": str(config.get("host") or "").strip(),
        "port": port,
        "security": str(config.get("security") or "").strip().casefold(),
        "username": str(config.get("username") or "").strip(),
        "password": str(config.get("password") or ""),
        "senderEmail": str(config.get("senderEmail") or "").strip(),
        "senderName": str(config.get("senderName") or "").strip(),
    }
    if not (
        normalized["provider"] == "smtp"
        and normalized["service"]
        and normalized["host"]
        and 1 <= normalized["port"] <= 65535
        and normalized["security"] in {"starttls", "ssl"}
        and normalized["username"]
        and normalized["password"]
        and EMAIL_PATTERN.fullmatch(normalized["senderEmail"])
        and normalized["senderName"]
    ):
        raise AuthEmailError("Authentication-email SMTP settings are incomplete.")
    return normalized


# @testable false
# @covered-by lagniappe/core/tools/auth_email.py::check_auth_email_connection
# @covered-by lagniappe/core/tools/auth_email.py::send_auth_email
# @reason shared SMTP connection setup is exercised through availability checks and delivery
@contextmanager
def _authenticated_smtp(
    smtp_config,
    *,
    smtp_factory=smtplib.SMTP,
    smtp_ssl_factory=smtplib.SMTP_SSL,
    tls_context=None,
):
    """Open and authenticate one configured SMTP connection."""
    context = tls_context or ssl.create_default_context()
    try:
        if smtp_config["security"] == "ssl":
            smtp_connection = smtp_ssl_factory(
                smtp_config["host"],
                smtp_config["port"],
                timeout=SMTP_TIMEOUT,
                context=context,
            )
        else:
            smtp_connection = smtp_factory(
                smtp_config["host"],
                smtp_config["port"],
                timeout=SMTP_TIMEOUT,
            )
        with smtp_connection as smtp:
            if smtp_config["security"] == "starttls":
                smtp.starttls(context=context)
            smtp.login(smtp_config["username"], smtp_config["password"])
            yield smtp
    except (OSError, smtplib.SMTPException) as error:
        raise AuthEmailError(
            "The SMTP service rejected or could not deliver the authentication email."
        ) from error


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_auth_email_connection_preflight_is_address_independent
# @features login
# @dimensions authentication-email smtp availability account-enumeration
def check_auth_email_connection(
    *,
    config=None,
    smtp_factory=smtplib.SMTP,
    smtp_ssl_factory=smtplib.SMTP_SSL,
    tls_context=None,
):
    """Confirm sender availability without consulting or sending to a recipient."""
    if config is None:
        from lagniappe import CONFIG

        config = getattr(CONFIG, "AUTH_EMAIL_CONFIG", None)
    smtp_config = _smtp_config(config)
    with _authenticated_smtp(
        smtp_config,
        smtp_factory=smtp_factory,
        smtp_ssl_factory=smtp_ssl_factory,
        tls_context=tls_context,
    ):
        pass
    return True


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_send_auth_email_supports_generic_smtp_transports
# @features login
# @dimensions authentication-email smtp tls
def send_auth_email(
    recipient,
    subject,
    text_body,
    html_body,
    *,
    config=None,
    smtp_factory=smtplib.SMTP,
    smtp_ssl_factory=smtplib.SMTP_SSL,
    tls_context=None,
):
    """Send one authentication message through the configured SMTP service."""
    if config is None:
        from lagniappe import CONFIG

        config = getattr(CONFIG, "AUTH_EMAIL_CONFIG", None)
    smtp_config = _smtp_config(config)
    recipient = str(recipient or "").strip()
    if not recipient:
        raise AuthEmailError("Authentication email requires a recipient.")

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = formataddr(
        (smtp_config["senderName"], smtp_config["senderEmail"])
    )
    message["Subject"] = str(subject or "").strip()
    message.set_content(str(text_body or ""))
    message.add_alternative(str(html_body or ""), subtype="html")

    with _authenticated_smtp(
        smtp_config,
        smtp_factory=smtp_factory,
        smtp_ssl_factory=smtp_ssl_factory,
        tls_context=tls_context,
    ) as smtp:
        smtp.send_message(message)
    return True


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_auth_action_message_escapes_content_and_links
# @features login
# @dimensions authentication-email action-link templates
def auth_action_message(action, app_name, action_url):
    """Build the plain-text and HTML bodies for one authentication action."""
    app_name = str(app_name or "").strip() or "Lagniappe"
    action_url = str(action_url or "").strip()
    if action == "verifyEmail":
        subject = f"Verify your email for {app_name}"
        introduction = f"Verify your email address to finish signing in to {app_name}."
        button = "Verify email"
    elif action == "resetPassword":
        subject = f"Reset your {app_name} password"
        introduction = f"Use this link to reset your password for {app_name}."
        button = "Reset password"
    else:
        raise AuthEmailError("Unsupported authentication email action.")

    text_body = (
        f"{introduction}\n\n{action_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    html_body = (
        f"<p>{escape(introduction)}</p>"
        f'<p><a href="{escape(action_url, quote=True)}">{escape(button)}</a></p>'
        "<p>If you did not request this, you can ignore this email.</p>"
    )
    return subject, text_body, html_body
