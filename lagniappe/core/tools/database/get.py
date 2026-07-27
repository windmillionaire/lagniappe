"""Datastore read queries for all entity types."""

from datetime import datetime, timedelta, timezone

from google.cloud.datastore import Entity, Key
from google.protobuf.message import DecodeError

from ...definitions import Restriction
from .core import DATA, KINDS
from .filter import Filter, Query, Results


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_empty_results_has_no_items_or_cursor
# @pairs database:restricted-results database:empty-page
def _empty_results():
    return Results([], None)


# --- Keys ---


# @testable infrastructure
def urlsafe_key(identifier):
    """Convert an identifier to its URL-safe base64 key string."""
    key = datastore_key(identifier)
    if key:
        return key.to_legacy_urlsafe().decode()

    return None


# @testable infrastructure
def datastore_key(identifier):
    """Resolve an identifier (key, entity, or URL-safe string) to a Datastore Key."""
    if not identifier:
        return None
    elif isinstance(identifier, Key):
        return identifier
    elif hasattr(identifier, "key"):
        return identifier.key
    elif isinstance(identifier, str):
        try:
            return Key.from_legacy_urlsafe(identifier)
        except (ValueError, DecodeError):
            return None
    return None


# @testable infrastructure
def is_urlsafe_key(identifier):
    """Return True if the identifier is a valid URL-safe Datastore key."""
    try:
        Key.from_legacy_urlsafe(identifier)
        return True
    except (ValueError, DecodeError):
        return False


# --- Entities ---


# @testable infrastructure
def entity(identifier):
    """Fetch a single Datastore entity by key, entity, or URL-safe string."""
    if isinstance(identifier, Entity):
        return identifier

    key = datastore_key(identifier)

    return DATA.datastore.get(key) if key else None


# @testable false
# @reason reserved model lookup is persistence-owned and covered by setup/E2E flows
def reserved(kind=None):
    """Return reserved models, optionally filtered to a single kind by type."""
    results = Query(KINDS.models).filter(Filter().eq("reserved", True)).fetch_all()
    reserved = {m["type"]: m for m in results}
    return reserved[kind] if kind else reserved


# @testable infrastructure
def entities(*keys):
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

    all_keys = [k for k in all_keys if k]
    if not all_keys:
        return []

    return DATA.datastore.get_multi(all_keys)


# --- Users ---


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def user(email):
    """Fetch a single user entity by email address."""
    return Query(KINDS.users).filter(Filter().eq("email", email)).fetch_one()


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def users(start_cursor=None, hashes=Restriction.UNRESTRICTED, group=None, limit=25):
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def groups(hashes=Restriction.UNRESTRICTED):
    """Fetch all group models, optionally restricted to the given hashes."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("type", "group").requires(hashes))
        .fetch_all()
    )


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def public_group():
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def group_view_access(hashes):
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def models(model_type, start_cursor=None, limit=10, hashes=Restriction.UNRESTRICTED):
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def recent_pages(start_cursor=None, limit=10, hashes=Restriction.UNRESTRICTED):
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def category_by_name(name):
    """Fetch an active category model by exact name."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("type", "category").eq("name", name).eq("active", True))
        .fetch_one()
    )


# --- Site ---


# @testable false
# @reason site config persistence is owned by route/E2E workflows
def site(key):
    """Fetch a site config entity by key, creating it if missing."""
    site = DATA.datastore.get(key)
    if site:
        return site

    site = DATA.datastore.entity(key=key)
    DATA.datastore.put(site)

    return site


# @testable infrastructure
def site_key(identifier):
    """Build a Datastore key for a site config entry."""
    return DATA.datastore.key(KINDS.site.value, identifier)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @features admin
# @dimensions metadata public-preview
def site_image():
    """Fetch the stored site image metadata entity."""
    image_key = DATA.datastore.key("site", "image")
    return DATA.datastore.get(image_key)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_deployment_form_saves_and_updates_summary
# @features admin
# @dimensions deployment-settings metadata
def site_deployment():
    """Fetch the stored deployment settings metadata entity."""
    deployment_key = DATA.datastore.key("site", "deployment")
    return DATA.datastore.get(deployment_key)


# @testable true
# @tests tests_e2e/008_users/test_008e_site_settings_routes.py::test_site_settings_loads_ai_settings_and_options
# @features admin
# @dimensions ai-settings metadata
def site_ai():
    """Fetch the stored AI model settings metadata entity."""
    ai_key = DATA.datastore.key("site", "ai")
    return DATA.datastore.get(ai_key)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::site_export
# @reason public database API forwards to the metadata helper
def site_export(export_id):
    """Fetch a site export metadata record by export id."""
    from .assets import site_export as _site_export

    return _site_export(export_id)


