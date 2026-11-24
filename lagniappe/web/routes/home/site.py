from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities.entity import Entity
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import abort, render_template, request, session, g
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from config import read_saved_app_settings
from config.ai_settings import normalize_ai_settings
from config.deployment import normalize_deployment_settings
from config.public_pages import normalize_public_page_settings
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, collaboration
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.site import images as site_image
from lagniappe.core.tools.site import public_pages as public_page_service
from lagniappe.core.tools.services import places
from lagniappe.core.tools.ai.settings import runtime_ai_settings
from lagniappe.core.tools.database import site as site_database
from lagniappe.core.tools.database import migrations as database_migrations
from lagniappe.core.tools.site.admin import (
    load_ai_settings_payload,
    load_deployment_settings,
    run_site_updates,
)
from lagniappe.core.tools.site.cache_rebuild import rebuild_application_cache
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web.auth import (
    authenticated_user,
    clear_client_cache_invalidation,
    is_demo_guest_session,
    logged_in,
    owner_only,
    permission,
)
from lagniappe.core.exceptions import AISettingsError, DeploymentSettingsError

from . import home, internal


def _site_image_response(paths):
    return {
        k: v
        if (v.startswith("http://") or v.startswith("https://") or v.startswith("/"))
        else f"/images/{v}"
        for k, v in paths.items()
        if k not in {"version", "asset_generations"}
    }


def _administrator_payload():
    """Return the canonical Owner, additional Admins, and promotion choices."""
    rows = database_get.users(limit=None).results
    users = [
        user
        for user in Entities.fetch(*rows, request=Fetch.direct())
        if isinstance(user, Entities.USER) and not user.is_public
    ]
    owner_email = str(CONFIG.ADMIN_EMAIL or "").strip().casefold()
    owner = next(
        (
            user
            for user in users
            if str(user.email or "").strip().casefold() == owner_email
        ),
        None,
    )

    def role_entry(user, *, primary_owner=False):
        last_login = user.last_login if user else None
        if last_login is not None and hasattr(last_login, "isoformat"):
            last_login = last_login.isoformat()
        return {
            "key": user.urlsafe_key if user else None,
            "name": (user.name if user else CONFIG.ADMIN_NAME) or "Owner",
            "email": str((user.email if user else CONFIG.ADMIN_EMAIL) or ""),
            "last_login": last_login,
            "awaiting_first_sign_in": bool(primary_owner and not user),
            "is_owner": primary_owner,
        }

    additional = sorted(
        (role_entry(user) for user in users if user is not owner and user.is_admin),
        key=lambda entry: (
            str(entry["name"] or "").casefold(),
            str(entry["email"] or "").casefold(),
        ),
    )
    candidates = sorted(
        (role_entry(user) for user in users if user is not owner and not user.is_admin),
        key=lambda entry: (
            str(entry["name"] or "").casefold(),
            str(entry["email"] or "").casefold(),
        ),
    )
    return [role_entry(owner, primary_owner=True), *additional], candidates


def _installation_access_payload():
    """Return an Owner-safe view of saved operator and provider identities."""
    owner_email = str(getattr(CONFIG, "ADMIN_EMAIL", "") or "").strip().casefold()
    installer_email = str(
        getattr(CONFIG, "INSTALLER_EMAIL", "") or ""
    ).strip().casefold()
    deployer_email = str(
        getattr(CONFIG, "DEPLOYER_EMAIL", "") or ""
    ).strip().casefold()
    bootstrap_email = str(
        getattr(CONFIG, "BOOTSTRAP_ADMIN_EMAIL", "") or ""
    ).strip().casefold()
    delegated = bool(
        owner_email and installer_email and owner_email != installer_email
    )
    application_handoff_complete = bool(
        delegated and deployer_email == owner_email and not bootstrap_email
    )

    if application_handoff_complete:
        state = "application-complete"
        summary = "Owner is the saved deployer; installer bootstrap is closed"
    elif delegated:
        state = "pending"
        summary = "Delegated handoff is still pending"
    else:
        state = "owner-managed"
        summary = "Owner-managed installation"

    auth_email = getattr(CONFIG, "AUTH_EMAIL_CONFIG", None) or {}
    if not isinstance(auth_email, dict):
        auth_email = {}
    auth_service = str(auth_email.get("service") or "").strip()
    auth_sender = str(auth_email.get("senderEmail") or "").strip().casefold()
    auth_login = str(auth_email.get("username") or "").strip().casefold()
    installer_controls_auth_email = bool(
        installer_email
        and installer_email in {auth_sender, auth_login}
    )

    project_id = str(
        getattr(CONFIG, "GOOGLE_CLOUD_PROJECT", "") or ""
    ).strip()
    return {
        "state": state,
        "summary": summary,
        "delegated": delegated,
        "application_handoff_complete": application_handoff_complete,
        "project_id": project_id,
        "project_iam_url": (
            "https://console.cloud.google.com/iam-admin/iam"
            f"?project={project_id}"
        ),
        "owner_email": owner_email,
        "installer_email": installer_email,
        "deployer_email": deployer_email,
        "bootstrap_admin_email": bootstrap_email,
        "runtime_service_account": str(
            getattr(CONFIG, "RUNTIME_SERVICE_ACCOUNT_EMAIL", "") or ""
        ).strip().casefold(),
        "authentication_email": {
            "configured": bool(auth_email),
            "service": auth_service,
            "sender_email": auth_sender,
            "login": auth_login,
            "uses_installer": installer_controls_auth_email,
        },
    }


