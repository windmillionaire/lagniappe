import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import abort, request, session, g
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from config import SETTINGS
from config.ai_settings import normalize_ai_settings
from config.deployment import normalize_deployment_settings
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, collaboration
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.site import images as site_image
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
    clear_client_cache_invalidation,
    logged_in,
    owner_only,
    permission,
)
from lagniappe.core.exceptions import AISettingsError, DeploymentSettingsError

from . import home, internal


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::site_settings
# @covered-by lagniappe/web/routes/home/site.py::set_site_image
# @reason small response-shaping helper covered through site settings load and upload routes
def _site_image_response(paths):
    return {
        k: v
        if (v.startswith("http://") or v.startswith("https://") or v.startswith("/"))
        else f"/images/{v}"
        for k, v in paths.items()
        if k not in {"version", "asset_generations"}
    }


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_administrator_roster_and_owner_controls
# @matrix admin : managed-users roster
# @matrix owner : awaiting-first-sign-in role-controls
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

    # @testable false
    # @covered-by lagniappe/web/routes/home/site.py::_administrator_payload
    # @reason private roster row formatting is exercised through the payload owner
    def role_entry(user, *, primary_owner=False):
        last_login = user.last_login if user else None
        if hasattr(last_login, "isoformat"):
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


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::promote_site_administrator
# @covered-by lagniappe/web/routes/home/site.py::demote_site_administrator
# @reason target loading and role protection are exercised through both role endpoints
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


