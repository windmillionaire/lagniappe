"""Error handlers for HTTP, Datastore, and uncaught exceptions."""

from flask import make_response, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError
from lagniappe import CONFIG
from google.api_core.exceptions import GoogleAPIError
from jinja2.exceptions import TemplateError, TemplateNotFound
from werkzeug.exceptions import HTTPException

from lagniappe.core import exceptions


# @testable false
# @reason Flask error handler registration is exercised through E2E app boot and error-page behavior
def initialize(app):
    app.register_error_handler(GoogleAPIError, handle_datastore_error)
    app.register_error_handler(TemplateError, handle_template_error)
    app.register_error_handler(HTTPException, handle_http_error)
    app.register_error_handler(Exception, handle_exception)


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_csrf_exempt_surfaces_reach_replacement_authentication_gates
# @tests tests_e2e/001_site/test_001a_environment.py::test_error_handling
# @tests tests_e2e/001_site/test_001b_login.py::test_login_returns_to_requested_url_after_redirect
# @tests tests_e2e/001_site/test_001b_login.py::test_csrf_failure_is_identified_for_targeted_retry
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @matrix error-handling : csrf http-404
# @matrix agent-api : error-envelope routing
# @pair login:redirect-target
def handle_http_error(error):
    """Handle HTTP exceptions (4xx and 5xx errors)."""
    code = error.code if hasattr(error, "code") else 500

    if request.path == "/api" or request.path.startswith("/api/"):
        from lagniappe.web.routes.api.main import handle_api_http_error

        return handle_api_http_error(error)

    if isinstance(error, CSRFError):
        response = make_response(str(error.description))
        response.headers["Content-Type"] = "text/plain"
        response.headers["X-Lagniappe-CSRF"] = "invalid"
        return response, 400
    elif code == 401:
        target = None
        if request.method in {"GET", "HEAD"}:
            target = request.full_path if request.query_string else request.path
            session["next"] = target
        login_url = (
            url_for("users.login", next=target) if target else url_for("users.login")
        )
        return redirect(login_url)
    elif code == 422:
        response = make_response(str(error.description))
        response.headers["Content-Type"] = "text/plain"
        return response, 422

    return _handle_error_with_context(error, code=code, header_msg=f"Error {code}")


# @testable false
# @reason Datastore errors require live Google exceptions and rendered app context
def handle_datastore_error(error):
    """Handle Google Datastore/API errors."""
    if "index for this query is not ready to serve" in str(error).casefold():
        response, code = _handle_error_with_context(
            error,
            code=503,
            header_msg="Database setup is finishing",
            description=(
                "Lagniappe is deployed successfully, but Google Cloud is still "
                "building the Datastore indexes needed for this page. This "
                "normally resolves automatically within a few minutes. Wait a "
                "little, then refresh the page."
            ),
            transient=True,
            capture_error=False,
        )
        response.headers["Retry-After"] = "60"
        return response, code
    return _handle_error_with_context(error, code=500, header_msg="Google API Error")


# @testable false
# @reason Flask error handler wrappers are exercised through E2E error-page behavior
def handle_template_error(error):
    """Handle Jinja2 template errors."""
    return _handle_error_with_context(error, code=500, header_msg="Template Error")


# @testable false
# @reason Flask error handler wrappers are exercised through E2E error-page behavior
def handle_exception(error):
    """Handle uncaught exceptions."""
    return _handle_error_with_context(error, code=500, header_msg="Exception")


# @testable false
# @reason debug-context visibility is part of Flask error-page behavior exercised through E2E
def _should_show_debug():
    return CONFIG.local


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_error_handling
# @pair error-handling:error-page
def _handle_error_with_context(
    error,
    code=500,
    header_msg="Error",
    *,
    description=None,
    transient=False,
    capture_error=True,
):
    """Extract debug context, send to Sentry if enabled, render error template."""
    debug_context = exceptions.get_debug_context(error)

    if capture_error and CONFIG.capture_errors and code >= 500:
        exceptions.capture(error, debug_context)

    description = description or getattr(error, "description", str(error))

    if _should_show_debug():
        formatted = exceptions.format_debug_context_for_template(debug_context)
        template_context = {
            "description": description,
            "code": code,
            "debug": formatted,
            "show_debug": True,
            "header_msg": header_msg,
            "transient": transient,
        }
    else:
        template_context = {
            "description": description,
            "code": code,
            "show_debug": False,
            "header_msg": header_msg,
            "transient": transient,
        }

    try:
        html = render_template(f"errors/{code}.html", **template_context)
    except TemplateNotFound:
        html = render_template("errors/500.html", **template_context)

    response = make_response(html)
    response.headers["X-Lagniappe-Error"] = header_msg

    return response, code