def _role_target(identifier):
    target = collaboration.resolve_user(identifier)
    if target:
        target = Entities.fetch_one(
            target.urlsafe_key,
            request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
        )
    if not isinstance(target, Entities.USER) or target.is_public:
        abort(404)
    if target.is_owner:
        abort(403)
    return target


@internal.route("/delete/<key>", methods=["GET"])
@permission(requested=Action.DELETE)
def delete(key: str, **kwargs: Unpack[EntityContext[Entity]]) -> ResponseReturnValue:
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    if not entity:
        return abort(404)

    return responses.delete_entity(entity)


@home.route("/offline", methods=["GET"])
def offline() -> ResponseReturnValue:
    g.NO_CACHE = True
    return responses.offline()


@internal.route("/rebuild-cache", methods=["POST"])
@permission(Resource.SITE)
def rebuild_cache() -> ResponseReturnValue:
    result = rebuild_application_cache()
    if not result.rebuilt:
        return responses.json_response(
            {"migration_status": result.migration_status},
            status=409,
        )
    return responses.json_response({"cache_status": result.cache_status})


@internal.route("/site-update", methods=["POST"])
@permission(Resource.SITE)
def site_update() -> ResponseReturnValue:
    migration_status = run_site_updates()
    status = 200 if migration_status["status"] == "current" else 409
    return responses.json_response(
        {"migration_status": migration_status},
        status=status,
    )


@internal.route("/site-settings", methods=["GET"])
@permission(Resource.SITE, no_store=True)
def site_settings() -> ResponseReturnValue:
    project_id = CONFIG.GOOGLE_CLOUD_PROJECT
    google_console_url = "https://console.cloud.google.com"

    # Generate list of service provider links
    links = [
        {
            "title": "Google Cloud Console",
            "url": f"{google_console_url}/home/dashboard?project={project_id}",
            "description": "Main GCP dashboard and project overview",
            "icon": "google",
        },
        {
            "title": "App Engine",
            "url": f"{google_console_url}/appengine?project={project_id}",
            "description": "Manage your App Engine application and deployments",
            "icon": "launch",
        },
        {
            "title": "Identity Platform",
            "url": f"{google_console_url}/customer-identity/providers?project={project_id}",
            "description": "Manage sign-in providers and user authentication",
            "icon": "security",
        },
        {
            "title": "Cloud Tasks",
            "url": f"{google_console_url}/cloudtasks?project={project_id}",
            "description": "Monitor and manage task queues",
            "icon": "checklist",
        },
        {
            "title": "Document AI",
            "url": f"{google_console_url}/ai/document-ai?project={project_id}",
            "description": "OCR processor management and settings",
            "icon": "fileText",
        },
        {
            "title": "OAuth Credentials",
            "url": f"{google_console_url}/apis/credentials?project={project_id}",
            "description": "Manage OAuth client ID for Google sign-in",
            "icon": "security",
        },
        {
            "title": "IAM & Service Accounts",
            "url": f"{google_console_url}/iam-admin/serviceaccounts?project={project_id}",
            "description": "Service account permissions and roles",
            "icon": "configuration",
        },
        {
            "title": "Cloud Storage",
            "url": f"{google_console_url}/storage/browser?project={project_id}",
            "description": "File storage buckets and uploads",
            "icon": "files",
        },
        {
            "title": "Billing",
            "url": f"{google_console_url}/billing?project={project_id}",
            "description": "Monitor costs, usage, and AI spending",
            "icon": "billing",
        },
        {
            "title": "Google Cloud APIs",
            "url": f"{google_console_url}/apis/dashboard?project={project_id}",
            "description": "Enabled APIs and usage quotas",
            "icon": "integration",
        },
        {
            "title": "Redis Cloud",
            "url": "https://app.redislabs.com/",
            "description": "Manage Redis instances and monitoring",
            "icon": "database",
        },
    ]

    account_id = CONFIG.CLOUDFLARE_ACCOUNT_ID
    root_domain = CONFIG.CUSTOM_DOMAIN
    if account_id and root_domain:
        cloudflare_url = f"https://dash.cloudflare.com/{account_id}/{root_domain}"
        description = f"DNS settings for {root_domain}"

        links.append(
            {
                "title": "Cloudflare DNS",
                "url": cloudflare_url,
                "description": description,
                "icon": "cloudflare",
            }
        )

    entity = site_database.image()
    site_image_response = _site_image_response(dict(entity)) if entity else None

    ai_settings, ai_model_options = (
        load_ai_settings_payload(config=CONFIG) if CONFIG.AI_ENABLED else ({}, {})
    )

    administrators, administrator_candidates = _administrator_payload()
    payload = {
        "ai_settings": ai_settings,
        "ai_model_options": ai_model_options,
        "deployment": load_deployment_settings(config=CONFIG),
        "site_image": site_image_response,
        "service_providers": links,
        "migration_status": database_migrations.get_migration_status(),
        "administrators": administrators,
        "administrator_candidates": administrator_candidates,
        "can_manage_administrators": current_user.is_owner,
        "can_view_sensitive_configuration": current_user.is_owner,
    }
    if current_user.is_owner:
        installation_access = _installation_access_payload()
        if installation_access["delegated"]:
            payload["installation_access"] = installation_access
    return responses.json_response(payload)


