import datetime
from io import BytesIO
from types import SimpleNamespace

import pytest

from config.storage import (
    configure_recovery_bucket,
    recovery_bucket_name,
    storage_bucket_names,
)
from lagniappe.core import exceptions
from lagniappe.core.tools.site import images as site_image
from lagniappe.core.tools.database import assets
from lagniappe.core.tools.database import core
from lagniappe.core.tools.database import site as site_database
from lagniappe.core.definitions import (
    FILE_CONSUMER_CAPABILITIES,
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
    known_file_size,
)

_DATA_SERVICES_INITIALIZE = core.DataServices.initialize


# @matrix file storage : byte-range
@pytest.mark.unit
def test_download_file_passes_optional_byte_range(monkeypatch):
    calls = []

    class Blob:
        def download_as_bytes(self, **kwargs):
            calls.append(kwargs)
            return b"chunk"

    class Bucket:
        def blob(self, path):
            calls.append({"path": path})
            return Blob()

    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda visibility: Bucket()),
    )

    assert (
        assets.download_file("files/source.pdf", "private", start=10, end=19)
        == b"chunk"
    )
    assert calls == [
        {"path": "files/source.pdf"},
        {"start": 10, "end": 19},
    ]


# @matrix file storage : byte-range metadata
@pytest.mark.unit
def test_file_size_reloads_blob_metadata(monkeypatch):
    calls = []

    class Blob:
        size = None

        def reload(self):
            calls.append("reload")
            self.size = 4096

    class Bucket:
        def blob(self, path):
            calls.append({"path": path})
            return Blob()

    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda visibility: Bucket()),
    )

    assert assets.file_size("files/source.pdf", "private") == 4096
    assert calls == [{"path": "files/source.pdf"}, "reload"]


# @matrix file storage : missing-object
@pytest.mark.unit
def test_missing_blob_download_and_size_return_none(monkeypatch):
    calls = []

    class Blob:
        def download_as_bytes(self, **kwargs):
            calls.append(("download", kwargs))
            raise assets.google_exceptions.NotFound("missing")

        def reload(self):
            calls.append(("reload",))
            raise assets.google_exceptions.NotFound("missing")

    class Bucket:
        def blob(self, path):
            calls.append(("blob", path))
            return Blob()

    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda visibility: Bucket()),
    )

    assert assets.download_file("missing.jpeg", "private") is None
    assert assets.file_size("missing.jpeg", "private") is None
    assert calls == [
        ("blob", "missing.jpeg"),
        ("download", {}),
        ("blob", "missing.jpeg"),
        ("reload",),
    ]


# @matrix storage : idempotent-delete missing-object
@pytest.mark.unit
def test_delete_file_ignores_missing_blob(monkeypatch):
    calls = []

    class Blob:
        def delete(self):
            calls.append("delete")
            raise assets.google_exceptions.NotFound("missing")

    class Bucket:
        def blob(self, path):
            calls.append(("blob", path))
            return Blob()

    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda visibility: Bucket()),
    )

    assets.delete_file("missing.jpeg", "private")
    assert calls == [("blob", "missing.jpeg"), "delete"]


# @matrix file storage : asset-size metadata
@pytest.mark.unit
def test_save_file_returns_reloaded_blob_metadata(monkeypatch):
    calls = []

    class Blob:
        size = None

        def upload_from_file(self, file, content_type=None):
            calls.append(("upload", file.read(), content_type))

        def reload(self):
            calls.append("reload")
            self.size = 2048

    class Bucket:
        def __init__(self):
            self.blob_instance = Blob()

        def blob(self, path):
            calls.append(("blob", path))
            return self.blob_instance

    bucket = Bucket()
    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda visibility: bucket),
    )
    upload = SimpleNamespace(
        seek=lambda position: calls.append(("seek", position)),
        read=lambda: b"hello",
    )

    blob = assets.save_file(upload, "files/source.pdf", "application/pdf", "private")

    assert blob is bucket.blob_instance
    assert blob.size == 2048
    assert calls == [
        ("blob", "files/source.pdf"),
        ("seek", 0),
        ("upload", b"hello", "application/pdf"),
        "reload",
    ]