# @testable false
# @covered-by lagniappe/core/tools/database/assets.py::site_exports
# @reason public database API forwards to the metadata helper
def site_exports(limit=10):
    """Fetch recent site export metadata records."""
    from .assets import site_exports as _site_exports

    return _site_exports(limit=limit)


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_models():
    """Iterate over all active models."""
    return Query(KINDS.models).filter(Filter().eq("active", True)).fetch_iter()


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_categories():
    """Iterate over all active category models."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("active", True).eq("type", "category"))
        .fetch_iter()
    )


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_projects():
    """Iterate over all active project models."""
    return (
        Query(KINDS.models)
        .filter(Filter().eq("active", True).eq("type", "project"))
        .fetch_iter()
    )


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_instances():
    """Iterate over all active instances."""
    return Query(KINDS.instances).fetch_iter()


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_pages():
    """Iterate over all active page instances."""
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("active", True).eq("type", "page"))
        .fetch_iter()
    )


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_files():
    """Iterate over all file entities."""
    return Query(KINDS.files).fetch_iter()


# @testable false
# @reason maintenance iterator is persistence-owned and covered by maintenance/E2E workflows
def all_users():
    """Iterate over all user entities."""
    return Query(KINDS.users).fetch_iter()


# --- Pages ---


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def public_pages(public_id):
    """Fetch all page instances sharing a public_id."""
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("type", "page").eq("public_id", public_id))
        .fetch_all()
    )


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def pages(
    category_key,
    form=None,
    start_cursor=None,
    limit=25,
    hashes=Restriction.UNRESTRICTED,
):
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def page_files(page_key):
    """Fetch all file entities attached to a page."""
    return (
        Query(KINDS.files)
        .filter(Filter().eq("pages", datastore_key(page_key)))
        .fetch_all()
    )


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def ingress_files():
    """Fetch all file entities with type 'ingress'."""
    return Query(KINDS.files).filter(Filter().eq("type", "ingress")).fetch_all()


# --- Projects ---


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def model_tasks(project):
    """Fetch all task model entities that are children of a project."""
    return (
        Query(KINDS.models)
        .ancestor(project.key)
        .filter(Filter().eq("type", "model"))
        .fetch_all()
    )


# --- Tasks ---

# Lower bound so ``>=`` matches only instances that have ``due_date`` indexed.
_TASK_DUE_MIN = datetime(1, 1, 1, tzinfo=timezone.utc)


# @testable true
# @tests tests_unit/test_010_task_index.py::test_task_query_filter_uses_completed_status_not_active_status
# @features task-index
# @dimensions query-filter completed active
def _tasks_filter(project=None, model=None, hashes=None, completed=False):
    f = Filter().eq("type", "task").eq("active", True).eq("completed", completed)
    if model:
        f.eq("model", datastore_key(model))
    elif project:
        f.eq("project", datastore_key(project))
    if hashes is not None:
        f.requires(hashes)
    return f


# @testable false
# @reason task index query recipe is persistence-owned and covered by route/E2E workflows
def tasks(start_cursor=None, limit=25, **kwargs):
    """Fetch paginated task instances with optional model, project, and completion filters."""
    if Restriction.is_denied(kwargs.get("hashes")):
        return _empty_results()

    f = _tasks_filter(
        kwargs.get("project"),
        kwargs.get("model"),
        kwargs.get("hashes"),
        kwargs.get("completed", False),
    )

    q = Query(KINDS.instances).filter(f).order("-modified")
    if limit:
        q.limit(limit)
    if start_cursor:
        q.cursor(start_cursor)

    return q.fetch()


# @testable false
# @reason task index query recipe is persistence-owned and covered by route/E2E workflows
def tasks_with_due_dates(start_cursor=None, limit=25, **kwargs):
    """Paginate incomplete active tasks that have a due date, ordered soonest first."""
    if Restriction.is_denied(kwargs.get("hashes")):
        return _empty_results()

    f = _tasks_filter(
        kwargs.get("project"),
        kwargs.get("model"),
        kwargs.get("hashes"),
        kwargs.get("completed", False),
    )
    f.ge("due_date", _TASK_DUE_MIN)

    q = Query(KINDS.instances).filter(f).order("due_date")
    if limit:
        q.limit(limit)
    if start_cursor:
        q.cursor(start_cursor)

    return q.fetch()


# @testable false
# @reason task index query recipe is persistence-owned and covered by route/E2E workflows
def tasks_without_due_dates(start_cursor=None, limit=25, **kwargs):
    """Paginate tasks with no due date, most recently modified first."""
    if Restriction.is_denied(kwargs.get("hashes")):
        return _empty_results()

    f = _tasks_filter(
        kwargs.get("project"),
        kwargs.get("model"),
        kwargs.get("hashes"),
        kwargs.get("completed", False),
    )
    f.is_null("due_date")

    q = Query(KINDS.instances).filter(f).order("-modified")
    if limit:
        q.limit(limit)
    if start_cursor:
        q.cursor(start_cursor)

    return q.fetch()


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def page_tasks(page):
    """Fetch all tasks linked to, owned by, or assigned to a page."""
    f = Filter().any_of(
        Filter().eq("type", "task").eq("linked_pages", page.key),
        Filter().eq("type", "task").eq("page", page.key),
        Filter().eq("type", "task").eq("assigned_to", page.key),
    )

    return Query(KINDS.instances).filter(f).fetch_all()


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def page_tasks_with_history(page):
    """Fetch Task and TaskHistory rows whose owning ``page`` is this Page."""
    f = Filter().eq("type", "task").eq("page", page.key)
    tasks = Query(KINDS.instances).filter(f).fetch_all()

    h = Filter().eq("type", "task_history").eq("page", page.key)
    history = Query(KINDS.history).filter(h).fetch_all()

    return tasks + history


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def user_task_count(page):
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


# @testable false
# @reason home task query recipe is persistence-owned and covered by home/E2E workflows
def due_tasks(hashes=Restriction.UNRESTRICTED):
    """Fetch incomplete active tasks due within the next seven days."""
    if Restriction.is_denied(hashes):
        return []

    today = datetime.now(timezone.utc)
    next_week = today + timedelta(days=7)

    f = (
        Filter()
        .eq("type", "task")
        .eq("active", True)
        .eq("completed", False)
        .ge("due_date", _TASK_DUE_MIN)
        .le("due_date", next_week)
    )
    if hashes is not None:
        f.requires(hashes)

    return Query(KINDS.instances).filter(f).order("due_date").fetch_all()


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def task_history(task):
    """Fetch all history entries for a task."""
    return Query(KINDS.history).ancestor(task.key).fetch_all()


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::latest_history_submission
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def latest_task_history(task):
    """Fetch the most recent history entry for a task."""
    return Query(KINDS.history).ancestor(task.key).order("-created").fetch_one()


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def document_history(entity):
    """Fetch direct document-history children for an entity."""
    rows = (
        Query(KINDS.history)
        .ancestor(entity.key)
        .filter(Filter().eq("type", "document_history"))
        .fetch_all()
    )
    return [row for row in rows if row.key.parent == entity.key]


# --- Filters ---


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def filters(entity, user_key=None):
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


# @testable false
# @reason form index query recipe is persistence-owned and covered by route/E2E workflows
def forms(start_cursor=None, limit=25):
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


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def form_users(*forms):
    """Find categories and models that reference any of the given forms."""
    form_keys = {f.key for f in forms}
    f = Filter().any_of(
        Filter().eq("type", "category"),
        Filter().eq("type", "model"),
    )

    parents = []
    project_keys = set()
    for model in Query(KINDS.models).filter(f).fetch_iter():
        if model.get("form") not in form_keys and not bool(
            form_keys & set(model.get("forms", []))
        ):
            continue
        elif model.get("type") == "category":
            parents.append(model)
        elif model.get("type") == "model":
            parents.append(model)
            project_keys.add(model.key.parent)

    return parents + entities(list(project_keys))


# @testable false
# @reason datastore query recipe is persistence-owned and covered by route/E2E workflows
def form_instance_users(form_key):
    """Fetch all instances that reference a given form."""
    return Query(KINDS.instances).filter(Filter().eq("form", form_key)).fetch_all()


# --- Activity ---


# @testable true
# @tests tests_unit/test_002j_notes.py::test_activity_query_filters_requested_types
# @features activity
# @dimensions query ancestor type-order
def activity(parent, types=("note", "notification")):
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


# @testable true
# @tests tests_unit/test_002j_notes.py::test_home_notes_return_only_visible_notes
# @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_note_visibility_across_users
# @features notes permissions
# @dimensions home shared private owner ordering
def home_notes(user):
    """Fetch Home-scope notes visible to ``user``."""
    note_filter = Filter().eq("type", "note").eq("scope", "home")
    notes = (
        Query(KINDS.activity)
        .filter(note_filter)
        .order("-created")
        .fetch_all()
    )

    if not user.is_owner:
        user_key = datastore_key(user)
        notes = [
            note
            for note in notes
            if note.get("visibility") == "everyone"
            or note.get("user") == user_key
        ]

    return notes


# @testable false
# @covered-by lagniappe/core/tools/database/get.py::home_notes
# @reason compatibility alias keeps the Home property contract focused on notes
def notes(user):
    return home_notes(user)


# @testable false
# @covered-by lagniappe/web/routes/pages/notes.py::get_notes
# @reason page note query reuses the indexed ancestor activity recipe
def page_notes(page):
    """Fetch notes attached to a Page."""
    return activity(page, types="note")


# @testable false
# @covered-by lagniappe/core/mutations/delete.py::DeleteCollector.user_notes
# @reason user-deletion lookup is exercised through the delete mutation plan
def notes_by_user(user):
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


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_note_ingress_and_tool_lists_load_database_entities
# @features home ai-report
# @dimensions query list
def ai_reports(user_key):
    """Fetch AI report activity records belonging to a user."""
    return activity(user_key, types=("report",))
