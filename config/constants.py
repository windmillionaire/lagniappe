SENTRY_DSN = "https://6ad2f168c5abc9f35de261d98b588633@o4511027028033536.ingest.us.sentry.io/4511218693242880"
SENTRY_JS_DSN = "https://48fea2b31b65f353ee375b95ffcc6884@o4511027028033536.ingest.us.sentry.io/4511218663292928"
BUILD_ID = "bba93930"
RUNTIME = "python314"
DEFAULT_EXPIRATION = "31536000s"
DEFAULT_APP_ENGINE_LOCATION = "us-central"
DEFAULT_RESOURCE_REGION = "us-central1"
UNSUPPORTED_SETTING_KEYS = frozenset(
    {
        "CREDENTIALS",
        "FIREBASE_AUTH_ENABLED",
        "REGION",
        "TASK_OIDC_SERVICE_ACCOUNT_EMAIL",
    }
)
DEFAULT_OCR_LOCATION = "us"
DEFAULT_AI_MODEL = "gemini-3.7-flash"
DEFAULT_UTILITY_AI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_AI_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_AI_LOCATION = "global"
DEFAULT_TASK_QUEUE_NAME = "lagniappe-tasks"
DEFAULT_DEFERRED_JOB_RECONCILER_NAME = "lagniappe-deferred-jobs-reconciler"
DEFAULT_DEFERRED_JOB_RECONCILER_SCHEDULE = "*/5 * * * *"
GUNICORN_TIMEOUT_SECONDS = 60 * 60
AUTOMATIC_INBOUND_SERVICES = ("warmup",)
DEFAULT_OCR_PROCESSOR_NAME = "lagniappe-document-processor"
DEFAULT_ANALYTICS_ENABLED = True
DEFAULT_GOOGLE_SIGNIN_ENABLED = True
DEFAULT_BOOTSTRAP_ADMIN_EMAIL = ""
DEFAULT_AI_OBSERVABILITY_ENABLED = False
DEFAULT_ERROR_MONITORING_ENABLED = False
DEFAULT_SENTRY_TRACES_SAMPLE_RATE = 1.0
DEFAULT_SENTRY_PROFILE_SESSION_SAMPLE_RATE = 1.0
DEFAULT_PUBLIC_MANUAL = False
DEFAULT_PUBLIC_PAGE_INDEXING = False
DEFAULT_SOURCE_URL = "https://github.com/windmillionaire/lagniappe"
DEFAULT_REDIS_TLS_ENABLED = False
REDIS_CA_CERT_RELATIVE_PATH = "config/files/redis_ca.pem"
DEFAULT_AGENT_ACCESS_ENABLED = False
DEFAULT_AGENT_ACCESS_EMAIL = "agent@localhost"
DEFAULT_AGENT_ACCESS_NAME = "Agent"
DEFAULT_AGENT_ACCESS_TEST_CODE = "agent-test-code"

DEFAULT_DEPLOYMENT_SETTINGS = {
    "DEPLOY_SCALING_TYPE": "basic",
    "DEPLOY_MAX_INSTANCES": "1",
    "DEPLOY_IDLE_TIMEOUT": "15m",
    "DEPLOY_WORKER_COUNT": "4",
    "DEPLOY_INSTANCE_CLASS": "B2",
    "DEPLOY_MIN_IDLE_INSTANCES": "1",
}

AUTOMATIC_INSTANCE_CLASSES = ("F1", "F2", "F4", "F4_1G")
BASIC_INSTANCE_CLASSES = ("B1", "B2", "B4", "B4_1G", "B8")
SCALING_TYPES = ("automatic", "basic")

DEFAULT_SERVER_NAME = "127.0.0.1"
DEFAULT_DEV_PORT = "5050"
DEFAULT_TEST_PORT = "5000"
DEFAULT_TEST_PREFIX = "test-"
DEFAULT_ADMIN_EMAIL = "admin@test.com"
DEFAULT_ADMIN_NAME = "admin"

