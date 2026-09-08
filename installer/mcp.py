"""Optional MCP service lifecycle shared by setup and ordinary app deployments."""

from runner import presentation as ui
from runner.presentation import output as print

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace

from config import SETTINGS
from config.ai_settings import normalize_ai_features
from config.locations import normalize_resource_region
from config.remote_mcp import https_url, mcp_issuer, normalize_mcp_config
from installer import iam, wrap_text
from installer.errors import ProviderTransientError, SetupError, retry_provider_call
from installer.state import record_mutation, record_step
from installer.utils import run_gcloud_command
from runner.context import REPOSITORY_ROOT, setup_command

SERVICE = "lagniappe-mcp"
BUILD_ACCOUNT = "lagniappe-mcp-build"
VERSION_LABEL = "lagniappe-mcp-version"
RUNTIME_ARGUMENTS = (
    "--allow-unauthenticated", "--min-instances=0", "--max-instances=2",
    "--concurrency=4", "--cpu=1", "--memory=1Gi", "--timeout=330s",
)
SERVICES = ("run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com")
PROJECT_PERMISSIONS = (
    "run.services.get", "run.services.create", "run.services.update",
    "run.services.getIamPolicy", "run.services.setIamPolicy",
    "cloudbuild.builds.create", "cloudbuild.builds.get",
    "artifactregistry.repositories.get", "artifactregistry.repositories.create",
    "artifactregistry.repositories.getIamPolicy", "artifactregistry.repositories.setIamPolicy",
    "iam.serviceAccounts.create", "iam.serviceAccounts.getIamPolicy",
    "iam.serviceAccounts.setIamPolicy", "resourcemanager.projects.getIamPolicy",
    "resourcemanager.projects.setIamPolicy", "storage.buckets.create",
    "logging.sinks.get", "logging.sinks.update",
    "datastore.indexes.get", "datastore.indexes.list", "datastore.indexes.update",
    "iam.serviceAccounts.get", "resourcemanager.projects.get", "serviceusage.services.enable",
)
# Navigation away from OAuth can put its query in another request's referrer.
# App Engine RequestLog and the shared HTTP envelope use different spellings.
AUTH_LOG_FILTER = (
    'resource.type="gae_app" AND ('
    'protoPayload.resource=~"^/oauth/" OR httpRequest.requestUrl=~"/oauth/" OR '
    'protoPayload.referrer=~"/oauth/" OR httpRequest.referer=~"/oauth/")'
)
AUTH_LOG_EXCLUSION = "remote-mcp-oauth-query"


# @testable infrastructure
@dataclass(frozen=True)
class Deployment:
    project: str
    region: str
    runtime: str
    build_account: str
    bucket: str
    issuer: str
    version: str
    image: str


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_version_tracks_only_build_inputs_and_rejects_symlinks
# @matrix mcp-install : source-version upload-boundary
def source_version(root=REPOSITORY_ROOT):
    """Identify the exact service build without coupling it to app releases."""
    root = Path(root)
    directory = root / "mcp"
    if directory.is_symlink() or (directory / "src").is_symlink() or not (directory / "src/lagniappe_mcp/server.py").is_file():
        raise SetupError("MCP source directory is missing or linked outside the build.")
    inputs = [directory / name for name in (
        "pyproject.toml", "uv.lock", "README.md", "Dockerfile", "cloudbuild.yaml", "gcloudignore",
    )]
    inputs.extend(path for path in (directory / "src").rglob("*")
                  if "__pycache__" not in path.parts and path.suffix != ".pyc")
    digest = hashlib.sha256(json.dumps(RUNTIME_ARGUMENTS).encode())
    for path in sorted(inputs):
        if path.is_symlink():
            raise SetupError("MCP build inputs must not contain symlinks.")
        if path.is_dir():
            continue
        if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
            raise SetupError("MCP build inputs are incomplete or outside mcp/.")
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:32]


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_policy_preserves_legacy_api_without_implicitly_installing_service
# @matrix mcp-install : configuration opt-in legacy-settings
def requested(settings):
    """Legacy REST access alone does not opt an installation into Cloud Run."""
    policy = normalize_ai_features(settings)
    return policy["EXTERNAL_AI_ENABLED"] and settings.get(
        "EXTERNAL_AI_ENABLED", bool(settings.get("MCP_RESOURCE"))
    ) is True


