"""Entity creation, persistence, deletion, and site fingerprinting."""

from enum import Enum
import uuid

from google.cloud.datastore import Entity, Key

from lagniappe import CONFIG

from .core import DATA, KINDS
from .defaults import DEFAULT_USER_FORM, DEFAULT_USER_PAGE
from .filter import Filter, Query
from lagniappe.core.definitions.default import DefaultEnum

PREFIX = CONFIG.PREFIX


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_database_initialize_only_marks_new_content_stores_as_fresh
# @features database-migrations setup
# @dimensions fresh-install detection reserved-seeding
def initialize():
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


# @testable infrastructure
def create_entity(key):
    """Create a new Datastore Entity with the given key."""
    return Entity(key)


# @testable infrastructure
def create_key(entity_kind, parent):
    """Allocate a new Datastore key for the given entity kind and optional parent."""
    kind = KINDS[entity_kind].value
    if parent and isinstance(parent, Key):
        partial = DATA.datastore.key(kind, parent=parent)
    elif parent and hasattr(parent, "key"):
        partial = DATA.datastore.key(kind, parent=parent.key)
    else:
        partial = DATA.datastore.key(kind)
    key = DATA.datastore.allocate_ids(partial, 1)[0]
    return key


# @testable infrastructure
def create_named_key(entity_kind, identifier, parent=None):
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


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_save_persists_user_and_users_fingerprint_record
# @features users caching
# @dimensions site-fingerprint save
def save(*entities):
    """Persist entities to Datastore and update their site fingerprints."""
    to_save = {e.key: e.db for e in entities if getattr(e, "key", None)}
    to_update = update_site_fingerprints(*to_save.values())

    DATA.datastore.put_multi(list(to_save.values()) + to_update)


# @testable false
# @covered-by lagniappe/core/tools/database/utility.py::save_mutations
# @reason neutral-mask selection is asserted through the public mutation writer
def _advances_site_fingerprint(entity, mask):
    fields = set(mask or ())
    if entity.db.get("type") == "notification":
        return False
    if entity.db.get("type") == "page" and fields and fields.issubset({"deferred_job"}):
        return False
    if not fields:
        return True
    return not (
        entity.db.get("type") in {"page", "project"}
        and "document_history" in fields
        and fields.issubset({"assets", "document_history"})
    )


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::save_mutations
def _put_mutation(writer, entity, property_mask=None):
    """Queue one full or property-masked Datastore mutation."""
    writer.put(entity)
    if property_mask is None:
        return
    mutation = writer.mutations[-1]
    mutation.update = mutation.upsert
    mutation.property_mask.paths.extend(property_mask)


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_save_mutations_applies_property_masks_and_fingerprints
# @tests tests_unit/test_018_database_utility.py::test_notification_save_and_delete_skip_site_fingerprints
# @features mutations database
# @dimensions property-mask update full-upsert site-fingerprint document-checkpoint
# @pairs database:property-mask database:update database:full-upsert
# @pairs database:site-fingerprint database:document-checkpoint
# @pairs mutations:property-mask mutations:update mutations:full-upsert
# @pairs mutations:site-fingerprint mutations:document-checkpoint
# @pairs notifications:mutation notifications:site-fingerprint-isolation
def save_mutations(writes):
    """Persist full and property-masked entity writes in one Datastore batch.

    ``writes`` contains ``(typed_entity, property_mask)`` pairs. A ``None`` mask
    is a normal full upsert. A non-empty mask is converted to an ``update``
    mutation so a missing row fails rather than being recreated with only the
    selected properties.
    """
    writes = [
        (entity, None if mask is None else tuple(dict.fromkeys(mask)))
        for entity, mask in writes
        if getattr(entity, "key", None)
    ]
    if not writes:
        return

    for entity, mask in writes:
        if mask == ():
            raise ValueError("Property-masked writes require at least one property")
        if mask is not None and getattr(entity.key, "is_partial", False):
            raise ValueError("Property-masked writes require a complete entity key")

    fingerprint_entities = [
        entity.db for entity, mask in writes if _advances_site_fingerprint(entity, mask)
    ]
    fingerprints = (
        update_site_fingerprints(*fingerprint_entities) if fingerprint_entities else []
    )
    with DATA.datastore.batch() as batch:
        for entity, mask in writes:
            _put_mutation(batch, entity.db, mask)

        for fingerprint in fingerprints:
            batch.put(fingerprint)


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_save_raw_persists_datastore_entities_without_typed_save_hooks
# @features database migrations
# @dimensions raw-save site-fingerprint
def save_raw(*entities):
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


# @testable false
# @reason delete side effects are owned by E2E coverage against configured services
def delete_entities(entities):
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


# @testable false
# @covered-by lagniappe/core/mutations/executor.py::execute_post_commit
# @reason blob cleanup is a post-commit provider effect covered by entity deletion
def delete_blobs(private_paths, public_paths):
    """Delete post-commit storage blobs and return provider error messages."""
    errors = []

    # @testable false
    # @covered-by lagniappe/core/tools/database/utility.py::delete_blobs
    # @reason provider callback only normalizes an error into the outcome
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


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_update_site_fingerprints_upserts_missing_users_fingerprint
# @features users caching
# @dimensions site-fingerprint invalidation
def update_site_fingerprints(*entities):
    fingerprints = set(Fingerprint[e.get("type")].value for e in entities)
    keys = [DATA.datastore.key("site", f) for f in fingerprints if f]

    missing = []
    records = DATA.datastore.get_multi(keys, missing=missing)
    records = [r for r in records if r] + missing
    for record in records:
        record["fingerprint"] = str(uuid.uuid4())

    return records


# @testable false
# @reason site fingerprint creation is persistence-owned and covered by route/E2E workflows
def site_fingerprint(path):
    """Return the current fingerprint UUID for a URL path, creating one if needed."""
    return site_fingerprints((path,)).get(path)


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_channel_revisions_batch_only_requested_site_fingerprints
# @tests tests_unit/test_018_database_utility.py::test_site_fingerprints_batch_reads_only_resolved_paths
# @pairs polling:channel polling:batching polling:mounted-scope
def site_fingerprints(paths):
    """Return fingerprints for ``paths`` through one bounded multi-read."""
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
    missing = []
    records = DATA.datastore.get_multi(list(keys_by_index.values()), missing=missing)
    for record in missing:
        record["fingerprint"] = str(uuid.uuid4())
    if missing:
        DATA.datastore.put_multi(missing)
    by_key = {record.key: record for record in [*records, *missing] if record}

    return {
        path: by_key[keys_by_index[index]].get("fingerprint")
        for path, index in indexes.items()
    }


# @testable infrastructure
def cleanup_test_data():
    """Delete all test Datastore entities and Storage objects (testing only)."""
    if not CONFIG.testing:
        return

    for kind in set([k.value for k in KINDS if k.value]):
        entities = Query(kind).fetch_all()
        if entities:
            DATA.datastore.delete_multi(entities)

    DATA.delete_buckets()