# @matrix direct-upload storage : deferred-cleanup
@pytest.mark.unit
def test_save_file_preserves_direct_upload_source_when_requested(monkeypatch):
    captured = {}
    copied = object()

    def copy_upload(upload, path, visibility, content_type, *, delete_source):
        captured.update(
            {
                "upload": upload,
                "path": path,
                "visibility": visibility,
                "content_type": content_type,
                "delete_source": delete_source,
            }
        )
        return copied

    monkeypatch.setattr(assets, "copy_direct_upload_file", copy_upload)
    upload = SimpleNamespace(
        lagniappe_direct_upload=True,
        lagniappe_preserve_source=True,
    )

    assert (
        assets.save_file(upload, "files/source.pdf", "application/pdf", "private")
        is copied
    )
    assert captured == {
        "upload": upload,
        "path": "files/source.pdf",
        "visibility": "private",
        "content_type": "application/pdf",
        "delete_source": False,
    }


@pytest.mark.unit
def test_direct_upload_file_read_sample_uses_bounded_range():
    calls = []

    class Blob:
        size = 1024 * 1024

        def download_as_bytes(self, **kwargs):
            calls.append(kwargs)
            return b"sample"

    upload = assets.DirectUploadFile(
        {},
        {
            "path": "tmp/uploads/upload-id/large-video.mp4",
            "filename": "large-video.mp4",
            "content_type": "application/octet-stream",
        },
        Blob(),
    )

    assert upload.read_sample(100_000) == b"sample"
    assert calls == [{"start": 0, "end": 8191}]


# @pair files:size-limit
@pytest.mark.unit
def test_file_consumer_limits_use_metadata_before_reading():
    limit = FILE_CONSUMER_CAPABILITIES[FileConsumer.AI_INLINE].max_bytes

    class Oversized:
        size = limit + 1
        filename = "oversized.pdf"

        def read(self):
            raise AssertionError("size rejection must happen before content is read")

    with pytest.raises(
        FileConsumerLimitError,
        match=r"oversized\.pdf is too large.*Maximum size is 30 MB",
    ) as error:
        enforce_file_consumer(
            Oversized(),
            FileConsumer.AI_INLINE,
            filename="oversized.pdf",
        )

    assert error.value.size == limit + 1
    assert error.value.max_bytes == limit
    assert FILE_CONSUMER_CAPABILITIES[FileConsumer.AI_REPORT].max_bytes is None
    assert (
        enforce_file_consumer(
            Oversized(),
            FileConsumer.AI_REPORT,
            filename="oversized.pdf",
        )
        == limit + 1
    )

    stream = SimpleNamespace(
        content_length=0,
        stream=BytesIO(b"known without a read"),
    )
    stream.stream.seek(4)
    assert known_file_size(stream) == len(b"known without a read")
    assert stream.stream.tell() == 4


# @pair files:bounded-consumer
@pytest.mark.unit
def test_direct_upload_full_read_requires_named_bounded_consumer():
    downloads = []

    class Blob:
        size = 12

        def download_as_bytes(self, **kwargs):
            downloads.append(kwargs)
            return b"small upload"

    upload = assets.DirectUploadFile(
        {},
        {
            "path": "tmp/uploads/upload-id/small.pdf",
            "filename": "small.pdf",
            "content_type": "application/pdf",
        },
        Blob(),
    )

    with pytest.raises(FileConsumerLimitError, match="require a named file consumer"):
        upload.read()
    assert downloads == []

    enforce_file_consumer(upload, FileConsumer.AI_INLINE, filename=upload.filename)
    assert upload.read() == b"small upload"
    assert downloads == [{}]


# @matrix storage : cors origins
@pytest.mark.unit
def test_storage_cors_origins_include_configured_urls():
    config = SimpleNamespace(
        APP_URL="https://app.example.com/some/path",
        CUSTOM_DOMAIN="custom.example.com",
        BASE_URL="http://127.0.0.1:5050",
        local=True,
    )

    assert core.expected_storage_cors_origins(config) == [
        "http://127.0.0.1:5050",
        "https://app.example.com",
        "https://custom.example.com",
    ]


# @matrix disaster-recovery setup storage : naming
@pytest.mark.unit
def test_storage_bucket_names_match_runtime_contract():
    settings = {
        "GIBBERISH": "stable-secret",
        "PREFIX": "test-",
    }
    names = storage_bucket_names(settings)
    recovery = recovery_bucket_name(settings)

    assert set(names) == {"history", "private", "public"}
    assert all(name.startswith("test-") for name in names.values())
    assert all(len(name) == 37 for name in names.values())
    assert names["public"].startswith("test-public-")
    assert recovery.startswith("test-recovery-")
    assert len(recovery) == 37
    assert recovery not in names.values()


