"""Least-privilege IAM planning, preflight, and policy reconciliation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol


from config import constants
from installer.package_install import install_if_missing


if TYPE_CHECKING:
    from google.cloud.resourcemanager_v3 import ProjectsClient
    from google.cloud.storage import Bucket

class _Policy(Protocol):
    @property
    def bindings(self) -> Iterable[object]: ...

class _PermissionResult(Protocol):
    @property
    def permissions(self) -> Iterable[str]: ...

class _PermissionClient(Protocol):
    def test_iam_permissions(
        self, *, request: dict[str, object], timeout: float
    ) -> _PermissionResult: ...


PROJECT_OWNER_ROLE = "roles/owner"


def principal_member(email: str) -> str:
    """Return the IAM member string for a Google user or service account."""
    principal_type = (
        "serviceAccount"
        if str(email).casefold().endswith(".gserviceaccount.com")
        else "user"
    )
    return f"{principal_type}:{email}"


def _binding_value(binding, key, default=None):
    if isinstance(binding, dict):
        return binding.get(key, default)
    return getattr(binding, key, default)


def _set_binding_value(binding, key, value):
    if isinstance(binding, dict):
        binding[key] = value
    else:
        current = getattr(binding, key)
        if key == "members":
            del current[:]
            current.extend(value)
        else:
            setattr(binding, key, value)


def _is_conditional(binding):
    condition = _binding_value(binding, "condition")
    if not condition:
        return False
    if isinstance(condition, dict):
        return any(condition.get(key) for key in ("title", "description", "expression"))
    return any(
        getattr(condition, key, None)
        for key in ("title", "description", "expression")
    )


def _replace_bindings(policy, bindings):
    try:
        policy.bindings = bindings
    except AttributeError:
        del policy.bindings[:]
        policy.bindings.extend(bindings)


def reconcile_member_roles(
    policy: _Policy,
    member: str,
    *,
    desired_roles: Iterable[str],
    managed_roles: Iterable[str],
    binding_factory: Callable[[str, list[str]], object],
) -> bool:
    """Reconcile one Lagniappe member without changing conditional bindings."""
    desired_roles = set(desired_roles)
    managed_roles = set(managed_roles) | desired_roles
    bindings = list(policy.bindings)
    rebuilt = []
    first_unconditional = {}
    changed = False

    for binding in bindings:
        role = _binding_value(binding, "role")
        if role not in managed_roles or _is_conditional(binding):
            rebuilt.append(binding)
            continue

        members = list(_binding_value(binding, "members", ()) or ())
        if role not in first_unconditional:
            first_unconditional[role] = binding
            rebuilt.append(binding)
            continue

        target = first_unconditional[role]
        target_members = list(_binding_value(target, "members", ()) or ())
        for existing_member in members:
            if existing_member not in target_members:
                target_members.append(existing_member)
        _set_binding_value(target, "members", target_members)
        changed = True

    for role, binding in list(first_unconditional.items()):
        members = list(_binding_value(binding, "members", ()) or ())
        if role in desired_roles:
            reconciled = []
            member_seen = False
            for existing in members:
                if existing == member:
                    if member_seen:
                        continue
                    member_seen = True
                reconciled.append(existing)
            if not member_seen:
                reconciled.append(member)
        else:
            reconciled = [existing for existing in members if existing != member]
        if reconciled != members:
            _set_binding_value(binding, "members", reconciled)
            changed = True
        if not reconciled:
            rebuilt.remove(binding)
            changed = True

    for role in sorted(desired_roles - set(first_unconditional)):
        rebuilt.append(binding_factory(role, [member]))
        changed = True

    if len(rebuilt) != len(bindings) or any(
        left is not right for left, right in zip(rebuilt, bindings, strict=True)
    ):
        changed = True
    if changed:
        _replace_bindings(policy, rebuilt)
    return changed


def policy_member_roles(
    policy: _Policy, member: str, *, include_conditions: bool = True
) -> set[str]:
    """Return direct roles containing one member without changing the policy."""
    return {
        role
        for binding in policy.bindings
        if isinstance(role := _binding_value(binding, "role"), str)
        if member in (_binding_value(binding, "members", ()) or ())
        and (include_conditions or not _is_conditional(binding))
    }


def require_permanent_owner_binding(
    project_id: str, owner_email: str, *, client: ProjectsClient | None = None
) -> bool:
    """Require the delegated site's permanent Owner to own the project directly."""
    install_if_missing(
        "google.cloud.resourcemanager_v3",
        "Google Resource Manager API",
        package_name="google-cloud-resource-manager",
    )
    if client is None:
        from google.cloud import resourcemanager_v3

        client = resourcemanager_v3.ProjectsClient()

    policy = client.get_iam_policy(
        request={
            "resource": f"projects/{project_id}",
            "options": {"requested_policy_version": 3},
        },
        timeout=30,
    )
    member = principal_member(str(owner_email or "").strip().casefold())
    roles = policy_member_roles(policy, member, include_conditions=False)
    if PROJECT_OWNER_ROLE in roles:
        return True

    raise RuntimeError(
        f"Permanent site Owner {owner_email} must already have a direct "
        f"{PROJECT_OWNER_ROLE} binding on project {project_id}. Enter the "
        "Owner's exact Google account email, not a forwarding alias, and have "
        "a project administrator grant that account Owner before retrying setup."
    )