# @testable true
# @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_delete_cascades_dependents_assets_and_cache
# @pair entities:delete
@internal.route("/delete/<key>", methods=["GET"])
@permission(requested=Action.DELETE)
def delete(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    if not entity:
        return abort(404)

    return responses.delete_entity(entity)


# @testable true
# @tests tests_e2e/001_site/test_001d_offline.py::test_offline_indicator_toggles
# @pair offline:indicator
@home.route("/offline", methods=["GET"])
def offline():
    g.NO_CACHE = True
    return responses.offline()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_maintenance_update_and_cache_refresh_use_real_routes
# @matrix cache : current redis-connection
@internal.route("/rebuild-cache", methods=["POST"])
@permission(Resource.SITE)
def rebuild_cache():
    result = rebuild_application_cache()
    if not result.rebuilt:
        return responses.json_response(
            {"migration_status": result.migration_status},
            status=409,
        )
    return responses.ok()


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_maintenance_update_and_cache_refresh_use_real_routes
# @matrix admin : site-update success
@internal.route("/site-update", methods=["POST"])
@permission(Resource.SITE)
def site_update():
    migration_status = run_site_updates()
    status = 200 if migration_status["status"] == "current" else 409
    return responses.json_response(
        {"migration_status": migration_status},
        status=status,
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_requires_administrator
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_additional_admin_cannot_access_owner_configuration
# @matrix admin : admin-only metadata public-preview site-settings
@internal.route("/site-settings", methods=["GET"])
@permission(Resource.SITE)
def site_settings():
    g.NO_CACHE = True
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
    if entity:
        site_image_response = _site_image_response(dict(entity))
    else:
        site_image_response = None

    ai_settings, ai_model_options = load_ai_settings_payload(config=CONFIG)

    administrators, administrator_candidates = _administrator_payload()
    return responses.json_response(
        {
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
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_administrator_roster_and_owner_controls
# @pairs admin:promotion cache:cache-invalidation owner:owner-only
@internal.route("/site-administrators", methods=["POST"])
@owner_only
def promote_site_administrator():
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


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_administrator_roster_and_owner_controls
# @matrix admin : account-preservation demotion
# @pairs cache:cache-invalidation owner:owner-only
@internal.route("/site-administrators/<key>", methods=["DELETE"])
@owner_only
def demote_site_administrator(key):
    target = _role_target(key)
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


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_deployment_form_saves_and_updates_summary
# @matrix admin : deployment-settings metadata validation
@internal.route("/set-deployment-settings", methods=["POST"])
@permission(Resource.SITE)
def set_deployment_settings():
    data = request.form if request.form else request.get_json(silent=True) or {}

    try:
        deployment = normalize_deployment_settings(data)
    except DeploymentSettingsError as e:
        return responses.error(str(e))

    site_database.save_deployment(deployment)
    return responses.json_response({"deployment": deployment})


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_ai_form_saves_current_models_through_route
# @matrix admin : ai-settings validation
@internal.route("/set-ai-settings", methods=["POST"])
@permission(Resource.SITE)
def set_ai_settings():
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
    return responses.json_response(
        {
            "ai_settings": ai_settings,
            "ai_model_options": model_options,
        }
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_additional_admin_cannot_access_owner_configuration
# @matrix owner : configuration sensitive-configuration
# @pair admin:site-settings
@internal.route("/site-configuration", methods=["GET"])
@owner_only
def site_configuration():
    g.NO_CACHE = True
    return responses.site_configuration(SETTINGS.app_settings)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @matrix admin : generated-images metadata public-preview site-image-upload
@internal.route("/set-site-image", methods=["POST"])
@permission(Resource.SITE)
def set_site_image():
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


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::set_site_image
# @reason route permission mirrors the final site image upload endpoint
@internal.route("/set-site-image/direct-upload", methods=["POST"])
@permission(Resource.SITE)
def set_site_image_direct():
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_server_running
# @tests tests_e2e/001_site/test_001a_environment.py::test_ping_notification_state_is_redis_only_and_optional
# @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
# @tests tests_e2e/001_site/test_001d_offline.py::test_offline_poll_recovers_without_online_event
# @matrix notifications : ping redis-projection
# @pairs offline:server-health server:initialization web-headers:notification-state
@internal.route("/ping")
def ping():
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


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_privacy_policy_is_public
# @matrix privacy public-pages : anonymous-access document-load
@home.route("/privacy-policy", methods=["GET"])
def privacy_policy():
    return responses.privacy_policy()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_reporting_privacy_notice_is_public
# @matrix error-reporting privacy public-pages : anonymous-access document-load maintainer-destination
@home.route("/reporting_privacy", methods=["GET"])
def reporting_privacy():
    return responses.reporting_privacy()


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_sets_hardened_auth_cookies
# @pair login:remember-cookie
@internal.route("/token")
def refresh_token():
    g.NO_CACHE = True
    return generate_csrf()


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_page_loads
# @matrix login : form-state page-load
@internal.route("/identity-config")
def identity_config():
    g.NO_CACHE = True
    return responses.json_response(getattr(CONFIG, "IDENTITY_PLATFORM_CONFIG", {}))


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_sets_hardened_auth_cookies
# @tests tests_e2e/001_site/test_001a_environment.py::test_update_session_rejects_invalid_timezone_and_location_atomically
# @matrix location session timezone : atomic-update coordinates validation
# @pair login:remember-cookie
@internal.route("/update-session", methods=["POST"])
@logged_in
def update_session():
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

    if save_user:
        current_user.save()

    return responses.json_response({"userHash": current_user.hash})


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_reassign_and_remove_user_from_page
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_submit_preserves_attached_form_and_categories
# @tests tests_e2e/001_site/test_001b_login.py::test_switching_session_user_requests_client_cache_invalidation
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_clears_session_and_returns_login
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_flags_user_cache_invalidation
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_ai_access_tiers_gate_tool_routes
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_ask_access_can_read_create_report_without_create_actions
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_requires_administrator
# @pair cache:invalidation-acknowledgement
@internal.route("/validate-user", methods=["POST"])
@logged_in
def validate_user():
    data = request.get_json(silent=True) or {}
    cache_cleared = (
        data.get("cacheCleared") is True and data.get("responseCacheCleared") is True
    )

    if cache_cleared:
        clear_client_cache_invalidation()
        if current_user.invalidate_cache:
            current_user.invalidate_cache = False
            current_user.save()

    return responses.json_response({"cacheCleared": cache_cleared})
