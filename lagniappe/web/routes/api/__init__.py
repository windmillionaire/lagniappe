"""Versioned bearer-authenticated API for external planning agents."""

from flask import Blueprint


api = Blueprint("agent_api", __name__)
api_family = Blueprint("agent_api_family", __name__)

from . import main

__all__ = ["api", "api_family"]
