"""Versioned bearer-authenticated API for external planning agents."""

from flask import Blueprint


api = Blueprint("agent_api", __name__)

from . import main

__all__ = ["api"]