# @matrix disaster-recovery : bucket-metadata lifecycle-preservation
@pytest.mark.unit
def test_configure_recovery_bucket_removes_cors_and_is_idempotent():
    lifecycle = [{"action": {"type": "Delete"}, "condition": {"age": 365}}]

    class Bucket:
        storage_class = "NEARLINE"
        cors = [{"origin": ["https://runtime.example.test"]}]
        lifecycle_rules = lifecycle
        retention_period = 86400
        soft_delete_policy = SimpleNamespace(retention_duration_seconds=604800)
        iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=False)
        patches = 0

        def patch(self):
            self.patches += 1

    bucket = Bucket()

    assert configure_recovery_bucket(bucket) is True
    assert bucket.storage_class == "STANDARD"
    assert bucket.cors == []
    assert bucket.iam_configuration.uniform_bucket_level_access_enabled is True
    assert bucket.lifecycle_rules is lifecycle
    assert bucket.retention_period == 86400
    assert bucket.soft_delete_policy.retention_duration_seconds == 604800
    assert bucket.patches == 1
    assert configure_recovery_bucket(bucket) is False
    assert bucket.patches == 1


# @pair storage:cors
@pytest.mark.unit
def test_expected_storage_cors_shape():
    config = SimpleNamespace(
        APP_URL="https://app.example.com",
        CUSTOM_DOMAIN=None,
        local=False,
    )

    assert core.expected_storage_cors(config) == [
        {
            "origin": ["https://app.example.com"],
            "method": ["GET", "HEAD", "POST", "PUT"],
            "responseHeader": [
                "Content-Type",
                "Content-Range",
                "Range",
                "X-Goog-Resumable",
                "X-Goog-Meta-*",
            ],
            "maxAgeSeconds": 3600,
        }
    ]


# @matrix storage : cors idempotent
@pytest.mark.unit
def test_storage_cors_comparison_is_order_insensitive():
    left = [
        {
            "origin": ["https://b.example", "https://a.example"],
            "method": ["PUT", "GET"],
            "responseHeader": ["Range", "Content-Type"],
            "maxAgeSeconds": 3600,
        }
    ]
    right = [
        {
            "origin": ["https://a.example", "https://b.example"],
            "method": ["GET", "PUT"],
            "responseHeader": ["Content-Type", "Range"],
            "maxAgeSeconds": 3600,
        }
    ]

    assert core._normalized_cors(left) == core._normalized_cors(right)


# @matrix storage : cors idempotent
@pytest.mark.unit
def test_configure_bucket_is_idempotent():
    config = SimpleNamespace(
        APP_URL="https://app.example.com",
        CUSTOM_DOMAIN=None,
        local=False,
    )
    expected = core.expected_storage_cors(config)

    class Bucket:
        storage_class = "STANDARD"
        versioning_enabled = True
        lifecycle_rules = [
            {
                "action": {"type": "Delete"},
                "condition": {"daysSinceNoncurrentTime": 98},
            }
        ]
        cors = [
            {
                "origin": list(reversed(expected[0]["origin"])),
                "method": list(reversed(expected[0]["method"])),
                "responseHeader": list(reversed(expected[0]["responseHeader"])),
                "maxAgeSeconds": expected[0]["maxAgeSeconds"],
            }
        ]
        iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=True)

        def patch(self):
            raise AssertionError("patch should not be called")

    assert core.configure_storage_bucket(Bucket(), config=config) is False


# @matrix storage : cors idempotent
@pytest.mark.unit
def test_configure_bucket_repairs_cors_drift():
    config = SimpleNamespace(
        APP_URL="https://app.example.com",
        CUSTOM_DOMAIN=None,
        local=False,
    )
    patches = []

    class Bucket:
        storage_class = "STANDARD"
        versioning_enabled = True
        lifecycle_rules = [
            {
                "action": {"type": "Delete"},
                "condition": {"daysSinceNoncurrentTime": 98},
            }
        ]
        cors = []
        iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=False)

        def patch(self):
            patches.append(
                {
                    "cors": self.cors,
                    "uniform": (
                        self.iam_configuration.uniform_bucket_level_access_enabled
                    ),
                }
            )

    bucket = Bucket()

    assert core.configure_storage_bucket(bucket, config=config) is True
    assert bucket.cors == core.expected_storage_cors(config)
    assert bucket.iam_configuration.uniform_bucket_level_access_enabled is True
    assert patches == [{"cors": bucket.cors, "uniform": True}]