@internal.route("/site-administrators", methods=["POST"])
@owner_only
def promote_site_administrator() -> ResponseReturnValue:
    data = request.form if request.form else request.get_json(silent=True) or {}
    identifier = str(data.get("user_key") or data.get("key") or "").strip()
    if not identifier:
        return responses.error("Choose an existing managed user.")
    target = _role_target(identifier)
    if not target.is_admin:
        target.is_admin = True
        target.save()
    administrators, candidates = _administrator_payload()
    return responses.json_response(
        {
            "administrators": administrators,
            "administrator_candidates": candidates,
            "can_manage_administrators": True,
            "can_view_sensitive_configuration": True,
        }
    )


@internal.route("/site-administrators/<key>", methods=["GET", "DELETE"])
@owner_only
def demote_site_administrator(key: str) -> ResponseReturnValue:
    target = _role_target(key)
    if request.method == "GET":
        return render_template(
            "delete/site_administrator.html",
            administrator=target,
        )
    if target.is_admin:
        target.is_admin = False
        target.save()
    administrators, candidates = _administrator_payload()
    return responses.json_response(
        {
            "administrators": administrators,
            "administrator_candidates": candidates,
            "can_manage_administrators": True,
            "can_view_sensitive_configuration": True,
        }
    )


@internal.route("/set-deployment-settings", methods=["POST"])
@permission(Resource.SITE)
def set_deployment_settings() -> ResponseReturnValue:
    data = request.form if request.form else request.get_json(silent=True) or {}

    try:
        deployment = normalize_deployment_settings(data)
    except DeploymentSettingsError as e:
        return responses.error(str(e))

    site_database.save_deployment(deployment)
    return responses.json_response({"deployment": deployment})


@internal.route("/set-ai-settings", methods=["POST"])
@permission(Resource.SITE)
def set_ai_settings() -> ResponseReturnValue:
    if not CONFIG.AI_ENABLED:
        abort(403)
    data = request.form if request.form else request.get_json(silent=True) or {}
    current = runtime_ai_settings(config=CONFIG)
    _, model_options = load_ai_settings_payload(current, config=CONFIG)

    try:
        ai_settings = normalize_ai_settings(
            data,
            current_settings=current,
            model_options=model_options,
        )
    except AISettingsError as e:
        return responses.error(str(e))

    site_database.save_ai(ai_settings)
    if bool(ai_settings.get("AI_AUTO_EXECUTE", False)) != bool(
        current.get("AI_AUTO_EXECUTE", False)
    ):
        site_database.bump_fingerprint("home")
    return responses.json_response(
        {
            "ai_settings": ai_settings,
            "ai_model_options": model_options,
        }
    )


@internal.route("/site-settings/public-pages", methods=["GET", "POST"])
@permission(Resource.SITE, no_store=True)
def set_public_page_settings() -> ResponseReturnValue:
    current = public_page_service.runtime_settings(config=CONFIG)
    if request.method == "GET":
        return responses.json_response({"public_pages": current})

    data = request.form if request.form else request.get_json(silent=True) or {}
    try:
        settings = normalize_public_page_settings(
            data,
            current_settings=current,
        )
    except ValueError as error:
        return responses.error(str(error))

    site_database.save_public_pages(settings)
    cache.invalidate_public_discovery()
    return responses.json_response({"public_pages": settings})


