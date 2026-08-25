"""Authorization contracts for browser-submitted secondary entity keys."""

import json
from unittest.mock import patch

import pytest

from lagniappe import CONFIG
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.auth.references import (
    SubmittedReferenceResolver,
    UNAVAILABLE_REFERENCE_ERROR,
)
from lagniappe.core.tools.auth.task_attachments import (
    sign_task_attachment_claim,
    valid_task_attachment_claim,
)

from testing.utility.mock_submission import WebFormSubmission
from testing.utility.test_entities import TestEntities, TestUser as UtilityTestUser


pytestmark = pytest.mark.unit


def _allowed(entity, allowed):
    entity.allowed = lambda _action, user=None: allowed
    return entity


# @matrix submitted-references : action batch generic-error kind predicate
def test_submitted_reference_resolver_rejects_unavailable_targets():
    actor = UtilityTestUser()
    denied = _allowed(
        TestEntities.get("PAGE", {"hash": "denied-page", "name": "Denied"}),
        False,
    )
    wrong_kind = _allowed(
        TestEntities.get("FILE", {"hash": "wrong-file", "name": "Wrong"}),
        True,
    )
    missing = TestEntities.get("PAGE", {"hash": "missing-page", "name": "Missing"})
    malformed = "not-a-datastore-key"

    with patch(
        "lagniappe.core.tools.auth.references.Entities.fetch",
        return_value=[denied, wrong_kind],
    ):
        resolver = SubmittedReferenceResolver(
            actor,
            denied,
            wrong_kind,
            missing,
            malformed,
        )

    for target in (denied, wrong_kind, missing, malformed):
        with pytest.raises(ValidationError, match=UNAVAILABLE_REFERENCE_ERROR):
            resolver.one(
                target,
                expected=Entities.PAGE,
                action=Action.VIEW,
                required=True,
            )


# @matrix submitted-references : dedup existing order predicate
def test_submitted_reference_resolver_preserves_authorized_order_and_existing_targets():
    actor = UtilityTestUser()
    first = _allowed(
        TestEntities.get("PAGE", {"hash": "first-page", "name": "First"}),
        True,
    )
    existing = _allowed(
        TestEntities.get("PAGE", {"hash": "existing-page", "name": "Existing"}),
        False,
    )

    with patch(
        "lagniappe.core.tools.auth.references.Entities.fetch",
        return_value=[first, existing],
    ):
        resolver = SubmittedReferenceResolver(actor, first, existing)

    assert resolver.many(
        [first, existing, first],
        expected=Entities.PAGE,
        action=Action.VIEW,
        existing=[existing],
        predicate=lambda page: page.name != "Blocked by predicate",
    ) == [first, existing]


# @matrix task-attachments : actor expiry file scope signed-claim tamper validation
def test_task_attachment_claim_is_actor_file_scope_bound_and_expiring(monkeypatch):
    monkeypatch.setattr(CONFIG, "SECRET_KEY", "attachment-secret-" * 4)
    actor = TestEntities.get(
        "USER",
        {
            "hash": "claim-actor",
            "name": "Claim Actor",
            "page": {"hash": "claim-actor-page", "name": "Claim Actor"},
        },
    )
    other_actor = TestEntities.get(
        "USER",
        {
            "hash": "other-actor",
            "name": "Other Actor",
            "page": {"hash": "other-actor-page", "name": "Other Actor"},
        },
    )
    file = TestEntities.get("FILE", {"hash": "claim-file", "name": "Claim File"})
    other_file = TestEntities.get(
        "FILE", {"hash": "other-file", "name": "Other File"}
    )
    scope = TestEntities.get("PAGE", {"hash": "claim-scope", "name": "Scope"})
    other_scope = TestEntities.get(
        "PAGE", {"hash": "other-scope", "name": "Other Scope"}
    )

    claim = sign_task_attachment_claim(actor=actor, file=file, scope=scope)

    assert valid_task_attachment_claim(
        claim, actor=actor, file=file, scope=scope
    )
    assert not valid_task_attachment_claim(
        claim + "tampered", actor=actor, file=file, scope=scope
    )
    assert not valid_task_attachment_claim(
        claim, actor=other_actor, file=file, scope=scope
    )
    assert not valid_task_attachment_claim(
        claim, actor=actor, file=other_file, scope=scope
    )
    assert not valid_task_attachment_claim(
        claim, actor=actor, file=file, scope=other_scope
    )
    assert not valid_task_attachment_claim(
        claim, actor=actor, file=file, scope=scope, max_age=-1
    )