# @matrix storage : bucket-metadata lifecycle-preservation object-versioning storage-class
@pytest.mark.unit
def test_configure_bucket_enables_versioning_and_reconciles_noncurrent_lifecycle():
    config = SimpleNamespace(
        APP_URL="https://app.example.com",
        CUSTOM_DOMAIN=None,
        local=False,
    )
    lifecycle = [
        {"action": {"type": "Delete"}, "condition": {"age": 365}},
        {
            "action": {"type": "Delete"},
            "condition": {"daysSinceNoncurrentTime": 7},
        },
        {
            "action": {"type": "Delete"},
            "condition": {
                "daysSinceNoncurrentTime": 30,
                "matchesPrefix": ["user-owned/"],
            },
        },
    ]
    patches = []

    class Bucket:
        storage_class = "NEARLINE"
        versioning_enabled = False
        cors = core.expected_storage_cors(config)
        lifecycle_rules = lifecycle
        retention_period = 86400
        soft_delete_policy = SimpleNamespace(retention_duration_seconds=604800)
        iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=True)

        def patch(self):
            patches.append(self.storage_class)

    bucket = Bucket()

    assert core.configure_storage_bucket(bucket, config=config) is True
    assert bucket.storage_class == core.BUCKET_DEFAULT_STORAGE_CLASS
    assert bucket.versioning_enabled is True
    assert bucket.lifecycle_rules == [
        {"action": {"type": "Delete"}, "condition": {"age": 365}},
        {
            "action": {"type": "Delete"},
            "condition": {
                "daysSinceNoncurrentTime": 30,
                "matchesPrefix": ["user-owned/"],
            },
        },
        {
            "action": {"type": "Delete"},
            "condition": {"daysSinceNoncurrentTime": 98},
        },
    ]
    assert bucket.retention_period == 86400
    assert bucket.soft_delete_policy.retention_duration_seconds == 604800
    assert patches == ["STANDARD"]


# @matrix storage : bucket-metadata transient-retry
@pytest.mark.unit
def test_configure_bucket_retries_transient_patch_failure(monkeypatch):
    config = SimpleNamespace(
        APP_URL="https://app.example.com",
        CUSTOM_DOMAIN=None,
        local=False,
    )
    sleeps = []
    warnings = []
    patch_attempts = []
    monkeypatch.setattr(
        core.storage_contract.time,
        "sleep",
        lambda delay: sleeps.append(delay),
    )
    monkeypatch.setattr(
        core.storage_contract.LOGGER,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    class Bucket:
        storage_class = "STANDARD"
        versioning_enabled = True
        lifecycle_rules = [
            {
                "action": {"type": "Delete"},
                "condition": {"daysSinceNoncurrentTime": 98},
            }
        ]
        cors = []
        iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=True)

        def patch(self):
            patch_attempts.append(self.cors)
            if len(patch_attempts) == 1:
                raise core.exceptions.ServiceUnavailable(
                    "Cloud Storage temporarily unavailable"
                )

    bucket = Bucket()

    assert core.configure_storage_bucket(bucket, config=config) is True
    assert bucket.cors == core.expected_storage_cors(config)
    assert len(patch_attempts) == 2
    assert sleeps == [core.BUCKET_CONFIG_RETRY_DELAYS[0]]
    assert warnings[0][1]["exc_info"] is True


# @matrix database storage : adc
@pytest.mark.unit
def test_data_services_initialize_uses_shared_adc(monkeypatch):
    credentials = object()
    datastore_clients = []
    storage_clients = []
    monkeypatch.setattr(
        type(core.CONFIG),
        "google_credentials",
        property(lambda self: credentials),
    )
    monkeypatch.setattr(
        core.datastore,
        "Client",
        lambda **kwargs: datastore_clients.append(kwargs) or object(),
    )
    monkeypatch.setattr(
        core.storage,
        "Client",
        lambda **kwargs: storage_clients.append(kwargs) or object(),
    )
    monkeypatch.setattr(
        core.DataServices,
        "initialize",
        _DATA_SERVICES_INITIALIZE,
    )

    data = core.DataServices()
    data._datastore_client = None
    data._storage_client = None
    data.initialize()
    data.initialize()

    expected = {
        "project": core.CONFIG.GOOGLE_CLOUD_PROJECT,
        "credentials": credentials,
    }
    assert datastore_clients == [expected]
    assert storage_clients == [expected]


