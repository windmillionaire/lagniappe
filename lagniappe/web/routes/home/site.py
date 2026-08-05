import json

from flask import abort, request, session, g
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from config import SETTINGS
from config.ai_settings import normalize_ai_settings
from config.deployment import normalize_deployment_settings
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, database, site_image
from lagniappe.core.tools.ai_settings import runtime_ai_settings
from lagniappe.core.tools.database import migrations as database_migrations
from lagniappe.core.tools.site_admin import (
    load_ai_settings_payload,
    load_deployment_settings,
    rebuild_application_cache,
    run_site_updates,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web.auth import clear_client_cache_invalidation, logged_in, permission
from lagniappe.core.exceptions import AISettingsError, DeploymentSettingsError

from . import home


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
        if k != "version"
    }


# @testable true
# @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_delete_cascades_dependents_assets_and_cache
@home.route("/delete/<key>", methods=["GET"])
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
# @features offline
# @dimensions indicator
@home.route("/offline", methods=["GET"])
def offline():
    g.NO_CACHE = True
    return responses.offline()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_maintenance_update_and_cache_refresh_use_real_routes
# @pairs cache:redis-connection cache:current
@home.route("/rebuild-cache", methods=["POST"])
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
# @pairs admin:site-update admin:success
@home.route("/site-update", methods=["POST"])
@permission(Resource.SITE)
def site_update():
    migration_status = run_site_updates()
    status = 200 if migration_status["status"] == "current" else 409
    return responses.json_response(
        {"migration_status": migration_status},
        status=status,
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_is_owner_only
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @features admin
# @dimensions site-settings owner-only public-preview metadata
@home.route("/site-settings", methods=["GET"])
@permission(Resource.SITE)
def site_settings():
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

    entity = database.get.site_image()
    if entity:
        site_image_response = _site_image_response(dict(entity))
    else:
        site_image_response = None

    ai_settings, ai_model_options = load_ai_settings_payload(config=CONFIG)

    return responses.json_response(
        {
            "ai_settings": ai_settings,
            "ai_model_options": ai_model_options,
            "deployment": load_deployment_settings(config=CONFIG),
            "site_image": site_image_response,
            "service_providers": links,
            "migration_status": database_migrations.get_migration_status(),
        }
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_deployment_form_saves_and_updates_summary
# @features admin
# @dimensions deployment-settings metadata validation
@home.route("/set-deployment-settings", methods=["POST"])
@permission(Resource.SITE)
def set_deployment_settings():
    data = request.form if request.form else request.get_json(silent=True) or {}

    try:
        deployment = normalize_deployment_settings(data)
    except DeploymentSettingsError as e:
        return str(e), 422

    database.save_site_deployment(deployment)
    return responses.json_response({"deployment": deployment})


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_ai_form_saves_current_models_through_route
# @features admin
# @dimensions ai-settings validation
@home.route("/set-ai-settings", methods=["POST"])
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
        return str(e), 422

    database.save_site_ai(ai_settings)
    return responses.json_response(
        {
            "ai_settings": ai_settings,
            "ai_model_options": model_options,
        }
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
# @features admin
# @dimensions configuration-modal environment-variables
@home.route("/site-configuration", methods=["GET"])
@permission(Resource.SITE)
def site_configuration():
    g.NO_CACHE = True
    return responses.site_configuration(SETTINGS.app_settings)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @features admin
# @dimensions site-image-upload generated-images public-preview metadata
@home.route("/set-site-image", methods=["POST"])
@permission(Resource.SITE)
def set_site_image():
    uploaded_file = (
        [f for f in request.files.values() if f.filename][0] if request.files else None
    )
    if not uploaded_file:
        uploaded_file = direct_uploads.direct_upload_file("site-image")

    if not uploaded_file:
        return "No file uploaded", 422
    try:
        paths = site_image.create_site_image(uploaded_file)
        site_image_response = _site_image_response(paths)
    except exceptions.SiteImageError as e:
        return str(e), 422

    return responses.json_response({"site_image": site_image_response})


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::set_site_image
# @reason route permission mirrors the final site image upload endpoint
@home.route("/set-site-image/direct-upload", methods=["POST"])
@permission(Resource.SITE)
def set_site_image_direct():
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_server_running
# @tests tests_e2e/001_site/test_001a_environment.py::test_ping_notification_state_is_redis_only_and_optional
# @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
# @tests tests_e2e/001_site/test_001d_offline.py::test_offline_poll_recovers_without_online_event
# @pairs notifications:ping notifications:redis-projection
# @pair web-headers:notification-state
@home.route("/ping")
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
# @features privacy public-pages
# @dimensions anonymous-access document-load
@home.route("/privacy-policy", methods=["GET"])
def privacy_policy():
    return responses.privacy_policy()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_reporting_privacy_notice_is_public
# @features privacy public-pages error-reporting
# @dimensions anonymous-access document-load maintainer-destination
@home.route("/reporting_privacy", methods=["GET"])
def reporting_privacy():
    return responses.reporting_privacy()


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_sets_hardened_auth_cookies
@home.route("/token")
def refresh_token():
    g.NO_CACHE = True
    return generate_csrf()


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_page_loads
# @features login
# @dimensions page-load form-state
@home.route("/identity-config")
def identity_config():
    g.NO_CACHE = True
    return responses.json_response(getattr(CONFIG, "IDENTITY_PLATFORM_CONFIG", {}))


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_sets_hardened_auth_cookies
@home.route("/update-session", methods=["POST"])
@logged_in
def update_session():
    if request.json.get("timezone"):
        tz = request.json.get("timezone")
        session["timezone"] = tz
        if current_user.db.get("timezone") != tz:
            current_user.db["timezone"] = tz
            current_user.save()

    if request.json.get("location"):
        session["location"] = json.dumps(request.json.get("location"))

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
# @features cache
# @dimensions invalidation-acknowledgement
@home.route("/validate-user", methods=["POST"])
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
