"""Route authorization decorators.

Permission decorators normally follow this pattern:
1. Check authentication (401 if not logged in)
2. Load the entity from the URL key (404 if missing)
3. Set g.fingerprint for ETag caching on GET requests
4. Check permission (403 if denied)
5. Return 304 if unchanged, otherwise pass the loaded entity via ``entity=`` kwarg

Routes declared ``no_store=True`` set the response cache policy before loading
authorization context and skip ETag handling entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from flask import Request
    from flask.typing import ResponseReturnValue
    from google.cloud.datastore import Key
    from lagniappe.core.definitions import Resource
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity

from typing import Protocol, TypedDict, cast, overload


import hashlib
import os
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for
from flask_login import current_user

from lagniappe import CONFIG
from uuid import uuid4
from lagniappe.core.definitions import AI, Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.measurements import timed
from lagniappe.core.tools.polling.projections import channel_paths, channel_revisions

LOGIN_USER_KEY = CONFIG.LOGIN_USER_KEY
LOGIN_USER_PAGE_KEY = CONFIG.LOGIN_USER_PAGE_KEY
LOGIN_INVALIDATE_CACHE_KEY = CONFIG.LOGIN_INVALIDATE_CACHE_KEY
LOGIN_DEMO_GUEST_KEY = CONFIG.LOGIN_DEMO_GUEST_KEY
AUTH_SESSION_CACHE_KEYS = CONFIG.AUTH_SESSION_CACHE_KEYS


def is_demo_guest_email(email: object) -> bool:
    """Return True when ``email`` matches the configured read-only demo guest."""
    configured = str(getattr(CONFIG, "DEMO_GUEST_EMAIL", "") or "").strip().casefold()
    candidate = str(email or "").strip().casefold()
    return bool(configured and candidate and candidate == configured)


def is_demo_guest_session() -> bool:
    """Return True when the active browser session belongs to the read-only demo guest."""
    if session.get(LOGIN_DEMO_GUEST_KEY):
        return True
    return is_demo_guest_email(session.get("_user_id"))


class _AuthenticationDecorator(Protocol):
    def __call__[**P, T](self, view: Callable[P, T], /) -> Callable[P, T]: ...


class _PermissionDecorator(Protocol):
    def __call__[**P](
        self, view: Callable[P, ResponseReturnValue], /
    ) -> Callable[P, ResponseReturnValue]: ...


class EntityContext[T](TypedDict):
    """Entity keyword supplied by the permission decorator for a keyed route."""

    entity: T


def authenticated_user() -> models.User:
    user = current_user._get_current_object()
    if not isinstance(user, Entities.USER):
        abort(401)
    return user


def load_route_entity[T: Entity](entity: T, *, request: Fetch) -> T:
    loaded = Entities.fetch_one(entity, request=request)
    if loaded is None:
        abort(404)
    return loaded


def verify_google_csrf(response: Request) -> None:
    """Verify Google's double-submit CSRF token (cookie vs. body)."""
    csrf_token_cookie = response.cookies.get("g_csrf_token")
    if not csrf_token_cookie:
        abort(400, "Google: No CSRF token in Cookie.")

    csrf_token_body = response.form.get("g_csrf_token")
    if not csrf_token_body:
        csrf_token_body = response.get_json(silent=True)
        if csrf_token_body:
            csrf_token_body = csrf_token_body.get("g_csrf_token")

    if not csrf_token_body:
        abort(400, "Google: No CSRF token in post body.")

    if csrf_token_cookie != csrf_token_body:
        abort(400, "Google: Failed to verify double submit cookie.")