# @matrix storage : adc iam-signing signed-url token-refresh
@pytest.mark.unit
def test_signed_url_uses_remote_iam_signing(monkeypatch):
    from lagniappe.core.tools.database import assets

    calls = []
    blob = SimpleNamespace(
        generate_signed_url=lambda **kwargs: (
            calls.append(kwargs) or "https://storage.example.test/signed"
        )
    )
    monkeypatch.setattr(
        assets.DATA,
        "_private_bucket",
        SimpleNamespace(blob=lambda path: blob),
    )
    monkeypatch.setattr(
        assets,
        "CONFIG",
        SimpleNamespace(
            google_credentials="adc",
            RUNTIME_SERVICE_ACCOUNT_EMAIL="runtime@project-1.iam.gserviceaccount.com",
            google_access_token=lambda: "fresh-token",
        ),
    )

    assert (
        assets.get_signed_url(
            "private/file.txt",
            expires_in=900,
            response_disposition="attachment",
            response_type="text/plain",
        )
        == "https://storage.example.test/signed"
    )
    assert calls == [
        {
            "version": "v4",
            "expiration": datetime.timedelta(seconds=900),
            "method": "GET",
            "credentials": "adc",
            "service_account_email": ("runtime@project-1.iam.gserviceaccount.com"),
            "access_token": "fresh-token",
            "response_disposition": "attachment",
            "response_type": "text/plain",
        }
    ]


# @matrix iam storage : provisioning-boundary runtime
@pytest.mark.unit
def test_runtime_storage_only_reads_setup_provisioned_buckets():
    bucket = SimpleNamespace(name="public-bucket")
    calls = []

    class Storage:
        def get_bucket(self, name):
            calls.append(("get", name))
            if name.endswith("missing"):
                raise core.exceptions.NotFound("missing")
            return bucket

        def create_bucket(self, name):
            raise AssertionError("runtime must not create buckets")

    data = core.DataServices()
    data._storage_client = Storage()
    data._public_bucket = None

    assert data._create_bucket("public-bucket") is bucket
    assert data.bucket("public") is bucket
    assert calls == [
        ("get", f"{core.PREFIX}public-bucket"),
        ("get", f"{core.PREFIX}{core.CONFIG.PUBLIC_BUCKET}"),
    ]

    with pytest.raises(RuntimeError, match="Rerun setup with the installer"):
        data._create_bucket("missing")


# @matrix iam storage : provisioning-boundary test-cleanup
@pytest.mark.unit
def test_test_cleanup_deletes_objects_without_deleting_buckets():
    deleted = []

    class Blob:
        def __init__(self, name):
            self.name = name

        def delete(self):
            deleted.append(self.name)

    class Bucket:
        def __init__(self, name):
            self.name = name

        def list_blobs(self):
            return [Blob(f"{self.name}/one"), Blob(f"{self.name}/two")]

        def delete(self, **kwargs):
            raise AssertionError("test cleanup must preserve buckets")

    class Storage:
        def get_bucket(self, name):
            return Bucket(name)

    data = core.DataServices()
    data._datastore_client = object()
    data._storage_client = Storage()
    data._history_bucket = object()
    data._private_bucket = object()
    data._public_bucket = object()
    data.initialize = lambda: None

    data.delete_buckets()

    assert len(deleted) == 6
    assert all(name.startswith(core.PREFIX) for name in deleted)
    assert data._history_bucket is None
    assert data._private_bucket is None
    assert data._public_bucket is None


# @matrix storage : direct-upload session token
@pytest.mark.unit
def test_create_direct_upload_session_uses_private_tmp_object(monkeypatch):
    calls = []

    class Blob:
        def __init__(self, path):
            self.path = path

        def create_resumable_upload_session(self, **kwargs):
            calls.append({"path": self.path, **kwargs})
            return "https://storage.example/session"

    class Bucket:
        def blob(self, path):
            return Blob(path)

    monkeypatch.setattr(assets.uuid, "uuid4", lambda: SimpleNamespace(hex="abc123"))
    monkeypatch.setattr(assets, "DATA", SimpleNamespace(private_bucket=Bucket()))

    session = assets.create_direct_upload_session(
        "unsafe name.csv",
        content_type="text/csv",
        size="42",
        input_name="ingress-file",
        origin="https://app.example.com",
    )
    payload = assets.load_direct_upload_token(session["token"])

    assert session["session_url"] == "https://storage.example/session"
    assert session["chunk_size"] == assets.DIRECT_UPLOAD_CHUNK_SIZE
    assert payload == {
        "path": "tmp/uploads/abc123/unsafe_name.csv",
        "visibility": "private",
        "filename": "unsafe name.csv",
        "content_type": "text/csv",
        "size": 42,
        "input_name": "ingress-file",
    }
    assert calls == [
        {
            "path": "tmp/uploads/abc123/unsafe_name.csv",
            "content_type": "text/csv",
            "size": 42,
            "origin": "https://app.example.com",
            "if_generation_match": 0,
        }
    ]


# @matrix storage : direct-upload token validation
@pytest.mark.unit
def test_verify_direct_upload_rejects_bad_token():
    with pytest.raises(assets.DirectUploadError, match="Invalid direct upload token"):
        assets.verify_direct_upload({"token": "not-valid"})


