"""Reconcile storage buckets, Firestore point-in-time recovery, and backup schedules."""

from __future__ import annotations

import time
from types import SimpleNamespace

from config import constants
from installer import FORMATTER
from installer import iam as iam_access
from installer.commands import run_gcloud_command
from installer.errors import retry_provider_call
from installer.package_install import install_if_missing
from installer.state import record_mutation

from .services import GCLOUD_API_PROPAGATION_ATTEMPTS, GCLOUD_API_PROPAGATION_DELAYS


def configure_storage_buckets(
    *, include_production: bool = True, include_test: bool = False
) -> bool:
    """Provision the selected production or developer bucket families."""
    from config import SETTINGS
    from config.hosted_e2e import hosted_test_service_cors_origin
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

    project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
    runtime_email = SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    if not isinstance(runtime_email, str) or not runtime_email:
        raise RuntimeError(
            "Cloud Storage provisioning requires "
            "RUNTIME_SERVICE_ACCOUNT_EMAIL."
        )
    operator_email = (
        SETTINGS.APP.get("DEPLOYER_EMAIL")
        or SETTINGS.APP.get("INSTALLER_EMAIL")
        or SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
    )
    if not isinstance(operator_email, str) or not operator_email:
        raise RuntimeError(
            "Cloud Storage provisioning requires an installer/deployer account."
        )

    client = storage.Client(project=project_id)
    runtime_member = f"serviceAccount:{runtime_email}"
    operator_member = iam_access.principal_member(operator_email)
    site_origins = {
        "APP_URL": SETTINGS.APP.get("APP_URL"),
        "CUSTOM_DOMAIN": SETTINGS.APP.get("CUSTOM_DOMAIN"),
    }

    if not include_production and not include_test:
        raise ValueError("At least one Cloud Storage bucket family is required.")

    managed_buckets = {}
    if include_production:
        config = SimpleNamespace(**site_origins, local=False)
        managed_buckets.update(
            (name, (kind, config, None))
            for kind, name in storage_bucket_names(SETTINGS.APP).items()
        )
        managed_buckets[recovery_bucket_name(SETTINGS.APP)] = ("recovery", None, None)
    if include_test:
        test_settings = getattr(SETTINGS, "TEST_CONFIG", {}) or {}
        test_prefix = str(test_settings.get("PREFIX") or "")
        app_prefix = str(SETTINGS.APP.get("PREFIX") or "")
        if not test_prefix or test_prefix == app_prefix:
            raise RuntimeError(
                "Developer bucket provisioning requires a distinct test prefix."
            )
        host = test_settings.get("SERVER_NAME") or constants.DEFAULT_SERVER_NAME
        port = test_settings.get("SERVER_PORT") or constants.DEFAULT_TEST_PORT
        test_config = SimpleNamespace(
            **site_origins,
            local=host in {"127.0.0.1", "localhost", "[::1]"},
            SERVER_NAME=host,
            SERVER_PORT=port,
        )
        test_names = storage_bucket_names(dict(SETTINGS.APP, PREFIX=test_prefix))
        service_origin = hosted_test_service_cors_origin(project_id, str(site_origins["APP_URL"] or ""))
        managed_buckets.update(
            (name, (kind, test_config, service_origin)) for kind, name in test_names.items()
        )

    with f.progress(
        text="Configure Cloud Storage buckets",
        success_text='Cloud Storage buckets configured',
    ) as sp:
        for bucket_name, (bucket_kind, config, service_origin) in managed_buckets.items():
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
                configure_storage_bucket(bucket, config, preserve_cors_origin=service_origin)
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
        sp.ok()
    return True


def configure_data_protection() -> bool:
    """Enable PITR and reconcile daily/weekly native backup schedules."""
    import json

    from config import SETTINGS

    project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
    database = "(default)"
    retry_provider_call(
        lambda: run_gcloud_command(
            [
                "firestore",
                "databases",
                "update",
                f"--database={database}",
                "--enable-pitr",
                f"--project={project_id}",
                "--quiet",
            ]
        ),
        description="Enable Firestore point-in-time recovery",
        attempts=GCLOUD_API_PROPAGATION_ATTEMPTS,
        delays=GCLOUD_API_PROPAGATION_DELAYS,
        sleep=time.sleep,
    )
    result = run_gcloud_command(
        [
            "firestore",
            "backups",
            "schedules",
            "list",
            f"--database={database}",
            f"--project={project_id}",
            "--format=json",
        ]
    )
    try:
        schedules = json.loads(str(result.stdout or "[]"))
    except json.JSONDecodeError as error:
        raise RuntimeError("Firestore returned malformed backup schedules.") from error
    if not isinstance(schedules, list):
        raise RuntimeError("Firestore returned malformed backup schedules.")

    daily = next(
        (item for item in schedules if isinstance(item, dict) and "dailyRecurrence" in item),
        None,
    )
    weekly = next(
        (item for item in schedules if isinstance(item, dict) and "weeklyRecurrence" in item),
        None,
    )
    desired = (
        ("daily", "14d", daily, None),
        ("weekly", "98d", weekly, "SUN"),
    )
    for recurrence, retention, existing, day in desired:
        if existing:
            schedule_id = str(existing.get("name") or "").rsplit("/", 1)[-1]
            if not schedule_id:
                raise RuntimeError("Firestore backup schedule has no resource name.")
            arguments = [
                "firestore",
                "backups",
                "schedules",
                "update",
                f"--backup-schedule={schedule_id}",
                f"--database={database}",
                f"--retention={retention}",
                f"--project={project_id}",
                "--quiet",
            ]
        else:
            arguments = [
                "firestore",
                "backups",
                "schedules",
                "create",
                f"--database={database}",
                f"--retention={retention}",
                f"--recurrence={recurrence}",
                f"--project={project_id}",
                "--quiet",
            ]
            if day:
                arguments.insert(-2, f"--day-of-week={day}")
        run_gcloud_command(arguments)
    record_mutation(
        "reconcile database data protection",
        action="update",
        resource="firestore-data-protection",
        identifier=f"{project_id}/{database}",
        details={"pitr": True, "daily_retention": "14d", "weekly_retention": "98d"},
    )
    return True
