"""Cloud Storage file upload, download, and deletion helpers."""

import base64
import datetime
from datetime import timezone
import io
import uuid

from google.api_core import exceptions as google_exceptions
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.utils import secure_filename

from lagniappe import CONFIG
from config.ai_settings import AI_SETTING_KEYS
from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from lagniappe.core.definitions.file_consumers import (
    FILE_CONSUMER_CAPABILITIES,
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
)

from .core import DATA, KINDS

DIRECT_UPLOAD_PREFIX = "tmp/uploads"
DIRECT_UPLOAD_VISIBILITY = "private"
DIRECT_UPLOAD_TOKEN_MAX_AGE = 60 * 60
DIRECT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DIRECT_UPLOAD_SALT = "lagniappe-direct-upload"
GENERIC_CONTENT_TYPES = {"", None, "application/octet-stream"}


class DirectUploadError(ValueError):
    """Raised when direct-upload metadata or storage state fails validation."""


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
class DirectUploadFile:
    """File-like wrapper around a verified direct-to-GCS upload."""

    lagniappe_direct_upload = True

    def __init__(self, record, payload, blob):
        self.record = record
        self.payload = payload
        self.blob = blob
        self.filename = payload.get("filename") or record.get("filename") or "upload"
        self.content_type = (
            payload.get("content_type")
            or record.get("content_type")
            or "application/octet-stream"
        )
        self.lagniappe_content_type = self.content_type
        self._buffer = None
        self._file_consumer = None
        self.lagniappe_saved_blob = None

    @property
    def stream(self):
        return self

    @property
    def path(self):
        return self.payload["path"]

    @property
    def visibility(self):
        return self.payload.get("visibility") or DIRECT_UPLOAD_VISIBILITY

    @property
    def size(self):
        return getattr(self.blob, "size", None)

    @property
    def md5_hex(self):
        blob = self.lagniappe_saved_blob or self.blob
        md5_hash = getattr(blob, "md5_hash", None)
        if not md5_hash:
            return None
        try:
            return base64.b64decode(md5_hash).hex()
        except Exception:
            return None

    def _source_blob_for_download(self):
        return self.lagniappe_saved_blob or self.blob

    def _authorize_file_consumer(self, consumer):
        self._file_consumer = consumer

    def _ensure_buffer(self):
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

    def read_sample(self, size=8192):
        """Read a small prefix of the upload without materializing the full object."""
        sample_limit = FILE_CONSUMER_CAPABILITIES[FileConsumer.MIME_SAMPLE].max_bytes
        size = min(int(size or 0), sample_limit)
        if size <= 0:
            return b""
        return self._source_blob_for_download().download_as_bytes(
            start=0,
            end=size - 1,
        )

    def seek(self, *args, **kwargs):
        return self._ensure_buffer().seek(*args, **kwargs)

    def tell(self):
        return self._ensure_buffer().tell()

    def read(self, *args, **kwargs):
        return self._ensure_buffer().read(*args, **kwargs)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::create_direct_upload_session
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason serializer construction is a tiny wrapper around app secret configuration
def _direct_upload_serializer():
    return URLSafeTimedSerializer(CONFIG.SECRET_KEY, salt=DIRECT_UPLOAD_SALT)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_create_direct_upload_session_uses_private_tmp_object
