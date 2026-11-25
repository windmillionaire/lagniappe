"""Reconcile the Cloud Tasks queue and the deferred-job Cloud Scheduler job."""

from __future__ import annotations

from config import constants
from installer import FORMATTER
from installer import iam as iam_access
from installer.commands import run_gcloud_command
from installer.errors import ProviderNotFound, classify_provider_error, retry_provider_call
from installer.package_install import install_if_missing
from installer.state import record_mutation


def create_task_queue() -> bool:
    """Creates a Cloud Tasks queue named 'lagniappe-tasks' if it doesn't exist."""
    from config import SETTINGS

    f = FORMATTER.initialize()

    with f.progress(
        text="Configure Cloud Tasks queue",
        success_text='Cloud Tasks queue configured',
    ) as sp:
        install_if_missing(
            "google.cloud.tasks_v2",
            "Google Cloud Tasks",
            package_name="google-cloud-tasks",
        )
        install_if_missing(
            "google.api_core", "Google API Core", package_name="google-api-core"
        )
        from google.cloud import tasks_v2
        from google.cloud.tasks_v2 import types as task_types

        project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
        region = str(SETTINGS.APP["RESOURCE_REGION"])
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
            sp.ok()
            return True
        except ProviderNotFound:
            queue = task_types.Queue(name=queue_path)
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
                sp.ok()
                return True
            except Exception as e:
                sp.write(
                    f.error("Failed to create Cloud Tasks queue.", e),
                    raw=True,
                )
                sp.fail()
                raise classify_provider_error(
                    e,
                    message="Failed to create the Cloud Tasks queue.",
                ) from e
        except Exception as e:
            sp.write(
                f.error("Error checking for Cloud Tasks queue.", e),
                raw=True,
            )
            sp.fail()
            raise classify_provider_error(
                e,
                message="Failed to discover the Cloud Tasks queue.",
            ) from e


def create_deferred_job_reconciler() -> bool:
    """Create or update the five-minute durable-job recovery schedule."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
    region = str(SETTINGS.APP["RESOURCE_REGION"])
    runtime_service_account = SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    service_account = SETTINGS.APP.get(
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"
    )
    app_url = str(SETTINGS.APP.get("APP_URL") or "").rstrip("/")
    account = str(SETTINGS.GCLOUD_CONFIG.get("ACCOUNT") or "")
    if (
        not isinstance(runtime_service_account, str) or not runtime_service_account
        or not isinstance(service_account, str) or not service_account
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

    with f.progress(
        text="Configure background-job recovery",
        success_text='Background-job recovery configured',
    ) as sp:
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
        sp.ok()
    return True