REQUIRED_APPLICATION_SETTINGS = {
    "ADMIN_NAME": "Owner access",
    "ADMIN_EMAIL": "Owner access",
    "AI_MODEL": "AI",
    "AI_UTILITY_MODEL": "AI",
    "AI_IMAGE_MODEL": "AI",
    "AI_LOCATION": "AI",
    "ANALYTICS": "Analytics",
    "APP_NAME": "Application identity",
    "APP_URL": "Application identity",
    "AUTH_EMAIL_CONFIG": "Authentication email",
    "CAPTURE_ERRORS": "Error monitoring",
    "CONFIG_KIND": "Recovery metadata",
    "CONFIG_SCHEMA_VERSION": "Recovery metadata",
    "RUNTIME_SERVICE_ACCOUNT_EMAIL": "Google Cloud runtime identity",
    "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": "Internal request identity",
    **{key: "Deployment" for key in DEFAULT_DEPLOYMENT_SETTINGS},
    "IDENTITY_PLATFORM_CONFIG": "Authentication",
    "GIBBERISH": "Security",
    "GOOGLE_SIGNIN_ENABLED": "Authentication",
    "GOOGLE_CLOUD_PROJECT": "Google Cloud project",
    "OCR_LOCATION": "Document processing",
    "OCR_PROCESSOR": "Document processing",
    "OCR_PROCESSOR_ID": "Document processing",
    "PUBLIC_MANUAL": "Public manual",
    "PUBLIC_PAGE_INDEXING": "Public pages",
    "REDIS_HOST": "Redis",
    "REDIS_PORT": "Redis",
    "REDIS_PASSWORD": "Redis",
    "REDIS_TLS": "Redis",
    "APP_ENGINE_LOCATION": "App Engine",
    "RESOURCE_REGION": "Google Cloud regional resources",
    "SECRET_KEY": "Security",
    "TASK_QUEUE_NAME": "Task queue",
    "VERSION": "Version tracking",
}


