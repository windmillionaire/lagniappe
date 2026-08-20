"""Google Cloud Datastore and Storage client initialization."""

from enum import Enum

from google.api_core import exceptions
from google.cloud import datastore, storage

from config import storage as storage_contract
from lagniappe import CONFIG


PREFIX = CONFIG.PREFIX
BUCKET_CORS_METHODS = storage_contract.BUCKET_CORS_METHODS
BUCKET_CORS_HEADERS = storage_contract.BUCKET_CORS_HEADERS
BUCKET_CORS_MAX_AGE_SECONDS = storage_contract.BUCKET_CORS_MAX_AGE_SECONDS
BUCKET_CONFIG_RETRY_DELAYS = storage_contract.BUCKET_CONFIG_RETRY_DELAYS
BUCKET_CREATE_LOCATION = storage_contract.BUCKET_CREATE_LOCATION
BUCKET_DEFAULT_STORAGE_CLASS = storage_contract.BUCKET_DEFAULT_STORAGE_CLASS


# @testable false
# @covered-by config/storage.py::expected_storage_cors_origins
# @reason compatibility wrapper for the shared setup/runtime storage contract
def expected_storage_cors_origins(config=CONFIG):
    return storage_contract.expected_storage_cors_origins(config)


# @testable false
# @covered-by config/storage.py::expected_storage_cors
# @reason compatibility wrapper for the shared setup/runtime storage contract
def expected_storage_cors(config=CONFIG):
    return storage_contract.expected_storage_cors(config)


# @testable false
# @covered-by config/storage.py::_normalized_cors
# @reason compatibility wrapper retained for existing runtime callers
def _normalized_cors(cors):
    return storage_contract._normalized_cors(cors)


# @testable false
# @covered-by config/storage.py::configure_storage_bucket
# @reason compatibility wrapper for the shared setup/runtime storage contract
def configure_storage_bucket(bucket, config=CONFIG):
    return storage_contract.configure_storage_bucket(bucket, config)