# @testable false
# @covered-by installer/mcp.py::_deployment
# @reason deterministic account naming is exercised through resource provisioning
def _available_account(project, name, occupied):
    """Keep managed MCP identities separate from the application's accounts."""
    email = f"{name}@{project}.iam.gserviceaccount.com"
    suffix = 2
    while email in occupied:
        email = f"{name}-{suffix}@{project}.iam.gserviceaccount.com"
        suffix += 1
    return email


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_install_keeps_app_runtime_and_build_accounts_separate
# @matrix mcp-install : configuration iam resources recovery
def _deployment(settings, *, version=None):
    project = settings.get("GOOGLE_CLOUD_PROJECT") or SETTINGS.GCLOUD_CONFIG.get("PROJECT")
    if not isinstance(project, str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise SetupError("MCP requires the installation's exact Google Cloud project.")
    region = normalize_resource_region(settings.get("RESOURCE_REGION"))
    issuer = mcp_issuer(settings)
    runtime = settings.get("MCP_SERVICE_ACCOUNT") or f"{SERVICE}@{project}.iam.gserviceaccount.com"
    if not runtime.endswith(f"@{project}.iam.gserviceaccount.com"):
        raise SetupError("MCP runtime identity must belong to this installation's project.")
    app_accounts = {
        settings.get("RUNTIME_SERVICE_ACCOUNT_EMAIL"),
        settings.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"),
    }
    # The app's account is named from the installation name, which may itself
    # be "lagniappe-mcp" or "lagniappe-mcp-build". Never reuse its privileges.
    if runtime in app_accounts:
        runtime = _available_account(project, SERVICE, app_accounts)
    build_account = _available_account(project, BUILD_ACCOUNT, app_accounts | {runtime})
    version = version or source_version()
    return Deployment(
        project, region, runtime, build_account,
        f"{project}-mcp-builds", issuer, version,
        f"{region}-docker.pkg.dev/{project}/{SERVICE}/server:{version}",
    )


# @testable false
# @covered-by installer/mcp.py::prepare_deployment
# @reason all provider commands are project-bound and use the shared setup error boundary
def _run(target, arguments, *, timeout=600, check=True):
    return run_gcloud_command(
        [*arguments, f"--project={target.project}", "--quiet"],
        check=check, timeout=timeout,
    )


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_discovery_distinguishes_absence_from_unavailable_state
# @matrix mcp-install : fail-closed provider-discovery
def describe(target, arguments, *, optional=False):
    result = _run(target, [*arguments, "--format=json"], check=False)
    if result.returncode:
        error = (result.stderr or "").casefold()
        denied = any(token in error for token in ("permission", "forbidden", "unauthorized", "403"))
        # Storage uses a different absence message from Run/IAM. Match the
        # exact requested bucket, not an arbitrary 404 from a provider failure.
        missing_bucket = (
            arguments[:3] == ["storage", "buckets", "describe"]
            and len(arguments) >= 4
            and re.fullmatch(
                rf"error: \(gcloud\.storage\.buckets\.describe\) {re.escape(arguments[3].casefold())} not found: 404\.?",
                error.strip(),
            ) is not None
        )
        # Artifact Registry translates HttpNotFoundError into this diagnostic,
        # followed by image-reference help rather than a numeric status code.
        missing_image = (
            arguments[:4] == ["artifacts", "docker", "images", "describe"]
            and error.strip().partition("\n")[0].strip()
            == "error: (gcloud.artifacts.docker.images.describe) image not found."
        )
        if optional and not denied and (missing_bucket or missing_image or any(
            token in error for token in ("not_found", "httperror 404", "cannot find service")
        )):
            return None
        raise SetupError(f"MCP provider discovery failed: {(result.stderr or '').strip()}")
    try:
        value = json.loads(result.stdout)
    except (TypeError, ValueError) as error:
        raise SetupError("MCP provider returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise SetupError("MCP provider returned an unexpected resource.")
    return value


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_permissions_are_checked_before_resource_mutation
# @matrix mcp-install : iam preflight
def require_permissions(target, *, client=None):
    if client is None:
        from google.cloud import resourcemanager_v3
        client = resourcemanager_v3.ProjectsClient()
    result = client.test_iam_permissions(request={
        "resource": f"projects/{target.project}", "permissions": list(PROJECT_PERMISSIONS),
    }, timeout=30)
    missing = sorted(set(PROJECT_PERMISSIONS) - set(result.permissions))
    if missing:
        raise SetupError(
            "The installer/deployer lacks MCP provisioning permissions: "
            + ", ".join(missing) + ". Ask the project Owner to grant them before retrying."
        )


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_iam_preserves_conditions_etags_and_skips_noop_writes
# @matrix mcp-install : iam idempotence handoff
def reconcile_access(target, command, resource, grants=(), *, flags=(), remove_member=None):
    """Apply scoped bindings using the existing IAM reconciler and provider etag."""
    policy = describe(target, [*command, "get-iam-policy", resource, *flags])
    view = SimpleNamespace(bindings=policy.get("bindings", []))
    changed = False
    for member, roles in grants:
        changed |= iam.reconcile_member_roles(
            view, member, desired_roles=roles, managed_roles=roles,
            binding_factory=lambda role, members: {"role": role, "members": members},
        )
    if remove_member:
        changed |= iam.remove_member_bindings(view, remove_member)
    if not changed:
        return
    policy.update(bindings=view.bindings, version=3)
    with tempfile.TemporaryDirectory(prefix="lagniappe-mcp-iam-") as directory:
        path = Path(directory) / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        _run(target, [*command, "set-iam-policy", resource, str(path), *flags])
    verified = describe(target, [*command, "get-iam-policy", resource, *flags])
    checked = SimpleNamespace(bindings=verified.get("bindings", []))
    for member, roles in grants:
        if not set(roles).issubset(iam.policy_member_roles(checked, member, include_conditions=False)):
            raise SetupError(f"MCP IAM did not converge on {resource}.")
    if remove_member and iam.policy_member_roles(checked, remove_member):
        raise SetupError(f"Installer still has direct access to {resource}.")
    record_mutation("MCP IAM", action="updated", resource="MCP resource policy", identifier=resource)


# @testable false
# @covered-by installer/mcp.py::reconcile_resources
# @reason account discovery and creation are exercised by the resource reconciler
def _ensure_account(target, email):
    arguments = ["iam", "service-accounts", "describe", email]
    account = describe(target, arguments, optional=True)
    if account is None:
        _run(target, ["iam", "service-accounts", "create", email.partition("@")[0],
                      "--display-name=Lagniappe MCP"])
        record_mutation("MCP account creation", action="created",
                        resource="service-account", identifier=email)
        from installer.gcloud import (
            GCLOUD_API_PROPAGATION_ATTEMPTS,
            GCLOUD_API_PROPAGATION_DELAYS,
        )

        # @testable false
        # @covered-by installer/mcp.py::reconcile_resources
        # @reason newly created account visibility is owned by resource provisioning
        def read_created_account():
            result = describe(target, arguments, optional=True)
            if result is None:
                raise ProviderTransientError(
                    f"New MCP service account {email} is not visible yet."
                )
            return result

        # @testable false
        # @covered-by installer/mcp.py::reconcile_resources
        # @reason propagation feedback and backoff are exercised by provisioning
        def wait_for_visibility(delay):
            print(wrap_text(
                f"Waiting for Google IAM to make {email} available; "
                f"retrying in {delay} seconds..."
            ))
            time.sleep(delay)

        account = retry_provider_call(
            read_created_account,
            description="Verify newly created MCP service account",
            attempts=GCLOUD_API_PROPAGATION_ATTEMPTS,
            delays=GCLOUD_API_PROPAGATION_DELAYS,
            sleep=wait_for_visibility,
        )
    if account.get("email") != email or account.get("disabled"):
        raise SetupError("MCP service account is disabled or differs from the saved identity.")


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_resources_use_separate_build_identity_and_scoped_roles
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_resource_upgrade_covers_oauth_referrers_and_preserves_other_exclusions
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_account_creation_waits_for_visibility
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_account_readback_failure_stops_before_more_resources
# @matrix mcp-install : iam resources keyless privacy idempotence
# @matrix mcp-install : provider-convergence fail-closed
def reconcile_resources(target, deployer):
    require_permissions(target)
    _run(target, ["services", "enable", *SERVICES])
    for email in (target.runtime, target.build_account):
        _ensure_account(target, email)
    flags = [f"--location={target.region}"]
    repository = describe(target, ["artifacts", "repositories", "describe", SERVICE, *flags], optional=True)
    if repository is None:
        _run(target, ["artifacts", "repositories", "create", SERVICE, *flags,
                      "--repository-format=docker", "--description=Lagniappe MCP images"])
    repository = describe(target, ["artifacts", "repositories", "describe", SERVICE, *flags])
    if repository.get("format") != "DOCKER":
        raise SetupError("The MCP image repository is not a Docker repository.")
    bucket_url = f"gs://{target.bucket}"
    # The default gcloud projection omits projectNumber; ownership requires
    # the raw Storage API metadata, including on the post-create read.
    bucket = describe(target, ["storage", "buckets", "describe", bucket_url, "--raw"], optional=True)
    if bucket is None:
        _run(target, ["storage", "buckets", "create", bucket_url,
                      f"--location={target.region}", "--uniform-bucket-level-access",
                      "--public-access-prevention"])
        bucket = describe(target, ["storage", "buckets", "describe", bucket_url, "--raw"])
    project = describe(target, ["projects", "describe", target.project])
    bucket_project = bucket.get("project_number", bucket.get("projectNumber"))
    if not bucket_project or not project.get("projectNumber"):
        raise SetupError("The MCP build bucket ownership could not be verified: project number missing.")
    if str(bucket_project) != str(project["projectNumber"]):
        raise SetupError("The MCP build bucket belongs to a different project.")
    if str(bucket.get("location", "")).casefold() != target.region:
        raise SetupError("The MCP build bucket is in a different region.")
    member = iam.principal_member(deployer)
    build_member = iam.principal_member(target.build_account)
    for email in (target.runtime, target.build_account):
        reconcile_access(target, ["iam", "service-accounts"], email,
                         [(member, ["roles/iam.serviceAccountUser"])])
    reconcile_access(target, ["artifacts", "repositories"], SERVICE, [
        (build_member, ["roles/artifactregistry.writer"]),
        (member, ["roles/artifactregistry.admin"]),
    ], flags=flags)
    reconcile_access(target, ["storage", "buckets"], bucket_url, [
        (build_member, ["roles/storage.objectViewer"]),
        (member, ["roles/storage.admin"]),
    ])
    reconcile_access(target, ["projects"], target.project,
                     [(build_member, ["roles/logging.logWriter"])])
    _reconcile_oauth_resources(target)
    record_step("MCP resources verified")


# @testable false
# @covered-by installer/mcp.py::reconcile_resources
# @reason token expiry cleanup and request-log privacy are owned by resource setup
def _reconcile_oauth_resources(target):
    flags = ["--collection-group=mcp_oauth", "--database=(default)"]
    result = _run(target, ["firestore", "fields", "ttls", "list", *flags, "--format=json"])
    try:
        fields = json.loads(result.stdout)
        if not isinstance(fields, list):
            raise ValueError("expected TTL field list")
        configured = any(
            field.get("name", "").endswith("/fields/expires_at")
            and field.get("ttlConfig", {}).get("state") in {"ACTIVE", "CREATING"}
            for field in fields
        )
    except (TypeError, ValueError, AttributeError) as error:
        raise SetupError("MCP TTL discovery returned invalid data.") from error
    if not configured:
        _run(target, ["firestore", "fields", "ttls", "update", "expires_at", *flags, "--enable-ttl", "--async"])
    sink = describe(target, ["logging", "sinks", "describe", "_Default"])
    exclusion = next((row for row in sink.get("exclusions", []) if row.get("name") == AUTH_LOG_EXCLUSION), None)
    if exclusion is None or exclusion.get("filter") != AUTH_LOG_FILTER or exclusion.get("disabled"):
        action = "add" if exclusion is None else "update"
        _run(target, ["logging", "sinks", "update", "_Default",
                      f"--{action}-exclusion=name={AUTH_LOG_EXCLUSION},filter={AUTH_LOG_FILTER},disabled="])
        sink = describe(target, ["logging", "sinks", "describe", "_Default"])
        if not any(row.get("name") == AUTH_LOG_EXCLUSION and row.get("filter") == AUTH_LOG_FILTER
                   and not row.get("disabled") for row in sink.get("exclusions", [])):
            raise SetupError("MCP OAuth request-log exclusion did not converge.")


# @testable false
# @covered-by installer/mcp.py::prepare_deployment
# @covered-by installer/mcp.py::finish_deployment
# @reason canonical provider state is checked at both deployment boundaries
def _service(target):
    return describe(target, ["run", "services", "describe", SERVICE,
                             f"--region={target.region}"], optional=True)


# @testable false
# @covered-by installer/mcp.py::prepare_deployment
# @reason a saved exact resource cannot silently follow another service
def _resource(service):
    url = service.get("status", {}).get("url", "")
    https_url(url, origin=True)
    if not url.endswith(".run.app"):
        raise SetupError("MCP requires Cloud Run's canonical service URL.")
    return url + "/mcp"


# @testable false
# @covered-by installer/mcp.py::prepare_deployment
# @reason image discovery makes interrupted builds resumable without rebuilding
def _build(target, *, announce_progress=True):
    image = describe(target, ["artifacts", "docker", "images", "describe", target.image], optional=True)
    if image is not None:
        return
    if announce_progress:
        print(f"Building MCP service {target.version} in Cloud Build...")
    _run(target, [
        "builds", "submit", str(REPOSITORY_ROOT), f"--region={target.region}",
        f"--config={REPOSITORY_ROOT / 'mcp/cloudbuild.yaml'}",
        f"--ignore-file={REPOSITORY_ROOT / 'mcp/gcloudignore'}",
        f"--substitutions=_IMAGE={target.image}",
        f"--service-account=projects/{target.project}/serviceAccounts/{target.build_account}",
        f"--gcs-source-staging-dir=gs://{target.bucket}/source", "--timeout=1800s",
    ], timeout=1860)
    describe(target, ["artifacts", "docker", "images", "describe", target.image])
    record_mutation("MCP build", action="built", resource="MCP image", identifier=target.image)


# @testable false
# @covered-by installer/mcp.py::finish_deployment
# @reason the service revision owns both the image and its fixed API target
def _environment(target, resource, enabled):
    return {
        "LAGNIAPPE_MCP_ENABLED": "true" if enabled else "false",
        "LAGNIAPPE_MCP_ISSUER": target.issuer,
        "LAGNIAPPE_MCP_RESOURCE": resource,
    }


# @testable false
# @covered-by installer/mcp.py::finish_deployment
# @covered-by installer/mcp.py::inspect_deployment
# @reason readiness, identity, image version and env determine whether a revision is current
def _matches(service, target, resource):
    service = service or {}
    status = service.get("status", {})
    spec = service.get("spec", {}).get("template", {}).get("spec", {})
    containers = spec.get("containers", [])
    env = {entry.get("name"): entry.get("value") for entry in (containers[0].get("env", []) if containers else [])}
    ready = any(row.get("type") == "Ready" and str(row.get("status")).casefold() == "true"
                for row in status.get("conditions", []))
    return bool(
        ready and status.get("url", "") + "/mcp" == resource
        and status.get("latestReadyRevisionName") == status.get("latestCreatedRevisionName")
        and service.get("metadata", {}).get("labels", {}).get(VERSION_LABEL) == target.version
        and bool(status.get("latestReadyRevisionName"))
        and sum(row.get("percent", 0) for row in status.get("traffic", [])
                if row.get("revisionName") == status.get("latestReadyRevisionName")) == 100
        and bool(containers) and containers[0].get("image") == target.image
        and spec.get("serviceAccountName") == target.runtime
        and all(env.get(key) == value for key, value in _environment(target, resource, True).items())
    )


# @testable false
# @covered-by installer/mcp.py::prepare_deployment
# @covered-by installer/mcp.py::finish_deployment
# @reason revision writes happen only after preparation or a successful main app deployment
def _deploy_service(target, resource, *, enabled):
    variables = ",".join(f"{name}={value}" for name, value in _environment(target, resource, enabled).items())
    _run(target, [
        "run", "deploy", SERVICE, f"--region={target.region}", f"--image={target.image}",
        f"--service-account={target.runtime}", f"--update-env-vars={variables}",
        f"--update-labels=managed-by=lagniappe,{VERSION_LABEL}={target.version}",
        *RUNTIME_ARGUMENTS,
    ])
    _run(target, ["run", "services", "update-traffic", SERVICE,
                  f"--region={target.region}", "--to-latest"])
    record_mutation("MCP revision", action="deployed", resource="Cloud Run service", identifier=SERVICE,
                    details={"version": target.version, "enabled": enabled})


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_prepare_bootstraps_disabled_and_saves_exact_resource_before_app
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_unchanged_update_skips_build_and_revision
# @matrix mcp-install : bootstrap configuration source-version update-order
def prepare_deployment(settings=None, *, announce_progress=True):
    """Prepare the optional service and configuration before publishing App Engine."""
    settings = SETTINGS.APP if settings is None else settings
    if not requested(settings):
        return None
    target = _deployment(settings)
    record_step("prepare MCP service")
    deployer = settings.get("DEPLOYER_EMAIL") or SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
    if not deployer:
        raise SetupError("MCP requires the saved installer/deployer identity.")
    reconcile_resources(target, deployer)
    service = _service(target)
    saved_resource = settings.get("MCP_RESOURCE")
    if service is not None:
        resource = _resource(service)
        if saved_resource and saved_resource != resource:
            raise SetupError("The saved MCP resource differs from this Cloud Run service.")
        if not saved_resource and service.get("metadata", {}).get("labels", {}).get("managed-by") != "lagniappe":
            raise SetupError("An unmanaged Cloud Run service already uses the MCP service name.")
        if not _matches(service, target, resource):
            _build(target, announce_progress=announce_progress)
    else:
        _build(target, announce_progress=announce_progress)
        # Disabled startup does not contact the main app or use this placeholder.
        _deploy_service(target, "https://unconfigured.invalid/mcp", enabled=False)
        service = _service(target)
        if service is None:
            raise SetupError("The prepared MCP service could not be read back.")
        resource = _resource(service)
    settings.update(normalize_mcp_config({
        **settings, "MCP_RESOURCE": resource, "MCP_SERVICE_ACCOUNT": target.runtime,
    }))
    settings["MCP_VERSION"] = target.version
    reconcile_access(target, ["run", "services"], SERVICE,
                     [(iam.principal_member(deployer), ["roles/run.admin"])],
                     flags=[f"--region={target.region}"])
    return target


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_unchanged_update_skips_build_and_revision
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_disable_and_failed_activation_do_not_claim_success
# @matrix mcp-install : disable failure-recovery update-order verification
def finish_deployment(target=None, settings=None, *, announce_progress=True):
    """Activate only after the main app accepts the matching OAuth configuration."""
    settings = SETTINGS.APP if settings is None else settings
    if not requested(settings):
        if not settings.get("MCP_RESOURCE"):
            return
        target = _deployment(settings, version=settings.get("MCP_VERSION") or "disabled")
        service = _service(target)
        if service is not None:
            if _resource(service) != settings["MCP_RESOURCE"]:
                raise SetupError("The saved MCP resource differs from this Cloud Run service.")
            if _enabled(service):
                _run(target, ["run", "services", "update", SERVICE, f"--region={target.region}",
                              "--update-env-vars=LAGNIAPPE_MCP_ENABLED=false"])
                _run(target, ["run", "services", "update-traffic", SERVICE,
                              f"--region={target.region}", "--to-latest"])
                verified = _service(target)
                if verified is None or _enabled(verified):
                    raise SetupError(f"MCP disable could not be verified. Retry with {setup_command('mcp')}.")
                record_mutation("MCP disable", action="disabled", resource="Cloud Run service", identifier=SERVICE)
        if announce_progress:
            print("External AI access is disabled.")
        return
    if target is None:
        raise SetupError(f"MCP deployment was not prepared. Run {setup_command('mcp')}.")
    resource = settings["MCP_RESOURCE"]
    if _matches(_service(target), target, resource):
        if announce_progress:
            print(ui.status(f"MCP service {target.version} is unchanged; no new revision needed."))
        return
    record_step("deploy MCP service after application")
    if announce_progress:
        print(f"Deploying MCP service {target.version}...")
    _deploy_service(target, resource, enabled=True)
    if not _matches(_service(target), target, resource):
        raise SetupError(f"MCP revision did not become ready. Retry with {setup_command('mcp')}.")
    if announce_progress:
        from installer import FORMATTER

        f = FORMATTER.initialize()
        print(f.success('MCP server is ready'))


# @testable false
# @covered-by installer/mcp.py::finish_deployment
# @covered-by installer/mcp.py::inspect_deployment
# @reason persisted service environment is read at disable and diagnostic boundaries
def _enabled(service):
    spec = (service or {}).get("spec", {}).get("template", {}).get("spec", {})
    return any(entry.get("name") == "LAGNIAPPE_MCP_ENABLED" and entry.get("value") == "true"
               for container in spec.get("containers", []) for entry in container.get("env", []))


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_inspection_is_read_only_and_detects_version_drift
# @matrix mcp-install : doctor recovery source-version
def inspect_deployment(settings):
    if not requested(settings):
        if settings.get("MCP_RESOURCE"):
            target = _deployment(settings, version=settings.get("MCP_VERSION") or "disabled")
            service = _service(target)
            if service is not None and (_resource(service) != settings["MCP_RESOURCE"] or _enabled(service)):
                return {"state": "UNAVAILABLE", "details": {"message": f"Reconcile disabled MCP with {setup_command('mcp')}."}}
        return {"state": "AVAILABLE", "details": {"message": "MCP is not selected."}}
    target = _deployment(settings)
    service = _service(target)
    resource = settings.get("MCP_RESOURCE")
    if service is None or not resource or _resource(service) != resource or not _matches(service, target, resource):
        return {"state": "UNAVAILABLE", "details": {"message": f"MCP is missing or out of date; run {setup_command('mcp')}."}}
    return {"state": "AVAILABLE", "details": {"version": target.version}}


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_handoff_uses_selected_accounts_and_scoped_resources
# @matrix mcp-install : handoff iam
def handoff_access(settings, *, owner=None, remove_installer=None):
    """Transfer exact MCP resource access before removing the installer's project role."""
    if not settings.get("MCP_RESOURCE"):
        return
    target = _deployment(settings)
    member = iam.principal_member(owner) if owner else None
    remove_member = iam.principal_member(remove_installer) if remove_installer else None
    resources = [
        (["iam", "service-accounts"], target.runtime, [], "roles/iam.serviceAccountUser"),
        (["iam", "service-accounts"], target.build_account, [], "roles/iam.serviceAccountUser"),
        (["storage", "buckets"], f"gs://{target.bucket}", [], "roles/storage.admin"),
        (["artifacts", "repositories"], SERVICE, [f"--location={target.region}"], "roles/artifactregistry.admin"),
        (["run", "services"], SERVICE, [f"--region={target.region}"], "roles/run.admin"),
    ]
    for command, resource, flags, role in resources:
        # Older installations may not yet have the dedicated build resources.
        if describe(target, [*command, "describe", resource, *flags], optional=True) is None:
            continue
        reconcile_access(target, command, resource, [(member, [role])] if member else [],
                         flags=flags, remove_member=remove_member)


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_focused_mcp_command_uses_normal_deployment_path
# @matrix mcp-install : cli-routing retry
def configure_mcp():
    from installer.verify import prepare_existing_installation
    from installer.utils import deploy_to_app_engine
    prepare_existing_installation()
    if not requested(SETTINGS.APP) and not SETTINGS.APP.get("MCP_RESOURCE"):
        raise SetupError(f"External AI is disabled. Choose it with {setup_command('ai')} first.")
    deploy_to_app_engine()
    return 0