@internal.route("/site-configuration", methods=["GET"])
@owner_only
def site_configuration() -> ResponseReturnValue:
    g.NO_CACHE = True
    return responses.site_configuration(read_saved_app_settings())


@internal.route("/set-site-image", methods=["POST"])
@permission(Resource.SITE)
def set_site_image() -> ResponseReturnValue:
    uploaded_file = (
        [f for f in request.files.values() if f.filename][0] if request.files else None
    )
    if not uploaded_file:
        uploaded_file = direct_uploads.direct_upload_file("site-image")

    if not uploaded_file:
        return responses.error("No file uploaded")
    try:
        paths = site_image.create_site_image(uploaded_file)
        site_image_response = _site_image_response(paths)
    except exceptions.SiteImageError as e:
        return responses.error(str(e))

    return responses.json_response({"site_image": site_image_response})


@internal.route("/set-site-image/direct-upload", methods=["POST"])
@permission(Resource.SITE)
def set_site_image_direct() -> ResponseReturnValue:
    return direct_uploads.direct_upload_response()


@internal.route("/ping")
def ping() -> ResponseReturnValue:
    g.NO_CACHE = True
    user_key = session.get(CONFIG.LOGIN_USER_KEY) if session.get("_user_id") else None
    if user_key:
        try:
            responses.publish_notification_state(
                cache.peek_notification_state(user_key)
            )
        except Exception as error:
            exceptions.capture(error, context={"operation": "notification-state-peek"})
    return "pong", 200


@home.route("/privacy-policy", methods=["GET"])
def privacy_policy() -> ResponseReturnValue:
    return responses.privacy_policy()


@home.route("/reporting_privacy", methods=["GET"])
def reporting_privacy() -> ResponseReturnValue:
    return responses.reporting_privacy()


@internal.route("/token")
def refresh_token() -> ResponseReturnValue:
    g.NO_CACHE = True
    return generate_csrf()


@internal.route("/identity-config")
def identity_config() -> ResponseReturnValue:
    g.NO_CACHE = True
    return responses.json_response(getattr(CONFIG, "IDENTITY_PLATFORM_CONFIG", {}))


@internal.route("/update-session", methods=["POST"])
@logged_in
def update_session() -> ResponseReturnValue:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return responses.error("Invalid session update.")

    timezone = None
    if "timezone" in data:
        timezone = data["timezone"].strip() if isinstance(data["timezone"], str) else ""
        try:
            if not timezone:
                raise ValueError("timezone is empty")
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            return responses.error("Invalid session update.")

    location = None
    if "location" in data:
        location = places.normalize_location_coordinates(data["location"])
        if location is None:
            return responses.error("Invalid session update.")

    save_user = False
    if timezone is not None:
        session["timezone"] = timezone
        if current_user.db.get("timezone") != timezone:
            current_user.db["timezone"] = timezone
            save_user = True

    if location is not None:
        session["location"] = json.dumps(location, separators=(",", ":"))

    if save_user and not is_demo_guest_session():
        # Startup requests may hold a snapshot from before a permission edit.
        Entities.save_root(authenticated_user(), property_mask=("timezone",))

    return responses.json_response({"userHash": current_user.hash})


@internal.route("/validate-user", methods=["POST"])
@logged_in
def validate_user() -> ResponseReturnValue:
    data = request.get_json(silent=True) or {}
    cache_cleared = (
        data.get("cacheCleared") is True and data.get("responseCacheCleared") is True
    )

    revision = data.get("cacheRevision")
    expected = session.get(CONFIG.LOGIN_INVALIDATE_CACHE_KEY)
    if cache_cleared and expected and revision != str(expected):
        cache_cleared = False
    if cache_cleared and is_demo_guest_session():
        clear_client_cache_invalidation()
        return responses.json_response({"cacheCleared": True, "retry": False})
    if cache_cleared and current_user.invalidate_cache:
        prefix = f"user:{current_user.urlsafe_key}:"
        cache_cleared = (
            isinstance(revision, str)
            and revision.startswith(prefix)
            and database_utility.acknowledge_user_cache(
                current_user.key, revision[len(prefix):]
            )
        )
    if cache_cleared:
        clear_client_cache_invalidation()
        current_user.invalidate_cache = False

    return responses.json_response({"cacheCleared": cache_cleared, "retry": not cache_cleared})
