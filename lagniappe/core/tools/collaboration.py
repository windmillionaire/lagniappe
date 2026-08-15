"""Shared eligibility checks for managed-user collaboration features."""

from ..definitions import Action, Fetch, Restriction
from ..entities import Entities
from . import cache


# @testable true
# @tests tests_unit/test_027_messaging.py::test_collaboration_permissions_use_current_recipient_and_document_access
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:managed-user messaging:public-exclusion
def managed_user(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and not getattr(user, "is_public", False)
    )


# @testable true
# @tests tests_unit/test_027_messaging.py::test_collaboration_permissions_use_current_recipient_and_document_access
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_inbound_message_allows_reply_without_compose_permission
# @pairs messaging:compose-eligibility messaging:owner-opt-in
def can_initiate_messages(user):
    """Return whether a managed user has any possible new-message recipient."""
    return bool(
        managed_user(user)
        and user.properties.restrictions.can_initiate_messages
    )


# @testable true
# @tests tests_unit/test_027_messaging.py::test_collaboration_permissions_use_current_recipient_and_document_access
# @pair messaging:recipient-resolution
def resolve_user(identifier):
    """Resolve either a canonical User key or its personal Page selector key."""
    entity = Entities.fetch_one(identifier, request=Fetch.direct())
    if isinstance(entity, Entities.USER):
        return entity
    if isinstance(entity, Entities.PAGE) and entity.user:
        return entity.user
    return None


# @testable false
# @covered-by lagniappe/core/tools/collaboration.py::recipient_allowed
# @reason restriction-set math is exercised through the final recipient predicate
def _ordinary_restriction_allows(recipient, restrictions):
    if Restriction.is_unrestricted(restrictions):
        return True
    if Restriction.is_denied(restrictions):
        return False
    required = set(recipient.requires or ()) - {"users"}
    return bool(required & set(restrictions or ()))


# @testable true
# @tests tests_unit/test_027_messaging.py::test_collaboration_permissions_use_current_recipient_and_document_access
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:permission messaging:self-exclusion messaging:owner-opt-in
# @pair task-assignment:permission
def recipient_allowed(actor, recipient, *, channel):
    """Validate a recipient at the final mutation boundary."""
    if not managed_user(actor) or not managed_user(recipient):
        return False
    actor_key = getattr(actor, "key", None)
    recipient_key = getattr(recipient, "key", None)
    if actor_key is None or recipient_key is None:
        return False
    if actor_key == recipient_key and channel in {"message", "mention"}:
        return False

    if channel in {"message", "mention"}:
        owner_toggle = "allow_messages_and_mentions"
        restrictions = actor.properties.restrictions.user_message_restrictions
    elif channel == "assign":
        if actor_key == recipient_key:
            return True
        owner_toggle = "allow_task_assignments"
        restrictions = actor.properties.restrictions.user_assign_restrictions
    else:
        raise ValueError("Unknown collaboration channel.")

    if recipient.is_owner:
        # Mutation boundaries already hold the canonical recipient. The Redis
        # projection may shape suggestions, but it must never grant access.
        return bool(getattr(recipient, owner_toggle, False))
    return _ordinary_restriction_allows(recipient, restrictions)


# @testable true
# @tests tests_unit/test_027_messaging.py::test_collaboration_permissions_use_current_recipient_and_document_access
# @pairs mentions:permission mentions:document-view
def mention_recipient_allowed(actor, recipient, document):
    return bool(
        recipient_allowed(actor, recipient, channel="mention")
        and document
        and document.allowed(Action.VIEW, user=recipient)
    )


# @testable true
# @tests tests_unit/test_027_messaging.py::test_collaboration_search_filters_self_owner_and_document_access
# @pairs messaging:self-exclusion messaging:recipient-key messaging:owner-search
# @pairs mentions:document-view owner-projection:normalization owner-projection:deduplication
def collaboration_user_results(
    results,
    query,
    permission,
    actor,
    *,
    document_identifier=None,
):
    """Apply collaboration recipient invariants to user-search results."""
    if permission not in {"message", "mention", "assign"}:
        return results
    owner = cache.get_owner_projection()
    owner_page = owner.get("page_key") if owner else None
    current_page_entity = getattr(actor, "page", None)
    current_page = (
        current_page_entity.urlsafe_key if current_page_entity else None
    )
    filtered = [
        result
        for result in results
        if result.get("id") not in {owner_page, current_page}
        and result.get("details", {}).get("id") not in {owner_page, current_page}
    ]
    selectable = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(
            *[result.get("id") for result in filtered if result.get("id")],
            request=Fetch.direct(),
        )
        if isinstance(entity, Entities.PAGE) and entity.user
    }
    filtered = [result for result in filtered if result.get("id") in selectable]
    if permission == "mention":
        document = Entities.fetch_one(document_identifier, request=Fetch.root())
        filtered = [
            result
            for result in filtered
            if (page := selectable.get(result.get("id")))
            and document
            and document.allowed(Action.VIEW, user=page.user)
        ]
    for result in filtered:
        page = selectable.get(result.get("id"))
        if page and page.user:
            result.setdefault("details", {})["recipient_key"] = page.user.urlsafe_key
    toggle = (
        "allow_task_assignments"
        if permission == "assign"
        else "allow_messages_and_mentions"
    )
    normalized_query = cache.normalize_owner_name(query)
    if (
        owner
        and owner.get(toggle)
        and normalized_query
        and normalized_query in owner.get("normalized_name", "")
        and owner.get("key") != actor.urlsafe_key
    ):
        filtered.append(cache.owner_search_result(owner))
    return filtered