def remove_member_bindings(policy: _Policy, member: str) -> bool:
    """Remove one direct member from every binding, including conditional ones."""
    changed = False
    rebuilt = []
    for binding in list(policy.bindings):
        members = list(_binding_value(binding, "members", ()) or ())
        reconciled = [existing for existing in members if existing != member]
        if reconciled != members:
            changed = True
            _set_binding_value(binding, "members", reconciled)
        if reconciled:
            rebuilt.append(binding)
        elif members:
            changed = True
    if changed:
        _replace_bindings(policy, rebuilt)
    return changed


def inspect_operator_permissions(
    project_id: str,
    *,
    billing_account: str | None = None,
    require_billing_link: bool = False,
    client: ProjectsClient | None = None,
    billing_client: _PermissionClient | None = None,
) -> dict[str, list[str]]:
    """Return missing project permissions for the active installer/deployer."""
    install_if_missing(
        "google.cloud.resourcemanager_v3",
        "Google Resource Manager API",
        package_name="google-cloud-resource-manager",
    )
    if client is None:
        from google.cloud import resourcemanager_v3

        client = resourcemanager_v3.ProjectsClient()

    required = sorted(
        set(constants.INSTALLER_PROJECT_PERMISSIONS)
        | set(constants.DEPLOYER_PROJECT_PERMISSIONS)
    )
    response = client.test_iam_permissions(
        request={
            "resource": f"projects/{project_id}",
            "permissions": required,
        },
        timeout=30,
    )
    granted = set(response.permissions)
    missing_billing = []
    if require_billing_link:
        if not billing_account:
            missing_billing = list(constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS)
        elif billing_client is not None:
            billing_response = billing_client.test_iam_permissions(
                request={
                    "resource": f"billingAccounts/{billing_account}",
                    "permissions": constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS,
                },
                timeout=30,
            )
            missing_billing = sorted(
                set(constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS)
                - set(billing_response.permissions)
            )
        else:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            response = AuthorizedSession(credentials).post(
                "https://cloudbilling.googleapis.com/v1/"
                f"billingAccounts/{billing_account}:testIamPermissions",
                json={
                    "permissions": constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS
                },
                timeout=10,
            )
            response.raise_for_status()
            missing_billing = sorted(
                set(constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS)
                - set(response.json().get("permissions") or ())
            )
    return {
        "installer": sorted(set(constants.INSTALLER_PROJECT_PERMISSIONS) - granted),
        "billing": missing_billing,
        "deployer": sorted(set(constants.DEPLOYER_PROJECT_PERMISSIONS) - granted),
    }


def require_operator_permissions(
    project_id: str,
    *,
    billing_account: str | None = None,
    require_billing_link: bool = False,
    client: ProjectsClient | None = None,
    billing_client: _PermissionClient | None = None,
) -> dict[str, list[str]]:
    """Fail before provisioning when the active human lacks required authority."""
    missing = inspect_operator_permissions(
        project_id,
        billing_account=billing_account,
        require_billing_link=require_billing_link,
        client=client,
        billing_client=billing_client,
    )
    if not any(missing.values()):
        return missing

    lines = [
        "The active Google account is missing permissions required before "
        f"Lagniappe may change project '{project_id}'."
    ]
    for boundary in ("installer", "billing", "deployer"):
        if missing[boundary]:
            lines.append(f"{boundary.title()}: {', '.join(missing[boundary])}")
    lines.append(
        "Setup will not grant these permissions automatically. Ask a project "
        "administrator to grant them to the active installer/deployer account, "
        "then rerun installer."
    )
    raise RuntimeError("\n".join(lines))


