"""Reconcile the experiments operator's resource-scoped grants using its installer's identity."""

import argparse
import json
from pathlib import Path
import subprocess

from config.constants import DEFAULT_TEST_PREFIX
from config.experiments import normalize_experiments_config
from config.storage import storage_bucket_names
from runner import cloud_settings
from runner.context import GCLOUD_CLI

# The only custom role that changes IAM can change Cloud Run job policies.
CUSTOM = {
    "lagniappeSettingsPublisher": (
        "Publish Lagniappe settings",
        [
            "secretmanager.secrets.get",
            "secretmanager.secrets.update",
            "secretmanager.versions.add",
        ],
    ),
    "lagniappeTestBucketCors": (
        "Update Lagniappe test bucket CORS",
        [
            "storage.buckets.get",
            "storage.buckets.update",
        ],
    ),
    "lagniappeHostedJobPolicy": (
        "Bind Lagniappe hosted job invoker",
        [
            "run.jobs.getIamPolicy",
            "run.jobs.setIamPolicy",
        ],
    ),
}


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_operator_grants_stay_in_experiments
# @matrix hosted-e2e setup : iam project-identity
def bindings(
    project, app, setup, build_account, *, app_engine_account=None,
    hosted_job_exists=False, project_job_policy=False,
):
    from runner.hosted_e2e import JOB

    policy = normalize_experiments_config(app)
    if (
        not policy["EXPERIMENTS_ENABLED"]
        or policy["EXPERIMENTS_PROJECT"] != project
        or setup["project"] != project
        or setup["project_number"] == ""
        or setup["job"] != JOB
    ):
        raise ValueError(
            "Select the same experiments installation for settings and hosted setup."
        )
    roles = f"projects/{project}/roles/"
    project_target = ["projects", "add-iam-policy-binding", project]
    grants = []
    for role in (
        "serviceusage.serviceUsageConsumer",
        "appengine.deployer",
        "appengine.serviceAdmin",
        "datastore.indexAdmin",
        "cloudbuild.builds.editor",
        "run.developer",
        "logging.viewer",
    ):
        grants.append((project_target, "roles/" + role))
    if project_job_policy:
        grants.append((project_target, roles + "lagniappeHostedJobPolicy"))
    elif hosted_job_exists:
        grants.append(
            (
                ["run", "jobs", "add-iam-policy-binding", JOB, f"--region={setup['region']}"],
                roles + "lagniappeHostedJobPolicy",
            )
        )
    deployment_accounts = {
        build_account,
        setup["runtime_email"],
        app["RUNTIME_SERVICE_ACCOUNT_EMAIL"],
    }
    if app_engine_account:
        deployment_accounts.add(app_engine_account)
    for account in sorted(deployment_accounts):
        grants.append(
            (
                ["iam", "service-accounts", "add-iam-policy-binding", account],
                "roles/iam.serviceAccountUser",
            )
        )
    for runtime in {app["RUNTIME_SERVICE_ACCOUNT_EMAIL"], setup["runtime_email"]}:
        grants.append(
            (
                ["iam", "service-accounts", "add-iam-policy-binding", runtime],
                "roles/iam.serviceAccountTokenCreator",
            )
        )
    secret = ["secrets", "add-iam-policy-binding", cloud_settings.SECRET]
    grants.extend(
        [
            (secret, "roles/secretmanager.secretAccessor"),
            (secret, roles + "lagniappeSettingsPublisher"),
        ]
    )
    for secret_name in (setup["settings_secret"], setup["redis_ca_secret"]):
        grants.append(
            (
                ["secrets", "add-iam-policy-binding", secret_name],
                "roles/secretmanager.secretVersionAdder",
            )
        )
    bucket = ["storage", "buckets", "add-iam-policy-binding"]
    checkpoint_bucket = f"{project}-lagniappe-operator"
    for name in (
        f"staging.{project}.appspot.com",
        f"{project}_cloudbuild",
        checkpoint_bucket,
    ):
        for role in ("roles/storage.objectUser", "roles/storage.legacyBucketReader"):
            grants.append(([*bucket, f"gs://{name}"], role))
    grants.append(
        ([*bucket, "gs://" + setup["artifact_bucket"]], "roles/storage.objectViewer")
    )
    for name in storage_bucket_names(dict(app, PREFIX=DEFAULT_TEST_PREFIX)).values():
        grants.append(([*bucket, f"gs://{name}"], roles + "lagniappeTestBucketCors"))
    if app.get("MCP_RESOURCE"):
        from installer.mcp import SERVICE, _deployment

        target = _deployment(app, version="provisioning")
        for account in (target.runtime, target.build_account):
            grants.append(
                (
                    ["iam", "service-accounts", "add-iam-policy-binding", account],
                    "roles/iam.serviceAccountUser",
                )
            )
        for role in ("roles/storage.objectUser", "roles/storage.legacyBucketReader"):
            grants.append(([*bucket, f"gs://{target.bucket}"], role))
        grants.append(
            (
                [
                    "artifacts",
                    "repositories",
                    "add-iam-policy-binding",
                    SERVICE,
                    f"--location={target.region}",
                ],
                "roles/artifactregistry.reader",
            )
        )
        grants.append(
            (
                [
                    "run",
                    "services",
                    "add-iam-policy-binding",
                    SERVICE,
                    f"--region={target.region}",
                ],
                "roles/run.admin",
            )
        )
    grants.append(
        (
            [
                "artifacts",
                "repositories",
                "add-iam-policy-binding",
                setup["artifact_repository"],
                f"--location={setup['region']}",
            ],
            "roles/artifactregistry.reader",
        )
    )
    return grants


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_operator_checks_both_build_accounts_before_granting_access
# @matrix hosted-e2e setup : iam project-identity
def _build_accounts(base, project, *, apply):
    """Discover the two build identities and check the privileges actAs would convey."""
    build = subprocess.check_output(
        [
            *base, "builds", "get-default-service-account",
            "--format=value(serviceAccountEmail)",
        ],
        text=True,
    ).strip().rsplit("/", 1)[-1]
    app = json.loads(subprocess.check_output(
        [*base, "app", "describe", "--format=json(id,serviceAccount)"], text=True
    ))
    app_engine = app.get("serviceAccount")
    if app.get("id") != project or not app_engine or not build:
        raise SystemExit("Could not identify both build accounts for the selected project.")
    policy = json.loads(subprocess.check_output(
        [*base, "projects", "get-iam-policy", project, "--format=json(bindings)"],
        text=True,
    ))
    members = {f"serviceAccount:{account}" for account in (app_engine, build)}
    for binding in policy["bindings"]:
        if binding["role"] in {"roles/editor", "roles/owner"}:
            broad = members.intersection(binding["members"])
            if broad:
                message = (
                    f"{', '.join(sorted(broad))} has {binding['role']} in {project}. "
                    "Replace the broad project role with build permissions before granting actAs."
                )
                if apply:
                    raise SystemExit(message)
                print(message)
    return build, app_engine