# @features storage
# @dimensions direct-upload session token
def create_direct_upload_session(
    filename,
    content_type=None,
    size=None,
    input_name=None,
    origin=None,
):
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
# @features storage
# @dimensions direct-upload token validation
def load_direct_upload_token(token, max_age=DIRECT_UPLOAD_TOKEN_MAX_AGE):
    """Load and validate a direct-upload token payload."""
    try:
        payload = _direct_upload_serializer().loads(token, max_age=max_age)
    except SignatureExpired as e:
        raise DirectUploadError("Direct upload token expired") from e
    except BadSignature as e:
        raise DirectUploadError("Invalid direct upload token") from e

    if not isinstance(payload, dict) or not payload.get("path"):
        raise DirectUploadError("Invalid direct upload token")
    if not str(payload["path"]).startswith(f"{DIRECT_UPLOAD_PREFIX}/"):
        raise DirectUploadError("Invalid direct upload path")

    return payload


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason content-type comparison is exercised through direct-upload validation
def _content_types_match(expected, actual):
    if expected in GENERIC_CONTENT_TYPES:
        return True
    if not actual:
        return False
    return (
        expected.split(";")[0].strip().lower()
        == actual.split(";")[0].strip().lower()
    )


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_mismatched_size
# @tests tests_unit/test_018_database_assets.py::test_verify_direct_upload_rejects_generation_mismatch
# @features storage
# @dimensions direct-upload object validation
def verify_direct_upload(
    record,
    max_age=DIRECT_UPLOAD_TOKEN_MAX_AGE,
    *,
    consumer=None,
):
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

    generation = record.get("generation")
    if generation and str(generation) != str(getattr(blob, "generation", "")):
        raise DirectUploadError("Direct upload generation mismatch")

    upload = DirectUploadFile(record, payload, blob)
    if consumer is not None:
        enforce_file_consumer(upload, consumer, filename=upload.filename)
    return upload


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason direct-upload wrapping delegates to the validation helper
def direct_upload_file(record, *, consumer=None):
    """Return a file-like wrapper for verified direct-upload metadata."""
    return verify_direct_upload(record, consumer=consumer)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_copy_direct_upload_file_copies_and_deletes_temp_object
# @features storage
# @dimensions direct-upload final-copy
def copy_direct_upload_file(
    upload,
    path,
    visibility,
    content_type=None,
    *,
    delete_source=True,
):
    """Copy a verified direct-upload temp object into its permanent asset path."""
    source_bucket = DATA.bucket(upload.visibility)
    destination_bucket = DATA.bucket(visibility)
    copied = source_bucket.copy_blob(upload.blob, destination_bucket, path)
    if content_type and getattr(copied, "content_type", None) != content_type:
        copied.content_type = content_type
        copied.patch()
    if delete_source:
        upload.blob.delete()
    upload.lagniappe_saved_blob = copied
    return copied


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::verify_direct_upload
# @reason best-effort temp cleanup is a provider-owned side effect
def delete_direct_upload(record):
    """Best-effort delete for an uploaded temp object."""
    try:
        upload = verify_direct_upload(record)
        upload.blob.delete()
        return True
    except Exception:
        return False


# @testable false
# @reason cloud storage behavior is owned by E2E coverage against configured services
def save_file(file, path, content_type, visibility):
    """Upload a file object to the specified bucket.

    Args:
        file: File-like object to upload.
        path: Destination blob path within the bucket.
        content_type: MIME type for the uploaded blob.
        visibility: Bucket name — 'private', 'public', or 'history'.
    """
    if getattr(file, "lagniappe_direct_upload", False):
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
# @features file storage
# @dimensions byte-range
def download_file(path, visibility, start=None, end=None):
    """Download a blob's contents as bytes from the specified bucket."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    options = {}
    if start is not None:
        options["start"] = start
    if end is not None:
        options["end"] = end
    return blob.download_as_bytes(**options)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_file_size_reloads_blob_metadata
# @features file storage
# @dimensions byte-range metadata
def file_size(path, visibility):
    """Return a blob's byte size from storage metadata."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    blob.reload()
    return blob.size


