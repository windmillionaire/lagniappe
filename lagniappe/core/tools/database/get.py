"""Datastore read queries for all entity types."""

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, UTC
from typing import Literal, Protocol, TypedDict, Unpack, cast, overload

from google.cloud.datastore import Entity, Key

from ...restrictions import QueryHashes, Restriction
from .core import DATA, KINDS
from .filter import Filter, Query, Results
from config.datastore import decode_urlsafe_key, encode_urlsafe_key


class _Keyed(Protocol):
    @property
    def key(self) -> Key | None: ...


type Identifier = Key | _Keyed | str | None


class TaskFilters(TypedDict, total=False):
    project: Identifier
    model: Identifier
    hashes: QueryHashes | None
    completed: bool
    assigned_to: Identifier


def _empty_results() -> Results[Entity]:
    return Results([], None)


# --- Keys ---


@overload
def urlsafe_key(identifier: Key) -> str: ...


@overload
def urlsafe_key(identifier: object) -> str | None: ...


def urlsafe_key(identifier: object) -> str | None:
    """Convert an identifier to its URL-safe base64 key string."""
    key = datastore_key(identifier)
    if key:
        return encode_urlsafe_key(key)

    return None


def datastore_key(identifier: object) -> Key | None:
    """Resolve a live key, keyed entity, or urlsafe string without rebinding."""
    if identifier is None:
        return None
    elif isinstance(identifier, Key):
        return identifier
    elif hasattr(identifier, "key"):
        # Framework entities and SDK records both expose their own key.
        return cast(_Keyed, identifier).key
    elif isinstance(identifier, str):
        try:
            return decode_urlsafe_key(identifier)
        except (ValueError, UnicodeError):
            return None
    return None


def is_urlsafe_key(identifier: str | bytes) -> bool:
    """Return True if the identifier is a valid URL-safe Datastore key."""
    try:
        decode_urlsafe_key(identifier)
        return True
    except (ValueError, UnicodeError):
        return False


# --- Entities ---


def entity(identifier: Identifier) -> Entity | None:
    """Fetch a single Datastore entity by key, entity, or URL-safe string."""
    if isinstance(identifier, Entity):
        return identifier

    key = datastore_key(identifier)

    return DATA.datastore.get(key) if key else None


def reserved(kind: str | None = None) -> Entity | dict[str, Entity]:
    """Return reserved models, optionally filtered to a single kind by type."""
    results = Query(KINDS.models).filter(Filter().eq("reserved", True)).fetch_all()
    reserved = {m["type"]: m for m in results}
    return reserved[kind] if kind else reserved


def entities(*keys: Identifier | list[Key] | set[Key]) -> list[Entity]:
    """Fetch multiple entities by keys, accepting keys, lists, or sets."""
    if not keys:
        return []

    all_keys = set()
    for key in keys:
        if isinstance(key, list):
            all_keys.update(key)
        elif isinstance(key, set):
            all_keys |= key
        elif key:
            all_keys.add(datastore_key(key))

    valid_keys = [k for k in all_keys if k]
    if not valid_keys:
        return []

    return DATA.datastore.get_multi(valid_keys)


# --- Users ---


def user(email: str) -> Entity | None:
    """Fetch a single user entity by email address."""
    return Query(KINDS.users).filter(Filter().eq("email", email)).fetch_one()


def users(start_cursor: str | None = None, hashes: QueryHashes | None = Restriction.UNRESTRICTED, group: Key | None = None, limit: int | None = 25) -> Results[Entity]:
    """Fetch a paginated list of users, optionally filtered by hashes or group."""
    if Restriction.is_denied(hashes):
        return _empty_results()

    f = Filter()
    if hashes is not None and not Restriction.is_unrestricted(hashes):
        f.contains("hash", hashes)
    elif group:
        f.eq("groups", group)

    q = (
        Query(KINDS.users)
        .filter(f)
        .order("-modified")
        .limit(limit)
        .cursor(start_cursor)
    )
    return q.fetch()


