"""Initialize services on the process-global Flask application."""


# @testable false
# @reason Flask app startup is exercised through E2E app boot; unit coverage would require broad Flask/import scaffolding
def initialize_app(app, csrf):
    """Initialize persistence, AI, entities, templates, errors, routes, and login."""
    from lagniappe.core.tools import ai, cache
    from lagniappe.core.tools.database import utility as database_utility
    from lagniappe.core.tools.database import migrations
    from lagniappe.core import entities
    from . import blueprints, errors, jinja, login

    cache.initialize()
    fresh_install = database_utility.initialize()
    migrations.initialize_fresh_install(fresh_install)

    ai.initialize()
    entities.initialize()

    jinja.initialize(app)
    errors.initialize(app)
    blueprints.initialize(app, csrf)
    login.initialize(app)


__all__ = ["initialize_app"]
