"""Cloud Storage file upload, download, and deletion helpers."""

from __future__ import annotations

import base64
import datetime
import io
import re
import uuid
from contextlib import suppress
from copy import deepcopy
from typing import BinaryIO, NotRequired, Protocol, Self, TypedDict, TypeGuard, cast

from google.api_core import exceptions as google_exceptions
from google.cloud.storage import Blob
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from lagniappe import CONFIG
from lagniappe.core.definitions.file_consumers import (
    FILE_CONSUMER_CAPABILITIES,
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
)

from .core import DATA

DIRECT_UPLOAD_PREFIX = "tmp/uploads"
DIRECT_UPLOAD_VISIBILITY = "private"
DIRECT_UPLOAD_TOKEN_MAX_AGE = 60 * 60
DIRECT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DIRECT_UPLOAD_SALT = "lagniappe-direct-upload"
GENERIC_CONTENT_TYPES = {"", None, "application/octet-stream"}
DIRECT_UPLOAD_ASSET_NONCE = re.compile(r"^[a-f0-9]{32}$")


class UploadSession(TypedDict):
    token: str
    session_url: str
    chunk_size: int


class UploadToken(TypedDict):
    path: str
    visibility: NotRequired[str | None]
    filename: NotRequired[str | None]
    content_type: NotRequired[str | None]
    size: NotRequired[int | str | None]
    input_name: NotRequired[str | None]


class AttemptOwner(Protocol):
    _form_attempt_assets: list[dict[str, object]] | None


# @testable false
# @covered-by lagniappe/core/tools/forms/drafts.py::save_form_draft
# @covered-by lagniappe/core/tools/forms/drafts.py::copy_form_draft
# @reason attempt ownership bounds cleanup to newly allocated objects
def record_attempt_asset(owner: AttemptOwner, definition: dict[str, object]) -> None:
    owned = getattr(owner, "_form_attempt_assets", None)
    if owned is None:
        owner._form_attempt_assets = owned = []
    owned.append(deepcopy(definition))


# @testable true
# @tests tests_unit/test_004f_form_drafts.py::test_rejected_save_cleans_only_attempt_blobs_and_ambiguous_commit_retains_them
# @matrix html-field : isolated-assets cleanup
def cleanup_rejected_attempt(owner: AttemptOwner) -> None:
    """Retire known rejected attempt objects, never accepted/history objects."""
    for definition in getattr(owner, "_form_attempt_assets", None) or []:
        if not definition.get("generation"):
            continue
        # A cleanup failure never authorizes deletion without its generation.
        with suppress(Exception):
            delete_file_generation(
                definition["path"], definition.get("visibility", "private"), definition["generation"],
            )
    owner._form_attempt_assets = []