def _direct_upload_token(**overrides):
    payload = {
        "path": "tmp/uploads/upload-1/file.txt",
        "visibility": "private",
        "filename": "file.txt",
        "content_type": "text/plain",
        "size": 10,
        "input_name": "file-upload",
    }
    payload.update(overrides)
    return assets._direct_upload_serializer().dumps(payload)


# @matrix storage : direct-upload object validation
@pytest.mark.unit
def test_verify_direct_upload_rejects_mismatched_size(monkeypatch):
    class Blob:
        size = 9
        content_type = "text/plain"
        generation = "7"

        def reload(self):
            pass

    class Bucket:
        def blob(self, path):
            return Blob()

    monkeypatch.setattr(assets, "DATA", SimpleNamespace(bucket=lambda name: Bucket()))

    with pytest.raises(assets.DirectUploadError, match="size mismatch"):
        assets.verify_direct_upload(
            {
                "token": _direct_upload_token(),
                "input_name": "file-upload",
                "path": "tmp/uploads/upload-1/file.txt",
                "generation": "7",
            }
        )


# @matrix storage : direct-upload object validation
@pytest.mark.unit
def test_verify_direct_upload_rejects_generation_mismatch(monkeypatch):
    class Blob:
        size = 10
        content_type = "text/plain"
        generation = "7"

        def reload(self):
            pass

    class Bucket:
        def blob(self, path):
            return Blob()

    monkeypatch.setattr(assets, "DATA", SimpleNamespace(bucket=lambda name: Bucket()))

    with pytest.raises(assets.DirectUploadError, match="generation mismatch"):
        assets.verify_direct_upload(
            {
                "token": _direct_upload_token(),
                "input_name": "file-upload",
                "path": "tmp/uploads/upload-1/file.txt",
                "generation": "8",
            }
        )


# @pair storage:object
# @pair storage:generation-conditional-cleanup
# @source lagniappe/core/tools/database/assets.py::delete_direct_upload
@pytest.mark.unit
def test_verified_direct_upload_pins_generation_for_later_cleanup(monkeypatch):
    calls = []

    class Blob:
        size = 10
        content_type = "text/plain"
        generation = "7"

        def reload(self):
            pass

        def delete(self, **options):
            calls.append(options)
            if int(options["if_generation_match"]) != int(self.generation):
                raise assets.google_exceptions.PreconditionFailed("replaced")

    blob = Blob()
    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(
            bucket=lambda _name: SimpleNamespace(blob=lambda _path: blob)
        ),
    )
    record = {
        "token": _direct_upload_token(),
        "input_name": "file-upload",
        "path": "tmp/uploads/upload-1/file.txt",
    }

    assets.verify_direct_upload(record)
    assert record["generation"] == "7"

    blob.generation = "8"
    assert assets.delete_direct_upload(record) is False
    assert calls == [{"if_generation_match": 7}]


# @matrix storage : direct-upload final-copy
@pytest.mark.unit
def test_copy_direct_upload_file_copies_and_deletes_temp_object(monkeypatch):
    calls = []

    class Blob:
        size = 10
        content_type = "text/plain"
        generation = "7"

        def reload(self):
            pass

        def delete(self):
            calls.append("delete-source")

    class CopiedBlob:
        content_type = "text/plain"
        generation = "11"

        def patch(self, **options):
            calls.append(("patch-copy", options))

    class Bucket:
        def __init__(self, name):
            self.name = name

        def blob(self, path):
            calls.append(("blob", self.name, path))
            return Blob()

        def copy_blob(self, blob, destination_bucket, path, **options):
            calls.append(
                (
                    "copy",
                    self.name,
                    destination_bucket.name,
                    path,
                    blob,
                    options,
                )
            )
            return CopiedBlob()

    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda name: Bucket(name)),
    )

    upload = assets.verify_direct_upload(
        {
            "token": _direct_upload_token(),
            "input_name": "file-upload",
            "path": "tmp/uploads/upload-1/file.txt",
            "generation": "7",
        }
    )
    copied = assets.copy_direct_upload_file(
        upload,
        "entity_file.txt",
        "private",
        content_type="application/pdf",
    )

    assert upload.lagniappe_saved_blob is copied
    assert copied.content_type == "application/pdf"
    assert calls[:3] == [
        ("blob", "private", "tmp/uploads/upload-1/file.txt"),
        (
            "copy",
            "private",
            "private",
            "entity_file.txt",
            upload.blob,
            {
                "source_generation": 7,
                "if_source_generation_match": 7,
                "if_generation_match": 0,
            },
        ),
        ("patch-copy", {"if_generation_match": 11}),
    ]
    assert calls[3:] == ["delete-source"]

    calls.clear()
    assets.copy_direct_upload_file(
        upload,
        "entity_file.txt",
        "private",
        content_type="application/pdf",
        delete_source=False,
    )
    assert "delete-source" not in calls