def groups(hashes: QueryHashes = Restriction.UNRESTRICTED) -> list[Entity]:
    """Fetch all group models, optionally restricted to the given hashes."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("type", "group").requires(hashes))
        .fetch_all()
    )


def public_group() -> Entity | None:
    """Fetch the built-in public group model."""
    public = (
        Query(KINDS.models)
        .filter(Filter().eq("type", "public_group").eq("name", "public"))
        .fetch_one()
    )
    if public:
        return public

    return (
        Query(KINDS.models)
        .filter(Filter().eq("type", "group").eq("name", "public"))
        .fetch_one()
    )


def group_view_access(hashes: list[str] | str) -> list[Entity]:
    """Fetch all groups that have view access to the given hashes."""
    if Restriction.is_denied(hashes):
        return []
    elif isinstance(hashes, str):
        hashes = [hashes]

    hashes = [h for h in hashes if h]
    return (
        Query(KINDS.models)
        .filter(Filter().eq("type", "group").contains("views", hashes))
        .fetch_all()
    )


# --- Home ---


@overload
def models(
    model_type: str, start_cursor: str | None = None, limit: Literal[10] = 10,
    hashes: QueryHashes = Restriction.UNRESTRICTED,
) -> Results[Entity]: ...


@overload
def models(
    model_type: str, start_cursor: str | None = None, limit: int | None = 10,
    hashes: QueryHashes = Restriction.UNRESTRICTED,
) -> Results[Entity] | list[Entity]: ...


def models(
    model_type: str, start_cursor: str | None = None, limit: int | None = 10,
    hashes: QueryHashes = Restriction.UNRESTRICTED,
) -> Results[Entity] | list[Entity]:
    """Fetch active models of a given type with optional pagination."""
    if Restriction.is_denied(hashes):
        return _empty_results() if limit else []

    f = Filter().eq("type", model_type).eq("active", True).requires(hashes)

    if not limit:
        return [
            e
            for e in Query(KINDS.models).filter(f).fetch_all()
            if not e.get("reserved")
        ]

    return (
        Query(KINDS.models)
        .filter(f)
        .order("-modified")
        .limit(limit)
        .cursor(start_cursor)
        .fetch()
    )


def recent_pages(start_cursor: str | None = None, limit: int = 10,
                 hashes: QueryHashes = Restriction.UNRESTRICTED) -> Results[Entity]:
    """Fetch recent active pages with optional permission restrictions."""
    if Restriction.is_denied(hashes):
        return _empty_results()

    return (
        Query(KINDS.instances)
        .filter(Filter().eq("type", "page").eq("active", True).requires(hashes))
        .order("-modified")
        .limit(limit)
        .cursor(start_cursor)
        .fetch()
    )


def category_by_name(name: str) -> Entity | None:
    """Fetch an active category model by exact name."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("type", "category").eq("name", name).eq("active", True))
        .fetch_one()
    )


def all_models() -> Iterator[Entity]:
    """Iterate over all active models."""
    return Query(KINDS.models).filter(Filter().eq("active", True)).fetch_iter()


def all_categories() -> Iterator[Entity]:
    """Iterate over all active category models."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("active", True).eq("type", "category"))
        .fetch_iter()
    )


def all_projects() -> Iterator[Entity]:
    """Iterate over all active project models."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("active", True).eq("type", "project"))
        .fetch_iter()
    )


def all_instances() -> Iterator[Entity]:
    """Iterate over all active instances."""
    return Query(KINDS.instances).fetch_iter()


def all_pages() -> Iterator[Entity]:
    """Iterate over all active page instances."""
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("active", True).eq("type", "page"))
        .fetch_iter()
    )


def all_files() -> Iterator[Entity]:
    """Iterate over all file entities."""
    return Query(KINDS.files).fetch_iter()


def all_users() -> Iterator[Entity]:
    """Iterate over all user entities."""
    return Query(KINDS.users).fetch_iter()


# --- Pages ---


def public_pages(public_id: str) -> list[Entity]:
    """Fetch all page instances sharing a public_id."""
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("type", "page").eq("public_id", public_id))
        .fetch_all()
    )


def discoverable_page_rows() -> list[Entity]:
    """Fetch candidate public rows; callers enforce active/type/page settings."""
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("public", True))
        .fetch_all()
    )


@overload
def pages(category_key: Key, form: _Keyed | None = None, start_cursor: str | None = None,
          limit: int | None = 25, hashes: QueryHashes = Restriction.UNRESTRICTED) -> Results[Entity]: ...

@overload
def pages(category_key: object, form: _Keyed | None = None, start_cursor: str | None = None,
          limit: Literal[25] = 25, hashes: QueryHashes = Restriction.UNRESTRICTED) -> Results[Entity]: ...

