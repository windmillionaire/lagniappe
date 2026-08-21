"""Least-privilege IAM planning, preflight, and policy reconciliation."""

from config import constants
from installer.package_install import install_if_missing


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_iam_principal_member_classifies_google_identities
# @features setup iam
# @dimensions identity
def principal_member(email):
    """Return the IAM member string for a Google user or service account."""
    principal_type = (
        "serviceAccount"
        if str(email).casefold().endswith(".gserviceaccount.com")
        else "user"
    )
    return f"{principal_type}:{email}"


# @testable false
# @covered-by installer/iam.py::reconcile_member_roles
# @reason provider binding-shape adapter owned by policy reconciliation
def _binding_value(binding, key, default=None):
    if isinstance(binding, dict):
        return binding.get(key, default)
    return getattr(binding, key, default)


# @testable false
# @covered-by installer/iam.py::reconcile_member_roles
# @reason provider binding-shape adapter owned by policy reconciliation
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


# @testable false
# @covered-by installer/iam.py::reconcile_member_roles
# @reason condition-shape adapter owned by policy reconciliation
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


# @testable false
# @covered-by installer/iam.py::reconcile_member_roles
# @reason provider policy-shape adapter owned by policy reconciliation
def _replace_bindings(policy, bindings):
    try:
        policy.bindings = bindings
    except AttributeError:
        del policy.bindings[:]
        policy.bindings.extend(bindings)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_iam_reconciliation_is_idempotent_and_preserves_conditions_and_etag
# @features setup iam
# @dimensions idempotence conditions etag unrelated-members
def reconcile_member_roles(
    policy,
    member,
    *,
    desired_roles,
    managed_roles,
    binding_factory,
):
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
        left is not right for left, right in zip(rebuilt, bindings)
    ):
        changed = True
    if changed:
        _replace_bindings(policy, rebuilt)
    return changed


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_handoff_policy_helpers_remove_only_the_target_member
# @pairs iam:policy-inspection iam:conditions iam:unrelated-members
def policy_member_roles(policy, member, *, include_conditions=True):
    """Return direct roles containing one member without changing the policy."""
    return {
        _binding_value(binding, "role")
        for binding in policy.bindings
        if member in (_binding_value(binding, "members", ()) or ())
        and (include_conditions or not _is_conditional(binding))
    }


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_handoff_policy_helpers_remove_only_the_target_member
# @pairs iam:member-removal iam:conditions iam:unrelated-members iam:empty-bindings
def remove_member_bindings(policy, member):
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


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_operator_permission_preflight_reports_missing_boundaries
# @features setup iam
# @dimensions preflight installer deployer
def inspect_operator_permissions(
    project_id,
    *,
    billing_account=None,
    require_billing_link=False,
    client=None,
    billing_client=None,
):
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


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_operator_permission_preflight_reports_missing_boundaries
# @features setup iam
# @dimensions preflight failure-reporting
def require_operator_permissions(
    project_id,
    *,
    billing_account=None,
    require_billing_link=False,
    client=None,
    billing_client=None,
):
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


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_installer_bucket_permission_preflight_uses_bucket_resource
# @features setup storage iam
# @dimensions preflight installer bucket-scope failure-reporting
def require_installer_bucket_permissions(bucket):
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


# @testable false
# @covered-by installer/gcloud.py::configure_service_account
# @reason provider client composition over the tested policy reconciler
def reconcile_runtime_project_policy(project_id, runtime_email, removed_roles=None):
    """Apply runtime project roles and remove prior broad Lagniappe grants."""
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
    removed_roles = set(
        constants.REMOVED_RUNTIME_PROJECT_ROLES
        if removed_roles is None
        else removed_roles
    )
    blocked_conditions = sorted(
        {
            _binding_value(binding, "role")
            for binding in policy.bindings
            if _binding_value(binding, "role")
            in removed_roles
            and _is_conditional(binding)
            and member in (_binding_value(binding, "members", ()) or ())
        }
    )
    if blocked_conditions:
        raise RuntimeError(
            "Runtime service account has conditional broad-role bindings that "
            "setup will preserve but cannot safely reconcile: "
            + ", ".join(blocked_conditions)
        )

    changed = reconcile_member_roles(
        policy,
        member,
        desired_roles=constants.RUNTIME_PROJECT_ROLES,
        managed_roles=(
            set(constants.RUNTIME_PROJECT_ROLES)
            | removed_roles
        ),
        binding_factory=lambda role, members: policy_pb2.Binding(
            role=role, members=members
        ),
    )
    if changed:
        client.set_iam_policy(request={"resource": resource, "policy": policy})
    return changed


# @testable false
# @covered-by installer/gcloud.py::configure_service_account
# @reason provider client composition over the tested policy reconciler
def reconcile_runtime_service_account_policy(
    project_id,
    runtime_email,
    deployer_email,
):
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


# @testable false
# @covered-by installer/gcloud.py::create_deferred_job_reconciler
# @reason provider client composition over the tested policy reconciler
def reconcile_project_service_agent(project_id, member, role):
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