def require_installer_bucket_permissions(bucket: Bucket) -> list[str]:
    """Require human installer permissions used to reconcile one bucket."""
    required = sorted(set(constants.INSTALLER_BUCKET_PERMISSIONS))
    granted = set(bucket.test_iam_permissions(required))
    missing = sorted(set(constants.INSTALLER_BUCKET_PERMISSIONS) - granted)
    if not missing:
        return missing

    lines = [
        "The active Google account is missing permissions required on Cloud "
        f"Storage bucket '{bucket.name}'.",
        f"Installer: {', '.join(missing)}",
    ]
    lines.append(
        "Setup will not grant these permissions automatically. Ask a project "
        "administrator to grant them to the active installer account "
        "on this bucket or its project, then rerun installer."
    )
    raise RuntimeError("\n".join(lines))


def reconcile_runtime_project_policy(project_id: str, runtime_email: str) -> bool:
    """Apply current runtime project roles without changing unmanaged grants."""
    install_if_missing(
        "google.cloud.resourcemanager_v3",
        "Google Resource Manager API",
        package_name="google-cloud-resource-manager",
    )
    from google.cloud import resourcemanager_v3
    from google.iam.v1 import policy_pb2

    client = resourcemanager_v3.ProjectsClient()
    resource = f"projects/{project_id}"
    policy = client.get_iam_policy(
        request={
            "resource": resource,
            "options": {"requested_policy_version": 3},
        }
    )
    member = f"serviceAccount:{runtime_email}"
    changed = reconcile_member_roles(
        policy,
        member,
        desired_roles=constants.RUNTIME_PROJECT_ROLES,
        managed_roles=constants.RUNTIME_PROJECT_ROLES,
        binding_factory=lambda role, members: policy_pb2.Binding(
            role=role, members=members
        ),
    )
    if changed:
        client.set_iam_policy(request={"resource": resource, "policy": policy})
    return changed


def reconcile_runtime_service_account_policy(
    project_id: str,
    runtime_email: str,
    deployer_email: str,
) -> bool:
    """Grant exact-resource actAs and remote signing to runtime and deployer."""
    install_if_missing(
        "google.cloud.iam_admin_v1",
        "Google IAM Admin API",
        package_name="google-cloud-iam",
    )
    from google.cloud import iam_admin_v1
    from google.iam.v1 import policy_pb2

    client = iam_admin_v1.IAMClient()
    resource = f"projects/{project_id}/serviceAccounts/{runtime_email}"
    policy = client.get_iam_policy(
        request={
            "resource": resource,
            "options": {"requested_policy_version": 3},
        }
    )
    changed = False
    for member in (
        principal_member(deployer_email),
        f"serviceAccount:{runtime_email}",
    ):
        changed = (
            reconcile_member_roles(
                policy,
                member,
                desired_roles=constants.RUNTIME_SERVICE_ACCOUNT_ROLES,
                managed_roles=constants.RUNTIME_SERVICE_ACCOUNT_ROLES,
                binding_factory=lambda role, members: policy_pb2.Binding(
                    role=role, members=members
                ),
            )
            or changed
        )
    if changed:
        client.set_iam_policy(request={"resource": resource, "policy": policy})
    return changed


def reconcile_project_service_agent(project_id: str, member: str, role: str) -> bool:
    """Ensure one Google-managed service agent project role idempotently."""
    install_if_missing(
        "google.cloud.resourcemanager_v3",
        "Google Resource Manager API",
        package_name="google-cloud-resource-manager",
    )
    from google.cloud import resourcemanager_v3
    from google.iam.v1 import policy_pb2

    client = resourcemanager_v3.ProjectsClient()
    resource = f"projects/{project_id}"
    policy = client.get_iam_policy(
        request={
            "resource": resource,
            "options": {"requested_policy_version": 3},
        }
    )
    changed = reconcile_member_roles(
        policy,
        member,
        desired_roles={role},
        managed_roles={role},
        binding_factory=lambda binding_role, members: policy_pb2.Binding(
            role=binding_role, members=members
        ),
    )
    if changed:
        client.set_iam_policy(request={"resource": resource, "policy": policy})
    return changed
