"""One-time account bootstrap and execution policy for experiments installs."""

import hashlib

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.mutations import execute_mutation, plan_mutation
from lagniappe.core.tools.database.core import DATA, KINDS


# @testable true
# @tests tests_unit/test_034_experiments.py::test_execution_requires_designated_admin_and_current_policy
# @matrix experiments : execution-policy
def can_execute(user, *, remote_mcp=False):
    """Additional capability never substitutes for ordinary record permissions."""
    return bool(
        remote_mcp
        and getattr(CONFIG, "EXPERIMENTS_ENABLED", False)
        and getattr(CONFIG, "EXPERIMENTS_EXECUTION_ENABLED", False)
        and getattr(CONFIG, "EXPERIMENTS_PROJECT", None) == CONFIG.GOOGLE_CLOUD_PROJECT
        and CONFIG.AI_ENABLED
        and CONFIG.EXTERNAL_AI_ENABLED
        and getattr(CONFIG, "AGENT_ACCESS_ENABLED", False)
        and user
        and user.is_authenticated
        and user.is_admin
        and not user.is_public
        and str(user.email or "").strip().casefold()
        == str(CONFIG.AGENT_ACCESS_EMAIL).strip().casefold()
    )


# @testable true
# @tests tests_unit/test_034_experiments.py::test_bootstrap_is_guarded_idempotent_and_preserves_roles
# @matrix experiments : bootstrap
def bootstrap():
    """Create both normal accounts once, preserving subsequent Owner decisions."""
    if not getattr(CONFIG, "EXPERIMENTS_ENABLED", False) or not CONFIG.production:
        return
    marker_key = DATA.datastore.key(KINDS.site.value, "experiments-bootstrap")
    marker = DATA.datastore.get(marker_key)
    if marker:
        if marker.get("version") != 1 or marker.get("identities") != [
            CONFIG.ADMIN_EMAIL.casefold(),
            CONFIG.AGENT_ACCESS_EMAIL.casefold(),
        ]:
            raise RuntimeError(
                "Experiments bootstrap identities differ from the saved installation."
            )
        return
    users = {}
    for role, email, name in (
        ("owner", CONFIG.ADMIN_EMAIL, "Owner"),
        ("agent", CONFIG.AGENT_ACCESS_EMAIL, CONFIG.AGENT_ACCESS_NAME),
    ):
        email = email.strip().casefold()
        key = DATA.datastore.key(
            KINDS.users.value,
            "experiments-" + hashlib.sha256(email.encode()).hexdigest(),
        )
        row = DATA.datastore.get(key)
        if row is None:
            user = Entities.USER.create(
                {"email": email, "name": name, "admin": role == "agent"}, key=key
            )
            # A login that already created this identity is reused, not promoted.
            if user.key == key:
                try:
                    outcome = execute_mutation(
                        plan_mutation(MutationOperation.SAVE, user, registry=Entities),
                        guards=[(key, None)],
                    )
                    if not outcome.post_commit_complete:
                        raise RuntimeError(
                            "Experiments account saved but cache publication failed; retry startup."
                        )
                except exceptions.MutationConflict:
                    row = DATA.datastore.get(key)
                    if row is None:
                        raise
            key = user.key
        users[role] = key
    from google.cloud.datastore import Entity

    marker = Entity(marker_key, exclude_from_indexes=("identities",))
    marker.update(
        version=1,
        identities=[
            CONFIG.ADMIN_EMAIL.casefold(),
            CONFIG.AGENT_ACCESS_EMAIL.casefold(),
        ],
        **users,
    )
    DATA.datastore.put(marker)
