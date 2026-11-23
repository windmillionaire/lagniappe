"""Entity creation, persistence, deletion, and site fingerprinting."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from copy import copy
from enum import Enum
from typing import TYPE_CHECKING, cast

from google.api_core.exceptions import ServiceUnavailable
from google.cloud.datastore import Entity, Key
from google.cloud.datastore.transaction import Transaction

from lagniappe import CONFIG
from lagniappe.core.definitions.default import DefaultEnum

from .core import DATA, KINDS
from .defaults import DEFAULT_USER_FORM, DEFAULT_USER_PAGE
from .filter import Filter, Query
from .transactions import retry_aborted

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity as DomainEntity
    from lagniappe.core.entities.site import Site

    from .get import Identifier

PREFIX = CONFIG.PREFIX


def stored_row(entity: DomainEntity | Entity) -> Entity:
    """Return the keyed row for persistence, including SDK-compatible row subclasses."""
    row = getattr(entity, "db", entity)
    if not isinstance(row, dict) or getattr(row, "key", None) is None:
        raise ValueError("A persistent Datastore entity requires a key.")
    return cast(Entity, row)


def stored_key(row: Entity) -> Key:
    """Queries return persisted entities, each with its Datastore key."""
    key = row.key
    if key is None:
        raise ValueError("A queried Datastore entity has no key.")
    return key


class ExactEntityState(dict):
    """Guard a complete saved row, including absence of additional properties."""


class PageSubmissionState(ExactEntityState):
    """A full Page form edit leaves the revision-bound notes hint to its reader."""

    @staticmethod
    def with_current_note_hint[Row: dict[str, object]](
        row: Row, current: dict[str, object]
    ) -> Row:
        result = copy(row)
        for name in ("has_notes", "notes_checked_revision"):
            if name in current:
                result[name] = current[name]
            else:
                result.pop(name, None)
        return result


def initialize() -> bool:
    """Initialize data services and seed default reserved models if absent."""
    DATA.initialize()

    existing = Query(KINDS.models).filter(Filter().eq("reserved", True)).fetch_all()
    fresh_install = False

    if not existing:
        fresh_install = not any(
            Query(kind).fetch_one() for kind in KINDS if kind is not KINDS.site
        )
        partial = DATA.datastore.key(KINDS.models.value)
        keys = DATA.datastore.allocate_ids(partial, 2)

        default_user_form = Entity(keys[0])
        default_user_form.update(DEFAULT_USER_FORM)

        default_user_category = Entity(keys[1])
        default_user_category.update(DEFAULT_USER_PAGE)
        default_user_category["form"] = default_user_form.key

        DATA.datastore.put_multi([default_user_form, default_user_category])

    return fresh_install


def create_entity(key: Key) -> Entity:
    """Create a new Datastore Entity with the given key."""
    return Entity(key)


def create_key(entity_kind: str, parent: Identifier) -> Key:
    """Allocate a new Datastore key for the given entity kind and optional parent."""
    return create_keys(entity_kind, parent, 1)[0]


def create_keys(entity_kind: str, parent: Identifier, count: int) -> list[Key]:
    """Allocate a bounded group of numeric keys with one kind and parent."""
    if not 1 <= count <= 50:
        raise ValueError("Allocate between 1 and 50 keys at a time.")
    kind = KINDS[entity_kind].value
    if parent and isinstance(parent, Key):
        partial = DATA.datastore.key(kind, parent=parent)
    elif parent and (parent_key := getattr(parent, "key", None)):
        partial = DATA.datastore.key(kind, parent=parent_key)
    else:
        partial = DATA.datastore.key(kind)
    return DATA.datastore.allocate_ids(partial, count)


def create_named_key(
    entity_kind: str, identifier: int | str, parent: Identifier = None
) -> Key:
    """Create a stable complete key for an idempotent internal record."""
    kind = KINDS[entity_kind].value
    parent_key = getattr(parent, "key", parent)
    if parent_key:
        return DATA.datastore.key(kind, identifier, parent=parent_key)
    return DATA.datastore.key(kind, identifier)


class Fingerprint(Enum, metaclass=DefaultEnum):
    """Maps entity types and URL segments to site fingerprint identifiers."""

    # kind name
    category = "categories"
    project = "projects"
    page = "pages"
    ingress = "ingress"
    task = "tasks"
    form = "forms"
    user = "users"
    group = "users"
    public_group = "users"
    note = "home"
    notification = None
    report = "reports"

    # url segment
    categories = category
    projects = project
    pages = page
    tasks = task
    forms = form
    users = user
    notes = note
    activity = note
    notifications = notification
    reports = report

    DEFAULT = None


def save(*entities: DomainEntity | Site) -> None:
    """Persist entities to Datastore and update their site fingerprints."""
    to_save = {e.key: e.db for e in entities if getattr(e, "key", None)}
    to_update = update_site_fingerprints(*to_save.values())

    DATA.datastore.put_multi(list(to_save.values()) + to_update)


def _advances_site_fingerprint(entity, mask):
    fields = set(mask or ())
    if entity.db.get("type") == "notification":
        return False
    if entity.db.get("type") == "page" and fields and fields.issubset({
        "deferred_job", "has_notes", "notes_checked_revision",
    }):
        return False
    if not fields:
        return True
    return not (
        entity.db.get("type") in {"page", "project"}
        and "document_history" in fields
        and fields.issubset({"assets", "document_history"})
    )


def _put_mutation(writer, entity, property_mask=None):
    """Queue one full or property-masked Datastore mutation."""
    writer.put(entity)
    if property_mask is None:
        return
    mutation = writer.mutations[-1]
    mutation.update = mutation.upsert
    mutation.property_mask.paths.extend(property_mask)


@retry_aborted
def acknowledge_user_cache(key: Key, revision: str | int) -> bool:
    """Clear only the invalidation that the browser actually observed."""
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        if current is None:
            return False
        if not current.get("invalidate_cache"):
            return True
        if revision != current.get("cache_invalidation_revision", "legacy"):
            return False
        current["invalidate_cache"] = False
        _put_mutation(transaction, current, ("invalidate_cache",))
    return True


def save_mutations(
    writes: Iterable[tuple[DomainEntity, Iterable[str] | None]],
    *,
    guards: Iterable[tuple[Key, Mapping[str, object] | None]] | None = None,
    deletes: Iterable[DomainEntity] = (),
) -> None:
    """Persist full and property-masked writes with their collection revisions.

    ``writes`` contains ``(typed_entity, property_mask)`` pairs. A ``None`` mask
    is a normal full upsert. A non-empty mask is converted to an ``update``
    mutation so a missing row fails rather than being recreated with only the
    selected properties. Optional typed ``deletes`` commit with these writes;
    when guards are supplied, both use the same transaction.
    """
    writes = [
        (entity, None if mask is None else tuple(dict.fromkeys(mask)))
        for entity, mask in writes
        if getattr(entity, "key", None)
    ]
    deletes = list({
        entity.key: entity for entity in deletes if getattr(entity, "key", None)
    }.values())
    if not writes and not deletes:
        return

    for entity, mask in writes:
        if mask == ():
            raise ValueError("Property-masked writes require at least one property")
        if mask is not None and getattr(entity.key, "is_partial", False):
            raise ValueError("Property-masked writes require a complete entity key")

    fingerprint_entities = [
        entity.db for entity, mask in writes if _advances_site_fingerprint(entity, mask)
    ]
    fingerprint_entities.extend(
        entity.db for entity in deletes if _advances_site_fingerprint(entity, None)
    )
    if any(
        mask is None and entity.db.get("type") in {"page", "form"}
        and getattr(entity, "_permission_sources_changed", False)
        for entity, mask in writes
    ):
        # One collection invalidation replaces a write to every affected Task.
        fingerprint_entities.append({"type": "task"})
    fingerprints = (
        update_site_fingerprints(*fingerprint_entities) if fingerprint_entities else []
    )
    if guards:
        return _save_guarded_mutations(writes, fingerprints, guards, deletes=deletes)
    with DATA.datastore.batch() as batch:
        for entity, mask in writes:
            _put_mutation(batch, entity.db, mask)

        for fingerprint in fingerprints:
            batch.put(fingerprint)
        for entity in deletes:
            batch.delete(entity.key)


@retry_aborted
def _save_guarded_mutations(writes, fingerprints, guards, *, deletes=()):
    with DATA.datastore.transaction() as transaction:
        guarded_pages = check_mutation_guards(transaction, guards)
        for entity, mask in writes:
            row = entity.db
            if mask is None and (current := guarded_pages.get(row.key)) is not None:
                row = PageSubmissionState.with_current_note_hint(row, current)
            _put_mutation(transaction, row, mask)
        for fingerprint in fingerprints:
            transaction.put(fingerprint)
        for entity in deletes:
            transaction.delete(entity.key)


def check_mutation_guards(
    transaction: Transaction, guards: Iterable[tuple[Key, Mapping[str, object] | None]]
) -> dict[Key, Entity]:
    """Check every precondition and return Page rows whose notes hints must survive full writes."""
    guards = tuple(guards)
    keys = list(dict.fromkeys(key for key, _expected in guards))
    current_rows = {}
    # Datastore Lookup accepts at most 1,000 keys per request.
    for offset in range(0, len(keys), 1000):
        batch = keys[offset:offset + 1000]
        missing = []
        rows = DATA.datastore.get_multi(batch, missing=missing, transaction=transaction)
        current_rows.update((row.key, row) for row in rows)
        current_rows.update((row.key, None) for row in missing)
        # The SDK retries deferred keys, but can exhaust its retry loop without
        # resolving them. Only explicitly missing rows satisfy absence guards.
        if any(key not in current_rows for key in batch):
            raise ServiceUnavailable("Datastore did not resolve all mutation guards; retry.")
    guarded_pages = {}
    for key, expected in guards:
        current = current_rows[key]
        if isinstance(expected, PageSubmissionState) and current is not None:
            # Compare all other properties, including additions and removals.
            expected = PageSubmissionState.with_current_note_hint(expected, current)
            guarded_pages[key] = current
        conflict = (
            current is not None if expected is None else
            current is None or (
                dict(current) != expected if isinstance(expected, ExactEntityState) else
                any(current.get(name) != value for name, value in expected.items())
            )
        )
        if conflict:
            from lagniappe.core.exceptions import MutationConflict
            raise MutationConflict("Saved state changed while saving; reload and retry.")
    return guarded_pages


def save_raw(*entities: Entity) -> None:
    """Persist raw Datastore entities without running typed entity save hooks.

    Maintenance migrations use this path so malformed legacy properties do not
    need to survive typed entity construction. Site fingerprints still change,
    while business timestamps and unrelated fields remain untouched.
    """
    to_save = {
        entity.key: entity for entity in entities if getattr(entity, "key", None)
    }
    if not to_save:
        return

    to_update = update_site_fingerprints(*to_save.values())

    DATA.datastore.put_multi(list(to_save.values()) + to_update)


def delete_entities(entities: Iterable[DomainEntity]) -> None:
    """Delete durable rows and update fingerprints in one Datastore batch."""
    to_delete = {e.key: e.db for e in entities if getattr(e, "key", None)}
    if not to_delete:
        return
    to_update = update_site_fingerprints(
        *(
            entity
            for entity in to_delete.values()
            if entity.get("type") != "notification"
        )
    )

    with DATA.datastore.batch() as batch:
        for entity in to_update:
            batch.put(entity)
        for key in to_delete:
            batch.delete(key)


def delete_blobs(
    private_paths: Sequence[str], public_paths: Sequence[str]
) -> list[str]:
    """Delete post-commit storage blobs and return provider error messages."""
    errors = []

    def record_error(error):
        errors.append(str(error))

    if private_paths:
        DATA.private_bucket.delete_blobs(
            [path for path in private_paths if path], on_error=record_error
        )
    if public_paths:
        DATA.public_bucket.delete_blobs(
            [path for path in public_paths if path], on_error=record_error
        )
    return errors


def update_site_fingerprints(*entities: Mapping[str, object]) -> list[Entity]:
    fingerprints = {Fingerprint[kind].value for entity in entities if isinstance(kind := entity.get("type"), str)}
    keys = [DATA.datastore.key("site", f) for f in fingerprints if f]

    missing = []
    records = DATA.datastore.get_multi(keys, missing=missing)
    records = [r for r in records if r] + missing
    for record in records:
        record["fingerprint"] = str(uuid.uuid4())

    return records


def advance_site_fingerprints(*kinds: str) -> None:
    """Publish completed projection changes through the existing channels."""
    records = update_site_fingerprints(*({"type": kind} for kind in kinds))
    if records:
        DATA.datastore.put_multi(records)


def site_fingerprint(path: str) -> str | None:
    """Return the current fingerprint UUID for a URL path, creating one if needed."""
    return site_fingerprints((path,)).get(path)


def site_fingerprint_keys(paths: Iterable[str]) -> dict[str, Key]:
    """Resolve channel paths to their canonical durable revision keys."""
    paths = tuple(dict.fromkeys(path for path in paths if isinstance(path, str)))
    indexes = {}
    for path in paths:
        parts = [part for part in path.split("/") if part]
        index = (
            "home"
            if not parts
            else next((part for part in parts if Fingerprint[part].value), None)
        )
        if index:
            indexes[path] = index

    keys_by_index = {
        index: DATA.datastore.key("site", index)
        for index in dict.fromkeys(indexes.values())
    }
    return {path: keys_by_index[index] for path, index in indexes.items()}


def site_fingerprints(
    paths: Iterable[str], *, records: Mapping[Key, Entity] | None = None
) -> dict[str, str | None]:
    """Read channel revisions once, or reuse this request's durable root batch."""
    path_keys = site_fingerprint_keys(paths)
    keys = list(dict.fromkeys(path_keys.values()))
    missing = []
    if records is None:
        rows = DATA.datastore.get_multi(keys, missing=missing)
    else:
        rows = [records[key] for key in keys if key in records]
        missing = [Entity(key) for key in keys if key not in records]
    for record in missing:
        record["fingerprint"] = str(uuid.uuid4())
    if missing:
        DATA.datastore.put_multi(missing)
    by_key = {record.key: record for record in [*rows, *missing] if record}

    return {
        path: by_key[key].get("fingerprint")
        for path, key in path_keys.items()
    }


def cleanup_test_data() -> None:
    """Delete all test Datastore entities and Storage objects (testing only)."""
    if not CONFIG.testing:
        return

    for kind in set([k.value for k in KINDS if k.value]):
        entities = Query(kind).fetch_all()
        if entities:
            DATA.datastore.delete_multi(entities)

    DATA.delete_buckets()