# @matrix submitted-references : browser internal-link preflight preservation
def test_browser_submission_references_require_view_and_preserve_hidden_existing_values(
    get_schema,
):
    actor = UtilityTestUser()
    page = TestEntities.get(
        "PAGE",
        {
            "hash": "link-owner",
            "name": "Link Owner",
            "form": {
                "hash": "link-form",
                "name": "Link Form",
                "form_type": "page",
            },
        },
    )
    page.form.schema = get_schema("submission_integration_links")
    existing = _allowed(
        TestEntities.get("PAGE", {"hash": "existing-link", "name": "Existing"}),
        False,
    )
    denied = _allowed(
        TestEntities.get("PAGE", {"hash": "denied-link", "name": "Denied"}),
        False,
    )
    page.properties.submission.value = {"top_link": existing.details}

    def datastore_key(identifier):
        return {
            existing.urlsafe_key: existing.key,
            denied.urlsafe_key: denied.key,
        }.get(identifier)

    with (
        patch(
            "lagniappe.core.tools.auth.references.Entities.fetch",
            return_value=[existing, denied],
        ),
        patch(
            "lagniappe.core.tools.auth.references.database.get.datastore_key",
            side_effect=datastore_key,
        ),
    ):
        with pytest.raises(ValidationError, match=UNAVAILABLE_REFERENCE_ERROR):
            page.form_submission(
                WebFormSubmission({"top_link": denied.urlsafe_key}),
                actor=actor,
            )

        assert page.properties.submission.fields["top_link"].db_value == existing.details

        page.form_submission(WebFormSubmission({}), actor=actor)
        assert page.properties.submission.fields["top_link"].db_value == existing.details


# @matrix submitted-references : browser internal-link no-partial-mutation preflight table
def test_browser_submission_references_validate_table_links_before_mutation(get_schema):
    actor = UtilityTestUser()
    page = TestEntities.get(
        "PAGE",
        {
            "hash": "table-link-owner",
            "name": "Table Link Owner",
            "form": {
                "hash": "table-link-form",
                "name": "Table Link Form",
                "form_type": "page",
            },
        },
    )
    page.form.schema = get_schema("submission_integration_links")
    denied = _allowed(
        TestEntities.get(
            "PAGE", {"hash": "denied-table-link", "name": "Denied Table"}
        ),
        False,
    )
    rows = json.dumps({"rows": [{"row_rel": denied.urlsafe_key}]})

    with (
        patch(
            "lagniappe.core.tools.auth.references.Entities.fetch",
            return_value=[denied],
        ),
        patch(
            "lagniappe.core.tools.auth.references.database.get.datastore_key",
            return_value=denied.key,
        ),
    ):
        with pytest.raises(ValidationError, match=UNAVAILABLE_REFERENCE_ERROR):
            page.form_submission(
                WebFormSubmission({"with_rows": rows}),
                actor=actor,
            )

    assert "with_rows" not in page.properties.submission.db_value


# @pair task:assignee-preservation
def test_task_update_preserves_unchanged_assignee_eligibility():
    task = TestEntities.get(
        "TASK",
        {
            "hash": "assigned-task",
            "name": "Assigned Task",
            "page": {"hash": "assigned-task-page", "name": "Task Page"},
            "assigned_to": {
                "hash": "assigned-user",
                "name": "Assigned User",
                "page": {"hash": "assigned-user-page", "name": "Assigned User"},
            },
        },
    )
    assigned_to = task.assigned_to

    with patch.object(
        task,
        "validate_assignment",
        side_effect=AssertionError("unchanged assignment must not be revalidated"),
    ):
        task.update(
            {
                "page": task.page,
                "form": task.form,
                "name": task.name,
                "description": task.description,
                "due_date": task.due_date,
                "assigned_to": assigned_to,
            }
        )

    assert task.assigned_to.key == assigned_to.key