class DirectUploadError(ValueError):
    """Raised when direct-upload metadata or storage state fails validation."""


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_direct_upload_attempt_path_is_unique_and_validated
# @matrix direct-upload storage : attempt-isolation destination-path
def direct_upload_destination_path(path: str, upload: object) -> str:
    """Add an internal attempt nonce without trusting user-controlled paths."""
    nonce = getattr(upload, "lagniappe_asset_nonce", None)
    if nonce is None:
        return path
    if not isinstance(nonce, str) or not DIRECT_UPLOAD_ASSET_NONCE.fullmatch(nonce):
        raise DirectUploadError("Direct upload asset attempt identity is invalid")
    stem, separator, extension = str(path).rpartition(".")
    if not separator:
        return f"{path}_{nonce}"
    return f"{stem}_{nonce}.{extension}"


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
class DirectUploadFile:
    """File-like wrapper around a verified direct-to-GCS upload."""

    lagniappe_direct_upload = True
    lagniappe_asset_nonce: str
    lagniappe_preserve_source: bool

    def __init__(
        self, record: dict[str, object], payload: UploadToken, blob: Blob
    ) -> None:
        self.record = record
        self.payload = payload
        self.blob = blob
        self.filename = str(payload.get("filename") or record.get("filename") or "upload")
        self.content_type = (
            payload.get("content_type")
            or record.get("content_type")
            or "application/octet-stream"
        )
        self.lagniappe_content_type = self.content_type
        self._buffer: io.BytesIO | None = None
        self._file_consumer: FileConsumer | None = None
        self.lagniappe_saved_blob: Blob | None = None
        self.lagniappe_saved_destination: dict[str, str] | None = None

    @property
    def stream(self) -> Self:
        return self

    @property
    def path(self) -> str:
        return self.payload["path"]

    @property
    def visibility(self) -> str:
        return self.payload.get("visibility") or DIRECT_UPLOAD_VISIBILITY

    @property
    def size(self) -> int | None:
        return getattr(self.blob, "size", None)

    @property
    def md5_hex(self) -> str | None:
        blob = self.lagniappe_saved_blob or self.blob
        md5_hash = getattr(blob, "md5_hash", None)
        if not md5_hash:
            return None
        try:
            return base64.b64decode(md5_hash).hex()
        except Exception:
            return None

    def _source_blob_for_download(self) -> Blob:
        return self.lagniappe_saved_blob or self.blob

    def _authorize_file_consumer(self, consumer: FileConsumer) -> None:
        self._file_consumer = consumer

    def _ensure_buffer(self) -> io.BytesIO:
        if self._buffer is not None:
            return self._buffer

        if self._file_consumer is None:
            raise FileConsumerLimitError(
                "Full-byte direct upload reads require a named file consumer.",
                consumer=None,
            )
        enforce_file_consumer(
            self,
            self._file_consumer,
            filename=self.filename,
        )

        data = self._source_blob_for_download().download_as_bytes()
        self._buffer = io.BytesIO(data)
        return self._buffer

    def read_sample(self, size: int = 8192) -> bytes:
        """Read a small prefix of the upload without materializing the full object."""
        sample_limit = FILE_CONSUMER_CAPABILITIES[FileConsumer.MIME_SAMPLE].max_bytes
        size = int(size or 0)
        if sample_limit is None:
            raise FileConsumerLimitError(
                "MIME sample reads require a byte limit.", consumer=FileConsumer.MIME_SAMPLE
            )
        size = min(size, sample_limit)
        if size <= 0:
            return b""
        return self._source_blob_for_download().download_as_bytes(
            start=0,
            end=size - 1,
        )

    def seek(self, offset: int, whence: int = 0, /) -> int:
        return self._ensure_buffer().seek(offset, whence)

    def tell(self) -> int:
        return self._ensure_buffer().tell()

    def read(self, size: int | None = -1, /) -> bytes:
        return self._ensure_buffer().read(size)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::create_direct_upload_session
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason serializer construction is a tiny wrapper around app secret configuration
def _direct_upload_serializer():
    return URLSafeTimedSerializer(CONFIG.SECRET_KEY, salt=DIRECT_UPLOAD_SALT)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_create_direct_upload_session_uses_private_tmp_object