@overload
def pages(category_key: object, form: _Keyed | None = None, start_cursor: str | None = None,
          limit: int | None = 25, hashes: QueryHashes = Restriction.UNRESTRICTED) -> Results[Entity] | list[Entity]: ...

def pages(
    category_key: object,
    form: _Keyed | None = None,
    start_cursor: str | None = None,
    limit: int | None = 25,
    hashes: QueryHashes = Restriction.UNRESTRICTED,
) -> Results[Entity] | list[Entity]:
    """Fetch paginated pages belonging to a category."""
    if Restriction.is_denied(hashes):
        return _empty_results()

    if not limit and not category_key:
        return (
            Query(KINDS.instances)
            .filter(Filter().eq("active", True).eq("type", "page"))
            .fetch_all()
        )

    category_key = datastore_key(category_key)

    f = (
        Filter()
        .any_of(
            Filter()
            .eq("active", True)
            .eq("type", "page")
            .eq("form", form.key if form else None)
            .eq("categories", category_key),
            Filter()
            .eq("active", True)
            .eq("type", "page")
            .eq("model", category_key)
            .eq("form", form.key if form else None),
        )
        .requires(hashes)
    )

    return (
        Query(KINDS.instances)
        .filter(f)
        .order("-modified")
        .limit(limit)
        .cursor(start_cursor)
        .fetch()
    )


# --- Files ---


def page_files(page_key: Identifier) -> list[Entity]:
    """Fetch Files owned directly by the Page."""
    return (
        Query(KINDS.files)
        .filter(Filter().eq("page", datastore_key(page_key)))
        .fetch_all()
    )


def ingress_files() -> list[Entity]:
    """Fetch all file entities with type 'ingress'."""
    return Query(KINDS.files).filter(Filter().eq("type", "ingress")).fetch_all()


# --- Projects ---


def model_tasks(project: _Keyed) -> list[Entity]:
    """Fetch all task model entities that are children of a project."""
    return (
        Query(KINDS.models)
        .ancestor(project.key)
        .filter(Filter().eq("type", "model"))
        .fetch_all()
    )


# --- Tasks ---

# Lower bound so ``>=`` matches only instances that have ``due_date`` indexed.
_TASK_DUE_MIN = datetime(1, 1, 1, tzinfo=UTC)


def _tasks_filter(
    project: Identifier = None,
    model: Identifier = None,
    hashes: QueryHashes | None = None,
    completed: bool = False,
    assigned_to: Identifier = None,
) -> Filter:
    f = Filter().eq("type", "task").eq("active", True).eq("completed", completed)
    if model:
        f.eq("model", datastore_key(model))
    elif project:
        f.eq("project", datastore_key(project))

    assigned_to_key = datastore_key(assigned_to)
    if (
        assigned_to_key is not None
        and hashes is not None
        and not Restriction.is_unrestricted(hashes)
    ):
        if Restriction.is_denied(hashes):
            f.eq("assigned_to", assigned_to_key)
        else:
            f.any_of(
                Filter().requires(hashes),
                Filter().eq("assigned_to", assigned_to_key),
            )
    elif hashes is not None:
        f.requires(hashes)
    return f


def tasks(
    start_cursor: str | None = None, limit: int | None = 25, **kwargs: Unpack[TaskFilters]
) -> Results[Entity]:
    """Fetch paginated task instances with optional model, project, and completion filters."""
    if (
        Restriction.is_denied(kwargs.get("hashes"))
        and kwargs.get("assigned_to") is None
    ):
        return _empty_results()

    f = _tasks_filter(
        kwargs.get("project"),
        kwargs.get("model"),
        kwargs.get("hashes"),
        kwargs.get("completed", False),
        kwargs.get("assigned_to"),
    )

    q = Query(KINDS.instances).filter(f).order("-modified")
    if limit:
        q.limit(limit)
    if start_cursor:
        q.cursor(start_cursor)

    return q.fetch()


def tasks_with_due_dates(
    start_cursor: str | None = None, limit: int | None = 25, **kwargs: Unpack[TaskFilters]
) -> Results[Entity]:
    """Paginate incomplete active tasks that have a due date, ordered soonest first."""
    if (
        Restriction.is_denied(kwargs.get("hashes"))
        and kwargs.get("assigned_to") is None
    ):
        return _empty_results()

    f = _tasks_filter(
        kwargs.get("project"),
        kwargs.get("model"),
        kwargs.get("hashes"),
        kwargs.get("completed", False),
        kwargs.get("assigned_to"),
    )
    f.ge("due_date", _TASK_DUE_MIN)

    q = Query(KINDS.instances).filter(f).order("due_date")
    if limit:
        q.limit(limit)
    if start_cursor:
        q.cursor(start_cursor)

    return q.fetch()


