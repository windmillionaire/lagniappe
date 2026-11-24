"""Localhost one-shot browser secret vault for zero-terminal AI-assisted installs.

This module uses only the Python standard library for its HTTP server and binds
strictly to ``127.0.0.1`` on an ephemeral port with a 256-bit single-use URL
token, per-session CSRF token, strict Host/Origin validation, ``no-store``
headers, and immediate shutdown after one validated submission. Submitted secret
values live strictly in RAM during validation and persistence and are never
printed to stdout/stderr or written to workspace files.
"""

from __future__ import annotations

import hmac
import html
import json
import secrets
import threading
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

MAX_FORM_BODY_BYTES = 64 * 1024
DEFAULT_VAULT_TIMEOUT_SECONDS = 15 * 60


class VaultError(RuntimeError):
    """Secret-free error raised when the localhost secret vault fails or expires."""


@dataclass(frozen=True)
class VaultLink:
    """Clickable external provider console link displayed inside a vault section."""

    label: str
    url: str


@dataclass(frozen=True)
class VaultField:
    """One browser form input in the localhost secret vault."""

    name: str
    label: str
    secret: bool = True
    required: bool = True
    placeholder: str = ""
    help_text: str = ""
    autocomplete: str = "off"
    multiline: bool = False
    default: str = ""


@dataclass(frozen=True)
class VaultSection:
    """Grouped credentials for one provider (e.g., OAuth, Email, Redis, Sentry)."""

    section_id: str
    title: str
    description: str
    fields: tuple[VaultField, ...]
    links: tuple[VaultLink, ...] = ()


@dataclass(frozen=True)
class VaultSubmitResult:
    """Outcome of validating and applying a vault form submission in RAM."""

    ok: bool
    summary: tuple[str, ...] = ()
    error: str = ""
    field_errors: Mapping[str, str] = field(default_factory=dict)


_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("Cache-Control", "no-store, max-age=0"),
    ("Pragma", "no-cache"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    (
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'",
    ),
)