# @testable infrastructure
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--from-checkout", type=Path, required=True)
    parser.add_argument(
        "--project-job-policy", action="store_true",
        help="Grant the operator IAM policy access to every Cloud Run job in this experiments project.",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.from_checkout.resolve()
    project = args.project
    bundle = cloud_settings._local_bundle(root, project, cloud_settings._receipt(root))
    app, dev = cloud_settings.validate_bundle(bundle, project)
    target = dev["gcloud_config"]
    setup = json.loads(
        cloud_settings._read(root, Path("reports/hosted-e2e/setup.json"))
    )
    base = [
        GCLOUD_CLI,
        "--quiet",
        f"--project={project}",
        f"--configuration={target['NAME']}",
        f"--account={target['ACCOUNT']}",
    ]
    build, app_engine = _build_accounts(base, project, apply=args.apply)
    job_exists = False
    if not args.project_job_policy:
        job_names = subprocess.check_output(
            [*base, "run", "jobs", "list", f"--region={setup['region']}", "--format=value(metadata.name)"],
            text=True,
        ).splitlines()
        job_exists = setup["job"] in job_names
    grants = bindings(
        project, app, setup, build, app_engine_account=app_engine,
        hosted_job_exists=job_exists, project_job_policy=args.project_job_policy,
    )
    if not args.project_job_policy and not job_exists:
        print(f"Job-scoped provisioning requires {setup['job']} to exist for its IAM grant.")
    member = (
        f"--member=serviceAccount:lagniappe-codex@{project}.iam.gserviceaccount.com"
    )
    existing = json.loads(
        subprocess.check_output(
            [*base, "iam", "roles", "list", "--format=json(name)"], text=True
        )
    )
    names = {role["name"] for role in existing}
    for name, (title, perms) in CUSTOM.items():
        if f"projects/{project}/roles/{name}" in names:
            data = json.loads(
                subprocess.check_output(
                    [
                        *base,
                        "iam",
                        "roles",
                        "describe",
                        name,
                        "--format=json(includedPermissions,deleted)",
                    ],
                    text=True,
                )
            )
            if data.get("deleted") or set(data["includedPermissions"]) != set(perms):
                raise SystemExit(
                    f"Review the existing custom role {name} before granting it."
                )
        elif args.apply:
            subprocess.run(
                [
                    *base,
                    "iam",
                    "roles",
                    "create",
                    name,
                    f"--title={title}",
                    "--stage=GA",
                    "--permissions=" + ",".join(perms),
                    "--format=none",
                ],
                check=True,
            )
    for resource, role in grants:
        print(" ".join(resource), role, flush=True)
        if args.apply:
            command = [*base, *resource, member, f"--role={role}", "--format=none"]
            if resource[0] == "projects" and not any(
                x.startswith("--condition") for x in resource
            ):
                command.append("--condition=None")
            subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