def tasks_without_due_dates(
    start_cursor: str | None = None, limit: int | None = 25, **kwargs: Unpack[TaskFilters]
) -> Results[Entity]:
    """Paginate tasks with no due date, most recently modified first."""
    if (
        Restriction.is_denied(kwargs.get("hashes"))
        and kwargs.get("assigned_to") is None
    ):
        return _empty_results()

    f = _tasks_filter(
        kwargs.get("project"),
        kwargs.get("model"),
        kwargs.get("hashes"),
        kwargs.get("completed", False),
        kwargs.get("assigned_to"),
    )
    f.is_null("due_date")

    q = Query(KINDS.instances).filter(f).order("-modified")
    if limit:
        q.limit(limit)
    if start_cursor:
        q.cursor(start_cursor)

    return q.fetch()


def page_tasks(page: _Keyed) -> list[Entity]:
    """Fetch all tasks linked to, owned by, or assigned to a page."""
    f = Filter().any_of(
        Filter().eq("type", "task").eq("linked_pages", page.key),
        Filter().eq("type", "task").eq("page", page.key),
        Filter().eq("type", "task").eq("assigned_to", page.key),
    )

    return Query(KINDS.instances).filter(f).fetch_all()


def page_tasks_with_history(page: _Keyed) -> list[Entity]:
    """Fetch Task and TaskHistory rows whose owning ``page`` is this Page."""
    f = Filter().eq("type", "task").eq("page", page.key)
    tasks = Query(KINDS.instances).filter(f).fetch_all()

    h = Filter().eq("type", "task_history").eq("page", page.key)
    history = Query(KINDS.history).filter(h).fetch_all()

    return tasks + history


def user_task_count(page: _Keyed) -> int:
    """Count tasks owned by or assigned to a page."""
    f = Filter().any_of(
        Filter()
        .eq("type", "task")
        .eq("active", True)
        .eq("completed", False)
        .eq("page", page.key),
        Filter()
        .eq("type", "task")
        .eq("active", True)
        .eq("completed", False)
        .eq("assigned_to", page.key),
    )

    return Query(KINDS.instances).filter(f).count()


def due_tasks(hashes: QueryHashes = Restriction.UNRESTRICTED, assigned_to: Identifier = None) -> list[Entity]:
    """Fetch incomplete active tasks due within the next seven days."""
    if Restriction.is_denied(hashes) and assigned_to is None:
        return []

    today = datetime.now(UTC)
    next_week = today + timedelta(days=7)

    f = _tasks_filter(
        hashes=hashes,
        completed=False,
        assigned_to=assigned_to,
    )
    f.ge("due_date", _TASK_DUE_MIN).le("due_date", next_week)

    return Query(KINDS.instances).filter(f).order("due_date").fetch_all()


def task_history(task: _Keyed) -> list[Entity]:
    """Fetch all history entries for a task."""
    return Query(KINDS.history).ancestor(task.key).fetch_all()


def latest_task_history(task: _Keyed) -> Entity | None:
    """Fetch the most recent history entry for a task."""
    return Query(KINDS.history).ancestor(task.key).order("-created").fetch_one()


def document_history(entity: _Keyed) -> list[Entity]:
    """Fetch direct document-history children for an entity."""
    rows = (
        Query(KINDS.history)
        .ancestor(entity.key)
        .filter(Filter().eq("type", "document_history"))
        .fetch_all()
    )
    # Datastore assigns a key to every persisted query result.
    return [row for row in rows if cast(Key, row.key).parent == entity.key]


# --- Filters ---


def filters(entity: Identifier, user_key: Identifier = None) -> list[Entity]:
    """Fetch saved filters for an entity, optionally scoped to a user."""
    entity_key = datastore_key(entity)
    user_key = datastore_key(user_key) or user_key

    if not entity_key:
        return []

    query = Query(KINDS.filters).ancestor(entity_key)
    if user_key:
        query.filter(Filter().eq("creator", user_key))

    return query.fetch_all()


# --- Forms ---