def _render_vault_page(
    *,
    title: str,
    subtitle: str,
    sections: Sequence[VaultSection],
    action_path: str,
    csrf_token: str,
    error: str = "",
    field_errors: Mapping[str, str] | None = None,
    preserved_non_secret: Mapping[str, str] | None = None,
) -> str:
    field_errors = field_errors or {}
    preserved_non_secret = preserved_non_secret or {}
    error_banner = (
        f'<div class="alert error" role="alert">{html.escape(error)}</div>'
        if error
        else ""
    )

    section_blocks: list[str] = []
    for section in sections:
        links_html = ""
        if section.links:
            rendered_links = " ".join(
                f'<a class="link-pill" href="{html.escape(link.url, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">'
                f"{html.escape(link.label)} ↗</a>"
                for link in section.links
            )
            links_html = f'<div class="links">{rendered_links}</div>'

        fields_html: list[str] = []
        for item in section.fields:
            field_id = f"field-{html.escape(item.name, quote=True)}"
            # Never re-populate secret values back into rendered HTML on retry.
            value = (
                ""
                if item.secret
                else preserved_non_secret.get(item.name, item.default)
            )
            req_attr = " required" if item.required else ""
            req_badge = (
                '<span class="req">Required</span>'
                if item.required
                else '<span class="opt">Optional</span>'
            )
            if item.multiline:
                control = (
                    f'<textarea id="{field_id}" name="{html.escape(item.name, quote=True)}" '
                    f'rows="4" placeholder="{html.escape(item.placeholder, quote=True)}"'
                    f"{req_attr}>{html.escape(value)}</textarea>"
                )
            else:
                input_type = "password" if item.secret else "text"
                control = (
                    f'<input id="{field_id}" type="{input_type}" '
                    f'name="{html.escape(item.name, quote=True)}" '
                    f'value="{html.escape(value, quote=True)}" '
                    f'placeholder="{html.escape(item.placeholder, quote=True)}" '
                    f'autocomplete="{html.escape(item.autocomplete, quote=True)}"'
                    f"{req_attr}>"
                )
            help_block = (
                f'<p class="help">{html.escape(item.help_text)}</p>'
                if item.help_text
                else ""
            )
            err_msg = field_errors.get(item.name)
            err_block = (
                f'<p class="field-error">{html.escape(err_msg)}</p>'
                if err_msg
                else ""
            )
            fields_html.append(
                f'<div class="field">'
                f'<label for="{field_id}">{html.escape(item.label)} {req_badge}</label>'
                f"{control}{help_block}{err_block}"
                f"</div>"
            )

        section_blocks.append(
            f'<section class="card">'
            f"<h2>{html.escape(section.title)}</h2>"
            f'<p class="desc">{html.escape(section.description)}</p>'
            f"{links_html}"
            f"{''.join(fields_html)}"
            f"</section>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 2rem 1rem 4rem; }}
  main {{ max-width: 680px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 0.5rem; }}
  .subtitle {{ color: #475569; margin: 0 0 1.5rem; line-height: 1.5; }}
  .notice {{ background: #eff6ff; border: 1px solid #bfdbfe; color: #1e3a8a; border-radius: 10px; padding: 0.9rem 1rem; margin-bottom: 1.25rem; font-size: 0.92rem; line-height: 1.45; }}
  .alert.error {{ background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; border-radius: 10px; padding: 0.9rem 1rem; margin-bottom: 1.25rem; font-weight: 500; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.25rem 1.4rem; margin-bottom: 1rem; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }}
  .card h2 {{ font-size: 1.1rem; margin: 0 0 0.35rem; }}
  .desc {{ color: #475569; font-size: 0.92rem; margin: 0 0 0.9rem; line-height: 1.45; }}
  .links {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }}
  .link-pill {{ display: inline-block; font-size: 0.85rem; text-decoration: none; color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; padding: 0.35rem 0.65rem; border-radius: 999px; }}
  .link-pill:hover {{ background: #dbeafe; }}
  .field {{ margin-bottom: 1rem; }}
  .field:last-child {{ margin-bottom: 0; }}
  label {{ display: flex; align-items: center; justify-content: space-between; font-size: 0.9rem; font-weight: 600; margin-bottom: 0.35rem; }}
  .req {{ font-size: 0.75rem; font-weight: 500; color: #9a3412; background: #ffedd5; padding: 0.1rem 0.45rem; border-radius: 999px; }}
  .opt {{ font-size: 0.75rem; font-weight: 500; color: #475569; background: #f1f5f9; padding: 0.1rem 0.45rem; border-radius: 999px; }}
  input, textarea {{ width: 100%; box-sizing: border-box; font: inherit; font-size: 0.94rem; padding: 0.6rem 0.75rem; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; }}
  input:focus, textarea:focus {{ outline: 2px solid #2563eb; border-color: #2563eb; }}
  .help {{ margin: 0.35rem 0 0; font-size: 0.82rem; color: #64748b; line-height: 1.4; }}
  .field-error {{ margin: 0.35rem 0 0; font-size: 0.84rem; color: #b91c1c; font-weight: 500; }}
  button {{ width: 100%; font: inherit; font-weight: 600; font-size: 1rem; padding: 0.8rem 1rem; border: none; border-radius: 10px; background: #0f766e; color: #fff; cursor: pointer; }}
  button:hover {{ background: #115e59; }}
</style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <p class="subtitle">{html.escape(subtitle)}</p>
  <div class="notice">
    <strong>Local-only one-shot vault:</strong> These credentials go directly from this browser page to Google Cloud Secret Manager / Identity Platform. They are never sent to your AI chat, printed to logs, or saved to workspace files.
  </div>
  {error_banner}
  <form method="post" action="{html.escape(action_path, quote=True)}">
    <input type="hidden" name="_csrf" value="{html.escape(csrf_token, quote=True)}">
    {''.join(section_blocks)}
    <button type="submit">Test &amp; Save Credentials</button>
  </form>
</main>
</body>
</html>"""


def _render_complete_page(title: str, summary: Sequence[str]) -> str:
    items = "".join(f"<li>{html.escape(line)}</li>" for line in summary)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title)} — Saved</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 3rem 1rem; }}
  main {{ max-width: 560px; margin: 0 auto; background: #fff; border: 1px solid #bbf7d0; border-radius: 12px; padding: 1.75rem; }}
  h1 {{ font-size: 1.35rem; color: #166534; margin: 0 0 0.75rem; }}
  p {{ color: #475569; line-height: 1.5; }}
  ul {{ padding-left: 1.25rem; line-height: 1.6; }}
</style>
</head>
<body>
<main>
  <h1>Credentials verified and saved</h1>
  <p>Your secrets were validated and written directly to Google Cloud. This local vault server has shut down; you can close this tab and return to your AI assistant.</p>
  <ul>{items}</ul>
</main>
</body>
</html>"""


class OneShotSecretVault:
    """Ephemeral ``127.0.0.1`` HTTP server for collecting and validating secrets once."""

    def __init__(
        self,
        sections: Sequence[VaultSection],
        on_submit: Callable[[dict[str, str]], VaultSubmitResult],
        *,
        title: str = "Lagniappe Setup — Secure Credential Vault",
        subtitle: str = "Enter your provider credentials below to validate and save them directly to Google Cloud.",
    ) -> None:
        if not sections:
            raise ValueError("OneShotSecretVault requires at least one VaultSection.")
        self.sections = tuple(sections)
        self.on_submit = on_submit
        self.title = title
        self.subtitle = subtitle
        self.token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._completed = threading.Event()
        self._consumed = False
        self._result: VaultSubmitResult | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0

    @property
    def port(self) -> int:
        return self._port

    @property
    def path(self) -> str:
        return f"/vault/{self.token}"

    @property
    def url(self) -> str:
        if not self._port:
            raise VaultError("Secret vault server has not been started.")
        return f"http://127.0.0.1:{self._port}{self.path}"

    def start(self) -> str:
        """Bind to 127.0.0.1 on an ephemeral port and start serving in a background thread."""
        vault = self
        known_fields = {
            item.name: item
            for section in self.sections
            for item in section.fields
        }

        class _VaultHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                # Never emit request paths (contains single-use token) or headers.
                return

            def _send_html(self, status: HTTPStatus, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(int(status))
                for header_name, header_value in _SECURITY_HEADERS:
                    self.send_header(header_name, header_value)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)

            def _send_plain(self, status: HTTPStatus, message: str) -> None:
                encoded = message.encode("utf-8")
                self.send_response(int(status))
                for header_name, header_value in _SECURITY_HEADERS:
                    self.send_header(header_name, header_value)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)

            def _expected_host(self) -> str:
                return f"127.0.0.1:{vault.port}"

            def _validate_host_and_path(self) -> bool:
                host = str(self.headers.get("Host") or "").strip()
                if not hmac.compare_digest(host, self._expected_host()):
                    self._send_plain(HTTPStatus.FORBIDDEN, "Invalid Host header.")
                    return False
                if not hmac.compare_digest(self.path, vault.path):
                    self._send_plain(HTTPStatus.NOT_FOUND, "Not found.")
                    return False
                return True

            def _validate_origin(self) -> bool:
                expected_origin = f"http://{self._expected_host()}"
                origin = self.headers.get("Origin")
                if origin is not None and origin.strip().casefold() != "null":
                    return hmac.compare_digest(origin.strip(), expected_origin)
                referer = self.headers.get("Referer")
                if referer is not None:
                    expected_prefix = f"{expected_origin}{vault.path}"
                    return hmac.compare_digest(referer.strip(), expected_prefix)
                return False

            def do_GET(self) -> None:
                if not self._validate_host_and_path():
                    return
                with vault._lock:
                    consumed = vault._consumed
                if consumed:
                    self._send_plain(
                        HTTPStatus.GONE,
                        "This one-shot vault session has already completed.",
                    )
                    return
                page = _render_vault_page(
                    title=vault.title,
                    subtitle=vault.subtitle,
                    sections=vault.sections,
                    action_path=vault.path,
                    csrf_token=vault.csrf_token,
                )
                self._send_html(HTTPStatus.OK, page)

            def do_POST(self) -> None:
                if not self._validate_host_and_path():
                    return
                if not self._validate_origin():
                    self._send_plain(
                        HTTPStatus.FORBIDDEN, "Invalid request Origin or Referer."
                    )
                    return
                content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
                if content_type != "application/x-www-form-urlencoded":
                    self._send_plain(
                        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                        "Unsupported Content-Type.",
                    )
                    return
                try:
                    content_length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    self._send_plain(HTTPStatus.BAD_REQUEST, "Invalid Content-Length.")
                    return
                if content_length <= 0 or content_length > MAX_FORM_BODY_BYTES:
                    self._send_plain(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        "Form submission is empty or exceeds the size limit.",
                    )
                    return
                raw_body = self.rfile.read(content_length)
                parsed = parse_qs(
                    raw_body.decode("utf-8", errors="replace"),
                    keep_blank_values=True,
                )
                submitted_csrf = (parsed.get("_csrf") or [""])[0]
                if not hmac.compare_digest(submitted_csrf, vault.csrf_token):
                    self._send_plain(HTTPStatus.FORBIDDEN, "Invalid CSRF token.")
                    return

                values: dict[str, str] = {}
                preserved_non_secret: dict[str, str] = {}
                missing_errors: dict[str, str] = {}
                for field_name, spec in known_fields.items():
                    raw_val = (parsed.get(field_name) or [""])[0].strip()
                    values[field_name] = raw_val
                    if not spec.secret:
                        preserved_non_secret[field_name] = raw_val
                    if spec.required and not raw_val:
                        missing_errors[field_name] = f"{spec.label} is required."

                with vault._lock:
                    if vault._consumed:
                        self._send_plain(
                            HTTPStatus.GONE,
                            "This one-shot vault session has already completed.",
                        )
                        return

                if missing_errors:
                    page = _render_vault_page(
                        title=vault.title,
                        subtitle=vault.subtitle,
                        sections=vault.sections,
                        action_path=vault.path,
                        csrf_token=vault.csrf_token,
                        error="Please fill in all required fields and try again.",
                        field_errors=missing_errors,
                        preserved_non_secret=preserved_non_secret,
                    )
                    self._send_html(HTTPStatus.BAD_REQUEST, page)
                    return

                try:
                    outcome = vault.on_submit(values)
                except Exception as error:
                    outcome = VaultSubmitResult(
                        ok=False,
                        error=(
                            "Credential validation failed "
                            f"({type(error).__name__}). Check your entries and try again."
                        ),
                    )
                finally:
                    values.clear()

                if not outcome.ok:
                    page = _render_vault_page(
                        title=vault.title,
                        subtitle=vault.subtitle,
                        sections=vault.sections,
                        action_path=vault.path,
                        csrf_token=vault.csrf_token,
                        error=outcome.error or "Validation failed. Please check your entries.",
                        field_errors=outcome.field_errors,
                        preserved_non_secret=preserved_non_secret,
                    )
                    self._send_html(HTTPStatus.BAD_REQUEST, page)
                    return

                with vault._lock:
                    vault._consumed = True
                    vault._result = outcome

                self._send_html(
                    HTTPStatus.OK,
                    _render_complete_page(vault.title, outcome.summary),
                )
                vault._completed.set()
                threading.Thread(target=vault.stop, daemon=True).start()

        server = ThreadingHTTPServer(("127.0.0.1", 0), _VaultHandler)
        server.daemon_threads = True
        self._server = server
        self._port = int(server.server_address[1])
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return self.url

    def wait(self, timeout: float = DEFAULT_VAULT_TIMEOUT_SECONDS) -> VaultSubmitResult:
        """Wait for one validated submission, then guarantee the server is closed."""
        try:
            finished = self._completed.wait(timeout=timeout)
            if not finished or self._result is None:
                raise VaultError(
                    "Timed out waiting for credentials in the local browser vault."
                )
            return self._result
        finally:
            self.stop()

    def stop(self) -> None:
        """Shut down and close the localhost socket cleanly."""
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)


def build_install_vault_sections(
    settings: Mapping[str, Any],
    *,
    include_oauth: bool = False,
    include_auth_email: bool = False,
    include_redis: bool = False,
    include_sentry: bool = False,
    auth_email_provider: str = "gmail",
) -> tuple[VaultSection, ...]:
    """Build declarative browser vault sections with clickable provider console links."""
    project_id = str(settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    app_origin = (
        f"https://{settings['CUSTOM_DOMAIN']}"
        if settings.get("CUSTOM_DOMAIN")
        else str(settings.get("APP_URL") or "").strip()
    )
    redirect_uri = str(settings.get("GOOGLE_LOGIN_URI") or "").strip()
    sections: list[VaultSection] = []

    if include_oauth:
        clients_url = (
            f"https://console.cloud.google.com/auth/clients?project={project_id}"
            if project_id
            else "https://console.cloud.google.com/auth/clients"
        )
        sections.append(
            VaultSection(
                section_id="google_oauth",
                title="Google Sign-In OAuth Web Client",
                description=(
                    "In Google Auth Platform, finish the one-time Branding / Audience "
                    "(External) setup if prompted, then create a Web application OAuth "
                    f"client with Authorized JavaScript origin {app_origin or '(your app URL)'} "
                    f"and Authorized redirect URI {redirect_uri or '(your login callback)'}. "
                    "Download the client JSON and paste its contents below."
                ),
                links=(VaultLink("Open Google Auth Platform Clients", clients_url),),
                fields=(
                    VaultField(
                        name="oauth_credentials_json",
                        label="OAuth Web Client JSON",
                        secret=True,
                        required=True,
                        multiline=True,
                        placeholder='{"web": {"client_id": "...", "client_secret": "..."}}',
                        help_text=(
                            "Paste the full downloaded JSON from Google Auth Platform. "
                            "The Client Secret is sent directly to Identity Platform and never stored in Lagniappe files."
                        ),
                    ),
                ),
            )
        )

    if include_auth_email:
        provider = str(auth_email_provider or "gmail").strip().casefold()
        if provider == "resend":
            email_links = (
                VaultLink("Open Resend API Keys", "https://resend.com/api-keys"),
                VaultLink("Open Resend Domains", "https://resend.com/domains"),
            )
            secret_label = "Resend SMTP API Key"
            secret_placeholder = "re_..."
            secret_help = "Used for authenticated Resend SMTP delivery (smtp.resend.com:465)."
        elif provider == "custom_smtp":
            email_links = ()
            secret_label = "SMTP Password"
            secret_placeholder = "SMTP password"
            secret_help = "Stored directly in GCP Secret Manager under AUTH_EMAIL_CONFIG.password."
        else:
            email_links = (
                VaultLink(
                    "Create Gmail App Password",
                    "https://accounts.google.com/AccountChooser?continue=https%3A%2F%2Fmyaccount.google.com%2Fapppasswords",
                ),
            )
            secret_label = "Gmail 16-character App Password"
            secret_placeholder = "xxxx xxxx xxxx xxxx"
            secret_help = "Spaces are stripped automatically. Tested live via SMTP before saving."

        sections.append(
            VaultSection(
                section_id="auth_email",
                title="Authentication Email Credential",
                description="Used to send sign-in links and password resets. Tested live before saving.",
                links=email_links,
                fields=(
                    VaultField(
                        name="auth_email_password",
                        label=secret_label,
                        secret=True,
                        required=True,
                        placeholder=secret_placeholder,
                        help_text=secret_help,
                    ),
                ),
            )
        )

    if include_redis:
        sections.append(
            VaultSection(
                section_id="redis",
                title="Redis Cloud Connection",
                description=(
                    "Create a Redis Cloud database on Google Cloud in the same region "
                    "with data eviction policy set to volatile-ttl, click Connect → "
                    "Redis CLI, and paste the copied command below."
                ),
                links=(VaultLink("Open Redis Cloud Console", "https://cloud.redis.io/"),),
                fields=(
                    VaultField(
                        name="redis_cli_command",
                        label="Redis CLI Command",
                        secret=True,
                        required=True,
                        placeholder="redis-cli -u redis://default:PASSWORD@HOST:PORT",
                        help_text="Tested live before saving; host, port, and password are parsed automatically.",
                    ),
                ),
            )
        )

    if include_sentry:
        sections.append(
            VaultSection(
                section_id="sentry",
                title="Sentry Error Monitoring DSN",
                description="Optional server DSN stored in Secret Manager (plus optional browser DSN).",
                links=(VaultLink("Open Sentry", "https://sentry.io/"),),
                fields=(
                    VaultField(
                        name="sentry_dsn",
                        label="Sentry Server DSN",
                        secret=True,
                        required=True,
                        placeholder="https://<key>@o0.ingest.sentry.io/<project>",
                    ),
                    VaultField(
                        name="sentry_js_dsn",
                        label="Sentry Browser DSN (optional; defaults to server DSN)",
                        secret=False,
                        required=False,
                        default=str(settings.get("SENTRY_JS_DSN") or ""),
                    ),
                ),
            )
        )

    return tuple(sections)


def parse_oauth_vault_inputs(values: Mapping[str, str]) -> tuple[str, str]:
    """Extract and validate Google OAuth Web client_id + client_secret from vault inputs."""
    raw_json = str(values.get("oauth_credentials_json") or "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as error:
            raise ValueError("OAuth credentials JSON is not valid JSON.") from error
        web = parsed.get("web") if isinstance(parsed, dict) else None
        if not isinstance(web, dict):
            raise ValueError(
                "OAuth credentials JSON must be a 'Web application' client containing a 'web' object."
            )
        client_id = str(web.get("client_id") or "").strip()
        client_secret = str(web.get("client_secret") or "").strip()
    else:
        client_id = str(values.get("oauth_client_id") or "").strip()
        client_secret = str(values.get("oauth_client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ValueError(
            "Provide either the downloaded Web OAuth JSON or both Client ID and Client Secret."
        )
    return client_id, client_secret


def run_secret_vault(
    sections: Sequence[VaultSection],
    on_submit: Callable[[dict[str, str]], VaultSubmitResult],
    *,
    open_browser: bool = True,
    timeout: float = DEFAULT_VAULT_TIMEOUT_SECONDS,
    on_ready: Callable[[str], None] | None = None,
    title: str = "Lagniappe Setup — Secure Credential Vault",
    subtitle: str = "Enter your provider credentials below to validate and save them directly to Google Cloud.",
) -> VaultSubmitResult:
    """Start the one-shot browser vault, open the URL, and wait for a validated submit."""
    vault = OneShotSecretVault(
        sections,
        on_submit,
        title=title,
        subtitle=subtitle,
    )
    url = vault.start()
    if on_ready is not None:
        on_ready(url)
    if open_browser:
        with suppress(webbrowser.Error):
            webbrowser.open_new_tab(url)
    return vault.wait(timeout=timeout)
