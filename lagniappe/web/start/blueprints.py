"""Register all route blueprints with their URL prefixes."""


# @testable false
# @reason Flask blueprint registration is exercised through E2E app boot; unit coverage would require route import scaffolding
def initialize(app, csrf):
    from lagniappe import CONFIG
    from lagniappe.web.routes import home, internal
    from lagniappe.web.routes import projects
    from lagniappe.web.routes import files
    from lagniappe.web.routes import categories
    from lagniappe.web.routes import forms
    from lagniappe.web.routes import users
    from lagniappe.web.routes import pages
    from lagniappe.web.routes import tasks
    from lagniappe.web.routes import tools
    from lagniappe.web.routes import process
    from lagniappe.web.routes import manual
    from lagniappe.web.routes import reference
    from lagniappe.web.routes import filters
    from lagniappe.web.routes import assets
    from lagniappe.web.routes import testing

    app.register_blueprint(home)
    app.register_blueprint(internal, url_prefix="/l")
    app.register_blueprint(projects, url_prefix="/projects")
    app.register_blueprint(files, url_prefix="/files")
    app.register_blueprint(categories, url_prefix="/categories")
    app.register_blueprint(forms, url_prefix="/forms")
    app.register_blueprint(users, url_prefix="/users")
    app.register_blueprint(pages, url_prefix="/pages")
    app.register_blueprint(tasks, url_prefix="/tasks")
    app.register_blueprint(tools, url_prefix="/tools")
    app.register_blueprint(process, url_prefix="/process")
    app.register_blueprint(manual, url_prefix="/manual")
    app.register_blueprint(reference, url_prefix="/reference")
    app.register_blueprint(filters, url_prefix="/filters")
    app.register_blueprint(assets, url_prefix="/assets")
    app.register_blueprint(testing, url_prefix="/testing")
    if getattr(CONFIG, "ANALYTICS", False) or getattr(
        CONFIG,
        "AI_OBSERVABILITY",
        False,
    ):
        from lagniappe.web.routes import analytics

        app.register_blueprint(analytics, url_prefix="/analytics")
    csrf.exempt(process)
