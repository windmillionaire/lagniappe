"""Resumable delegated-installation handoff to the permanent business Owner."""

from config.storage import recovery_bucket_name, storage_bucket_names
from installer import iam
from installer.package_install import install_if_missing
from installer.state import record_step


OWNER_ROLE = "roles/owner"


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_handoff_operator_preparation_accepts_installer_or_owner
# @pairs handoff:operator handoff:installer handoff:owner handoff:active-account
# @pairs handoff:gcloud handoff:adc handoff:preconditions
def prepare_handoff_operator():
    """Activate the saved project as either permitted handoff operator."""
    from config import SETTINGS
    from runner import gcloud as runner_gcloud

    installer_email = str(
        SETTINGS.APP.get("INSTALLER_EMAIL") or ""
    ).strip().casefold()
    owner_email = str(SETTINGS.APP.get("ADMIN_EMAIL") or "").strip().casefold()
    allowed = {email for email in (installer_email, owner_email) if email}
    if len(allowed) != 2:
        raise RuntimeError(
            "Handoff requires distinct saved installer and Owner identities."
        )

    active_email = str(
        runner_gcloud.get_configuration_value("account") or ""
    ).strip().casefold()
    if active_email not in allowed:
        permitted = " or ".join(sorted(allowed))
        raise RuntimeError(
            "The active gcloud account must be the saved installer or permanent "
            f"Owner ({permitted}); found {active_email or '(unset)'}."
        )

    saved_account = SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
    SETTINGS.GCLOUD_CONFIG["ACCOUNT"] = active_email
    try:
        runner_gcloud.activate_repository_gcloud(
            ensure_adc=True,
            ensure_cli_token=True,
        )
    finally:
        if saved_account is None:
            SETTINGS.GCLOUD_CONFIG.pop("ACCOUNT", None)
        else:
            SETTINGS.GCLOUD_CONFIG["ACCOUNT"] = saved_account

    role = "permanent Owner" if active_email == owner_email else "installer"
    print(f"[OK] Handoff operator: {active_email} ({role})")
    return active_email


# @testable false
# @covered-by installer/handoff.py::handoff
# @reason terminal-only role formatting is exercised through the handoff preview
def _role_list(roles):
    return ", ".join(sorted(roles)) if roles else "(no current direct binding)"


# @testable false
# @covered-by installer/handoff.py::handoff
# @reason provider client composition is exercised through the injected transaction contract
def _cloud_context(project_id, bucket_names):
    install_if_missing(
        "google.cloud.resourcemanager_v3",
        "Google Resource Manager API",
        package_name="google-cloud-resource-manager",
    )
    install_if_missing(
        "google.cloud.iam_admin_v1",
        "Google IAM Admin API",
        package_name="google-cloud-iam",
    )
    install_if_missing(
        "google.cloud.storage",
        "Google Cloud Storage",
        package_name="google-cloud-storage",
    )
    from google.cloud import iam_admin_v1, resourcemanager_v3, storage

    storage_client = storage.Client(project=project_id)
    return {
        "projects": resourcemanager_v3.ProjectsClient(),
        "service_accounts": iam_admin_v1.IAMClient(),
        "buckets": {
            name: storage_client.get_bucket(name) for name in bucket_names
        },
    }


# @testable false
# @covered-by installer/handoff.py::handoff
# @reason provider policy fetch shape is owned by the handoff transaction
def _project_policy(client, project_id):
    return client.get_iam_policy(
        request={
            "resource": f"projects/{project_id}",
            "options": {"requested_policy_version": 3},
        }
    )