# @testable false
# @reason cloud storage behavior is owned by E2E coverage against configured services
def get_text(path, visibility, encoding="utf-8"):
    """Download a blob as decoded text from the specified bucket."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)

    encoding = "utf-8-sig" if encoding == "utf-8" else encoding
    text = blob.download_as_text(encoding=encoding)

    return text


# @testable false
# @reason cloud storage behavior is owned by E2E coverage against configured services
def save_text(text, path, content_type, visibility):
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


# @testable false
# @reason cloud storage copy behavior is provider-owned; export tests mock this helper
def copy_file(source_path, source_visibility, destination_path, destination_visibility):
    """Copy a blob between storage buckets without downloading it into memory."""
    source_bucket = DATA.bucket(source_visibility)
    destination_bucket = DATA.bucket(destination_visibility)
    source_blob = source_bucket.blob(source_path)
    if not source_blob.exists():
        return None

    return source_bucket.copy_blob(source_blob, destination_bucket, destination_path)


# @testable false
# @reason cloud storage listing behavior is provider-owned; export tests mock this helper
def list_files(prefix, visibility):
    """List blobs under a prefix in the selected bucket."""
    bucket = DATA.bucket(visibility)
    return list(bucket.list_blobs(prefix=prefix))


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_signed_url_uses_remote_iam_signing
# @features storage
# @dimensions signed-url adc iam-signing token-refresh
def get_signed_url(
    path,
    expires_in=3600,
    response_disposition=None,
    response_type=None,
):
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


# @testable false
# @reason cloud storage behavior is owned by E2E coverage against configured services
def delete_file(path, visibility):
    """Delete a blob from the specified bucket."""
    bucket = DATA.bucket(visibility)
    blob = bucket.blob(path)
    blob.delete()


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @features admin
# @dimensions site-image-upload
def upload_site_image(filename, image_data):
    """Upload a site image to the public bucket. Returns the blob path (filename)."""
    if filename.endswith(".png"):
        content_type = "image/png"
    elif filename.endswith(".ico"):
        content_type = "image/x-icon"

    blob = DATA.public_bucket.blob(filename)
    blob.upload_from_string(image_data, content_type=content_type)

    return filename


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @tests tests_unit/test_018_database_assets.py::test_save_site_image_persists_version_without_mutating_input
# @features admin
# @dimensions site-image-upload metadata
def save_site_image(data):
    """Persist site image metadata to the Datastore 'site/image' entity.
    Stores paths (filename -> path) and a version that is incremented on each save.
    """
    image_key = DATA.datastore.key("site", "image")
    image = DATA.datastore.get(image_key)
    if not image:
        image = DATA.datastore.entity(key=image_key)

    version = int(image.get("version", 0)) + 1
    image.update({**data, "version": version})
    DATA.datastore.put(image)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_site_deployment_persists_canonical_payload_and_prunes_old_keys
# @features admin
# @dimensions deployment-settings metadata
def save_site_deployment(data):
    """Persist deployment settings metadata to the Datastore 'site/deployment' entity."""
    deployment_key = DATA.datastore.key("site", "deployment")
    deployment = DATA.datastore.get(deployment_key)
    if not deployment:
        deployment = DATA.datastore.entity(key=deployment_key)

    version = int(deployment.get("version", 0)) + 1
    canonical = {
        key: value
        for key, value in data.items()
        if key in DEFAULT_DEPLOYMENT_SETTINGS
    }
    deployment.clear()
    deployment.update({**canonical, "version": version})
    DATA.datastore.put(deployment)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_site_ai_persists_canonical_payload_and_prunes_old_keys
# @features admin
# @dimensions ai-settings metadata
def save_site_ai(data):
    """Persist AI model settings metadata to the Datastore 'site/ai' entity."""
    ai_key = DATA.datastore.key("site", "ai")
    ai_settings = DATA.datastore.get(ai_key)
    if not ai_settings:
        ai_settings = DATA.datastore.entity(key=ai_key)

    version = int(ai_settings.get("version", 0)) + 1
    canonical = {
        key: value
        for key, value in data.items()
        if key in AI_SETTING_KEYS
    }
    ai_settings.clear()
    ai_settings.update({**canonical, "version": version})
    DATA.datastore.put(ai_settings)


SITE_EXPORT_INDEX_ID = "exports"
SITE_EXPORT_PREFIX = "export:"
SITE_EXPORT_INDEX_LIMIT = 25
SITE_EXPORT_EXCLUDE_FROM_INDEXES = (
    "command",
    "entrypoint",
    "error",
    "manifest_path",
    "prefix",
    "readme_path",
    "storage_uri",
    "warnings",
)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::create_site_export
# @reason timestamp defaulting is covered through export metadata creation/update
def _now():
    return datetime.datetime.now(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::site_export
# @reason key construction is covered through export metadata fetch/list helpers
def _site_export_key(export_id):
    return DATA.datastore.key(KINDS.site.value, f"{SITE_EXPORT_PREFIX}{export_id}")


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::site_exports
# @reason index key construction is covered through recent export listing
def _site_export_index_key():
    return DATA.datastore.key(KINDS.site.value, SITE_EXPORT_INDEX_ID)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::create_site_export
# @reason recent-index creation is covered through export metadata creation
def _site_export_index():
    key = _site_export_index_key()
    entity = DATA.datastore.get(key)
    if entity:
        return entity

    entity = DATA.datastore.entity(key=key)
    entity.update({"ids": []})
    return entity


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::create_site_export
# @reason entity shape is covered through export metadata creation
def _site_export_entity(export_id):
    return DATA.datastore.entity(
        key=_site_export_key(export_id),
        exclude_from_indexes=SITE_EXPORT_EXCLUDE_FROM_INDEXES,
    )


# @testable true
# @tests tests_unit/test_019_site_export.py::test_create_site_export_records_metadata_and_recent_index
# @features admin export
# @dimensions metadata create recent-index
def create_site_export(data):
    """Create a site export metadata record and add it to the recent index."""
    export_id = data.get("id") or uuid.uuid4().hex[:12]
    now = _now()
    entity = _site_export_entity(export_id)
    entity.update(
        {
            "id": export_id,
            "type": "site_export",
            "profile": data.get("profile", "html"),
            "status": data.get("status", "queued"),
            "created": data.get("created", now),
            "modified": data.get("modified", now),
            "started": data.get("started"),
            "completed": data.get("completed"),
            "prefix": data.get("prefix"),
            "storage_uri": data.get("storage_uri"),
            "entrypoint": data.get("entrypoint"),
            "manifest_path": data.get("manifest_path"),
            "readme_path": data.get("readme_path"),
            "object_count": int(data.get("object_count", 0) or 0),
            "byte_count": int(data.get("byte_count", 0) or 0),
            "warnings": data.get("warnings", []),
            "error": data.get("error"),
            "command": data.get("command"),
        }
    )

    index = _site_export_index()
    ids = [export_id, *[i for i in index.get("ids", []) if i != export_id]]
    index["ids"] = ids[:SITE_EXPORT_INDEX_LIMIT]
    DATA.datastore.put_multi([entity, index])
    return entity


# @testable true
# @tests tests_unit/test_019_site_export.py::test_update_site_export_sets_modified_timestamp_and_keeps_counts
# @features admin export
# @dimensions metadata update
def update_site_export(export_id, updates):
    """Update an existing site export metadata record."""
    entity = DATA.datastore.get(_site_export_key(export_id))
    if not entity:
        return None

    entity.exclude_from_indexes = SITE_EXPORT_EXCLUDE_FROM_INDEXES
    entity.update({**updates, "modified": _now()})
    DATA.datastore.put(entity)
    return entity


# @testable true
# @tests tests_unit/test_019_site_export.py::test_site_exports_returns_recent_records_in_index_order
# @features admin export
# @dimensions metadata list
def site_export(export_id):
    """Fetch a site export metadata record by export id."""
    return DATA.datastore.get(_site_export_key(export_id))


# @testable true
# @tests tests_unit/test_019_site_export.py::test_site_exports_returns_recent_records_in_index_order
# @features admin export
# @dimensions metadata list
def site_exports(limit=10):
    """Fetch recent site export metadata records in newest-first index order."""
    index = DATA.datastore.get(_site_export_index_key())
    ids = list(index.get("ids", [])) if index else []
    ids = ids[:limit]
    if not ids:
        return []

    keys = [_site_export_key(export_id) for export_id in ids]
    records = [record for record in DATA.datastore.get_multi(keys) if record]
    by_id = {record.get("id"): record for record in records}
    return [by_id[export_id] for export_id in ids if export_id in by_id]
