"""Signed inbound-email boundary and handoff to saved AI report workflows."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import base64
import binascii
from email import policy
from email.parser import Parser
from html import escape
import hashlib
import hmac
import json
import re
import tempfile
import time
from urllib.parse import quote, urlparse
import uuid

from bs4 import BeautifulSoup
import requests
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from config.ai_email import normalize_email_address


RESEND_API_ROOT = "https://api.resend.com"
RESEND_TIMEOUT = 15
SVIX_TOLERANCE_SECONDS = 300
REPLY_MARKER = "--- Reply above this line to start a new report ---"
SPOOL_MEMORY_BYTES = 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
_PROVIDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_CONTENT_TYPE_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$"
)
_AUTH_PARAMETER_PATTERN = re.compile(
    r"(?i)\b(header\.from|header\.d|smtp\.mailfrom)\s*=\s*"
    r'(?:"([^"\r\n]+)"|([^\s;()]+))'
)
_INLINE_IMAGE_MARKER_PATTERN = re.compile(
    r"\[\s*image\s*:\s*([^\]\r\n]+?)\s*\]", re.IGNORECASE
)
_IGNORED_INLINE_CONTAINER_PATTERN = re.compile(
    r"(?:^|[\s_-])(?:gmail[-_]?signature|apple[-_]?signature|signature|"
    r"gmail[-_]?quote|yahoo[-_]?quoted|quoted|moz[-_]?cite)(?:$|[\s_-])",
    re.IGNORECASE,
)


class AIEmailWebhookError(ValueError):
    """Raised when a webhook cannot cross the signed request boundary."""


class AIEmailProviderError(RuntimeError):
    """Raised for a bounded provider operation that should be retried."""


# @testable infrastructure
class AIEmailRejection(ValueError):
    """A safe, correctable submission rejection for a known user."""

    def __init__(self, code, message, *, silent=False):
        super().__init__(message)
        self.code = str(code)
        self.public_message = str(message)
        self.silent = bool(silent)


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_inbound_attachment_disposition_overrides_content_id
# @features ai-email
# @dimensions attachments
@dataclass(frozen=True)
class InboundAttachment:
    """Provider-neutral attachment metadata with no signed URL."""

    id: str
    filename: str
    content_type: str
    size: int
    content_disposition: str | None = None
    content_id: str | None = None
    include_inline: bool = False

    # @testable true
    # @tests tests_unit/test_028_ai_email.py::test_inbound_attachment_disposition_overrides_content_id
    # @features ai-email
    # @dimensions attachments content-disposition content-id inline
    @property
    def inline(self):
        if self.content_disposition:
            return self.content_disposition == "inline"
        return bool(self.content_id)

    @property
    def submitted(self):
        """Return whether this part should enter the report attachment pipeline."""
        return not self.inline or self.include_inline

    def job_record(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
        }

    def display_record(self):
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
        }


@dataclass(frozen=True)
class InboundMessage:
    """Provider-neutral received message used by submission policy."""

    provider_message_id: str
    sender: str
    recipients: tuple[str, ...]
    subject: str
    text_body: str
    headers: dict
    received_at: str
    attachments: tuple[InboundAttachment, ...]


@dataclass(frozen=True)
class AIEmailSubmissionResult:
    """Bounded result returned to the webhook route."""

    state: str
    code: str | None = None
    report: object | None = None


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::verify_svix_signature
# @reason case-insensitive header lookup is exercised through signature verification
def _header(headers, name):
    wanted = name.casefold()
    for key, value in (headers or {}).items():
        if str(key).casefold() == wanted:
            return str(value or "")
    return ""


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::authentication_results_candidates
# @reason multi-value header normalization is owned by authentication telemetry
def _header_values(headers, name):
    if not isinstance(headers, dict):
        return []
    wanted = name.casefold()
    values = []
    for key, value in headers.items():
        if str(key).casefold() != wanted:
            continue
        if isinstance(value, list):
            values.extend(str(item) for item in value if item is not None)
        elif value is not None:
            values.append(str(value))
    return values


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::verify_svix_signature
# @reason signing-secret decoding is exercised through the signed webhook boundary
def _svix_secret_bytes(secret):
    encoded = str(secret or "").strip()
    if encoded.startswith("whsec_"):
        encoded = encoded[6:]
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise AIEmailWebhookError("Webhook signing secret is invalid.") from error


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_svix_signature_verification_uses_raw_body_timestamp_and_any_v1_signature
# @tests tests_unit/test_028_ai_email.py::test_svix_signature_verification_rejects_invalid_or_stale_requests
# @features ai-email
# @dimensions webhook signature raw-body timestamp rotation
# @pairs ai-email:webhook ai-email:signature ai-email:raw-body ai-email:timestamp ai-email:rotation
# @pairs webhook:webhook webhook:signature webhook:raw-body webhook:timestamp webhook:rotation
def verify_svix_signature(
    raw_body,
    headers,
    webhook_secret,
    *,
    now=None,
    tolerance_seconds=SVIX_TOLERANCE_SECONDS,
):
    """Verify a Resend/Svix signature against the untouched request bytes."""
    if not isinstance(raw_body, bytes):
        raise AIEmailWebhookError("Webhook body must be raw bytes.")
    event_id = _header(headers, "svix-id").strip()
    timestamp_text = _header(headers, "svix-timestamp").strip()
    signature_header = _header(headers, "svix-signature").strip()
    if not event_id or not timestamp_text or not signature_header:
        raise AIEmailWebhookError("Required webhook signature headers are missing.")
    try:
        timestamp = int(timestamp_text)
    except ValueError as error:
        raise AIEmailWebhookError("Webhook timestamp is invalid.") from error
    current_time = int(time.time() if now is None else now)
    if abs(current_time - timestamp) > tolerance_seconds:
        raise AIEmailWebhookError("Webhook timestamp is outside the allowed window.")

    signed = (
        event_id.encode("utf-8")
        + b"."
        + timestamp_text.encode("ascii")
        + b"."
        + raw_body
    )
    expected = base64.b64encode(
        hmac.new(_svix_secret_bytes(webhook_secret), signed, hashlib.sha256).digest()
    ).decode("ascii")
    candidates = []
    for item in signature_header.split():
        version, separator, signature = item.partition(",")
        if separator and version == "v1" and signature:
            candidates.append(signature)
    if not candidates or not any(
        hmac.compare_digest(expected, candidate) for candidate in candidates
    ):
        raise AIEmailWebhookError("Webhook signature is invalid.")
    return event_id


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_parse_resend_event_rejects_malformed_shapes
# @features ai-email
# @dimensions webhook event-shape json
def parse_resend_event(raw_body):
    """Decode one signed Resend event without retaining its raw payload."""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AIEmailWebhookError("Webhook body is not valid UTF-8 JSON.") from error
    if not isinstance(payload, dict):
        raise AIEmailWebhookError("Webhook event must be an object.")
    event_type = payload.get("type")
    data = payload.get("data")
    if not isinstance(event_type, str) or not isinstance(data, dict):
        raise AIEmailWebhookError("Webhook event shape is invalid.")
    return {"type": event_type, "data": data}


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::authentication_results_candidates
# @reason RFC comment removal is private authentication-header normalization
def _strip_rfc_comments(value):
    output = []
    depth = 0
    escaped = False
    quoted = False
    for character in str(value or ""):
        if escaped:
            if depth == 0:
                output.append(character)
            escaped = False
            continue
        if character == "\\":
            escaped = True
            if depth == 0:
                output.append(character)
            continue
        if character == '"' and depth == 0:
            quoted = not quoted
            output.append(character)
            continue
        if not quoted and character == "(":
            depth += 1
            continue
        if not quoted and character == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            output.append(character)
    return "".join(output)


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::authentication_results_candidates
# @reason domain canonicalization is owned by aligned authentication parsing
def _parameter_domain(value):
    raw = str(value or "").strip().strip("<>")
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    try:
        return raw.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return ""


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_authentication_results_candidates_require_aligned_dmarc_pass
# @tests tests_unit/test_028_ai_email.py::test_authentication_results_candidates_handle_folding_comments_and_multiple_values
# @features ai-email
# @dimensions sender-auth authentication-results dmarc alignment telemetry
# @pairs ai-email:sender-auth ai-email:authentication-results ai-email:dmarc
# @pairs ai-email:alignment ai-email:telemetry
# @pairs sender-auth:sender-auth sender-auth:authentication-results
# @pairs sender-auth:dmarc sender-auth:alignment sender-auth:telemetry
def authentication_results_candidates(headers, visible_from_domain):
    """Return authserv IDs reporting aligned DMARC pass as optional telemetry."""
    expected_domain = _parameter_domain(visible_from_domain)
    if not expected_domain:
        return ()
    candidates = []
    for value in _header_values(headers, "authentication-results"):
        unfolded = re.sub(r"\r?\n[ \t]+", " ", value)
        parts = [part.strip() for part in _strip_rfc_comments(unfolded).split(";")]
        authserv_id = (parts[0].split() or [""])[0].casefold()
        if not _PROVIDER_ID_PATTERN.fullmatch(authserv_id):
            continue
        for part in parts[1:]:
            result = re.match(r"(?i)^\s*dmarc\s*=\s*pass\b", part)
            if not result:
                continue
            parameters = {
                match.group(1).casefold(): match.group(2) or match.group(3) or ""
                for match in _AUTH_PARAMETER_PATTERN.finditer(part)
            }
            if _parameter_domain(parameters.get("header.from")) == expected_domain:
                if authserv_id not in candidates:
                    candidates.append(authserv_id)
                break
    return tuple(candidates)


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::ResendAIEmailClient
# @reason provider identifier validation is exercised through the runtime adapter
def _provider_id(value, label):
    identifier = str(value or "").strip()
    if not _PROVIDER_ID_PATTERN.fullmatch(identifier):
        raise AIEmailProviderError(f"Resend {label} ID is invalid.")
    return identifier


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_resend_runtime_client_retrieves_with_full_key_and_sends_with_scoped_key
# @features ai-email
# @dimensions provider-adapter authorization retrieval attachments outbound-email idempotency
# @pairs ai-email:provider-adapter ai-email:authorization ai-email:retrieval
# @pairs ai-email:attachments ai-email:outbound-email ai-email:idempotency
# @pairs provider-adapter:provider-adapter provider-adapter:authorization
# @pairs provider-adapter:retrieval provider-adapter:attachments
# @pairs provider-adapter:outbound-email provider-adapter:idempotency
class ResendAIEmailClient:
    """Small runtime Resend adapter for received messages, files, and feedback."""

    def __init__(
        self,
        inbound_api_key,
        sending_api_key,
        *,
        request=None,
        download_request=None,
    ):
        self.inbound_api_key = inbound_api_key
        self.sending_api_key = sending_api_key
        self.request = request or requests.request
        self.download_request = download_request or requests.get

    def _request(self, method, path, api_key, *, json_data=None, headers=None):
        request_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Lagniappe-AI-Email/1",
        }
        request_headers.update(headers or {})
        try:
            response = self.request(
                method,
                f"{RESEND_API_ROOT}{path}",
                headers=request_headers,
                json=json_data,
                timeout=RESEND_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            raise AIEmailProviderError("Resend API request was unavailable.") from error
        if not response.ok:
            raise AIEmailProviderError(
                f"Resend API returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise AIEmailProviderError("Resend API returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise AIEmailProviderError("Resend API returned an invalid object.")
        return payload

    def retrieve_received_email(self, email_id):
        email_id = _provider_id(email_id, "received-email")
        return self._request(
            "GET",
            f"/emails/receiving/{quote(email_id, safe='')}",
            self.inbound_api_key,
        )

    def list_received_attachments(self, email_id):
        email_id = _provider_id(email_id, "received-email")
        payload = self._request(
            "GET",
            f"/emails/receiving/{quote(email_id, safe='')}/attachments",
            self.inbound_api_key,
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise AIEmailProviderError("Resend returned an invalid attachment list.")
        return data

    def retrieve_received_attachment(self, email_id, attachment_id):
        email_id = _provider_id(email_id, "received-email")
        attachment_id = _provider_id(attachment_id, "attachment")
        return self._request(
            "GET",
            f"/emails/receiving/{quote(email_id, safe='')}/attachments/"
            f"{quote(attachment_id, safe='')}",
            self.inbound_api_key,
        )

    def download_received_attachment(
        self,
        email_id,
        attachment,
        *,
        max_file_bytes,
        max_total_bytes,
        total_bytes=0,
    ):
        """Return a bounded spooled upload without exposing the signed URL."""
        metadata = self.retrieve_received_attachment(email_id, attachment["id"])
        download_url = str(metadata.get("download_url") or "").strip()
        parsed = urlparse(download_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not (
                parsed.hostname == "cdn.resend.app"
                or parsed.hostname == "resend.com"
                or parsed.hostname.endswith(".resend.com")
            )
        ):
            raise AIEmailProviderError("Resend returned an invalid attachment URL.")
        spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
        actual = 0
        response = None
        try:
            try:
                response = self.download_request(
                    download_url,
                    stream=True,
                    timeout=RESEND_TIMEOUT,
                )
            except (requests.ConnectionError, requests.Timeout) as error:
                raise AIEmailProviderError(
                    "Resend attachment download was unavailable."
                ) from error
            if not response.ok:
                raise AIEmailProviderError(
                    f"Resend attachment download returned HTTP {response.status_code}."
                )
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                actual += len(chunk)
                if actual > max_file_bytes or total_bytes + actual > max_total_bytes:
                    raise AIEmailRejection(
                        "attachment_contract",
                        "One or more attachments exceeded the AI email size limit.",
                    )
                spool.write(chunk)
            if actual <= 0:
                raise AIEmailRejection(
                    "attachment_contract",
                    "Empty attachments cannot be submitted by email.",
                )
            spool.seek(0)
            filename = secure_filename(attachment.get("filename") or "") or "attachment.bin"
            upload = FileStorage(
                stream=spool,
                filename=filename,
                content_type=(
                    attachment.get("content_type") or "application/octet-stream"
                ),
                content_length=actual,
            )
            return upload, actual
        except Exception:
            spool.close()
            raise
        finally:
            if response is not None and hasattr(response, "close"):
                response.close()

    def send_email(self, payload, *, idempotency_key):
        return self._request(
            "POST",
            "/emails",
            self.sending_api_key,
            json_data=payload,
            headers={"Idempotency-Key": idempotency_key},
        )


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_inbound_message_normalization_routes_alias_and_strips_reply_marker
# @features ai-email
# @dimensions sender routing reply-marker html-fallback
def parse_mailbox(value):
    """Return one normalized mailbox while preserving exact local-part spelling."""
    if not isinstance(value, str) or any(ord(character) < 32 for character in value):
        raise AIEmailRejection("sender_unknown", "Sender address is invalid.", silent=True)
    try:
        header = Parser(policy=policy.default).parsestr(f"From: {value}\n\n")["From"]
        addresses = tuple(header.addresses)
        named_groups = tuple(
            group for group in header.groups if group.display_name is not None
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        addresses = ()
        named_groups = ()
        header = None
    if (
        header is None
        or header.defects
        or len(addresses) != 1
        or named_groups
        or not addresses[0].addr_spec
    ):
        raise AIEmailRejection("sender_unknown", "Sender address is invalid.", silent=True)
    try:
        return normalize_email_address(addresses[0].addr_spec)
    except ValueError as error:
        raise AIEmailRejection(
            "sender_unknown", "Sender address is invalid.", silent=True
        ) from error


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::normalize_resend_message
# @reason subject canonicalization is part of provider message normalization
def _normalize_subject(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in text
    )
    return " ".join(text.split()).strip()


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::normalize_message_body
# @reason HTML fallback conversion is owned by message-body normalization
def _html_to_text(value):
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_inbound_message_normalization_routes_alias_and_strips_reply_marker
# @features ai-email
# @dimensions reply-marker html-fallback
def normalize_message_body(text, html=None):
    """Normalize provider text without broad reply or quote heuristics."""
    source = text if isinstance(text, str) and text.strip() else _html_to_text(html)
    source = str(source or "").replace("\r\n", "\n").replace("\r", "\n")
    source = "".join(
        character
        for character in source
        if character in {"\n", "\t"} or (ord(character) >= 32 and ord(character) != 127)
    )
    marker_index = source.find(REPLY_MARKER)
    if marker_index >= 0:
        source = source[:marker_index]
    lines = [line.rstrip(" \t") for line in source.split("\n")]
    normalized = "\n".join(lines).strip(" \t\n")
    return re.sub(r"\n{4,}", "\n\n\n", normalized)


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_select_inline_attachments
# @reason private canonicalization exercised by inline attachment selection
def _attachment_reference_key(value):
    return secure_filename(str(value or "")).casefold()


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_select_inline_attachments
# @reason private canonicalization exercised by inline attachment selection
def _content_id_key(value):
    key = str(value or "").strip()
    if key[:4].casefold() == "cid:":
        key = key[4:]
    return key.strip("<> ").casefold()


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_select_inline_attachments
# @reason private HTML classification exercised by inline attachment selection
def _ignored_inline_image(image):
    for node in (image, *image.parents):
        if getattr(node, "name", None) == "blockquote":
            return True
        if not hasattr(node, "attrs"):
            continue
        attributes = []
        for name in ("id", "class", "data-smartmail"):
            value = node.attrs.get(name)
            if isinstance(value, (list, tuple)):
                attributes.extend(str(item) for item in value)
            elif value:
                attributes.append(str(value))
        if _IGNORED_INLINE_CONTAINER_PATTERN.search(" ".join(attributes)):
            return True
    return False


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_select_inline_attachments
# @reason private HTML matching exercised by inline attachment selection
def _matching_inline_images(attachment, html):
    raw_html = str(html or "")
    marker_index = raw_html.find(REPLY_MARKER)
    if marker_index >= 0:
        raw_html = raw_html[:marker_index]
    if not raw_html.strip():
        return ()

    filename = _attachment_reference_key(attachment.filename)
    content_id = _content_id_key(attachment.content_id)
    matches = []
    soup = BeautifulSoup(raw_html, "html.parser")
    for image in soup.find_all("img"):
        source = str(image.get("src") or "").strip()
        source_id = (
            _content_id_key(source) if source.casefold().startswith("cid:") else ""
        )
        alternate = _attachment_reference_key(image.get("alt"))
        if (content_id and source_id == content_id) or (
            filename and alternate == filename
        ):
            matches.append(image)
    return tuple(matches)


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_inline_attachment_selection_keeps_user_content_and_filters_signature_art
# @features ai-email
# @dimensions attachments inline image-only signature quoted-content routing
def _select_inline_attachments(attachments, body, html):
    """Select intentional inline content while filtering signature and reply art."""
    ordinary = tuple(item for item in attachments if not item.inline)
    inline = tuple(item for item in attachments if item.inline)
    if not inline:
        return frozenset()

    marker_filenames = {
        _attachment_reference_key(match)
        for match in _INLINE_IMAGE_MARKER_PATTERN.findall(body or "")
    }
    meaningful_body = _INLINE_IMAGE_MARKER_PATTERN.sub("", body or "").strip()
    image_only_message = not meaningful_body and not ordinary
    selected = set()
    for attachment in inline:
        matching_images = _matching_inline_images(attachment, html)
        if any(not _ignored_inline_image(image) for image in matching_images):
            selected.add(attachment.id)
            continue
        if matching_images:
            continue
        if _attachment_reference_key(attachment.filename) in marker_filenames:
            selected.add(attachment.id)
            continue
        if image_only_message:
            selected.add(attachment.id)
    return frozenset(selected)


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::normalize_resend_message
# @reason alias routing is exercised through provider message normalization
def _recognized_tool(recipients, config):
    if not isinstance(recipients, (list, tuple)):
        raise AIEmailRejection("route_invalid", "AI email recipient is invalid.")
    recognized = []
    for value in recipients:
        try:
            mailbox = parse_mailbox(value)
        except AIEmailRejection:
            continue
        for tool, alias in config["aliases"].items():
            if mailbox.casefold() == f"{alias}@{config['domain']}".casefold():
                recognized.append(tool)
    unique = tuple(dict.fromkeys(recognized))
    if len(unique) != 1:
        raise AIEmailRejection(
            "route_invalid",
            "Send the message to exactly one Lagniappe AI email address.",
        )
    return unique[0]


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::normalize_resend_message
# @reason attachment canonicalization is exercised through message normalization
def _normalize_attachment(value):
    if not isinstance(value, dict):
        raise AIEmailRejection(
            "attachment_contract", "Resend returned invalid attachment metadata."
        )
    identifier = _provider_id(value.get("id"), "attachment")
    filename = secure_filename(str(value.get("filename") or "")) or "attachment.bin"
    content_type = (
        str(value.get("content_type") or "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .casefold()
    )
    if not _CONTENT_TYPE_PATTERN.fullmatch(content_type):
        content_type = "application/octet-stream"
    disposition = str(value.get("content_disposition") or "").casefold() or None
    content_id = str(value.get("content_id") or "").strip() or None
    try:
        size = int(value.get("size"))
    except (TypeError, ValueError) as error:
        raise AIEmailRejection(
            "attachment_contract", "Attachment sizes could not be verified."
        ) from error
    return InboundAttachment(
        id=identifier,
        filename=filename,
        content_type=content_type,
        size=size,
        content_disposition=disposition,
        content_id=content_id,
    )


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_inbound_message_normalization_routes_alias_and_strips_reply_marker
# @tests tests_unit/test_028_ai_email.py::test_inline_attachment_selection_keeps_user_content_and_filters_signature_art
# @features ai-email
# @dimensions attachments inline
def normalize_resend_message(message, attachments, config):
    """Validate a Resend response and return only provider-neutral fields."""
    if not isinstance(message, dict):
        raise AIEmailProviderError("Resend returned an invalid received email.")
    email_id = _provider_id(message.get("id"), "received-email")
    recipients = message.get("to")
    if not isinstance(recipients, list):
        raise AIEmailProviderError("Resend returned invalid recipients.")
    tool = _recognized_tool(recipients, config)
    sender = parse_mailbox(message.get("from"))
    subject = _normalize_subject(message.get("subject"))
    body = normalize_message_body(message.get("text"), message.get("html"))
    headers = message.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    normalized_attachments = tuple(_normalize_attachment(item) for item in attachments)
    selected_inline = _select_inline_attachments(
        normalized_attachments,
        body,
        message.get("html"),
    )
    normalized_attachments = tuple(
        replace(item, include_inline=item.id in selected_inline)
        for item in normalized_attachments
    )
    received_at = _normalize_subject(message.get("created_at"))[:64]
    return InboundMessage(
        provider_message_id=email_id,
        sender=sender,
        recipients=tuple(str(item) for item in recipients),
        subject=subject,
        text_body=body,
        headers=headers,
        received_at=received_at,
        attachments=normalized_attachments,
    ), tool


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_preflight_submission
# @reason automated-message classification is owned by submission preflight
def _automated_message(message):
    headers = message.headers
    auto_submitted = _header(headers, "auto-submitted").strip().casefold()
    if auto_submitted and auto_submitted != "no":
        return True
    if any(
        _header(headers, name).strip()
        for name in (
            "list-id",
            "list-post",
            "list-unsubscribe",
            "x-auto-response-suppress",
            "x-autoreply",
            "x-autorespond",
        )
    ):
        return True
    precedence = _header(headers, "precedence").strip().casefold()
    if precedence in {"bulk", "list", "junk"}:
        return True
    content_type = _header(headers, "content-type").casefold()
    return "multipart/report" in content_type or "message/delivery-status" in content_type


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_preflight_submission
# @reason instruction assembly is owned by the submission body contract
def _instructions(subject, body):
    return f"Subject: {subject or '(no subject)'}\n\n{body}".rstrip()


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_submission_contract_keeps_create_and_organize_report_only
# @tests tests_unit/test_028_ai_email.py::test_inline_attachment_selection_keeps_user_content_and_filters_signature_art
# @features ai-email
# @dimensions access attachment-contract body-contract rate-limit
def _preflight_submission(message, tool, user, config):
    from lagniappe.core.definitions import AI
    from lagniappe.core.tools.cache.rate_limit import check_limit

    if _automated_message(message):
        raise AIEmailRejection("automated_mail", "Automated mail is ignored.", silent=True)
    required_access = AI.ASK if tool in {"ai", "ask"} else AI.CREATE
    if not user.access(required_access):
        raise AIEmailRejection(
            "ai_access_denied",
            f"Your account does not currently have access to {tool.title()} reports.",
        )

    submitted = tuple(item for item in message.attachments if item.submitted)
    limits = config["limits"]
    if len(submitted) > limits["maxFiles"]:
        raise AIEmailRejection(
            "attachment_contract",
            f"A maximum of {limits['maxFiles']} attachments may be submitted.",
        )
    if any(item.size <= 0 for item in submitted):
        raise AIEmailRejection(
            "attachment_contract", "Empty attachments cannot be submitted by email."
        )
    if any(item.size > limits["maxFileBytes"] for item in submitted):
        raise AIEmailRejection(
            "attachment_contract", "Each attachment must be no larger than 30 MiB."
        )
    if sum(item.size for item in submitted) > limits["maxTotalFileBytes"]:
        raise AIEmailRejection(
            "attachment_contract", "Attachments may total no more than 50 MiB."
        )
    if tool == "create" and submitted:
        raise AIEmailRejection(
            "attachment_contract",
            "Create email does not accept attachments. Send files to the Organize address.",
        )
    if tool == "organize" and not submitted:
        raise AIEmailRejection(
            "attachment_contract", "Organize email requires at least one attachment."
        )

    instructions = _instructions(message.subject, message.text_body)
    if tool in {"ask", "create"} and not (message.subject or message.text_body):
        raise AIEmailRejection(
            "body_required", f"{tool.title()} email requires a subject or message body."
        )
    if tool == "ai" and not (message.subject or message.text_body or submitted):
        raise AIEmailRejection(
            "body_required", "AI email requires a subject, message body, or attachment."
        )
    if len(instructions.encode("utf-8")) > limits["maxBodyBytes"]:
        raise AIEmailRejection(
            "body_too_large", "The email subject and message body exceed 64 KiB."
        )

    for scope, limit, window in (
        ("ai-email-hour", limits["hourlyPerUser"], 3600),
        ("ai-email-day", limits["dailyPerUser"], 86400),
    ):
        result = check_limit(scope, user.urlsafe_key, limit, window)
        if not result["allowed"]:
            minutes = max((int(result["retry_after"]) + 59) // 60, 1)
            raise AIEmailRejection(
                "rate_limited",
                f"AI email submission limit reached. Try again in about {minutes} minute(s).",
            )
    return instructions, submitted


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_create_shared_address_email_report_preserves_routing_input
def _compact_report_name(tool, message, attachments):
    if tool == "organize":
        if len(attachments) == 1:
            return f"Organize: {attachments[0].filename}"[:100]
        return f"Organize: {len(attachments)} files"
    source = message.subject or " ".join(message.text_body.split())
    source = source[:80]
    suffix = "..." if len(message.subject or message.text_body) > 80 else ""
    prefix = "Email" if tool == "ai" else tool.title()
    return f"{prefix}: {source}{suffix}"[:100]


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_feedback_payload
# @reason report-link construction is exercised through outbound feedback
def report_url(report, config=None):
    if config is None:
        from lagniappe import CONFIG

        domain = CONFIG.CUSTOM_DOMAIN
    else:
        domain = config.get("applicationDomain") or config.get("customDomain")
    return f"https://{domain}/tools/reports/{report.urlsafe_key}"


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::_feedback_payload
# @reason reply-address construction is exercised through outbound feedback
def receiving_address(config, tool):
    return f"{config['aliases'][tool]}@{config['domain']}"


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::process_resend_email
# @reason stored-address normalization is owned by sender authorization
def _stored_email(user):
    """Normalize a stored mailbox without turning legacy bad data into retries."""
    try:
        return normalize_email_address(user.email)
    except ValueError:
        return ""


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_report_feedback_links_to_report_and_remains_available_after_disable
# @features ai-email
# @dimensions acceptance terminal-link reply-to idempotency disabled-completion
def _feedback_payload(config, user, tool, kind, *, report=None, message=None):
    label = tool.title()
    link = report_url(report) if report is not None else None
    if kind == "acceptance":
        subject = f"{label} email accepted"
        text = f"Your email was accepted and a {label} report is being prepared."
        if tool in {"create", "organize"}:
            text += " Any proposed changes will require review in Lagniappe."
    elif kind == "success":
        subject = f"{label} {'answer' if tool == 'ask' else 'proposal'} ready"
        text = (
            "Your Ask answer is ready."
            if tool == "ask"
            else f"Your {label} proposal is ready for review. No changes were applied."
        )
    elif kind == "failure":
        subject = f"{label} report could not be completed"
        text = message or "The report could not be completed. Open it for details."
    else:
        subject = f"{label} email was not accepted"
        text = message or "The email could not be submitted."
    if link:
        text = f"{text}\n\nOpen report: {link}"
    text = f"{text}\n\n{REPLY_MARKER}"
    html_parts = [f"<p>{escape(paragraph)}</p>" for paragraph in text.split("\n\n")]
    if link:
        escaped_link = escape(link, quote=True)
        html_parts = [
            part.replace(
                escape(f"Open report: {link}"),
                f'Open report: <a href="{escaped_link}">{escaped_link}</a>',
            )
            for part in html_parts
        ]
    resend = config["resend"]
    reply_to = receiving_address(config, tool)
    if report is not None:
        manifest = getattr(report, "inbound_manifest", None) or {}
        original_alias = manifest.get("alias") if isinstance(manifest, dict) else None
        configured_addresses = {
            receiving_address(config, configured_tool)
            for configured_tool in config["aliases"]
        }
        if original_alias in configured_addresses:
            reply_to = original_alias
    return {
        "from": f"{resend['senderName']} <{resend['senderEmail']}>",
        "to": [user.email],
        "reply_to": reply_to,
        "subject": subject,
        "text": text,
        "html": "".join(html_parts),
        "headers": {
            "Auto-Submitted": "auto-generated",
            "X-Auto-Response-Suppress": "All",
        },
    }


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::send_report_feedback
# @reason feedback idempotency hashing is owned by the outbound feedback contract
def _feedback_digest(value):
    from lagniappe import CONFIG

    return hmac.new(
        str(CONFIG.SECRET_KEY).encode("utf-8"),
        str(value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_report_feedback_links_to_report_and_remains_available_after_disable
# @features ai-email
# @dimensions terminal-link reply-to idempotency disabled-completion
def send_report_feedback(report, kind, *, message=None, client=None):
    """Send one idempotent acceptance/result email for an email-origin report."""
    from lagniappe import CONFIG

    if report.origin != "email" or report.tool not in {"ask", "create", "organize"}:
        return None
    user = report.user
    if user is None:
        raise AIEmailProviderError("Email report user is unavailable.")
    config = CONFIG.AI_EMAIL_CONFIG
    if not config:
        raise AIEmailProviderError("AI email feedback is unavailable.")
    client = client or ResendAIEmailClient(
        config["resend"]["inboundApiKey"],
        config["resend"]["sendingApiKey"],
    )
    digest = _feedback_digest(f"{report.urlsafe_key}:{kind}")
    return client.send_email(
        _feedback_payload(
            config,
            user,
            report.tool,
            kind,
            report=report,
            message=message,
        ),
        idempotency_key=f"ai-email/{kind}/{digest[:40]}",
    )


# @testable false
# @covered-by lagniappe/core/tools/email/ai.py::process_resend_email
# @reason rejection delivery is a private terminal branch of event processing
def _send_rejection(config, user, tool, rejection, digest, client):
    return client.send_email(
        _feedback_payload(
            config,
            user,
            tool,
            "rejection",
            message=rejection.public_message,
        ),
        idempotency_key=f"ai-email/rejection/{digest[:40]}",
    )


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_create_shared_address_email_report_preserves_routing_input
# @features ai-email
# @dimensions report-handoff routing idempotency privacy
def _create_email_report(
    message, tool, user, instructions, attachments, digest, config
):
    from lagniappe.core.definitions import DeferredJobSpec, DeferredJobType, Fetch
    from lagniappe.core.entities import Entities
    from lagniappe.core.tools import database
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    key = database.create_named_key("report", f"email-{digest}", user)
    report = Entities.fetch_one(key, request=Fetch.direct())
    if not isinstance(report, Entities.REPORT):
        effective_tool = "ask" if tool == "ai" else tool
        report = Entities.REPORT.create(
            {
                "parent": user,
                "user": user,
                "name": _compact_report_name(tool, message, attachments),
                "tool": effective_tool,
                "instructions": instructions,
                "status": "pending",
                "pending": True,
                "origin": "email",
                "inbound_manifest": {
                    "subject": message.subject,
                    "body": message.text_body,
                    "tool": effective_tool,
                    "requested_tool": tool,
                    "alias": receiving_address(config, tool),
                    "received_at": message.received_at,
                    "attachments": [item.display_record() for item in attachments],
                },
            },
            key=key,
        )
        Entities.save(report, user)

    DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.EMAIL_INGEST,
            actor=user,
            inputs={"report": report},
            parameters={
                "provider_message_id": message.provider_message_id,
                "attachments": [item.job_record() for item in attachments],
                "event_digest": digest,
                "requested_tool": tool,
            },
            notification_body=f"Preparing {tool} report from email...",
            notification_target=report,
            client={},
            idempotency_key=f"ai-email/ingest/{digest}",
        )
    )
    return report


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_process_resend_email_hands_off_to_existing_report_pipeline
# @features ai-email
# @dimensions replay sender exact-match user-policy report-handoff
# @pairs ai-email:replay ai-email:sender ai-email:exact-match ai-email:user-policy
# @pair ai-email:report-handoff
# @pairs webhook:replay webhook:sender webhook:exact-match webhook:user-policy
# @pair webhook:report-handoff
def process_resend_email(event, event_id, config, digest_secret, *, client=None):
    """Retrieve, authorize, and durably hand one signed event to report ingestion."""
    from lagniappe.core.definitions import Fetch
    from lagniappe.core.entities import Entities
    from lagniappe.core.tools import database
    from lagniappe.core.tools.database import ai_email as email_database

    if event.get("type") != "email.received":
        return AIEmailSubmissionResult("ignored")
    digest = hmac.new(
        str(digest_secret).encode("utf-8"),
        f"resend:{event_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    lease_token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    claim = email_database.claim_ai_email_event(digest, lease_token, now)
    if not claim.get("claimed"):
        return AIEmailSubmissionResult("duplicate", code=claim.get("reason"))

    client = client or ResendAIEmailClient(
        config["resend"]["inboundApiKey"],
        config["resend"]["sendingApiKey"],
    )
    terminal_state = None
    try:
        email_id = _provider_id((event.get("data") or {}).get("email_id"), "received-email")
        raw_message = client.retrieve_received_email(email_id)
        if str(raw_message.get("id") or "") != email_id:
            raise AIEmailProviderError("Resend returned a different received email.")
        attachment_rows = client.list_received_attachments(email_id)
        message, tool = normalize_resend_message(raw_message, attachment_rows, config)

        raw_user = database.get.user(message.sender)
        user = (
            Entities.fetch_one(raw_user, request=Fetch.direct()) if raw_user else None
        )
        if (
            not isinstance(user, Entities.USER)
            or user.is_public
            or not user.active
            or _stored_email(user) != message.sender
        ):
            terminal_state = "ignored"
            return AIEmailSubmissionResult("ignored", code="sender_unknown")

        try:
            instructions, attachments = _preflight_submission(
                message, tool, user, config
            )
        except AIEmailRejection as rejection:
            if rejection.silent:
                terminal_state = "ignored"
                return AIEmailSubmissionResult("ignored", code=rejection.code)
            _send_rejection(config, user, tool, rejection, digest, client)
            terminal_state = "rejected"
            return AIEmailSubmissionResult("rejected", code=rejection.code)

        report = _create_email_report(
            message,
            tool,
            user,
            instructions,
            attachments,
            digest,
            config,
        )
        terminal_state = "accepted"
        return AIEmailSubmissionResult("accepted", report=report)
    except AIEmailRejection as rejection:
        terminal_state = "ignored" if rejection.silent else "rejected"
        return AIEmailSubmissionResult(terminal_state, code=rejection.code)
    except Exception:
        email_database.release_ai_email_event(
            digest, lease_token, datetime.now(timezone.utc)
        )
        raise
    finally:
        if terminal_state:
            email_database.finish_ai_email_event(
                digest,
                lease_token,
                terminal_state,
                datetime.now(timezone.utc),
            )


__all__ = [
    "AIEmailProviderError",
    "AIEmailRejection",
    "AIEmailSubmissionResult",
    "AIEmailWebhookError",
    "InboundAttachment",
    "InboundMessage",
    "REPLY_MARKER",
    "ResendAIEmailClient",
    "authentication_results_candidates",
    "normalize_message_body",
    "normalize_resend_message",
    "parse_mailbox",
    "parse_resend_event",
    "process_resend_email",
    "receiving_address",
    "report_url",
    "send_report_feedback",
    "verify_svix_signature",
]
