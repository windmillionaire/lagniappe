import re
import time
from types import SimpleNamespace

from config import constants
from installer import FORMATTER
from installer import iam as iam_access
from .package_install import install_if_missing
from .utils import run_gcloud_command
from .errors import (
    ProviderNotFound,
    ProviderTransientError,
    SetupCancelled,
    classify_provider_error,
    retry_provider_call,
)
from .state import record_mutation


GCLOUD_SERVICE_DISCOVERY_TIMEOUT = 60
GCLOUD_SERVICE_ENABLE_TIMEOUT = 300
GCLOUD_API_PROPAGATION_ATTEMPTS = 8
GCLOUD_API_PROPAGATION_DELAYS = (2, 4, 8, 15, 20, 30, 30)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_enable_gcloud_apis_reuses_confirmed_preflight
# @features setup
# @dimensions gcloud-command provider-apis preflight timeout
def enable_gcloud_apis():
    """Enable only APIs missing from the confirmed target preflight."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    required_apis = constants.REQUIRED_GOOGLE_CLOUD_APIS

    feedback_text = f.success("Enabling required Google Cloud APIs")
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    enabled_apis = getattr(
        SETTINGS,
        "_SETUP_ENABLED_GOOGLE_CLOUD_APIS",
        None,
    )
    with f.yaspin(text=feedback_text) as sp:
        if enabled_apis is None:
            result = retry_provider_call(
                lambda: run_gcloud_command(
                    [
                        "services",
                        "list",
                        "--enabled",
                        f"--project={project_id}",
                        "--format=value(config.name)",
                    ],
                    timeout=GCLOUD_SERVICE_DISCOVERY_TIMEOUT,
                ),
                description="List enabled Google Cloud APIs",
            )
            enabled_apis = {
                value.strip()
                for value in result.stdout.splitlines()
                if value.strip()
            }

        missing_apis = sorted(set(required_apis) - set(enabled_apis))
        if missing_apis:
            retry_provider_call(
                lambda: run_gcloud_command(
                    [
                        "services",
                        "enable",
                        *missing_apis,
                        f"--project={project_id}",
                    ],
                    timeout=GCLOUD_SERVICE_ENABLE_TIMEOUT,
                ),
                description="Enable required Google Cloud APIs",
            )
            for service_name in missing_apis:
                display_name = required_apis[service_name]
                record_mutation(
                    "enable Google Cloud APIs",
                    action="enabled",
                    resource="provider-api",
                    identifier=service_name,
                )
                sp.write(f.success(f"Enabled {display_name}"))
            enabled_apis = set(enabled_apis) | set(missing_apis)

        SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(enabled_apis)
        sp.ok(f.ok_glyph)
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_gcloud_resource_client_contracts
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_service_account_waits_for_newly_enabled_iam
# @features setup
# @dimensions service-account provider-convergence
def configure_service_account():
    """Create or update the explicit keyless runtime service account."""
    from config import SETTINGS

    f = FORMATTER.initialize()

    with f.yaspin(text=f.success("Configuring service account")) as sp:
        install_if_missing(
            "google.cloud.iam_admin_v1",
            "Google IAM Admin API",
            package_name="google-cloud-iam",
        )
        from google.cloud import iam_admin_v1

        project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
        project_name = SETTINGS.GCLOUD_CONFIG.get("NAME") or re.sub(
            r"[^a-z0-9]", "-", project_id.lower()
        )
        runtime_email = str(
            SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
            or f"{project_name}@{project_id}.iam.gserviceaccount.com"
        ).strip().casefold()
        if not runtime_email.endswith(
            f"@{project_id}.iam.gserviceaccount.com"
        ):
            raise RuntimeError(
                "RUNTIME_SERVICE_ACCOUNT_EMAIL must identify a service "
                "account in the configured Google Cloud project."
            )
        deployer_email = SETTINGS.APP.get(
            "DEPLOYER_EMAIL"
        ) or SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
        if not deployer_email:
            raise RuntimeError("A deployer Google account is required.")

        iam_admin_client = iam_admin_v1.IAMClient()
        resource = f"projects/{project_id}"

        def retry_iam(operation, description):
            def wait_for_retry(delay):
                sp.write(
                    f.info(
                        "Google IAM is still becoming available; "
                        f"retrying in {delay} seconds..."
                    )
                )
                time.sleep(delay)

            return retry_provider_call(
                operation,
                description=description,
                attempts=GCLOUD_API_PROPAGATION_ATTEMPTS,
                delays=GCLOUD_API_PROPAGATION_DELAYS,
                sleep=wait_for_retry,
            )

        def apply_iam_policy(email):
            iam_access.reconcile_runtime_project_policy(
                project_id,
                email,
                removed_roles=(
                    set(constants.REMOVED_RUNTIME_PROJECT_ROLES)
                    - set(constants.REMOVED_RUNTIME_PROJECT_STORAGE_ROLES)
                ),
            )
            iam_access.reconcile_runtime_service_account_policy(
                project_id,
                email,
                deployer_email,
            )

        name = f"projects/{project_id}/serviceAccounts/{runtime_email}"
        request = iam_admin_v1.types.GetServiceAccountRequest(name=name)
        try:
            account = retry_iam(
                lambda: iam_admin_client.get_service_account(request=request),
                f"Discover service account {name}",
            )
            sp.write(f.info("Using existing service account..."))
            record_mutation(
                "reconcile service account",
                action="existing",
                resource="service-account",
                identifier=account.email,
            )
        except ProviderTransientError as e:
            message = (
                "Google IAM is enabled but did not become ready in time. "
                "Run setup again to resume."
            )
            sp.write(f.error(message))
            sp.fail(f.fail_glyph)
            raise ProviderTransientError(message) from e
        except ProviderNotFound:
            sp.write(f.info("Creating new service account..."))
            try:
                request = iam_admin_v1.types.CreateServiceAccountRequest()
                request.account_id = runtime_email.split("@", 1)[0]
                request.name = resource

                new_service_account = iam_admin_v1.types.ServiceAccount()
                new_service_account.display_name = SETTINGS.APP["APP_NAME"]
                request.service_account = new_service_account

                account = retry_iam(
                    lambda: iam_admin_client.create_service_account(request=request),
                    f"Create service account {name}",
                )
                record_mutation(
                    "reconcile service account",
                    action="created",
                    resource="service-account",
                    identifier=account.email,
                )
            except Exception as e:
                sp.fail(f.fail_glyph)
                classified = classify_provider_error(e)
                if isinstance(classified, ProviderTransientError):
                    message = (
                        "Google IAM is enabled but did not become ready in "
                        "time. Run setup again to resume."
                    )
                    sp.write(f.error(message))
                    raise ProviderTransientError(message) from e
                sp.write(f.error("Failed to create service account."))
                raise classify_provider_error(
                    e,
                    message="Failed to create service account.",
                ) from e

        def wait_for_service_account(name):
            active, count = False, 0
            while not active:
                try:
                    request = iam_admin_v1.types.GetServiceAccountRequest(name=name)
                    iam_admin_client.get_service_account(request=request)
                    break
                except Exception as e:
                    count += 1
                    if count > 9:
                        raise e
                    time.sleep(1)

        try:
            wait_for_service_account(account.name)
            apply_iam_policy(account.email)
        except Exception as e:
            sp.fail(f.fail_glyph)
            classified = classify_provider_error(e)
            if isinstance(classified, ProviderTransientError):
                message = (
                    "Google IAM is enabled but did not become ready in time. "
                    "Run setup again to resume."
                )
                sp.write(f.error(message))
                raise ProviderTransientError(message) from e
            sp.write(f.error("Failed to reconcile the service account."))
            raise classify_provider_error(
                e,
                message="Failed to reconcile the keyless runtime service account.",
            ) from e

        sp.ok(f.ok_glyph)
        return {"client_email": account.email}


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_storage_provisioning_is_bucket_scoped_and_idempotent
# @features setup storage iam
# @dimensions provisioning bucket-scope idempotence bucket-location storage-class
def configure_storage_buckets(*, include_production=True, include_test=False):
    """Provision the selected production or developer bucket families."""
    from config import SETTINGS
    from config.storage import (
        BUCKET_CREATE_LOCATION,
        BUCKET_DEFAULT_STORAGE_CLASS,
        configure_recovery_bucket,
        configure_storage_bucket,
        recovery_bucket_name,
        storage_bucket_names,
    )

    f = FORMATTER.initialize()
    install_if_missing(
        "google.cloud.storage",
        "Google Cloud Storage",
        package_name="google-cloud-storage",
    )
    from google.api_core import exceptions as api_exceptions
    from google.cloud import storage

    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    runtime_email = SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    if not runtime_email:
        raise RuntimeError(
            "Cloud Storage provisioning requires "
            "RUNTIME_SERVICE_ACCOUNT_EMAIL."
        )
    operator_email = (
        SETTINGS.APP.get("DEPLOYER_EMAIL")
        or SETTINGS.APP.get("INSTALLER_EMAIL")
        or SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
    )
    if not operator_email:
        raise RuntimeError(
            "Cloud Storage provisioning requires an installer/deployer account."
        )

    client = storage.Client(project=project_id)
    runtime_member = f"serviceAccount:{runtime_email}"
    operator_member = iam_access.principal_member(operator_email)
    config = SimpleNamespace(
        APP_URL=SETTINGS.APP.get("APP_URL"),
        CUSTOM_DOMAIN=SETTINGS.APP.get("CUSTOM_DOMAIN"),
        local=False,
    )

    if not include_production and not include_test:
        raise ValueError("At least one Cloud Storage bucket family is required.")

    bucket_settings = []
    if include_production:
        bucket_settings.append(SETTINGS.APP)
    test_prefix = str(
        (getattr(SETTINGS, "TEST_CONFIG", {}) or {}).get("PREFIX") or ""
    )
    app_prefix = str(SETTINGS.APP.get("PREFIX") or "")
    if include_test:
        if not test_prefix or test_prefix == app_prefix:
            raise RuntimeError(
                "Developer bucket provisioning requires a distinct test prefix."
            )
        test_bucket_settings = dict(SETTINGS.APP)
        test_bucket_settings["PREFIX"] = test_prefix
        bucket_settings.append(test_bucket_settings)
    managed_buckets = {
        bucket_name: bucket_kind
        for settings in bucket_settings
        for bucket_kind, bucket_name in storage_bucket_names(settings).items()
    }
    if include_production:
        managed_buckets[recovery_bucket_name(SETTINGS.APP)] = "recovery"

    with f.yaspin(text=f.success("Configure Cloud Storage buckets")) as sp:
        for bucket_name, bucket_kind in managed_buckets.items():
            created = False
            try:
                bucket = client.get_bucket(bucket_name)
            except api_exceptions.NotFound:
                try:
                    bucket = client.bucket(bucket_name)
                    bucket.storage_class = BUCKET_DEFAULT_STORAGE_CLASS
                    bucket = client.create_bucket(
                        bucket,
                        location=BUCKET_CREATE_LOCATION,
                    )
                    created = True
                    sp.write(f.success(f"Created bucket {bucket_name}"))
                except api_exceptions.Conflict:
                    bucket = client.get_bucket(bucket_name)

            record_mutation(
                "reconcile storage buckets",
                action="created" if created else "existing",
                resource="storage-bucket",
                identifier=bucket_name,
                details={
                    "location": str(getattr(bucket, "location", "") or ""),
                    "storage_class": str(
                        getattr(bucket, "storage_class", "") or ""
                    ),
                },
            )

            iam_access.require_installer_bucket_permissions(bucket)
            if bucket_kind == "recovery":
                configure_recovery_bucket(bucket)
            else:
                configure_storage_bucket(bucket, config)
            policy = bucket.get_iam_policy(requested_policy_version=3)
            changed = iam_access.reconcile_member_roles(
                policy,
                operator_member,
                desired_roles=constants.OPERATOR_BUCKET_ROLES,
                managed_roles=constants.OPERATOR_BUCKET_ROLES,
                binding_factory=lambda role, members: {
                    "role": role,
                    "members": set(members),
                },
            )
            if bucket_kind == "recovery":
                changed = (
                    iam_access.reconcile_member_roles(
                        policy,
                        runtime_member,
                        desired_roles=[],
                        managed_roles=constants.RUNTIME_BUCKET_ROLES,
                        binding_factory=lambda role, members: {
                            "role": role,
                            "members": set(members),
                        },
                    )
                    or changed
                )
                changed = (
                    iam_access.reconcile_member_roles(
                        policy,
                        "allUsers",
                        desired_roles=[],
                        managed_roles=constants.PUBLIC_BUCKET_ROLES,
                        binding_factory=lambda role, members: {
                            "role": role,
                            "members": set(members),
                        },
                    )
                    or changed
                )
            else:
                changed = (
                    iam_access.reconcile_member_roles(
                        policy,
                        runtime_member,
                        desired_roles=constants.RUNTIME_BUCKET_ROLES,
                        managed_roles=constants.RUNTIME_BUCKET_ROLES,
                        binding_factory=lambda role, members: {
                            "role": role,
                            "members": set(members),
                        },
                    )
                    or changed
                )
                if bucket_kind == "public":
                    changed = (
                        iam_access.reconcile_member_roles(
                            policy,
                            "allUsers",
                            desired_roles=constants.PUBLIC_BUCKET_ROLES,
                            managed_roles=constants.PUBLIC_BUCKET_ROLES,
                            binding_factory=lambda role, members: {
                                "role": role,
                                "members": set(members),
                            },
                        )
                        or changed
                    )
            if changed:
                bucket.set_iam_policy(policy)
        iam_access.reconcile_runtime_project_policy(project_id, runtime_email)
        sp.ok(f.ok_glyph)
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_gcloud_resource_client_contracts
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_app_engine_persists_provider_location_hostname_and_oidc_subject
# @features setup
# @dimensions app-engine immutable-location provider-state
def create_app_engine_app():
    """Get the immutable App Engine application or create it after confirmation."""
    from config import SETTINGS
    from config.locations import normalize_app_engine_location

    f = FORMATTER.initialize()

    install_if_missing(
        "google.cloud.appengine_admin_v1",
        "Google App Engine Admin API",
        package_name="google-cloud-appengine-admin",
    )
    install_if_missing(
        "google.api_core", "Google API Core", package_name="google-api-core"
    )
    from google.cloud import appengine_admin_v1

    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    location = normalize_app_engine_location(
        SETTINGS.APP["APP_ENGINE_LOCATION"]
    )

    with f.yaspin(text=f.success("Configure App Engine")) as sp:
        client = appengine_admin_v1.ApplicationsClient()

        try:
            application = retry_provider_call(
                lambda: client.get_application(
                    request={"name": f"apps/{project_id}"}
                ),
                description=f"Discover App Engine application {project_id}",
            )
            record_mutation(
                "reconcile App Engine",
                action="existing",
                resource="app-engine-application",
                identifier=project_id,
            )
            sp.ok(f.ok_glyph)
            return application
        except ProviderNotFound:
            sp.write(f.info("Creating new App Engine app..."))

        sp.write(
            f.warning(
                "App Engine location is permanent and cannot be changed after "
                f"creation. Selected location: {location}"
            )
        )
        confirmation = input(
            f.warning(
                f"Create the App Engine application in '{location}'? [y/N]: "
            )
        )
        if confirmation.strip().lower() not in ("y", "yes"):
            sp.fail(f.fail_glyph)
            print(f.error("App Engine application creation cancelled."))
            raise SetupCancelled("App Engine application creation was cancelled.")

        application_to_create = appengine_admin_v1.Application()
        application_to_create.id = project_id
        application_to_create.location_id = location

        try:
            operation = client.create_application(
                request={"application": application_to_create}
            )
            sp.write(
                f.info(
                    "Waiting for App Engine app creation to complete (this can take a few minutes)..."
                )
            )
            created_app = operation.result(timeout=300)
            record_mutation(
                "reconcile App Engine",
                action="created",
                resource="app-engine-application",
                identifier=project_id,
            )

            sp.write(
                f.success(
                    "Successfully created App Engine app in "
                    f"{created_app.location_id}."
                )
            )
            sp.ok(f.ok_glyph)
            return created_app
        except Exception as e:
            sp.write(f.error(f"Failed to create App Engine app.\n{str(e)}"))
            sp.fail(f.fail_glyph)
            raise classify_provider_error(
                e,
                message="Failed to create the App Engine application.",
            ) from e


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_gcloud_resource_client_contracts
# @features setup
# @dimensions cloud-tasks
def create_task_queue():
    """Creates a Cloud Tasks queue named 'lagniappe-tasks' if it doesn't exist."""
    from config import SETTINGS

    f = FORMATTER.initialize()

    with f.yaspin(text=f.success("Configure Cloud Tasks queue")) as sp:
        install_if_missing(
            "google.cloud.tasks_v2",
            "Google Cloud Tasks",
            package_name="google-cloud-tasks",
        )
        install_if_missing(
            "google.api_core", "Google API Core", package_name="google-api-core"
        )
        from google.cloud import tasks_v2

        project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
        region = SETTINGS.APP["RESOURCE_REGION"]
        queue_name = SETTINGS.APP.get(
            "TASK_QUEUE_NAME", constants.DEFAULT_TASK_QUEUE_NAME
        )
        SETTINGS.APP["TASK_QUEUE_NAME"] = queue_name

        client = tasks_v2.CloudTasksClient()
        parent = f"projects/{project_id}/locations/{region}"
        queue_path = f"projects/{project_id}/locations/{region}/queues/{queue_name}"

        try:
            retry_provider_call(
                lambda: client.get_queue(name=queue_path),
                description=f"Discover Cloud Tasks queue {queue_path}",
            )
            record_mutation(
                "reconcile task queue",
                action="existing",
                resource="cloud-tasks-queue",
                identifier=queue_path,
            )
            SETTINGS.save()
            sp.ok(f.ok_glyph)
            return True
        except ProviderNotFound:
            sp.write(f.info("Creating new Cloud Tasks queue..."))
            queue = tasks_v2.types.Queue(name=queue_path)
            try:
                retry_provider_call(
                    lambda: client.create_queue(parent=parent, queue=queue),
                    description=f"Create Cloud Tasks queue {queue_path}",
                )
                retry_provider_call(
                    lambda: client.get_queue(name=queue_path),
                    description=f"Verify Cloud Tasks queue {queue_path}",
                )
                record_mutation(
                    "reconcile task queue",
                    action="created",
                    resource="cloud-tasks-queue",
                    identifier=queue_path,
                )
                SETTINGS.save()
                sp.write(f.success("Successfully created Cloud Tasks queue."))
                sp.ok(f.ok_glyph)
                return True
            except Exception as e:
                sp.write(f.error(f"Failed to create Cloud Tasks queue.\n{str(e)}"))
                sp.fail(f.fail_glyph)
                raise classify_provider_error(
                    e,
                    message="Failed to create the Cloud Tasks queue.",
                ) from e
        except Exception as e:
            sp.write(f.error(f"Error checking for Cloud Tasks queue.\n{str(e)}"))
            sp.fail(f.fail_glyph)
            raise classify_provider_error(
                e,
                message="Failed to discover the Cloud Tasks queue.",
            ) from e


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_deferred_job_reconciler_contract
# @features setup deferred-jobs
# @dimensions cloud-scheduler recovery oidc iam
def create_deferred_job_reconciler():
    """Create or update the five-minute durable-job recovery schedule."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    region = SETTINGS.APP["RESOURCE_REGION"]
    runtime_service_account = SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    service_account = SETTINGS.APP.get(
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"
    )
    app_url = str(SETTINGS.APP.get("APP_URL") or "").rstrip("/")
    account = SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
    if (
        not runtime_service_account
        or not service_account
        or not app_url
        or not account
    ):
        raise RuntimeError(
            "Cloud Scheduler requires APP_URL, runtime service-account "
            "identity, INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL, and an active "
            "gcloud account."
        )
    if service_account.casefold() != runtime_service_account.casefold():
        raise RuntimeError(
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL must identify the attached "
            "runtime service account for this release."
        )

    name = constants.DEFAULT_DEFERRED_JOB_RECONCILER_NAME
    endpoint = f"{app_url}/process/jobs/reconcile"
    common = [
        f"--location={region}",
        f"--project={project_id}",
        f"--schedule={constants.DEFAULT_DEFERRED_JOB_RECONCILER_SCHEDULE}",
        f"--uri={endpoint}",
        "--http-method=POST",
        '--message-body={"reconcile":true}',
        f"--oidc-service-account-email={service_account}",
        f"--oidc-token-audience={endpoint}",
    ]

    with f.yaspin(text=f.success("Configure background-job recovery")) as sp:
        run_gcloud_command(
            [
                "services",
                "enable",
                "cloudscheduler.googleapis.com",
                f"--project={project_id}",
            ]
        )
        project = run_gcloud_command(
            [
                "projects",
                "describe",
                project_id,
                "--format=value(projectNumber)",
            ]
        )
        project_number = project.stdout.strip()
        if not project_number:
            raise RuntimeError("Could not resolve the Cloud Scheduler project number.")
        scheduler_agent = (
            f"service-{project_number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
        )
        iam_access.reconcile_project_service_agent(
            project_id,
            f"serviceAccount:{scheduler_agent}",
            "roles/cloudscheduler.serviceAgent",
        )
        iam_access.reconcile_runtime_service_account_policy(
            project_id,
            service_account,
            account,
        )
        existing = run_gcloud_command(
            [
                "scheduler",
                "jobs",
                "describe",
                name,
                f"--location={region}",
                f"--project={project_id}",
            ],
            check=False,
        )
        action = "update" if getattr(existing, "returncode", 1) == 0 else "create"
        header_flag = "--update-headers" if action == "update" else "--headers"
        run_gcloud_command(
            [
                "scheduler",
                "jobs",
                action,
                "http",
                name,
                *common,
                f"{header_flag}=Content-Type=application/json",
            ]
        )
        run_gcloud_command(
            [
                "scheduler",
                "jobs",
                "describe",
                name,
                f"--location={region}",
                f"--project={project_id}",
            ]
        )
        record_mutation(
            "reconcile deferred-job scheduler",
            action=action,
            resource="cloud-scheduler-job",
            identifier=f"{region}/{name}",
        )
        sp.ok(f.ok_glyph)
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_gcloud_resource_client_contracts
# @features setup
# @dimensions ocr
def create_ocr_processor():
    from config import SETTINGS

    f = FORMATTER.initialize()

    with f.yaspin(text=f.success("Configure OCR processor")) as sp:
        install_if_missing(
            "google.cloud.documentai",
            "Google Document AI",
            package_name="google-cloud-documentai",
        )
        install_if_missing(
            "google.api_core", "Google API Core", package_name="google-api-core"
        )
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
        from google.api_core import exceptions as api_exceptions

        project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
        location = SETTINGS.APP["OCR_LOCATION"]

        try:
            opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
            client = documentai.DocumentProcessorServiceClient(client_options=opts)
            parent = client.common_location_path(project_id, location)
            display_name = SETTINGS.APP.get(
                "OCR_PROCESSOR", constants.DEFAULT_OCR_PROCESSOR_NAME
            )
            saved_processor = SETTINGS.APP.get("OCR_PROCESSOR_ID")
            if saved_processor:
                try:
                    processor = client.get_processor(name=saved_processor)
                    if processor.display_name != display_name:
                        raise RuntimeError(
                            "Saved OCR processor display name does not match "
                            "the provider resource."
                        )
                    sp.ok(f.ok_glyph)
                    record_mutation(
                        "reconcile OCR processor",
                        action="existing",
                        resource="document-ai-processor",
                        identifier=processor.name,
                    )
                    return True
                except api_exceptions.NotFound:
                    pass

            if not saved_processor:
                processor_list = client.list_processors(parent=parent)
                for processor in processor_list.processors:
                    if processor.display_name == display_name:
                        SETTINGS.APP["OCR_PROCESSOR_ID"] = processor.name
                        SETTINGS.APP["OCR_PROCESSOR"] = processor.display_name
                        SETTINGS.save()
                        record_mutation(
                            "reconcile OCR processor",
                            action="existing",
                            resource="document-ai-processor",
                            identifier=processor.name,
                        )
                        sp.ok(f.ok_glyph)
                        return True

            processor = retry_provider_call(
                lambda: client.create_processor(
                    parent=parent,
                    processor=documentai.Processor(
                        display_name=display_name,
                        type_="OCR_PROCESSOR",
                    ),
                ),
                description=f"Create OCR processor {display_name}",
            )
            processor = retry_provider_call(
                lambda: client.get_processor(name=processor.name),
                description=f"Verify OCR processor {processor.name}",
            )

            SETTINGS.APP["OCR_PROCESSOR_ID"] = processor.name
            SETTINGS.APP["OCR_PROCESSOR"] = processor.display_name
            record_mutation(
                "reconcile OCR processor",
                action="created",
                resource="document-ai-processor",
                identifier=processor.name,
            )
            sp.write(f.info(f"Document AI processor '{display_name}' created."))
            SETTINGS.save()
            sp.ok(f.ok_glyph)
        except Exception as e:
            sp.write(f.error(f"Failed to create OCR processor.\n{str(e)}"))
            sp.fail(f.fail_glyph)
            raise classify_provider_error(
                e,
                message="Failed to reconcile the OCR processor.",
            ) from e


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_gcloud_resource_client_contracts
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_app_engine_persists_provider_location_hostname_and_oidc_subject
# @features setup
# @dimensions service-account app-engine immutable-location provider-state oidc keyless-config
def setup_app_engine():
    """Configure App Engine and service account."""
    from config import SETTINGS

    identity = configure_service_account()

    settings_changed = False
    runtime_email = identity.get("client_email")
    if SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") != runtime_email:
        SETTINGS.APP["RUNTIME_SERVICE_ACCOUNT_EMAIL"] = runtime_email
        settings_changed = True
    if (
        SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL")
        != runtime_email
    ):
        SETTINGS.APP["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] = runtime_email
        settings_changed = True
    if SETTINGS.DEPLOY.get("service_account") != runtime_email:
        SETTINGS.DEPLOY["service_account"] = runtime_email
        settings_changed = True
    if settings_changed:
        SETTINGS.save()

    application = create_app_engine_app()
    location = str(getattr(application, "location_id", "") or "").strip()
    hostname = str(getattr(application, "default_hostname", "") or "").strip()
    if not location or not hostname:
        raise RuntimeError(
            "App Engine returned an application without locationId or "
            "defaultHostname; setup will not guess immutable provider state."
        )
    SETTINGS.APP["APP_ENGINE_LOCATION"] = location
    SETTINGS.APP["APP_URL"] = f"https://{hostname}"
    if not SETTINGS.APP.get("CUSTOM_DOMAIN"):
        SETTINGS.APP["GOOGLE_LOGIN_URI"] = (
            f"https://{hostname}/users/google-signin"
        )
    SETTINGS.save()
