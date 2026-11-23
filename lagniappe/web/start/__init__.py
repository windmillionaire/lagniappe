"""Initialize services on the process-global Flask application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from flask_wtf.csrf import CSRFProtect

def initialize_app(app: Flask, csrf: CSRFProtect) -> None:
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
    from lagniappe.core.tools.experiments import bootstrap
    bootstrap()

    jinja.initialize(app)
    errors.initialize(app)
    blueprints.initialize(app, csrf)
    login.initialize(app)


__all__ = ["initialize_app"]