# @source lagniappe/core/tools/database/assets.py::copy_direct_upload_file
# @pair storage:final-copy
@pytest.mark.unit
def test_copy_direct_upload_registers_destination_before_metadata_patch(monkeypatch):
    class SourceBlob:
        generation = "7"

    class CopiedBlob:
        content_type = "application/octet-stream"
        generation = "11"

        def patch(self, **_options):
            raise RuntimeError("metadata patch failed")

    copied = CopiedBlob()
    bucket = SimpleNamespace(copy_blob=lambda *_args, **_kwargs: copied)
    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(bucket=lambda _visibility: bucket),
    )
    upload = SimpleNamespace(
        blob=SourceBlob(),
        visibility="private",
        lagniappe_saved_blob=None,
        lagniappe_saved_destination=None,
    )

    with pytest.raises(RuntimeError, match="metadata patch failed"):
        assets.copy_direct_upload_file(
            upload,
            "filehash_attempt.pdf",
            "private",
            content_type="application/pdf",
            delete_source=False,
        )

    assert upload.lagniappe_saved_blob is copied
    assert upload.lagniappe_saved_destination == {
        "path": "filehash_attempt.pdf",
        "visibility": "private",
        "generation": "11",
    }


# @matrix direct-upload storage : attempt-isolation destination-path
@pytest.mark.unit
def test_direct_upload_attempt_path_is_unique_and_validated():
    upload = SimpleNamespace(lagniappe_asset_nonce="a" * 32)
    assert assets.direct_upload_destination_path("filehash_file.pdf", upload) == (
        f"filehash_file_{'a' * 32}.pdf"
    )
    assert assets.direct_upload_destination_path(
        "extensionless",
        upload,
    ) == f"extensionless_{'a' * 32}"
    assert assets.direct_upload_destination_path(
        "ordinary.pdf",
        SimpleNamespace(),
    ) == "ordinary.pdf"

    upload.lagniappe_asset_nonce = "../unsafe"
    with pytest.raises(assets.DirectUploadError, match="identity is invalid"):
        assets.direct_upload_destination_path("ordinary.pdf", upload)


# @matrix storage : attempt-isolation generation-conditional-cleanup
@pytest.mark.unit
def test_delete_file_generation_never_deletes_a_replacement(monkeypatch):
    calls = []

    class Blob:
        def __init__(self, replaced=False):
            self.replaced = replaced

        def delete(self, **options):
            calls.append(options)
            if self.replaced:
                raise assets.google_exceptions.PreconditionFailed("replaced")

    current = Blob()
    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(
            bucket=lambda _visibility: SimpleNamespace(blob=lambda _path: current)
        ),
    )
    assert assets.delete_file_generation("attempt.pdf", "private", "17") is True
    assert calls == [{"if_generation_match": 17}]

    current = Blob(replaced=True)
    assert assets.delete_file_generation("attempt.pdf", "private", 17) is False
    assert calls[-1] == {"if_generation_match": 17}


# @matrix direct-upload storage : cleanup generation-conditional-cleanup idempotency
@pytest.mark.unit
def test_delete_direct_upload_is_idempotent_and_generation_conditional(monkeypatch):
    calls = []

    class Blob:
        generation = "7"

        def delete(self, **options):
            calls.append(options)

    current = Blob()
    monkeypatch.setattr(
        assets,
        "DATA",
        SimpleNamespace(
            bucket=lambda _visibility: SimpleNamespace(blob=lambda _path: current)
        ),
    )
    record = {
        "token": _direct_upload_token(),
        "path": "tmp/uploads/upload-1/file.txt",
        "input_name": "file-upload",
        "generation": "7",
    }

    assert assets.delete_direct_upload(record) is True
    assert calls == [{"if_generation_match": 7}]

    def missing(**_options):
        raise assets.google_exceptions.NotFound("already gone")

    current.delete = missing
    assert assets.delete_direct_upload(record) is True

    def replaced(**_options):
        raise assets.google_exceptions.PreconditionFailed("replaced")

    current.delete = replaced
    assert assets.delete_direct_upload(record) is False


