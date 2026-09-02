from flask_login import LoginManager


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_login_manager_wiring_and_anonymous_redirect
# @matrix auth login : lazy-user-loading login-manager redirect-view
def initialize(app, *, manager_factory=LoginManager, user_loader=None):
    """Configure Flask-Login without its eager template context processor."""
    if user_loader is None:
        from lagniappe.core.entities import Entities

        user_loader = Entities.USER.load

    login_manager = manager_factory()
    # Jinja gets the lazy current_user proxy from start/jinja.py. Flask-Login's
    # context processor resolves the user for every rendered template, including
    # 404 pages, so skip it to keep user loads demand-driven.
    login_manager.init_app(app, add_context_processor=False)
    login_manager.login_view = "users.login"
    login_manager.user_loader(user_loader)