def _etag_fingerprint(base_fingerprint, user):
    """Hash resource, deployment, frontend build, and viewer authorization."""
    authorization = getattr(user, "authorization_fingerprint", None)
    if authorization is None:
        authorization = user.permissions_fingerprint
    deployment_id = (
        os.environ.get("GAE_DEPLOYMENT_ID")
        or os.environ.get("GAE_VERSION")
        or CONFIG.VERSION
    )
    value = (
        f"{base_fingerprint}-{deployment_id}-{CONFIG.BUILD_ID}-{authorization}"
    )
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _fingerprint_matches_etag():
    """Check if the client's If-None-Match header matches the current fingerprint."""
    if session.get(LOGIN_INVALIDATE_CACHE_KEY):
        # A 304 would merge a transient invalidation command into an older body.
        return False
    if not getattr(g, "fingerprint", None):
        return False
    if request.headers.get("Range"):
        return False

    cached = request.headers.get("If-None-Match")
    if cached:
        expected_value = str(g.fingerprint)
        for candidate in cached.split(","):
            cached_value = candidate.strip().removeprefix("W/").strip('"')
            if cached_value == expected_value:
                return True

    return False


def clear_login_session() -> None:
    """Clear request-auth helper keys and derived permission caches."""
    for key in AUTH_SESSION_CACHE_KEYS:
        session.pop(key, None)


def request_client_cache_invalidation(
    user: models.User | None = None, persist_user: bool = False
) -> None:
    """Mark this session response as requiring a client response-cache clear."""
    if user is not None and persist_user:
        user.invalidate_cache = True
        user.save()
    session[LOGIN_INVALIDATE_CACHE_KEY] = (
        f"user:{user.urlsafe_key}:{user.db.get('cache_invalidation_revision', 'legacy')}"
        if user is not None and user.invalidate_cache
        else f"session:{uuid4().hex}"
    )


def clear_client_cache_invalidation() -> None:
    """Clear the session flag once the client confirms its cache was wiped."""
    session.pop(LOGIN_INVALIDATE_CACHE_KEY, None)


def login_cache_invalidation_required(user: models.User) -> bool:
    """Return True when login is switching an existing session to another user."""
    session_user_key = session.get(LOGIN_USER_KEY)
    if session_user_key:
        return session_user_key != user.urlsafe_key

    session_user_id = session.get("_user_id")
    if session_user_id:
        return session_user_id != user.get_id()

    return False


def seed_login_session(user: models.User, invalidate_cache: bool = False) -> None:
    """Store direct entity keys for faster auth loads on later requests."""
    clear_login_session()

    if not getattr(user, "is_authenticated", False):
        return

    session[LOGIN_USER_KEY] = user.urlsafe_key
    session[LOGIN_USER_PAGE_KEY] = user.page.urlsafe_key
    if is_demo_guest_email(getattr(user, "email", "")):
        session[LOGIN_DEMO_GUEST_KEY] = True
    if invalidate_cache or getattr(user, "invalidate_cache", False):
        request_client_cache_invalidation(user)



def abort_public_user_action() -> None:
    """Reject actions that public users may not invoke despite edit access."""
    if getattr(current_user, "is_public", False):
        abort(403)


def require_ai_access(required: AI) -> None:
    """Reject a request unless the current user has the required AI tier."""
    if not getattr(current_user, "access", lambda _required: False)(required):
        abort(403)


def ai_access(required: AI) -> _AuthenticationDecorator:
    """Authorize an AI-only route before invoking its handler."""
    if not isinstance(required, AI) or required is AI.NONE:
        raise ValueError("AI route access requires ASK or CREATE.")

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user, _entity = _load_request_context()
            if not user.is_authenticated:
                abort(401)
            require_ai_access(required)
            return f(*args, **kwargs)

        return wrapped

    return decorator


def _session_protection_failed():
    login_manager = getattr(current_app, "login_manager", None)
    if not login_manager:
        return False

    failed = login_manager._session_protection_failed()
    if failed:
        login_manager._update_request_context_with_user()
    return failed