def forms(start_cursor: str | None = None, limit: int | None = 25) -> Results[Entity]:
    """Fetch a paginated list of active form models."""
    f = Filter().eq("type", "form").eq("active", True)
    return (
        Query(KINDS.models)
        .filter(f)
        .order("-modified")
        .limit(limit)
        .cursor(start_cursor)
        .fetch()
    )


def form_users(*forms: _Keyed) -> list[Entity]:
    """Find categories and models that reference any of the given forms."""
    form_keys = list(dict.fromkeys(f.key for f in forms))
    if not form_keys:
        return []

    parents = {}
    project_keys = set()
    # Two reference properties per Form: keep each OR within 30 disjunctions.
    # Filter types locally so this needs only the existing property indexes.
    for start in range(0, len(form_keys), 15):
        batch = form_keys[start:start + 15]
        references = Filter().any_of(
            Filter().contains("form", batch),
            Filter().contains("forms", batch),
        )
        for model in Query(KINDS.models).filter(references).fetch_iter():
            if model.get("type") not in {"category", "model"}:
                continue
            parents[model.key] = model
            if model.get("type") == "model":
                project_keys.add(cast(Key, model.key).parent)

    return list(parents.values()) + entities(list(project_keys))


def form_instance_users(form_key: Key) -> list[Entity]:
    """Fetch all instances that reference a given form."""
    return Query(KINDS.instances).filter(Filter().eq("form", form_key)).fetch_all()


# --- Activity ---


def activity(parent: Identifier, types: str | Iterable[str] | None = ("note", "notification")) -> list[Entity]:
    """Fetch activity items belonging to ``parent``."""
    parent_key = datastore_key(parent)
    if not parent_key:
        return []

    activity_types = [types] if isinstance(types, str) else list(types or [])
    f = Filter()
    if len(activity_types) == 1:
        f.eq("type", activity_types[0])
    elif activity_types:
        f.contains("type", activity_types)

    return (
        Query(KINDS.activity)
        .ancestor(parent_key)
        .filter(f)
        .order("-created")
        .fetch_all()
    )


def home_notes(user: Identifier) -> list[Entity]:
    """Fetch Home-scope notes visible to ``user``."""
    note_filter = Filter().eq("type", "note").eq("scope", "home")
    notes = Query(KINDS.activity).filter(note_filter).order("-created").fetch_all()

    if not (getattr(user, "is_admin", False) or getattr(user, "is_owner", False)):
        user_key = datastore_key(user)
        notes = [
            note
            for note in notes
            if note.get("visibility") == "everyone" or note.get("user") == user_key
        ]

    return notes


def notes(user: Identifier) -> list[Entity]:
    return home_notes(user)


def page_notes(page: Identifier) -> list[Entity]:
    """Fetch notes attached to a Page."""
    return activity(page, types="note")


def notes_by_user(user: Identifier) -> list[Entity]:
    """Fetch notes authored by ``user`` across Home and Page surfaces."""
    user_key = datastore_key(user)
    if not user_key:
        return []
    return [
        item
        for item in Query(KINDS.activity)
        .filter(Filter().eq("user", user_key))
        .fetch_all()
        if item.get("type") == "note"
    ]


def ai_reports(user_key: Identifier, *, start_cursor: str | None = None, limit: int | None = 10) -> Results[Entity]:
    """Fetch paginated AI report activity records belonging to a user."""
    parent_key = datastore_key(user_key)
    if not parent_key:
        return _empty_results()

    return (
        Query(KINDS.activity)
        .ancestor(parent_key)
        .filter(Filter().eq("type", "report"))
        .order("-created")
        .limit(limit)
        .cursor(start_cursor)
        .fetch()
    )


def ai_report_by_hash(user_key: Identifier, report_hash: str) -> Entity | None:
    """Fetch one activity record by public hash beneath the given user."""
    parent_key = datastore_key(user_key)
    report_hash = str(report_hash or "").strip()
    if not parent_key or not report_hash:
        return None
    return (
        Query(KINDS.activity)
        .ancestor(parent_key)
        .filter(Filter().eq("hash", report_hash))
        .fetch_one()
    )


def task_files(task_key: Identifier) -> list[Entity]:
    return Query(KINDS.files).filter(Filter().eq("task", datastore_key(task_key))).fetch_all()


def file_references(file_key: Identifier) -> list[Entity]:
    return [row for kind in (KINDS.instances, KINDS.history)
            for row in Query(kind).filter(Filter().eq("files", datastore_key(file_key))).fetch_all()]