# @matrix storage : direct-upload session token
def create_direct_upload_session(
    filename: str,
    content_type: str | None = None,
    size: int | str | None = None,
    input_name: str | None = None,
    origin: str | None = None,
) -> UploadSession:
    """Create a browser-usable resumable upload session for a private temp blob."""
    safe_name = secure_filename(filename or "") or "upload.bin"
    upload_id = uuid.uuid4().hex
    path = f"{DIRECT_UPLOAD_PREFIX}/{upload_id}/{safe_name}"
    content_type = content_type or "application/octet-stream"
    size = int(size) if size not in (None, "") else None
    if size is not None and size < 0:
        raise DirectUploadError("Upload size cannot be negative")

    blob = DATA.private_bucket.blob(path)
    session_url = blob.create_resumable_upload_session(
        content_type=content_type,
        size=size,
        origin=origin,
        if_generation_match=0,
    )
    if not session_url:
        raise DirectUploadError("Cloud Storage did not return an upload session URL.")
    payload = {
        "path": path,
        "visibility": DIRECT_UPLOAD_VISIBILITY,
        "filename": filename or safe_name,
        "content_type": content_type,
        "size": size,
        "input_name": input_name,
    }
    token = _direct_upload_serializer().dumps(payload)

    return {
        "session_url": session_url,
        "token": token,
        "chunk_size": DIRECT_UPLOAD_CHUNK_SIZE,
    }


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_bad_token
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_mismatched_size
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_generation_mismatch
# @matrix storage : direct-upload expiry token validation
def load_direct_upload_token(
    token: object, max_age: int | None = DIRECT_UPLOAD_TOKEN_MAX_AGE
) -> UploadToken:
    """Load and validate a direct-upload token payload."""
    if not isinstance(token, (str, bytes)):
        raise DirectUploadError("Invalid direct upload token")
    try:
        payload = _direct_upload_serializer().loads(token, max_age=max_age)
    except SignatureExpired as e:
        raise DirectUploadError("Direct upload token expired") from e
    except BadSignature as e:
        raise DirectUploadError("Invalid direct upload token") from e

    if not isinstance(payload, dict) or not payload.get("path"):
        raise DirectUploadError("Invalid direct upload token")
    if not isinstance(payload["path"], str) or not payload["path"].startswith(f"{DIRECT_UPLOAD_PREFIX}/"):
        raise DirectUploadError("Invalid direct upload path")

    for field in ("filename", "visibility", "content_type", "input_name"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise DirectUploadError("Invalid direct upload metadata")
    if payload.get("size") is not None and not isinstance(payload["size"], (str, int)):
        raise DirectUploadError("Invalid direct upload size")
    return cast(UploadToken, payload)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason content-type comparison is exercised through direct-upload validation
def _content_types_match(expected, actual):
    if expected in GENERIC_CONTENT_TYPES:
        return True
    if not actual:
        return False
    return (
        expected.split(";")[0].strip().lower() == actual.split(";")[0].strip().lower()
    )


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_mismatched_size
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_generation_mismatch
# @tests tests_unit/test_018_database_assets.py::test_verified_direct_upload_pins_generation_for_later_cleanup
# @matrix storage : direct-upload object validation
def verify_direct_upload(
    record: object,
    max_age: int | None = DIRECT_UPLOAD_TOKEN_MAX_AGE,
    *,
    consumer: FileConsumer | str | None = None,
) -> DirectUploadFile:
    """Verify a direct-upload token and the object now present in Cloud Storage."""
    if not isinstance(record, dict):
        raise DirectUploadError("Invalid direct upload metadata")

    payload = load_direct_upload_token(record.get("token"), max_age=max_age)
    submitted_path = record.get("path") or record.get("name")
    if submitted_path and submitted_path != payload["path"]:
        raise DirectUploadError("Direct upload object path mismatch")

    submitted_input = record.get("input_name")
    if (
        submitted_input
        and payload.get("input_name")
        and submitted_input != payload.get("input_name")
    ):
        raise DirectUploadError("Direct upload input mismatch")

    bucket = DATA.bucket(payload.get("visibility") or DIRECT_UPLOAD_VISIBILITY)
    blob = bucket.blob(payload["path"])
    try:
        blob.reload()
    except google_exceptions.NotFound as e:
        raise DirectUploadError("Direct upload object not found") from e

    expected_size = payload.get("size")
    if expected_size is not None and int(getattr(blob, "size", -1)) != int(
        expected_size
    ):
        raise DirectUploadError("Direct upload size mismatch")

    expected_type = payload.get("content_type")
    if not _content_types_match(expected_type, getattr(blob, "content_type", None)):
        raise DirectUploadError("Direct upload content type mismatch")

    observed_generation = getattr(blob, "generation", None)
    if observed_generation is None:
        raise DirectUploadError("Direct upload generation is invalid")
    try:
        observed_generation = int(observed_generation)
    except (TypeError, ValueError) as error:
        raise DirectUploadError("Direct upload generation is invalid") from error
    generation = record.get("generation")
    if generation and str(generation) != str(observed_generation):
        raise DirectUploadError("Direct upload generation mismatch")
    # Bind later cleanup to the exact object revision verified here. The value
    # is checkpointed with finalized manifests, so an out-of-band replacement
    # at this private temporary path cannot be deleted by a delayed retry.
    record["generation"] = str(observed_generation)

    upload = DirectUploadFile(record, payload, blob)
    if consumer is not None:
        enforce_file_consumer(upload, consumer, filename=upload.filename)
    return upload


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason direct-upload wrapping delegates to the validation helper
def direct_upload_file(
    record: object, *, consumer: FileConsumer | str | None = None
) -> DirectUploadFile:
    """Return a file-like wrapper for verified direct-upload metadata."""
    return verify_direct_upload(record, consumer=consumer)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_copy_direct_upload_file_copies_and_deletes_temp_object
# @matrix storage : direct-upload final-copy generation-conditional-cleanup idempotency
def copy_direct_upload_file(
    upload: DirectUploadFile,
    path: str,
    visibility: str,
    content_type: str | None = None,
    *,
    delete_source: bool = True,
) -> Blob:
    """Copy a verified direct-upload temp object into its permanent asset path."""
    source_bucket = DATA.bucket(upload.visibility)
    destination_bucket = DATA.bucket(visibility)
    try:
        if upload.blob.generation is None:
            raise DirectUploadError("Direct upload generation is invalid")
        source_generation = int(upload.blob.generation)
    except (AttributeError, TypeError, ValueError) as error:
        raise DirectUploadError("Direct upload generation is invalid") from error
    try:
        copied = source_bucket.copy_blob(
            upload.blob,
            destination_bucket,
            path,
            source_generation=source_generation,
            if_source_generation_match=source_generation,
            if_generation_match=0,
        )
    except google_exceptions.PreconditionFailed as error:
        raise DirectUploadError(
            "Direct upload source changed or destination already exists"
        ) from error
    upload.lagniappe_saved_blob = copied
    destination_generation = getattr(copied, "generation", None)
    if destination_generation is not None:
        upload.lagniappe_saved_destination = {
            "path": path,
            "visibility": visibility,
            "generation": str(destination_generation),
        }
    if content_type and getattr(copied, "content_type", None) != content_type:
        copied.content_type = content_type
        if destination_generation is None:
            copied.patch()
        else:
            copied.patch(if_generation_match=int(destination_generation))
    if delete_source:
        # An absent source needs no cleanup; a replacement is not ours to delete.
        with suppress(google_exceptions.NotFound, google_exceptions.PreconditionFailed):
            upload.blob.delete(if_generation_match=source_generation)
    return copied


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_delete_file_generation_never_deletes_a_replacement
# @matrix storage : attempt-isolation generation-conditional-cleanup
def delete_file_generation(path: str, visibility: str, generation: str | int) -> bool:
    """Delete only the exact blob generation created by one failed attempt."""
    try:
        expected_generation = int(generation)
    except (TypeError, ValueError) as error:
        raise DirectUploadError("Direct upload generation is invalid") from error
    blob = DATA.bucket(visibility).blob(path)
    try:
        blob.delete(if_generation_match=expected_generation)
        return True
    except google_exceptions.NotFound:
        return True
    except google_exceptions.PreconditionFailed:
        return False


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_delete_direct_upload_is_idempotent_and_generation_conditional
# @matrix direct-upload storage : cleanup generation-conditional-cleanup idempotency
def delete_direct_upload(record: object) -> bool:
    """Delete exactly one signed temporary upload, treating absence as success."""
    try:
        if not isinstance(record, dict):
            return False
        payload = load_direct_upload_token(record.get("token"), max_age=None)
        submitted_path = record.get("path") or record.get("name")
        if submitted_path and submitted_path != payload["path"]:
            return False
        submitted_input = record.get("input_name")
        if (
            submitted_input
            and payload.get("input_name")
            and submitted_input != payload.get("input_name")
        ):
            return False
        blob = DATA.bucket(
            payload.get("visibility") or DIRECT_UPLOAD_VISIBILITY
        ).blob(payload["path"])
        generation = record.get("generation")
        if generation is None:
            blob.reload()
            generation = blob.generation
        if generation is None:
            return False
        blob.delete(if_generation_match=int(generation))
        return True
    except google_exceptions.NotFound:
        return True
    except google_exceptions.PreconditionFailed:
        return False
    except Exception:
        return False


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_file_preserves_direct_upload_source_when_requested
# @tests tests_unit/test_018_database_assets.py::test_save_file_returns_reloaded_blob_metadata
# @matrix direct-upload file storage : asset-size deferred-cleanup metadata
def _is_direct_upload(file: object) -> TypeGuard[DirectUploadFile]:
    return bool(getattr(file, "lagniappe_direct_upload", False))


def save_file(
    file: BinaryIO | FileStorage | DirectUploadFile,
    path: str,
    content_type: str,
    visibility: str,
) -> Blob:
    """Upload a file object to the specified bucket.

    Args:
        file: File-like object to upload.
        path: Destination blob path within the bucket.
        content_type: MIME type for the uploaded blob.
        visibility: Bucket name — 'private', 'public', or 'history'.
    """
    if _is_direct_upload(file):
        return copy_direct_upload_file(
            file,
            path,
            visibility,
            content_type,
            delete_source=not getattr(file, "lagniappe_preserve_source", False),
        )

    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    file.seek(0)
    blob.upload_from_file(file, content_type=content_type)
    blob.reload()
    return blob


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_download_file_passes_optional_byte_range
# @tests tests_unit/test_018_database_assets.py::test_missing_blob_download_and_size_return_none
# @matrix file storage : byte-range missing-object
def download_file(
    path: str, visibility: str, start: int | None = None, end: int | None = None
) -> bytes | None:
    """Download a blob's contents as bytes from the specified bucket."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    options = {}
    if start is not None:
        options["start"] = start
    if end is not None:
        options["end"] = end
    try:
        return blob.download_as_bytes(**options)
    except google_exceptions.NotFound:
        return None


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_file_size_reloads_blob_metadata
# @tests tests_unit/test_018_database_assets.py::test_missing_blob_download_and_size_return_none
# @matrix file storage : byte-range metadata missing-object
def file_size(path: str, visibility: str) -> int | None:
    """Return a blob's byte size from storage metadata."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    try:
        blob.reload()
    except google_exceptions.NotFound:
        return None
    return blob.size


# @testable true
# @matrix storage : generation-pinned read copy
def get_text(
    path: str,
    visibility: str,
    encoding: str = "utf-8",
    *,
    generation: int | str | None = None,
) -> str:
    """Read text, optionally pinning a descriptor's recorded object generation."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path, **({"generation": int(generation)} if generation else {}))

    encoding = "utf-8-sig" if encoding == "utf-8" else encoding
    text = blob.download_as_text(encoding=encoding)

    return text


# @testable false
# @reason cloud storage behavior is owned by E2E coverage against configured services
def save_text(text: str, path: str, content_type: str, visibility: str) -> Blob:
    """Upload a text string as a blob to the specified bucket.

    Args:
        text: String content to upload.
        path: Destination blob path within the bucket.
        content_type: MIME type for the uploaded blob.
        visibility: Bucket name — 'private', 'public', or 'history'.
    """
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    blob.upload_from_string(text, content_type=content_type)
    blob.reload()
    return blob


# @testable true
# @matrix storage : generation-pinned read copy
def copy_file(
    source_path: str,
    source_visibility: str,
    destination_path: str,
    destination_visibility: str,
    *,
    source_generation: int | str | None = None,
) -> Blob | None:
    """Copy a live or generation-pinned blob without downloading it into memory."""
    source_bucket = DATA.bucket(source_visibility)
    destination_bucket = DATA.bucket(destination_visibility)
    source_blob = source_bucket.blob(
        source_path, **({"generation": int(source_generation)} if source_generation else {})
    )
    if not source_blob.exists():
        return None

    return source_bucket.copy_blob(
        source_blob, destination_bucket, destination_path,
        source_generation=int(source_generation) if source_generation else None,
    )


# @testable false
# @reason cloud storage listing behavior is provider-owned; export tests mock this helper
def list_files(prefix: str, visibility: str) -> list[Blob]:
    """List blobs under a prefix in the selected bucket."""
    bucket = DATA.bucket(visibility)
    return list(bucket.list_blobs(prefix=prefix))


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_signed_url_uses_remote_iam_signing
# @matrix storage : adc iam-signing signed-url token-refresh
def get_signed_url(
    path: str,
    expires_in: int = 3600,
    response_disposition: str | None = None,
    response_type: str | None = None,
) -> str:
    """Generate a v4 signed URL through IAM Credentials remote signing."""
    blob = DATA.private_bucket.blob(path)
    options = {}
    if response_disposition:
        options["response_disposition"] = response_disposition
    if response_type:
        options["response_type"] = response_type
    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=expires_in),
        method="GET",
        credentials=CONFIG.google_credentials,
        service_account_email=CONFIG.RUNTIME_SERVICE_ACCOUNT_EMAIL,
        access_token=CONFIG.google_access_token(),
        **options,
    )
    return url


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_delete_file_ignores_missing_blob
# @matrix storage : idempotent-delete missing-object
def delete_file(path: str, visibility: str) -> None:
    """Delete a blob from the specified bucket."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    with suppress(google_exceptions.NotFound):
        blob.delete()


# @testable true
# @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @pair admin:site-image-upload
def upload_site_image(filename: str, image_data: bytes) -> dict[str, str]:
    """Upload a site image and return its path and immutable generation."""
    if filename.endswith(".png"):
        content_type = "image/png"
    elif filename.endswith(".ico"):
        content_type = "image/x-icon"
    else:
        raise ValueError("Site image filenames must end in .png or .ico.")

    blob = DATA.public_bucket.blob(filename)
    blob.upload_from_string(image_data, content_type=content_type)
    blob.reload()

    return {"path": filename, "generation": str(blob.generation)}