def _load_session_user_context(entity_identifier=None, *, context_keys=(), context_entity_keys=()):
    if not session.get("_user_id"):
        clear_login_session()
        return None, None

    if _session_protection_failed():
        clear_login_session()
        return None, None

    user_identifier = session.get(LOGIN_USER_KEY)
    user_page_identifier = session.get(LOGIN_USER_PAGE_KEY)
    if not user_identifier or not user_page_identifier:
        return None, None

    identifiers = (user_identifier, user_page_identifier, entity_identifier, *context_entity_keys)
    if context_keys:
        # Route-specific raw revision records share the root lookup. Only
        # entity rows enter the typed loader; relations still load normally.
        root_keys = {key for value in identifiers if (key := database_get.datastore_key(value)) is not None}
        records = database_get.entities(list(root_keys | set(context_keys)))
        g.request_context_records = {
            row.key: row for row in records if row.key in context_keys
        }
        identifiers = tuple(row for row in records if row.key in root_keys)
    loaded = Entities.fetch(*identifiers, request=Fetch.direct())
    user = next(
        (
            entity
            for entity in loaded
            if isinstance(entity, Entities.USER)
            and entity.urlsafe_key == user_identifier
        ),
        None,
    )
    entity = next(
        (
            entity
            for entity in loaded
            if entity_identifier and entity.urlsafe_key == entity_identifier
        ),
        None,
    )
    user_email = user.db.get("email") if isinstance(user, Entities.USER) else None
    if user is None or not user_email or str(user_email) != session.get("_user_id"):
        clear_login_session()
        return None, None

    canonical_page_identifier = database_get.urlsafe_key(user.db.get("page"))
    if canonical_page_identifier != user_page_identifier:
        clear_login_session()
        return None, None

    if context_entity_keys:
        g.request_context_entities = {entity.urlsafe_key: entity for entity in loaded}
    g._login_user = user
    if user.invalidate_cache:
        request_client_cache_invalidation(user)
    return current_user, entity


@timed("auth", "context")
def _load_request_context(entity_identifier=None, *, context_keys=(), context_entity_keys=()):
    user, entity = _load_session_user_context(
        entity_identifier, context_keys=context_keys, context_entity_keys=context_entity_keys,
    )
    if not user:
        # A stale session preload must not supply validation state for the
        # fallback identity. Its route resolves revisions normally instead.
        g.pop("request_context_records", None)
        g.pop("request_context_entities", None)
        user = current_user
        if user.is_authenticated:
            seed_login_session(authenticated_user())

        entity = (
            Entities.fetch_one(entity_identifier, request=Fetch.direct())
            if entity_identifier else None
        )

    if user.is_authenticated:
        if isinstance(entity, (Entities.TASK, Entities.FILE)):
            Entities.fetch(
                entity,
                request=Fetch.nested(
                    because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
                ),
            )
        elif isinstance(entity, Entities.TASK_HISTORY):
            Entities.fetch(
                entity.task,
                request=Fetch.nested(
                    because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION,
                ),
            )
    return user, entity


def permission[T](
    resource: Resource | None = None,
    requested: Action | None = None,
    *,
    no_store: bool = False,
    fingerprint: Callable[[T, models.User], str | None] | None = None,
    context_keys: Callable[[], Sequence[Key]] | None = None,
) -> _PermissionDecorator:
    """Check route access and optionally use a route-specific revision resolver."""

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if no_store:
                g.NO_CACHE = True
            user, entity = _load_request_context(
                kwargs.get("key"),
                context_keys=context_keys() if context_keys and request.method == "GET" else (),
            )
            if not user.is_authenticated:
                abort(401)
            elif not resource and not kwargs.get("key"):
                abort(403)

            allowed = False

            if kwargs.get("key") and not entity:
                abort(404)

            if request.method == "GET" and not no_store:
                base_fingerprint = (
                    fingerprint(cast("T", entity), cast("models.User", user)) if fingerprint else (
                        entity.fingerprint if entity
                        else database_utility.site_fingerprint(request.path)
                    )
                )
                g.fingerprint = _etag_fingerprint(base_fingerprint, user)

            if entity and requested is not None:
                allowed = entity.allowed(requested, user)
            elif resource is not None:
                allowed = user.has_permission(resource, requested or Action.ALL)

            if not allowed:
                abort(403)

            if (
                request.method == "GET"
                and not no_store
                and _fingerprint_matches_etag()
            ):
                return "", 304

            if entity:
                return f(*args, entity=entity, **kwargs)

            return f(*args, **kwargs)

        return wrapped

    return decorator

