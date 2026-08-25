"""Unit tests for the independent per-user AI entitlement."""

from unittest.mock import patch

from google.cloud.datastore import Entity, Key
import pytest

from lagniappe.core.definitions import AI, Action, Resource
from lagniappe.core.entities.user import User
from testing.utility.test_entities import TestEntities


# @matrix ai-access : fail-closed hierarchy validation
# @source lagniappe/core/definitions/ai_access.py::AI.implies
@pytest.mark.unit
def test_ai_access_tiers_are_hierarchical_and_fail_closed():
    assert AI.CREATE.implies(AI.CREATE)
    assert AI.CREATE.implies(AI.ASK)
    assert AI.ASK.implies(AI.ASK)
    assert not AI.ASK.implies(AI.CREATE)
    assert not AI.NONE.implies(AI.NONE)
    assert not AI.CREATE.implies("ASK")

    assert AI.name_for(AI.CREATE) == "CREATE"
    assert AI.name_for("ASK") == "ASK"
    with pytest.raises(ValueError, match="CREATE, ASK, or NONE"):
        AI.name_for("create")
    with pytest.raises(ValueError, match="CREATE, ASK, or NONE"):
        AI.name_for("DEFAULT")


# @matrix ai-access : cache-invalidation legacy-default persistence public validation
@pytest.mark.unit
def test_user_ai_access_legacy_defaults_validation_and_invalidation():
    regular = TestEntities.get(
        "USER",
        {"name": "Legacy Regular", "hash": "legacy-regular"},
    )
    regular.db.pop("ai_access", None)
    regular.invalidate_cache = False

    assert regular.ai_access == "CREATE"
    regular.ai_access = "ASK"
    assert regular.db["ai_access"] == "ASK"
    assert regular.invalidate_cache is True

    regular.invalidate_cache = False
    with pytest.raises(ValueError, match="CREATE, ASK, or NONE"):
        regular.ai_access = "UNKNOWN"
    assert regular.ai_access == "ASK"
    assert regular.invalidate_cache is False

    public = TestEntities.get(
        "USER",
        {"name": "Legacy Public", "hash": "legacy-public", "public": True},
    )
    public.db.pop("ai_access", None)
    assert public.ai_access == "NONE"

    public.ai_access = AI.CREATE
    assert public.ai_access == "CREATE"
    assert public.access(AI.CREATE)

    public.db["ai_access"] = "CORRUPT"
    public.properties.ai_access.unset()
    assert public.ai_access == "NONE"
    public.db["ai_access"] = "DEFAULT"
    public.properties.ai_access.unset()
    assert public.ai_access == "NONE"
    assert "ai_access" in public.exclude_from_index


# @matrix ai-access : authentication hierarchy owner-no-bypass permissions-independent
@pytest.mark.unit
def test_user_access_is_independent_hierarchical_and_fail_closed():
    powerful = TestEntities.get(
        "USER",
        {
            "name": "Powerful User",
            "hash": "powerful-user",
            "permissions": {"models": "ALL", "forms": "ALL", "users": "ALL"},
        },
    )
    powerful.ai_access = "NONE"
    assert powerful.has_permission(Resource.MODELS, Action.CREATE)
    assert not powerful.access(AI.ASK)
    assert not powerful.access(AI.CREATE)

    limited = TestEntities.get(
        "USER",
        {"name": "AI User", "hash": "ai-user", "permissions": {}},
    )
    limited.ai_access = "CREATE"
    assert not limited.has_permission(Resource.MODELS, Action.VIEW)
    assert limited.access(AI.ASK)
    assert limited.access(AI.CREATE)

    owner = TestEntities.get(
        "USER",
        {"name": "Owner Without AI", "hash": "owner-without-ai", "owner": True},
    )
    owner.ai_access = "NONE"
    assert not owner.access(AI.ASK)
    assert not owner.access(AI.NONE)
    assert not owner.access("ASK")

    anonymous = User(testing=True)
    assert not anonymous.access(AI.ASK)


# @matrix ai-access cache : authorization-fingerprint entitlement permissions
@pytest.mark.unit
def test_authorization_fingerprint_tracks_ai_access():
    user = TestEntities.get(
        "USER",
        {
            "name": "Authorization Fingerprint",
            "hash": "authorization-fingerprint",
            "permissions": {"models": "VIEW"},
        },
    )
    user.ai_access = "ASK"
    before = user.authorization_fingerprint
    permissions_before = user.permissions_fingerprint

    user.ai_access = "CREATE"

    assert user.authorization_fingerprint != before
    assert user.permissions_fingerprint == permissions_before


# @pair user:new-user-default
@pytest.mark.unit
def test_user_create_defaults_non_owner_to_none():
    page = TestEntities.get(
        "PAGE",
        {"name": "New AI User Page", "hash": "new-ai-user-page"},
    )
    users_model = TestEntities.get(
        "USERS",
        {"name": "Users", "hash": "users", "type": "users"},
    )
    new_key = Key("users", "new-ai-user", project="test")
    new_entity = Entity(new_key)

    with (
        patch(
            "lagniappe.core.entities.user.CONFIG.ADMIN_EMAIL",
            "owner@example.test",
        ),
        patch("lagniappe.core.entities.user.database.get.user", return_value=None),
        patch(
            "lagniappe.core.entities.entity.database.create_key",
            return_value=new_key,
        ),
        patch(
            "lagniappe.core.entities.entity.database.get.entity",
            return_value=None,
        ),
        patch(
            "lagniappe.core.entities.entity.database.create_entity",
            return_value=new_entity,
        ),
        patch(
            "lagniappe.core.properties.user_related.Entities.USERS.get",
            return_value=users_model,
        ),
    ):
        user = User.create(
            {
                "name": "New AI User",
                "email": "user@example.test",
                "page": page,
                "admin": True,
            }
        )

    assert user.is_owner is not True
    assert user.is_admin is True
    assert user.ai_access == "NONE"
    assert user.db["ai_access"] == "NONE"
