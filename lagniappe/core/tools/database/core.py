"""Google Cloud Datastore and Storage client initialization."""

from enum import Enum

from google.api_core import exceptions
from google.cloud import datastore, storage

from config import storage as storage_contract
from lagniappe import CONFIG, Config


PREFIX = CONFIG.PREFIX
BUCKET_CORS_METHODS = storage_contract.BUCKET_CORS_METHODS
BUCKET_CORS_HEADERS = storage_contract.BUCKET_CORS_HEADERS
BUCKET_CORS_MAX_AGE_SECONDS = storage_contract.BUCKET_CORS_MAX_AGE_SECONDS
BUCKET_CONFIG_RETRY_DELAYS = storage_contract.BUCKET_CONFIG_RETRY_DELAYS
BUCKET_CREATE_LOCATION = storage_contract.BUCKET_CREATE_LOCATION
BUCKET_DEFAULT_STORAGE_CLASS = storage_contract.BUCKET_DEFAULT_STORAGE_CLASS


def expected_storage_cors_origins(config: Config = CONFIG) -> list[str]:
    return storage_contract.expected_storage_cors_origins(config)


def expected_storage_cors(config: Config = CONFIG) -> list[storage_contract._CorsRule]:
    return storage_contract.expected_storage_cors(config)


def _normalized_cors(cors):
    return storage_contract._normalized_cors(cors)


def configure_storage_bucket(bucket: storage.Bucket, config: Config = CONFIG) -> bool:
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
    agent_api_credentials = f"{PREFIX}agent_api_credentials"
    mcp_oauth = f"{PREFIX}mcp_oauth"
    agent_api_plan_operation_claims = f"{PREFIX}agent_api_plan_operation_claims"

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
    agent_api_credential = agent_api_credentials
    agent_api_plan_operation_claim = agent_api_plan_operation_claims


class DataServices:
    """Lazy-initialized singleton for Datastore and Cloud Storage clients."""

    _datastore_client: datastore.Client | None = None
    _storage_client: storage.Client | None = None
    _private_bucket: storage.Bucket | None = None
    _public_bucket: storage.Bucket | None = None
    _history_bucket: storage.Bucket | None = None

    def initialize(self) -> None:
        """Create project-bound Datastore and Storage clients with shared ADC."""
        if self._datastore_client and self._storage_client:
            return

        credentials = CONFIG.google_credentials
        project = getattr(CONFIG, "GOOGLE_CLOUD_PROJECT", None)
        client_kwargs = {"project": project} if project else {}
        client_kwargs["credentials"] = credentials
        self._datastore_client = datastore.Client(**client_kwargs)
        self._storage_client = storage.Client(**client_kwargs)
        if CONFIG.EXPERIMENTS_ENABLED and CONFIG.EXPERIMENTS_DIAGNOSTICS != "off":
            from lagniappe.core.tools.measurements import instrument_datastore, instrument_storage
            instrument_datastore(self._datastore_client)
            instrument_storage(self._storage_client)

    @property
    def datastore(self) -> datastore.Client:
        """Return the Datastore client, initializing on first access."""
        if not self._datastore_client:
            self.initialize()

        assert self._datastore_client is not None
        return self._datastore_client

    @property
    def storage(self) -> storage.Client:
        """Return the Storage client, initializing on first access."""
        if not self._storage_client:
            self.initialize()

        assert self._storage_client is not None
        return self._storage_client

    def _create_bucket(self, name: str) -> storage.Bucket:
        bucket_name = f"{PREFIX}{name}"

        try:
            return self.storage.get_bucket(bucket_name)
        except exceptions.NotFound as error:
            raise RuntimeError(
                f"Required Cloud Storage bucket '{bucket_name}' is missing. "
                "Rerun setup with the installer identity before starting the app."
            ) from error

    def configure_buckets(self) -> dict[str, storage.Bucket]:
        """Verify and return all storage buckets provisioned by setup."""
        return {
            name: self._create_bucket(config_name)
            for name, config_name in (
                ("history", CONFIG.HISTORY_BUCKET),
                ("private", CONFIG.PRIVATE_BUCKET),
                ("public", CONFIG.PUBLIC_BUCKET),
            )
        }

    def bucket(self, name: str) -> storage.Bucket:
        """Return the named storage bucket (history, private, or public)."""
        if name == "history":
            return self.history_bucket
        elif name == "private":
            return self.private_bucket
        elif name == "public":
            return self.public_bucket
        else:
            raise ValueError(f"Invalid bucket name: {name}")

    def delete_buckets(self) -> None:
        """Delete test objects while preserving setup-owned bucket resources."""
        self.initialize()

        for config_name in (
            CONFIG.HISTORY_BUCKET,
            CONFIG.PRIVATE_BUCKET,
            CONFIG.PUBLIC_BUCKET,
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

    @property
    def history_bucket(self) -> storage.Bucket:
        """Return the setup-provisioned history bucket."""
        if self._history_bucket:
            return self._history_bucket

        self._history_bucket = self._create_bucket(CONFIG.HISTORY_BUCKET)
        return self._history_bucket

    @property
    def private_bucket(self) -> storage.Bucket:
        """Return the setup-provisioned private bucket."""
        if self._private_bucket:
            return self._private_bucket

        self._private_bucket = self._create_bucket(CONFIG.PRIVATE_BUCKET)
        return self._private_bucket

    @property
    def public_bucket(self) -> storage.Bucket:
        """Return the setup-provisioned public bucket."""
        if self._public_bucket:
            return self._public_bucket

        self._public_bucket = self._create_bucket(CONFIG.PUBLIC_BUCKET)
        return self._public_bucket



DATA = DataServices()
