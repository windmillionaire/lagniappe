"""Authorization boundary for entity references submitted by a browser."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ...definitions import Action, Fetch
from ...entities import Entities
from ...exceptions import ValidationError
from .. import database


UNAVAILABLE_REFERENCE_ERROR = "One or more selected items are unavailable."


# @testable false
# @covered-by lagniappe/core/tools/auth/references.py::SubmittedReferenceResolver
# @reason identifier normalization is exercised through the resolver boundary
def _entity_key(value):
    if not value:
        return None
    if getattr(value, "key", None):
        return value.key
    return database.get.datastore_key(value)


# @testable false
# @covered-by lagniappe/core/tools/auth/references.py::SubmittedReferenceResolver
# @reason existing-relation normalization is exercised through the resolver boundary
def _existing_keys(existing) -> set:
    if not existing:
        return set()
    values = existing if isinstance(existing, (list, tuple, set)) else [existing]
    return {key for key in (_entity_key(value) for value in values) if key}


# @testable true
# @tests tests_unit/test_031_submitted_references.py::test_submitted_reference_resolver_rejects_unavailable_targets
# @tests tests_unit/test_031_submitted_references.py::test_submitted_reference_resolver_preserves_authorized_order_and_existing_targets
# @matrix submitted-references : action batch dedup existing generic-error kind order predicate
class SubmittedReferenceResolver:
    """Batch-load and authorize secondary entity keys from a request body."""

    def __init__(self, actor, *identifiers):
        if actor is None:
            raise TypeError("SubmittedReferenceResolver requires an actor")
        self.actor = actor
        self._entities = {
            entity.key: entity
            for entity in Entities.fetch(*identifiers, request=Fetch.direct())
            if entity and getattr(entity, "key", None)
        }

    @staticmethod
    def _reject():
        raise ValidationError(UNAVAILABLE_REFERENCE_ERROR)

    def one(
        self,
        identifier,
        *,
        expected,
        action: Action | None = Action.VIEW,
        existing=None,
        predicate: Callable | None = None,
        authorize: Callable | None = None,
        required: bool = False,
    ):
        """Return one valid target, or raise the generic boundary error."""
        if not identifier:
            if required:
                self._reject()
            return None

        key = _entity_key(identifier)
        entity = self._entities.get(key)
        expected_types = expected if isinstance(expected, tuple) else (expected,)
        if not key or not entity or not isinstance(entity, expected_types):
            self._reject()

        try:
            if predicate is not None and predicate(entity) is False:
                self._reject()

            if key not in _existing_keys(existing):
                if authorize is not None:
                    allowed = authorize(entity)
                elif action is not None:
                    allowed = entity.allowed(action, user=self.actor)
                else:
                    allowed = False
                if not allowed:
                    self._reject()
        except ValidationError:
            self._reject()
        except (AttributeError, TypeError, ValueError):
            self._reject()

        return entity

    def many(
        self,
        identifiers: Iterable,
        *,
        expected,
        action: Action | None = Action.VIEW,
        existing=None,
        predicate: Callable | None = None,
        authorize: Callable | None = None,
    ) -> list:
        """Return unique valid targets while preserving submitted order."""
        resolved = []
        seen = set()
        for identifier in identifiers:
            entity = self.one(
                identifier,
                expected=expected,
                action=action,
                existing=existing,
                predicate=predicate,
                authorize=authorize,
                required=True,
            )
            if entity.key in seen:
                continue
            seen.add(entity.key)
            resolved.append(entity)
        return resolved


__all__ = [
    "SubmittedReferenceResolver",
    "UNAVAILABLE_REFERENCE_ERROR",
]