INDEX_YAML = {
    "indexes": [
        # Core indexes
        {
            "kind": "models",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "modified", "direction": "desc"},
                {"name": "name"},
            ],
        },
        {
            "kind": "models",
            "properties": [
                {"name": "active"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "models",
            "properties": [
                {"name": "name"},
                {"name": "type"},
            ],
        },
        {
            "kind": "models",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "models",
            "properties": [
                {"name": "requires"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "requires"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "hash"},
                {"name": "due_date"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "requires"},
                {"name": "due_date"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "assigned_to"},
                {"name": "due_date"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "assigned_to"},
                {"name": "due_date"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "completed"},
                {"name": "due_date"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "type"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "model"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "categories"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "project"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "model"},
                {"name": "form"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "due_date", "direction": "asc"},
            ],
        },
        # tasks_without_due_dates when requires is not filtered (unrestricted users)
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "due_date"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "due_date"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "requires"},
                {"name": "due_date", "direction": "asc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "requires"},
                {"name": "due_date"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "assigned_to"},
                {"name": "due_date", "direction": "asc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "assigned_to"},
                {"name": "due_date"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "project"},
                {"name": "active"},
                {"name": "type"},
                {"name": "due_date", "direction": "asc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "project"},
                {"name": "active"},
                {"name": "type"},
                {"name": "due_date"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "active"},
                {"name": "type"},
                {"name": "categories"},
                {"name": "form"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "properties": [
                {"name": "completed"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        # Filters
        {
            "kind": "filters",
            "properties": [
                {"name": "user"},
                {"name": "entity"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        # Ancestor queries
        {
            "kind": "models",
            "ancestor": True,
            "properties": [
                {"name": "modified", "direction": "desc"},
            ],
        },
        {
            "kind": "instances",
            "ancestor": True,
            "properties": [
                {"name": "modified", "direction": "desc"},
            ],
        },
        # Public instances
        {
            "kind": "instances",
            "properties": [
                {"name": "public"},
                {"name": "public_id"},
            ],
        },
        # Users
        {
            "kind": "users",
            "properties": [
                {"name": "active"},
                {"name": "name"},
            ],
        },
        {
            "kind": "users",
            "properties": [
                {"name": "groups"},
                {"name": "modified", "direction": "desc"},
            ],
        },
        # Activity
        {
            "kind": "activity",
            "properties": [
                {"name": "type"},
                {"name": "scope"},
                {"name": "created", "direction": "desc"},
            ],
        },
        {
            "kind": "activity",
            "ancestor": True,
            "properties": [
                {"name": "type"},
                {"name": "created", "direction": "desc"},
            ],
        },
        {
            "kind": "activity",
            "ancestor": True,
            "properties": [
                {"name": "type"},
                {"name": "notification_type"},
                {"name": "created", "direction": "desc"},
            ],
        },
        # Direct messages
        {
            "kind": "message_conversations",
            "properties": [
                {"name": "participants"},
                {"name": "last_activity", "direction": "desc"},
            ],
        },
        {
            "kind": "message_conversations",
            "properties": [
                {"name": "visible_to"},
                {"name": "last_activity", "direction": "desc"},
            ],
        },
        {
            "kind": "messages",
            "ancestor": True,
            "properties": [
                {"name": "sequence", "direction": "desc"},
            ],
        },
        # Notification email digest events
        {
            "kind": "email_deliveries",
            "properties": [
                {"name": "recipient"},
                {"name": "record_type"},
                {"name": "mode"},
                {"name": "bucket"},
                {"name": "state"},
                {"name": "created"},
            ],
        },
        # History
        {
            "kind": "history",
            "ancestor": True,
            "properties": [
                {"name": "created", "direction": "desc"},
            ],
        },
        # Deferred jobs
        {
            "kind": "jobs",
            "properties": [
                {"name": "status"},
                {"name": "modified", "direction": "asc"},
            ],
        },
        {
            "kind": "jobs",
            "properties": [
                {"name": "dispatch_state"},
                {"name": "modified", "direction": "asc"},
            ],
        },
    ]
}

INSTALLER_PROJECT_PERMISSIONS = [
    "appengine.applications.create",
    "appengine.applications.get",
    "cloudscheduler.jobs.create",
    "cloudscheduler.jobs.enable",
    "cloudscheduler.jobs.get",
    "cloudscheduler.jobs.pause",
    "cloudscheduler.jobs.update",
    "cloudtasks.queues.create",
    "cloudtasks.queues.get",
    "cloudtasks.queues.pause",
    "cloudtasks.queues.purge",
    "cloudtasks.queues.resume",
    "cloudtasks.tasks.fullView",
    "cloudtasks.tasks.list",
    "datastore.backupSchedules.create",
    "datastore.backupSchedules.get",
    "datastore.backupSchedules.list",
    "datastore.backupSchedules.update",
    "datastore.backups.get",
    "datastore.backups.list",
    "datastore.databases.clone",
    "datastore.databases.create",
    "datastore.databases.delete",
    "datastore.databases.export",
    "datastore.databases.getMetadata",
    "datastore.databases.import",
    "datastore.databases.update",
    "datastore.operations.get",
    "datastore.operations.list",
    "documentai.processors.create",
    "documentai.processors.get",
    "documentai.processors.list",
    "firebaseauth.configs.create",
    "firebaseauth.configs.get",
    "firebaseauth.configs.getSecret",
    "firebaseauth.configs.update",
    "iam.serviceAccounts.create",
    "iam.serviceAccounts.get",
    "iam.serviceAccounts.getIamPolicy",
    "iam.serviceAccounts.list",
    "iam.serviceAccounts.setIamPolicy",
    "resourcemanager.projects.get",
    "resourcemanager.projects.createBillingAssignment",
    "resourcemanager.projects.getIamPolicy",
    "resourcemanager.projects.setIamPolicy",
    "serviceusage.effectivepolicy.get",
    "serviceusage.services.enable",
    "serviceusage.services.get",
    "serviceusage.services.list",
    "serviceusage.services.use",
    "storage.buckets.create",
]

INSTALLER_BUCKET_PERMISSIONS = [
    "storage.buckets.get",
    "storage.buckets.getIamPolicy",
    "storage.buckets.setIamPolicy",
    "storage.buckets.update",
]

INSTALLER_BILLING_ACCOUNT_PERMISSIONS = [
    "billing.resourceAssociations.create",
]

DEPLOYER_PROJECT_PERMISSIONS = [
    "appengine.applications.get",
    "appengine.operations.get",
    "appengine.services.get",
    "appengine.versions.create",
    "appengine.versions.get",
    "cloudbuild.builds.create",
    "cloudbuild.builds.get",
    "datastore.indexes.create",
    "datastore.indexes.delete",
    "datastore.indexes.get",
    "datastore.indexes.list",
    "datastore.indexes.update",
]

DEPLOYER_PROJECT_ROLES = [
    "roles/appengine.deployer",
    "roles/cloudbuild.builds.editor",
    "roles/datastore.indexAdmin",
    "roles/storage.objectAdmin",
]

RUNTIME_PROJECT_ROLES = [
    "roles/cloudscheduler.admin",
    "roles/datastore.user",
    "roles/datastore.backupSchedulesViewer",
    "roles/datastore.backupsViewer",
    "roles/firebaseauth.editor",
    "roles/cloudtasks.enqueuer",
    "roles/cloudtasks.taskDeleter",
    "roles/documentai.apiUser",
    "roles/aiplatform.user",
]

RUNTIME_BUCKET_ROLES = [
    "roles/storage.legacyBucketReader",
    "roles/storage.objectAdmin",
]

OPERATOR_BUCKET_ROLES = [
    "roles/storage.objectAdmin",
]

PUBLIC_BUCKET_ROLES = [
    "roles/storage.objectViewer",
]

RUNTIME_SERVICE_ACCOUNT_ROLES = [
    "roles/iam.serviceAccountUser",
    "roles/iam.serviceAccountTokenCreator",
]

REMOVED_RUNTIME_PROJECT_ROLES = [
    "roles/appengine.deployer",
    "roles/iam.serviceAccountUser",
    "roles/cloudbuild.builds.editor",
    "roles/storage.admin",
    "roles/storage.objectCreator",
    "roles/storage.objectViewer",
    "roles/firebase.admin",
    "roles/firebaseauth.admin",
    "roles/firebasecloudmessaging.admin",
    "roles/firebasemessagingcampaigns.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/cloudtasks.admin",
]

REMOVED_RUNTIME_PROJECT_STORAGE_ROLES = [
    "roles/storage.admin",
    "roles/storage.objectCreator",
    "roles/storage.objectViewer",
]


REQUIRED_GOOGLE_CLOUD_APIS = {
    "cloudbuild.googleapis.com": "Cloud Build",
    "appengine.googleapis.com": "App Engine Admin",
    "storage-api.googleapis.com": "Cloud Storage API",
    "storage-component.googleapis.com": "Cloud Storage Component",
    "cloudresourcemanager.googleapis.com": "Cloud Resource Manager",
    "serviceusage.googleapis.com": "Service Usage",
    "cloudbilling.googleapis.com": "Cloud Billing",
    "iam.googleapis.com": "Identity and Access Management (IAM)",
    "iamcredentials.googleapis.com": "Service Account Credentials API",
    "identitytoolkit.googleapis.com": "Identity Platform",
    "cloudtasks.googleapis.com": "Cloud Tasks API",
    "cloudscheduler.googleapis.com": "Cloud Scheduler API",
    "documentai.googleapis.com": "Cloud Document AI API",
    "firestore.googleapis.com": "Cloud Firestore API",
    "aiplatform.googleapis.com": "AI Platform API",
    "places.googleapis.com": "Places API",
}

MANIFEST = {
    "background_color": "#FFFFFF",
    "display": "standalone",
    "scope": "/",
    "start_url": "/",
    "name": "Lagniappe",
    "short_name": "Lagniappe",
    "description": "a Lagniappe instance",
    "icons": [
        {"src": "/images/logo-192x192.png", "sizes": "192x192", "type": "image/png"},
        {
            "src": "/images/logo-512x512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ],
}

SCREENSHOTS = [
    {
        "src": "/images/splash-1242x2688.png",
        "sizes": "1242x2688",
        "type": "image/png",
        "form_factor": "narrow",
    },
    {
        "src": "/images/splash-2048x2732.png",
        "sizes": "2048x2732",
        "type": "image/png",
        "form_factor": "wide",
    },
]


# Keep these path families aligned with the registered Flask blueprints, the
# unprefixed home routes, and App Engine's lifecycle routes. Requests outside
# this allowlist fall through to the final static 404 handler without starting
# the application runtime.
APP_BLUEPRINT_ROUTE_PREFIXES = (
    "analytics",
    "assets",
    "categories",
    "files",
    "filters",
    "forms",
    "l",
    "manual",
    "messages",
    "pages",
    "process",
    "projects",
    "reference",
    "tasks",
    "testing",
    "tools",
    "users",
    "webhooks",
)

APP_ROOT_ROUTE_PREFIXES = (
    "_ah",
    "admin",
    "offline",
    "privacy-policy",
    "public",
    "reporting_privacy",
    "robots.txt",
    "sitemap.xml",
)


APP_HANDLERS = [
    {
        "url": "/(.*\\.css)$",
        "mime_type": "text/css; charset=utf-8",
        "secure": "always",
        "static_files": "lagniappe/web/static/\\1",
        "upload": "lagniappe/web/static/(.*\\.css)",
        "http_headers": {"Cache-Control": "public, max-age=31536000, immutable"},
    },
    {
        "url": "/fonts/(.*\\.woff2)",
        "mime_type": "font/woff2",
        "secure": "always",
        "static_files": "lagniappe/web/static/fonts/\\1",
        "upload": "lagniappe/web/static/fonts/(.*\\.woff2)",
    },
    {
        "url": "/sw.js",
        "secure": "always",
        "static_files": "lagniappe/web/static/sw.js",
        "upload": "lagniappe/web/static/sw.js",
        "mime_type": "application/javascript",
        "http_headers": {
            "Cache-Control": "no-cache",
        },
        "expiration": "0s",
    },
    {
        "url": "/chunks/(.*\\.js)$",
        "mime_type": "text/javascript",
        "secure": "always",
        "static_files": "lagniappe/web/static/chunks/\\1",
        "upload": "lagniappe/web/static/chunks/(.*\\.js)",
        "http_headers": {
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    },
    {
        "url": "/pdfjs/wasm/(.*\\.wasm)$",
        "mime_type": "application/wasm",
        "secure": "always",
        "static_files": "lagniappe/web/static/pdfjs/wasm/\\1",
        "upload": "lagniappe/web/static/pdfjs/wasm/(.*\\.wasm)",
    },
    {
        "url": "/pdfjs/wasm/(.*\\.js)$",
        "mime_type": "text/javascript",
        "secure": "always",
        "static_files": "lagniappe/web/static/pdfjs/wasm/\\1",
        "upload": "lagniappe/web/static/pdfjs/wasm/(.*\\.js)",
    },
    {
        "url": "/(.*\\.m?js)$",
        "mime_type": "text/javascript",
        "secure": "always",
        "static_files": "lagniappe/web/static/\\1",
        "upload": "lagniappe/web/static/(.*\\.m?js)",
    },
    {
        "url": "/(.*\\.map)",
        "mime_type": "application/json",
        "secure": "always",
        "static_files": "lagniappe/web/static/\\1",
        "upload": "lagniappe/web/static/(.*\\.map)",
    },
    {
        "url": "/favicon\\.ico",
        "mime_type": "image/x-icon",
        "secure": "always",
        "static_files": "lagniappe/web/static/images/favicon.ico",
        "upload": "lagniappe/web/static/images/favicon\\.ico",
    },
    {
        "url": "/images/(.*\\.(bmp|gif|jpeg|jpg|png|pdf))",
        "static_files": "lagniappe/web/static/images/\\1",
        "secure": "always",
        "upload": "lagniappe/web/static/images/(.*\\.(bmp|gif|jpeg|jpg|png|pdf))",
    },
    {
        "url": "/manifest.json",
        "secure": "always",
        "static_files": "lagniappe/web/static/manifest.json",
        "upload": "lagniappe/web/static/manifest.json",
        "mime_type": "application/manifest+json",
    },
]

APP_HANDLERS.extend(
    {
        "url": f"/{prefix}(/.*)?$",
        "script": "auto",
        "secure": "always",
        "redirect_http_response_code": 301,
    }
    for prefix in (*APP_BLUEPRINT_ROUTE_PREFIXES, *APP_ROOT_ROUTE_PREFIXES)
)

APP_HANDLERS.extend(
    [
        {
            "url": "/$",
            "script": "auto",
            "secure": "always",
            "redirect_http_response_code": 301,
        },
        {
            "url": "/(.*)$",
            "mime_type": "text/html; charset=utf-8",
            "secure": "always",
            "static_files": "lagniappe/web/static/404.html",
            "upload": "lagniappe/web/static/404.html",
            "expiration": "0s",
            "http_headers": {
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow",
            },
        },
    ]
)