# @matrix admin : metadata site-image-upload
@pytest.mark.unit
def test_save_site_image_persists_version_without_mutating_input(monkeypatch):
    saved = []

    class Datastore:
        def key(self, *parts):
            return parts

        def get(self, key):
            return {"version": 4}

        def entity(self, key):
            return {}

        def put(self, entity):
            saved.append(dict(entity))

    monkeypatch.setattr(site_database, "DATA", SimpleNamespace(datastore=Datastore()))

    image_data = {"favicon-32x32.png": "favicon-32x32.png"}
    site_database.save_image(image_data)

    assert image_data == {"favicon-32x32.png": "favicon-32x32.png"}
    assert saved == [{"favicon-32x32.png": "favicon-32x32.png", "version": 5}]


# @pair admin:site-image-upload
@pytest.mark.unit
def test_site_image_rejects_oversized_input_before_decode():
    upload = SimpleNamespace(
        filename="oversized.png",
        size=100 * 1024 * 1024 + 1,
        stream=SimpleNamespace(
            seek=lambda *_args: (_ for _ in ()).throw(
                AssertionError("oversized image must not be decoded")
            )
        ),
    )

    with pytest.raises(
        exceptions.SiteImageError,
        match=r"oversized\.png is too large for site image processing",
    ):
        site_image.create_site_image(upload)


# @matrix admin : deployment-settings metadata
@pytest.mark.unit
def test_save_site_deployment_persists_canonical_payload_and_prunes_old_keys(
    monkeypatch,
):
    saved = []

    class Datastore:
        def key(self, *parts):
            return parts

        def get(self, key):
            return {
                "version": 2,
                "instance_class": "F2",
                "scaling_type": "automatic",
                "unrelated": "remove-me",
            }

        def entity(self, key):
            return {}

        def put(self, entity):
            saved.append(dict(entity))

    monkeypatch.setattr(site_database, "DATA", SimpleNamespace(datastore=Datastore()))

    deployment_data = {
        "DEPLOY_SCALING_TYPE": "basic",
        "DEPLOY_WORKER_COUNT": "2",
        "DEPLOY_INSTANCE_CLASS": "B2",
        "DEPLOY_MAX_INSTANCES": "1",
        "DEPLOY_MIN_IDLE_INSTANCES": "0",
        "DEPLOY_IDLE_TIMEOUT": "15m",
    }
    site_database.save_deployment(deployment_data)

    assert deployment_data == {
        "DEPLOY_SCALING_TYPE": "basic",
        "DEPLOY_WORKER_COUNT": "2",
        "DEPLOY_INSTANCE_CLASS": "B2",
        "DEPLOY_MAX_INSTANCES": "1",
        "DEPLOY_MIN_IDLE_INSTANCES": "0",
        "DEPLOY_IDLE_TIMEOUT": "15m",
    }
    assert saved == [
        {
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_WORKER_COUNT": "2",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MAX_INSTANCES": "1",
            "DEPLOY_MIN_IDLE_INSTANCES": "0",
            "DEPLOY_IDLE_TIMEOUT": "15m",
            "version": 3,
        }
    ]


# @matrix admin : ai-settings metadata
@pytest.mark.unit
def test_save_site_ai_persists_canonical_payload_and_prunes_old_keys(monkeypatch):
    saved = []

    class Datastore:
        def key(self, *parts):
            return parts

        def get(self, key):
            return {
                "version": 2,
                "AI_MODEL": "old-primary",
                "unrelated": "remove-me",
            }

        def entity(self, key):
            return {}

        def put(self, entity):
            saved.append(dict(entity))

    monkeypatch.setattr(site_database, "DATA", SimpleNamespace(datastore=Datastore()))

    ai_data = {
        "AI_MODEL": "gemini-3.5-flash",
        "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
        "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
        "AI_LOCATION": "global",
        "unrelated": "ignored",
    }
    site_database.save_ai(ai_data)

    assert ai_data["unrelated"] == "ignored"
    assert saved == [
        {
            "AI_MODEL": "gemini-3.5-flash",
            "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
            "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
            "AI_LOCATION": "global",
            "version": 3,
        }
    ]


# @matrix admin : metadata public-page-indexing
@pytest.mark.unit
def test_save_site_public_pages_persists_canonical_payload(monkeypatch):
    saved = []

    class Datastore:
        def key(self, *parts):
            return parts

        def get(self, key):
            return {"version": 7, "PUBLIC_PAGE_INDEXING": False, "old": True}

        def entity(self, key):
            return {}

        def put(self, entity):
            saved.append(dict(entity))

    monkeypatch.setattr(site_database, "DATA", SimpleNamespace(datastore=Datastore()))

    site_database.save_public_pages(
        {"PUBLIC_PAGE_INDEXING": True, "unrelated": "ignored"}
    )

    assert saved == [{"PUBLIC_PAGE_INDEXING": True, "version": 8}]
