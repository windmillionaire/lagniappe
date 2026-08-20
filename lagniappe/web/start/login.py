from flask_login import LoginManager


# @testable false
# @reason Flask-Login registration is exercised through E2E app boot; unit coverage would require request/app scaffolding
def initialize(app):
    from lagniappe.core.entities import Entities

    login_manager = LoginManager()
    # Jinja gets the lazy current_user proxy from start/jinja.py. Flask-Login's
    # context processor resolves the user for every rendered template, including
    # 404 pages, so skip it to keep user loads demand-driven.
    login_manager.init_app(app, add_context_processor=False)
    login_manager.login_view = "users.login"
    login_manager.user_loader(Entities.USER.load)