def home_permission(
    *,
    anonymous_endpoint: str | None = None,
    poll_channels: Callable[[str | None], tuple[str, ...]] | None = None,
    context_keys: Callable[[], Sequence[Key]] | None = None,
) -> _PermissionDecorator:
    """Authenticate Home reads and share their revision keys with the session lookup."""

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            remember_cookie = current_app.config.get(
                "REMEMBER_COOKIE_NAME",
                "remember_token",
            )
            if (
                anonymous_endpoint
                and not session.get("_user_id")
                and not request.cookies.get(remember_cookie)
            ):
                return redirect(url_for(anonymous_endpoint))

            kind = kwargs.get("kind")
            channels = poll_channels(kind) if poll_channels else ()
            paths = tuple(path for channel in channels for path in channel_paths(channel))
            if channels and request.method == "GET" and kind != "starred":
                paths = (request.path, *paths)
            keys = (
                database_utility.site_fingerprint_keys(paths)
                if paths and session.get(LOGIN_USER_KEY) else {}
            )
            lookup_keys = set(keys.values())
            if keys and context_keys and request.method == "GET":
                lookup_keys.update(context_keys())
            user, _entity = _load_request_context(context_keys=tuple(lookup_keys))
            if not user.is_authenticated:
                if anonymous_endpoint:
                    return redirect(url_for(anonymous_endpoint))
                abort(401)

            # Both the ETag and polling revisions describe the same pre-render snapshot.
            fingerprints = database_utility.site_fingerprints(
                paths, records=g.get("request_context_records"),
            ) if paths else {}
            if request.method == "GET":
                if kind == "starred":
                    base_fingerprint = user.modified.timestamp()
                else:
                    site_fingerprint = (
                        fingerprints.get(request.path) if channels
                        else database_utility.site_fingerprint(request.path)
                    )
                    user_fingerprint = user.modified.timestamp()
                    base_fingerprint = f"{site_fingerprint}:{user_fingerprint}"

                g.fingerprint = _etag_fingerprint(base_fingerprint, user)

                if _fingerprint_matches_etag():
                    return "", 304

            if channels:
                kwargs["poll_revisions"] = channel_revisions(
                    channels, authenticated_user(), fingerprint_loader=lambda _: fingerprints,
                )

            return f(*args, **kwargs)

        return wrapped

    return decorator


@overload
def logged_in[**P, T](
    f: Callable[P, T], *, context: Callable[[], Mapping[str, object]] | None = None,
) -> Callable[P, T]: ...


@overload
def logged_in(
    f: None = None, *, context: Callable[[], Mapping[str, object]] | None = None,
) -> _AuthenticationDecorator: ...


def logged_in[**P, T](
    f: Callable[P, T] | None = None,
    *,
    context: Callable[[], Mapping[str, object]] | None = None,
) -> Callable[P, T] | _AuthenticationDecorator:
    """Authenticate, optionally sharing a bounded route preload with auth roots."""
    if f is None:
        return lambda function: logged_in(function, context=context)

    @wraps(f)
    def wrapped(*args, **kwargs):
        user, _entity = _load_request_context(**(context() if context else {}))
        if not user.is_authenticated:
            abort(401)

        return f(*args, **kwargs)

    return wrapped


def owner_only[**P, T](f: Callable[P, T]) -> Callable[P, T]:
    """Require the configured primary Owner, not an additional Admin."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        user, _entity = _load_request_context()
        if not user.is_authenticated:
            abort(401)
        if not getattr(user, "is_owner", False):
            abort(403)
        return f(*args, **kwargs)

    return wrapped


def manual_permission() -> _AuthenticationDecorator:
    """Permission for the user manual. Public if CONFIG.PUBLIC_MANUAL is set."""

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if CONFIG.PUBLIC_MANUAL:
                return f(*args, **kwargs)

            user, _entity = _load_request_context()
            if user.is_authenticated:
                return f(*args, **kwargs)
            abort(401)

        return wrapped

    return decorator