class KINDS(Enum):
    """Datastore kind names, mapping entity types to prefixed kind strings."""

    users = f"{PREFIX}users"
    models = f"{PREFIX}models"
    instances = f"{PREFIX}instances"
    files = f"{PREFIX}files"
    filters = f"{PREFIX}filters"
    history = f"{PREFIX}history"
    activity = f"{PREFIX}activity"
    analytics = f"{PREFIX}analytics"
    ai_observability = f"{PREFIX}ai_observability"
    site = f"{PREFIX}site"
    jobs = f"{PREFIX}jobs"
    job_locks = f"{PREFIX}job_locks"
    message_conversations = f"{PREFIX}message_conversations"
    messages = f"{PREFIX}messages"
    mention_markers = f"{PREFIX}mention_markers"
    email_deliveries = f"{PREFIX}email_deliveries"

    page = instances
    group = models
    public_group = models
    project = models
    task = instances
    category = models
    form = models
    file = files
    ingress = files
    model = models
    user = users
    filter = filters
    note = activity
    notification = activity
    report = activity
    task_history = history
    form_history = history
    document_history = history
    job = jobs
    job_lock = job_locks
    message_conversation = message_conversations
    message = messages
    mention_marker = mention_markers
    email_delivery = email_deliveries


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_data_services_initialize_uses_shared_adc
# @features database storage
class DataServices:
    """Lazy-initialized singleton for Datastore and Cloud Storage clients."""

    _datastore_client = None
    _storage_client = None
    _private_bucket = None
    _public_bucket = None
    _history_bucket = None
    _export_bucket = None

    # @testable true
    # @tests tests_unit/test_018_database_assets.py::test_data_services_initialize_uses_shared_adc
    # @features database storage
    # @dimensions adc
    def initialize(self):
        """Create project-bound Datastore and Storage clients with shared ADC."""
        if self._datastore_client and self._storage_client:
            return

        credentials = CONFIG.google_credentials
        project = getattr(CONFIG, "GOOGLE_CLOUD_PROJECT", None)
        client_kwargs = {"project": project} if project else {}
        client_kwargs["credentials"] = credentials

        self._datastore_client = datastore.Client(**client_kwargs)
        self._storage_client = storage.Client(**client_kwargs)

    @property
    def datastore(self):
        """Return the Datastore client, initializing on first access."""
        if not self._datastore_client:
            self.initialize()

        return self._datastore_client

    @property
    def storage(self):
        """Return the Storage client, initializing on first access."""
        if not self._storage_client:
            self.initialize()

        return self._storage_client

    # @testable true
    # @tests tests_unit/test_018_database_assets.py::test_runtime_storage_only_reads_setup_provisioned_buckets
    # @features storage iam
    # @dimensions runtime provisioning-boundary
    def _create_bucket(self, name):
        bucket_name = f"{PREFIX}{name}"

        try:
            return self.storage.get_bucket(bucket_name)
        except exceptions.NotFound as error:
            raise RuntimeError(
                f"Required Cloud Storage bucket '{bucket_name}' is missing. "
                "Rerun setup with the installer identity before starting the app."
            ) from error

    # @testable false
    # @covered-by lagniappe/core/tools/database/core.py::configure_storage_bucket
    # @reason setup/runtime bucket iteration is thin plumbing over the tested helper
    def configure_buckets(self):
        """Verify and return all storage buckets provisioned by setup."""
        return {
            name: self._create_bucket(config_name)
            for name, config_name in (
                ("history", CONFIG.HISTORY_BUCKET),
                ("private", CONFIG.PRIVATE_BUCKET),
                ("public", CONFIG.PUBLIC_BUCKET),
                ("export", CONFIG.EXPORT_BUCKET),
            )
        }

    # @testable true
    # @tests tests_unit/test_018_database_assets.py::test_runtime_storage_only_reads_setup_provisioned_buckets
    # @features storage
    # @dimensions runtime provisioning-boundary
    def bucket(self, name):
        """Return the named storage bucket (history, private, or public)."""
        if name == "history":
            return self.history_bucket
        elif name == "private":
            return self.private_bucket
        elif name == "public":
            return self.public_bucket
        elif name == "export":
            return self.export_bucket
        else:
            raise ValueError(f"Invalid bucket name: {name}")

    # @testable true
    # @tests tests_unit/test_018_database_assets.py::test_test_cleanup_deletes_objects_without_deleting_buckets
    # @features storage iam
    # @dimensions test-cleanup provisioning-boundary
    def delete_buckets(self):
        """Delete test objects while preserving setup-owned bucket resources."""
        self.initialize()

        for config_name in (
            CONFIG.HISTORY_BUCKET,
            CONFIG.PRIVATE_BUCKET,
            CONFIG.PUBLIC_BUCKET,
            CONFIG.EXPORT_BUCKET,
        ):
            bucket_name = f"{PREFIX}{config_name}"
            try:
                bucket = self.storage.get_bucket(bucket_name)
                for blob in bucket.list_blobs():
                    blob.delete()
            except exceptions.NotFound:
                pass

        self._history_bucket = None
        self._private_bucket = None
        self._public_bucket = None
        self._export_bucket = None

    @property
    def history_bucket(self):
        """Return the setup-provisioned history bucket."""
        if self._history_bucket:
            return self._history_bucket

        self._history_bucket = self._create_bucket(CONFIG.HISTORY_BUCKET)
        return self._history_bucket

    @property
    def private_bucket(self):
        """Return the setup-provisioned private bucket."""
        if self._private_bucket:
            return self._private_bucket

        self._private_bucket = self._create_bucket(CONFIG.PRIVATE_BUCKET)
        return self._private_bucket

    @property
    def public_bucket(self):
        """Return the setup-provisioned public bucket."""
        if self._public_bucket:
            return self._public_bucket

        self._public_bucket = self._create_bucket(CONFIG.PUBLIC_BUCKET)
        return self._public_bucket

    @property
    def export_bucket(self):
        """Return the setup-provisioned export bucket."""
        if self._export_bucket:
            return self._export_bucket

        self._export_bucket = self._create_bucket(CONFIG.EXPORT_BUCKET)
        return self._export_bucket


DATA = DataServices()