# @testable false
# @covered-by installer/handoff.py::handoff
# @reason provider policy fetch shape is owned by the handoff transaction
def _service_account_policy(client, project_id, runtime_email):
    resource = f"projects/{project_id}/serviceAccounts/{runtime_email}"
    policy = client.get_iam_policy(
        request={
            "resource": resource,
            "options": {"requested_policy_version": 3},
        }
    )
    return resource, policy


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_delegated_handoff_orders_mutations_preserves_unrelated_members_and_is_idempotent
# @pairs handoff:owner-add handoff:bucket handoff:service-account
# @pairs handoff:idempotence handoff:verification
def _grant_owner_resource_access(context, project_id, runtime_email, owner_email):
    from google.iam.v1 import policy_pb2

    owner_member = iam.principal_member(owner_email)
    for bucket in context["buckets"].values():
        policy = bucket.get_iam_policy(requested_policy_version=3)
        changed = iam.reconcile_member_roles(
            policy,
            owner_member,
            desired_roles=set(iam.constants.OPERATOR_BUCKET_ROLES),
            managed_roles=set(iam.constants.OPERATOR_BUCKET_ROLES),
            binding_factory=lambda role, members: {
                "role": role,
                "members": set(members),
            },
        )
        if changed:
            bucket.set_iam_policy(policy)
        verified = bucket.get_iam_policy(requested_policy_version=3)
        if not set(iam.constants.OPERATOR_BUCKET_ROLES).issubset(
            iam.policy_member_roles(verified, owner_member)
        ):
            raise RuntimeError(
                f"Permanent Owner access did not verify on bucket '{bucket.name}'."
            )

    resource, policy = _service_account_policy(
        context["service_accounts"], project_id, runtime_email
    )
    changed = iam.reconcile_member_roles(
        policy,
        owner_member,
        desired_roles=set(iam.constants.RUNTIME_SERVICE_ACCOUNT_ROLES),
        managed_roles=set(iam.constants.RUNTIME_SERVICE_ACCOUNT_ROLES),
        binding_factory=lambda role, members: policy_pb2.Binding(
            role=role, members=members
        ),
    )
    if changed:
        context["service_accounts"].set_iam_policy(
            request={"resource": resource, "policy": policy}
        )
    _, verified = _service_account_policy(
        context["service_accounts"], project_id, runtime_email
    )
    if not set(iam.constants.RUNTIME_SERVICE_ACCOUNT_ROLES).issubset(
        iam.policy_member_roles(verified, owner_member)
    ):
        raise RuntimeError(
            "Permanent Owner access did not verify on the runtime service account."
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_delegated_handoff_orders_mutations_preserves_unrelated_members_and_is_idempotent
# @pairs handoff:installer-removal handoff:bucket handoff:service-account
# @pairs handoff:verification handoff:unrelated-members
def _remove_installer_resource_access(
    context, project_id, runtime_email, installer_email
):
    installer_member = iam.principal_member(installer_email)
    for bucket in context["buckets"].values():
        policy = bucket.get_iam_policy(requested_policy_version=3)
        if iam.remove_member_bindings(policy, installer_member):
            bucket.set_iam_policy(policy)
        verified = bucket.get_iam_policy(requested_policy_version=3)
        if iam.policy_member_roles(verified, installer_member):
            raise RuntimeError(
                f"Installer still has direct IAM on bucket '{bucket.name}'."
            )

    resource, policy = _service_account_policy(
        context["service_accounts"], project_id, runtime_email
    )
    if iam.remove_member_bindings(policy, installer_member):
        context["service_accounts"].set_iam_policy(
            request={"resource": resource, "policy": policy}
        )
    _, verified = _service_account_policy(
        context["service_accounts"], project_id, runtime_email
    )
    if iam.policy_member_roles(verified, installer_member):
        raise RuntimeError("Installer still has direct IAM on the runtime service account.")


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_delegated_handoff_orders_mutations_preserves_unrelated_members_and_is_idempotent
# @pairs handoff:project-role handoff:final-mutation handoff:owner-lockout
# @pairs handoff:verification handoff:all-bindings
def _remove_installer_project_access(
    context, project_id, installer_email, owner_email
):
    project_client = context["projects"]
    installer_member = iam.principal_member(installer_email)
    owner_member = iam.principal_member(owner_email)
    policy = _project_policy(project_client, project_id)
    if iam.remove_member_bindings(policy, installer_member):
        project_client.set_iam_policy(
            request={"resource": f"projects/{project_id}", "policy": policy}
        )

    verified = _project_policy(project_client, project_id)
    if iam.policy_member_roles(verified, installer_member):
        raise RuntimeError("Installer still has a direct project IAM binding.")
    if OWNER_ROLE not in iam.policy_member_roles(
        verified, owner_member, include_conditions=False
    ):
        raise RuntimeError(
            "Permanent Owner binding disappeared during handoff verification."
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_delegated_handoff_orders_mutations_preserves_unrelated_members_and_is_idempotent
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_delegated_handoff_rejects_owner_lockout_and_default_no_confirmation
# @pairs handoff:preconditions handoff:preview handoff:confirmation handoff:ordering
# @pairs handoff:resumable handoff:idempotence handoff:cleanup
# @pairs handoff:settings handoff:deploy handoff:owner-lockout
# @pairs handoff:default-no handoff:no-mutation
def handoff(*, context=None, deploy=None, confirm=None, permission_check=None):
    """Transfer Lagniappe-managed operator access from installer to Owner."""
    from config import File, SETTINGS
    from installer import utils

    if not File.APP_SETTINGS_YAML.exists():
        raise RuntimeError("Production settings are required before handoff.")

    settings = SETTINGS.APP
    project_id = str(settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    installer_email = str(settings.get("INSTALLER_EMAIL") or "").strip().casefold()
    owner_email = str(settings.get("ADMIN_EMAIL") or "").strip().casefold()
    runtime_email = str(
        settings.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    if not all((project_id, installer_email, owner_email, runtime_email)):
        raise RuntimeError(
            "Handoff requires project, installer, Owner, and runtime identities."
        )
    if installer_email == owner_email:
        raise RuntimeError("Installer and permanent Owner must be distinct.")

    managed_bucket_names = [
        *storage_bucket_names(settings).values(),
        recovery_bucket_name(settings),
    ]
    context = context or _cloud_context(project_id, managed_bucket_names)
    project_policy = _project_policy(context["projects"], project_id)
    owner_member = iam.principal_member(owner_email)
    if OWNER_ROLE not in iam.policy_member_roles(
        project_policy, owner_member, include_conditions=False
    ):
        raise RuntimeError(
            f"Permanent Owner {owner_email} must already hold roles/owner on "
            f"project {project_id}."
        )

    permission_check = permission_check or iam.require_operator_permissions
    permission_check(project_id)
    for bucket in context["buckets"].values():
        iam.require_installer_bucket_permissions(bucket)

    installer_member = iam.principal_member(installer_email)
    bucket_installer_roles = {
        name: iam.policy_member_roles(
            bucket.get_iam_policy(requested_policy_version=3), installer_member
        )
        for name, bucket in context["buckets"].items()
    }
    _runtime_resource, runtime_policy = _service_account_policy(
        context["service_accounts"], project_id, runtime_email
    )
    runtime_installer_roles = iam.policy_member_roles(
        runtime_policy, installer_member
    )
    project_installer_roles = iam.policy_member_roles(
        project_policy, installer_member
    )

    print("\n=== Delegated installation handoff ===")
    print(f"Installer/source: {installer_email}")
    print(f"Permanent Owner/deployer: {owner_email}")
    print(f"Target project: {project_id}")
    print(f"Runtime service account: {runtime_email}")
    print("Planned binding changes:")
    for name in managed_bucket_names:
        print(f"  Bucket {name}:")
        print(f"    add Owner: {_role_list(iam.constants.OPERATOR_BUCKET_ROLES)}")
        print(
            "    remove installer: "
            f"{_role_list(bucket_installer_roles.get(name, set()))}"
        )
    print(f"  Runtime service account {runtime_email}:")
    print(
        "    add Owner: "
        f"{_role_list(iam.constants.RUNTIME_SERVICE_ACCOUNT_ROLES)}"
    )
    print(f"    remove installer: {_role_list(runtime_installer_roles)}")
    print("  Application configuration:")
    print(f"    set DEPLOYER_EMAIL: {owner_email}")
    print(f"    set saved gcloud account: {owner_email}")
    print("    clear BOOTSTRAP_ADMIN_EMAIL and deploy")
    print(f"  Project {project_id} (final cloud mutation):")
    print(f"    retain Owner: {OWNER_ROLE}")
    print(f"    remove installer: {_role_list(project_installer_roles)}")
    answer = (confirm or input)("Continue with handoff? [y/N]: ")
    if str(answer or "").strip().casefold() not in {"y", "yes"}:
        print("Handoff cancelled. No changes were made.")
        return 1

    record_step("grant permanent Owner managed-resource access")
    _grant_owner_resource_access(context, project_id, runtime_email, owner_email)

    record_step("deploy permanent Owner configuration")
    settings["DEPLOYER_EMAIL"] = owner_email
    settings["BOOTSTRAP_ADMIN_EMAIL"] = ""
    SETTINGS.GCLOUD_CONFIG["ACCOUNT"] = owner_email
    SETTINGS.save()
    (deploy or utils.deploy_to_app_engine)(print_final_summary=False)

    record_step("remove installer managed-resource access")
    _remove_installer_resource_access(
        context, project_id, runtime_email, installer_email
    )

    record_step("remove installer project IAM access")
    _remove_installer_project_access(
        context, project_id, installer_email, owner_email
    )

    print("\nHandoff complete. INSTALLER_EMAIL was retained as historical metadata.")
    print("Remaining business cleanup:")
    print("  Verify the installer is absent from Google Cloud project IAM.")
    print("  Revoke provider invitations and temporary access tokens.")
    print("  Remove local credentials and settings from the installer's machine.")
    print("  Suspend, then delete the temporary Workspace user when no longer needed.")
    print("  Rotate any secret that could not remain business-controlled.")
    return 0


__all__ = ["handoff", "prepare_handoff_operator"]
