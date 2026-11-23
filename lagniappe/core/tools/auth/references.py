"""Authorization boundary for entity references submitted by a browser."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Literal, Never, cast, overload

from ...definitions import Action, Fetch, FetchReason
from ...entities import Entities
from ...exceptions import ValidationError
from lagniappe.core.tools.database import get as database_get


if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ...entities import Identifier
    from ...entities.entity import Entity
    from ...entities.user import User


UNAVAILABLE_REFERENCE_ERROR = "One or more selected items are unavailable."


# @testable false
# @covered-by lagniappe/core/tools/auth/references.py::SubmittedReferenceResolver
# @reason identifier normalization is exercised through the resolver boundary
def _entity_key(value: object) -> Key | None:
    if not value:
        return None
    if key := getattr(value, "key", None):
        return key
    return database_get.datastore_key(value)


# @testable false
# @covered-by lagniappe/core/tools/auth/references.py::SubmittedReferenceResolver
# @reason existing-relation normalization is exercised through the resolver boundary
def _existing_keys(existing: object) -> set[Key]:
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

    def __init__(self, actor: User, *identifiers: Identifier) -> None:
        if actor is None:
            raise TypeError("SubmittedReferenceResolver requires an actor")
        self.actor = actor
        self._entities = {
            entity.key: entity
            for entity in Entities.fetch(*identifiers, request=Fetch.direct())
            if entity and getattr(entity, "key", None)
        }
        Entities.fetch(
            *(entity for entity in self._entities.values()
              if isinstance(entity, (Entities.TASK, Entities.FILE))),
            *(entity.task for entity in self._entities.values()
              if isinstance(entity, Entities.TASK_HISTORY)),
            request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
        )

    @staticmethod
    def _reject() -> Never:
        raise ValidationError(UNAVAILABLE_REFERENCE_ERROR)

    @overload
    def one[T: Entity](
        self, identifier: object, *, expected: type[T] | tuple[type[T], ...],
        action: Action | None = Action.VIEW, existing: object = None,
        predicate: Callable[[T], object] | None = None,
        authorize: Callable[[T], object] | None = None, required: Literal[True],
    ) -> T: ...

    @overload
    def one[T: Entity](
        self, identifier: object, *, expected: type[T] | tuple[type[T], ...],
        action: Action | None = Action.VIEW, existing: object = None,
        predicate: Callable[[T], object] | None = None,
        authorize: Callable[[T], object] | None = None, required: bool = False,
    ) -> T | None: ...

    def one[T: Entity](
        self,
        identifier: object,
        *,
        expected: type[T] | tuple[type[T], ...],
        action: Action | None = Action.VIEW,
        existing: object = None,
        predicate: Callable[[T], object] | None = None,
        authorize: Callable[[T], object] | None = None,
        required: bool = False,
    ) -> T | None:
        """Return one valid target, or raise the generic boundary error."""
        if not identifier:
            if required:
                self._reject()
            return None

        key = _entity_key(identifier)
        entity = self._entities.get(key) if key is not None else None
        expected_types = expected if isinstance(expected, tuple) else (expected,)
        if not key or not entity or not isinstance(entity, expected_types):
            self._reject()

        target = cast("T", entity)
        try:
            if predicate is not None and predicate(target) is False:
                self._reject()

            if key not in _existing_keys(existing):
                if authorize is not None:
                    allowed = authorize(target)
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

        return target

    def many[T: Entity](
        self,
        identifiers: Iterable[object],
        *,
        expected: type[T] | tuple[type[T], ...],
        action: Action | None = Action.VIEW,
        existing: object = None,
        predicate: Callable[[T], object] | None = None,
        authorize: Callable[[T], object] | None = None,
    ) -> list[T]:
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
