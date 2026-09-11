"""Explicitly opt-in ChatGPT OAuth and discovery blueprints."""

from flask import Blueprint

oauth = Blueprint("oauth", __name__)
oauth_metadata = Blueprint("oauth_metadata", __name__)

from . import main

__all__ = ["oauth", "oauth_metadata"]
